"""Topic builders, key aliases, and MQTT payload parsing."""

from __future__ import annotations

import time


def test_platforms_match_tcl_no_button_entities(proto_const) -> None:
    assert proto_const.PLATFORMS == ("media_player", "remote", "select")
    assert proto_const.ATTR_HIDDEN == "hidden"


def test_key_aliases_match_aijia(proto_keys) -> None:
    assert proto_keys.normalize_key("power") == proto_keys.KEY_POWER
    assert proto_keys.normalize_key("KEY_HOME") == proto_keys.KEY_HOME
    assert proto_keys.normalize_key("ok") == "KEY_OK"
    assert proto_keys.normalize_key("jubao") == "KEY_JUBAO"
    assert proto_keys.normalize_key("returns") == "KEY_RETURNS"
    assert proto_keys.normalize_key("settings") == proto_keys.KEY_CONTROL_CENTER
    assert proto_keys.normalize_key("screenshot") == "screenshot"
    assert proto_keys.normalize_key("截屏") == "screenshot"
    assert proto_keys.normalize_key("capture") == "screenshot"


def test_aijia_remoter_has_screenshot_keys(proto_keys) -> None:
    slugs = [item.slug for item in proto_keys.AIJIA_REMOTER_BUTTONS]
    assert slugs == [
        "power",
        "volume_down",
        "mute",
        "volume_up",
        "screenshot",
        "source",
        "smart_image",
        "settings",
        "up",
        "left",
        "ok",
        "right",
        "down",
        "back",
        "home",
        "menu",
    ]
    commands = proto_keys.aijia_send_commands()
    assert "KEY_HOME" in commands
    assert "KEY_CONTROL_CENTER" in commands
    assert "screenshot" in commands
    assert "smart_image" in commands


def test_sendkey_topic_uses_client_id(proto_credentials, proto_topics) -> None:
    creds = proto_credentials.generate_dynamic_credentials(
        "56:b8:88:4e:f7:19", timestamp=1766974704
    )
    topic = proto_topics.sendkey(creds)
    assert topic.startswith("/remoteapp/tv/remote_service/")
    assert topic.endswith("/actions/sendkey")
    assert creds.client_id in topic
    assert "HomeAssistant" not in topic


def test_sendkey_uses_connected_client_only(proto_credentials, proto_topics) -> None:
    creds = proto_credentials.generate_dynamic_credentials(
        "12:34:56:78:9a:bc", timestamp=1766974704
    )
    topics = proto_topics.action_topics(
        creds, "remote_service", "sendkey", tv_mac="aa:bb:cc:dd:ee:ff"
    )
    assert topics == [
        f"/remoteapp/tv/remote_service/{creds.client_id}/actions/sendkey"
    ]
    assert "aa:bb:cc:dd:ee:ff" not in topics[0]


def test_pair_topic_and_subscriptions_are_concrete(proto_client, proto_credentials, proto_topics) -> None:
    creds = proto_credentials.generate_dynamic_credentials(
        "56:b8:88:4e:f7:19", timestamp=1766974704
    )
    assert proto_client.CONNECT_PAYLOAD["device_type"] == "Mobile App"
    assert proto_topics.vidaa_app_connect(creds).endswith("/actions/vidaa_app_connect")
    subs = proto_topics.subscription_topics(creds)
    assert not any(item.endswith("#") or "/+" in item for item in subs)
    assert "/remoteapp/mobile/broadcast/ui_service/state" in subs
    assert "/remoteapp/mobile/broadcast/platform_service/actions/tvsleep" in subs
    assert "/remoteapp/mobile/broadcast/platform_service/data/volumechange" in subs
    assert "/remoteapp/mobile/broadcast/platform_service/actions/volumechange" in subs


