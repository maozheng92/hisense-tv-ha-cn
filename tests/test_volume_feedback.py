"""Inbound volume/mute must change media_player 0–1 level and mute flag.

爱家 7.0.8.12 has no TV volume/mute telemetry (no volume_value, mute_status,
getvolume). Mute is a local remoter icon. This E7N also never publishes
platform_service volumechange. When an OSD / gettvstate does arrive it uses
volume_type=1 (eARC; sehaas/pyvidaa ignore that). Type 2 / mute_status is
mute if the TV ever sends it.
"""

from __future__ import annotations


_OSD_STATE = b'{"volume_value": 18, "volume_type": 1, "state": 1}'
_MUTE_STATE = b'{"volume_type": 2, "volume_value": 1, "state": 1}'
_UNMUTE_STATE = b'{"volume_type": 2, "volume_value": 0, "state": 1}'
_GETVOLUME = b'{"volume_value": 24, "mute_status": 1}'
_STATE_TOPIC = "/remoteapp/mobile/broadcast/ui_service/state"
_NESTED_STATE = (
    b'{"statetype":"app","name":"Netflix",'
    b'"infoPackage":{"volume_value":22,"volume_type":1,"mute_status":1}}'
)


def test_ui_service_osd_type1_sets_volume_level(proto_client) -> None:
    """eARC OSD volume_type=1 is the current level, not ignored."""
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.available = True
    assert client.state.media_volume_level() is None
    client._handle_message(_STATE_TOPIC, _OSD_STATE)
    assert client.state.volume == 18
    assert client.state.volume_type == 1
    assert client.state.media_volume_level() == 0.18
    assert client.state.media_is_volume_muted() is None
    assert "ui_service/state" in (client.state.volume_topic or "")


def test_volume_type_0_and_1_are_both_levels(proto_client) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.available = True
    client._apply_volume({"volume_type": 0, "volume_value": 12})
    assert client.state.media_volume_level() == 0.12
    client._apply_volume({"volume_type": 1, "volume_value": 18})
    assert client.state.media_volume_level() == 0.18
    assert client.state.volume_type == 1
    client._apply_volume({"volume_type": 1, "volume_value": 1})
    assert client.state.volume == 1
    assert client.state.media_volume_level() == 0.01


def test_ui_service_mute_updates_is_volume_muted(proto_client) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.available = True
    client._handle_message(_STATE_TOPIC, _OSD_STATE)
    assert client.state.media_volume_level() == 0.18
    client._handle_message(_STATE_TOPIC, _MUTE_STATE)
    assert client.state.media_is_volume_muted() is True
    assert client.state.media_volume_level() == 0.18
    client._handle_message(_STATE_TOPIC, _UNMUTE_STATE)
    assert client.state.media_is_volume_muted() is False


def test_unicast_state_osd_and_mute(proto_client, proto_credentials) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    creds = proto_credentials.generate_dynamic_credentials(
        "aa:bb:cc:dd:ee:ff", timestamp=1
    )
    client.state.available = True
    topic = f"/remoteapp/mobile/{creds.client_id}/ui_service/state"
    client._handle_message(topic, _OSD_STATE)
    assert client.state.media_volume_level() == 0.18
    client._handle_message(topic, _MUTE_STATE)
    assert client.state.media_is_volume_muted() is True
    assert client.state.media_volume_level() == 0.18


def test_nested_infopackage_volume_and_mute_status(proto_client) -> None:
    """gettvstate / full ui_service/state nests volume under infoPackage."""
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.available = True
    client.state.power_on = True
    client._handle_message(_STATE_TOPIC, _NESTED_STATE)
    assert client.state.statetype == "app"
    assert client.state.media_volume_level() == 0.22
    assert client.state.volume_type == 1
    assert client.state.media_is_volume_muted() is True


