"""Uautentisert rute for leietakersiden.

Selve filen skrives til /config/www/<slug>/index.html. Fordi Home Assistants egen
/local-rute bare finnes hvis www-mappen fantes ved oppstart, og leverer filer med
«Cache-Control: public, max-age=2678400» (31 dager), registrerer vi en rute på
nøyaktig samme URL. Den er mer spesifikk enn /local og vinner derfor, og leverer
siden med «no-store» slik at leietaker alltid ser ferske tall.
"""

from __future__ import annotations

import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

HODER = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}


def _les(sti: str) -> bytes | None:
    try:
        with open(sti, "rb") as fil:
            return fil.read()
    except OSError:
        return None


class LeietakerSideView(HomeAssistantView):
    """GET /local/<slug>/index.html uten innlogging."""

    requires_auth = False
    cors_allowed = False

    def __init__(self, hass: HomeAssistant, slug: str) -> None:
        self.hass = hass
        self.slug = slug
        self.url = f"/local/{slug}/index.html"
        self.name = f"{DOMAIN}:side:{slug}"

    async def get(self, request: web.Request) -> web.Response:
        reg = self.hass.data.get(DOMAIN, {})
        koordinator = reg.get("koordinatorer", {}).get(self.slug)
        if koordinator is not None:
            try:
                html = koordinator.bygg_side_html(dt_util.now())
            except Exception:  # noqa: BLE001 - leietaker skal få siste lagrede side hvis byggingen feiler
                _LOGGER.exception("Kunne ikke bygge leietakersiden, bruker lagret fil")
            else:
                return web.Response(
                    text=html, content_type="text/html", charset="utf-8", headers=HODER
                )
        sti = reg.get("aktive_slugs", {}).get(self.slug)
        innhold = await self.hass.async_add_executor_job(_les, sti) if sti else None
        if innhold is None:
            return web.Response(status=404)
        return web.Response(body=innhold, content_type="text/html", charset="utf-8", headers=HODER)
