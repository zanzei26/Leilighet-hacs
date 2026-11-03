"""Blokkerende filhjelpere. Kalles via hass.async_add_executor_job."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Any


def skriv_atomisk(sti: str, innhold: str) -> None:
    """Skriver filen via en midlertidig fil i samme mappe og os.replace."""
    mappe = os.path.dirname(sti)
    os.makedirs(mappe, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=mappe, prefix=".index-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fil:
            fil.write(innhold)
        os.chmod(tmp, 0o644)
        os.replace(tmp, sti)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def skriv_arkiv(mappe: str, basisnavn: str, innhold: dict[str, Any]) -> str:
    """Skriver arkivfilen uten å overskrive eksisterende (legger på _2, _3 …)."""
    os.makedirs(mappe, exist_ok=True)
    n = 1
    while True:
        navn = f"{basisnavn}.json" if n == 1 else f"{basisnavn}_{n}.json"
        sti = os.path.join(mappe, navn)
        try:
            with open(sti, "x", encoding="utf-8") as fil:
                json.dump(innhold, fil, ensure_ascii=False, indent=2)
            return sti
        except FileExistsError:
            n += 1


def fjern_mappe(sti: str) -> None:
    shutil.rmtree(sti, ignore_errors=True)
