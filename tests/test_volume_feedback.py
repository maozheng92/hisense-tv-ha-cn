"""Inbound volume/mute must change media_player 0–1 level and mute flag.

This E7N's HA logs never showed platform_service volumechange. They DID
show partial ui_service/state during the volume OSD:

    {"volume_value": 18, "volume_type": 1, "state": 1}
"""

from __future__ import annotations


_OSD_STATE = b'{"volume_value": 18, "volume_type": 1, "state": 1}'
_MUTE_STATE = b'{"volume_type": 2, "volume_value": 1, "state": 1}'
_UNMUTE_STATE = b'{"volume_type": 2, "volume_value": 0, "state": 1}'
_GETVOLUME = b'{"volume_value": 24, "mute_status": 1}'
_STATE_TOPIC = "/remoteapp/mobile/broadcast/ui_service/state"


def test_ui_service_osd_sets_volume_level(proto_client) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client.state.available = True
    assert client.state.media_volume_level() is None
    client._handle_message(_STATE_TOPIC, _OSD_STATE)
    assert client.state.volume == 18
    assert client.state.volume_type == 1
    assert client.state.media_volume_level() == 0.18
    assert client.state.media_is_volume_muted() is False
    assert "ui_service/state" in (client.state.volume_topic or "")


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
