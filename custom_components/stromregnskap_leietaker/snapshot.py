"""Øyeblikksbilder av kildetallene gjennom måneden, som reserve for regnskapssensoren.

Skulle regnskapssensoren miste en måned før oppgjøret lages den 3., finnes de siste tallene vi så
i egen lagring. Oppgjør som bygger på et øyeblikksbilde sendes aldri automatisk, men venter alltid
på godkjenning.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .const import CONF_ENT_IMPORT, CONF_ENT_UTILITY
from .kilder import KREVD_FRA_HUSET, fullstendig, til_float

BILDE_INTERVALL = timedelta(hours=6)
BEHOLD_MANEDER = 6
EKSTRA_FELT = ("leilighet_kwh", "leilighet_kr", "kapasitet", "fast")


class SnapshotMixin:
    """Metoder for StromregnskapCoordinator."""

    async def _ta_bilde(self, naa: datetime) -> None:
        mnd = f"{naa.year}-{naa.month:02d}"
        denne = self.kilder.regnskap_attr().get("denne_maneden")
        if not fullstendig(denne) or denne.get("mnd") != mnd:
            return  # bare tall for inneværende måned, og bare hele sett
        bilder = self.lager.data["snapshots"]
        forrige = bilder.get(mnd)
        if forrige and naa - datetime.fromisoformat(forrige["tid"]) < BILDE_INTERVALL:
            return
        maned = {k: float(denne[k]) for k in KREVD_FRA_HUSET}
        maned["mnd"] = mnd
        for felt in EKSTRA_FELT:
            if til_float(denne.get(felt)) is not None:
                maned[felt] = float(denne[felt])
        bilder[mnd] = {
            "tid": naa.isoformat(),
            "maned": maned,
            "utility": self.kilder.float_tilstand(self.cfg[CONF_ENT_UTILITY]),
            "maaler": self.kilder.float_tilstand(self.cfg[CONF_ENT_IMPORT]),
        }
        for gammel in sorted(bilder)[:-BEHOLD_MANEDER]:
            del bilder[gammel]
        await self.lager.async_lagre()
