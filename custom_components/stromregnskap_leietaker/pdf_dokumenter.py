"""Fakturagrunnlag (per periode) og hele regnskapet som PDF.

Alt er ferdig utregnet og vises med utregningen synlig, slik at både utleier og leietaker kan
kontrollere tallene uten å regne selv. Oppgjør som venter på godkjenning tas aldri med.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from .calc import STATUS_BETALT, STATUS_VENTER, avrund, utestaaende
from .filnavn import REGNSKAPSNAVN, fakturanavn  # noqa: F401 - gjeneksporteres
from .page import fmt_dato, fmt_kwh, fmt_tall, maaned_tekst, periode_tekst
from .pdf import (
    A4_BREDDE,
    A4_HOYDE,
    GRAA,
    Dokument,
    Side,
    tekstbredde,
)

M = 50.0  # venstre marg
H = A4_BREDDE - M  # høyre kant
MAKS_Y = A4_HOYDE - 70  # nederste y for innhold; bunnteksten ligger under
RAD = 14.0


def _status(p: dict[str, Any]) -> str:
    return "Betalt" if p["status"] == STATUS_BETALT else "Ikke betalt"


def _bunntekst(naa: datetime) -> str:
    return f"Generert av Home Assistant {naa:%d.%m.%Y %H:%M}"


def _avsnitt(side: Side, y: float, tekst: str, bredde: float, *, storrelse: float = 9) -> float:
    """Skriver tekst brutt på ordgrenser. Returnerer y under siste linje."""
    linje = ""
    for ord_ in tekst.split():
        prov = f"{linje} {ord_}".strip()
        if tekstbredde(prov, storrelse) > bredde and linje:
            side.tekst(M, y, linje, storrelse=storrelse)
            y += storrelse + 3
            linje = ord_
        else:
            linje = prov
    if linje:
        side.tekst(M, y, linje, storrelse=storrelse)
        y += storrelse + 3
    return y


def _seksjon(side: Side, y: float, tittel: str) -> float:
    side.rektangel(M, y - 11, H - M, 16)
    side.tekst(M + 6, y, tittel, storrelse=10, fet=True)
    return y + 20


def _verdirad(
    side: Side, y: float, tekst: str, verdi: str, *, fet: bool = False, storrelse: float = 10
) -> float:
    side.tekst(M + 6, y, tekst, storrelse=storrelse, fet=fet)
    side.tekst(H - 6, y, verdi, storrelse=storrelse, fet=fet, hoyre=True)
    return y + RAD + 1


def _parter(side: Side, y: float, leietaker: dict[str, Any], utleier: dict[str, Any]) -> float:
    side.tekst(M, y, "Fra (utleier)", storrelse=8, farge=GRAA)
    side.tekst(300, y, "Til (leietaker)", storrelse=8, farge=GRAA)
    y += 13
    side.tekst(M, y, utleier["navn"], fet=True)
    side.tekst(300, y, leietaker["navn"], fet=True)
    y += 13
    side.tekst(M, y, utleier["epost"])
    side.tekst(300, y, leietaker["adresse"])
    y += 13
    side.tekst(300, y, leietaker["epost"])
    return y + 18


# --- fakturagrunnlag ----------------------------------------------------------------------------


def bygg_fakturagrunnlag(
    periode: dict[str, Any], leietaker: dict[str, Any], utleier: dict[str, Any], naa: datetime
) -> bytes:
    """Fakturagrunnlag for én periode: forbruk, husets kostnader, utregning og betaling."""
    maaned = maaned_tekst(periode["id"])
    start = date.fromisoformat(periode["start"])
    slutt = date.fromisoformat(periode["slutt"])
    siste = slutt - timedelta(days=1)
    dok = Dokument(f"Fakturagrunnlag strøm leilighet – {maaned}", bunntekst=_bunntekst(naa))
    s = dok.ny_side()

    y = 62.0
    s.tekst(M, y, "Fakturagrunnlag – strøm leilighet", storrelse=20, fet=True)
    y += 24
    s.tekst(M, y, f"Periode: {maaned}   ({start:%d.%m.%Y} – {siste:%d.%m.%Y})", storrelse=11)
    y += 10
    s.linje(M, y, H, y)
    y += 18
    y = _parter(s, y, leietaker, utleier)

    y = _seksjon(s, y, "1. Ditt forbruk")
    if periode.get("maaler_start") is not None and periode.get("maaler_slutt") is not None:
        y = _verdirad(
            s, y, f"Målerstand {start:%d.%m.%Y}", f"{fmt_tall(periode['maaler_start'], 1)} kWh"
        )
        y = _verdirad(
            s, y, f"Målerstand {slutt:%d.%m.%Y}", f"{fmt_tall(periode['maaler_slutt'], 1)} kWh"
        )
    y = _verdirad(
        s, y, "Ditt forbruk i perioden", f"{fmt_kwh(periode['leilighet_kwh'])} kWh", fet=True
    )
    y += 8

    y = _seksjon(s, y, "2. Husets strømkostnad i samme periode")
    y = _verdirad(
        s, y, "Kraft (inkl. fast månedspris og mva)", f"{fmt_tall(periode['kraft'], 2)} kr"
    )
    y = _verdirad(
        s, y, "Nettleie (inkl. kapasitetsledd og mva)", f"{fmt_tall(periode['nettleie'], 2)} kr"
    )
    y = _verdirad(s, y, "Fratrekk Norgespris", f"-{fmt_tall(periode['norgespris'], 2)} kr")
    y = _verdirad(s, y, "Husets strømkostnad", f"{fmt_tall(periode['sum'], 2)} kr", fet=True)
    y = _verdirad(s, y, "Husets forbruk", f"{fmt_tall(periode['hus_kwh'], 2)} kWh")
    y = _verdirad(
        s,
        y,
        "Snittpris (husets strømkostnad ÷ husets forbruk)",
        f"{fmt_tall(periode['snitt'], 4)} kr/kWh",
        fet=True,
    )
    y += 8

    y = _seksjon(s, y, "3. Utregning")
    utregning = (
        f"{fmt_kwh(periode['leilighet_kwh'])} kWh × {fmt_tall(periode['snitt'], 4)} kr/kWh"
        f" = {fmt_tall(periode['belop'], 2)} kr"
    )
    s.tekst(M + 6, y, utregning, storrelse=11)
    y += RAD + 6
    s.linje(M, y - 8, H, y - 8)
    y = _verdirad(
        s, y + 6, "Beløp å betale", f"{fmt_tall(periode['belop'], 2)} kr", fet=True, storrelse=14
    )
    y += 6

    y = _seksjon(s, y, "4. Betaling")
    y = _verdirad(s, y, "Kontonummer", utleier["kontonummer"])
    y = _verdirad(s, y, "Merk betalingen", f"Strøm – {maaned}")
    y = _verdirad(s, y, "Forfall", fmt_dato(periode["forfall"]))
    y = _verdirad(s, y, "Status", _status(periode))
    y += 14

    _avsnitt(
        s,
        y,
        "Beløpet er ditt målte forbruk multiplisert med husets faktiske snittpris for samme "
        "kalendermåned. Husets snittpris er kraft pluss nettleie minus Norgespris, delt på "
        "husets samlede forbruk. Alle ledd er med, inkludert mva og faste ledd.",
        H - M,
    )
    return dok.til_bytes(naa)


# --- regnskap ------------------------------------------------------------------------------------


class _Papir:
    """Holder styr på gjeldende side og y-posisjon, og bytter side når det ikke er plass."""

    def __init__(self, dok: Dokument, topptekst: str) -> None:
        self.dok = dok
        self.topptekst = topptekst
        self.side = dok.ny_side()
        self.y = 62.0

    def ny_side(self) -> None:
        self.side = self.dok.ny_side()
        self.side.tekst(M, 44, f"{self.topptekst} (fortsatt)", storrelse=9, farge=GRAA)
        self.y = 66.0

    def sikre(self, hoyde: float) -> bool:
        """Bytter side hvis ``hoyde`` ikke får plass. Returnerer True ved sidebytte."""
        if self.y + hoyde > MAKS_Y:
            self.ny_side()
            return True
        return False


Kolonne = tuple[str, float, str]  # (overskrift, x, "v" venstre eller "h" høyre)


def _tabell(papir: _Papir, tittel: str, kolonner: list[Kolonne], rader: list[list[str]]) -> None:
    papir.sikre(2 * RAD + 30)
    papir.side.tekst(M, papir.y, tittel, storrelse=12, fet=True)
    papir.y += 16

    def hode() -> None:
        papir.side.rektangel(M, papir.y - 10, H - M, RAD + 1)
        for overskrift, x, justering in kolonner:
            papir.side.tekst(
                x, papir.y, overskrift, storrelse=8.5, fet=True, hoyre=justering == "h"
            )
        papir.y += RAD + 2

    hode()
    for rad in rader:
        if papir.sikre(RAD + 2):
            hode()
        for (_, x, justering), celle in zip(kolonner, rad, strict=True):
            papir.side.tekst(x, papir.y, celle, storrelse=8.5, hoyre=justering == "h")
        papir.side.linje(M, papir.y + 4, H, papir.y + 4, bredde=0.25)
        papir.y += RAD
    papir.y += 10


def bygg_regnskap(
    perioder: list[dict[str, Any]],
    leietaker: dict[str, Any],
    utleier: dict[str, Any],
    naa: datetime,
) -> bytes:
    """Hele regnskapet fra start: leietakers oppgjør, totaler og husets kostnader per måned."""
    synlige = sorted((p for p in perioder if p["status"] != STATUS_VENTER), key=lambda p: p["id"])
    dok = Dokument("Regnskap strøm leilighet", bunntekst=_bunntekst(naa))
    papir = _Papir(dok, "Regnskap – strøm leilighet")
    s = papir.side

    s.tekst(M, papir.y, "Regnskap – strøm leilighet", storrelse=20, fet=True)
    papir.y += 20
    innflyttet = leietaker.get("innflyttet")
    fra = f"Leieforhold fra {fmt_dato(innflyttet)}. " if innflyttet else ""
    s.tekst(M, papir.y, f"{fra}Per {naa:%d.%m.%Y}.", storrelse=10, farge=GRAA)
    papir.y += 10
    s.linje(M, papir.y, H, papir.y)
    papir.y += 18
    papir.y = _parter(s, papir.y, leietaker, utleier)

    fakturert = avrund(sum((Decimal(str(p["belop"])) for p in synlige), Decimal(0)), 2)
    betalt = avrund(
        sum(
            (Decimal(str(p["belop"])) for p in synlige if p["status"] == STATUS_BETALT), Decimal(0)
        ),
        2,
    )
    papir.y = _seksjon(s, papir.y, "Sammendrag")
    papir.y = _verdirad(s, papir.y, "Totalt fakturert", f"{fmt_tall(fakturert, 2)} kr")
    papir.y = _verdirad(s, papir.y, "Herav betalt", f"{fmt_tall(betalt, 2)} kr")
    papir.y = _verdirad(
        s, papir.y, "Utestående", f"{fmt_tall(utestaaende(synlige), 2)} kr", fet=True
    )
    papir.y += 10

    if not synlige:
        s.tekst(M, papir.y, "Ingen oppgjør ennå.", storrelse=11)
        papir.y += 24
    else:
        _tabell(
            papir,
            "Leietakers oppgjør (snittpris i kr/kWh)",
            [
                ("Periode", M, "v"),
                ("Forbruk (kWh)", 290.0, "h"),
                ("Snittpris", 350.0, "h"),
                ("Beløp (kr)", 415.0, "h"),
                ("Forfall", 430.0, "v"),
                ("Status", H, "h"),
            ],
            [
                [
                    periode_tekst(p),
                    fmt_kwh(p["leilighet_kwh"]),
                    fmt_tall(p["snitt"], 4),
                    fmt_tall(p["belop"], 2),
                    fmt_dato(p["forfall"]),
                    _status(p),
                ]
                for p in synlige
            ],
        )
        _tabell(
            papir,
            "Husets strømkostnader per måned (kr)",
            [
                ("Periode", M, "v"),
                ("Husets kWh", 215.0, "h"),
                ("Kraft", 280.0, "h"),
                ("Nettleie", 345.0, "h"),
                ("Norgespris", 415.0, "h"),
                ("Sum", 480.0, "h"),
                ("Snittpris", H, "h"),
            ],
            [
                [
                    maaned_tekst(p["id"]),
                    fmt_tall(p["hus_kwh"], 2),
                    fmt_tall(p["kraft"], 2),
                    fmt_tall(p["nettleie"], 2),
                    fmt_tall(p["norgespris"], 2),
                    fmt_tall(p["sum"], 2),
                    fmt_tall(p["snitt"], 4),
                ]
                for p in synlige
            ],
        )

    papir.sikre(110)
    papir.y = _seksjon(papir.side, papir.y, "Betaling")
    papir.y = _verdirad(papir.side, papir.y, "Kontonummer", utleier["kontonummer"])
    papir.y = _verdirad(papir.side, papir.y, "Til", utleier["navn"])
    papir.y += 6
    _avsnitt(
        papir.side,
        papir.y,
        "Beløp per måned er leietakers målte forbruk multiplisert med husets faktiske snittpris "
        "for samme kalendermåned (kraft pluss nettleie minus Norgespris, delt på husets forbruk).",
        H - M,
    )
    return dok.til_bytes(naa)
