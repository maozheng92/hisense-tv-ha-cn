"""Remove leftover remoter button entities. Keys are not HA buttons."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN


def should_remove_button_registry_entry(
    *,
    domain: str,
    platform: str,
) -> bool:
    """True when a leftover hisense_e7n button row should be deleted."""
    return domain == "button" and platform == DOMAIN


def async_remove_legacy_button_entities(hass: Any, entry: Any) -> int:
    """Delete remoter / custom-source button entities created by older versions."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    removed = 0
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if not should_remove_button_registry_entry(
            domain=entity_entry.domain,
            platform=entity_entry.platform,
        ):
            continue
        registry.async_remove(entity_entry.entity_id)
        removed += 1
    return removed
