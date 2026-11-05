"""Generering av månedsoppgjør (automatisk i kjørevinduet og manuelt via tjeneste)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .calc import (
    STATUS_VENTER,
    avrund,
    beregn_oppgjor,
    er_kopi_av_forrige,
    forrige_maaned_id,
    forrige_periode,
    forrige_periode_id,
    leilighet_belop,
    periode_start_slutt,
    sjekk_rimelighet,
    velg_leilighet_kwh,
)
from .const import CONF_ENT_REGNSKAP, CONF_FORFALLSDAG
from .kilder import fullstendig, sperre, til_float
from .maaler import LADER
from .page import fmt_kwh, fmt_tall
from .varsler import ISSUE_MANGLER, ISSUE_VENTER

PERIODE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class ManglerData(ServiceValidationError):
    """Dataene som trengs for å lage oppgjøret er ikke tilgjengelige."""


def sammendrag(p: dict[str, Any]) -> str:
    tekst = (
        f"{fmt_kwh(p['leilighet_kwh'])} kWh × {fmt_tall(p['snitt'], 4)} "
        f"= {fmt_tall(leilighet_belop(p), 2)} kr"
    )
    if p.get("lader_kwh") is not None:
        tekst += (
            f" + lader {fmt_kwh(p['lader_kwh'])} kWh = {fmt_tall(p['lader_belop'], 2)} kr "
            f"(totalt {fmt_tall(p['belop'], 2)} kr)"
        )
    return tekst


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
        self,
        periode_id: str,
        *,
        tving: bool,
        send_epost: bool,
        naa: datetime,
        reserve_fra: datetime | None = None,
    ) -> dict[str, Any]:
        """Lager oppgjøret. Øyeblikksbildet brukes som reserve først fra `reserve_fra` (ingen
        grense hvis None), slik at den automatiske kjøringen gir kilden tid til å rette seg."""
        self._sjekk_periodeformat(periode_id)
        if self.lager.finn(periode_id):
            raise ServiceValidationError(
                f"Perioden {periode_id} finnes allerede. "
                "Slett den først hvis den skal lages på nytt."
            )
        maned = self.kilder.finn_maned(periode_id)
        fra_bilde: str | None = None
        if sperret := sperre(maned):
            # Ikke tving, ikke øyeblikksbilde: et bilde fra før grensen ble passert ser plausibelt
            # ut, men er delvis og feil. Tallene må inn i regnskapssensoren (manuell overstyring).
            raise ManglerData(
                f"Regnskapssensoren {self.cfg[CONF_ENT_REGNSKAP]} har sperret {periode_id}: "
                f"{sperret}. Oppgjøret lages ikke, og øyeblikksbildet brukes ikke, fordi tallene "
                "ikke er til å stole på. Legg inn fakturaens tall i regnskapssensoren "
                "(manuell overstyring), så lages oppgjøret ved neste timekjøring."
            )
        forrige_id = forrige_maaned_id(periode_id)
        if (
            not tving
            and fullstendig(maned)
            and er_kopi_av_forrige(maned, self.lager.finn(forrige_id))
        ):
            # Ikke lagre noe: neste timekjøring prøver igjen, og er kilden fortsatt feil når
            # vinduet er over, får utleier varsel om at data mangler.
            raise ManglerData(
                f"Husets tall for {periode_id} i {self.cfg[CONF_ENT_REGNSKAP]} er identiske med "
                f"{forrige_id} (samme kWh og sum). Kilden har trolig ikke rullet over til den nye "
                "måneden ennå. Oppgjøret lages ikke før tallene er endret."
            )
        if not fullstendig(maned):
            bilde = self.lager.data["snapshots"].get(periode_id)
            if bilde and fullstendig(bilde.get("maned")):
                if reserve_fra is not None and naa < reserve_fra:
                    # Ikke lagre noe: kilden kan rulle over, og neste timekjøring prøver igjen.
                    raise ManglerData(
                        f"{self.cfg[CONF_ENT_REGNSKAP]} har ikke komplette tall for {periode_id} "
                        "ennå. Reservetallene fra øyeblikksbildet brukes først fra "
                        f"{reserve_fra:%d.%m.%Y kl. %H:%M}."
                    )
                maned, fra_bilde = bilde["maned"], bilde["tid"]
            else:
                raise ManglerData(
                    f"{self.cfg[CONF_ENT_REGNSKAP]} har ikke komplette tall for {periode_id}."
                )
        # last_period gjelder bare måneden før den løpende
        last_period = (
            self.kilder.last_period() if periode_id == forrige_periode_id(naa.date()) else None
        )
        maaler = self._maaler_forbruk(periode_id)
        lader = self._lader_forbruk(periode_id) if self.lader_aktiv else None
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
            kilde=valg.kilde
            + (" + laderstander" if lader is not None and lader.kwh is not None else "")
            + (" + snapshot" if fra_bilde else ""),
            lader_kwh=lader.kwh if lader is not None else None,
        )
        if maaler.kwh is not None:
            start, slutt = periode_start_slutt(periode_id)
            p["maaler_start"] = avrund(self._lagret_stand(start), 1)
            p["maaler_slutt"] = avrund(self._lagret_stand(slutt), 1)
        if lader is not None and lader.kwh is not None:
            start, slutt = periode_start_slutt(periode_id)
            p["lader_start"] = avrund(self._lagret_stand(start, LADER), 1)
            p["lader_slutt"] = avrund(self._lagret_stand(slutt, LADER), 1)
        brudd: list[str] = []
        if not tving:
            if fra_bilde:
                brudd.append(
                    f"Husets tall for {periode_id} mangler i regnskapssensoren og er hentet fra et "
                    f"øyeblikksbilde tatt {fra_bilde[:16].replace('T', ' ')}. "
                    "Kontroller mot fakturaen før godkjenning."
                )
            if maaler.feil:
                brudd.append(maaler.feil)
            elif maaler.kwh is None:
                start, slutt = periode_start_slutt(periode_id)
                brudd.append(
                    f"Målerstand mangler ved {start:%d.%m.%Y} eller {slutt:%d.%m.%Y}. "
                    "kWh er hentet fra regnskapssensoren og må kontrolleres."
                )
            if lader is not None:
                if lader.feil:
                    brudd.append(lader.feil + " Beløpet er regnet uten lader.")
                elif lader.kwh is None:
                    start, slutt = periode_start_slutt(periode_id)
                    brudd.append(
                        f"Laderens teller mangler ved {start:%d.%m.%Y} eller {slutt:%d.%m.%Y}. "
                        "Beløpet er regnet uten lader. Legg inn telleren med handlingen «Sett "
                        "målerstand», slett perioden og lag den på nytt."
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
                ekstra_kwh=p.get("lader_kwh") or 0.0,
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
