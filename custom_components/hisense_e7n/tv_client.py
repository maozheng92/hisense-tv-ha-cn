"""Local VIDAA MQTT client for Hisense E7N Pro.

Talks to the TV's own broker on TCP 36669 (MQTT 3.1.1 over TLS).
No Hisense cloud, no extra Mosquitto bridge.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import ssl
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import paho.mqtt.client as mqtt

from . import topics
from .apps import normalize_apps
from .certs_util import build_ssl_context
from .const import (
    DEFAULT_PORT,
    DEFAULT_SOURCE_KEY_DELAY,
    MQTT_CONNACK_WAIT,
    MQTT_CONNECT_TIMEOUT,
    MQTT_DISCONNECT_GRACE,
    MQTT_KEEPALIVE,
    RC_TCP_FAILED,
    RC_TLS_FAILED,
    REMOTER_READY_POLL,
    REMOTER_READY_TIMEOUT,
    SOURCE_MENU_SETTLE,
    SOURCE_OPEN_RETRIES,
    SOURCE_OPEN_RETRY_DELAY,
    VOLUME_CEC_GAP,
    VOLUME_KEY_IDLE_WARMUP,
    VOLUME_KEY_PAUSE,
    VOLUME_TYPE_ARC,
    VOLUME_TYPE_MUTE,
    VOLUME_TYPE_TV,
    VOLUME_UNKNOWN_FLOOR_STEPS,
)
from .credentials import (
    MqttCredentials,
    credentials_for_mode,
    generate_dynamic_credentials,
    normalize_uuid,
    with_access_token,
)
from .keys import (
    KEY_MUTE,
    KEY_POWER,
    KEY_SOURCE,
    KEY_VOLUMEDOWN,
    KEY_VOLUMEUP,
    normalize_key,
)
from .local_http import (
    capture_screen,
    is_android_package,
    launch_local_app,
    push_voice,
    remoter_reachable,
    send_local_key,
)

_LOGGER = logging.getLogger(__name__)

CONNECT_PAYLOAD = {
    "app_version": 2,
    "connect_result": 0,
    "device_type": "Mobile App",
}


def _paho_client(client_id: str) -> mqtt.Client:
    callback_api = getattr(mqtt, "CallbackAPIVersion", None)
    if callback_api is not None:
        try:
            return mqtt.Client(
                callback_api_version=callback_api.VERSION1,
                client_id=client_id,
                protocol=mqtt.MQTTv311,
                clean_session=True,
            )
        except (TypeError, ValueError):
            return mqtt.Client(
                callback_api_version=callback_api.VERSION2,
                client_id=client_id,
                protocol=mqtt.MQTTv311,
            )
    return mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311, clean_session=True)


def _rc_failed(reason_code: Any) -> bool:
    if hasattr(reason_code, "is_failure"):
        return bool(reason_code.is_failure)
    return int(reason_code) != 0


def _rc_value(reason_code: Any) -> int:
    if hasattr(reason_code, "value"):
        try:
            return int(reason_code.value)
        except (TypeError, ValueError):
            pass
    try:
        return int(reason_code)
    except (TypeError, ValueError):
        return -1


def classify_connect_error(message: str) -> str:
    """Map ConnectionError text to a config-flow error key."""
    text = (message or "").lower()
    if "mqtt_rc_5" in text or "not_authorized" in text:
        return "not_authorized"
    if "mqtt_rc_99" in text or "tls" in text:
        return "tls_failed"
    if "tcp_timeout" in text or "timed out" in text or "mqtt_rc_-1" in text:
        return "timeout"
    if "tcp_refused" in text or "connection refused" in text:
        return "cannot_connect"
    return "cannot_connect"


def probe_tcp(host: str, port: int, timeout: float = MQTT_CONNECT_TIMEOUT) -> None:
    """Fail fast if 36669 is not reachable before starting MQTT/TLS."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return
    except TimeoutError as err:
        raise ConnectionError("tcp_timeout") from err
    except ConnectionRefusedError as err:
        raise ConnectionError("tcp_refused") from err
    except OSError as err:
        raise ConnectionError(f"tcp_failed:{err}") from err


def send_wol(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    mac_bytes = bytes.fromhex(normalize_uuid(mac).replace(":", ""))
    packet = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))


_MUTE_KEYS = (
    "mute",
    "mute_status",
    "muteStatus",
    "is_mute",
    "isMute",
    "muted",
    "Mute",
    "mute_state",
    "muteState",
)
_VOLUME_KEYS = (
    "volume_value",
    "volumeValue",
    "volume",
    "vol",
    "current_volume",
    "currentVolume",
)
_VOLUME_WRAP_KEYS = (
    "data",
    "result",
    "payload",
    "volumeinfo",
    "volumeInfo",
    "infoPackage",
)
# VIDAA volume_type 0 = TV speakers, 1 = HDMI ARC/eARC. Both are the level.
_VOLUME_LEVEL_TYPES = {VOLUME_TYPE_TV, VOLUME_TYPE_ARC}


def _mute_flag(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "on", "yes", "mute"}:
        return True
    if text in {"0", "false", "off", "no", "unmute"}:
        return False
    return None


