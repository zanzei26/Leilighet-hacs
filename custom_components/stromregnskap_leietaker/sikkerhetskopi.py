"""Rullerende sikkerhetskopier av lagringen som JSON-filer.

Blokkerende filfunksjoner uten Home Assistant-avhengigheter. Kalles via executor.
Filnavn: data-ÅÅÅÅMMDD-TTMMSS.json (med _2, _3 … hvis flere i samme sekund).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

VERSJON = 1
NAVN_RE = re.compile(r"^data-(\d{8})-(\d{6})(?:_(\d+))?\.json$")
STANDARD_ANTALL = 20


def _nokkel(navn: str) -> tuple[str, str, int]:
    dato, tid, n = NAVN_RE.match(navn).groups()
    return dato, tid, int(n) if n else 1


def _kopinavn(mappe: str) -> list[str]:
    try:
        navn = [n for n in os.listdir(mappe) if NAVN_RE.match(n)]
    except OSError:
        return []
    return sorted(navn, key=_nokkel)


def skriv_kopi(mappe: str, data: dict[str, Any], tidspunkt: datetime) -> str:
    """Skriver en ny kopi (via midlertidig fil) og returnerer filnavnet."""
    os.makedirs(mappe, exist_ok=True)
    grunn = f"data-{tidspunkt:%Y%m%d-%H%M%S}"
    n = 1
    while True:
        navn = f"{grunn}.json" if n == 1 else f"{grunn}_{n}.json"
        sti = os.path.join(mappe, navn)
        if not os.path.exists(sti):
            break
        n += 1
    tmp = sti + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fil:
        json.dump(
            {"versjon": VERSJON, "lagret": tidspunkt.isoformat(), "data": data},
            fil,
            ensure_ascii=False,
            indent=2,
        )
    os.replace(tmp, sti)
    return navn


def les_siste_gyldige(mappe: str) -> tuple[str, dict[str, Any]] | None:
    """Nyeste kopi som kan leses og har riktig form. Ødelagte kopier hoppes over."""
    for navn in reversed(_kopinavn(mappe)):
        try:
            with open(os.path.join(mappe, navn), encoding="utf-8") as fil:
                innhold = json.load(fil)
        except (OSError, ValueError):
            continue
        data = innhold.get("data") if isinstance(innhold, dict) else None
        if isinstance(data, dict) and isinstance(data.get("perioder"), list):
            return navn, data
    return None


def velg_a_beholde(navn: list[str], antall: int = STANDARD_ANTALL) -> set[str]:
    """De ``antall`` nyeste, pluss den nyeste fra hver eldre måned som ellers ikke er dekket."""
    gyldige = sorted((n for n in navn if NAVN_RE.match(n)), key=_nokkel, reverse=True)
    behold = set(gyldige[:antall])
    dekkede = {_nokkel(n)[0][:6] for n in behold}
    for n in gyldige[antall:]:
        maaned = _nokkel(n)[0][:6]
        if maaned not in dekkede:
            behold.add(n)
            dekkede.add(maaned)
    return behold


def rydd(mappe: str, antall: int = STANDARD_ANTALL) -> int:
    """Sletter kopier som ikke skal beholdes. Returnerer antall slettede."""
    alle = _kopinavn(mappe)
    behold = velg_a_beholde(alle, antall)
    slettet = 0
    for navn in alle:
        if navn not in behold:
            try:
                os.unlink(os.path.join(mappe, navn))
                slettet += 1
            except OSError:
                pass
    return slettet
