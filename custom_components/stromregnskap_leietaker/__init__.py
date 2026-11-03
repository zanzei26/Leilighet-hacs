"""Strømregnskap leietaker: månedlig strømoppgjør for leietaker i Home Assistant."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import CONF_IMPORTER_HISTORIKK, CONF_PUBLISER_SIDE, CONF_SLUG, DOMAIN, HISTORIKK
from .coordinator import StromregnskapCoordinator
from .services import async_registrer_tjenester
from .storage import Lager
from .view import LeietakerSideView

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]


@dataclass
class StromregnskapData:
    """Kjøretidsdata for en config entry."""

    coordinator: StromregnskapCoordinator
    lager: Lager


type StromregnskapConfigEntry = ConfigEntry[StromregnskapData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {"aktive_slugs": {}, "registrerte_slugs": set()})
    async_registrer_tjenester(hass)
    return True


async def _importer_historikk(entry: ConfigEntry, lager: Lager, naa: datetime) -> None:
    """Legger inn de to eksisterende periodene én gang, hvis brukeren ba om det."""
    if not entry.data.get(CONF_IMPORTER_HISTORIKK) or lager.tilstand["historikk_importert"]:
        return
    for h in HISTORIKK:
        if lager.finn(h["id"]):
            continue
        lager.legg_til(
            {
                **h,
                "generert": naa.isoformat(),
                "epost_sendt": None,
                "epost_ventende_siden": None,
                "kilde": "import",
                "notat": "Importert fra eksisterende historikk",
            }
        )
    lager.tilstand["historikk_importert"] = True
    await lager.async_lagre()


def _registrer_side(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: StromregnskapCoordinator
) -> None:
    """Gjør siden tilgjengelig for denne config entry'en så lenge den er lastet."""
    if not coordinator.cfg.get(CONF_PUBLISER_SIDE):
        return
    reg = hass.data[DOMAIN]
    slug = coordinator.cfg[CONF_SLUG]
    reg["aktive_slugs"][slug] = coordinator.side_sti
    if slug not in reg["registrerte_slugs"]:  # ruter kan ikke fjernes, bare registreres én gang
        hass.http.register_view(LeietakerSideView(hass, slug))
        reg["registrerte_slugs"].add(slug)

    @callback
    def _skjul_side() -> None:
        reg["aktive_slugs"].pop(slug, None)

    entry.async_on_unload(_skjul_side)


async def async_setup_entry(hass: HomeAssistant, entry: StromregnskapConfigEntry) -> bool:
    lager = Lager(hass, entry.entry_id)
    await lager.async_last()
    await _importer_historikk(entry, lager, dt_util.now())

    coordinator = StromregnskapCoordinator(hass, entry, lager)
    lager.data["leietaker"] = coordinator.leietaker
    lager.data["utleier"] = coordinator.utleier
    await lager.async_lagre()

    await coordinator.async_seed_maaler()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = StromregnskapData(coordinator=coordinator, lager=lager)

    _registrer_side(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Rett etter midnatt: lagre målerstanden ved månedsskiftet (ellers hentes den senere)
    entry.async_on_unload(
        async_track_time_change(
            hass, coordinator.async_fang_maalerstand, hour=0, minute=0, second=20
        )
    )
    entry.async_on_unload(entry.add_update_listener(_ved_endring))
    return True


async def _ved_endring(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: StromregnskapConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
