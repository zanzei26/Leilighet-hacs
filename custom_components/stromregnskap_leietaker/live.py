"""Live oppdatering: sensorene følger kildene så fort de endrer seg.

Den timelige kjøringen (_async_update_data) står for oppgjør, e-post og varsler. Men tallene for
måneden som pågår skal ikke henge etter måleren. Derfor lytter vi på kildesensorene og
oppdaterer entitetene med høyst én oppdatering per 15 sekund. Vi bruker ikke
async_set_updated_data her, siden det ville startet timeren for den timelige kjøringen på nytt
hver gang og dermed sultet den ut.
"""

from __future__ import annotations

import logging

from homeassistant.helpers.debounce import Debouncer
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ENT_EFFEKT,
    CONF_ENT_IMPORT,
    CONF_ENT_PROGNOSE,
    CONF_ENT_REGNSKAP,
    CONF_ENT_UTILITY,
)

_LOGGER = logging.getLogger(__name__)

LIVE_INTERVALL = 15.0  # sekunder


class LiveMixin:
    """Metoder for StromregnskapCoordinator."""

    _live: Debouncer | None = None

    def kildeentiteter(self) -> list[str]:
        c = self.cfg
        nokler = (
            CONF_ENT_IMPORT,
            CONF_ENT_UTILITY,
            CONF_ENT_REGNSKAP,
            CONF_ENT_PROGNOSE,
            CONF_ENT_EFFEKT,
        )
        return sorted({c[k] for k in nokler if c.get(k)})

    def start_live(self) -> None:
        self._live = Debouncer(
            self.hass,
            _LOGGER,
            cooldown=LIVE_INTERVALL,
            immediate=True,
            function=self._live_oppdater,
        )

    def stopp_live(self) -> None:
        if self._live is not None:
            self._live.async_shutdown()
            self._live = None

    async def async_kilde_endret(self, _event) -> None:
        """Kalles når en kildesensor endrer tilstand."""
        if self._live is not None:
            await self._live.async_call()

    async def _live_oppdater(self) -> None:
        if self.data is None:
            return  # første kjøring er ikke ferdig ennå
        data = self._bygg_data(dt_util.now())
        data["side_sist_publisert"] = self._side_publisert
        self.data = data
        self.async_update_listeners()