def test_platform_service_getvolume_sets_level_and_mute(
    proto_client, proto_credentials
) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    creds = proto_credentials.generate_dynamic_credentials(
        "aa:bb:cc:dd:ee:ff", timestamp=1
    )
    client.state.available = True
    client._handle_message(
        f"/remoteapp/mobile/{creds.client_id}/platform_service/data/volume",
        _GETVOLUME,
    )
    assert client.state.media_volume_level() == 0.24
    assert client.state.media_is_volume_muted() is True


def test_screenshot_metadata_sets_volume(proto_client) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.available = True
    client._apply_volume_tree(
        {
            "infoPackage": {
                "volume_value": 31,
                "mute_status": 0,
                "curAppInfo": {"curAppName": "聚好看"},
            }
        },
        topic="screenshot",
    )
    assert client.state.media_volume_level() == 0.31
    assert client.state.media_is_volume_muted() is False
    assert client.state.volume_topic == "screenshot"


def test_offline_hides_mute(proto_client) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.available = False
    client.state.muted = True
    assert client.state.media_is_volume_muted() is None


def test_volume_on_unexpected_topic_is_still_parsed(proto_client) -> None:
    """Wildcard /remoteapp/# delivers topics we never listed explicitly."""
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.available = True
    client._handle_message(
        "/remoteapp/mobile/broadcast/platform_service/data/soundinfo",
        b'{"volume_value": 27, "volume_type": 1, "mute_status": 0}',
    )
    assert client.state.media_volume_level() == 0.27
    assert client.state.volume_type == 1
    assert client.state.media_is_volume_muted() is False


def test_refresh_volume_state_does_not_applist(
    proto_client, proto_credentials
) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    creds = proto_credentials.generate_dynamic_credentials(
        "aa:bb:cc:dd:ee:ff", timestamp=1
    )
    client._creds = creds
    calls: list[tuple] = []

    def publish_action(service, action, payload, *, as_key=False):
        calls.append((service, action, payload, as_key))

    client._publish_action = publish_action  # type: ignore[method-assign]
    client.refresh_volume_state()
    assert {action for _s, action, _p, _k in calls} == {"gettvstate", "getvolume"}
    assert not any(action == "applist" for _s, action, _p, _k in calls)


def test_unknown_mute_is_not_shown_as_unmuted(proto_client) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.available = True
    assert client.state.muted is None
    assert client.state.media_is_volume_muted() is None


def test_key_mute_toggles_like_aijia_button(proto_client, monkeypatch) -> None:
    """爱家 _buttonMute: first KEY_MUTE from unknown → muted, then toggle."""
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.available = True
    client._control_warmup = False
    client._last_remoter_ok_at = 10_000.0
    keys: list[str] = []
    calls: list[tuple] = []

    def publish_action(service, action, payload, *, as_key=False):
        calls.append((service, action, payload, as_key))

    monkeypatch.setattr(client, "_publish_action", publish_action)
    monkeypatch.setattr(proto_client, "remoter_reachable", lambda host, **kwargs: True)
    monkeypatch.setattr(
        proto_client, "send_local_key", lambda host, key, **kwargs: keys.append(key) or 200
    )
    client.send_key("KEY_MUTE")
    assert keys == ["KEY_MUTE"]
    assert client.state.muted is True
    assert client.state.media_is_volume_muted() is True
    client.send_key("KEY_MUTE")
    assert keys == ["KEY_MUTE", "KEY_MUTE"]
    assert client.state.muted is False
    assert client.state.media_is_volume_muted() is False
    assert {action for _s, action, _p, _k in calls} == {"gettvstate", "getvolume"}


def test_failed_mute_key_does_not_toggle(proto_client, monkeypatch) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.available = True
    monkeypatch.setattr(client, "_publish_action", lambda *a, **k: None)
    monkeypatch.setattr(proto_client, "send_local_key", lambda host, key, **kwargs: None)
    try:
        client.send_key("KEY_MUTE")
    except ConnectionError:
        pass
    assert client.state.muted is None
    assert client.state.media_is_volume_muted() is None
