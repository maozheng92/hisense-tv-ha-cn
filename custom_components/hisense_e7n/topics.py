"""VIDAA ``/remoteapp/`` topic helpers.

This TV's broker appears to cap how many concrete subscriptions it
keeps. 1.23.9 added many volume topics and the volume OSD on
``broadcast/ui_service/state`` stopped arriving. Subscribe
``/remoteapp/#`` first (pyvidaa confirmed the TV grants it), then the
broadcasts that actually carry volume, then unicast replies.
"""

from __future__ import annotations

from .credentials import MqttCredentials


def _tv_action(creds: MqttCredentials, service: str, action: str) -> str:
    return f"/remoteapp/tv/{service}/{creds.client_id}/actions/{action}"


def _mobile_data(creds: MqttCredentials, service: str, data_type: str) -> str:
    return f"/remoteapp/mobile/{creds.client_id}/{service}/data/{data_type}"


def command_identities(creds: MqttCredentials, tv_mac: str | None = None) -> list[str]:
    """Topic identity the broker actually routes.

    sendkey is delivered only to the ``client_id`` of this MQTT session
    (``{uuid}$his${hash}_vidaacommon_001`` or the static ``$vidaa_common`` /
    ``$normal`` id we connected with). The TV Wi-Fi MAC is not that id.
    ``tv_mac`` is accepted so older callers keep working and is not used.
    """
    del tv_mac
    client_id = (creds.client_id or "").strip()
    return [client_id] if client_id else []


def action_topics(
    creds: MqttCredentials,
    service: str,
    action: str,
    tv_mac: str | None = None,
) -> list[str]:
    return [
        f"/remoteapp/tv/{service}/{ident}/actions/{action}"
        for ident in command_identities(creds, tv_mac)
    ]


def sendkey(creds: MqttCredentials) -> str:
    return _tv_action(creds, "remote_service", "sendkey")


def gettvstate(creds: MqttCredentials) -> str:
    return _tv_action(creds, "ui_service", "gettvstate")


def sourcelist(creds: MqttCredentials) -> str:
    return _tv_action(creds, "ui_service", "sourcelist")


def changesource(creds: MqttCredentials) -> str:
    return _tv_action(creds, "ui_service", "changesource")


def launchapp(creds: MqttCredentials) -> str:
    return _tv_action(creds, "ui_service", "launchapp")


def applist(creds: MqttCredentials) -> str:
    return _tv_action(creds, "ui_service", "applist")


def vidaa_app_connect(creds: MqttCredentials) -> str:
    return _tv_action(creds, "ui_service", "vidaa_app_connect")


def authenticationcode(creds: MqttCredentials) -> str:
    return _tv_action(creds, "ui_service", "authenticationcode")


def login_each_other_info(creds: MqttCredentials) -> str:
    return _tv_action(creds, "ui_service", "login_each_other_info")


def getvolume(creds: MqttCredentials) -> str:
    return _tv_action(creds, "platform_service", "getvolume")


def changevolume(creds: MqttCredentials) -> str:
    return _tv_action(creds, "platform_service", "changevolume")


_MOBILE_DATA = (
    ("ui_service", "authentication"),
    ("ui_service", "authenticationcodetoast"),
    ("ui_service", "authenticationcode"),
    ("ui_service", "authenticationcodeclose"),
    ("ui_service", "tokenissuance"),
    ("ui_service", "state"),
    ("ui_service", "sourcelist"),
    ("ui_service", "applist"),
    ("ui_service", "vidaa_app_connect"),
    ("ui_service", "volume"),
    ("platform_service", "volume"),
    ("platform_service", "volumechange"),
    ("platform_service", "getvolume"),
    ("platform_service", "tokenissuance"),
)

_WILDCARDS = (
    "/remoteapp/#",
)

_BROADCASTS = (
    "/remoteapp/mobile/broadcast/ui_service/state",
    "/remoteapp/mobile/broadcast/ui_service/data/state",
    "/remoteapp/mobile/broadcast/platform_service/actions/volumechange",
    "/remoteapp/mobile/broadcast/platform_service/data/volumechange",
    "/remoteapp/mobile/broadcast/ui_service/volume",
    "/remoteapp/mobile/broadcast/ui_service/data/volume",
    "/remoteapp/mobile/broadcast/platform_service/volume",
    "/remoteapp/mobile/broadcast/platform_service/data/volume",
    "/remoteapp/mobile/broadcast/platform_service/data/getvolume",
    "/remoteapp/mobile/broadcast/platform_service/actions/tvsleep",
    "/remoteapp/mobile/broadcast/ui_service/data/applist",
)


def subscription_topics(creds: MqttCredentials, tv_mac: str | None = None) -> list[str]:
    topics: list[str] = []
    seen: set[str] = set()

    def _add(topic: str) -> None:
        if topic and topic not in seen:
            seen.add(topic)
            topics.append(topic)

    for topic in _WILDCARDS:
        _add(topic)
    for topic in _BROADCASTS:
        _add(topic)
    for ident in command_identities(creds, tv_mac):
        _add(f"/remoteapp/mobile/{ident}/ui_service/state")
        _add(f"/remoteapp/mobile/{ident}/ui_service/data/state")
        _add(f"/remoteapp/mobile/{ident}/ui_service/volume")
        _add(f"/remoteapp/mobile/{ident}/platform_service/data/volume")
        _add(f"/remoteapp/mobile/{ident}/platform_service/actions/volumechange")
        _add(f"/remoteapp/mobile/{ident}/platform_service/data/volumechange")
        for service, data_type in _MOBILE_DATA:
            _add(f"/remoteapp/mobile/{ident}/{service}/data/{data_type}")
    return topics
