"""Push-varsler til utleier (med deduplisering) og Repairs-issues."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir

from .const import CONF_VARSEL_TJENESTE, DOMAIN
from .page import maaned_tekst
from .storage import Lager

_LOGGER = logging.getLogger(__name__)

ISSUE_VENTER = "venter_godkjenning"
ISSUE_MANGLER = "mangler_data"
ISSUE_EPOST = "epost_feilet"
ISSUE_DATAGRUNNLAG = "datagrunnlag"
ISSUE_ETTERSLEP = "etterslep"
ISSUE_ARTER = (ISSUE_VENTER, ISSUE_MANGLER, ISSUE_EPOST, ISSUE_DATAGRUNNLAG, ISSUE_ETTERSLEP)


class Varsler:
    """Samler varsling og issues slik at resten av koden slipper å kjenne detaljene."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        lager: Lager,
        hent_cfg: Callable[[], dict[str, Any]],
    ) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._lager = lager
        self._cfg = hent_cfg

    async def varsle(self, tittel: str, melding: str) -> None:
        """Sender varsel. Feil logges, men stopper aldri oppgjøret."""
        tjeneste_navn = self._cfg()[CONF_VARSEL_TJENESTE]
        domene, _, tjeneste = tjeneste_navn.partition(".")
        try:
            await self._hass.services.async_call(
                domene, tjeneste, {"title": tittel, "message": melding}, blocking=True
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Kunne ikke sende varsel via %s: %s", tjeneste_navn, err)

    async def varsle_en_gang(self, nokkel: str, tittel: str, melding: str) -> None:
        """Som varsle, men bare første gang nøkkelen brukes (huskes i lagringen)."""
        if nokkel in self._lager.tilstand["varslet"]:
            return
        self._lager.tilstand["varslet"].append(nokkel)
        del self._lager.tilstand["varslet"][:-300]  # listen skal ikke vokse for alltid
        await self._lager.async_lagre()
        await self.varsle(tittel, melding)

    def opprett_issue(
        self,
        art: str,
        periode_id: str,
        *,
        fixable: bool,
        severity: ir.IssueSeverity,
        placeholders: dict[str, str] | None = None,
    ) -> None:
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            f"{art}_{periode_id}",
            is_fixable=fixable,
            severity=severity,
            translation_key=art,
            translation_placeholders={
                "periode": periode_id,
                "maned": maaned_tekst(periode_id),
                **(placeholders or {}),
            },
            data={"entry_id": self._entry_id, "periode": periode_id},
        )

    def fjern_issue(self, art: str, periode_id: str) -> None:
        ir.async_delete_issue(self._hass, DOMAIN, f"{art}_{periode_id}")

    def fjern_alle_issues(self, periode_id: str) -> None:
        for art in ISSUE_ARTER:
            self.fjern_issue(art, periode_id)

    def synk_ventende(self) -> None:
        """Sørger for at issues finnes for perioder som venter (også etter omstart)."""
        for p in self._lager.perioder:
            if p["status"] == "venter_godkjenning":
                self.opprett_issue(
                    ISSUE_VENTER,
                    p["id"],
                    fixable=True,
                    severity=ir.IssueSeverity.WARNING,
                    placeholders={"detaljer": p.get("notat", "")},
                )
