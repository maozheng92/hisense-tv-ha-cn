"""爱家 login, X-Sign-For, and cloud 我的应用 parsing — no Home Assistant."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json

from conftest import load_proto


class _FakeResponse:
    def __init__(self, status: int, body):
        self.status = status
        self._body = body

    async def json(self, content_type=None):
        return self._body

    async def text(self):
        return json.dumps(self._body, ensure_ascii=False)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, routes: dict[str, object]):
        self.routes = routes
        self.calls: list[tuple[str, str]] = []
        self.bodies: list[object] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method.upper(), url))
        self.bodies.append(kwargs.get("data"))
        for suffix, body in self.routes.items():
            if suffix in url:
                status = 200
                payload = body
                if isinstance(body, tuple):
                    status, payload = body
                return _FakeResponse(status, payload)
        return _FakeResponse(404, {"error": url})


def _account():
    load_proto("apps")
    return load_proto("aijia_account")


def test_sign_is_md5_of_body_plus_web_secret() -> None:
    account = _account()
    body = '{"appType":1}'
    digest = hashlib.md5(
        (body + account.APP_SECRET).encode("utf-8"), usedforsecurity=False
    ).digest()
    assert account.sign_body(body) == base64.b64encode(digest).decode("ascii")
    headers = account.signed_headers(body)
    assert headers["appKey"] == "commonweb"
    assert headers["X-Sign-For"] == account.sign_body(body)
    assert "Authorization" not in headers


def test_portal_encrypt_hides_plaintext() -> None:
    account = _account()
    secret = account.encrypt_portal("13800138000")
    assert "13800138000" not in secret
    assert base64.b64decode(secret)


def test_parse_login_reads_token_info() -> None:
    account = _account()
    tokens = account.parse_login(
        {
            "data": {
                "resultCode": 0,
                "customerId": "cust-1",
                "tokenInfo": {
                    "token": "access-1",
                    "refreshToken": "refresh-1",
                    "tokenExpiredTime": 100,
                },
            }
        }
    )
    assert tokens.access_token == "access-1"
    assert tokens.refresh_token == "refresh-1"
    assert tokens.customer_id == "cust-1"
    assert tokens.token_ttl == 100
    blob = tokens.to_entry()
    assert "password" not in blob
    assert blob["aijia_access_token"] == "access-1"
    assert account.tokens_from_entry(blob).logged_in


def test_pick_tv_prefers_wifi_mac_and_tv_product() -> None:
    account = _account()
    fridge = {
        "deviceId": "fridge",
        "product": {"name": "冰箱"},
        "wifiId": "111111111111",
    }
    tv = {
        "deviceId": "tv-1",
        "product": {"name": "海信电视 E7N Pro"},
        "wifiId": "AABBCCDDEEFF",
        "ip": "192.168.1.20",
    }
    chosen = account.pick_tv_device(
        [fridge, tv], host="192.168.1.20", mac="aa:bb:cc:dd:ee:ff"
    )
    assert chosen is not None
    assert chosen["deviceId"] == "tv-1"
    assert account.pick_tv_device([fridge, tv], device_id="fridge")["deviceId"] == "fridge"


def test_extract_cloud_apps_filters_tiles_by_mqtt_names() -> None:
    account = _account()
    apps = account.extract_cloud_apps(
        {
            "mqttAppNameList": ["云视听极光"],
            "columns": [
                {
                    "columnName": "我的应用",
                    "tiles": [
                        {
                            "name": "云视听极光",
                            "startupType": 4,
                            "packageName": "com.ktcp.video",
                        },
                        {
                            "name": "推荐广告",
                            "packageName": "com.ad",
                            "startupType": 4,
                        },
                    ],
                }
            ],
        }
    )
    assert [item["name"] for item in apps] == ["云视听极光"]
    assert apps[0]["package"] == "com.ktcp.video"


def test_async_login_and_fetch_apps_from_device_state() -> None:
    account = _account()
    tv = {
        "deviceId": "tv-1",
        "wifiId": "aabbccddeeff",
        "product": {"name": "Hisense VIDAA TV"},
        "states": {
            "mqttAppNameList": [
                {
                    "name": "健身镜",
                    "packageName": "com.hisense.fitness",
                    "isLocalApp": 1,
                }
            ]
        },
    }
    session = FakeSession(
        {
            "/mobile/se/signon": {
                "data": {
                    "resultCode": 0,
                    "tokenInfo": {
                        "token": "tok",
                        "refreshToken": "ref",
                        "customerId": "c1",
                    },
                }
            },
            "/4.0/iot/home/list": {
                "payload": {"status": "SUCCESS", "homes": [{"id": "home-1"}]}
            },
            "/4.0/iot/devices/list": {
                "payload": {"status": "SUCCESS", "devices": [tv]}
            },
        }
    )

    async def _run():
        tokens = await account.async_login(session, "13800138000", "secret")
        assert tokens.access_token == "tok"
        signed = session.calls[0]
        assert signed[0] == "POST"
        assert "signon" in signed[1]
        updated, apps = await account.async_fetch_apps(
            session, tokens, host="192.168.1.8", mac="aa:bb:cc:dd:ee:ff"
        )
        assert updated.device_id == "tv-1"
        assert [item["name"] for item in apps] == ["健身镜"]
        assert apps[0]["package"] == "com.hisense.fitness"

    asyncio.run(_run())


def test_signed_headers_include_token_when_given() -> None:
    account = _account()
    headers = account.signed_headers("{}", "tok-1")
    assert headers["Authorization"] == "tok-1"
    assert headers["accessToken"] == "tok-1"


def test_parse_login_accepts_0000_result_code() -> None:
    account = _account()
    tokens = account.parse_login(
        {
            "data": {
                "resultCode": "0000",
                "customerId": "cust-2",
                "token": "tok-2",
                "refreshToken": "ref-2",
            }
        }
    )
    assert tokens.access_token == "tok-2"
    assert tokens.customer_id == "cust-2"


def test_pick_tv_matches_nested_ip() -> None:
    account = _account()
    tv = {
        "deviceId": "tv-nested",
        "wifiInfo": {"ip": "192.168.1.8"},
        "product": {"name": "空调"},
    }
    picked = account.pick_tv_device([tv], host="192.168.1.8")
    assert picked is not None
    assert picked["deviceId"] == "tv-nested"


def test_fetch_apps_uses_columns_when_iot_forbidden() -> None:
    account = _account()
    session = FakeSession(
        {
            "/4.0/iot/home/list": (403, {"error": "no"}),
            "/4.0/iot/devices/list": (403, {"error": "no"}),
            "/api/columns": {
                "mqttAppNameList": [
                    {
                        "name": "云视听极光",
                        "packageName": "com.ktcp.video",
                        "isLocalApp": 1,
                    }
                ]
            },
        }
    )

    async def _run():
        tokens = account.AijiaTokens(access_token="tok", customer_id="c1")
        updated, apps = await account.async_fetch_apps(session, tokens)
        assert [item["name"] for item in apps] == ["云视听极光"]
        assert apps[0]["package"] == "com.ktcp.video"
        assert updated.access_token == "tok"

    asyncio.run(_run())


def test_extract_cloud_apps_from_named_state_list() -> None:
    account = _account()
    apps = account.extract_cloud_apps(
        {
            "deviceId": "tv-1",
            "states": [
                {"name": "onlineStatus", "value": "1"},
                {
                    "name": "mqttAppNameList",
                    "value": json.dumps(
                        [
                            {
                                "name": "健身镜",
                                "packageName": "com.hisense.fitness",
                                "isLocalApp": 1,
                            }
                        ],
                        ensure_ascii=False,
                    ),
                },
            ],
        }
    )
    assert [item["name"] for item in apps] == ["健身镜"]
    assert apps[0]["package"] == "com.hisense.fitness"


def test_fetch_apps_from_extend_state() -> None:
    account = _account()
    session = FakeSession(
        {
            "/4.0/iot/home/list": {
                "payload": {"status": "SUCCESS", "homes": [{"id": "home-1"}]}
            },
            "/4.0/iot/devices/list": {
                "payload": {
                    "status": "SUCCESS",
                    "devices": [
                        {
                            "deviceId": "tv-1",
                            "wifiId": "aabbccddeeff",
                            "categoryCode": "connector.device.type.tv",
                            "nickname": "客厅电视",
                            "states": [{"name": "onlineStatus", "value": "1"}],
                        }
                    ],
                }
            },
            "/4.0/iot/state/getExtendState": {
                "payload": {
                    "status": "SUCCESS",
                    "mqttAppNameList": [
                        {
                            "name": "健身镜",
                            "packageName": "com.hisense.fitness",
                            "isLocalApp": 1,
                        }
                    ],
                }
            },
        }
    )

    async def _run():
        tokens = account.AijiaTokens(access_token="tok", customer_id="c1")
        updated, apps = await account.async_fetch_apps(
            session, tokens, host="192.168.1.8", mac="aa:bb:cc:dd:ee:ff"
        )
        assert updated.device_id == "tv-1"
        assert updated.wifi_id == "aabbccddeeff"
        assert [item["name"] for item in apps] == ["健身镜"]
        assert any("getExtendState" in url for _method, url in session.calls)

    asyncio.run(_run())


def test_wifi_from_nested_additional_and_device_id() -> None:
    account = _account()
    nested = {
        "deviceId": "86100300900000300000050593af4296",
        "additional": {"wifiId": "AA:BB:CC:DD:EE:FF"},
        "categoryCode": "connector.device.type.TV",
    }
    assert account._wifi_from_device(nested) == "aabbccddeeff"
    bare = {"deviceId": "86100300900000300000050593af4296"}
    assert account._wifi_from_device(bare) == ""
    assert account._wifi_from_device_id(bare) == "050593af4296"


def test_fetch_apps_fills_wifi_id_from_config_mac() -> None:
    account = _account()
    session = FakeSession(
        {
            "/4.0/iot/home/list": {
                "payload": {"status": "SUCCESS", "homes": [{"id": "home-1"}]}
            },
            "/4.0/iot/devices/list": {
                "payload": {
                    "status": "SUCCESS",
                    "devices": [
                        {
                            "deviceId": "86100300900000300000050593af4296",
                            "categoryCode": "connector.device.type.TV",
                            "nickname": "客厅电视",
                            "states": [{"name": "onlineStatus", "value": "1"}],
                        }
                    ],
                }
            },
            "/api/columns": {
                "mqttAppNameList": [
                    {
                        "name": "云视听极光",
                        "packageName": "com.ktcp.video",
                        "isLocalApp": 1,
                    }
                ]
            },
        }
    )

    async def _run():
        tokens = account.AijiaTokens(access_token="tok", customer_id="c1")
        updated, apps = await account.async_fetch_apps(
            session, tokens, mac="aa:bb:cc:dd:ee:ff"
        )
        assert updated.wifi_id == "aabbccddeeff"
        assert [item["name"] for item in apps] == ["云视听极光"]

    asyncio.run(_run())


def test_fetch_skips_iot_error_payload_then_reads_extend_state() -> None:
    account = _account()
    session = FakeSession(
        {
            "/4.0/iot/home/list": {
                "payload": {"status": "SUCCESS", "homes": [{"id": "home-1"}]}
            },
            "/4.0/iot/devices/list": {
                "payload": {
                    "status": "SUCCESS",
                    "devices": [
                        {
                            "deviceId": "tv-1",
                            "wifiId": "aabbccddeeff",
                            "categoryCode": "connector.device.type.tv",
                            "nickname": "客厅电视",
                            "states": [{"name": "onlineStatus", "value": "1"}],
                        }
                    ],
                }
            },
            "/4.0/iot/devices/detail": {
                "payload": {
                    "status": "FAIL",
                    "errorCode": "400",
                    "errorDesc": "partner mismatch",
                }
            },
            "/4.0/iot/state/getExtendState": {
                "payload": {
                    "status": "SUCCESS",
                    "mqttAppNameList": [
                        {
                            "name": "健身镜",
                            "packageName": "com.hisense.fitness",
                            "isLocalApp": 1,
                        }
                    ],
                }
            },
        }
    )

    async def _run():
        tokens = account.AijiaTokens(access_token="tok", customer_id="c1")
        updated, apps = await account.async_fetch_apps(session, tokens)
        assert updated.device_id == "tv-1"
        assert [item["name"] for item in apps] == ["健身镜"]

    asyncio.run(_run())


def test_summarize_json_includes_error_desc() -> None:
    account = _account()
    text = account._summarize_json({"resultCode": 1, "errorDesc": "wifiId不能为空"})
    assert "wifiId不能为空" in text
    nested = account._summarize_json(
        {"payload": {"status": "FAIL", "errorCode": "X", "errorDesc": "partner mismatch"}}
    )
    assert "partner mismatch" in nested
    msg = account._summarize_json({"resultCode": 1, "errorMsg": "device not bind"})
    assert "device not bind" in msg


def test_extend_state_sends_com_module_id() -> None:
    account = _account()
    session = FakeSession(
        {
            "/4.0/iot/home/list": {
                "payload": {"status": "SUCCESS", "homes": [{"id": "home-1"}]}
            },
            "/4.0/iot/devices/list": {
                "payload": {
                    "status": "SUCCESS",
                    "devices": [
                        {
                            "deviceId": "tv-1",
                            "comModuleId": "com-mod-1",
                            "homeId": "home-1",
                            "partner": {"id": "1000"},
                            "categoryCode": "connector.device.type.TV",
                            "nickname": "客厅电视",
                            "states": [{"name": "onlineStatus", "value": "1"}],
                        }
                    ],
                }
            },
            "/4.0/iot/state/getExtendState": {
                "payload": {
                    "status": "SUCCESS",
                    "mqttAppNameList": [
                        {
                            "name": "健身镜",
                            "packageName": "com.hisense.fitness",
                            "isLocalApp": 1,
                        }
                    ],
                }
            },
        }
    )

    async def _run():
        tokens = account.AijiaTokens(access_token="tok", customer_id="c1")
        updated, apps = await account.async_fetch_apps(session, tokens)
        assert updated.com_module_id == "com-mod-1"
        assert [item["name"] for item in apps] == ["健身镜"]
        assert any(
            isinstance(body, str) and "com-mod-1" in body and "payloadVersion" in body
            for body in session.bodies
        )

    asyncio.run(_run())


def test_login_id_from_nested_data() -> None:
    account = _account()
    assert (
        account._login_id_from_blob({"data": {"tvLoginedId": "tv-token-123456"}})
        == "tv-token-123456"
    )
    assert account._login_id_from_blob({"accessToken": "phone-token-xxx"}) == ""


def test_parse_login_rejects_bad_password() -> None:
    account = _account()
    try:
        account.parse_login({"data": {"resultCode": 1, "errorDesc": "密码错误"}})
    except account.AijiaAuthError as err:
        assert "密码错误" in str(err)
    else:
        raise AssertionError("expected AijiaAuthError")
