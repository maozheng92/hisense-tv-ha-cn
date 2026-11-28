"""爱家账号登录与「我的应用」云栏目。

协议来自爱家 APK 7.0.8.12（``portal-account`` / ``iot-aihome`` /
``mobile-home-launcher-verif``）以及公开网页客户端的 ``X-Sign-For``。
``appKey`` / ``appSecret`` 是网页端 ``commonweb`` 公钥，不是用户口令。
密码只在登录请求里使用，不写入配置项。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .apps import normalize_apps

_LOGGER = logging.getLogger(__name__)

APP_KEY = "commonweb"
APP_SECRET = "MORZRbkuiWxjp+SM4vR_GxY4pZxLZ6rn"
# 爱家 IoT 实测签名钥（与登录 PORTAL_SECRET 不同）。栏目接口两种都试。
IOT_SIGN_SECRET = "AOSj8JBr0IpUzv5w+hURR6W4oINsI4o5"
APP_VERSION = "7.0.8.12"
SERVER_CODE = "9501"
DISTRIBUTE_ID = "2001"
PORTAL_SIGNON = "https://portal-account.hismarttv.com/mobile/se/signon"
REFRESH_URL = "https://bas-wg.hismarttv.com/aaa/refresh_token2"
IOT_BASE = "https://iot-aihome.hismarttv.com"
COLUMNS_URL = "https://mobile-home-launcher-verif.hismarttv.com/api/columns"
MAIN_PAGE_URL = "https://mobile-home-launcher-verif.hismarttv.com/api/mobileMainPage"
SIDE_BAR_URL = "https://mobile-home-launcher-verif.hismarttv.com/api/sideBar"
TV_TOKEN_URL = "https://mobile-aiot.hismarttv.com/weixintv/oauth/login4TVByPhoneToken"
DEVICE_INFO_URL = "https://mobile-aiot.hismarttv.com/mobiletv/device/deviceInfo"
GET_REC_DATA_URL = "https://mobile-aiot.hismarttv.com/vodapptv/5.14/getRecData"
ACTIVITY_RESOURCES_URL = "https://layout-launcher.hismarttv.com/api/activityResources"
HOMEPAGE_LAYOUT = "/4.0/iot/layout/smartHomeApp/common"
DEVICE_DETAIL = "/4.0/iot/devices/detail"
EXTEND_STATE = "/4.0/iot/state/getExtendState"
HOMEPAGE_CONFIG = "/4.0/iot/devices/function/getHomepageConfig"
TOKEN_TTL_DEFAULT = 259200.0
_TV_HINTS = (
    "电视",
    "tv",
    "vidaa",
    "hisense tv",
    "smarttv",
    "smart tv",
    "television",
    "智屏",
    "e7n",
)
_LOGIN_OK = {"0", "0.0", "00", "0000", "200", "success", "SUCCESS"}


class AijiaError(Exception):
    """爱家云接口失败。"""


class AijiaAuthError(AijiaError):
    """账号或令牌无效。"""


@dataclass
class AijiaTokens:
    access_token: str
    refresh_token: str = ""
    customer_id: str = ""
    username: str = ""
    device_id: str = ""
    wifi_id: str = ""
    tv_login_id: str = ""
    obtained_at: float = 0.0
    token_ttl: float = TOKEN_TTL_DEFAULT

    @property
    def logged_in(self) -> bool:
        return bool(self.access_token and self.customer_id)

    def to_entry(self) -> dict[str, Any]:
        return {
            "aijia_username": self.username,
            "aijia_access_token": self.access_token,
            "aijia_refresh_token": self.refresh_token,
            "aijia_customer_id": self.customer_id,
            "aijia_device_id": self.device_id,
            "aijia_wifi_id": self.wifi_id,
            "aijia_tv_login_id": self.tv_login_id,
            "aijia_token_obtained_at": self.obtained_at,
            "aijia_token_ttl": self.token_ttl,
        }


def tokens_from_entry(data: dict[str, Any] | None) -> AijiaTokens | None:
    blob = data or {}
    access = str(blob.get("aijia_access_token") or "").strip()
    customer = str(blob.get("aijia_customer_id") or "").strip()
    if not access or not customer:
        return None
    try:
        obtained = float(blob.get("aijia_token_obtained_at") or 0.0)
    except (TypeError, ValueError):
        obtained = 0.0
    try:
        ttl = float(blob.get("aijia_token_ttl") or TOKEN_TTL_DEFAULT)
    except (TypeError, ValueError):
        ttl = TOKEN_TTL_DEFAULT
    return AijiaTokens(
        access_token=access,
        refresh_token=str(blob.get("aijia_refresh_token") or "").strip(),
        customer_id=customer,
        username=str(blob.get("aijia_username") or "").strip(),
        device_id=str(blob.get("aijia_device_id") or "").strip(),
        wifi_id=str(blob.get("aijia_wifi_id") or "").strip(),
        tv_login_id=str(blob.get("aijia_tv_login_id") or "").strip(),
        obtained_at=obtained,
        token_ttl=ttl or TOKEN_TTL_DEFAULT,
    )


def empty_entry_fields() -> dict[str, Any]:
    return AijiaTokens(access_token="", customer_id="").to_entry()


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def sign_body(body: str, secret: str = APP_SECRET) -> str:
    digest = hashlib.md5(
        (body + secret).encode("utf-8"), usedforsecurity=False
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def encrypt_portal(value: str) -> str:
    raw = value.encode("utf-8")
    padding = 16 - len(raw) % 16
    cipher = Cipher(
        algorithms.AES(APP_SECRET.encode("ascii")),
        modes.CBC(APP_SECRET[:16].encode("ascii")),
    )
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(raw + bytes([padding]) * padding) + encryptor.finalize()
    return base64.b64encode(encrypted).decode("ascii")


def signed_headers(
    body: str, access_token: str = "", *, secret: str = APP_SECRET
) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json",
        "User-Agent": "okhttp/4.10.0",
        "appKey": APP_KEY,
        "X-Sign-For": sign_body(body, secret),
        "X-Platform": "android",
        "X-Terminal-Version": APP_VERSION,
    }
    token = (access_token or "").strip()
    if token:
        headers["accessToken"] = token
        headers["Authorization"] = token
    return headers


def parse_login(result: Any) -> AijiaTokens:
    if not isinstance(result, dict):
        raise AijiaAuthError("登录响应不是 JSON 对象")
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    if not isinstance(data, dict):
        raise AijiaAuthError("登录响应缺少 data")
    if str(data.get("resultCode", "0")) not in _LOGIN_OK:
        raise AijiaAuthError(str(data.get("errorDesc") or data.get("message") or "登录失败"))
    info = data.get("tokenInfo") if isinstance(data.get("tokenInfo"), dict) else data
    token = str(
        info.get("token")
        or info.get("accessToken")
        or data.get("token")
        or data.get("accessToken")
        or ""
    ).strip()
    customer = str(
        info.get("customerId")
        or data.get("customerId")
        or result.get("customerId")
        or info.get("customerID")
        or ""
    ).strip()
    if not token or not customer:
        raise AijiaAuthError("登录未返回 token / customerId")
    ttl = _as_float(info.get("tokenExpiredTime"), TOKEN_TTL_DEFAULT)
    return AijiaTokens(
        access_token=token,
        refresh_token=str(info.get("refreshToken") or data.get("refreshToken") or "").strip(),
        customer_id=customer,
        obtained_at=time.time(),
        token_ttl=ttl or TOKEN_TTL_DEFAULT,
    )


def parse_refresh(result: Any) -> dict[str, Any]:
    if isinstance(result, list) and result:
        result = result[0]
    if not isinstance(result, dict):
        raise AijiaAuthError("续期响应无效")
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    if str(data.get("resultCode", "0")) not in _LOGIN_OK or not data.get("token"):
        raise AijiaAuthError("令牌续期失败")
    return data


def pick_tv_device(
    devices: list[dict[str, Any]],
    *,
    host: str | None = None,
    mac: str | None = None,
    device_id: str | None = None,
) -> dict[str, Any] | None:
    if not devices:
        return None
    wanted = str(device_id or "").strip()
    if wanted:
        for item in devices:
            if str(item.get("deviceId") or "") == wanted:
                return item
    scored: list[tuple[int, dict[str, Any]]] = []
    host_norm = (host or "").strip()
    mac_norm = _norm_mac(mac)
    for item in devices:
        score = 0
        if mac_norm and _mac_in_device(item, mac_norm):
            score += 100
        if host_norm and _host_in_device(item, host_norm):
            score += 80
        if _looks_like_tv(item):
            score += 25
        if score:
            scored.append((score, item))
    if scored:
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[0][1]
    tvs = [item for item in devices if _looks_like_tv(item)]
    if len(tvs) == 1:
        return tvs[0]
    if tvs:
        return tvs[0]
    if len(devices) == 1:
        return devices[0]
    return None


def extract_cloud_apps(data: Any) -> list[dict[str, Any]]:
    """Turn a launcher/IoT JSON blob into ``normalize_apps`` rows."""
    data = _inflate(data)
    names, tiles = _collect_names_and_tiles(data)
    if tiles and names:
        wanted = {name.casefold() for name in names}
        matched = [
            tile
            for tile in tiles
            if str(_tile_name(tile) or "").strip().casefold() in wanted
        ]
        parsed = normalize_apps(matched or tiles)
        if parsed:
            return parsed
    if tiles:
        parsed = normalize_apps({"我的应用": tiles})
        if parsed:
            return parsed
    if names:
        parsed = normalize_apps({"mqttAppNameList": names})
        if parsed:
            return parsed
    return normalize_apps(data)


def devices_from_response(body: Any) -> list[dict[str, Any]]:
    nodes: list[Any] = []
    if isinstance(body, dict):
        payload = body.get("payload")
        if isinstance(payload, dict):
            nodes.append(payload.get("devices"))
        nodes.append(body.get("devices"))
        data = body.get("data")
        if isinstance(data, dict):
            nodes.append(data.get("devices"))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in nodes:
        if not isinstance(node, list):
            continue
        for item in node:
            if not isinstance(item, dict):
                continue
            key = str(item.get("deviceId") or item.get("wifiId") or id(item))
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


async def async_login(session: Any, username: str, password: str) -> AijiaTokens:
    user = (username or "").strip()
    if not user or not password:
        raise AijiaAuthError("请填写爱家手机号和密码")
    body = compact_json(
        {
            "loginName": encrypt_portal(user),
            "signature": encrypt_portal(password),
            "serverCode": SERVER_CODE,
            "distributeId": DISTRIBUTE_ID,
            "termType": 2,
        }
    )
    params = {
        "lastUpdateTime": "0",
        "version": "1.0",
        "deviceType": "2",
        "appType": "100",
        "versionCode": "101",
        "adaptertRank": "720",
        "_": str(_timestamp()),
    }
    status, result = await _request_json(
        session, "POST", PORTAL_SIGNON, headers=signed_headers(body), data=body, params=params
    )
    if status in (401, 403):
        raise AijiaAuthError("爱家拒绝了登录")
    if status >= 400:
        raise AijiaError(f"登录 HTTP {status}")
    tokens = parse_login(result)
    tokens.username = user
    return tokens


async def async_refresh(session: Any, tokens: AijiaTokens) -> AijiaTokens:
    if not tokens.refresh_token:
        raise AijiaAuthError("没有刷新令牌")
    status, result = await _request_json(
        session,
        "POST",
        REFRESH_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=f"refreshToken={tokens.refresh_token}&appKey=2&format=1",
    )
    if status >= 400:
        raise AijiaAuthError(f"续期 HTTP {status}")
    data = parse_refresh(result)
    updated = replace(
        tokens,
        access_token=str(data.get("token") or tokens.access_token),
        refresh_token=str(data.get("refreshToken") or tokens.refresh_token),
        customer_id=str(data.get("customerId") or tokens.customer_id),
        obtained_at=time.time(),
        token_ttl=_as_float(data.get("tokenExpiredTime"), tokens.token_ttl),
    )
    if data.get("customerId"):
        updated.customer_id = str(data["customerId"])
    return updated


async def async_ensure_token(session: Any, tokens: AijiaTokens) -> AijiaTokens:
    if not tokens.logged_in:
        raise AijiaAuthError("未登录爱家")
    age = time.time() - (tokens.obtained_at or 0.0)
    ttl = tokens.token_ttl or TOKEN_TTL_DEFAULT
    if tokens.obtained_at and age < max(0.0, ttl - 3600):
        return tokens
    if not tokens.refresh_token:
        return tokens
    try:
        return await async_refresh(session, tokens)
    except AijiaError:
        _LOGGER.warning("爱家令牌续期失败，继续使用现有 accessToken")
        return tokens


async def async_fetch_apps(
    session: Any,
    tokens: AijiaTokens,
    *,
    host: str | None = None,
    mac: str | None = None,
) -> tuple[AijiaTokens, list[dict[str, Any]]]:
    """Login-state fetch of 我的应用. Returns updated tokens and app rows."""
    current = await async_ensure_token(session, tokens)
    devices: list[dict[str, Any]] = []
    traces: list[str] = []
    try:
        devices = await async_list_devices(session, current)
    except AijiaError as err:
        _LOGGER.warning("爱家设备列表失败，改走栏目: %s", err)
        traces.append(f"list:{err}")
    tv = pick_tv_device(
        devices, host=host, mac=mac, device_id=current.device_id or None
    )
    targets: list[dict[str, Any]] = [tv] if tv is not None else list(devices[:3])
    for item in targets:
        current = replace(
            current,
            device_id=str(item.get("deviceId") or current.device_id),
            wifi_id=str(item.get("wifiId") or item.get("wifiid") or current.wifi_id),
        )
        apps = extract_cloud_apps(item)
        if apps:
            _LOGGER.info(
                "爱家从设备 %s 解析到 %s 个应用", current.device_id, len(apps)
            )
            return current, apps
        for blob in await _device_extra_blobs(session, current, traces):
            apps = extract_cloud_apps(blob)
            if apps:
                _LOGGER.info(
                    "爱家从设备 %s 解析到 %s 个应用", current.device_id, len(apps)
                )
                return current, apps
    if tv is not None:
        current = replace(
            current,
            device_id=str(tv.get("deviceId") or current.device_id),
            wifi_id=str(tv.get("wifiId") or tv.get("wifiid") or current.wifi_id),
        )
    if current.device_id:
        current = await _try_tv_login_id(session, current)
    for candidate in await _column_candidates(session, current, traces):
        apps = extract_cloud_apps(candidate)
        if apps:
            _LOGGER.info(
                "爱家栏目解析到 %s 个应用 (deviceId=%s)",
                len(apps),
                current.device_id,
            )
            return current, apps
    summaries = [_device_summary(item) for item in devices[:3]]
    _LOGGER.warning(
        "爱家已登录但未解析到我的应用 devices=%s tv=%s summaries=%s traces=%s",
        len(devices),
        current.device_id or "-",
        summaries,
        "; ".join(traces[:16]) or "-",
    )
    return current, []


async def async_list_devices(session: Any, tokens: AijiaTokens) -> list[dict[str, Any]]:
    homes_body = await _iot_post(session, tokens, "/4.0/iot/home/list", {})
    homes = []
    payload = homes_body.get("payload") if isinstance(homes_body, dict) else None
    if isinstance(payload, dict) and isinstance(payload.get("homes"), list):
        homes = [item for item in payload["homes"] if isinstance(item, dict)]
    home_ids = [
        str(item.get("id") or item.get("homeId") or "").strip()
        for item in homes
        if str(item.get("id") or item.get("homeId") or "").strip()
    ]
    if not home_ids:
        home_ids = [""]
    collected: list[dict[str, Any]] = []
    for home_id in home_ids:
        extra: dict[str, Any] = {
            "withState": True,
            "withMultiSplit": True,
            "whitelist": 1,
        }
        if home_id:
            extra["homeId"] = home_id
        body = await _iot_post(session, tokens, "/4.0/iot/devices/list", extra)
        collected.extend(devices_from_response(body))
    return collected


async def _device_extra_blobs(
    session: Any, tokens: AijiaTokens, traces: list[str]
) -> list[Any]:
    extra = {
        "deviceId": tokens.device_id,
        "wifiId": tokens.wifi_id,
        "customerId": tokens.customer_id,
        "sourceType": 20,
        "partnerId": "1001",
    }
    extra = {key: value for key, value in extra.items() if value not in ("", None)}
    found: list[Any] = []
    for path in (DEVICE_DETAIL, EXTEND_STATE, HOMEPAGE_CONFIG):
        try:
            body = await _iot_post(session, tokens, path, extra)
        except AijiaError as err:
            traces.append(f"{path}:{err}")
            continue
        if body:
            traces.append(f"{path}:{_summarize_json(body)}")
            found.append(body)
        else:
            traces.append(f"{path}:empty")
    return found


async def _try_tv_login_id(session: Any, tokens: AijiaTokens) -> AijiaTokens:
    payload = {
        "accessToken": tokens.access_token,
        "customerId": tokens.customer_id,
        "deviceId": tokens.device_id,
        "wifiId": tokens.wifi_id,
        "serverCode": SERVER_CODE,
        "distributeId": DISTRIBUTE_ID,
    }
    body = compact_json({key: value for key, value in payload.items() if value})
    try:
        status, result = await _request_json(
            session,
            "POST",
            TV_TOKEN_URL,
            headers=signed_headers(body, tokens.access_token),
            data=body,
        )
    except AijiaError:
        return tokens
    if status >= 400 or not isinstance(result, dict):
        return tokens
    data = result.get("data") if isinstance(result.get("data"), dict) else result
    if not isinstance(data, dict):
        return tokens
    login_id = str(
        data.get("tvLoginedId")
        or data.get("tvLoginId")
        or data.get("token")
        or data.get("accessToken")
        or ""
    ).strip()
    if not login_id:
        return tokens
    return replace(tokens, tv_login_id=login_id)


async def _column_candidates(
    session: Any, tokens: AijiaTokens, traces: list[str] | None = None
) -> list[Any]:
    traces = traces if traces is not None else []
    payload = _column_payload(tokens)
    body = compact_json(payload)
    urls = (
        COLUMNS_URL,
        MAIN_PAGE_URL,
        SIDE_BAR_URL,
        DEVICE_INFO_URL,
        GET_REC_DATA_URL,
        ACTIVITY_RESOURCES_URL,
    )
    found: list[Any] = []
    secrets = (APP_SECRET, IOT_SIGN_SECRET)
    for url in urls:
        short = url.rsplit("/", 1)[-1]
        for secret in secrets:
            try:
                status, result = await _request_json(
                    session,
                    "POST",
                    url,
                    headers=signed_headers(body, tokens.access_token, secret=secret),
                    data=body,
                )
            except AijiaError as err:
                traces.append(f"POST {short}:{err}")
                continue
            traces.append(f"POST {short} {status} {_summarize_json(result)}")
            if status and status < 400 and result not in (None, "", [], {}):
                found.append(result)
                if extract_cloud_apps(result):
                    return found
        params = {
            "deviceId": tokens.device_id,
            "wifiId": tokens.wifi_id,
            "customerId": tokens.customer_id,
            "accessToken": tokens.access_token,
            "tvLoginedId": tokens.tv_login_id,
            "serverCode": SERVER_CODE,
            "distributeId": DISTRIBUTE_ID,
        }
        params = {key: value for key, value in params.items() if value}
        try:
            status, result = await _request_json(
                session,
                "GET",
                url,
                headers=signed_headers(compact_json(params), tokens.access_token),
                params=params,
            )
        except AijiaError as err:
            traces.append(f"GET {short}:{err}")
            continue
        traces.append(f"GET {short} {status} {_summarize_json(result)}")
        if status < 400 and result not in (None, "", [], {}):
            found.append(result)
    try:
        layout = await _iot_post(
            session,
            tokens,
            HOMEPAGE_LAYOUT,
            {
                "deviceId": tokens.device_id,
                "wifiId": tokens.wifi_id,
                "customerId": tokens.customer_id,
            },
        )
    except AijiaError as err:
        traces.append(f"layout:{err}")
        layout = None
    if layout:
        traces.append(f"layout:{_summarize_json(layout)}")
        found.append(layout)
    return found


def _column_payload(tokens: AijiaTokens) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "appVersion": APP_VERSION,
        "appType": 1,
        "header": {
            "messageId": str(uuid.uuid4()),
            "timestamp": _timestamp(),
            "languageId": 0,
        },
        "accessToken": tokens.access_token,
        "customerId": tokens.customer_id,
        "serverCode": SERVER_CODE,
        "distributeId": DISTRIBUTE_ID,
        "deviceId": tokens.device_id,
        "wifiId": tokens.wifi_id,
        "tvLoginedId": tokens.tv_login_id,
    }
    return {key: value for key, value in payload.items() if value not in ("", None)}


async def _iot_post(
    session: Any, tokens: AijiaTokens, path: str, extra: dict[str, Any]
) -> dict[str, Any]:
    errors: list[str] = []
    denied = False
    for secret in (APP_SECRET, IOT_SIGN_SECRET):
        for body in (_iot_body_hialife(tokens, extra), _iot_body_hisenseha(tokens, extra)):
            raw = compact_json(body)
            try:
                status, result = await _request_json(
                    session,
                    "POST",
                    f"{IOT_BASE}{path}",
                    headers=signed_headers(raw, tokens.access_token, secret=secret),
                    data=raw,
                )
            except AijiaError as err:
                errors.append(str(err))
                continue
            if status in (401, 403):
                denied = True
                errors.append(f"HTTP {status}")
                continue
            if isinstance(result, dict) and (
                _iot_ok(result) or devices_from_response(result) or result.get("payload")
            ):
                return result
            errors.append(f"HTTP {status}")
    if denied:
        _LOGGER.warning("爱家 IoT %s 返回 401/403，改走栏目接口", path)
    else:
        _LOGGER.debug("爱家 IoT %s 未成功: %s", path, "; ".join(errors))
    return {}


def _iot_body_hialife(tokens: AijiaTokens, extra: dict[str, Any]) -> dict[str, Any]:
    payload = {"customerId": tokens.customer_id, "sourceType": 20, **extra}
    return {
        "appVersion": APP_VERSION,
        "appType": 1,
        "header": {
            "messageId": str(uuid.uuid4()),
            "timestamp": _timestamp(),
            "languageId": 0,
        },
        "accessToken": tokens.access_token,
        "payload": payload,
    }


def _iot_body_hisenseha(tokens: AijiaTokens, extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "lastUpdateTime": 0,
        "accessToken": tokens.access_token,
        "appVersion": "",
        "openId": "",
        "version": "1.0",
        "deviceType": 2,
        "appType": 100,
        "versionCode": "101",
        "adaptertRank": 720,
        "_": _timestamp(),
        "header": {"messageId": str(uuid.uuid4())},
        "payload": {
            "customerId": tokens.customer_id,
            "sourceType": 3,
            **extra,
        },
    }


def _iot_ok(body: dict[str, Any]) -> bool:
    payload = body.get("payload")
    if isinstance(payload, dict) and str(payload.get("status") or "").upper() == "SUCCESS":
        return True
    return False


async def _request_json(
    session: Any,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: Any = None,
    params: dict[str, str] | None = None,
) -> tuple[int, Any]:
    kwargs: dict[str, Any] = {"headers": headers or {}}
    if data is not None:
        kwargs["data"] = data
    if params:
        kwargs["params"] = params
    request = getattr(session, "request", None)
    if request is None:
        request = session.post if method.upper() == "POST" else session.get
        response_cm = request(url, **kwargs)
    else:
        response_cm = request(method, url, **kwargs)
    async with response_cm as response:
        status = int(getattr(response, "status", 0) or 0)
        try:
            result = await response.json(content_type=None)
        except TypeError:
            result = await response.json()
        except Exception:  # noqa: BLE001
            try:
                text = await response.text()
            except Exception:  # noqa: BLE001
                text = ""
            result = {"raw": text} if text else {}
        return status, result


def _collect_names_and_tiles(data: Any) -> tuple[list[str], list[Any]]:
    names: list[str] = []
    tiles: list[Any] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            mqtt = node.get("mqttAppNameList")
            if isinstance(mqtt, str):
                mqtt = _inflate(mqtt)
            if isinstance(mqtt, str) and mqtt.strip():
                names.extend(
                    part.strip()
                    for part in mqtt.replace("，", ",").split(",")
                    if part.strip()
                )
            elif isinstance(mqtt, list):
                for item in mqtt:
                    if isinstance(item, str) and item.strip():
                        names.append(item.strip())
                    elif isinstance(item, dict):
                        label = _tile_name(item)
                        if label:
                            names.append(label)
                        tiles.append(item)
            for key in (
                "tiles",
                "tileList",
                "tile",
                "resources",
                "itemList",
                "resourceList",
                "contents",
                "records",
                "appInfo",
                "appInfoList",
                "columnList",
            ):
                value = node.get(key)
                if isinstance(value, list):
                    tiles.extend(item for item in value if isinstance(item, (dict, str)))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return names, tiles


def _tile_name(item: dict[str, Any]) -> str:
    for key in ("name", "appName", "title", "showName", "resourceName", "tileName", "label"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _looks_like_tv(item: dict[str, Any]) -> bool:
    blob = json.dumps(item, ensure_ascii=False).lower()
    return any(hint in blob for hint in _TV_HINTS)


def _inflate(node: Any, depth: int = 0) -> Any:
    """Decode JSON strings and name/value state lists used by 爱家 IoT."""
    if depth > 8:
        return node
    if isinstance(node, str):
        text = node.strip()
        if len(text) >= 2 and text[0] in "{[":
            try:
                return _inflate(json.loads(text), depth + 1)
            except json.JSONDecodeError:
                return node
        return node
    if isinstance(node, list):
        if node and all(_is_named_state(item) for item in node):
            mapping: dict[str, Any] = {}
            for item in node:
                key = str(item.get("name") or item.get("key") or item.get("labelKey") or "")
                if key:
                    mapping[key] = _inflate(
                        item.get("value", item.get("labelValue")), depth + 1
                    )
            return _inflate(mapping, depth + 1)
        return [_inflate(item, depth + 1) for item in node]
    if isinstance(node, dict):
        out = {key: _inflate(value, depth + 1) for key, value in node.items()}
        labels = out.get("labels")
        if isinstance(labels, list):
            for item in labels:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or item.get("labelKey") or item.get("name") or "")
                if key and key not in out:
                    out[key] = _inflate(item.get("value", item.get("labelValue")), depth + 1)
        return out
    return node


def _is_named_state(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    has_key = "name" in item or "key" in item or "labelKey" in item
    has_value = "value" in item or "labelValue" in item
    if not (has_key and has_value):
        return False
    return not any(
        key in item
        for key in ("packageName", "jumpParam", "startupType", "isLocalApp", "appName")
    )


def _device_summary(item: dict[str, Any]) -> dict[str, Any]:
    product = item.get("product") if isinstance(item.get("product"), dict) else {}
    states = item.get("states")
    state_keys: list[str] = []
    if isinstance(states, dict):
        state_keys = list(states)[:24]
    elif isinstance(states, list):
        state_keys = [
            str(row.get("name") or row.get("key") or "")
            for row in states
            if isinstance(row, dict)
        ][:24]
    return {
        "deviceId": str(item.get("deviceId") or "")[:12],
        "wifiId": str(item.get("wifiId") or "")[:12],
        "nickname": item.get("nickname") or item.get("deviceName") or item.get("name"),
        "categoryCode": item.get("categoryCode"),
        "product": product.get("name") or product.get("code"),
        "topKeys": list(item)[:16],
        "stateKeys": state_keys,
    }


def _summarize_json(data: Any) -> str:
    if data in (None, "", [], {}):
        return "empty"
    if not isinstance(data, dict):
        return type(data).__name__
    keys = ",".join(str(key) for key in list(data)[:10])
    code = data.get("resultCode", data.get("code", data.get("errorCode", "")))
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else None
    extra = f" payload={','.join(list(payload)[:8])}" if payload else ""
    return f"keys={keys} code={code}{extra}"


def _norm_mac(value: str | None) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def _mac_in_device(item: dict[str, Any], mac: str) -> bool:
    for key in ("wifiId", "wifiid", "mac", "macAddress", "deviceMac"):
        raw = str(item.get(key) or "")
        if raw and _norm_mac(raw) == mac:
            return True
    return bool(mac) and mac in _norm_mac(json.dumps(item, ensure_ascii=False))


def _host_in_device(item: dict[str, Any], host: str) -> bool:
    wanted = (host or "").strip()
    if not wanted:
        return False
    for key in ("ip", "lanIp", "deviceIp", "wifiIp", "localIp"):
        if str(item.get(key) or "").strip() == wanted:
            return True
    parsed = urlparse(str(item.get("deviceUrl") or item.get("url") or ""))
    if parsed.hostname == wanted:
        return True
    return wanted in json.dumps(item, ensure_ascii=False)


def _timestamp() -> int:
    return int(time.time() * 1000)


def _as_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default
