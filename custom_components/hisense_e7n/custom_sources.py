"""User-defined TV inputs switched by a remoter key / HA button sequence.

Layout matches TCL ``sources.py``: ``{name, hidden, buttons, interval}``.
Shipped 1.22.14 ``{name, keys: [KEY_*]}`` records still load.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .keys import (
    KEY_CONTROL_CENTER,
    KEY_DOWN,
    KEY_HOME,
    KEY_LEFT,
    KEY_MENU,
    KEY_MUTE,
    KEY_OK,
    KEY_POWER,
    KEY_RETURNS,
    KEY_RIGHT,
    KEY_SOURCE,
    KEY_UP,
    KEY_VOLUMEDOWN,
    KEY_VOLUMEUP,
    normalize_key,
)

ATTR_NAME = "name"
ATTR_HIDDEN = "hidden"
ATTR_BUTTONS = "buttons"
ATTR_INTERVAL = "interval"
ATTR_ACTIONS = "actions"
ATTR_ADD_MORE = "add_more"
ATTR_EDIT_SEQUENCE = "edit_sequence"
ATTR_GO_BACK = "go_back"
ATTR_KEYS = "keys"

KIND_KEY = "key"
KIND_BUTTON = "button"

DEFAULT_INTERVAL = 0.1
MAX_INTERVAL = 10.0
SOURCE_REPEAT_MIN = 1
SOURCE_REPEAT_MAX = 20

# Remoter keys offered when composing a custom input sequence (TCL KEYS set).
SEQUENCE_BUTTON_KEYS: tuple[str, ...] = (
    KEY_SOURCE,
    KEY_UP,
    KEY_DOWN,
    KEY_LEFT,
    KEY_RIGHT,
    KEY_OK,
    KEY_RETURNS,
    KEY_HOME,
    KEY_MENU,
    KEY_CONTROL_CENTER,
)

# Short names stored in ``buttons`` (TCL style). Map to VIDAA KEY_*.
HISENSE_SOURCE_KEYS: dict[str, str] = {
    "up": KEY_UP,
    "down": KEY_DOWN,
    "left": KEY_LEFT,
    "right": KEY_RIGHT,
    "ok": KEY_OK,
    "back": KEY_RETURNS,
    "menu": KEY_MENU,
    "home": KEY_HOME,
    "power": KEY_POWER,
    "volume_up": KEY_VOLUMEUP,
    "volume_down": KEY_VOLUMEDOWN,
    "mute": KEY_MUTE,
    "source": KEY_SOURCE,
    "settings": KEY_CONTROL_CENTER,
}

_WIRE_TO_SHORT = {wire: name for name, wire in HISENSE_SOURCE_KEYS.items()}
_WIRE_TO_SHORT[KEY_CONTROL_CENTER] = "settings"
_WIRE_TO_SHORT[KEY_RETURNS] = "back"

_KEY_LABELS = {
    KEY_SOURCE: "source",
    KEY_UP: "up",
    KEY_DOWN: "down",
    KEY_LEFT: "left",
    KEY_RIGHT: "right",
    KEY_OK: "ok",
    KEY_RETURNS: "back",
    KEY_HOME: "home",
    KEY_MENU: "menu",
    KEY_CONTROL_CENTER: "settings",
}

_NAME_SPLIT = re.compile(r"\s*[:：|＝=]\s*", re.UNICODE)
_KEY_SPLIT = re.compile(r"[\s,，、+/|]+")
_SOURCE_KEY_PREFIX = "key:"


def normalize_name(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    return " ".join(name.split())


def format_key_sequence(keys: list[str] | None) -> str:
    """Human-readable sequence for options descriptions."""
    if not keys:
        return ""
    return " → ".join(_KEY_LABELS.get(key, key) for key in keys)


def summarize_custom_sources(sources: list[dict[str, Any]] | None) -> str:
    """One numbered line per source for the manage-sources description."""
    lines: list[str] = []
    for index, item in enumerate(sources or [], start=1):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        actions = source_actions(item)
        sequence = format_key_sequence(actions) or " → ".join(actions)
        body = f"{name}: {sequence}" if sequence else name
        if item.get(ATTR_HIDDEN):
            body = f"{body} (hidden)"
        lines.append(f"{index}. {body}")
    return "\n".join(lines) if lines else ""


def move_custom_source(
    sources: list[dict[str, Any]],
    name: str,
    *,
    direction: str,
    steps: int = 1,
) -> list[dict[str, Any]]:
    """Return a copy with ``name`` moved up or down by ``steps`` slots."""
    items = [dict(item) for item in sources]
    needle = name.strip()
    index = next(
        (i for i, item in enumerate(items) if item.get("name") == needle),
        None,
    )
    if index is None:
        raise ValueError(f"unknown custom source: {name}")
    try:
        count = int(steps)
    except (TypeError, ValueError) as err:
        raise ValueError(f"invalid move steps: {steps}") from err
    count = max(1, count)
    if direction == "move_up":
        new_index = max(0, index - count)
    elif direction == "move_down":
        new_index = min(len(items) - 1, index + count)
    else:
        raise ValueError(f"invalid move direction: {direction}")
    if new_index == index:
        return items
    item = items.pop(index)
    items.insert(new_index, item)
    return items


def parse_custom_sources_text(text: str | None) -> list[dict[str, Any]]:
    """Parse ``Name: key, key, key`` lines into ``[{name, keys}]``."""
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if _NAME_SPLIT.search(line):
            name, rest = _NAME_SPLIT.split(line, maxsplit=1)
        else:
            parts = line.split(None, 1)
            if len(parts) < 2:
                raise ValueError(f"invalid custom source line: {raw}")
            name, rest = parts
        name = name.strip()
        if not name:
            raise ValueError(f"empty custom source name: {raw}")
        keys = parse_key_sequence(rest)
        if not keys:
            raise ValueError(f"custom source {name!r} needs at least one key")
        if name in seen:
            raise ValueError(f"duplicate custom source name: {name}")
        seen.add(name)
        sources.append({"name": name, "keys": keys})
    return sources


def parse_key_sequence(text: str | None) -> list[str]:
    """Normalize a free-form key list into wire KEY_* names."""
    keys: list[str] = []
    for part in _KEY_SPLIT.split(str(text or "").strip()):
        token = part.strip()
        if not token:
            continue
        keys.append(normalize_key(token))
    return keys


def serialize_custom_sources(sources: list[dict[str, Any]] | None) -> str:
    """Render sources back to the options multiline text."""
    lines: list[str] = []
    for item in sources or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        keys = item.get("keys") or []
        if not name or not isinstance(keys, list) or not keys:
            continue
        lines.append(f"{name}: {', '.join(str(key) for key in keys)}")
    return "\n".join(lines)


def _token_list(raw: Any) -> list[str]:
    if raw is None:
        items: list[Any] = []
    elif isinstance(raw, str):
        items = [part.strip() for part in raw.replace(";", ",").split(",")]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = [raw]
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        token = item.strip()
        if token:
            out.append(token)
    return out


def classify_source_action(action: str) -> tuple[str, str] | None:
    """Return ``('key', KEY_*)`` or ``('button', entity_id)``; else ``None``."""
    token = action.strip() if isinstance(action, str) else ""
    if not token:
        return None
    if token.startswith(_SOURCE_KEY_PREFIX):
        name = token.split(":", 2)[1] if token.count(":") >= 1 else ""
        wire = HISENSE_SOURCE_KEYS.get(name)
        return (KIND_KEY, wire) if wire else None
    if token.startswith("button.") and token.count(".") == 1 and token.split(".", 1)[1]:
        return (KIND_BUTTON, token)
    short = token.casefold()
    if short in HISENSE_SOURCE_KEYS:
        return (KIND_KEY, HISENSE_SOURCE_KEYS[short])
    # Other HA entity ids are not remoter keys (TCL classify is the same).
    if "." in token and not token.upper().startswith("KEY_"):
        return None
    try:
        wire = normalize_key(token)
    except ValueError:
        return None
    if wire in _WIRE_TO_SHORT or wire.startswith("KEY_"):
        return (KIND_KEY, wire)
    return None


def parse_source_actions(raw: Any) -> list[str]:
    """Press sequence: VIDAA keys (short or KEY_*) and ``button.*`` ids."""
    out: list[str] = []
    for token in _token_list(raw):
        classified = classify_source_action(token)
        if classified is None:
            continue
        kind, value = classified
        out.append(value if kind == KIND_BUTTON else _store_key(value))
    return out


def unknown_source_actions(raw: Any) -> list[str]:
    return [token for token in _token_list(raw) if classify_source_action(token) is None]


def _store_key(wire: str) -> str:
    return _WIRE_TO_SHORT.get(wire, wire)


def short_key_name(wire: str) -> str:
    """TCL-style short name for a VIDAA KEY_*."""
    return _store_key(wire)


def parse_repeat(raw: Any, *, default: int = SOURCE_REPEAT_MIN) -> int:
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return default
    if value < SOURCE_REPEAT_MIN:
        return SOURCE_REPEAT_MIN
    if value > SOURCE_REPEAT_MAX:
        return SOURCE_REPEAT_MAX
    return value


def collapse_source_actions(raw: Any) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for value in parse_source_actions(raw):
        if out and out[-1][0] == value:
            out[-1] = (value, out[-1][1] + 1)
        else:
            out.append((value, 1))
    return out


def expand_source_steps(steps: list[tuple[str, int]]) -> list[str]:
    out: list[str] = []
    for action, count in steps:
        classified = classify_source_action(action)
        if classified is None:
            continue
        kind, value = classified
        stored = value if kind == KIND_BUTTON else _store_key(value)
        out.extend([stored] * parse_repeat(count))
    return out


def unique_actions_of_kind(raw: Any, kind: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in parse_source_actions(raw):
        classified = classify_source_action(token)
        if classified is None or classified[0] != kind:
            continue
        value = token if kind == KIND_BUTTON else _store_key(classified[1])
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def counts_for_kind(raw: Any, kind: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value, count in collapse_source_actions(raw):
        classified = classify_source_action(value)
        if classified is None or classified[0] != kind:
            continue
        stored = value if kind == KIND_BUTTON else _store_key(classified[1])
        if stored not in counts:
            counts[stored] = count
    return counts


def sequence_kind(raw: Any) -> str | None:
    kinds: set[str] = set()
    for token in parse_source_actions(raw):
        classified = classify_source_action(token)
        if classified is None:
            continue
        kinds.add(classified[0])
    if len(kinds) == 1:
        return next(iter(kinds))
    return None


def parse_interval(raw: Any) -> float:
    if raw is None or raw == "":
        return DEFAULT_INTERVAL
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL
    if value < 0:
        return 0.0
    if value > MAX_INTERVAL:
        return MAX_INTERVAL
    return value


def parse_button_ids(raw: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in _token_list(raw):
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def source_actions(item: dict[str, Any]) -> list[str]:
    raw = item.get(ATTR_BUTTONS)
    if raw in (None, "", []):
        raw = item.get(ATTR_KEYS)
    return parse_source_actions(raw)


def actions_to_wire_keys(actions: list[str]) -> list[str]:
    """KEY_* (and button.entity_id for mixed macros) for ``tv_client``."""
    out: list[str] = []
    for action in actions:
        classified = classify_source_action(action)
        if classified is None:
            continue
        kind, value = classified
        out.append(value)
    return out


def source_payload(
    *,
    name: str,
    hidden: bool,
    buttons: list[str],
    interval: float,
) -> dict[str, Any]:
    actions = parse_source_actions(buttons)
    entry: dict[str, Any] = {
        ATTR_NAME: name,
        ATTR_HIDDEN: bool(hidden),
        ATTR_BUTTONS: actions,
        ATTR_KEYS: actions_to_wire_keys(actions),
        ATTR_INTERVAL: parse_interval(interval),
    }
    return entry


def normalize_custom_sources(value: Any) -> list[dict[str, Any]]:
    """Accept stored list/dict/text and return a clean ``[{name, keys}]``."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return parse_custom_sources_text(value)
    if isinstance(value, dict):
        items = [{"name": key, "keys": keys} for key, keys in value.items()]
        return normalize_custom_sources(items)
    if not isinstance(value, list):
        raise ValueError("custom_sources must be a list or text")
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, str):
            parsed = parse_custom_sources_text(item)
            for entry in parsed:
                if entry["name"] in seen:
                    raise ValueError(f"duplicate custom source name: {entry['name']}")
                seen.add(entry["name"])
                sources.append(entry)
            continue
        if not isinstance(item, dict):
            raise ValueError(f"invalid custom source: {item!r}")
        name = str(item.get("name") or "").strip()
        if not name:
            raise ValueError("custom source name is required")
        raw_buttons = item.get(ATTR_BUTTONS)
        raw_keys = item.get("keys")
        if raw_buttons not in (None, "", []):
            actions = parse_source_actions(raw_buttons)
            keys = actions_to_wire_keys(actions)
        elif isinstance(raw_keys, str):
            keys = parse_key_sequence(raw_keys)
            actions = parse_source_actions(keys)
        elif isinstance(raw_keys, list):
            keys = parse_key_sequence(",".join(str(part) for part in raw_keys))
            actions = parse_source_actions(keys)
        else:
            raise ValueError(f"custom source {name!r} needs keys")
        if not keys:
            raise ValueError(f"custom source {name!r} needs at least one key")
        if name in seen:
            raise ValueError(f"duplicate custom source name: {name}")
        seen.add(name)
        entry: dict[str, Any] = {"name": name, "keys": keys}
        if raw_buttons not in (None, "", []):
            entry[ATTR_BUTTONS] = actions
        if item.get("hidden"):
            entry["hidden"] = True
        if item.get("interval") is not None:
            entry["interval"] = item.get("interval")
        sources.append(entry)
    return sources


