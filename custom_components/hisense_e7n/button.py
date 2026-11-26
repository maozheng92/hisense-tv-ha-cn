"""爱家 remoter keys are not Home Assistant button entities.

They stay callable from custom-source macros, ``remote.send_command``, and
``hisense_e7n.send_key``. Older installs that created hidden ``button.*`` rows
are cleaned up when the integration loads.
"""

from __future__ import annotations

from .button_visibility import async_remove_legacy_button_entities

__all__ = ["async_remove_legacy_button_entities"]