def _volume_level(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    # VIDAA is 0–100. Scale a 0–1 float (HA style); integer 1 is 1%, not 100%.
    if 0 < number < 1:
        number *= 100.0
    elif number == 1 and isinstance(value, float):
        number = 100.0
    return max(0, min(100, int(round(number))))


def _payload_has_volume(data: Any) -> bool:
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        return True
    if isinstance(data, str) and _volume_level(data) is not None:
        return True
    if isinstance(data, list) and data:
        return _payload_has_volume(data[0])
    if not isinstance(data, dict):
        return False
    if "volume_type" in data or "volumeType" in data:
        return True
    if any(key in data for key in _VOLUME_KEYS + _MUTE_KEYS):
        return True
    for wrap in _VOLUME_WRAP_KEYS + ("curAppInfo",):
        inner = data.get(wrap)
        if inner is not None and inner is not data and _payload_has_volume(inner):
            return True
    return False


def _unwrap_volume(data: Any) -> Any:
    if isinstance(data, list) and data:
        return _unwrap_volume(data[0])
    if not isinstance(data, dict):
        return data
    if "volume_type" in data or any(key in data for key in _VOLUME_KEYS + _MUTE_KEYS):
        return data
    for wrap in _VOLUME_WRAP_KEYS:
        inner = data.get(wrap)
        if inner is not None and inner is not data:
            return _unwrap_volume(inner)
    return data


def _loads(payload: bytes | str) -> Any:
    if payload is None:
        return None
    if isinstance(payload, bytes):
        text = payload.decode("utf-8", errors="replace").strip()
    else:
        text = str(payload).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


@dataclass
class TvState:
    available: bool = False
    power_on: bool = False
    volume: int | None = None
    # VIDAA volumechange volume_type: 0=TV speakers, 1=HDMI ARC/eARC, 2=mute/BT.
    volume_type: int | None = None
    muted: bool | None = None
    volume_topic: str | None = None
    statetype: str | None = None
    source_id: str | None = None
    source_name: str | None = None
    sources: list[dict[str, str]] = field(default_factory=list)
    apps: list[dict[str, Any]] = field(default_factory=list)
    auth_mode: str | None = None
    last_error: str | None = None
    needs_pin: bool = False
    already_paired: bool = False
    pin_requested: bool = False
    access_token: str | None = None
    refresh_token: str | None = None
    screenshot_path: str | None = None
    screenshot_media_id: str | None = None
    screenshot_note: str = ""

    def media_volume_level(self) -> float | None:
        """Home Assistant ``volume_level`` (0–1) from VIDAA 0–100."""
        if self.volume is None:
            return None
        return max(0.0, min(1.0, float(self.volume) / 100.0))

    def media_is_volume_muted(self) -> bool | None:
        """Home Assistant ``is_volume_muted``. Unknown while the TV is off."""
        if not self.available:
            return None
        return bool(self.muted)


class HisenseTvClient:
    """Threaded paho client with asyncio-friendly helpers."""

    def __init__(
        self,
        host: str,
        *,
        port: int = DEFAULT_PORT,
        uuid: str,
        tv_mac: str | None = None,
        auth_mode: str = "auto",
        certfile: str | None = None,
        keyfile: str | None = None,
        cert_pairs: list[tuple[str | None, str | None]] | None = None,
        use_ssl: bool | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
        control_username: str | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.uuid = normalize_uuid(uuid)
        self.tv_mac = tv_mac
        self.auth_mode = auth_mode
        self.certfile = certfile
        self.keyfile = keyfile
        self.cert_pairs = cert_pairs or ([(certfile, keyfile)] if certfile and keyfile else [(None, None)])
        self.use_ssl = use_ssl
        self.transport: str | None = None
        self._loop = loop
        self.state = TvState(
            access_token=(access_token or "").strip() or None,
            refresh_token=(refresh_token or "").strip() or None,
        )
        self._control_username = (control_username or "").strip()
        self._listeners: list[Callable[[TvState], None]] = []
        self._client: mqtt.Client | None = None
        self._creds: MqttCredentials | None = None
        self._stop = threading.Event()
        self._connected_event: asyncio.Event | None = None
        self._pin_event: asyncio.Event | None = None
        self._token_event: asyncio.Event | None = None
        self._apps_event: asyncio.Event | None = None
        self._connect_rc: int = -1
        self._lock = threading.Lock()
        self.ble: Any = None
        # After cold power-on / MQTT reconnect, wait for LAN remoter (7778/7779)
        # before KEY_SOURCE macros and volume KEY_VOLUME*.
        self._control_warmup = True
        self._volume_lock = threading.Lock()
        self._last_remoter_ok_at = 0.0
        self._last_volume_deliver_at = 0.0
        self._mqtt_epoch = 0
        self._offline_timer: threading.Timer | None = None
        self._offline_lock = threading.Lock()
        self._seen_volume_topics: set[str] = set()
        self._last_volume_log: tuple[Any, ...] | None = None

    @property
    def creds(self) -> MqttCredentials | None:
        return self._creds

    @property
    def mqtt_connected(self) -> bool:
        return self._creds is not None and self._client is not None

    def add_listener(self, callback: Callable[[TvState], None]) -> None:
        self._listeners.append(callback)

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _notify(self) -> None:
        state = self.state
        for listener in list(self._listeners):
            try:
                listener(state)
            except Exception:  # noqa: BLE001 — listener errors must not kill MQTT
                _LOGGER.exception("State listener failed")

    def _set_loop_event(self, event: asyncio.Event | None) -> None:
        if event is None:
            return
        loop = self._loop
        if loop is None:
            event.set()
            return
        loop.call_soon_threadsafe(event.set)

    def _note_volume_topic(self, topic: str) -> None:
        self.state.volume_topic = topic
        snapshot = (self.state.volume, self.state.volume_type, self.state.muted, topic)
        if snapshot == self._last_volume_log:
            return
        first = topic not in self._seen_volume_topics
        self._seen_volume_topics.add(topic)
        self._last_volume_log = snapshot
        _LOGGER.info(
            "MQTT volume from %s: volume=%s type=%s muted=%s%s",
            topic,
            self.state.volume,
            self.state.volume_type,
            self.state.muted,
            " (first)" if first else "",
        )

    def _apply_volume(self, data: Any, *, topic: str | None = None) -> None:
        if data is None:
            return
        payload = _unwrap_volume(data)
        if isinstance(payload, (int, float, str)):
            level = _volume_level(payload)
            if level is None:
                return
            self.state.volume = level
            if topic:
                self._note_volume_topic(topic)
            return
        if not isinstance(payload, dict):
            return
        raw_type = payload.get("volume_type", payload.get("volumeType"))
        volume_type: int | None
        try:
            volume_type = int(raw_type) if raw_type is not None else None
        except (TypeError, ValueError):
            volume_type = None
        mute = None
        for key in _MUTE_KEYS:
            if key in payload and payload[key] is not None:
                mute = _mute_flag(payload[key])
                break
        raw_value = None
        for key in _VOLUME_KEYS:
            if key in payload and payload[key] is not None:
                raw_value = payload[key]
                break
        # sehaas/pyvidaa ignore type 1 (eARC). This E7N is eARC: type 0 and 1
        # are the current level. Type 2 + 0/1 is mute (OSD / 爱家).
        type2_flag = _mute_flag(raw_value) if volume_type == VOLUME_TYPE_MUTE else None
        if volume_type == VOLUME_TYPE_MUTE:
            self.state.volume_type = VOLUME_TYPE_MUTE
            if mute is not None:
                self.state.muted = mute
            elif type2_flag is not None:
                self.state.muted = type2_flag
            if topic:
                self._note_volume_topic(topic)
            return
        if volume_type is not None:
            self.state.volume_type = volume_type
        level = None
        if volume_type in _VOLUME_LEVEL_TYPES or volume_type is None:
            level = _volume_level(raw_value)
            if level is not None:
                self.state.volume = level
        if mute is not None:
            self.state.muted = mute
        if topic and (level is not None or mute is not None or volume_type is not None):
            self._note_volume_topic(topic)

    def _apply_volume_tree(self, data: Any, *, topic: str | None = None) -> None:
        """Walk screenshot / nested platform payloads for volume and mute."""
        self._apply_volume(data, topic=topic)
        if not isinstance(data, dict):
            return
        for key in ("infoPackage", "curAppInfo", "data", "volumeinfo", "volumeInfo"):
            inner = data.get(key)
            if isinstance(inner, dict):
                self._apply_volume_tree(inner, topic=topic)

    def _apply_state(self, data: Any, *, topic: str | None = None) -> None:
        if not isinstance(data, dict):
            if isinstance(data, str) and data:
                self.state.statetype = data
                self.state.power_on = True
            return
        raw_type = data.get("statetype")
        raw_state = data.get("state")
        label: str | None = None
        if raw_type is not None and str(raw_type).strip() != "":
            label = str(raw_type)
        elif isinstance(raw_state, str) and raw_state.strip():
            # Numeric ``state`` flags (0/1) are OSD/power bits, not statetype.
            if not raw_state.strip().lstrip("-").isdigit():
                label = raw_state
        name = data.get("sourcename") or data.get("source_name") or data.get("displayname")
        sid = data.get("sourceid") or data.get("source_id")
        if name:
            self.state.source_name = str(name)
        if sid is not None:
            self.state.source_id = str(sid)
        if label is not None:
            self.state.statetype = label
            kind = label.lower()
            # sehaas treats fake_sleep_0 as off while the broker is still up.
            self.state.power_on = kind not in {
                "fake_sleep_0",
                "fake_sleep",
                "tvsleep",
                "sleep",
                "off",
            }
            if kind == "livetv":
                self.state.source_name = data.get("channel_name") or name or "TV"
        self._apply_volume_tree(data, topic=topic)
        self._maybe_learn_tv_mac(data)

    def _maybe_learn_tv_mac(self, data: Any) -> None:
        if self.tv_mac or not isinstance(data, dict):
            return
        for key in ("mac", "MAC", "tv_mac", "devicemac", "deviceMac"):
            value = data.get(key)
            if not value:
                continue
            try:
                self.tv_mac = normalize_uuid(str(value))
                _LOGGER.info("Learned TV MAC %s from MQTT state", self.tv_mac)
                return
            except ValueError:
                continue

    def _apply_sources(self, data: Any) -> None:
        items = data
        if isinstance(data, dict):
            items = data.get("source_list") or data.get("sourcelist") or data.get("list") or []
        if not isinstance(items, list):
            return
        sources: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            sid = item.get("sourceid", item.get("source_id", item.get("id")))
            name = item.get("sourcename", item.get("source_name", item.get("name", sid)))
            if sid is None:
                continue
            sources.append({"id": str(sid), "name": str(name)})
        if sources:
            self.state.sources = sources

    def _apply_apps(self, data: Any) -> None:
        apps = normalize_apps(data)
        if apps:
            self.state.apps = apps
            self._set_loop_event(self._apps_event)

    def _handle_message(self, topic: str, payload: bytes) -> None:
        data = _loads(payload)
        _LOGGER.debug("MQTT %s <- %s", topic, data)
        if topic.endswith("/data/authentication") or topic.endswith("/data/authenticationcodetoast"):
            self.state.needs_pin = not self.state.already_paired
            self._set_loop_event(self._pin_event)
        elif topic.endswith("/actions/tvsleep") or topic.endswith("/data/tvsleep"):
            self.state.power_on = False
            self.state.statetype = "tvsleep"
        elif topic.endswith("/data/authenticationcode"):
            if isinstance(data, dict) and str(data.get("result")) == "1":
                self.state.already_paired = True
                self.state.needs_pin = False
        elif topic.endswith("/actions/vidaa_app_connect") or topic.endswith("/data/vidaa_app_connect"):
            result = data.get("connect_result") if isinstance(data, dict) else None
            if result in (1, "1"):
                self.state.already_paired = True
                self.state.needs_pin = False
            self._set_loop_event(self._pin_event)
        elif topic.endswith("/data/tokenissuance"):
            if isinstance(data, dict):
                access = str(data.get("accesstoken") or "").strip()
                refresh = str(data.get("refreshtoken") or "").strip()
                if access:
                    self.state.access_token = access
                if refresh:
                    self.state.refresh_token = refresh
            self.state.already_paired = True
            self.state.needs_pin = False
            self._set_loop_event(self._token_event)
            self._set_loop_event(self._pin_event)
        elif (
            topic.endswith("/data/state")
            or topic.endswith("/ui_service/state")
            or topic.endswith("/ui_service/data/state")
        ):
            self._apply_state(data, topic=topic)
        elif topic.endswith("/data/sourcelist"):
            self._apply_sources(data)
        elif "applist" in topic:
            self._apply_apps(data)
        elif "volume" in topic:
            self._apply_volume_tree(data, topic=topic)
        elif _payload_has_volume(data):
            self._apply_volume_tree(data, topic=topic)
        self._notify()

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        self._connect_rc = _rc_value(reason_code)
        if _rc_failed(reason_code):
            _LOGGER.warning("MQTT CONNECT refused rc=%s", reason_code)
            self.state.available = False
            self.state.last_error = f"mqtt_rc_{self._connect_rc}"
            self._set_loop_event(self._connected_event)
            return
        _LOGGER.info("Connected to %s:%s as %s", self.host, self.port, self._creds.client_id if self._creds else "")
        self._mqtt_epoch += 1
        self._cancel_offline_timer()
        self.state.available = True
        self.state.power_on = True
        self.state.last_error = None
        if self._creds:
            for topic in topics.subscription_topics(self._creds, self.tv_mac):
                client.subscribe(topic, qos=0)
        self._set_loop_event(self._connected_event)
        self._notify()
        # Skip while the PIN dialog is up — status queries can dismiss it.
        if not self.state.needs_pin and not self.state.pin_requested:
            try:
                self.refresh_volume_state()
            except (ConnectionError, RuntimeError, OSError):
                _LOGGER.debug("gettvstate/getvolume after CONNECT failed", exc_info=True)

    def _cancel_offline_timer(self) -> None:
        with self._offline_lock:
            timer = self._offline_timer
            self._offline_timer = None
        if timer is not None:
            timer.cancel()

    def _schedule_offline(self, epoch: int) -> None:
        self._cancel_offline_timer()
        timer = threading.Timer(
            MQTT_DISCONNECT_GRACE, self._apply_mqtt_offline, args=(epoch,)
        )
        timer.daemon = True
        with self._offline_lock:
            self._offline_timer = timer
        timer.start()

    def _note_remoter_ok(self) -> None:
        """LAN 7778/7779 answered — the TV is on even if MQTT just blipped."""
        self._last_remoter_ok_at = time.monotonic()
        self._control_warmup = False
        changed = False
        if not self.state.available:
            self.state.available = True
            changed = True
        if not self.state.power_on:
            self.state.power_on = True
            changed = True
        pending = False
        with self._offline_lock:
            pending = self._offline_timer is not None
        if pending:
            self._schedule_offline(self._mqtt_epoch)
        if changed:
            self._notify()

    def _apply_mqtt_offline(self, epoch: int) -> None:
        """Mark the TV off only if this disconnect was not followed by CONNECT."""
        if epoch != self._mqtt_epoch or self._stop.is_set():
            return
        ble_up = self.ble is not None and getattr(self.ble, "connected", False)
        if ble_up:
            self.state.available = True
            self._notify()
            return
        _LOGGER.info("MQTT still down after %.1fs; marking TV off", MQTT_DISCONNECT_GRACE)
        self.state.available = False
        self.state.power_on = False
        self._control_warmup = True
        self._notify()

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, *args: Any, **kwargs: Any) -> None:
        reason_code: Any = 0
        for item in args:
            if hasattr(item, "is_failure") or isinstance(item, int):
                reason_code = item
                break
        _LOGGER.info("Disconnected from TV rc=%s", reason_code)
        ble_up = self.ble is not None and getattr(self.ble, "connected", False)
        if ble_up:
            self.state.available = True
            self._notify()
            return
        # Volume +/- hits LAN remoter 7778; that can drop MQTT 36669 briefly.
        # Flipping power_on here makes media_player go on→off→on.
        self._schedule_offline(self._mqtt_epoch)

    def _on_message(self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        try:
            self._handle_message(message.topic, message.payload)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed handling MQTT message on %s", message.topic)

    def _publish(self, topic: str, payload: Any, *, wait: bool = False) -> None:
        if self._client is None:
            raise ConnectionError("MQTT client is not connected")
        if payload is None:
            body: str | bytes = ""
        elif isinstance(payload, (dict, list)):
            body = json.dumps(payload, separators=(",", ":"))
        else:
            body = str(payload)
        # The TV broker delivers subscriptions and drops QoS 1 publishes.
        # sehaas/ha_hisense_tv publishes at QoS 0.
        info = self._client.publish(topic, body, qos=0, retain=False)
        _LOGGER.debug("MQTT %s -> %s", topic, body)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"Publish failed rc={info.rc} topic={topic}")
        if not wait:
            return
        wait_fn = getattr(info, "wait_for_publish", None)
        if not callable(wait_fn):
            return
        try:
            wait_fn(timeout=1.5)
        except TypeError:
            # paho 1.x wait_for_publish() has no timeout; do not block HA.
            return
        except Exception:  # noqa: BLE001 — some brokers never ack QoS 0
            return

    def _stop_client(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            client.loop_stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    def _try_connect(
        self,
        creds: MqttCredentials,
        *,
        use_tls: bool,
        certfile: str | None,
        keyfile: str | None,
    ) -> int:
        self._creds = creds
        client = _paho_client(creds.client_id)
        client.username_pw_set(creds.username, creds.password)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client._connect_timeout = MQTT_CONNECT_TIMEOUT  # noqa: SLF001 — paho 2.x
        if use_tls:
            context = build_ssl_context(certfile, keyfile)
            client.tls_set_context(context)
            # Do not call tls_insecure_set: it can rebuild the context and
            # wipe SECLEVEL=0 / the client chain on some paho versions.
        self._client = client
        self._connect_rc = -1
        try:
            client.connect(self.host, self.port, keepalive=MQTT_KEEPALIVE)
        except ssl.SSLError as err:
            _LOGGER.warning("TLS handshake failed (%s cert=%s): %s", creds.mode, certfile, err)
            self._stop_client()
            return RC_TLS_FAILED
        except TimeoutError as err:
            _LOGGER.warning("MQTT TCP timed out: %s", err)
            self._stop_client()
            return RC_TCP_FAILED
        except OSError as err:
            _LOGGER.warning("TCP connect failed: %s", err)
            self._stop_client()
            return RC_TCP_FAILED
        client.loop_start()
        steps = max(1, int(MQTT_CONNACK_WAIT / 0.1))
        for _ in range(steps):
            if self._connect_rc != -1:
                break
            threading.Event().wait(0.1)
        return self._connect_rc

    def _credential_sets(self, use_tls: bool) -> list[MqttCredentials]:
        mode = "static" if not use_tls else self.auth_mode
        candidates: list[MqttCredentials] = []
        token = (self.state.access_token or "").strip()
        if token:
            # Control session: same client id, access token as the password.
            # Try the username from the pairing session first, then a fresh one.
            base = generate_dynamic_credentials(self.uuid, modern=True)
            if self._control_username:
                candidates.append(
                    MqttCredentials(
                        client_id=base.client_id,
                        username=self._control_username,
                        password=token,
                        uuid=base.uuid,
                        timestamp=base.timestamp,
                        mode="access_token",
                    )
                )
            for modern in (True, False):
                fresh = base if modern else generate_dynamic_credentials(self.uuid, modern=False)
                if fresh.username == self._control_username:
                    continue
                candidates.append(with_access_token(fresh, token))
        candidates.extend(credentials_for_mode(mode, self.uuid))
        mac = (self.tv_mac or "").strip()
        if mac:
            try:
                extra = credentials_for_mode(mode, mac)
            except ValueError:
                extra = []
            for creds in extra:
                if all(creds.client_id != item.client_id for item in candidates):
                    candidates.append(creds)
        return candidates

    def _transports(self) -> list[tuple[str, bool, str | None, str | None]]:
        if self.use_ssl is False:
            return [("plain", False, None, None)]
        transports: list[tuple[str, bool, str | None, str | None]] = []
        for certfile, keyfile in self.cert_pairs:
            label = "tls" if certfile else "tls_anon"
            transports.append((label, True, certfile, keyfile))
        if not any(item[2] is None for item in transports):
            transports.append(("tls_anon", True, None, None))
        if self.use_ssl is not True:
            transports.append(("plain", False, None, None))
        return transports

    def connect_blocking(self) -> MqttCredentials:
        """Probe TCP, then try TLS (爱家 cert → stand-in → none) then plaintext."""
        self._stop.clear()
        probe_tcp(self.host, self.port)
        last_error: str | None = None
        for name, use_tls, certfile, keyfile in self._transports():
            for creds in self._credential_sets(use_tls):
                _LOGGER.debug(
                    "MQTT try transport=%s auth=%s client_id=%s cert=%s",
                    name,
                    creds.mode,
                    creds.client_id,
                    certfile,
                )
                self._stop_client()
                rc = self._try_connect(creds, use_tls=use_tls, certfile=certfile, keyfile=keyfile)
                if rc == 0:
                    self.transport = name
                    self.certfile = certfile
                    self.keyfile = keyfile
                    self.use_ssl = use_tls
                    self.state.auth_mode = creds.mode
                    self.state.last_error = None
                    _LOGGER.info("MQTT connected via %s auth=%s", name, creds.mode)
                    # Ask for the on-screen code only after the network loop
                    # is running. Doing it inside on_connect, together with
                    # login_each_other_info and status queries, is what kept
                    # the code from staying on screen.
                    if creds.mode != "access_token" and self.state.refresh_token:
                        try:
                            self._refresh_control_password()
                        except Exception:  # noqa: BLE001
                            _LOGGER.debug("Token refresh failed", exc_info=True)
                    return creds
                last_error = f"mqtt_rc_{rc}"
                self.state.last_error = last_error
                if rc in {RC_TCP_FAILED, RC_TLS_FAILED}:
                    # Same socket/TLS setup will fail for every password.
                    break
        self.disconnect_blocking()
        raise ConnectionError(last_error or "cannot_connect")

    async def async_connect(self) -> MqttCredentials:
        loop = asyncio.get_running_loop()
        self.attach_loop(loop)
        self._connected_event = asyncio.Event()
        return await loop.run_in_executor(None, self.connect_blocking)

    def disconnect_blocking(self) -> None:
        self._stop.set()
        self._mqtt_epoch += 1
        self._cancel_offline_timer()
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        try:
            client.loop_stop()
        except Exception:  # noqa: BLE001
            pass
        self.state.available = False

    def _require_creds(self) -> MqttCredentials:
        if self._creds is None or self._client is None:
            raise ConnectionError("Not connected")
        return self._creds

    def _publish_action(
        self,
        service: str,
        action: str,
        payload: Any,
        *,
        as_key: bool = False,
    ) -> None:
        creds = self._require_creds()
        if as_key:
            # The broker runs the key only when the body is the raw name.
            bodies = [normalize_key(str(payload))]
        else:
            bodies = [payload]
        last_error: Exception | None = None
        sent = 0
        for topic in topics.action_topics(creds, service, action, self.tv_mac):
            for body in bodies:
                try:
                    self._publish(topic, body, wait=sent == 0)
                    sent += 1
                except RuntimeError as err:
                    last_error = err
        if sent == 0 and last_error is not None:
            raise last_error

    def send_key(self, key: str) -> None:
        kind = key.strip().lower()
        if kind in {"screenshot", "capture", "capturescreen"}:
            self.capture_screenshot()
            return
        if kind in {"smart_image", "smartimage", "ai"}:
            self.push_smart_image()
            return
        # Custom-source macros store KEY_SOURCE; the remoter button uses "source".
        # Both must open the source menu the same way (voice → local → MQTT).
        if kind in {"source", "signal", "key_source"}:
            self.open_source()
            return
        name = normalize_key(key)
        if name == KEY_SOURCE:
            self.open_source()
            return
        if name in {KEY_VOLUMEUP, KEY_VOLUMEDOWN}:
            self._send_volume_step(name)
            return
        status = send_local_key(self.host, name)
        if status is not None and 200 <= status < 300:
            self._note_remoter_ok()
            if name == KEY_MUTE:
                self.refresh_volume_state()
            return
        if not self.mqtt_connected:
            _LOGGER.info(
                "HTTP remote did not take %s (status %s); MQTT not connected",
                name,
                status,
            )
            raise ConnectionError(
                f"TV remoter did not take {name} and MQTT is not connected"
            )
        _LOGGER.info("HTTP remote did not take %s (status %s); trying MQTT", name, status)
        self._publish_action("remote_service", "sendkey", key, as_key=True)
        if name == KEY_MUTE:
            self.refresh_volume_state()

    def submit_code(self, code: str) -> None:
        """Send the 4 digits shown on the TV after vidaa_app_connect."""
        digits = "".join(ch for ch in str(code) if ch.isdigit())
        if not digits:
            raise ValueError("empty pairing code")
        # The TV compares this as a number. A JSON string is rejected.
        self._publish_action("ui_service", "authenticationcode", {"authNum": int(digits)})
        self.state.needs_pin = False

    def capture_screenshot(self) -> bytes:
        """Download the current frame. The caller stores it in the Image media source."""
        shot = capture_screen(self.host)
        self.state.screenshot_note = shot.note
        self._apply_volume_tree(getattr(shot, "info", None), topic="screenshot")
        self._notify()
        _LOGGER.info("Captured TV screenshot (%s bytes)", len(shot.image))
        return shot.image

    def remember_screenshot(self, media_id: str) -> None:
        """Point state at the Image media-source item that holds the last frame."""
        self.state.screenshot_media_id = media_id
        self.state.screenshot_path = f"/api/image/serve/{media_id}/original"
        self._notify()

    @staticmethod
    def _is_source_key(key: str) -> bool:
        kind = key.strip().lower()
        if kind in {"source", "signal", "key_source"}:
            return True
        try:
            return normalize_key(key) == KEY_SOURCE
        except ValueError:
            return False

    def _wait_for_remoter(
        self,
        *,
        pause: Callable[[float], None] = time.sleep,
        timeout: float = REMOTER_READY_TIMEOUT,
        poll: float = REMOTER_READY_POLL,
    ) -> bool:
        """Block until the LAN remoter accepts TCP, or until timeout."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            if remoter_reachable(self.host):
                return True
            if time.monotonic() >= deadline:
                _LOGGER.info(
                    "LAN remoter on %s did not answer within %.1fs; continuing anyway",
                    self.host,
                    timeout,
                )
                return False
            pause(max(0.05, float(poll)))

    def open_source(
        self,
        *,
        retries: int = 1,
        retry_delay: float = SOURCE_OPEN_RETRY_DELAY,
        pause: Callable[[float], None] = time.sleep,
    ) -> bool:
        """爱家 信号源: speak the command, then fall back to KEY_SOURCE.

        Returns True when the local voice/HTTP path accepted the command.
        After cold boot the first attempt often gets no answer; retry before
        falling back to MQTT so custom-source macros keep their first press.
        """
        attempts = max(1, int(retries))
        last_status: int | None = None
        for attempt in range(attempts):
            status = push_voice(self.host, "信号源")
            if status is not None and 200 <= status < 300:
                return True
            last_status = status
            status = send_local_key(self.host, KEY_SOURCE)
            if status is not None and 200 <= status < 300:
                return True
            last_status = status if status is not None else last_status
            if attempt + 1 < attempts:
                pause(max(0.0, float(retry_delay)))
        if not self.mqtt_connected:
            _LOGGER.info(
                "Local source command was not accepted (%s); MQTT not connected",
                last_status,
            )
            raise ConnectionError(
                "Could not open the source menu (LAN remoter missed and MQTT is not connected)"
            )
        _LOGGER.info(
            "Local source command was not accepted (%s); trying MQTT", last_status
        )
        self._publish_action("ui_service", "sourcelist", "")
        self._publish_action("remote_service", "sendkey", KEY_SOURCE, as_key=True)
        return False

    def run_key_sequence(
        self,
        keys: list[str],
        *,
        delay: float = DEFAULT_SOURCE_KEY_DELAY,
        pause: Callable[[float], None] = time.sleep,
    ) -> None:
        """Send remoter keys in order, with a short pause between them.

        Used for custom inputs such as ``KEY_SOURCE → KEY_RIGHT → KEY_OK``.
        After cold power-on, wait for the LAN remoter and retry the first
        source open so SOURCE is not skipped before RIGHT/OK.
        """
        wait = max(0.0, float(delay))
        warmup = self._control_warmup
        if warmup:
            self._wait_for_remoter(pause=pause)
        for index, key in enumerate(keys):
            if index and wait:
                pause(wait)
            if self._is_source_key(key):
                retries = SOURCE_OPEN_RETRIES if (warmup and index == 0) else 1
                local_ok = self.open_source(retries=retries, pause=pause)
                if warmup and index == 0:
                    # Menu animation after the first successful open.
                    settle = SOURCE_MENU_SETTLE if local_ok else max(
                        SOURCE_MENU_SETTLE, wait
                    )
                    if settle:
                        pause(settle)
                    self._control_warmup = False
                    warmup = False
                continue
            self.send_key(key)
        if warmup:
            self._control_warmup = False

    def push_smart_image(self) -> None:
        """爱家 AI识图: voice 识图, then the app's function names."""
        status = push_voice(self.host, "识图")
        if status is not None and 200 <= status < 300:
            return
        for name in ("functionSmartImage", "pushSmartImage"):
            status = send_local_key(self.host, name)
            if status is not None and 200 <= status < 300:
                return
        _LOGGER.info("Local AI image command was not accepted (%s); trying MQTT", status)
        for action in ("smartimage", "pushSmartImage", "functionSmartImage"):
            self._publish_action("ui_service", action, "")

    def _note_volume_delta(self, delta: int) -> None:
        """Optimistic local level after a successful ±1 step."""
        if self.state.volume is None:
            return
        self.state.volume = max(0, min(100, int(self.state.volume) + int(delta)))
        self._notify()

    def _is_arc_audio(self) -> bool:
        """True when HDMI ARC/eARC is the active audio output (CEC volume)."""
        return self.state.volume_type == VOLUME_TYPE_ARC

    def _publish_changevolume_tip(self, tip: str) -> bool:
        """Publish changevolume on the session id and the ``$normal`` twin.

        Community ARC notes used ``{mac}$normal``; this TV session is
        ``$vidaa_common`` (see HA logs). Try both when the prefix differs.
        """
        sent = 0
        try:
            self._publish_action("platform_service", "changevolume", tip)
            sent += 1
        except RuntimeError:
            _LOGGER.debug("changevolume on session id failed", exc_info=True)
        creds = self._creds
        if creds is not None and "$" in (creds.client_id or ""):
            prefix, _, flavor = creds.client_id.partition("$")
            alt = "normal" if flavor != "normal" else "vidaa_common"
            alt_id = f"{prefix}${alt}"
            if alt_id != creds.client_id:
                try:
                    self._publish(
                        f"/remoteapp/tv/platform_service/{alt_id}/actions/changevolume",
                        tip,
                    )
                    sent += 1
                except RuntimeError:
                    _LOGGER.debug("changevolume on %s failed", alt_id, exc_info=True)
        return sent > 0

    def _send_volume_step(
        self,
        key: str,
        *,
        pause: Callable[[float], None] = time.sleep,
    ) -> bool:
        """One media_player +/- step: a single LAN KEY_VOLUME, paced for CEC.

        User: MQTT cannot control volume — use LAN. Dual MQTT+LAN (15:51)
        flooded CEC. 1.22.9 retried LAN when volumechange was silent; both
        keys landed and volume jumped two steps — that retry is gone.

        1. Wait ``VOLUME_CEC_GAP`` since the last KEY (0.9s).
        2. Deliver **one** ``KEY_VOLUME*`` via LAN remoter (7778/7779).
        3. Never MQTT ``sendkey`` / ``changevolume`` on this path.
        4. After a successful KEY, ask ``gettvstate`` + ``getvolume`` (OSD).
        """
        name = normalize_key(key)
        if name not in {KEY_VOLUMEUP, KEY_VOLUMEDOWN}:
            raise ValueError(f"not a volume key: {key}")
        delta = 1 if name == KEY_VOLUMEUP else -1
        gap = max(0.0, float(VOLUME_CEC_GAP))
        delivered = False
        with self._volume_lock:
            since = time.monotonic() - self._last_volume_deliver_at
            if gap and since < gap:
                pause(gap - since)
                _LOGGER.info("volume step CEC pace %.2fs before LAN", gap)

            idle = time.monotonic() - self._last_remoter_ok_at
            if self._control_warmup or idle >= VOLUME_KEY_IDLE_WARMUP:
                self._wait_for_remoter(pause=pause)
            status = send_local_key(self.host, name)
            delivered = status is not None and 200 <= status < 300
            if delivered:
                self._note_remoter_ok()
                _LOGGER.info("volume step LAN %s (status %s)", name, status)
            else:
                _LOGGER.info("volume step LAN %s missed (status %s)", name, status)

            self._last_volume_deliver_at = time.monotonic()
            if delivered:
                self._note_volume_delta(delta)
        if delivered:
            self.refresh_volume_state()
        return delivered

    def _press_volume_key(
        self,
        key: str,
        *,
        count: int,
        pause: Callable[[float], None] = time.sleep,
        step_pause: float = VOLUME_KEY_PAUSE,
    ) -> bool:
        """Repeat volume steps (helper for absolute set_volume)."""
        if count <= 0:
            return True
        wait = max(0.0, float(step_pause))
        for index in range(count):
            if not self._send_volume_step(key, pause=pause):
                return False
            if index + 1 < count and wait:
                pause(wait)
        return True

    def _set_volume_by_keys(
        self,
        target: int,
        *,
        pause: Callable[[float], None] = time.sleep,
        step_pause: float = VOLUME_KEY_PAUSE,
    ) -> bool:
        """Move toward an absolute level via repeated changevolume ±1 steps."""
        current = self.state.volume
        if current is None:
            # Unknown: one MQTT tip cannot seek; floor then climb on TV path.
            if self._is_arc_audio():
                return False
            if not self._press_volume_key(
                KEY_VOLUMEDOWN,
                count=VOLUME_UNKNOWN_FLOOR_STEPS,
                pause=pause,
                step_pause=step_pause,
            ):
                return False
            current = 0
        delta = int(target) - int(current)
        if delta == 0:
            return True
        key = KEY_VOLUMEUP if delta > 0 else KEY_VOLUMEDOWN
        return self._press_volume_key(
            key,
            count=abs(delta),
            pause=pause,
            step_pause=step_pause,
        )

    def set_volume(
        self,
        volume: int,
        *,
        pause: Callable[[float], None] = time.sleep,
    ) -> None:
        """Best-effort absolute volume for non-UI callers (no HA slider)."""
        target = max(0, min(100, int(volume)))
        used = self._set_volume_by_keys(target, pause=pause)
        if not used:
            try:
                self._publish_action("platform_service", "changevolume", str(target))
            except RuntimeError:
                _LOGGER.debug("absolute changevolume failed", exc_info=True)
        self.state.volume = target
        self._notify()
        try:
            self._publish_action("platform_service", "getvolume", "")
        except RuntimeError:
            _LOGGER.debug("getvolume after set_volume failed", exc_info=True)

    def change_source(self, source_id: str, source_name: str | None = None) -> None:
        payload: dict[str, str] = {"sourceid": str(source_id)}
        if source_name:
            payload["sourcename"] = source_name
        self._publish_action("ui_service", "changesource", payload)

    def launch_app(
        self,
        name: str,
        url: str | None = None,
        url_type: int = 37,
        store_type: int = 0,
        package: str | None = None,
    ) -> None:
        """Open an app. Prefer LAN 「电视打开」 when the target is a package."""
        app_url = (url or package or name or "").strip()
        pkg = (package or "").strip()
        if not is_android_package(pkg):
            pkg = app_url if is_android_package(app_url) else ""
        if not pkg:
            for app in self.state.apps:
                if str(app.get("name") or "") == name or str(app.get("url") or "") == app_url:
                    candidate = str(app.get("package") or app.get("url") or "")
                    if is_android_package(candidate):
                        pkg = candidate
                        url_type = int(app.get("url_type") or url_type)
                        break
        if pkg:
            status = launch_local_app(self.host, pkg)
            if status is not None and 200 <= status < 300:
                return
            _LOGGER.info("Local 电视打开 did not take %s (status %s); trying MQTT", pkg, status)
            payload = {
                "name": name or pkg,
                "url": pkg,
                "appId": pkg,
                "urlType": 0,
                "storeType": int(store_type),
                "isLocalApp": 1,
                "has_detail_page": 0,
                "type": 0,
            }
            self._publish_action("ui_service", "launchapp", payload)
            return
        payload = {
            "name": name,
            "url": app_url,
            "appId": app_url,
            "urlType": int(url_type),
            "storeType": int(store_type),
        }
        self._publish_action("ui_service", "launchapp", payload)

    def refresh_apps(self) -> None:
        """Ask the TV for 我的应用. The reply arrives on the applist data topic."""
        try:
            self._publish_action("ui_service", "applist", "")
        except RuntimeError:
            _LOGGER.debug("Cannot request the TV app list", exc_info=True)

    def change_channel(self, channel_param: str) -> None:
        self._publish_action(
            "ui_service",
            "changechannel",
            {"channel_param": str(channel_param)},
        )

    def refresh_volume(self) -> None:
        """Ask the TV for the current volume/mute (reply on data/volume or volumechange)."""
        try:
            self._publish_action("platform_service", "getvolume", "")
        except (ConnectionError, RuntimeError):
            _LOGGER.debug("getvolume failed", exc_info=True)

    def refresh_volume_state(self) -> None:
        """Poll gettvstate + getvolume. Do not send applist on this path."""
        try:
            self._publish_action("ui_service", "gettvstate", "")
        except (ConnectionError, RuntimeError):
            _LOGGER.debug("gettvstate failed", exc_info=True)
        self.refresh_volume()

    def refresh_status(self) -> None:
        self.refresh_volume_state()
        self.refresh_apps()

    def _refresh_control_password(self) -> None:
        refresh = {"refreshtoken": self.state.refresh_token}
        self._publish_action("platform_service", "gettoken", refresh)
        self._publish_action("ui_service", "gettoken", refresh)
        if self._creds is not None:
            self._publish(
                f"/remoteapp/tv/platform_service/{self._creds.client_id}/data/gettoken",
                refresh,
            )

    def start_pairing(self) -> None:
        """Ask the TV, once, to show the 4-digit code.

        Do not send ``login_each_other_info`` or status queries with this.
        Those messages replace the dialog before anyone can read it.
        Pressing this again rotates the code.
        """
        creds = self._require_creds()
        topic = topics.vidaa_app_connect(creds)
        self._publish(topic, CONNECT_PAYLOAD, wait=True)
        _LOGGER.info("Asked the TV to show a pairing code on %s", topic)
        self.state.pin_requested = True
        self._notify()

    async def async_pair(self) -> TvState:
        """Register with the TV without waiting for a PIN."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.start_pairing)
        return self.state

    async def async_send_key(self, key: str) -> None:
        await asyncio.get_running_loop().run_in_executor(None, self.send_key, key)

    async def async_submit_code(self, code: str) -> None:
        await asyncio.get_running_loop().run_in_executor(None, self.submit_code, code)

    async def async_connect_ble(self, hass: Any, address: str) -> None:
        from .ble_hid import HisenseBleRemote

        remote = HisenseBleRemote(hass, address)
        await remote.async_connect()
        self.ble = remote
        self.state.available = True
        self.state.power_on = True
        self._notify()

    async def async_disconnect(self) -> None:
        loop = asyncio.get_running_loop()
        ble = self.ble
        self.ble = None
        if ble is not None:
            try:
                await ble.async_disconnect()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("BLE disconnect failed", exc_info=True)
        await loop.run_in_executor(None, self.disconnect_blocking)

    async def async_capture_screenshot(self) -> bytes:
        return await asyncio.get_running_loop().run_in_executor(None, self.capture_screenshot)

    async def async_open_source(self) -> None:
        await asyncio.get_running_loop().run_in_executor(None, self.open_source)

    async def async_run_key_sequence(
        self,
        keys: list[str],
        *,
        delay: float = DEFAULT_SOURCE_KEY_DELAY,
    ) -> None:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: self.run_key_sequence(keys, delay=delay)
        )

    async def async_push_smart_image(self) -> None:
        await asyncio.get_running_loop().run_in_executor(None, self.push_smart_image)

    async def async_set_volume(self, volume: int) -> None:
        await asyncio.get_running_loop().run_in_executor(None, self.set_volume, volume)

    async def async_change_source(self, source_id: str, source_name: str | None = None) -> None:
        await asyncio.get_running_loop().run_in_executor(
            None, self.change_source, source_id, source_name
        )

    async def async_change_channel(self, channel_param: str) -> None:
        await asyncio.get_running_loop().run_in_executor(None, self.change_channel, channel_param)

    async def async_launch_app(
        self,
        name: str,
        url: str | None = None,
        url_type: int = 37,
        store_type: int = 0,
        package: str | None = None,
    ) -> None:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: self.launch_app(name, url, url_type, store_type, package)
        )

    async def async_refresh_apps(self, wait: float = 3.0) -> None:
        """Request applist and wait briefly for the reply."""
        loop = asyncio.get_running_loop()
        self._apps_event = asyncio.Event()
        before = list(self.state.apps)
        await loop.run_in_executor(None, self.refresh_apps)
        if wait <= 0:
            return
        try:
            await asyncio.wait_for(self._apps_event.wait(), timeout=wait)
        except TimeoutError:
            if self.state.apps == before:
                _LOGGER.debug("No applist reply within %ss", wait)

    async def async_wait_for_broker(self) -> bool:
        """Retry MQTT after a physical power-on (button / WoL)."""
        if self.state.available:
            return True
        for delay in (3, 5, 8, 13, 21):
            await asyncio.sleep(delay)
            try:
                await self.async_connect()
                return True
            except ConnectionError:
                _LOGGER.debug("TV broker not up yet, retrying")
        return False

    async def async_turn_on(self) -> None:
        """Wake via BLE KEY_POWER, then Wake-on-LAN when no HA button is configured."""
        if self.state.available:
            return
        ble = self.ble
        if ble is not None:
            try:
                await ble.async_send_key(KEY_POWER)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("BLE power-on failed", exc_info=True)
            if getattr(ble, "connected", False):
                self.state.available = True
                self.state.power_on = True
                self._notify()
            try:
                await self.async_connect()
            except ConnectionError:
                _LOGGER.debug("MQTT still down after BLE power-on")
            return
        if self.tv_mac:
            await asyncio.get_running_loop().run_in_executor(None, send_wol, self.tv_mac)
            await self.async_wait_for_broker()
            return
        _LOGGER.warning(
            "Cannot wake TV: configure a power-on button entity (Aijia cannot power on a dead TV)"
        )

    async def async_turn_off(self) -> None:
        if self.state.available:
            await self.async_send_key(KEY_POWER)

    async def async_toggle_mute(self) -> None:
        await self.async_send_key("KEY_MUTE")
        self.state.muted = not bool(self.state.muted)
        self._notify()