def custom_source_slug(name: str) -> str:
    """Stable unique-id fragment for a custom source name."""
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip()).strip("_").lower()
    if ascii_part:
        return f"{ascii_part}_{digest}"
    return f"custom_{digest}"


def find_custom_source(
    sources: list[dict[str, Any]], name: str
) -> dict[str, Any] | None:
    needle = (name or "").strip()
    if not needle:
        return None
    for item in sources:
        if item.get("name") == needle:
            return item
    lowered = needle.casefold()
    for item in sources:
        if str(item.get("name") or "").casefold() == lowered:
            return item
    return None


def find_source_index(sources: list[dict[str, Any]], name: str) -> int | None:
    wanted = normalize_name(name).casefold()
    if not wanted:
        return None
    for index, source in enumerate(sources):
        if str(source.get(ATTR_NAME, "")).casefold() == wanted:
            return index
    return None


def copy_sources(raw: Any) -> list[dict[str, Any]]:
    """Keep well-formed source dicts, in order (TCL copy_sources)."""
    if isinstance(raw, str):
        try:
            raw = parse_custom_sources_text(raw)
        except ValueError:
            return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = normalize_name(item.get(ATTR_NAME))
        if not name or name.casefold() in seen:
            continue
        actions = source_actions(item)
        if not actions:
            continue
        seen.add(name.casefold())
        out.append(
            source_payload(
                name=name,
                hidden=bool(item.get(ATTR_HIDDEN)),
                buttons=actions,
                interval=parse_interval(
                    item.get(ATTR_INTERVAL)
                    if item.get(ATTR_INTERVAL) is not None
                    else DEFAULT_INTERVAL
                ),
            )
        )
    return out


def visible_source_names(sources: list[dict[str, Any]] | None) -> list[str]:
    """Names shown on media_player.source_list (hidden macros stay callable)."""
    names: list[str] = []
    for item in sources or []:
        name = str(item.get("name") or "").strip()
        if name and not item.get("hidden"):
            names.append(name)
    return names


def source_names(sources: list[dict[str, Any]]) -> list[str]:
    return [str(source[ATTR_NAME]) for source in sources if source.get(ATTR_NAME)]


def name_in_use(
    sources: list[dict[str, Any]], name: str, *, exclude_index: int | None = None
) -> bool:
    wanted = normalize_name(name).casefold()
    if not wanted:
        return False
    for index, source in enumerate(sources):
        if exclude_index is not None and index == exclude_index:
            continue
        if str(source.get(ATTR_NAME, "")).casefold() == wanted:
            return True
    return False


def source_key_delay(source: dict[str, Any], default: float) -> float:
    """Per-source interval when set, else the integration default."""
    raw = source.get("interval")
    if raw is None:
        return default
    return parse_interval(raw)
