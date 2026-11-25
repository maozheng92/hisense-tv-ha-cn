"""Shared entity helpers (TCL TclTvEntity + tv_errors)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

try:
    from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
except ImportError:  # pragma: no cover - HA < 2022.8
    CONNECTION_BLUETOOTH = "bluetooth"

from .const import CONF_BLE_ADDRESS, CONF_CLIENT_UUID, DEFAULT_NAME, DOMAIN
from .hub import HisenseTvHub


@contextmanager
def tv_errors() -> Iterator[None]:
    """Turn protocol ConnectionError into HomeAssistantError (TCL tv_errors)."""
    try:
        yield
    except HomeAssistantError:
        raise
    except ConnectionError as err:
        raise HomeAssistantError(str(err)) from err
    except OSError as err:
        raise HomeAssistantError(str(err)) from err


class HisenseTvEntity(CoordinatorEntity[HisenseTvHub]):
    """Base entity bound to one E7N Pro."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: HisenseTvHub, entry: ConfigEntry) -> None:
        super().__init__(hub)
        self._entry = entry
        uuid = entry.data.get(CONF_CLIENT_UUID, entry.entry_id)
        host = entry.data.get(CONF_HOST, "")
        mac = (entry.data.get(CONF_MAC) or entry.options.get(CONF_MAC) or "").strip()
        ble = (entry.data.get(CONF_BLE_ADDRESS) or entry.options.get(CONF_BLE_ADDRESS) or "").strip()
        connections = {(CONNECTION_NETWORK_MAC, mac.lower())} if mac else set()
        if ble:
            connections.add((CONNECTION_BLUETOOTH, ble.upper()))
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, uuid or host)},
            connections=connections,
            manufacturer="Hisense",
            model="E7N Pro",
            name=entry.data.get(CONF_NAME) or DEFAULT_NAME,
        )

    @property
    def hub(self) -> HisenseTvHub:
        return self.coordinator

    @property
    def available(self) -> bool:
        if self.hub.client.state.available:
            return True
        return self.hub.can_power_on
