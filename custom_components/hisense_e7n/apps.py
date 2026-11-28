"""Installed TV apps, the same list 爱家 shows under 电视应用 → 我的应用."""

from __future__ import annotations

from typing import Any

_NAME_KEYS = ("name", "appName", "appname", "title", "app_name", "label")
_URL_KEYS = ("url", "appUrl", "appurl", "launchUrl")
_ID_KEYS = ("appId", "appid", "id", "packageName", "packagename", "package")
_PACKAGE_KEYS = ("packageName", "packagename", "package", "pkgName", "pkg")
_SIZE_KEYS = (
    "size",
    "appSize",
    "apkSize",
    "packageSize",
    "fileSize",
    "installSize",
    "occupiedSize",
    "dataSize",
)
# Prefer 我的应用 over store/recommend wrappers.
_MY_APP_KEYS = (
    "我的应用",
    "myApp",
    "myapp",
    "my_app",
    "myApps",
    "installedApps",
    "installedAppList",
    "mqttAppNameList",
)
_LIST_KEYS = _MY_APP_KEYS + (
    "appTypeList",
    "app_type_list",
    "tabList",
    "app_list",
    "applist",
    "appList",
    "list",
    "apps",
    "data",
    "packageList",
    "value",
    "appInfoList",
    "appinfo",
)
_NESTED_LIST_KEYS = (
    "appList",
    "app_list",
    "applist",
    "apps",
    "list",
    "children",
    "data",
)
# 热门/推荐 are the store rows next to 我的应用, not the installed set.
_OTHER_GROUPS = {"recommend", "hot", "store", "banner", "ad", "推荐", "热门", "应用推荐"}
_MY_APP_LABELS = {
    "我的应用",
    "my apps",
    "my app",
    "myapp",
    "my_app",
    "installed",
    "installed apps",
}


def normalize_apps(data: Any) -> list[dict[str, Any]]:
    """Return installed apps as ``{name, url, app_id, url_type, store_type}``."""
    apps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _items(data):
        app = _one_app(item)
        if app is None:
            continue
        key = app.get("package") or app["name"]
        if key in seen:
            continue
        seen.add(key)
        apps.append(app)
    return apps


def format_app_title(app: dict[str, Any]) -> str:
    """Display name like 爱家: ``健身镜 (51.45M)`` when size is known."""
    name = str(app.get("name") or app.get("package") or "").strip()
    size = str(app.get("size") or "").strip()
    if name and size:
        return f"{name} ({size})"
    return name


def app_choice_name(app: dict[str, Any]) -> str:
    """Select-entity option: 爱家 我的应用 display name, without size."""
    return str(app.get("name") or app.get("package") or "").strip()


