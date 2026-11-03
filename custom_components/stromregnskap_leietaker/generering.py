"""Generering av månedsoppgjør (automatisk i kjørevinduet og manuelt via tjeneste)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .calc import (
    STATUS_VENTER,
    beregn_oppgjor,
    forrige_periode,
    forrige_periode_id,
    periode_start_slutt,
    sjekk_rimelighet,
    velg_leilighet_kwh,
)
from .const import CONF_ENT_REGNSKAP, CONF_FORFALLSDAG
from .kilder import til_float
from .page import fmt_tall
from .varsler import ISSUE_MANGLER, ISSUE_VENTER

PERIODE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
KREVD_FRA_HUSET = ("kwh", "kraft", "nettleie", "norgespris", "sum", "snitt")


class ManglerData(ServiceValidationError):
    """Dataene som trengs for å lage oppgjøret er ikke tilgjengelige."""


def sammendrag(p: dict[str, Any]) -> str:
    return (
        f"{fmt_tall(p['leilighet_kwh'], 1)} kWh × {fmt_tall(p['snitt'], 4)} "
        f"= {fmt_tall(p['belop'], 2)} kr"
    )


class GenereringMixin:
    """Metoder for StromregnskapCoordinator. Forutsetter lager, kilder, varsler og cfg."""

    def _sjekk_periodeformat(self, periode_id: str) -> None:
        if not PERIODE_RE.match(periode_id):
            raise ServiceValidationError(
                f"Ugyldig periode «{periode_id}». Bruk formatet ÅÅÅÅ-MM, for eksempel 2026-11."
            )

    def _hent_periode(self, periode_id: str) -> dict[str, Any]:
        self._sjekk_periodeformat(periode_id)
        p = self.lager.finn(periode_id)
        if p is None:
            raise ServiceValidationError(f"Perioden {periode_id} finnes ikke.")
        return p

    async def async_generer_oppgjor(
        self,
        periode_id: str | None = None,
        *,
        tving: bool = False,
        send_epost: bool = True,
    ) -> dict[str, Any]:
        """Manuell generering (tjenesten generer_oppgjor)."""
        naa = dt_util.now()
        periode_id = periode_id or forrige_periode_id(naa.date())
        p = await self._generer(periode_id, tving=tving, send_epost=send_epost, naa=naa)
        self.async_set_updated_data(await self._publiser(naa))
        return p

    async def _generer(
        self, periode_id: str, *, tving: bool, send_epost: bool, naa: datetime
    ) -> dict[str, Any]:
        self._sjekk_periodeformat(periode_id)
        if self.lager.finn(periode_id):
            raise ServiceValidationError(
                f"Perioden {periode_id} finnes allerede. "
                "Slett den først hvis den skal lages på nytt."
            )
        maned = self.kilder.finn_maned(periode_id)
        if maned is None or any(til_float(maned.get(k)) is None for k in KREVD_FRA_HUSET):
            raise ManglerData(
                f"{self.cfg[CONF_ENT_REGNSKAP]} har ikke komplette tall for {periode_id}."
            )
        # last_period gjelder bare måneden før den løpende
        last_period = (
            self.kilder.last_period() if periode_id == forrige_periode_id(naa.date()) else None
        )
        maaler = self._maaler_forbruk(periode_id)
        valg = velg_leilighet_kwh(
            til_float(maned.get("leilighet_kwh")), last_period, maaler=maaler.kwh
        )
        if valg.kwh is None:
            raise ManglerData(f"Leilighetens kWh for {periode_id} er ikke tilgjengelig.")

        p = beregn_oppgjor(
            periode_id=periode_id,
            maned=maned,
            leilighet_kwh=valg.kwh,
            forfallsdag=int(self.cfg[CONF_FORFALLSDAG]),
            naa=naa,
            kilde=valg.kilde,
        )
        brudd: list[str] = []
        if not tving:
            if maaler.feil:
                brudd.append(maaler.feil)
            elif maaler.kwh is None:
                start, slutt = periode_start_slutt(periode_id)
                brudd.append(
                    f"Målerstand mangler ved {start:%d.%m.%Y} eller {slutt:%d.%m.%Y}. "
                    "kWh er hentet fra regnskapssensoren og må kontrolleres."
                )
            if valg.avvik:
                brudd.append(valg.avvik)
            forrige = forrige_periode(self.lager.perioder, periode_id)
            brudd += sjekk_rimelighet(
                leilighet_kwh=p["leilighet_kwh"],
                hus_kwh=p["hus_kwh"],
                snitt=p["snitt"],
                forrige_kwh=forrige["leilighet_kwh"] if forrige else None,
                grenser=self.grenser,
            )

        self.varsler.fjern_issue(ISSUE_MANGLER, periode_id)
        if brudd:
            p["status"] = STATUS_VENTER
            p["notat"] = " | ".join(brudd)
            self.lager.legg_til(p)
            await self.lager.async_lagre()
            self.varsler.synk_ventende()
            await self.varsler.varsle_en_gang(
                f"{ISSUE_VENTER}:{periode_id}",
                "Strømoppgjør venter på godkjenning",
                f"Oppgjør {periode_id}: {sammendrag(p)}. Ikke sendt fordi: {p['notat']}",
            )
            return p

        p["epost_ventende_siden"] = naa.isoformat() if send_epost else None
        self.lager.legg_til(p)
        await self.lager.async_lagre()
        await self._skriv_side(naa)  # siden skal være oppdatert før leietaker får lenken
        if send_epost:
            await self._send_epost(p, naa)
        else:
            await self.varsler.varsle(
                "Strømoppgjør lagret",
                f"Oppgjør {periode_id} er lagret uten utsending: {sammendrag(p)}",
            )
        return p
