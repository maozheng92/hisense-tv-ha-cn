"""Runtime hub for one Hisense E7N Pro (TCL TclTvHub layout).

MQTT push still lands on DataUpdateCoordinator so existing CoordinatorEntity
rows keep working. Platforms read ``entry.runtime_data``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .aijia_account import (
    AijiaAuthError,
    AijiaError,
    AijiaTokens,
    async_fetch_apps,
    tokens_from_entry,
)
from .apps import app_choice_name, app_choice_names, resolve_app
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CONTROL_USERNAME,
    CONF_REFRESH_TOKEN,
    DATA_COORDINATOR,
    DEFAULT_POWER_ON_COMMAND,
    DEFAULT_SOURCE_KEY_DELAY,
    DOMAIN,
    LEGACY_SOURCE_KEY_DELAYS,
    POWER_ON_MODE_WOL,
)
from .custom_sources import (
    KIND_KEY,
    actions_to_wire_keys,
    classify_source_action,
    copy_sources,
    find_custom_source,
    normalize_custom_sources,
    source_actions,
    source_key_delay,
    visible_source_names,
)
from .keys import KEY_VOLUMEDOWN, KEY_VOLUMEUP, normalize_key
from .power import (
    entity_press_call,
    infer_power_on_mode,
    normalize_power_on_entity,
    power_on_call,
)
from .screenshot_store import async_save_screenshot
from .tv_client import HisenseTvClient, TvState

_LOGGER = logging.getLogger(__name__)


def hub_from_entry(hass: HomeAssistant, entry: ConfigEntry) -> HisenseTvHub:
    """Prefer ConfigEntry.runtime_data; fall back to hass.data for older HA."""
    hub = getattr(entry, "runtime_data", None)
    if isinstance(hub, HisenseTvHub):
        return hub
    return hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]


class HisenseTvHub(DataUpdateCoordinator[TvState]):
    """Expose TV state to entities. Updates come from MQTT, not polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: HisenseTvClient,
        name: str,
        entry: ConfigEntry | None = None,
        *,
        power_on_button: str | None = None,
    ) -> None:
        super().__init__(
            hass,
            logger=logging.getLogger(__name__),
            name=f"{DOMAIN}_{name}",
            update_interval=None,
        )
        self.client = client
        self.config_entry = entry
        self.device_name = name
        self.power_on_button = normalize_power_on_entity(power_on_button)
        self.power_on_mode = POWER_ON_MODE_WOL
        self.power_on_remote: str | None = None
        self.power_on_command = DEFAULT_POWER_ON_COMMAND
        self.power_on_device = ""
        self.volume_up_button: str | None = None
        self.volume_down_button: str | None = None
        self.custom_sources: list[dict] = []
        self.source_key_delay = DEFAULT_SOURCE_KEY_DELAY
        self.selected_source: str | None = None
        self.last_app: str | None = None
        self.aijia: AijiaTokens | None = None
        self._aijia_fetch_at = 0.0
        self._pin_notified = False
        client.add_listener(self._on_client_state)

    @property
    def aijia_logged_in(self) -> bool:
        return bool(self.aijia and self.aijia.logged_in)

    def sync_aijia_from_entry(self) -> None:
        """Reload 爱家 tokens from the config entry (options login persists immediately)."""
        entry = self.config_entry
        if entry is None:
            return
        tokens = tokens_from_entry({**entry.data, **(entry.options or {})})
        if tokens is not None and tokens.logged_in:
            self.aijia = tokens

    @property
    def tv(self) -> TvState:
        return self.data or self.client.state

    @property
    def visible_source_names(self) -> list[str]:
        names = visible_source_names(self.custom_sources)
        seen = set(names)
        for item in self.tv.sources:
            name = item.get("name")
            if name and str(name) not in seen:
                names.append(str(name))
                seen.add(str(name))
        for name in app_choice_names(self.tv.apps):
            if name not in seen:
                names.append(name)
                seen.add(name)
        return names

    def configure_power_on(
        self,
        *,
        mode: str | None,
        button: str | None,
        remote: str | None,
        command: str | None,
        device: str | None,
        mac: str | None,
    ) -> None:
        """Store this TV's wake method. Each config entry has its own."""
        self.power_on_button = normalize_power_on_entity(button)
        self.power_on_remote = normalize_power_on_entity(remote)
        self.power_on_command = (command or "").strip() or DEFAULT_POWER_ON_COMMAND
        self.power_on_device = (device or "").strip()
        self.power_on_mode = infer_power_on_mode(mode, button, remote, mac)

    def configure_volume_buttons(
        self,
        *,
        volume_up: str | None,
        volume_down: str | None,
    ) -> None:
        """Optional HA buttons that replace LAN KEY_VOLUME* for +/-."""
        self.volume_up_button = normalize_power_on_entity(volume_up)
        self.volume_down_button = normalize_power_on_entity(volume_down)

    async def async_send_key(self, key: str) -> None:
        name = normalize_key(key)
        if name == KEY_VOLUMEUP:
            await self.async_volume_step(1)
            return
        if name == KEY_VOLUMEDOWN:
            await self.async_volume_step(-1)
            return
        if name in {"screenshot", "capture", "capturescreen", "截屏"}:
            await self.async_capture_and_store_screenshot()
            return
        await self.client.async_send_key(key)

    async def async_volume_step(self, delta: int) -> None:
        """Press a configured volume button, else LAN KEY_VOLUME*."""
        entity = self.volume_up_button if delta > 0 else self.volume_down_button
        call = entity_press_call(entity)
        if call is not None:
            _LOGGER.info(
                "Volume %s via %s.%s %s",
                "up" if delta > 0 else "down",
                call.domain,
                call.service,
                call.data.get(ATTR_ENTITY_ID),
            )
            try:
                await self.hass.services.async_call(
                    call.domain,
                    call.service,
                    call.data,
                    blocking=True,
                )
            except HomeAssistantError:
                _LOGGER.exception(
                    "Volume button %s.%s failed", call.domain, call.service
                )
            return
        key = KEY_VOLUMEUP if delta > 0 else KEY_VOLUMEDOWN
        await self.client.async_send_key(key)

    def configure_custom_sources(
        self,
        sources: object | None,
        *,
        delay: float | None = None,
    ) -> None:
        """Store user-defined inputs and the pause between remoter keys."""
        try:
            self.custom_sources = copy_sources(normalize_custom_sources(sources))
        except ValueError:
            _LOGGER.warning("Ignoring invalid custom sources", exc_info=True)
            self.custom_sources = []
        try:
            wait = DEFAULT_SOURCE_KEY_DELAY if delay is None else float(delay)
        except (TypeError, ValueError):
            wait = DEFAULT_SOURCE_KEY_DELAY
        # Prior shipped defaults felt sluggish between RIGHT/OK presses.
        if any(abs(wait - legacy) < 1e-9 for legacy in LEGACY_SOURCE_KEY_DELAYS):
            wait = DEFAULT_SOURCE_KEY_DELAY
        self.source_key_delay = max(0.0, min(5.0, wait))

    async def _ensure_source_control(self) -> None:
        """Reconnect MQTT if needed, else wait for the LAN remoter (volume path)."""
        client = self.client
        if client.mqtt_connected:
            return
        try:
            await client.async_connect()
        except (ConnectionError, OSError, RuntimeError) as err:
            _LOGGER.info("MQTT reconnect before source macro failed: %s", err)
        if not client.mqtt_connected:
            await asyncio.get_running_loop().run_in_executor(
                None, client._wait_for_remoter
            )

    async def async_press_source_buttons(self, source: str) -> None:
        """Run a custom source KEY / HA-button sequence (TCL layout)."""
        custom = find_custom_source(self.custom_sources, source)
        if custom is None:
            raise HomeAssistantError(f"Unknown custom source {source!r}")
        actions = source_actions(custom)
        if not actions:
            raise HomeAssistantError(f"Custom source {source!r} has no presses")
        delay = source_key_delay(custom, self.source_key_delay)
        kinds = {
            classified[0]
            for action in actions
            if (classified := classify_source_action(action)) is not None
        }
        try:
            await self._ensure_source_control()
            if kinds == {KIND_KEY}:
                await self.client.async_run_key_sequence(
                    actions_to_wire_keys(actions), delay=delay
                )
            else:
                for step, action in enumerate(actions):
                    classified = classify_source_action(action)
                    if classified is None:
                        raise HomeAssistantError(f"Unknown source action {action!r}")
                    kind, value = classified
                    if kind == KIND_KEY:
                        await self.async_send_key(value)
                    else:
                        await self.hass.services.async_call(
                            "button",
                            "press",
                            {ATTR_ENTITY_ID: value},
                            blocking=True,
                        )
                    if step < len(actions) - 1 and delay > 0:
                        await asyncio.sleep(delay)
        except HomeAssistantError:
            raise
        except (RuntimeError, ConnectionError, OSError) as err:
            raise HomeAssistantError(str(err) or "Could not send source keys") from err
        self.selected_source = str(custom["name"])
        self.async_set_updated_data(self.client.state)

    async def async_select_source(self, source: str) -> None:
        """Custom KEY macro, MQTT HDMI id, or VIDAA app name (1.22.14 fallback)."""
        custom = find_custom_source(self.custom_sources, source)
        if custom is not None:
            await self.async_press_source_buttons(source)
            return
        tv = self.tv
        for item in tv.sources:
            if item.get("name") == source:
                await self.client.async_change_source(item["id"], source)
                self.selected_source = source
                self.async_set_updated_data(self.client.state)
                return
        app = resolve_app(tv.apps, source)
        if app is not None:
            await self.async_launch_resolved_app(app)
            return
        await self.client.async_launch_app(source)

    async def async_refresh_apps(self, wait: float = 3.0) -> None:
        """Load 我的应用 from 爱家云 when logged in; otherwise probe VIDAA MQTT."""
        self.sync_aijia_from_entry()
        if self.aijia_logged_in:
            try:
                await self.async_refresh_aijia_apps()
            except (AijiaError, OSError) as err:
                _LOGGER.warning("爱家云刷新我的应用失败: %s", err)
            if self.tv.apps:
                return
        await self.client.async_refresh_apps(wait)

    async def async_refresh_aijia_apps(self, force: bool = False) -> None:
        """Fetch 爱家栏目 and apply the installed-app tiles."""
        self.sync_aijia_from_entry()
        tokens = self.aijia
        if tokens is None or not tokens.logged_in:
            return
        now = time.time()
        if not force and self._aijia_fetch_at and now - self._aijia_fetch_at < 3:
            return
        self._aijia_fetch_at = now
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        session = async_get_clientsession(self.hass)
        try:
            updated, apps = await async_fetch_apps(
                session,
                tokens,
                host=self.client.host,
                mac=self.client.tv_mac,
            )
        except AijiaAuthError:
            _LOGGER.warning("爱家令牌已失效，请在集成选项重新登录")
            raise
        self.aijia = updated
        self._store_aijia_tokens(updated)
        if apps:
            self.client.apply_cloud_apps(apps)
            self.async_set_updated_data(self.client.state)

    def configure_aijia(self, data: dict[str, Any] | None) -> None:
        self.aijia = tokens_from_entry(data)

    def _store_aijia_tokens(self, tokens: AijiaTokens) -> None:
        entry = self.config_entry
        if entry is None:
            return
        payload = tokens.to_entry()
        merged = {**entry.data, **payload}
        if all(entry.data.get(key) == value for key, value in payload.items()):
            return
        self.hass.config_entries.async_update_entry(entry, data=merged)

    async def async_launch_resolved_app(self, app: dict[str, Any]) -> None:
        name = str(app.get("name") or "")
        url = app.get("url") or app.get("app_id")
        await self.client.async_launch_app(
            name,
            str(url) if url else None,
            int(app.get("url_type") or 37),
            int(app.get("store_type") or 0),
            str(app["package"]) if app.get("package") else None,
        )
        self.last_app = app_choice_name(app) or name
        self.async_set_updated_data(self.client.state)

    async def async_launch_app(self, name: str, url: str | None = None) -> None:
        apps = self.tv.apps
        app = resolve_app(apps, name)
        if app is None and url:
            app = resolve_app(apps, url)
        if app is not None:
            await self.async_launch_resolved_app(app)
            return
        await self.client.async_launch_app(name, url)
        self.last_app = name
        self.async_set_updated_data(self.client.state)

    async def async_capture_and_store_screenshot(self) -> str:
        """Capture a frame and save it to Image upload (TCL screenshot path)."""
        image = await self.client.async_capture_screenshot()
        entry = self.config_entry
        entry_id = entry.entry_id if entry is not None else "hisense"
        title = ((entry.title if entry is not None else None) or "海信").strip() or "海信"
        filename = f"{title} 截屏.jpg".replace("/", " ").replace("\\", " ")
        media_id = await async_save_screenshot(self.hass, entry_id, image, filename)
        self.client.remember_screenshot(media_id)
        note = self.client.state.screenshot_note
        message = (
            f"截屏已保存到媒体浏览器的 Image upload，文件名是「{filename}」。"
            f"直接打开 /api/image/serve/{media_id}/original 。"
        )
        if note:
            message = f"{note}\n{message}"
        persistent_notification.async_create(
            self.hass,
            message,
            title="海信截屏",
            notification_id=f"{DOMAIN}_screenshot_{entry_id}",
        )
        return media_id

    @property
    def can_power_on(self) -> bool:
        if self.power_on_mode == POWER_ON_MODE_WOL:
            return bool(self.client.tv_mac)
        return power_on_call(
            self.power_on_mode,
            self.power_on_button,
            self.power_on_remote,
            self.power_on_command,
            self.power_on_device,
            self.client.tv_mac,
        ) is not None or bool(self.client.tv_mac)

    @callback
    def _on_client_state(self, state: TvState) -> None:
        self.hass.loop.call_soon_threadsafe(self._deliver_state, state)

    def _store_control_password(self, state: TvState) -> None:
        """Persist the access token and reload so the next login uses it."""
        entry = self.config_entry
        token = (state.access_token or "").strip()
        if entry is None or not token or entry.data.get(CONF_ACCESS_TOKEN) == token:
            return
        refresh = (state.refresh_token or "").strip() or entry.data.get(CONF_REFRESH_TOKEN, "")
        username = entry.data.get(CONF_CONTROL_USERNAME, "")
        creds = self.client.creds
        if creds is not None and creds.mode != "access_token" and creds.username:
            username = creds.username
        _LOGGER.info("TV issued a control password; reconnecting with it")
        self.hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: token,
                CONF_REFRESH_TOKEN: refresh,
                CONF_CONTROL_USERNAME: username,
            },
        )

    @callback
    def _deliver_state(self, state: TvState) -> None:
        self.async_set_updated_data(state)
        self._store_control_password(state)
        notification_id = f"{DOMAIN}_pair_{self.device_name}"
        if state.already_paired and not state.needs_pin:
            self._pin_notified = False
            persistent_notification.async_dismiss(self.hass, notification_id)
            return
        if (state.needs_pin or state.pin_requested) and not self._pin_notified:
            self._pin_notified = True
            persistent_notification.async_create(
                self.hass,
                (
                    "请马上看电视机画面，数字出现在画面上方或中间，大约一分钟后消失。"
                    "看到 4 位数字后，在开发者工具里调用 "
                    f"`{DOMAIN}.submit_code`，目标选这台电视的 Remote，"
                    "把数字填进 code。没有数字时，只按一次「请求授权码」按钮，"
                    "同时盯着电视。连按会把刚出现的数字换成新的。"
                ),
                title="海信电视需要授权",
                notification_id=notification_id,
            )

    async def _async_update_data(self) -> TvState:
        if self.client.state.available:
            try:
                await self.hass.async_add_executor_job(self.client.refresh_status)
            except Exception:  # noqa: BLE001
                self.logger.debug("Manual status refresh failed", exc_info=True)
        return self.client.state

    async def async_turn_on(self) -> None:
        """Power on via the configured button device, then wait for MQTT.

        Aijia cannot start a fully off E7N Pro: KEY_POWER needs the TV broker.
        Press (or turn on) the chosen HA entity instead, then reconnect.
        """
        if self.client.state.available:
            return
        if self.power_on_mode == POWER_ON_MODE_WOL:
            await self.client.async_turn_on()
            return
        call = power_on_call(
            self.power_on_mode,
            self.power_on_button,
            self.power_on_remote,
            self.power_on_command,
            self.power_on_device,
            self.client.tv_mac,
        )
        if call is None:
            await self.client.async_turn_on()
            return
        _LOGGER.info(
            "Powering on TV by calling %s.%s with %s",
            call.domain,
            call.service,
            call.data.get(ATTR_ENTITY_ID),
        )
        try:
            await self.hass.services.async_call(
                call.domain,
                call.service,
                call.data,
                blocking=True,
            )
        except HomeAssistantError:
            _LOGGER.exception("Power-on call %s.%s failed", call.domain, call.service)
            return
        await self.client.async_wait_for_broker()
