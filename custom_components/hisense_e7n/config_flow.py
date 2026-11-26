"""Config flow for Hisense E7N Pro. Options UX follows tcl_tv."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

try:
    from homeassistant.config_entries import ConfigFlowResult
except ImportError:  # pragma: no cover - HA < 2024.4
    from homeassistant.data_entry_flow import FlowResult as ConfigFlowResult

try:
    from homeassistant.config_entries import OptionsFlowWithReload

    OPTIONS_FLOW_RELOADS = True
except ImportError:  # pragma: no cover - HA < 2024.11
    OptionsFlowWithReload = config_entries.OptionsFlow  # type: ignore[misc,assignment]
    OPTIONS_FLOW_RELOADS = False

from .certs_util import resolve_cert_candidates
from .const import (
    AUTH_MODES,
    CONF_AUTH_MODE,
    CONF_CLIENT_CERT,
    CONF_CLIENT_KEY,
    CONF_CLIENT_UUID,
    CONF_CUSTOM_SOURCES,
    CONF_POWER_ON_BUTTON,
    CONF_POWER_ON_COMMAND,
    CONF_POWER_ON_DEVICE,
    CONF_POWER_ON_MODE,
    CONF_POWER_ON_REMOTE,
    CONF_SOURCE_KEY_DELAY,
    CONF_SOURCE_ORDER,
    CONF_USE_SSL,
    CONF_VOLUME_DOWN_BUTTON,
    CONF_VOLUME_UP_BUTTON,
    DEFAULT_AUTH_MODE,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_POWER_ON_COMMAND,
    DEFAULT_SOURCE_KEY_DELAY,
    DOMAIN,
    FORM_VOLUME_DOWN_BUTTON,
    FORM_VOLUME_UP_BUTTON,
    LEGACY_SOURCE_KEY_DELAYS,
    POWER_ON_MODE_BUTTON,
    POWER_ON_MODE_REMOTE,
)
from .credentials import random_client_uuid
from .custom_sources import (
    ATTR_ACTIONS,
    ATTR_ADD_MORE,
    ATTR_BUTTONS,
    ATTR_EDIT_SEQUENCE,
    ATTR_GO_BACK,
    ATTR_HIDDEN,
    ATTR_INTERVAL,
    ATTR_NAME,
    DEFAULT_INTERVAL,
    KIND_BUTTON,
    KIND_KEY,
    MAX_INTERVAL,
    SOURCE_REPEAT_MAX,
    SOURCE_REPEAT_MIN,
    copy_sources,
    counts_for_kind,
    expand_source_steps,
    find_source_index,
    name_in_use,
    normalize_name,
    parse_button_ids,
    parse_interval,
    parse_repeat,
    sequence_kind,
    source_names,
    source_payload,
    unique_actions_of_kind,
    unknown_source_actions,
)
from .flow_helpers import (
    button_choice_selector,
    format_action_label,
    format_source_sequence,
    hisense_key_choice_selector,
    ir_codes_filename,
    ir_details_schema,
    ir_remote_requires_device,
    ordered_choice_selector,
    remote_step_schema,
    source_kind_label,
)
from .power import (
    POWER_ON_DOMAINS,
    POWER_ON_MODES,
    clean_power_on_fields,
    infer_power_on_mode,
    normalize_power_on_entity,
    power_on_form_errors,
    volume_button_form_errors,
    volume_form_suggested,
)
from .tv_client import HisenseTvClient, classify_connect_error

POWER_ON_BUTTON_SELECTOR = EntitySelector(
    EntitySelectorConfig(domain=list(POWER_ON_DOMAINS), multiple=False)
)
VOLUME_BUTTON_SELECTOR = EntitySelector(
    EntitySelectorConfig(domain=list(POWER_ON_DOMAINS), multiple=False)
)
POWER_ON_MODE_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=list(POWER_ON_MODES),
        mode=SelectSelectorMode.DROPDOWN,
        translation_key="power_on_mode",
    )
)


def _go_back_chosen(value: Any) -> bool:
    """True when the footer Back button posted ``go_back``."""
    if value in (True, ATTR_GO_BACK, "true", "1", 1):
        return True
    if isinstance(value, (list, tuple)):
        return any(_go_back_chosen(item) for item in value)
    return False


class _SchemaWithBack(vol.Schema):
    """Accept ``{go_back: True}`` from the footer Back button without other fields."""

    def __call__(self, data: Any) -> Any:
        if isinstance(data, dict) and _go_back_chosen(data.get(ATTR_GO_BACK)):
            return {ATTR_GO_BACK: True}
        return super().__call__(data)


def _user_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST): TextSelector(TextSelectorConfig(type="text")),
            vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Optional(CONF_MAC): TextSelector(TextSelectorConfig(type="text")),
            vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
            vol.Optional(CONF_AUTH_MODE, default=DEFAULT_AUTH_MODE): SelectSelector(
                SelectSelectorConfig(
                    options=AUTH_MODES,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_CLIENT_CERT): str,
            vol.Optional(CONF_CLIENT_KEY): str,
        }
    )


def _power_on_add_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_POWER_ON_MODE, default=POWER_ON_MODE_BUTTON): POWER_ON_MODE_SELECTOR,
            vol.Optional(CONF_POWER_ON_BUTTON): POWER_ON_BUTTON_SELECTOR,
            vol.Optional(CONF_POWER_ON_REMOTE): EntitySelector(
                EntitySelectorConfig(domain=["remote"], multiple=False)
            ),
            vol.Optional(CONF_POWER_ON_COMMAND, default=DEFAULT_POWER_ON_COMMAND): TextSelector(
                TextSelectorConfig(type="text")
            ),
            vol.Optional(CONF_POWER_ON_DEVICE): TextSelector(TextSelectorConfig(type="text")),
        }
    )


def _volume_add_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(FORM_VOLUME_UP_BUTTON): VOLUME_BUTTON_SELECTOR,
            vol.Optional(FORM_VOLUME_DOWN_BUTTON): VOLUME_BUTTON_SELECTOR,
        }
    )


class HisenseE7NConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hisense E7N Pro."""

    VERSION = 1

    def __init__(self) -> None:
        self._client: HisenseTvClient | None = None
        self._pending: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input.get(CONF_PORT, DEFAULT_PORT))
            uuid = random_client_uuid()
            certfile = (user_input.get(CONF_CLIENT_CERT) or "").strip() or None
            keyfile = (user_input.get(CONF_CLIENT_KEY) or "").strip() or None
            cert_dir = Path(self.hass.config.config_dir) / "hisense_e7n" / "setup"
            search_roots = [
                Path(self.hass.config.config_dir),
                Path(__file__).resolve().parents[2],
            ]
            cert_pairs = await self.hass.async_add_executor_job(
                resolve_cert_candidates,
                cert_dir,
                certfile,
                keyfile,
                search_roots,
            )
            primary_cert, primary_key = cert_pairs[0] if cert_pairs else (certfile, keyfile)

            await self.async_set_unique_id(host.lower())
            self._abort_if_unique_id_configured()

            client = HisenseTvClient(
                host,
                port=port,
                uuid=uuid,
                tv_mac=(user_input.get(CONF_MAC) or "").strip() or None,
                auth_mode=user_input.get(CONF_AUTH_MODE, DEFAULT_AUTH_MODE),
                certfile=primary_cert,
                keyfile=primary_key,
                cert_pairs=cert_pairs,
                loop=self.hass.loop,
            )
            self._client = client
            mqtt_ok = False
            try:
                await client.async_connect()
                mqtt_ok = True
            except ConnectionError as err:
                errors["base"] = classify_connect_error(str(err))
            if mqtt_ok:
                try:
                    await client.async_pair()
                except Exception:  # noqa: BLE001
                    pass
            if not errors:
                self._pending = {
                    CONF_HOST: host,
                    CONF_PORT: port,
                    CONF_MAC: (user_input.get(CONF_MAC) or "").strip(),
                    CONF_NAME: user_input.get(CONF_NAME) or DEFAULT_NAME,
                    CONF_AUTH_MODE: user_input.get(CONF_AUTH_MODE, DEFAULT_AUTH_MODE),
                    CONF_CLIENT_UUID: uuid,
                    CONF_CLIENT_CERT: client.certfile or primary_cert,
                    CONF_CLIENT_KEY: client.keyfile or primary_key,
                    CONF_USE_SSL: True if client.use_ssl is None else client.use_ssl,
                }
                await client.async_disconnect()
                self._client = None
                return await self.async_step_power_on()
            await client.async_disconnect()
            self._client = None

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
            errors=errors,
        )

    async def async_step_power_on(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            merged = {**self._pending, **user_input}
            errors = power_on_form_errors(merged)
            if not errors:
                cleaned = clean_power_on_fields(merged)
                self._pending.update(
                    {
                        CONF_POWER_ON_MODE: cleaned[CONF_POWER_ON_MODE],
                        CONF_POWER_ON_BUTTON: cleaned.get(CONF_POWER_ON_BUTTON) or "",
                        CONF_POWER_ON_REMOTE: cleaned.get(CONF_POWER_ON_REMOTE) or "",
                        CONF_POWER_ON_COMMAND: cleaned.get(CONF_POWER_ON_COMMAND)
                        or DEFAULT_POWER_ON_COMMAND,
                        CONF_POWER_ON_DEVICE: cleaned.get(CONF_POWER_ON_DEVICE) or "",
                    }
                )
                return await self.async_step_volume()
        return self.async_show_form(
            step_id="power_on",
            data_schema=_power_on_add_schema(),
            errors=errors,
        )

    async def async_step_volume(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            merged = {**self._pending, **user_input}
            errors = volume_button_form_errors(merged)
            if not errors:
                cleaned = clean_power_on_fields(merged)
                self._pending[CONF_VOLUME_UP_BUTTON] = cleaned.get(CONF_VOLUME_UP_BUTTON) or ""
                self._pending[CONF_VOLUME_DOWN_BUTTON] = cleaned.get(CONF_VOLUME_DOWN_BUTTON) or ""
                return self.async_create_entry(
                    title=self._pending.get(CONF_NAME) or DEFAULT_NAME,
                    data=self._pending,
                )
        return self.async_show_form(
            step_id="volume",
            data_schema=_volume_add_schema(),
            errors=errors,
        )

    def async_remove(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            client.disconnect_blocking()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowWithReload:
        return HisenseE7NOptionsFlow(config_entry)


class HisenseE7NOptionsFlow(OptionsFlowWithReload):
    """Draft menu: connection, power-on, volume, sources; one Save reloads."""

    def __init__(self, config_entry: config_entries.ConfigEntry | None = None) -> None:
        if config_entry is not None:
            self._config_entry = config_entry
        self._draft_ready = False
        self._data: dict[str, Any] = {}
        self._edit_index: int | None = None
        self._pending_remote: str | None = None
        self._source_meta: dict[str, Any] | None = None
        self._source_original_buttons: list[str] = []
        self._seq_kind: str | None = None
        self._seq_picked: list[str] = []
        self._seq_counts: dict[str, int] = {}
        self._seq_actions: list[str] = []

    def _entry(self) -> config_entries.ConfigEntry:
        return getattr(self, "_config_entry", None) or self.config_entry

    def _merged(self) -> dict[str, Any]:
        return {**self._entry().data, **self._entry().options}

    def _clamp_delay(self, value: object | None) -> float:
        try:
            delay = DEFAULT_SOURCE_KEY_DELAY if value is None else float(value)
        except (TypeError, ValueError):
            delay = DEFAULT_SOURCE_KEY_DELAY
        if any(abs(delay - legacy) < 1e-9 for legacy in LEGACY_SOURCE_KEY_DELAYS):
            delay = DEFAULT_SOURCE_KEY_DELAY
        return max(0.0, min(MAX_INTERVAL, delay))

    def _ensure_draft(self) -> None:
        if self._draft_ready:
            return
        merged = self._merged()
        self._data = {
            CONF_HOST: str(merged.get(CONF_HOST, "")).strip(),
            CONF_PORT: int(merged.get(CONF_PORT, DEFAULT_PORT)),
            CONF_MAC: (merged.get(CONF_MAC) or "").strip(),
            CONF_NAME: merged.get(CONF_NAME) or DEFAULT_NAME,
            CONF_POWER_ON_MODE: infer_power_on_mode(
                merged.get(CONF_POWER_ON_MODE),
                merged.get(CONF_POWER_ON_BUTTON),
                merged.get(CONF_POWER_ON_REMOTE),
                merged.get(CONF_MAC),
            ),
            CONF_POWER_ON_BUTTON: normalize_power_on_entity(merged.get(CONF_POWER_ON_BUTTON))
            or "",
            CONF_POWER_ON_REMOTE: normalize_power_on_entity(merged.get(CONF_POWER_ON_REMOTE))
            or "",
            CONF_POWER_ON_COMMAND: merged.get(CONF_POWER_ON_COMMAND) or DEFAULT_POWER_ON_COMMAND,
            CONF_POWER_ON_DEVICE: merged.get(CONF_POWER_ON_DEVICE) or "",
            CONF_VOLUME_UP_BUTTON: normalize_power_on_entity(merged.get(CONF_VOLUME_UP_BUTTON))
            or "",
            CONF_VOLUME_DOWN_BUTTON: normalize_power_on_entity(
                merged.get(CONF_VOLUME_DOWN_BUTTON)
            )
            or "",
            CONF_SOURCE_KEY_DELAY: self._clamp_delay(merged.get(CONF_SOURCE_KEY_DELAY)),
            CONF_CUSTOM_SOURCES: copy_sources(merged.get(CONF_CUSTOM_SOURCES)),
        }
        self._draft_ready = True

    def _wants_back(self, user_input: dict[str, Any] | None) -> bool:
        return bool(user_input) and _go_back_chosen(user_input.get(ATTR_GO_BACK))

    def _with_back(self, schema: vol.Schema | dict[Any, Any]) -> vol.Schema:
        # No in-form Go-back control. www/hisense_e7n_flow.js posts
        # {go_back: True} from the dialog footer (返回 left, 提交 right).
        mapping = schema.schema if isinstance(schema, vol.Schema) else schema
        return _SchemaWithBack(mapping)

    def _show_form(
        self,
        step_id: str,
        schema: vol.Schema | dict[Any, Any],
        *,
        errors: dict[str, str] | None = None,
        placeholders: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        merged: dict[str, str] = {"host": "—"}
        if self._draft_ready:
            merged.update(self._menu_placeholders())
        if placeholders:
            merged.update(placeholders)
        kwargs: dict[str, Any] = {
            "step_id": step_id,
            "data_schema": self._with_back(schema),
            "description_placeholders": merged,
        }
        if errors:
            kwargs["errors"] = errors
        return self.async_show_form(**kwargs)

    def _menu_placeholders(self) -> dict[str, str]:
        mode = self._data.get(CONF_POWER_ON_MODE) or POWER_ON_MODE_BUTTON
        remote = self._data.get(CONF_POWER_ON_REMOTE)
        command = self._data.get(CONF_POWER_ON_COMMAND)
        if mode == POWER_ON_MODE_REMOTE and remote and command:
            power_on = f"{remote} / {command}"
        elif mode == "wol":
            power_on = "Wake-on-LAN"
        else:
            button = self._data.get(CONF_POWER_ON_BUTTON) or "—"
            power_on = str(button)
        names = source_names(self._data[CONF_CUSTOM_SOURCES])
        volume_up = self._data.get(CONF_VOLUME_UP_BUTTON) or "—"
        volume_down = self._data.get(CONF_VOLUME_DOWN_BUTTON) or "—"
        return {
            "power_on": str(power_on),
            "source_count": str(len(names)),
            "source_names": ", ".join(names) if names else "—",
            "volume_up": str(volume_up),
            "volume_down": str(volume_down),
            "host": str(self._data.get(CONF_HOST) or "—"),
        }

    def _saved_options(self) -> dict[str, Any]:
        cleaned = clean_power_on_fields(dict(self._data))
        sources = copy_sources(cleaned.get(CONF_CUSTOM_SOURCES))
        return {
            CONF_HOST: str(cleaned.get(CONF_HOST, "")).strip(),
            CONF_PORT: int(cleaned.get(CONF_PORT, DEFAULT_PORT)),
            CONF_MAC: (cleaned.get(CONF_MAC) or "").strip(),
            CONF_NAME: cleaned.get(CONF_NAME) or DEFAULT_NAME,
            CONF_POWER_ON_MODE: cleaned[CONF_POWER_ON_MODE],
            CONF_POWER_ON_BUTTON: cleaned.get(CONF_POWER_ON_BUTTON) or "",
            CONF_POWER_ON_REMOTE: cleaned.get(CONF_POWER_ON_REMOTE) or "",
            CONF_POWER_ON_COMMAND: cleaned.get(CONF_POWER_ON_COMMAND) or DEFAULT_POWER_ON_COMMAND,
            CONF_POWER_ON_DEVICE: cleaned.get(CONF_POWER_ON_DEVICE) or "",
            CONF_VOLUME_UP_BUTTON: cleaned.get(CONF_VOLUME_UP_BUTTON) or "",
            CONF_VOLUME_DOWN_BUTTON: cleaned.get(CONF_VOLUME_DOWN_BUTTON) or "",
            CONF_CUSTOM_SOURCES: sources,
            CONF_SOURCE_KEY_DELAY: self._clamp_delay(
                cleaned.get(CONF_SOURCE_KEY_DELAY, DEFAULT_SOURCE_KEY_DELAY)
            ),
        }

    def _reset_source_seq(self) -> None:
        self._source_meta = None
        self._source_original_buttons = []
        self._seq_kind = None
        self._seq_picked = []
        self._seq_counts = {}
        self._seq_actions = []

    def _sequence_preview(self) -> str:
        actions = self._seq_actions or self._source_original_buttons
        return format_source_sequence(self.hass, actions)

    def _source_meta_schema(
        self, source: dict[str, Any] | None, *, editing: bool
    ) -> vol.Schema:
        name = source[ATTR_NAME] if source else ""
        hidden = bool(source.get(ATTR_HIDDEN)) if source else False
        interval = (
            parse_interval(source.get(ATTR_INTERVAL)) if source else DEFAULT_INTERVAL
        )
        name_field = TextSelector(TextSelectorConfig(type="text"))
        schema: dict[Any, Any] = {}
        if name:
            schema[vol.Required(ATTR_NAME, default=name)] = name_field
        else:
            schema[vol.Required(ATTR_NAME)] = name_field
        schema[vol.Required(ATTR_HIDDEN, default=hidden)] = BooleanSelector()
        schema[vol.Required(ATTR_INTERVAL, default=interval)] = NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=MAX_INTERVAL,
                step=0.1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        )
        if editing:
            schema[vol.Required(ATTR_EDIT_SEQUENCE, default=False)] = BooleanSelector()
        return vol.Schema(schema)

    def _store_source_meta(self, user_input: dict[str, Any]) -> None:
        self._source_meta = {
            ATTR_NAME: normalize_name(user_input.get(ATTR_NAME)),
            ATTR_HIDDEN: bool(user_input.get(ATTR_HIDDEN)),
            ATTR_INTERVAL: parse_interval(user_input.get(ATTR_INTERVAL)),
        }

    def _source_meta_errors(self, user_input: dict[str, Any]) -> dict[str, str]:
        name = normalize_name(user_input.get(ATTR_NAME))
        errors: dict[str, str] = {}
        if not name:
            errors[ATTR_NAME] = "name_required"
        elif name_in_use(
            self._data[CONF_CUSTOM_SOURCES], name, exclude_index=self._edit_index
        ):
            errors[ATTR_NAME] = "name_in_use"
        return errors

    def _repeat_schema(self) -> vol.Schema:
        number = NumberSelector(
            NumberSelectorConfig(
                min=SOURCE_REPEAT_MIN,
                max=SOURCE_REPEAT_MAX,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="×",
            )
        )
        schema: dict[Any, Any] = {}
        for index, action in enumerate(self._seq_picked):
            schema[
                vol.Required(
                    f"repeat_{index}",
                    default=int(self._seq_counts.get(action, 1)),
                )
            ] = number
        schema[vol.Required(ATTR_ADD_MORE, default=False)] = BooleanSelector()
        return vol.Schema(schema)

    def _pick_defaults(self) -> list[str]:
        if self._seq_picked:
            return list(self._seq_picked)
        if self._seq_actions or self._seq_kind is None:
            return []
        original = self._source_original_buttons
        if sequence_kind(original) == self._seq_kind:
            return unique_actions_of_kind(original, self._seq_kind)
        return []

    def _count_defaults(self, picked: list[str]) -> dict[str, int]:
        defaults: dict[str, int] = {}
        original = self._source_original_buttons
        if not self._seq_actions and self._seq_kind is not None:
            if sequence_kind(original) == self._seq_kind:
                defaults.update(counts_for_kind(original, self._seq_kind))
        defaults.update(self._seq_counts)
        return {action: int(defaults.get(action, 1)) for action in picked}

    def _source_pick_schema(self) -> vol.Schema:
        names = source_names(self._data[CONF_CUSTOM_SOURCES])
        return vol.Schema(
            {
                vol.Required(ATTR_NAME): SelectSelector(
                    SelectSelectorConfig(
                        options=names,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

    async def _finish_source(self) -> ConfigFlowResult:
        meta = self._source_meta
        if not meta or not self._seq_actions:
            return await self.async_step_source_seq_kind()
        preview = source_payload(
            name=str(meta[ATTR_NAME]),
            hidden=bool(meta[ATTR_HIDDEN]),
            buttons=list(self._seq_actions),
            interval=parse_interval(meta[ATTR_INTERVAL]),
        )
        if self._edit_index is None:
            self._data[CONF_CUSTOM_SOURCES].append(preview)
        else:
            self._data[CONF_CUSTOM_SOURCES][self._edit_index] = preview
        self._edit_index = None
        self._reset_source_seq()
        return await self.async_step_sources()

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        self._edit_index = None
        self._pending_remote = None
        self._reset_source_seq()
        return self.async_show_menu(
            step_id="init",
            menu_options=["connection", "power_on", "volume", "sources", "save"],
            description_placeholders=self._menu_placeholders(),
        )

    async def async_step_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        payload = self._saved_options()
        errors = {
            **power_on_form_errors(payload),
            **volume_button_form_errors(payload),
        }
        if errors:
            return self.async_show_menu(
                step_id="init",
                menu_options=["connection", "power_on", "volume", "sources", "save"],
                description_placeholders=self._menu_placeholders(),
            )
        return self.async_create_entry(title="", data=payload)

    async def async_step_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._wants_back(user_input):
                return await self.async_step_init()
            host = str(user_input.get(CONF_HOST) or "").strip()
            if not host:
                errors[CONF_HOST] = "host_required"
            else:
                self._data[CONF_HOST] = host
                self._data[CONF_PORT] = int(user_input.get(CONF_PORT, DEFAULT_PORT))
                self._data[CONF_MAC] = str(user_input.get(CONF_MAC) or "").strip()
                self._data[CONF_NAME] = user_input.get(CONF_NAME) or DEFAULT_NAME
                self._data[CONF_SOURCE_KEY_DELAY] = self._clamp_delay(
                    user_input.get(CONF_SOURCE_KEY_DELAY)
                )
                return await self.async_step_init()
        schema = {
            vol.Required(CONF_HOST, default=self._data.get(CONF_HOST, "")): str,
            vol.Optional(CONF_PORT, default=self._data.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Optional(CONF_MAC, default=self._data.get(CONF_MAC, "")): str,
            vol.Optional(CONF_NAME, default=self._data.get(CONF_NAME, DEFAULT_NAME)): str,
            vol.Optional(
                CONF_SOURCE_KEY_DELAY,
                default=self._clamp_delay(self._data.get(CONF_SOURCE_KEY_DELAY)),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=MAX_INTERVAL,
                    step=0.1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            ),
        }
        return self._show_form("connection", schema, errors=errors)

    async def async_step_power_on(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._wants_back(user_input):
                return await self.async_step_init()
            mode = user_input.get(CONF_POWER_ON_MODE) or self._data.get(CONF_POWER_ON_MODE)
            button = user_input.get(CONF_POWER_ON_BUTTON)
            remote = user_input.get(CONF_POWER_ON_REMOTE)
            self._data[CONF_POWER_ON_MODE] = infer_power_on_mode(
                mode, button, remote, self._data.get(CONF_MAC)
            )
            self._data[CONF_POWER_ON_BUTTON] = normalize_power_on_entity(button) or ""
            remote_s = normalize_power_on_entity(remote) or ""
            self._data[CONF_POWER_ON_REMOTE] = remote_s
            if self._data[CONF_POWER_ON_MODE] == POWER_ON_MODE_REMOTE and remote_s:
                self._pending_remote = remote_s
                return await self.async_step_ir_details()
            return await self.async_step_init()
        current_remote = self._data.get(CONF_POWER_ON_REMOTE) or None
        schema: dict[Any, Any] = {
            vol.Optional(
                CONF_POWER_ON_MODE,
                default=self._data.get(CONF_POWER_ON_MODE, POWER_ON_MODE_BUTTON),
            ): POWER_ON_MODE_SELECTOR,
            vol.Optional(CONF_POWER_ON_BUTTON): POWER_ON_BUTTON_SELECTOR,
        }
        schema.update(remote_step_schema(self.hass, current_remote=current_remote))
        suggested = {}
        if self._data.get(CONF_POWER_ON_BUTTON):
            suggested[CONF_POWER_ON_BUTTON] = self._data[CONF_POWER_ON_BUTTON]
        return self._show_form(
            "power_on",
            self.add_suggested_values_to_schema(vol.Schema(schema), suggested)
            if suggested
            else schema,
            errors=errors,
        )

    async def async_step_ir_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        remote = self._pending_remote or self._data.get(CONF_POWER_ON_REMOTE)
        if not isinstance(remote, str) or not remote.strip():
            return await self.async_step_power_on()
        remote = remote.strip()
        current_device = str(self._data.get(CONF_POWER_ON_DEVICE) or "")
        current_command = str(self._data.get(CONF_POWER_ON_COMMAND) or "")
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._wants_back(user_input):
                return await self.async_step_power_on()
            device_s = str(user_input.get(CONF_POWER_ON_DEVICE) or "").strip()
            command_s = str(user_input.get(CONF_POWER_ON_COMMAND) or "").strip()
            if not command_s:
                errors[CONF_POWER_ON_COMMAND] = "command_required"
            elif ir_remote_requires_device(self.hass, remote) and not device_s:
                errors[CONF_POWER_ON_DEVICE] = "device_required"
            else:
                self._data[CONF_POWER_ON_REMOTE] = remote
                self._data[CONF_POWER_ON_COMMAND] = command_s
                self._data[CONF_POWER_ON_DEVICE] = device_s
                self._data[CONF_POWER_ON_MODE] = POWER_ON_MODE_REMOTE
                self._pending_remote = None
                return await self.async_step_init()
        schema = await ir_details_schema(
            self.hass,
            remote_entity_id=remote,
            current_device=current_device,
            current_command=current_command,
        )
        return self._show_form(
            "ir_details",
            schema,
            errors=errors,
            placeholders={
                "remote_entity": remote,
                "codes_file": ir_codes_filename(self.hass, remote),
            },
        )

    async def async_step_volume(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._wants_back(user_input):
                return await self.async_step_init()
            form_errors = volume_button_form_errors({**self._data, **user_input})
            if form_errors:
                return self._show_form(
                    "volume",
                    {
                        vol.Optional(FORM_VOLUME_UP_BUTTON): VOLUME_BUTTON_SELECTOR,
                        vol.Optional(FORM_VOLUME_DOWN_BUTTON): VOLUME_BUTTON_SELECTOR,
                    },
                    errors=form_errors,
                )
            cleaned = clean_power_on_fields({**self._data, **user_input})
            self._data[CONF_VOLUME_UP_BUTTON] = cleaned.get(CONF_VOLUME_UP_BUTTON) or ""
            self._data[CONF_VOLUME_DOWN_BUTTON] = cleaned.get(CONF_VOLUME_DOWN_BUTTON) or ""
            return await self.async_step_init()
        suggested = volume_form_suggested(
            {
                CONF_VOLUME_UP_BUTTON: self._data.get(CONF_VOLUME_UP_BUTTON),
                CONF_VOLUME_DOWN_BUTTON: self._data.get(CONF_VOLUME_DOWN_BUTTON),
            }
        )
        schema = vol.Schema(
            {
                vol.Optional(FORM_VOLUME_UP_BUTTON): VOLUME_BUTTON_SELECTOR,
                vol.Optional(FORM_VOLUME_DOWN_BUTTON): VOLUME_BUTTON_SELECTOR,
            }
        )
        return self._show_form(
            "volume",
            self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    async def async_step_sources(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        self._edit_index = None
        self._reset_source_seq()
        menu = ["source_add"]
        if self._data[CONF_CUSTOM_SOURCES]:
            menu.extend(["source_edit", "source_delete"])
            if len(self._data[CONF_CUSTOM_SOURCES]) > 1:
                menu.append("source_reorder")
        # save / sources_done are footer actions; the frontend script hides the rows.
        menu.extend(["save", "sources_done"])
        return self.async_show_menu(
            step_id="sources",
            menu_options=menu,
            description_placeholders=self._menu_placeholders(),
        )

    async def async_step_sources_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_init()

    async def async_step_source_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        self._edit_index = None
        if user_input is None:
            if self._source_meta is None:
                self._reset_source_seq()
                schema = self._source_meta_schema(None, editing=False)
            else:
                schema = self._source_meta_schema(self._source_meta, editing=False)
            return self._show_form("source_add", schema)
        if self._wants_back(user_input):
            return await self.async_step_sources()
        preview = {
            ATTR_NAME: normalize_name(user_input.get(ATTR_NAME)),
            ATTR_HIDDEN: bool(user_input.get(ATTR_HIDDEN)),
            ATTR_INTERVAL: parse_interval(user_input.get(ATTR_INTERVAL)),
        }
        errors = self._source_meta_errors(user_input)
        if errors:
            return self._show_form(
                "source_add",
                self._source_meta_schema(preview, editing=False),
                errors=errors,
            )
        self._store_source_meta(user_input)
        self._seq_actions = []
        self._source_original_buttons = []
        return await self.async_step_source_seq_kind()

    async def async_step_source_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        sources = self._data[CONF_CUSTOM_SOURCES]
        if not sources:
            return await self.async_step_sources()
        if user_input is not None:
            if self._wants_back(user_input):
                return await self.async_step_sources()
            index = find_source_index(sources, user_input.get(ATTR_NAME, ""))
            if index is None:
                return self._show_form(
                    "source_edit",
                    self._source_pick_schema(),
                    errors={"base": "unknown_source"},
                )
            self._edit_index = index
            self._source_meta = None
            return await self.async_step_source_form()
        return self._show_form("source_edit", self._source_pick_schema())

    async def async_step_source_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        sources = self._data[CONF_CUSTOM_SOURCES]
        if self._edit_index is None or self._edit_index >= len(sources):
            self._edit_index = None
            return await self.async_step_source_edit()
        existing = sources[self._edit_index]
        existing_buttons = list(existing.get(ATTR_BUTTONS) or existing.get("keys") or [])
        if user_input is None:
            shown = dict(existing)
            if self._source_meta:
                shown.update(self._source_meta)
            self._source_original_buttons = existing_buttons
            return self._show_form(
                "source_form",
                self._source_meta_schema(shown, editing=True),
                placeholders={"sequence": self._sequence_preview()},
            )
        if self._wants_back(user_input):
            self._source_meta = None
            return await self.async_step_source_edit()
        preview = {
            ATTR_NAME: normalize_name(user_input.get(ATTR_NAME)),
            ATTR_HIDDEN: bool(user_input.get(ATTR_HIDDEN)),
            ATTR_INTERVAL: parse_interval(user_input.get(ATTR_INTERVAL)),
            ATTR_BUTTONS: existing_buttons,
        }
        errors = self._source_meta_errors(user_input)
        if errors:
            return self._show_form(
                "source_form",
                self._source_meta_schema(preview, editing=True),
                errors=errors,
                placeholders={"sequence": self._sequence_preview()},
            )
        self._store_source_meta(user_input)
        self._source_original_buttons = existing_buttons
        if not user_input.get(ATTR_EDIT_SEQUENCE):
            self._seq_actions = existing_buttons
            return await self._finish_source()
        self._seq_actions = []
        return await self.async_step_source_seq_kind()

    async def async_step_source_seq_kind(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        if not self._source_meta:
            return await self.async_step_sources()
        return self.async_show_menu(
            step_id="source_seq_kind",
            menu_options=[
                "source_seq_keys",
                "source_seq_buttons",
                "source_seq_kind_back",
            ],
            description_placeholders={"sequence": self._sequence_preview()},
        )

    async def async_step_source_seq_kind_back(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._edit_index is None:
            return await self.async_step_source_add()
        return await self.async_step_source_form()

    async def async_step_source_seq_keys(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._seq_kind = KIND_KEY
        return await self.async_step_source_seq_pick()

    async def async_step_source_seq_buttons(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._seq_kind = KIND_BUTTON
        return await self.async_step_source_seq_pick()

    async def async_step_source_seq_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        if self._seq_kind not in (KIND_KEY, KIND_BUTTON) or not self._source_meta:
            return await self.async_step_source_seq_kind()
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._wants_back(user_input):
                return await self.async_step_source_seq_kind()
            raw = user_input.get(ATTR_ACTIONS)
            unknown = unknown_source_actions(raw)
            picked = unique_actions_of_kind(raw, self._seq_kind)
            if unknown:
                errors[ATTR_ACTIONS] = "unknown_action"
            elif not picked:
                errors[ATTR_ACTIONS] = "pick_required"
            else:
                self._seq_picked = picked[:SOURCE_REPEAT_MAX]
                self._seq_counts = self._count_defaults(self._seq_picked)
                return await self.async_step_source_seq_repeat()
        defaults = self._pick_defaults()
        if self._seq_kind == KIND_KEY:
            selector: Any = hisense_key_choice_selector(self.hass)
        else:
            selector = button_choice_selector(self.hass, current=defaults)
        return self._show_form(
            "source_seq_pick",
            {vol.Required(ATTR_ACTIONS, default=defaults): selector},
            errors=errors,
            placeholders={
                "kind": source_kind_label(self.hass, self._seq_kind),
                "sequence": self._sequence_preview(),
            },
        )

    async def async_step_source_seq_repeat(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        if not self._seq_picked or not self._source_meta:
            return await self.async_step_source_seq_pick()
        if user_input is not None:
            if self._wants_back(user_input):
                return await self.async_step_source_seq_pick()
            steps = [
                (action, parse_repeat(user_input.get(f"repeat_{index}")))
                for index, action in enumerate(self._seq_picked)
            ]
            self._seq_actions.extend(expand_source_steps(steps))
            self._seq_picked = []
            self._seq_counts = {}
            self._seq_kind = None
            if user_input.get(ATTR_ADD_MORE):
                return await self.async_step_source_seq_kind()
            return await self._finish_source()
        repeat_help = "\n".join(
            f"{index + 1}. {format_action_label(self.hass, action)}"
            for index, action in enumerate(self._seq_picked)
        )
        placeholders = {
            "sequence": format_source_sequence(self.hass, self._seq_actions),
            "repeat_help": repeat_help,
        }
        for index in range(SOURCE_REPEAT_MAX):
            placeholders[f"item_{index}"] = ""
        for index, action in enumerate(self._seq_picked):
            placeholders[f"item_{index}"] = format_action_label(self.hass, action)
        return self._show_form(
            "source_seq_repeat",
            self._repeat_schema(),
            placeholders=placeholders,
        )

    async def async_step_source_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        sources = self._data[CONF_CUSTOM_SOURCES]
        if not sources:
            return await self.async_step_sources()
        if user_input is not None:
            if self._wants_back(user_input):
                return await self.async_step_sources()
            index = find_source_index(sources, user_input.get(ATTR_NAME, ""))
            if index is not None:
                del self._data[CONF_CUSTOM_SOURCES][index]
            return await self.async_step_sources()
        return self._show_form("source_delete", self._source_pick_schema())

    async def async_step_source_reorder(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._ensure_draft()
        sources = self._data[CONF_CUSTOM_SOURCES]
        if len(sources) < 2:
            return await self.async_step_sources()
        names = source_names(sources)
        if user_input is not None:
            if self._wants_back(user_input):
                return await self.async_step_sources()
            order = parse_button_ids(user_input.get(CONF_SOURCE_ORDER))
            by_name = {str(item[ATTR_NAME]): item for item in sources}
            rebuilt: list[dict[str, Any]] = []
            seen: set[str] = set()
            for name in order:
                if name in by_name and name not in seen:
                    rebuilt.append(by_name[name])
                    seen.add(name)
            for item in sources:
                name = str(item[ATTR_NAME])
                if name not in seen:
                    rebuilt.append(item)
            self._data[CONF_CUSTOM_SOURCES] = rebuilt
            return await self.async_step_sources()
        return self._show_form(
            "source_reorder",
            {
                vol.Required(
                    CONF_SOURCE_ORDER, default=names
                ): ordered_choice_selector(names),
            },
        )
