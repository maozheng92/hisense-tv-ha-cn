"""Remote entity that sends VIDAA / 爱家 KEY_* codes."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

import voluptuous as vol

try:
    from homeassistant.components.remote import ATTR_DELAY_SECS
except ImportError:  # pragma: no cover
    ATTR_DELAY_SECS = "delay_secs"

from .entity import HisenseTvEntity, tv_errors
from .hub import HisenseTvHub, hub_from_entry
from .keys import KEY_POWER, aijia_send_commands, normalize_key


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = hub_from_entry(hass, entry)
    async_add_entities([HisenseTvRemote(hub, entry)])
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "send_key",
        {vol.Required("key"): cv.string},
        "async_send_key_service",
    )
    platform.async_register_entity_service(
        "submit_code",
        {vol.Required("code"): cv.string},
        "async_submit_code",
    )


class HisenseTvRemote(HisenseTvEntity, RemoteEntity):
    """Send individual remote keys (works with Universal Remote Card).

    Matches tcl_tv: unnamed entity so HA uses the device name and the
    remote platform default icon.
    """

    _attr_name = None

    def __init__(self, hub: HisenseTvHub, entry: ConfigEntry) -> None:
        super().__init__(hub, entry)
        self._attr_unique_id = f"{entry.entry_id}_remote"

    @property
    def is_on(self) -> bool:
        return self.hub.tv.available

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hub.async_turn_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        with tv_errors():
            await self.hub.client.async_turn_off()

    async def async_send_key_service(self, key: str) -> None:
        with tv_errors():
            await self.hub.async_send_key(normalize_key(key))

    async def async_submit_code(self, code: str) -> None:
        with tv_errors():
            await self.hub.client.async_submit_code(code)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ble = self.hub.client.ble
        return {
            "commands": aijia_send_commands(),
            "ble_connected": bool(ble is not None and getattr(ble, "connected", False)),
        }

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        repeats = int(kwargs.get("num_repeats") or 1)
        delay = float(kwargs.get(ATTR_DELAY_SECS) or kwargs.get("delay_secs") or 0.12)
        for raw in command:
            key = normalize_key(str(raw))
            for _ in range(max(1, repeats)):
                with tv_errors():
                    if key == KEY_POWER and not self.hub.client.state.available:
                        await self.hub.async_turn_on()
                    else:
                        await self.hub.async_send_key(key)
                if delay:
                    await asyncio.sleep(delay)
