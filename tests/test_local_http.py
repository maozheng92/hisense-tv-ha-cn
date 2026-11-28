"""Local HTTP key channel on ports 7778 and 7779."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest


class _Response(io.BytesIO):
    def __init__(self, status: int) -> None:
        super().__init__(b"ok")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()


class _Body(io.BytesIO):
    def __init__(self, status: int, body: bytes) -> None:
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()


def test_remoter_reachable_uses_tcp(proto_local_http, monkeypatch) -> None:
    seen: list[tuple[str, int]] = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

    def fake_connect(address, timeout=0):
        del timeout
        seen.append(address)
        if address[1] == 7779:
            return FakeSocket()
        raise OSError("down")

    monkeypatch.setattr(proto_local_http.socket, "create_connection", fake_connect)
    assert proto_local_http.remoter_reachable("192.0.2.10") is True
    assert seen[0] == ("192.0.2.10", 7778)
    assert seen[1] == ("192.0.2.10", 7779)


def test_post_key_to_7778(proto_local_http, monkeypatch) -> None:
    seen: list[tuple[str, str]] = []
    proto_local_http.clear_preferred_key_port()

    def fake_urlopen(request, timeout=0):
        del timeout
        seen.append((request.full_url, request.get_method()))
        if request.full_url.startswith("http://192.0.2.10:7778/") and request.get_method() == "POST":
            return _Response(200)
        raise urllib.error.URLError("down")

    monkeypatch.setattr(proto_local_http.urllib.request, "urlopen", fake_urlopen)
    status = proto_local_http.send_local_key("192.0.2.10", "KEY_VOLUMEUP", timeout=0.1)
    assert status == 200
    assert seen == [("http://192.0.2.10:7778/KEY_VOLUMEUP..controller", "POST")]


def test_prefers_sticky_remoter_port(proto_local_http, monkeypatch) -> None:
    """After 7779 works once, skip probing a dead 7778 on the next press."""
    proto_local_http.clear_preferred_key_port()
    seen: list[str] = []
    timeouts: list[float] = []

    def fake_urlopen(request, timeout=0):
        timeouts.append(timeout)
        seen.append(request.full_url)
        if ":7779/" in request.full_url and request.get_method() == "POST":
            return _Response(200)
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(proto_local_http.urllib.request, "urlopen", fake_urlopen)
    assert proto_local_http.send_local_key("192.0.2.10", "KEY_VOLUMEUP", timeout=2.0) == 200
    seen.clear()
    timeouts.clear()
    assert proto_local_http.send_local_key("192.0.2.10", "KEY_VOLUMEDOWN", timeout=2.0) == 200
    assert seen[0].startswith("http://192.0.2.10:7779/")
    assert all(":7778/" not in url for url in seen)
    assert timeouts[0] == 2.0


def test_remoter_reachable_checks_tcp(proto_local_http, monkeypatch) -> None:
    opens: list[tuple] = []

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_connect(addr, timeout=0):
        opens.append((addr, timeout))
        if addr[1] == 7779:
            return FakeSock()
        raise OSError("closed")

    monkeypatch.setattr(proto_local_http.socket, "create_connection", fake_connect)
    assert proto_local_http.remoter_reachable("192.0.2.10", timeout=0.2) is True
    assert opens[0][0] == ("192.0.2.10", 7778)


def test_falls_through_to_7779(proto_local_http, monkeypatch) -> None:
    proto_local_http.clear_preferred_key_port()

    def fake_urlopen(request, timeout=0):
        del timeout
        if ":7779/" in request.full_url and request.get_method() == "POST":
            return _Response(200)
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(proto_local_http.urllib.request, "urlopen", fake_urlopen)
    status = proto_local_http.send_local_key("192.0.2.10", "KEY_OK", timeout=0.1)
    assert status == 200


def test_voice_opens_source(proto_local_http, monkeypatch) -> None:
    seen: list[tuple[str, bytes | None]] = []

    def fake_urlopen(request, timeout=0):
        del timeout
        seen.append((request.full_url, request.data))
        if request.full_url.endswith(":7779/..pushwechatvoice"):
            return _Response(200)
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(proto_local_http.urllib.request, "urlopen", fake_urlopen)
    status = proto_local_http.push_voice("192.0.2.10", "信号源", timeout=0.1)
    assert status == 200
    assert seen[0][0] == "http://192.0.2.10:7779/..pushwechatvoice"
    assert b'"voice":"\xe4\xbf\xa1\xe5\x8f\xb7\xe6\xba\x90"' in seen[0][1]


def test_capture_saves_uploaded_frame(proto_local_http, monkeypatch) -> None:
    jpeg = b"\xff\xd8\xff\xd9"

    def fake_urlopen(request, timeout=0):
        del timeout
        url = request.full_url
        if url.endswith("/..commonstarttvapp"):
            assert b"UPLOAD_CAPTURE" in request.data
            assert b"mobilekey" in request.data
            return _Body(200, b"ok")
        if "imageurl/by/id" in url:
            body = (
                '{"imageURL":"https://img.example/a.jpg?image=https%3A%2F%2Fcdn.example%2Fshot.jpg",'
                '"infoPackage":{"curAppInfo":{"curAppName":"聚好看"},"vodPlayingInfo":"新闻"}}'
            ).encode()
            return _Body(200, body)
        if url == "https://cdn.example/shot.jpg":
            return _Body(200, jpeg)
        raise urllib.error.URLError(url)

    monkeypatch.setattr(proto_local_http.urllib.request, "urlopen", fake_urlopen)
    shot = proto_local_http.capture_screen("192.0.2.10", pause=lambda _seconds: None, retries=2)
    assert shot.image == jpeg
    assert shot.note == "聚好看正在播放新闻"
    assert shot.source_url == "https://cdn.example/shot.jpg"


def test_source_stops_after_voice(proto_client, proto_credentials, monkeypatch) -> None:
    client = proto_client.HisenseTvClient("192.0.2.10", uuid="12:34:56:78:9a:bc")
    client._creds = proto_credentials.generate_dynamic_credentials(
        "12:34:56:78:9a:bc", timestamp=1
    )
    published: list[str] = []

    class FakeMqtt:
        def publish(self, topic, body, qos=0, retain=False):
            published.append(topic)

            class Info:
                rc = proto_client.mqtt.MQTT_ERR_SUCCESS

                def wait_for_publish(self, timeout=None):
                    return None

            return Info()

    client._client = FakeMqtt()
    monkeypatch.setattr(proto_client, "push_voice", lambda host, text, **kwargs: 200)
    client.open_source()
    assert published == []


def test_send_key_stops_after_http_accepts(proto_client, proto_credentials, monkeypatch) -> None:
    client = proto_client.HisenseTvClient("192.0.2.10", uuid="12:34:56:78:9a:bc")
    client._creds = proto_credentials.generate_dynamic_credentials(
        "12:34:56:78:9a:bc", timestamp=1
    )
    published: list[str] = []

    class FakeMqtt:
        def publish(self, topic, body, qos=0, retain=False):
            published.append(topic)

            class Info:
                rc = proto_client.mqtt.MQTT_ERR_SUCCESS

                def wait_for_publish(self, timeout=None):
                    return None

            return Info()

    client._client = FakeMqtt()
    monkeypatch.setattr(proto_client, "send_local_key", lambda host, key, **kwargs: 200)
    client.send_key("home")
    assert published == []


def test_fetch_device_identity_reads_deviceid(proto_local_http, monkeypatch) -> None:
    seen: list[str] = []

    def fake_urlopen(request, timeout=0):
        del timeout
        seen.append(request.full_url)
        if request.full_url.endswith(":7779/..deviceid"):
            return _Body(200, b'{"ticket":"lan-ticket","wifiId":"aabbccddeeff"}')
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(proto_local_http.urllib.request, "urlopen", fake_urlopen)
    identity = proto_local_http.fetch_device_identity("192.0.2.10", timeout=0.1)
    assert identity == {"ticket": "lan-ticket", "wifiId": "aabbccddeeff"}
    assert seen[0].endswith("/..deviceid")


def test_launch_local_app_opens_by_voice(proto_local_http, monkeypatch) -> None:
    seen: list[tuple[str, bytes | None]] = []

    def fake_urlopen(request, timeout=0):
        del timeout
        seen.append((request.full_url, request.data))
        if request.full_url.endswith(":7779/..pushwechatvoice"):
            return _Response(200)
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(proto_local_http.urllib.request, "urlopen", fake_urlopen)
    status = proto_local_http.launch_local_app(
        "192.0.2.10",
        "com.jamdeo.tv.mediacenter",
        name="媒体中心",
        timeout=0.1,
    )
    assert status == 200
    assert seen[0][0] == "http://192.0.2.10:7779/..pushwechatvoice"
    body = json.loads(seen[0][1].decode())
    assert body["voice"] == "打开媒体中心"
    assert body["msgchannel"] == 1
    assert body["msgresource"] == 4
    assert body["msgtype"] == 6
    assert proto_local_http.open_app_voice_phrase("媒体中心", "com.jamdeo.tv.mediacenter") == "打开媒体中心"
    assert proto_local_http.is_android_package("com.ktcp.video")
    assert not proto_local_http.is_android_package("netflix")


def test_launch_local_app_does_not_push_media(proto_local_http, monkeypatch) -> None:
    seen: list[str] = []

    def fake_urlopen(request, timeout=0):
        del timeout
        seen.append(request.full_url)
        if request.full_url.endswith("/..pushwechatvoice"):
            return _Body(400, b"no")
        return _Response(200)

    monkeypatch.setattr(proto_local_http.urllib.request, "urlopen", fake_urlopen)
    status = proto_local_http.launch_local_app(
        "192.0.2.10",
        "com.android.tv.settings",
        name="设置",
        timeout=0.1,
    )
    assert status == 400
    assert seen
    assert all("/..pushsmartju" not in url for url in seen)
    assert all("/..commonstarttvapp" not in url for url in seen)


def test_launch_app_prefers_local_package(proto_client, monkeypatch) -> None:
    published: list[str] = []
    client = proto_client.HisenseTvClient("192.0.2.10", uuid="aa:bb:cc:dd:ee:ff")

    class FakeMqtt:
        def publish(self, topic, payload=None, qos=0, retain=False):
            published.append(topic)

            class Info:
                rc = proto_client.mqtt.MQTT_ERR_SUCCESS

                def wait_for_publish(self, timeout=None):
                    return None

            return Info()

    client._client = FakeMqtt()
    captured: dict[str, str] = {}

    def fake_launch(host, package, **kwargs):
        captured["host"] = host
        captured["package"] = package
        captured["name"] = kwargs.get("name") or ""
        return 200

    monkeypatch.setattr(proto_client, "launch_local_app", fake_launch)
    client.launch_app("云视听极光", "com.ktcp.video")
    assert published == []
    assert captured["package"] == "com.ktcp.video"
    assert captured["name"] == "云视听极光"
    assert client.state.current_app == "云视听极光"


def test_launch_app_mqtt_when_local_fails(
    proto_client, proto_credentials, monkeypatch
) -> None:
    published: list[tuple[str, str]] = []
    client = proto_client.HisenseTvClient("192.0.2.10", uuid="aa:bb:cc:dd:ee:ff")
    client._creds = proto_credentials.generate_dynamic_credentials(
        "aa:bb:cc:dd:ee:ff", timestamp=1
    )

    class FakeMqtt:
        def publish(self, topic, payload=None, qos=0, retain=False):
            published.append((topic, payload))

            class Info:
                rc = proto_client.mqtt.MQTT_ERR_SUCCESS

                def wait_for_publish(self, timeout=None):
                    return None

            return Info()

    client._client = FakeMqtt()
    monkeypatch.setattr(proto_client, "launch_local_app", lambda host, package, **kwargs: None)
    client.launch_app("Netflix", "netflix", url_type=37)
    assert any(topic.endswith("/actions/launchapp") for topic, _ in published)
    body = next(payload for topic, payload in published if topic.endswith("/actions/launchapp"))
    assert '"url":"netflix"' in body
    assert '"urlType":37' in body
    assert '"isLocalApp":0' in body
    assert client.state.current_app == "Netflix"


def test_launch_app_local_package_skips_mqtt_on_400(
    proto_client, proto_credentials, monkeypatch
) -> None:
    published: list[tuple[str, str]] = []
    client = proto_client.HisenseTvClient("192.0.2.10", uuid="aa:bb:cc:dd:ee:ff")
    client._creds = proto_credentials.generate_dynamic_credentials(
        "aa:bb:cc:dd:ee:ff", timestamp=1
    )

    class FakeMqtt:
        def publish(self, topic, payload=None, qos=0, retain=False):
            published.append((topic, payload))

            class Info:
                rc = proto_client.mqtt.MQTT_ERR_SUCCESS

                def wait_for_publish(self, timeout=None):
                    return None

            return Info()

    client._client = FakeMqtt()
    monkeypatch.setattr(proto_client, "launch_local_app", lambda host, package, **kwargs: 400)
    with pytest.raises(RuntimeError, match="拒绝打开"):
        client.launch_app("媒体中心", "com.jamdeo.tv.mediacenter")
    assert published == []
