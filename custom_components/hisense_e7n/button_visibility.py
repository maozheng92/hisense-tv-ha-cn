"""Remove leftover remoter button and 我的应用 select entities."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN


def should_remove_button_registry_entry(
    *,
    domain: str,
    platform: str,
    unique_id: str = "",
) -> bool:
    """True when a leftover hisense_e7n row should be deleted."""
    if platform != DOMAIN:
        return False
    if domain == "button":
        return True
    return domain == "select" and str(unique_id).endswith("_my_apps")


def async_remove_legacy_button_entities(hass: Any, entry: Any) -> int:
    """Delete remoter buttons and the 1.24.0 我的应用 select (shows unknown)."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    removed = 0
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if not should_remove_button_registry_entry(
            domain=entity_entry.domain,
            platform=entity_entry.platform,
            unique_id=str(entity_entry.unique_id or ""),
        ):
            continue
        registry.async_remove(entity_entry.entity_id)
        removed += 1
    return removed
