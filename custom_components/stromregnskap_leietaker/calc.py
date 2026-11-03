"""Ren beregningslogikk for strømoppgjøret.

Ingen avhengigheter til Home Assistant, slik at alt kan enhetstestes direkte.
Beløp regnes med Decimal og avrundes med «halvt øre opp» (ikke bankers rounding).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

STATUS_IKKE_BETALT = "ikke_betalt"
STATUS_BETALT = "betalt"
STATUS_VENTER = "venter_godkjenning"
STATUS_UNNTAK = "unntak_ikke_betalt"
STATUSER = (STATUS_IKKE_BETALT, STATUS_BETALT, STATUS_VENTER, STATUS_UNNTAK)
UTESTAAENDE_STATUSER = (STATUS_IKKE_BETALT, STATUS_UNNTAK)
GYLDIGE_MANUELLE_STATUSER = (STATUS_BETALT, STATUS_IKKE_BETALT, STATUS_UNNTAK)


@dataclass(frozen=True)
class Grenser:
    """Terskler for rimelighetskontrollen."""

    snitt_min: float = 0.50
    snitt_maks: float = 3.00
    endring_maks_prosent: float = 60.0


@dataclass(frozen=True)
class KwhValg:
    """Resultat av valget mellom de to kildene for leilighetens kWh."""

    kwh: float | None
    kilde: str
    avvik: str | None = None


def _dec(verdi: float | int | str) -> Decimal:
    return Decimal(str(verdi))


def avrund(verdi: Decimal | float, desimaler: int = 2) -> float:
    """Avrund halvt opp via Decimal."""
    d = verdi if isinstance(verdi, Decimal) else _dec(verdi)
    return float(d.quantize(Decimal(1).scaleb(-desimaler), rounding=ROUND_HALF_UP))


def beregn_belop(leilighet_kwh: float, snitt: float) -> float:
    """Beløp = leilighetens kWh × husets snittpris, avrundet til hele øre."""
    return avrund(_dec(leilighet_kwh) * _dec(snitt), 2)


def _mnd(periode_id: str) -> tuple[int, int]:
    aar, mnd = periode_id.split("-")
    return int(aar), int(mnd)


def _neste_maned(aar: int, mnd: int) -> tuple[int, int]:
    return (aar + 1, 1) if mnd == 12 else (aar, mnd + 1)


def periode_start_slutt(periode_id: str) -> tuple[date, date]:
    """Hele kalendermåneden: (første dag, første dag i neste måned)."""
    aar, mnd = _mnd(periode_id)
    na, nm = _neste_maned(aar, mnd)
    return date(aar, mnd, 1), date(na, nm, 1)


def forfall_for_periode(periode_id: str, forfallsdag: int) -> date:
    """Forfall er valgt dag i måneden etter perioden."""
    aar, mnd = _mnd(periode_id)
    na, nm = _neste_maned(aar, mnd)
    return date(na, nm, forfallsdag)


def forrige_periode_id(idag: date) -> str:
    """Perioden (YYYY-MM) som tilsvarer forrige kalendermåned."""
    if idag.month == 1:
        return f"{idag.year - 1}-12"
    return f"{idag.year}-{idag.month - 1:02d}"


def _norsk(tall: float, desimaler: int = 1) -> str:
    return f"{tall:.{desimaler}f}".replace(".", ",")


@dataclass(frozen=True)
class MaalerForbruk:
    """Forbruk regnet fra to målerstander. ``feil`` settes hvis målerstanden gikk bakover."""

    kwh: float | None
    feil: str | None = None


def maaler_forbruk(stand_start: float | None, stand_slutt: float | None) -> MaalerForbruk:
    """Forbruk = målerstand ved slutten minus målerstand ved starten av perioden.

    Målerstandene rundes til én desimal (halvt opp) før differansen, slik at forbruket er
    nøyaktig differansen av tallene som står på fakturagrunnlaget.
    """
    if stand_start is None or stand_slutt is None:
        return MaalerForbruk(None, None)
    stand_start, stand_slutt = avrund(stand_start, 1), avrund(stand_slutt, 1)
    if stand_slutt < stand_start:
        return MaalerForbruk(
            None,
            f"Målerstanden gikk bakover ({_norsk(stand_start)} → {_norsk(stand_slutt)} kWh). "
            "Måleren kan være byttet eller nullstilt.",
        )
    return MaalerForbruk(avrund(_dec(stand_slutt) - _dec(stand_start), 1), None)


def velg_leilighet_kwh(
    maaned_kwh: float | None,
    last_period: float | None,
    toleranse: float = 0.5,
    *,
    maaler: float | None = None,
) -> KwhValg:
    """Velger leilighetens kWh. Prioritet: målerstander, regnskapssensoren, last_period.

    Er flere kilder til stede og noen avviker mer enn ``toleranse`` kWh fra den valgte,
    settes ``avvik`` med tallene fra alle kildene.
    """
    kilder = [
        ("målerstander", "maalerstander", maaler),
        ("regnskapssensoren", "jarvis_stromregnskap.maneder", maaned_kwh),
        ("utility_meter (last_period)", "utility_meter.last_period", last_period),
    ]
    funnet = [k for k in kilder if k[2] is not None]
    if not funnet:
        return KwhValg(None, "mangler")
    valgt = funnet[0][2]
    kilde = " + ".join(k[1] for k in funnet)
    if any(round(abs(valgt - v), 6) > toleranse for _, _, v in funnet[1:]):
        avvik = "Leilighetens kWh avviker mellom kildene: " + ", ".join(
            f"{navn} {_norsk(v)} kWh" for navn, _, v in funnet
        )
        return KwhValg(valgt, kilde, avvik)
    return KwhValg(valgt, kilde)


def sjekk_rimelighet(
    *,
    leilighet_kwh: float,
    hus_kwh: float,
    snitt: float,
    forrige_kwh: float | None,
    grenser: Grenser,
) -> list[str]:
    """Returnerer en liste med meldinger, én per brutt regel (tom = alt OK)."""
    brudd: list[str] = []
    if snitt < grenser.snitt_min:
        brudd.append(
            f"Snittprisen {_norsk(snitt, 4)} kr/kWh er under minimum {_norsk(grenser.snitt_min, 2)}"
        )
    elif snitt > grenser.snitt_maks:
        brudd.append(
            f"Snittprisen {_norsk(snitt, 4)} kr/kWh er over maksimum "
            f"{_norsk(grenser.snitt_maks, 2)}"
        )
    if leilighet_kwh <= 0:
        brudd.append("Leilighetens forbruk er 0 kWh eller negativt")
    elif leilighet_kwh > hus_kwh:
        brudd.append(
            f"Leilighetens forbruk {_norsk(leilighet_kwh)} kWh er høyere enn husets "
            f"{_norsk(hus_kwh)} kWh"
        )
    if forrige_kwh and forrige_kwh > 0:
        endring = (leilighet_kwh - forrige_kwh) / forrige_kwh * 100
        if round(abs(endring), 6) > grenser.endring_maks_prosent:
            brudd.append(
                f"Forbruket har endret seg {_norsk(endring)} % mot forrige periode "
                f"({_norsk(forrige_kwh)} → {_norsk(leilighet_kwh)} kWh), "
                f"grense ±{_norsk(grenser.endring_maks_prosent, 0)} %"
            )
    return brudd


def beregn_oppgjor(
    *,
    periode_id: str,
    maned: dict[str, Any],
    leilighet_kwh: float,
    forfallsdag: int,
    naa: datetime,
    kilde: str,
) -> dict[str, Any]:
    """Bygger en periode (se datamodellen i README) fra husets månedstall."""
    start, slutt = periode_start_slutt(periode_id)
    snitt = float(maned["snitt"])
    leilighet_kwh = avrund(leilighet_kwh, 1)  # beløpet regnes fra tallet som vises
    return {
        "id": periode_id,
        "start": start.isoformat(),
        "slutt": slutt.isoformat(),
        "leilighet_kwh": leilighet_kwh,
        "hus_kwh": float(maned["kwh"]),
        "kraft": float(maned["kraft"]),
        "nettleie": float(maned["nettleie"]),
        "norgespris": float(maned["norgespris"]),
        "sum": float(maned["sum"]),
        "snitt": snitt,
        "belop": beregn_belop(leilighet_kwh, snitt),
        "forfall": forfall_for_periode(periode_id, forfallsdag).isoformat(),
        "status": STATUS_IKKE_BETALT,
        "generert": naa.isoformat(),
        "epost_sendt": None,
        "epost_ventende_siden": None,
        "kilde": kilde,
        "notat": "",
    }


def auto_status(periode: dict[str, Any], idag: date) -> str:
    """«ikke_betalt» blir «betalt» fra og med forfallsdagen. Andre statuser er uendret."""
    if periode["status"] == STATUS_IKKE_BETALT and idag >= date.fromisoformat(periode["forfall"]):
        return STATUS_BETALT
    return periode["status"]


def utestaaende(perioder: list[dict[str, Any]]) -> float:
    """Sum av beløp for perioder som regnes som ubetalt (ikke de som venter godkjenning)."""
    total = sum(
        (_dec(p["belop"]) for p in perioder if p["status"] in UTESTAAENDE_STATUSER),
        Decimal(0),
    )
    return avrund(total, 2)


def estimat_maned(
    forrige_kwh: float, endring_prosent: float, forrige_snitt: float
) -> tuple[float, float]:
    """Månedsestimat: forrige måneds kWh × (1 + endring/100), priset til forrige snittpris."""
    kwh = float(_dec(forrige_kwh) * (1 + _dec(endring_prosent) / 100))
    return kwh, beregn_belop(kwh, forrige_snitt)


def forrige_periode(perioder: list[dict[str, Any]], periode_id: str) -> dict[str, Any] | None:
    """Nyeste periode med lavere id enn ``periode_id``, uten de som venter på godkjenning."""
    kandidater = [p for p in perioder if p["id"] < periode_id and p["status"] != STATUS_VENTER]
    return max(kandidater, key=lambda p: p["id"]) if kandidater else None
