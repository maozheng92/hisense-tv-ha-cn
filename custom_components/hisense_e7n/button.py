"""爱家电视遥控页上的实体按键."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .button_visibility import should_hide_button_registry_entry
from .custom_sources import custom_source_slug
from .entity import HisenseTvEntity, tv_errors
from .hub import HisenseTvHub, hub_from_entry
from .keys import AIJIA_REMOTER_BUTTONS, KEY_POWER, RemoterButton

_LOGGER = logging.getLogger(__name__)


@callback
def async_hide_existing_buttons(hass: HomeAssistant, entry: ConfigEntry) -> int:
    """Hide this entry's button entities in the registry without disabling them."""
    registry = er.async_get(hass)
    hidden = 0
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if not should_hide_button_registry_entry(
            domain=entity_entry.domain,
            platform=entity_entry.platform,
            hidden_by=entity_entry.hidden_by,
        ):
            continue
        registry.async_update_entity(
            entity_entry.entity_id,
            hidden_by=er.RegistryEntryHider.INTEGRATION,
        )
        hidden += 1
    if hidden:
        _LOGGER.info(
            "Hid %s existing remoter/custom-source button(s) for %s",
            hidden,
            entry.entry_id,
        )
    return hidden


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = hub_from_entry(hass, entry)
    entities: list[ButtonEntity] = [
        HisenseTvRemoterButton(hub, entry, spec) for spec in AIJIA_REMOTER_BUTTONS
    ]
    entities.extend(
        HisenseTvCustomSourceButton(hub, entry, source)
        for source in hub.custom_sources
    )
    async_add_entities(entities)
    # New entities honour visible_default=False; migrate older visible rows.
    async_hide_existing_buttons(hass, entry)


class HisenseTvRemoterButton(HisenseTvEntity, ButtonEntity):
    """One 爱家 remoter key as a Home Assistant button.

    Hidden from the default UI so the device page stays clean, but still
    enabled and callable from automations, scripts, and ``button.press``.
    """

    _attr_entity_registry_visible_default = False

    def __init__(
        self,
        hub: HisenseTvHub,
        entry: ConfigEntry,
        spec: RemoterButton,
    ) -> None:
        super().__init__(hub, entry)
        self._spec = spec
        self._attr_unique_id = f"{entry.entry_id}_{spec.slug}"
        self._attr_translation_key = spec.translation_key
        self._attr_icon = spec.icon

    @property
    def available(self) -> bool:
        if self._spec.kind == "power":
            return super().available
        return self.hub.client.state.available

    async def async_press(self) -> None:
        client = self.hub.client
        kind = self._spec.kind
        if kind == "power":
            if not client.state.available:
                await self.hub.async_turn_on()
            else:
                with tv_errors():
                    await client.async_send_key(KEY_POWER)
            return
        if kind == "screenshot":
            with tv_errors():
                await self.hub.async_capture_and_store_screenshot()
            return
        if kind == "source":
            with tv_errors():
                await client.async_open_source()
            return
        if kind == "smart_image":
            with tv_errors():
                await client.async_push_smart_image()
            return
        with tv_errors():
            await self.hub.async_send_key(self._spec.payload or self._spec.slug)


class HisenseTvCustomSourceButton(HisenseTvEntity, ButtonEntity):
    """One user-defined input switched by a remoter key sequence."""

    _attr_icon = "mdi:video-input-hdmi"
    _attr_entity_registry_visible_default = False

    def __init__(
        self,
        hub: HisenseTvHub,
        entry: ConfigEntry,
        source: dict[str, Any],
    ) -> None:
        super().__init__(hub, entry)
        self._source_name = str(source["name"])
        slug = custom_source_slug(self._source_name)
        self._attr_unique_id = f"{entry.entry_id}_custom_source_{slug}"
        self._attr_name = self._source_name

    @property
    def available(self) -> bool:
        return self.hub.client.state.available

    async def async_press(self) -> None:
        with tv_errors():
            await self.hub.async_press_source_buttons(self._source_name)