def test_volume_and_source_parsing(proto_client) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client._apply_volume({"volume_value": 24, "mute": 1})
    assert client.state.volume == 24
    assert client.state.muted is True
    client._apply_volume({"volume_value": 24, "mute_status": 0})
    assert client.state.muted is False
    client._apply_volume("40")
    assert client.state.volume == 40
    client._apply_sources(
        [{"sourceid": "3", "sourcename": "HDMI1"}, {"sourceid": "0", "sourcename": "TV"}]
    )
    assert client.state.sources[0]["name"] == "HDMI1"
    client._apply_state({"statetype": "remote_launcher", "sourcename": "HDMI1"})
    assert client.state.power_on is True
    assert client.state.statetype == "remote_launcher"
    client._apply_state({"statetype": "app", "name": "云视听极光", "url": "com.ktcp.video"})
    assert client.state.current_app == "云视听极光"
    assert client.state.source_name == "云视听极光"
    client._apply_state({"statetype": "livetv", "channel_name": "CCTV1"})
    assert client.state.current_app is None


def test_token_issuance_replaces_the_pairing_secret(proto_client) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client._handle_message(
        "/remoteapp/mobile/x/ui_service/data/tokenissuance",
        b'{"accesstoken":"abc","refreshtoken":"def"}',
    )
    assert client.state.access_token == "abc"
    assert client.state.refresh_token == "def"
    assert client.state.already_paired is True
    assert client.state.needs_pin is False


def test_partial_state_does_not_clear_power(proto_client) -> None:
    """Volume OSD often republishes ui_service/state without statetype."""
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.available = True
    client.state.power_on = True
    client._apply_state({"statetype": "livetv", "sourcename": "HDMI1"})
    client._apply_state({"volume_value": 18, "volume_type": 1, "state": 1})
    assert client.state.power_on is True
    assert client.state.statetype == "livetv"
    assert client.state.volume == 18
    assert client.state.volume_type == 1


def test_mqtt_disconnect_does_not_immediately_turn_off(proto_client) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.available = True
    client.state.power_on = True
    client._on_disconnect(None, None, 0)
    assert client.state.available is True
    assert client.state.power_on is True
    client._cancel_offline_timer()


def test_mqtt_reconnect_before_grace_keeps_player_on(proto_client) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.available = True
    client.state.power_on = True
    epoch = client._mqtt_epoch
    client._on_disconnect(None, None, 0)
    client._on_connect(None, None, {}, 0)
    client._apply_mqtt_offline(epoch)
    assert client.state.available is True
    assert client.state.power_on is True
    client._cancel_offline_timer()


def test_mqtt_offline_after_grace_turns_player_off(proto_client) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.available = True
    client.state.power_on = True
    client._on_disconnect(None, None, 0)
    client._apply_mqtt_offline(client._mqtt_epoch)
    assert client.state.available is False
    assert client.state.power_on is False
    client._cancel_offline_timer()


def test_remoter_ok_keeps_player_on_during_mqtt_blip(
    proto_client, monkeypatch
) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.available = True
    client.state.power_on = True
    client._control_warmup = False
    client._last_remoter_ok_at = 10_000.0
    client._last_volume_deliver_at = 0.0
    client._on_disconnect(None, None, 0)
    monkeypatch.setattr(proto_client, "remoter_reachable", lambda host, **kwargs: True)
    monkeypatch.setattr(proto_client, "send_local_key", lambda host, key, **kwargs: 200)
    assert client._send_volume_step("KEY_VOLUMEUP", pause=lambda _delay: None) is True
    assert client.state.available is True
    assert client.state.power_on is True
    client._cancel_offline_timer()


def test_fake_sleep_and_tvsleep_turn_the_player_off(proto_client) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client._apply_state({"statetype": "fake_sleep_0"})
    assert client.state.power_on is False
    client._handle_message(
        "/remoteapp/mobile/broadcast/platform_service/actions/tvsleep",
        b"",
    )
    assert client.state.power_on is False
    assert client.state.statetype == "tvsleep"
    client._apply_state({"statetype": "sourceswitch", "sourcename": "HDMI1"})
    assert client.state.power_on is True
    assert client.state.source_name == "HDMI1"


def test_volume_type_2_is_mute(proto_client) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.volume = 30
    client._apply_volume({"volume_type": 2, "volume_value": 1})
    assert client.state.muted is True
    assert client.state.volume == 30
    client._apply_volume({"volume_type": 0, "volume_value": 12})
    assert client.state.volume == 12
    assert client.state.volume_type == 0
    client._apply_volume({"volume_type": 1, "volume_value": 18})
    assert client.state.volume == 18
    assert client.state.volume_type == 1