def app_choice_names(apps: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for app in apps:
        name = app_choice_name(app)
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def current_app_option(
    apps: list[dict[str, Any]],
    *candidates: str | None,
) -> str | None:
    """Pick a select option from the running app name or last launch."""
    names = app_choice_names(apps)
    if not names:
        return None
    for candidate in candidates:
        if not candidate:
            continue
        text = candidate.strip()
        if text in names:
            return text
        matched = resolve_app(apps, text)
        if matched is None:
            continue
        name = app_choice_name(matched)
        if name in names:
            return name
    return None


def app_media_id(app: dict[str, Any]) -> str:
    """Stable play_media / browse_media id (package, then url, then name)."""
    for key in ("package", "app_id", "url", "name"):
        value = str(app.get(key) or "").strip()
        if value:
            return value
    return ""


def app_summary(app: dict[str, Any]) -> dict[str, str]:
    """Compact row for media_player attributes / automations."""
    row = {"name": app_choice_name(app)}
    for key in ("package", "url", "app_id"):
        value = str(app.get(key) or "").strip()
        if value:
            row[key] = value
    return row


def resolve_app(apps: list[dict[str, Any]], media_id: str) -> dict[str, Any] | None:
    """Match play_media id: exact package/url/id/name, then unique substring.

    Same matching order as TCL ``resolve_app_package``, over VIDAA app dicts.
    """
    wanted = media_id.strip() if isinstance(media_id, str) else ""
    if not wanted:
        return None
    for app in apps:
        ids = {
            str(app.get("package") or "").strip(),
            str(app.get("app_id") or "").strip(),
            str(app.get("url") or "").strip(),
            str(app.get("name") or "").strip(),
            format_app_title(app).strip(),
        }
        if wanted in ids:
            return app
    lowered = wanted.casefold()
    for app in apps:
        name = str(app.get("name") or "").strip()
        title = format_app_title(app)
        if name.casefold() == lowered or title.casefold() == lowered:
            return app
    matches = [
        app
        for app in apps
        if lowered in " ".join(
            str(app.get(key) or "") for key in ("name", "package", "app_id", "url")
        ).casefold()
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def build_launch_payload(
    app: dict[str, Any] | None = None,
    *,
    name: str = "",
    url: str | None = None,
    url_type: int = 37,
    store_type: int = 0,
    package: str | None = None,
    is_local: bool = False,
) -> dict[str, Any]:
    """MQTT ``launchapp`` body: echo the 我的应用 row, RemoteNOW-shaped."""
    icon = ""
    app_id = ""
    if app:
        name = str(app.get("name") or name or "")
        package = str(app.get("package") or package or "") or None
        url = str(app.get("url") or url or package or name)
        url_type = int(app.get("url_type") if app.get("url_type") is not None else url_type)
        store_type = int(app.get("store_type") if app.get("store_type") is not None else store_type)
        app_id = str(app.get("app_id") or package or url or "")
        icon = str(app.get("icon") or "")
    app_url = (url or package or name or "").strip()
    if is_local:
        app_url = (package or app_url).strip()
        url_type = 0
        app_id = app_id or app_url
    return {
        "appIcon": icon,
        "appId": app_id or app_url,
        "has_detail_page": 0,
        "isLocalApp": 1 if is_local else 0,
        "name": (name or app_url).strip(),
        "storeType": int(store_type),
        "type": 0,
        "url": app_url,
        "urlType": int(url_type),
    }


def _items(data: Any) -> list[Any]:
    if isinstance(data, list):
        return _flatten_groups(data)
    if isinstance(data, dict):
        for key in _MY_APP_KEYS:
            if key not in data:
                continue
            nested = _items(data[key])
            if nested:
                return nested
        for key in _LIST_KEYS:
            if key in _MY_APP_KEYS:
                continue
            value = data.get(key)
            if isinstance(value, list):
                nested = _flatten_groups(value)
                if nested:
                    return nested
            if isinstance(value, dict):
                nested = _items(value)
                if nested:
                    return nested
        if _looks_like_app(data) or any(key in data for key in (*_NAME_KEYS, *_ID_KEYS, *_PACKAGE_KEYS)):
            return [data]
    return []


def _flatten_groups(items: list[Any]) -> list[Any]:
    if not items:
        return items
    groups: list[tuple[dict[str, Any], list[Any]]] = []
    apps: list[Any] = []
    for item in items:
        if isinstance(item, str):
            apps.append(item)
            continue
        if not isinstance(item, dict):
            continue
        children = _nested_app_list(item)
        if children is not None and not _looks_like_app(item):
            groups.append((item, children))
            continue
        apps.append(item)
    if not groups:
        return items
    mine: list[Any] = []
    rest: list[Any] = []
    for item, children in groups:
        if _is_my_apps_group(item):
            mine.extend(children)
        elif not _is_other_group(item):
            rest.extend(children)
    chosen = mine or rest
    if chosen and chosen != items:
        return _flatten_groups(chosen) + apps
    return items


def _nested_app_list(item: dict[str, Any]) -> list[Any] | None:
    for key in _NESTED_LIST_KEYS:
        value = item.get(key)
        if isinstance(value, list):
            return value
    return None


def _looks_like_app(item: dict[str, Any]) -> bool:
    if _first(item, _PACKAGE_KEYS) or _first(item, _URL_KEYS):
        return True
    if item.get("urlType") is not None or item.get("urltype") is not None:
        return True
    if item.get("isLocalApp") is not None or item.get("islocalapp") is not None:
        return True
    return False


def _is_my_apps_group(item: dict[str, Any]) -> bool:
    return _group_label(item).lower() in _MY_APP_LABELS or _group_label(item) == "我的应用"


def _is_other_group(item: dict[str, Any]) -> bool:
    return _group_label(item).lower() in {value.lower() for value in _OTHER_GROUPS}


def _group_label(item: dict[str, Any]) -> str:
    return str(
        item.get("typeName")
        or item.get("name")
        or item.get("title")
        or item.get("appType")
        or item.get("group")
        or item.get("category")
        or item.get("from")
        or ""
    ).strip()


def _one_app(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        name = item.strip()
        if not name:
            return None
        return _record(name, name, name, 37, 0)
    if not isinstance(item, dict) or not _installed(item):
        return None
    package = _first(item, _PACKAGE_KEYS)
    name = _first(item, _NAME_KEYS)
    app_id = _first(item, _ID_KEYS)
    url = _first(item, _URL_KEYS) or package or app_id or name
    icon = _first(item, ("icon", "iconUrl", "appIcon", "thumbnail"))
    size = _format_size(item)
    local = _truthy(item.get("isLocalApp", item.get("islocalapp")))
    if package and (local or not _first(item, _URL_KEYS)):
        url = package
    if not name:
        name = package or app_id or url
    if not name:
        return None
    url_type = _as_int(item.get("urlType", item.get("urltype")), 0 if package else 37)
    if package and local:
        url_type = 0
    return _record(
        name,
        url,
        app_id or package or url,
        url_type,
        _as_int(item.get("storeType", item.get("storetype")), 0),
        icon or None,
        package or None,
        size,
    )


def _record(
    name: str,
    url: str,
    app_id: str,
    url_type: int,
    store_type: int,
    icon: str | None = None,
    package: str | None = None,
    size: str | None = None,
) -> dict[str, Any]:
    app = {
        "name": name,
        "url": url,
        "app_id": app_id,
        "url_type": url_type,
        "store_type": store_type,
    }
    if icon:
        app["icon"] = icon
    if package:
        app["package"] = package
    if size:
        app["size"] = size
    return app


def _installed(item: dict[str, Any]) -> bool:
    for key in ("isuninstalled", "uninstalled", "isUninstalled"):
        if key in item and str(item[key]).lower() in {"1", "true"}:
            return False
    for key in ("installed", "isinstalled", "isInstalled"):
        if key in item and str(item[key]).lower() in {"0", "false"}:
            return False
    group = str(
        item.get("from") or item.get("category") or item.get("group") or item.get("appType") or ""
    ).strip().lower()
    return group not in {value.lower() for value in _OTHER_GROUPS}


def _first(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _truthy(value: Any) -> bool:
    return str(value).lower() in {"1", "true", "yes"}


def _format_size(item: dict[str, Any]) -> str | None:
    for key in _SIZE_KEYS:
        if key not in item or item[key] in (None, ""):
            continue
        value = item[key]
        if isinstance(value, str):
            text = value.strip()
            if not text:
                continue
            if text[-1:].upper() in {"B", "K", "M", "G"} or text[-2:].upper() in {
                "KB",
                "MB",
                "GB",
            }:
                return text
            try:
                value = float(text)
            except ValueError:
                return text
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number < 0:
            continue
        # Bytes when large; already-MB when small.
        if number >= 1024 * 1024:
            return f"{number / (1024 * 1024):.2f}M"
        if number >= 1024:
            return f"{number / 1024:.2f}K"
        if number >= 100:
            return f"{number:.2f}M"
        return f"{number:.2f}M"
    return None
