"""Koordinator: oppdateres hver time, lager oppgjør i kjørevinduet og holder siden à jour.

Selve logikken er delt i moduler: generering.py, epost.py og handlinger.py (mixins),
varsler.py (varsler og issues), kilder.py (sensoravlesing) og filer.py/url.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .calc import (
    Grenser,
    auto_status,
    avrund,
    beregn_belop,
    forrige_periode_id,
    maaler_forbruk,
    velg_estimat,
)
from .const import (
    CONF_ADRESSE,
    CONF_ENDRING_MAKS,
    CONF_ENT_IMPORT,
    CONF_ENT_LADER,
    CONF_ENT_REGNSKAP,
    CONF_FORFALLSDAG,
    CONF_INNFLYTTET,
    CONF_KJOREDAG,
    CONF_KJORETID,
    CONF_KONTONUMMER,
    CONF_LEIETAKER_EPOST,
    CONF_LEIETAKER_NAVN,
    CONF_PUBLISER_SIDE,
    CONF_SISTE_SJEKKDAG,
    CONF_SLUG,
    CONF_SNITT_MAKS,
    CONF_SNITT_MIN,
    CONF_UTLEIER_EPOST,
    CONF_UTLEIER_NAVN,
    CONF_UTLEIER_TELEFON,
    DOMAIN,
    OPPDATERINGSINTERVALL_TIMER,
)
from .datagrunnlag import DatagrunnlagMixin
from .eksport import EksportMixin
from .epost import EpostMixin
from .filer import skriv_atomisk
from .filnavn import REGNSKAPSNAVN, fakturanavn
from .generering import GenereringMixin, ManglerData
from .handlinger import HandlingerMixin
from .kilder import Kilder, bygg_data
from .live import LiveMixin
from .maaler import LADER, MaalerMixin
from .page import render_side
from .snapshot import SnapshotMixin
from .storage import Lager
from .url import bygg_pdf_url, bygg_side_url
from .varsler import ISSUE_ETTERSLEP, ISSUE_MANGLER, Varsler

_LOGGER = logging.getLogger(__name__)


class StromregnskapCoordinator(
    GenereringMixin,
    EpostMixin,
    EksportMixin,
    HandlingerMixin,
    MaalerMixin,
    SnapshotMixin,
    DatagrunnlagMixin,
    LiveMixin,
    DataUpdateCoordinator[dict[str, Any]],
):
    """Oppdateres hver time. Lager oppgjør i kjørevinduet og holder siden à jour."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, lager: Lager) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(hours=OPPDATERINGSINTERVALL_TIMER),
        )
        self.entry = entry
        self.lager = lager
        self.kilder = Kilder(hass, lambda: self.cfg)
        self.varsler = Varsler(hass, entry.entry_id, lager, lambda: self.cfg)
        self._side_publisert: datetime | None = None
        self._forsokt_na: set[str] = set()  # perioder det er sendt e-post for i denne kjøringen

    # ------------------------------------------------------------------ oppsett

    @property
    def cfg(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    @property
    def grenser(self) -> Grenser:
        c = self.cfg
        return Grenser(
            snitt_min=float(c[CONF_SNITT_MIN]),
            snitt_maks=float(c[CONF_SNITT_MAKS]),
            endring_maks_prosent=float(c[CONF_ENDRING_MAKS]),
        )

    @property
    def leietaker(self) -> dict[str, Any]:
        c = self.cfg
        return {
            "navn": c[CONF_LEIETAKER_NAVN],
            "epost": c[CONF_LEIETAKER_EPOST],
            "adresse": c[CONF_ADRESSE],
            "innflyttet": c.get(CONF_INNFLYTTET),
        }

    @property
    def utleier(self) -> dict[str, Any]:
        c = self.cfg
        return {
            "navn": c[CONF_UTLEIER_NAVN],
            "epost": c[CONF_UTLEIER_EPOST],
            "kontonummer": c[CONF_KONTONUMMER],
            "telefon": c.get(CONF_UTLEIER_TELEFON) or "",
        }

    @property
    def side_url(self) -> str | None:
        """Leietakers faste lenke (Nabu Casa først, ellers ekstern/intern URL).

        None hvis siden ikke publiseres eller HA ikke kjenner noen adresse.
        """
        if not self.cfg.get(CONF_PUBLISER_SIDE):
            return None
        return bygg_side_url(self.hass, self.cfg[CONF_SLUG])

    @property
    def side_sti(self) -> str:
        return self.hass.config.path("www", self.cfg[CONF_SLUG], "index.html")

    # ------------------------------------------------------------------ oppdatering

    async def _async_update_data(self) -> dict[str, Any]:
        naa = dt_util.now()
        self._forsokt_na.clear()
        try:
            await self.async_fang_maalerstand(naa)
        except Exception:  # noqa: BLE001 - skal ikke stoppe resten
            _LOGGER.exception("Kunne ikke sikre målerstand for måneden")
        try:
            await self._ta_bilde(naa)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Kunne ikke ta øyeblikksbilde av kildetallene")
        await self._oppdater_status(naa)
        try:
            await self._prov_automatisk(naa)
        except Exception:  # noqa: BLE001 - en feil her skal ikke stoppe siden og sensorene
            _LOGGER.exception("Automatisk oppgjør feilet uventet")
        self.varsler.synk_ventende()
        try:
            await self._send_ventende(naa)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Sending av ventende e-post feilet uventet")
        try:
            await self._varsle_datagrunnlag(naa)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Kunne ikke vurdere datagrunnlaget")
        return await self._publiser(naa)

    async def _oppdater_status(self, naa: datetime) -> None:
        endret = False
        for p in self.lager.perioder:
            ny = auto_status(p, naa.date())
            if ny != p["status"]:
                p["status"] = ny
                endret = True
        if endret:
            await self.lager.async_lagre()

    def _kjorevindu(self, naa: datetime) -> tuple[datetime, datetime, datetime]:
        """(start, slutt, tidspunkt for «mangler data»-varsel) i inneværende måned."""
        c = self.cfg
        kt = time.fromisoformat(c[CONF_KJORETID])
        start = naa.replace(
            day=int(c[CONF_KJOREDAG]), hour=kt.hour, minute=kt.minute, second=0, microsecond=0
        )
        siste = int(c[CONF_SISTE_SJEKKDAG])
        slutt = naa.replace(day=siste, hour=23, minute=59, second=59, microsecond=999999)
        varsel = naa.replace(day=siste, hour=kt.hour, minute=kt.minute, second=0, microsecond=0)
        return start, slutt, varsel

    async def _prov_automatisk(self, naa: datetime) -> None:
        periode_id = forrige_periode_id(naa.date())
        if self.lager.finn(periode_id):
            self.varsler.fjern_issue(ISSUE_ETTERSLEP, periode_id)
            return
        start, slutt, varsel_tid = self._kjorevindu(naa)
        if naa > slutt:
            await self._varsle_etterslep(periode_id, naa)
            return
        if naa < start:
            return
        try:
            # Øyeblikksbildet er siste utvei: vent til varseltidspunktet på siste sjekkdag, så
            # malen/Amperium får hele vinduet til å rulle over og oppgjøret blir et vanlig ett.
            await self._generer(
                periode_id, tving=False, send_epost=True, naa=naa, reserve_fra=varsel_tid
            )
        except ManglerData as err:
            _LOGGER.debug("Oppgjør for %s ikke klart: %s", periode_id, err)
            if naa >= varsel_tid:
                self.varsler.opprett_issue(
                    ISSUE_MANGLER,
                    periode_id,
                    fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    placeholders={"entitet": self.cfg[CONF_ENT_REGNSKAP]},
                )
                await self.varsler.varsle_en_gang(
                    f"{ISSUE_MANGLER}:{periode_id}",
                    "Strømoppgjør mangler data",
                    f"Oppgjør for {periode_id} kunne ikke lages – "
                    f"mangler data i {self.cfg[CONF_ENT_REGNSKAP]}. {err}",
                )

    # ------------------------------------------------------------------ data og side

    def _bygg_data(self, naa: datetime) -> dict[str, Any]:
        data = bygg_data(
            self.kilder, self.cfg, self.lager.perioder, naa, self.side_url, self._side_publisert
        )
        mnd = f"{naa.year}-{naa.month:02d}"
        avlesninger = sorted(self.lager.data["maalerstander"].items())[-6:]
        slug = self.cfg[CONF_SLUG]
        publisert = bool(self.cfg.get(CONF_PUBLISER_SIDE))
        siste = data["siste"]
        data["regnskap_pdf_url"] = (
            bygg_pdf_url(self.hass, slug, REGNSKAPSNAVN) if publisert else None
        )
        data["siste_faktura_pdf_url"] = (
            bygg_pdf_url(self.hass, slug, fakturanavn(siste["id"])) if publisert and siste else None
        )
        # «hittil» regnes som oppgjøret: målerstand nå minus målerstand ved månedsskiftet
        maaler = maaler_forbruk(
            self._lagret_stand(naa.date().replace(day=1)),
            self.kilder.float_tilstand(self.cfg[CONF_ENT_IMPORT]),
        )
        if maaler.kwh is not None:
            data["kwh_hittil"] = maaler.kwh
            if data["snitt_hittil"] is not None:
                data["kostnad_hittil"] = beregn_belop(maaler.kwh, data["snitt_hittil"])
            data["hittil_kilde"] = "maaler"
        else:
            data["hittil_kilde"] = "utility_meter"  # reserve: utility_meter og regnskapssensoren
        self._legg_til_lader_hittil(data, naa)
        self._sett_estimat(data, naa)
        data["datagrunnlag"] = self.vurder_datagrunnlag(naa)
        data["siste_bilde"] = (self.lager.data["snapshots"].get(mnd) or {}).get("tid")
        data["siste_sikkerhetskopi"] = self.lager.siste_kopi
        data["kopimappe"] = self.lager.kopimappe
        data["maalerstander"] = {dato: rad["stand"] for dato, rad in avlesninger}
        return data

    def _legg_til_lader_hittil(self, data: dict[str, Any], naa: datetime) -> None:
        """Laderen (valgfri) regnes som oppgjøret: telleren nå minus telleren ved månedsskiftet.

        ``kwh_hittil`` og ``kostnad_hittil`` er det leietaker skylder så langt, altså leilighet
        pluss lader. Delene ligger i egne felt.
        """
        data["leilighet_kwh_hittil"] = data["kwh_hittil"]
        data["lader_kwh_hittil"] = None
        data["lader_kostnad_hittil"] = None
        if not self.lader_aktiv:
            return
        lader = maaler_forbruk(
            self._lagret_stand(naa.date().replace(day=1), LADER),
            self.kilder.float_tilstand(self.cfg[CONF_ENT_LADER]),
            stand="Laderens teller",
            enhet="Laderen",
        )
        if lader.kwh is None:
            return
        data["lader_kwh_hittil"] = lader.kwh
        if data["kwh_hittil"] is not None:
            data["kwh_hittil"] = avrund(data["kwh_hittil"] + lader.kwh, 1)
        if data["snitt_hittil"] is not None:
            kr = beregn_belop(lader.kwh, data["snitt_hittil"])
            data["lader_kostnad_hittil"] = kr
            if data["kostnad_hittil"] is not None:
                data["kostnad_hittil"] = avrund(data["kostnad_hittil"] + kr, 2)

    def _sett_estimat(self, data: dict[str, Any], naa: datetime) -> None:
        """Månedsanslaget (bare visning): leilighetens egen takt når måleren har gitt «hittil».

        Takten bygger på ``kwh_hittil`` (leilighet pluss lader), men bare når forbruket kommer
        fra måleren (målerstand ved månedsskiftet finnes) og laderen, hvis den er på, også har en
        stand. Ellers brukes forrige periode × husets endring, som ``bygg_data`` alt har regnet.
        """
        if data.get("hittil_kilde") != "maaler":
            return
        if self.lader_aktiv and data["lader_kwh_hittil"] is None:
            return
        kwh, kr, metode = velg_estimat(
            naa,
            data["kwh_hittil"],
            data["forrige_kwh"],
            data["forrige_snitt"],
            data["endring_prosent"],
        )
        data["estimat_kwh"], data["estimat_kr"], data["estimat_metode"] = kwh, kr, metode

    def _side_ctx(self, naa: datetime, data: dict[str, Any]) -> dict[str, Any]:
        hittil = None
        if data["kwh_hittil"] is not None or data["snitt_hittil"] is not None:
            hittil = {
                "kwh": data["kwh_hittil"],
                "snitt": data["snitt_hittil"],
                "kr": data["kostnad_hittil"],
                "lader_kwh": data["lader_kwh_hittil"],
                "lader_kr": data["lader_kostnad_hittil"],
            }
        estimat = None
        if data["estimat_kwh"] is not None:
            estimat = {"kwh": data["estimat_kwh"], "kr": data["estimat_kr"]}
        return {
            "leietaker": self.leietaker,
            "utleier": self.utleier,
            "forfallsdag": int(self.cfg[CONF_FORFALLSDAG]),
            "perioder": data["perioder"],
            "hittil": hittil,
            "estimat": estimat,
            "oppdatert": naa,
            "pdf_base": f"/stromregnskap/{self.cfg[CONF_SLUG]}",
        }

    def bygg_side_html(self, naa: datetime) -> str:
        """Leietakersiden med tall som er ferske akkurat nå (brukes for hver forespørsel)."""
        return render_side(self._side_ctx(naa, self._bygg_data(naa)))

    async def _skriv_side(self, naa: datetime, data: dict[str, Any] | None = None) -> None:
        """Skriver siden til www/ (reserve for /local, og siste kjente tilstand)."""
        if not self.cfg.get(CONF_PUBLISER_SIDE):
            return
        data = data or self._bygg_data(naa)
        html = render_side(self._side_ctx(naa, data))
        await self.hass.async_add_executor_job(skriv_atomisk, self.side_sti, html)
        self._side_publisert = naa

    async def _publiser(self, naa: datetime) -> dict[str, Any]:
        data = self._bygg_data(naa)
        await self._skriv_side(naa, data)
        data["side_sist_publisert"] = self._side_publisert
        return data
