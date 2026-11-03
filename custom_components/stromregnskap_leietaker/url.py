"""Leietakers faste lenke."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url


def cloud_url(hass: HomeAssistant) -> str | None:
    """Nabu Casa remote UI-adresse, eller None hvis den ikke er tilgjengelig."""
    try:
        from homeassistant.components.cloud import async_remote_ui_url  # noqa: PLC0415

        return async_remote_ui_url(hass)
    except Exception:  # noqa: BLE001 - cloud ikke innlogget, avslått eller ikke importerbar
        return None


def bygg_side_url(hass: HomeAssistant, slug: str) -> str | None:
    """Nabu Casa først, ellers ekstern/intern URL. None hvis HA ikke kjenner noen adresse."""
    base = cloud_url(hass)
    if not base:
        try:
            base = get_url(hass, allow_cloud=False, prefer_external=True)
        except NoURLAvailableError:
            return None
    return f"{base.rstrip('/')}/local/{slug}/index.html"
