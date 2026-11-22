"""Hide remoter buttons in the entity registry without disabling them."""

from __future__ import annotations

from .const import DOMAIN


def should_hide_button_registry_entry(
    *,
    domain: str,
    platform: str,
    hidden_by: str | None,
) -> bool:
    """True when an existing button should be marked hidden by this integration.

    ``entity_registry_visible_default=False`` only affects *new* registry rows.
    Upgraded installs keep prior visibility unless we set ``hidden_by``.
    Leave rows already hidden (by user or integration) alone; never disable.
    """
    if domain != "button" or platform != DOMAIN:
        return False
    return hidden_by is None
