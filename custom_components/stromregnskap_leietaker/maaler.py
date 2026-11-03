"""Målerstander ved månedsskiftene.

Måleren teller opp og glemmer aldri. Forbruket i en måned er derfor målerstanden ved slutten
minus målerstanden ved starten, slik man regnet før. Integrasjonen lagrer målerstanden ved
hvert månedsskifte i egen historikk. Mangler en avlesning (for eksempel fordi Home Assistant var
nede ved midnatt), hentes den fra Home Assistants langtidsstatistikk, eller legges inn manuelt.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .calc import MaalerForbruk, maaler_forbruk, periode_start_slutt
from .const import (
    CONF_ENT_IMPORT,
    CONF_ENT_LADER,
    CONF_LADER_AKTIV,
    CONF_MAALER_START_STAND,
    DEFAULT_MAALER_START_STAND,
)

_LOGGER = logging.getLogger(__name__)

LIVE_VINDU = timedelta(hours=2)  # så lenge etter midnatt vi stoler på dagens måleravlesning
LIVE_PRESIS = timedelta(minutes=5)
DATO_RE = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$")

# Målerserier: nøkkelen i lagringen og nøkkelen i oppsettet for sensoren som leses.
LEILIGHET = "maalerstander"
LADER = "laderstander"
SERIE_ENTITET = {LEILIGHET: CONF_ENT_IMPORT, LADER: CONF_ENT_LADER}
MAALER_TIL_SERIE = {"leilighet": LEILIGHET, "lader": LADER}


def stand_fra_rader(rader: list[dict[str, Any]], grense_ts: float) -> float | None:
    """Målerstand ved ``grense_ts`` fra timesstatistikk: raden som slutter akkurat da."""
    for rad in rader:
        slutt = rad["end"]
        slutt = slutt.timestamp() if isinstance(slutt, datetime) else float(slutt)
        if abs(slutt - grense_ts) < 1 and rad.get("state") is not None:
            return float(rad["state"])
    return None


def tolk_maanedsstart(tekst: str) -> date:
    """«2026-12» eller «2026-12-01» til første dag i måneden. Ellers ServiceValidationError."""
    m = DATO_RE.match(tekst.strip())
    try:
        if m is None:
            raise ValueError
        aar, mnd, dag = int(m.group(1)), int(m.group(2)), int(m.group(3) or 1)
        if dag != 1:
            raise ValueError
        return date(aar, mnd, 1)
    except ValueError:
        raise ServiceValidationError(
            f"Ugyldig dato «{tekst}». Bruk første dag i en måned, "
            "for eksempel 2026-12-01 eller 2026-12."
        ) from None


class MaalerMixin:
    """Metoder for StromregnskapCoordinator.

    Leilighetens måler (``maalerstander``) er alltid med. Laderens teller (``laderstander``) er
    med bare når laderen er slått på i oppsettet. Begge følger samme regler.
    """

    @property
    def lader_aktiv(self) -> bool:
        c = self.cfg
        return bool(c.get(CONF_LADER_AKTIV) and c.get(CONF_ENT_LADER))

    def _serier(self) -> list[str]:
        return [LEILIGHET, LADER] if self.lader_aktiv else [LEILIGHET]

    def _lagret_stand(self, dato: date, serie: str = LEILIGHET) -> float | None:
        rad = self.lager.data[serie].get(dato.isoformat())
        return None if rad is None else float(rad["stand"])

    def _maaler_forbruk(self, periode_id: str) -> MaalerForbruk:
        start, slutt = periode_start_slutt(periode_id)
        return maaler_forbruk(self._lagret_stand(start), self._lagret_stand(slutt))

    def _lader_forbruk(self, periode_id: str) -> MaalerForbruk:
        start, slutt = periode_start_slutt(periode_id)
        return maaler_forbruk(
            self._lagret_stand(start, LADER),
            self._lagret_stand(slutt, LADER),
            stand="Laderens teller",
            enhet="Laderen",
        )

    async def _lagre_stand(
        self,
        dato: date,
        stand: float,
        kilde: str,
        naa: datetime | None = None,
        serie: str = LEILIGHET,
    ) -> None:
        self.lager.data[serie][dato.isoformat()] = {
            "stand": round(float(stand), 3),
            "kilde": kilde,
            "tid": (naa or dt_util.now()).isoformat(),
        }
        await self.lager.async_lagre()

    async def async_fang_maalerstand(self, naa: datetime) -> None:
        """Sørger for at målerstandene ved starten av inneværende måned er lagret.

        Rett etter midnatt brukes dagens avlesning. Senere hentes den fra statistikken.
        En lagret avlesning overskrives aldri her (bare manuelt). Feiler én måler, prøves
        likevel den andre.
        """
        for serie in self._serier():
            try:
                await self._fang_serie(serie, naa)
            except Exception:  # noqa: BLE001 - laderen skal ikke stoppe leilighetens måler
                _LOGGER.exception("Kunne ikke sikre målerstand for %s", serie)

    async def _fang_serie(self, serie: str, naa: datetime) -> None:
        dato = naa.date().replace(day=1)
        if self._lagret_stand(dato, serie) is not None:
            return
        entitet = self.cfg[SERIE_ENTITET[serie]]
        grense = dt_util.start_of_local_day(dato)
        alder = naa - grense
        if alder <= LIVE_VINDU:
            live = self.kilder.float_tilstand(entitet)
            if live is not None:
                await self._lagre_stand(
                    dato, live, "live" if alder <= LIVE_PRESIS else "live_sen", naa, serie
                )
                return
        stand = await self._stand_fra_statistikk(grense, entitet)
        if stand is not None:
            await self._lagre_stand(dato, stand, "statistikk", naa, serie)

    async def _stand_fra_statistikk(
        self, grense: datetime, entitet: str | None = None
    ) -> float | None:
        """Målerstand ved ``grense`` fra Home Assistants timesstatistikk (best effort)."""
        if "recorder" not in self.hass.config.components:
            return None
        entitet = entitet or self.cfg[CONF_ENT_IMPORT]
        try:
            from homeassistant.components.recorder import get_instance  # noqa: PLC0415
            from homeassistant.components.recorder.statistics import (  # noqa: PLC0415
                statistics_during_period,
            )

            resultat = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                dt_util.as_utc(grense - timedelta(hours=1)),
                dt_util.as_utc(grense + timedelta(minutes=1)),
                {entitet},
                "hour",
                None,
                {"state"},
            )
        except Exception:  # noqa: BLE001 - statistikk er en reserve, aldri en feilkilde
            _LOGGER.debug("Kunne ikke hente statistikk for %s", entitet, exc_info=True)
            return None
        return stand_fra_rader(resultat.get(entitet, []), grense.timestamp())

    async def async_seed_maaler(self) -> None:
        """Første gang: lagre målerstandene ved starten av inneværende måned."""
        naa = dt_util.now()
        if not self.lager.data[LEILIGHET]:
            dato = naa.date().replace(day=1)
            stand = await self._stand_fra_statistikk(dt_util.start_of_local_day(dato))
            kilde = "statistikk"
            if stand is None:
                stand = float(self.cfg.get(CONF_MAALER_START_STAND, DEFAULT_MAALER_START_STAND))
                kilde = "start"
            await self._lagre_stand(dato, stand, kilde, naa)
        if self.lader_aktiv:
            # Laderens teller har ingen fornuftig startverdi å falle tilbake på: uten statistikk
            # eller en avlesning rett etter midnatt må den legges inn manuelt (se datagrunnlaget).
            await self._fang_serie(LADER, naa)

    async def async_sett_malerstand(
        self, dato_tekst: str, stand: float, maaler: str = "leilighet"
    ) -> None:
        """Legger inn (eller retter) målerstanden ved et månedsskifte manuelt."""
        serie = MAALER_TIL_SERIE.get(maaler)
        if serie is None:
            raise ServiceValidationError(
                f"Ukjent måler «{maaler}». Bruk «leilighet» eller «lader»."
            )
        if serie == LADER and not self.lader_aktiv:
            raise ServiceValidationError("Laderen er ikke slått på i oppsettet.")
        dato = tolk_maanedsstart(dato_tekst)
        if stand < 0:
            raise ServiceValidationError("Målerstanden kan ikke være negativ.")
        await self._lagre_stand(dato, stand, "manuell", serie=serie)
        self.async_set_updated_data(await self._publiser(dt_util.now()))
