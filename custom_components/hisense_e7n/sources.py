"""Input-source helpers (TCL module name). VIDAA macros live in custom_sources."""

from __future__ import annotations

from .custom_sources import (  # noqa: F401
    SEQUENCE_BUTTON_KEYS,
    copy_sources,
    custom_source_slug,
    find_custom_source,
    format_key_sequence,
    move_custom_source,
    normalize_custom_sources,
    parse_custom_sources_text,
    parse_key_sequence,
    serialize_custom_sources,
    source_key_delay,
    summarize_custom_sources,
    visible_source_names,
)
