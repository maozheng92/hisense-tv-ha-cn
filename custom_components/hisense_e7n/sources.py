"""Input-source helpers (TCL module name). VIDAA macros live in custom_sources."""

from __future__ import annotations

from .custom_sources import (  # noqa: F401
    ATTR_BUTTONS,
    ATTR_GO_BACK,
    ATTR_HIDDEN,
    ATTR_INTERVAL,
    ATTR_NAME,
    SEQUENCE_BUTTON_KEYS,
    classify_source_action,
    copy_sources,
    custom_source_slug,
    find_custom_source,
    find_source_index,
    format_key_sequence,
    move_custom_source,
    normalize_custom_sources,
    parse_custom_sources_text,
    parse_key_sequence,
    parse_source_actions,
    serialize_custom_sources,
    source_key_delay,
    source_names,
    source_payload,
    summarize_custom_sources,
    visible_source_names,
)
