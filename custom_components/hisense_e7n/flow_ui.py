"""Load a small script that adds Back/Submit footer buttons on options dialogs.

Home Assistant option forms only expose Cancel + Submit. TCL's options UI
injects a real Back control (`extra_js_url` + static `www/`) so the footer is
Back on the left and Submit on the right. Hidden menu rows remain as a
fallback if the script does not run.
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_DATA_KEY = f"{DOMAIN}_flow_ui"
_WWW = Path(__file__).resolve().parent / "www"
_URL_BASE = f"/{DOMAIN}"
_JS_NAME = "hisense_e7n_flow.js"


def _version() -> str:
    manifest = Path(__file__).resolve().parent / "manifest.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "0"
    version = data.get("version")
    return str(version) if version else "0"


async def async_setup_flow_ui(hass: HomeAssistant) -> None:
    """Serve and inject the options-dialog footer script once per HA instance."""
    if hass.data.get(_DATA_KEY):
        return
    hass.data[_DATA_KEY] = True

    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(_URL_BASE, str(_WWW), False)]
        )
    except RuntimeError:
        pass
    url = f"{_URL_BASE}/{_JS_NAME}?v={_version()}"
    # Module (default) plus classic script: Companion WebView is more reliable
    # with extra_js_url_es5, and a window guard prevents double-install.
    add_extra_js_url(hass, url)
    add_extra_js_url(hass, url, es5=True)
