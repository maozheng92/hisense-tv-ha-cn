"""Install and load the options-dialog footer script.

Home Assistant option forms only expose Cancel + Submit. This copies the
bundled JS into ``<config>/www/hisense_e7n/`` (HA serves that as ``/local/``)
and registers it with ``extra_js_url``. Hidden menu rows remain as a fallback
if the script does not run.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_DATA_KEY = f"{DOMAIN}_flow_ui"
_BUNDLE_WWW = Path(__file__).resolve().parent / "www"
_JS_NAME = "hisense_e7n_flow.js"
_LOCAL_URL = f"/local/{DOMAIN}/{_JS_NAME}"


def _version() -> str:
    manifest = Path(__file__).resolve().parent / "manifest.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "0"
    version = data.get("version")
    return str(version) if version else "0"


def install_flow_www(config_dir: str | Path) -> Path:
    """Copy bundled ``www/`` files into ``<config>/www/hisense_e7n/``."""
    dest_dir = Path(config_dir) / "www" / DOMAIN
    dest_dir.mkdir(parents=True, exist_ok=True)
    if not _BUNDLE_WWW.is_dir():
        raise FileNotFoundError(f"bundled www missing: {_BUNDLE_WWW}")
    for src in sorted(_BUNDLE_WWW.iterdir()):
        if not src.is_file():
            continue
        dest = dest_dir / src.name
        data = src.read_bytes()
        if dest.is_file() and dest.read_bytes() == data:
            continue
        dest.write_bytes(data)
        _LOGGER.info("Installed options footer script at %s", dest)
    return dest_dir


async def async_setup_flow_ui(hass: Any) -> None:
    """Copy the footer script into config/www and inject it once per HA instance."""
    if hass.data.get(_DATA_KEY):
        return
    hass.data[_DATA_KEY] = True

    from homeassistant.components.frontend import add_extra_js_url

    try:
        await hass.async_add_executor_job(install_flow_www, hass.config.config_dir)
    except OSError as err:
        _LOGGER.warning("Could not install %s into config/www: %s", _JS_NAME, err)
        return
    url = f"{_LOCAL_URL}?v={_version()}"
    # Module (default) plus classic script: Companion WebView is more reliable
    # with extra_js_url_es5, and a window guard prevents double-install.
    add_extra_js_url(hass, url)
    add_extra_js_url(hass, url, es5=True)
