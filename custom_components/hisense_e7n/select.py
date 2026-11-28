"""爱家 电视应用 → 我的应用. Choosing a row opens that app on the TV."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .apps import app_choice_names, current_app_option
from .entity import HisenseTvEntity, tv_errors
from .hub import HisenseTvHub, hub_from_entry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = hub_from_entry(hass, entry)
    async_add_entities([HisenseTvMyAppsSelect(hub, entry)])


class HisenseTvMyAppsSelect(HisenseTvEntity, SelectEntity):
    """Installed apps from MQTT ``applist``, opened like 爱家 「电视打开」."""

    _attr_translation_key = "my_apps"
    _attr_icon = "mdi:application-outline"

    def __init__(self, hub: HisenseTvHub, entry: ConfigEntry) -> None:
        super().__init__(hub, entry)
        self._attr_unique_id = f"{entry.entry_id}_my_apps"

    @property
    def options(self) -> list[str]:
        return app_choice_names(self.hub.tv.apps)

    @property
    def current_option(self) -> str | None:
        tv = self.hub.tv
        return current_app_option(tv.apps, tv.current_app, self.hub.last_app)

    async def async_select_option(self, option: str) -> None:
        with tv_errors():
            await self.hub.async_launch_app(option)
