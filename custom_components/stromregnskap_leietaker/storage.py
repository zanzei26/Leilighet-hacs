"""Lagring av perioder, målerstander og tilstand.

Hovedlageret er homeassistant.helpers.storage.Store under en fast nøkkel (ikke knyttet til
config entry), så historikken overlever at integrasjonen fjernes og legges til igjen. Ved hver
lagring skrives i tillegg en rullerende JSON-sikkerhetskopi. Er hovedlageret borte eller
ødelagt, gjenopprettes siste gyldige kopi i stedet for å starte tomt.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .sikkerhetskopi import les_siste_gyldige, rydd, skriv_kopi

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_MINOR_VERSION = 2
LEGACY_MINOR_VERSION = 1


def standard_data() -> dict[str, Any]:
    """Tom lagring med alle nøkler på plass."""
    return {
        "leietaker": {},
        "utleier": {},
        "perioder": [],
        "maalerstander": {},
        "snapshots": {},
        "tilstand": {"historikk_importert": False, "varslet": [], "opprettet": None},
    }


def _fyll_inn(data: dict[str, Any]) -> dict[str, Any]:
    ferdig = standard_data()
    ferdig.update({k: v for k, v in data.items() if k != "tilstand"})
    ferdig["tilstand"].update(data.get("tilstand", {}))
    return ferdig


class _LagerStore(Store[dict[str, Any]]):
    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Fyller inn nøkler som mangler. Nyere hovedversjon støttes ikke."""
        if old_major_version > STORAGE_VERSION:
            raise NotImplementedError(
                f"Lagringsversjon {old_major_version} er nyere enn støttet ({STORAGE_VERSION})"
            )
        return _fyll_inn(old_data)


def _sjekksum(data: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


class Lager:
    """Perioder, målerstander, øyeblikksbilder og tilstand."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._store = _LagerStore(
            hass, STORAGE_VERSION, DOMAIN, minor_version=STORAGE_MINOR_VERSION
        )
        # 0.1.x lagret under en nøkkel med entry-id
        self._gammel = _LagerStore(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}", minor_version=LEGACY_MINOR_VERSION
        )
        self.data: dict[str, Any] = standard_data()
        self.migrert_fra_gammel = False
        self.gjenopprettet_fra: str | None = None
        self.siste_kopi: str | None = None
        self.kopi_feil: str | None = None
        self._siste_sjekksum: str | None = None

    @property
    def kopimappe(self) -> str:
        return self._hass.config.path(DOMAIN, "sikkerhetskopi")

    async def async_last(self) -> None:
        lagret = await self._store.async_load()
        if lagret is None:
            gammel = await self._gammel.async_load()
            if gammel is not None:
                lagret = gammel
                self.migrert_fra_gammel = True
        if lagret is None:
            # Aldri start tom hvis det finnes en kopi: lagringsfilen kan være ødelagt eller slettet
            kopi = await self._hass.async_add_executor_job(les_siste_gyldige, self.kopimappe)
            if kopi is not None:
                self.gjenopprettet_fra, lagret = kopi
                _LOGGER.warning("Lagringen manglet. Gjenopprettet fra sikkerhetskopi %s", kopi[0])
        self.data = _fyll_inn(lagret) if lagret else standard_data()
        if not self.tilstand.get("opprettet"):
            self.tilstand["opprettet"] = dt_util.now().isoformat()
        if self.migrert_fra_gammel or self.gjenopprettet_fra:
            await self.async_lagre()

    async def async_lagre(self) -> None:
        data = deepcopy(self.data)
        await self._store.async_save(data)
        await self._skriv_kopi(data)

    async def _skriv_kopi(self, data: dict[str, Any]) -> None:
        """Skriver sikkerhetskopi hvis noe er endret. Feil her stopper aldri lagringen."""
        sjekksum = _sjekksum(data)
        if sjekksum == self._siste_sjekksum:
            return
        try:
            navn = await self._hass.async_add_executor_job(
                skriv_kopi, self.kopimappe, data, dt_util.now()
            )
            await self._hass.async_add_executor_job(rydd, self.kopimappe)
        except (OSError, TypeError, ValueError) as err:
            self.kopi_feil = f"{type(err).__name__}: {err}"
            _LOGGER.warning("Kunne ikke skrive sikkerhetskopi: %s", err)
            return
        self.siste_kopi = navn
        self.kopi_feil = None
        self._siste_sjekksum = sjekksum

    @property
    def perioder(self) -> list[dict[str, Any]]:
        return self.data["perioder"]

    @property
    def tilstand(self) -> dict[str, Any]:
        return self.data["tilstand"]

    def finn(self, periode_id: str) -> dict[str, Any] | None:
        return next((p for p in self.perioder if p["id"] == periode_id), None)

    def legg_til(self, periode: dict[str, Any]) -> None:
        if self.finn(periode["id"]):
            raise ValueError(f"Perioden {periode['id']} finnes allerede")
        self.perioder.append(periode)
        self.perioder.sort(key=lambda p: p["id"])

    def fjern(self, periode_id: str) -> bool:
        antall = len(self.perioder)
        self.data["perioder"] = [p for p in self.perioder if p["id"] != periode_id]
        return len(self.perioder) != antall

    def tom_historikk(self) -> None:
        """Tømmer perioder og varslingshistorikk. Målerstander og importflagget beholdes."""
        self.data["perioder"] = []
        self.tilstand["varslet"] = []
