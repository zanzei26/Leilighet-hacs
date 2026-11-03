"""PDF-nedlasting bak den hemmelige lenken. Krever ikke innlogging, som leietakersiden."""

from __future__ import annotations

import re

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .pdf_dokumenter import REGNSKAPSNAVN

FAKTURA_RE = re.compile(r"^fakturagrunnlag-strom-leilighet-(\d{4}-(?:0[1-9]|1[0-2]))\.pdf$")


class LeietakerPdfView(HomeAssistantView):
    """GET /stromregnskap/<slug>/<regnskap- eller fakturagrunnlag-fil>.pdf uten innlogging."""

    requires_auth = False
    cors_allowed = False
    url = "/stromregnskap/{slug}/{fil}"
    name = f"{DOMAIN}:pdf"

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request, slug: str, fil: str) -> web.Response:
        koordinator = self.hass.data.get(DOMAIN, {}).get("koordinatorer", {}).get(slug)
        if koordinator is None:
            return web.Response(status=404)
        naa = dt_util.now()
        if fil == REGNSKAPSNAVN:
            data = await koordinator.async_regnskap_pdf(naa)
        elif (m := FAKTURA_RE.match(fil)) is not None:
            data = await koordinator.async_faktura_pdf(m.group(1), naa)
        else:
            data = None
        if data is None:
            return web.Response(status=404)
        return web.Response(
            body=data,
            content_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{fil}"',
                "Cache-Control": "no-store",
                "X-Robots-Tag": "noindex, nofollow",
            },
        )
