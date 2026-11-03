"""Bygging av PDF-er og JSON-sikkerhetskopi av dagens data.

Dataene kopieres i hendelsesløkken, og selve byggingen skjer i executor, slik at ingenting
leses mens det endres.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from typing import Any

from .calc import STATUS_VENTER
from .pdf_dokumenter import bygg_fakturagrunnlag, bygg_regnskap


class EksportMixin:
    """Metoder for StromregnskapCoordinator."""

    def synlige_perioder(self) -> list[dict[str, Any]]:
        """Perioder leietaker kan se: alt unntatt oppgjør som venter på godkjenning."""
        return [p for p in self.lager.perioder if p["status"] != STATUS_VENTER]

    def _kopi_av_data(self) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        return deepcopy(self.lager.perioder), dict(self.leietaker), dict(self.utleier)

    async def async_regnskap_pdf(self, naa: datetime) -> bytes:
        perioder, leietaker, utleier = self._kopi_av_data()
        return await self.hass.async_add_executor_job(
            bygg_regnskap, perioder, leietaker, utleier, naa
        )

    async def async_faktura_pdf(self, periode_id: str, naa: datetime) -> bytes | None:
        """PDF for én periode, eller None hvis den ikke finnes eller venter på godkjenning."""
        p = self.lager.finn(periode_id)
        if p is None or p["status"] == STATUS_VENTER:
            return None
        periode, leietaker, utleier = deepcopy(p), dict(self.leietaker), dict(self.utleier)
        return await self.hass.async_add_executor_job(
            bygg_fakturagrunnlag, periode, leietaker, utleier, naa
        )

    def sikkerhetsjson(self, naa: datetime) -> bytes:
        """All lagret data som JSON, samme form som sikkerhetskopiene."""
        return json.dumps(
            {"versjon": 1, "lagret": naa.isoformat(), "data": self.lager.data},
            ensure_ascii=False,
            indent=2,
            default=str,
        ).encode("utf-8")