def test_volumechange_mqtt_sets_mute_status(proto_client) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client._handle_message(
        "/remoteapp/mobile/broadcast/platform_service/data/volumechange",
        b'{"volume_value": 16, "mute_status": 1}',
    )
    assert client.state.volume == 16
    assert client.state.muted is True
    client._handle_message(
        "/remoteapp/mobile/broadcast/platform_service/actions/volumechange",
        b'{"volume_value": 16, "mute": 0}',
    )
    assert client.state.muted is False


def test_pairing_request_is_only_vidaa_app_connect(proto_client, proto_credentials) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="12:34:56:78:9a:bc")
    client._creds = proto_credentials.generate_dynamic_credentials(
        "12:34:56:78:9a:bc", timestamp=1
    )
    published: list[tuple[str, str]] = []

    class FakeMqtt:
        def publish(self, topic, body, qos=0, retain=False):
            published.append((topic, body))

            class Info:
                rc = proto_client.mqtt.MQTT_ERR_SUCCESS

                def wait_for_publish(self, timeout=None):
                    return None

            return Info()

    client._client = FakeMqtt()
    client.start_pairing()
    assert len(published) == 1
    topic, body = published[0]
    assert topic.endswith("/actions/vidaa_app_connect")
    assert "login_each_other_info" not in topic
    assert '"device_type":"Mobile App"' in body
    assert client.state.pin_requested is True
    published.clear()
    client.submit_code("0123")
    assert published[0][1] == '{"authNum":123}'


def test_send_key_publishes_raw_key_only(proto_client, proto_credentials) -> None:
    client = proto_client.HisenseTvClient(
        "127.0.0.1",
        uuid="12:34:56:78:9a:bc",
        tv_mac="aa:bb:cc:dd:ee:ff",
    )
    client._creds = proto_credentials.generate_dynamic_credentials(
        "12:34:56:78:9a:bc", timestamp=1
    )
    published: list[tuple[str, str]] = []

    class FakeMqtt:
        def publish(self, topic, body, qos=0, retain=False):
            published.append((topic, body))

            class Info:
                rc = proto_client.mqtt.MQTT_ERR_SUCCESS

                def wait_for_publish(self, timeout=None):
                    return None

            return Info()

    client._client = FakeMqtt()
    client.send_key("home")
    topics = [topic for topic, _ in published]
    payloads = [payload for _, payload in published]
    assert topics
    assert all(client._creds.client_id in topic for topic in topics)
    assert not any("aa:bb:cc:dd:ee:ff$vidaa_common" in topic for topic in topics)
    assert payloads == ["KEY_HOME"]
    assert not any(topic.endswith("/actions/vidaa_app_connect") for topic in topics)


def test_wol_packet_shape(proto_client, monkeypatch) -> None:
    sent: list[tuple[bytes, tuple]] = []

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def setsockopt(self, *args):
            return None

        def sendto(self, packet, addr):
            sent.append((packet, addr))

    monkeypatch.setattr(proto_client.socket, "socket", lambda *a, **k: FakeSock())
    proto_client.send_wol("aa:bb:cc:dd:ee:ff")
    packet, addr = sent[0]
    assert packet.startswith(b"\xff" * 6)
    assert packet.count(bytes.fromhex("aabbccddeeff")) == 16
    assert addr[1] == 9


def test_volume_step_lan_only_no_mqtt(
    proto_client, proto_credentials, monkeypatch
) -> None:
    """MQTT sendkey does not move volume — LAN remoter KEY only."""
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client._creds = proto_credentials.generate_dynamic_credentials(
        "aa:bb:cc:dd:ee:ff", timestamp=1
    )
    client.state.volume = None
    client.state.volume_type = None
    client._control_warmup = False
    client._last_remoter_ok_at = 10_000.0
    client._last_volume_deliver_at = 0.0
    keys: list[str] = []
    calls: list[tuple] = []

    def publish_action(service, action, payload, *, as_key=False):
        calls.append((service, action, payload, as_key))

    monkeypatch.setattr(proto_client, "remoter_reachable", lambda host, **kwargs: True)
    monkeypatch.setattr(
        proto_client, "send_local_key", lambda host, key, **kwargs: keys.append(key) or 200
    )
    monkeypatch.setattr(client, "_publish_action", publish_action)
    assert client._send_volume_step("KEY_VOLUMEUP", pause=lambda _delay: None) is True
    assert keys == ["KEY_VOLUMEUP"]
    assert calls == []


