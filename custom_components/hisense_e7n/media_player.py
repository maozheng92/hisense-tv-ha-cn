"""TV media player for Hisense E7N Pro.

HDMI/custom macros on source_list. 爱家 我的应用 is a cloud column; the
media browser is always advertised so more-info keeps 「浏览媒体」.
VOLUME_SET is never advertised.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

try:
    from homeassistant.components.media_player.errors import BrowseError
except ImportError:  # pragma: no cover
    BrowseError = HomeAssistantError  # type: ignore[misc,assignment]

try:
    from homeassistant.exceptions import ServiceValidationError
except ImportError:  # pragma: no cover
    ServiceValidationError = HomeAssistantError  # type: ignore[misc,assignment]

from .apps import app_media_id, app_summary, format_app_title, resolve_app
from .entity import HisenseTvEntity, tv_errors
from .hub import HisenseTvHub, hub_from_entry
from .keys import (
    KEY_CHANNELDOWN,
    KEY_CHANNELUP,
    KEY_PAUSE,
    KEY_PLAY,
    KEY_STOP,
    KEY_VOLUMEDOWN,
    KEY_VOLUMEUP,
)

_LOGGER = logging.getLogger(__name__)
_HINT_MEDIA_IDS = frozenset({"", "apps", "aijia-login", "apps-hint", "apps-refresh"})

# No VOLUME_SET: +/- uses MQTT sendkey KEY_VOLUME* + LAN remoter (eARC).
# VOLUME_STEP only — never a HA slider.
_BASE_SUPPORT = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.BROWSE_MEDIA
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = hub_from_entry(hass, entry)
    async_add_entities([HisenseTvMediaPlayer(hub, entry)])
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "launch_app",
        {
            vol.Required("name"): cv.string,
            vol.Optional("url"): cv.string,
        },
        "async_launch_app_service",
    )
    platform.async_register_entity_service(
        "refresh_apps",
        {},
        "async_refresh_apps_service",
    )


class HisenseTvMediaPlayer(HisenseTvEntity, MediaPlayerEntity):
    """One E7N Pro as a Home Assistant TV."""

    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_name = None
    _attr_icon = "mdi:television"
    _attr_translation_key = "tv"

    def __init__(self, hub: HisenseTvHub, entry: ConfigEntry) -> None:
        super().__init__(hub, entry)
        self._attr_unique_id = f"{entry.entry_id}_media_player"

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        features = _BASE_SUPPORT
        if self.source_list:
            features |= MediaPlayerEntityFeature.SELECT_SOURCE
        return features

    @property
    def state(self) -> MediaPlayerState:
        tv = self.hub.tv
        if not tv.available or not tv.power_on:
            return MediaPlayerState.OFF
        kind = (tv.statetype or "").lower()
        if "pause" in kind:
            return MediaPlayerState.PAUSED
        if kind in {"app", "video", "livetv", "play"}:
            return MediaPlayerState.PLAYING
        return MediaPlayerState.ON

    @property
    def volume_level(self) -> float | None:
        volume = self.hub.tv.volume
        if volume is None:
            return None
        return max(0.0, min(1.0, volume / 100.0))

    @property
    def is_volume_muted(self) -> bool | None:
        """VIDAA MQTT ``volumechange`` reports mute (``mute`` / type 2)."""
        tv = self.hub.tv
        if not tv.available:
            return None
        return tv.muted

    @property
    def media_title(self) -> str | None:
        return self.hub.tv.current_app or self.source

    @property
    def source(self) -> str | None:
        names = self.source_list or []
        current_app = self.hub.tv.current_app
        if current_app in names:
            return current_app
        selected = self.hub.selected_source
        if selected in names:
            return selected
        source_name = self.hub.tv.source_name
        if source_name in names:
            return source_name
        return source_name or current_app

    @property
    def source_list(self) -> list[str] | None:
        names = self.hub.visible_source_names
        return names or None

    async def async_turn_on(self) -> None:
        await self.hub.async_turn_on()

    async def async_turn_off(self) -> None:
        with tv_errors():
            await self.hub.client.async_turn_off()

    async def async_volume_up(self) -> None:
        await self.hub.async_send_key(KEY_VOLUMEUP)
        self.async_write_ha_state()

    async def async_volume_down(self) -> None:
        await self.hub.async_send_key(KEY_VOLUMEDOWN)
        self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        tv = self.hub.client.state
        if tv.muted != mute:
            with tv_errors():
                await self.hub.client.async_toggle_mute()
            self.async_write_ha_state()

    async def async_media_play(self) -> None:
        with tv_errors():
            await self.hub.client.async_send_key(KEY_PLAY)

    async def async_media_pause(self) -> None:
        with tv_errors():
            await self.hub.client.async_send_key(KEY_PAUSE)

    async def async_media_stop(self) -> None:
        with tv_errors():
            await self.hub.client.async_send_key(KEY_STOP)

    async def async_media_next_track(self) -> None:
        with tv_errors():
            await self.hub.client.async_send_key(KEY_CHANNELUP)

    async def async_media_previous_track(self) -> None:
        with tv_errors():
            await self.hub.client.async_send_key(KEY_CHANNELDOWN)

    async def async_select_source(self, source: str) -> None:
        with tv_errors():
            await self.hub.async_select_source(source)

    async def async_launch_app_service(self, name: str, url: str | None = None) -> None:
        with tv_errors():
            await self.hub.async_launch_app(name, url)

    async def async_refresh_apps_service(self) -> None:
        with tv_errors():
            await self.hub.async_refresh_apps()

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        if media_type not in (MediaType.APP, "app", MediaType.APPS, "apps"):
            raise ServiceValidationError(
                f"Unsupported media type {media_type!r}; use app"
            )
        await self._async_ensure_cloud_apps(force=media_id in _HINT_MEDIA_IDS)
        if media_id in _HINT_MEDIA_IDS:
            if self.hub.tv.apps:
                return
            raise ServiceValidationError(_apps_empty_message(self.hub))
        app = resolve_app(self.hub.tv.apps, media_id)
        if app is None:
            await self._async_ensure_cloud_apps(force=True)
            app = resolve_app(self.hub.tv.apps, media_id)
        if app is None:
            raise ServiceValidationError(
                f"Unknown app {media_id!r}; open 我的应用 on this media player"
            )
        with tv_errors():
            await self.hub.async_launch_resolved_app(app)

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        if (
            (media_content_type is None and media_content_id is None)
            or media_content_id in _HINT_MEDIA_IDS
            or media_content_type in (MediaType.APPS, "apps")
        ):
            apps = list(self.hub.tv.apps)
            if not apps:
                await self._async_ensure_cloud_apps(
                    force=media_content_id in ("apps-refresh", "aijia-login")
                )
                apps = list(self.hub.tv.apps)
            children = [_app_item(app) for app in apps]
            if children:
                return BrowseMedia(
                    title="我的应用",
                    media_class=MediaClass.APP,
                    media_content_id="apps",
                    media_content_type=MediaType.APPS,
                    can_play=False,
                    can_expand=True,
                    children=children,
                    children_media_class=MediaClass.APP,
                )
            return BrowseMedia(
                title="我的应用",
                media_class=MediaClass.DIRECTORY,
                media_content_id="apps",
                media_content_type=MediaType.APPS,
                can_play=False,
                can_expand=True,
                children=[_apps_placeholder(self.hub.aijia_logged_in)],
                children_media_class=MediaClass.DIRECTORY,
            )
        raise BrowseError("Media not found")

    async def _async_ensure_cloud_apps(self, force: bool = False) -> None:
        self.hub.sync_aijia_from_entry()
        if not self.hub.aijia_logged_in:
            return
        if self.hub.tv.apps and not force:
            return
        try:
            await self.hub.async_refresh_aijia_apps(force=force)
        except HomeAssistantError:
            raise
        except Exception:  # noqa: BLE001
            _LOGGER.debug("爱家云刷新我的应用失败", exc_info=True)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        self.hub.sync_aijia_from_entry()
        tv = self.hub.client.state
        return {
            "statetype": tv.statetype,
            "auth_mode": tv.auth_mode,
            "source_id": tv.source_id,
            "power_on_mode": self.hub.power_on_mode,
            "current_app": tv.current_app,
            "aijia_account": (self.hub.aijia.username if self.hub.aijia else "") or None,
            "aijia_logged_in": self.hub.aijia_logged_in,
            "apps": [format_app_title(app) for app in tv.apps if format_app_title(app)],
            "installed_apps": [app_summary(app) for app in tv.apps],
            "custom_sources": [
                {
                    "name": item["name"],
                    "keys": list(item.get("keys") or []),
                    "buttons": list(item.get("buttons") or item.get("keys") or []),
                    **({"hidden": True} if item.get("hidden") else {}),
                }
                for item in self.hub.custom_sources
            ],
        }


def _apps_empty_message(hub: HisenseTvHub) -> str:
    if hub.aijia_logged_in:
        account = (hub.aijia.username if hub.aijia else "") or ""
        who = f"（{account}）" if account else ""
        return (
            f"已登录爱家{who}，但没有拉到「我的应用」。"
            "请确认这台电视已绑定到该账号，并查看 Home Assistant 日志里的「爱家」。"
        )
    return "请在集成选项登录爱家账号后再打开「我的应用」。提交账号后令牌会立刻生效，不必等选项菜单里的「保存」。"


def _apps_placeholder(logged_in: bool) -> BrowseMedia:
    """Keep 浏览媒体 from rendering HA's empty 「没有项目」dialog.

    Must not be MediaType.APP: the more-info browser still calls play_media
    on APP rows even when can_play is False.
    """
    title = (
        "已登录爱家，点这里重新加载「我的应用」"
        if logged_in
        else "请在集成选项登录爱家账号以加载「我的应用」"
    )
    return BrowseMedia(
        title=title,
        media_class=MediaClass.DIRECTORY,
        media_content_id="apps-refresh",
        media_content_type=MediaType.APPS,
        can_play=False,
        can_expand=True,
    )


def _app_item(app: dict[str, Any]) -> BrowseMedia:
    icon = str(app.get("icon") or "")
    thumbnail = icon if icon.startswith("http") else None
    return BrowseMedia(
        title=format_app_title(app) or str(app.get("name") or ""),
        media_class=MediaClass.APP,
        media_content_id=app_media_id(app),
        media_content_type=MediaType.APP,
        can_play=True,
        can_expand=False,
        thumbnail=thumbnail,
    )
