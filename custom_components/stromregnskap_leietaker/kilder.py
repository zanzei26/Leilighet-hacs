"""Avlesning av de eksterne sensorene og bygging av dataene sensorene og siden bruker."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant

from .calc import (
    STATUS_VENTER,
    UTESTAAENDE_STATUSER,
    forrige_periode,
    utestaaende,
    velg_estimat,
)
from .const import (
    CONF_ENT_EFFEKT,
    CONF_ENT_IMPORT,
    CONF_ENT_PROGNOSE,
    CONF_ENT_REGNSKAP,
    CONF_ENT_UTILITY,
)


def til_float(verdi: Any) -> float | None:
    try:
        return float(verdi)
    except (TypeError, ValueError):
        return None


KREVD_FRA_HUSET = ("kwh", "kraft", "nettleie", "norgespris", "sum", "snitt")


def sperre(maned: Any) -> str | None:
    """Forklaringen i feltet «sperre» på en månedsrad, hvis regnskapssensoren har sperret måneden.

    Sperret betyr at tallene ikke er til å stole på (for eksempel over 5 000 kWh, der
    Norgespris-modellen ikke gjelder). Tomt felt (None, tom tekst, False) betyr ingen sperre.
    Er raden fullstendig og regnet fra fakturaen (`nettokraft_kilde` er «faktura», manuell
    overstyring), er den ikke sperret, selv om forklaringen står igjen.
    """
    if not isinstance(maned, dict):
        return None
    verdi = maned.get("sperre")
    if not verdi:
        return None
    if maned.get("nettokraft_kilde") == "faktura" and fullstendig(maned):
        return None
    tekst = verdi.strip() if isinstance(verdi, str) else "sperret av regnskapssensoren"
    return tekst or None


def fullstendig(maned: Any) -> bool:
    """Har månedstallene alt som trengs for å regne ut et oppgjør?"""
    return isinstance(maned, dict) and all(
        til_float(maned.get(k)) is not None for k in KREVD_FRA_HUSET
    )


class Kilder:
    """Leser fra sensorene som er valgt i oppsettet."""

    def __init__(self, hass: HomeAssistant, hent_cfg: Callable[[], dict[str, Any]]) -> None:
        self._hass = hass
        self._cfg = hent_cfg

    def regnskap_attr(self) -> dict[str, Any]:
        stat = self._hass.states.get(self._cfg()[CONF_ENT_REGNSKAP])
        if stat is None or stat.state == "unavailable":
            return {}
        return dict(stat.attributes)

    def finn_maned(self, periode_id: str) -> dict[str, Any] | None:
        maneder = self.regnskap_attr().get("maneder") or []
        return next(
            (m for m in maneder if isinstance(m, dict) and m.get("mnd") == periode_id), None
        )

    def float_tilstand(self, entity_id: str) -> float | None:
        stat = self._hass.states.get(entity_id)
        return til_float(stat.state) if stat is not None else None

    def last_period(self) -> float | None:
        """utility_meter.last_period (en tekststreng i HA) som tall."""
        stat = self._hass.states.get(self._cfg()[CONF_ENT_UTILITY])
        return None if stat is None else til_float(stat.attributes.get("last_period"))

    def prognose_endring(self) -> float | None:
        stat = self._hass.states.get(self._cfg()[CONF_ENT_PROGNOSE])
        return None if stat is None else til_float(stat.attributes.get("endring_prosent"))


def bygg_data(
    kilder: Kilder,
    cfg: dict[str, Any],
    perioder: list[dict[str, Any]],
    naa: datetime,
    side_url: str | None,
    side_sist_publisert: datetime | None,
) -> dict[str, Any]:
    """Alt sensorene og leietakersiden trenger, på ett sted."""
    synlige = [p for p in perioder if p["status"] != STATUS_VENTER]
    siste = max(synlige, key=lambda p: p["id"]) if synlige else None
    denne_id = f"{naa.year}-{naa.month:02d}"

    # «hittil» fra regnskapssensoren gjelder bare hvis den faktisk viser inneværende måned
    denne = kilder.regnskap_attr().get("denne_maneden") or {}
    i_maneden = isinstance(denne, dict) and denne.get("mnd") == denne_id
    endring = kilder.prognose_endring()
    forrige = forrige_periode(perioder, denne_id)
    forrige_kwh = forrige["leilighet_kwh"] if forrige is not None else None
    forrige_snitt = forrige["snitt"] if forrige is not None else None
    # Uten målerforbruk hittil: forrige periode × husets endring. Koordinatoren regner på nytt
    # med takten når måleren har gitt «hittil» (se StromregnskapCoordinator._sett_estimat).
    estimat_kwh, estimat_kr, estimat_metode = velg_estimat(
        naa, None, forrige_kwh, forrige_snitt, endring
    )

    return {
        "naa": naa,
        "perioder": list(perioder),
        "utestaaende": utestaaende(perioder),
        "antall_utestaaende": sum(1 for p in perioder if p["status"] in UTESTAAENDE_STATUSER),
        "siste": siste,
        "venter": sorted(p["id"] for p in perioder if p["status"] == STATUS_VENTER),
        "kwh_hittil": kilder.float_tilstand(cfg[CONF_ENT_UTILITY]),
        "snitt_hittil": til_float(denne.get("snitt")) if i_maneden else None,
        "kostnad_hittil": til_float(denne.get("leilighet_kr")) if i_maneden else None,
        "endring_prosent": endring,
        "estimat_kwh": estimat_kwh,
        "estimat_kr": estimat_kr,
        "estimat_metode": estimat_metode,
        "forrige_kwh": forrige_kwh,
        "forrige_snitt": forrige_snitt,
        "effekt_w": kilder.float_tilstand(cfg[CONF_ENT_EFFEKT]),
        "import_kwh": kilder.float_tilstand(cfg[CONF_ENT_IMPORT]),
        "side_url": side_url,
        "side_sist_publisert": side_sist_publisert,
    }
