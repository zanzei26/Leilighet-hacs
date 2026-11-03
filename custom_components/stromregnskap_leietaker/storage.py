"""Lagring av perioder og tilstand med homeassistant.helpers.storage.Store."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1
STORAGE_MINOR_VERSION = 1


def standard_data() -> dict[str, Any]:
    """Tom lagring med alle nøkler på plass."""
    return {
        "leietaker": {},
        "utleier": {},
        "perioder": [],
        "tilstand": {"historikk_importert": False, "varslet": []},
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


class Lager:
    """Perioder og tilstand for én config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = _LagerStore(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}",
            minor_version=STORAGE_MINOR_VERSION,
        )
        self.data: dict[str, Any] = standard_data()

    async def async_last(self) -> None:
        lagret = await self._store.async_load()
        self.data = _fyll_inn(lagret) if lagret else standard_data()

    async def async_lagre(self) -> None:
        await self._store.async_save(deepcopy(self.data))

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
        """Tømmer perioder og varslingshistorikk. Importflagget beholdes."""
        self.data["perioder"] = []
        self.tilstand["varslet"] = []