def test_volume_step_paces_between_presses(
    proto_client, proto_credentials, monkeypatch
) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client._creds = proto_credentials.generate_dynamic_credentials(
        "aa:bb:cc:dd:ee:ff", timestamp=1
    )
    client._control_warmup = False
    client._last_remoter_ok_at = 10_000.0
    client._last_volume_deliver_at = time.monotonic()
    pauses: list[float] = []

    monkeypatch.setattr(client, "_publish_action", lambda *a, **k: None)
    monkeypatch.setattr(proto_client, "remoter_reachable", lambda host, **kwargs: True)
    monkeypatch.setattr(proto_client, "send_local_key", lambda *a, **k: 200)
    assert (
        client._send_volume_step("KEY_VOLUMEUP", pause=lambda delay: pauses.append(delay))
        is True
    )
    assert any(p >= 0.5 for p in pauses)


def test_volume_step_lan_miss_does_not_mqtt(proto_client, monkeypatch) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.volume = 5
    client.state.volume_type = 0
    client._control_warmup = False
    client._last_remoter_ok_at = 10_000.0
    client._last_volume_deliver_at = 0.0
    calls: list[tuple] = []

    def publish_action(service, action, payload, *, as_key=False):
        calls.append((service, action, payload, as_key))

    monkeypatch.setattr(client, "_publish_action", publish_action)
    monkeypatch.setattr(proto_client, "remoter_reachable", lambda host, **kwargs: True)
    monkeypatch.setattr(proto_client, "send_local_key", lambda host, key, **kwargs: None)
    assert client._send_volume_step("KEY_VOLUMEUP", pause=lambda _delay: None) is False
    assert calls == []
    assert client.state.volume == 5


def test_set_volume_steps_via_keys(proto_client, proto_credentials, monkeypatch) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client._creds = proto_credentials.generate_dynamic_credentials(
        "aa:bb:cc:dd:ee:ff", timestamp=1
    )
    client.state.volume = 10
    client.state.volume_type = 0
    client._control_warmup = False
    client._last_remoter_ok_at = 10_000.0
    client._last_volume_deliver_at = 0.0
    keys: list[str] = []
    calls: list[tuple] = []

    def publish_action(service, action, payload, *, as_key=False):
        calls.append((service, action, payload, as_key))

    monkeypatch.setattr(client, "_publish_action", publish_action)
    monkeypatch.setattr(proto_client, "remoter_reachable", lambda host, **kwargs: True)
    monkeypatch.setattr(
        proto_client, "send_local_key", lambda host, key, **kwargs: keys.append(key) or 200
    )
    client.set_volume(13, pause=lambda _delay: None)
    assert keys == ["KEY_VOLUMEUP", "KEY_VOLUMEUP", "KEY_VOLUMEUP"]
    assert not any(action in {"sendkey", "changevolume"} for _s, action, _p, _k in calls)
    assert client.state.volume == 13


def test_on_connect_requests_applist(proto_client, proto_credentials) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    creds = proto_credentials.generate_dynamic_credentials(
        "aa:bb:cc:dd:ee:ff", timestamp=1
    )
    client._creds = creds
    published: list[tuple[str, str]] = []

    class FakeMqtt:
        def subscribe(self, topic, qos=0):
            del topic, qos

        def publish(self, topic, body, qos=0, retain=False):
            published.append((topic, body))

            class Info:
                rc = proto_client.mqtt.MQTT_ERR_SUCCESS

                def wait_for_publish(self, timeout=None):
                    return None

            return Info()

    mqtt_client = FakeMqtt()
    client._client = mqtt_client
    client._on_connect(mqtt_client, None, {}, 0)
    assert any(topic.endswith("/actions/applist") for topic, _ in published)
    client.state.pin_requested = True
    published.clear()
    client._on_connect(mqtt_client, None, {}, 0)
    assert not any(topic.endswith("/actions/applist") for topic, _ in published)
