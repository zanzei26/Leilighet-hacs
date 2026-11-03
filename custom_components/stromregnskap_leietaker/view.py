"""Uautentisert rute for leietakersiden.

Selve filen skrives til /config/www/<slug>/index.html. Fordi Home Assistants egen
/local-rute bare finnes hvis www-mappen fantes ved oppstart, og leverer filer med
«Cache-Control: public, max-age=2678400» (31 dager), registrerer vi en rute på
nøyaktig samme URL. Den er mer spesifikk enn /local og vinner derfor, og leverer
siden med «no-store» slik at leietaker alltid ser ferske tall.
"""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN


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
        sti = self.hass.data.get(DOMAIN, {}).get("aktive_slugs", {}).get(self.slug)
        innhold = await self.hass.async_add_executor_job(_les, sti) if sti else None
        if innhold is None:
            return web.Response(status=404)
        return web.Response(
            body=innhold,
            content_type="text/html",
            charset="utf-8",
            headers={
                "Cache-Control": "no-store",
                "X-Robots-Tag": "noindex, nofollow",
            },
        )
