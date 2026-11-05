"""Tidlig varsel om datagrunnlaget, og varsel om oppgjør som ikke er laget.

Poenget er at du skal få vite om et hull i god tid før månedsskiftet, ikke på selve dagen.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .calc import periode_start_slutt
from .const import CONF_ENT_IMPORT, CONF_ENT_LADER, CONF_ENT_REGNSKAP
from .kilder import fullstendig, sperre
from .maaler import LADER, LIVE_VINDU
from .varsler import ISSUE_DATAGRUNNLAG, ISSUE_ETTERSLEP

VARSEL_FRA_DAG = 25
BILDE_MAKS_ALDER = timedelta(hours=48)


class DatagrunnlagMixin:
    """Metoder for StromregnskapCoordinator."""

    def vurder_datagrunnlag(self, naa: datetime) -> list[str]:
        """Alt som hindrer at neste månedsoppgjør kan lages trygt, på klartekst."""
        c = self.cfg
        mnd = f"{naa.year}-{naa.month:02d}"
        problemer: list[str] = []

        attr = self.kilder.regnskap_attr()
        if not attr:
            problemer.append(f"Regnskapssensoren {c[CONF_ENT_REGNSKAP]} er utilgjengelig.")
        elif naa.day >= 2:
            denne = attr.get("denne_maneden")
            if (sperret := sperre(denne)) and denne.get("mnd") == mnd:
                problemer.append(
                    f"Regnskapssensoren {c[CONF_ENT_REGNSKAP]} har sperret inneværende måned "
                    f"({mnd}): {sperret}. Oppgjøret lages ikke før fakturaens tall er lagt inn."
                )
            elif not fullstendig(denne) or denne.get("mnd") != mnd:
                problemer.append(
                    f"Regnskapssensoren {c[CONF_ENT_REGNSKAP]} har ikke komplette tall for "
                    f"inneværende måned ({mnd})."
                )

        if self.kilder.float_tilstand(c[CONF_ENT_IMPORT]) is None:
            problemer.append(f"Måleren {c[CONF_ENT_IMPORT]} er utilgjengelig.")

        start = naa.date().replace(day=1)
        grense = dt_util.start_of_local_day(start)
        if self._lagret_stand(start) is None and naa - grense > LIVE_VINDU:
            problemer.append(
                f"Målerstand ved månedsskiftet {start:%d.%m.%Y} mangler. "
                "Legg den inn med handlingen «Sett målerstand»."
            )

        if self.lader_aktiv:
            if self.kilder.float_tilstand(c[CONF_ENT_LADER]) is None:
                problemer.append(f"Laderens teller {c[CONF_ENT_LADER]} er utilgjengelig.")
            if self._lagret_stand(start, LADER) is None and naa - grense > LIVE_VINDU:
                problemer.append(
                    f"Laderens teller ved månedsskiftet {start:%d.%m.%Y} mangler. "
                    "Legg den inn med handlingen «Sett målerstand» (måler: lader)."
                )

        if naa.day >= 3:
            bilde = self.lager.data["snapshots"].get(mnd)
            if bilde is None or naa - datetime.fromisoformat(bilde["tid"]) > BILDE_MAKS_ALDER:
                problemer.append(
                    "Det er ikke tatt noe øyeblikksbilde av kildetallene siste 48 timer."
                )

        if self.lager.kopi_feil:
            problemer.append(f"Sikkerhetskopiering feiler: {self.lager.kopi_feil}")
        return problemer

    async def _varsle_datagrunnlag(self, naa: datetime) -> None:
        mnd = f"{naa.year}-{naa.month:02d}"
        forrige = f"{naa.year - 1}-12" if naa.month == 1 else f"{naa.year}-{naa.month - 1:02d}"
        self.varsler.fjern_issue(ISSUE_DATAGRUNNLAG, forrige)
        problemer = self.vurder_datagrunnlag(naa)
        if not problemer:
            self.varsler.fjern_issue(ISSUE_DATAGRUNNLAG, mnd)
            return
        if naa.day < VARSEL_FRA_DAG:
            return
        self.varsler.opprett_issue(
            ISSUE_DATAGRUNNLAG,
            mnd,
            fixable=False,
            severity=ir.IssueSeverity.WARNING,
            placeholders={"problemer": " ".join(problemer)},
        )
        await self.varsler.varsle_en_gang(
            f"{ISSUE_DATAGRUNNLAG}:{naa.date().isoformat()}",
            "Strømoppgjør: datagrunnlaget har problemer",
            "Månedsskiftet nærmer seg, og dette må ordnes før oppgjøret kan lages trygt:\n"
            + "\n".join(f"• {p}" for p in problemer),
        )

    async def _varsle_etterslep(self, periode_id: str, naa: datetime) -> None:
        """Oppgjøret for forrige måned er ikke laget, og vinduet for automatisk kjøring er over."""
        slutt = periode_start_slutt(periode_id)[1]
        opprettet = date.fromisoformat(self.lager.tilstand["opprettet"][:10])
        if slutt <= opprettet:
            return  # perioden var over før integrasjonen fantes
        self.varsler.opprett_issue(
            ISSUE_ETTERSLEP, periode_id, fixable=True, severity=ir.IssueSeverity.ERROR
        )
        await self.varsler.varsle_en_gang(
            f"{ISSUE_ETTERSLEP}:{periode_id}:{naa.date().isoformat()}",
            "Strømoppgjør er ikke laget",
            f"Oppgjøret for {periode_id} er ikke laget, og den automatiske kjøringen er over. "
            "Bruk reparasjonen i Home Assistant eller handlingen «Generer oppgjør».",
        )
