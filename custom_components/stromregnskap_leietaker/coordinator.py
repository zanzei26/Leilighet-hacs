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

from .calc import Grenser, auto_status, forrige_periode_id
from .const import (
    CONF_ADRESSE,
    CONF_ENDRING_MAKS,
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
    DOMAIN,
    OPPDATERINGSINTERVALL_TIMER,
)
from .epost import EpostMixin
from .filer import skriv_atomisk
from .generering import GenereringMixin, ManglerData
from .handlinger import HandlingerMixin
from .kilder import Kilder, bygg_data
from .maaler import MaalerMixin
from .page import render_side
from .snapshot import SnapshotMixin
from .storage import Lager
from .url import bygg_side_url
from .varsler import ISSUE_MANGLER, Varsler

_LOGGER = logging.getLogger(__name__)


class StromregnskapCoordinator(
    GenereringMixin,
    EpostMixin,
    HandlingerMixin,
    MaalerMixin,
    SnapshotMixin,
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
            return
        start, slutt, varsel_tid = self._kjorevindu(naa)
        if not start <= naa <= slutt:
            return
        try:
            await self._generer(periode_id, tving=False, send_epost=True, naa=naa)
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
        return bygg_data(
            self.kilder, self.cfg, self.lager.perioder, naa, self.side_url, self._side_publisert
        )

    async def _skriv_side(self, naa: datetime, data: dict[str, Any] | None = None) -> None:
        if not self.cfg.get(CONF_PUBLISER_SIDE):
            return
        data = data or self._bygg_data(naa)
        hittil = None
        if data["kwh_hittil"] is not None or data["snitt_hittil"] is not None:
            hittil = {
                "kwh": data["kwh_hittil"],
                "snitt": data["snitt_hittil"],
                "kr": data["kostnad_hittil"],
            }
        estimat = None
        if data["estimat_kwh"] is not None:
            estimat = {"kwh": data["estimat_kwh"], "kr": data["estimat_kr"]}
        html = render_side(
            {
                "leietaker": self.leietaker,
                "utleier": self.utleier,
                "forfallsdag": int(self.cfg[CONF_FORFALLSDAG]),
                "perioder": data["perioder"],
                "hittil": hittil,
                "estimat": estimat,
                "oppdatert": naa,
            }
        )
        await self.hass.async_add_executor_job(skriv_atomisk, self.side_sti, html)
        self._side_publisert = naa

    async def _publiser(self, naa: datetime) -> dict[str, Any]:
        data = self._bygg_data(naa)
        await self._skriv_side(naa, data)
        data["side_sist_publisert"] = self._side_publisert
        return data
