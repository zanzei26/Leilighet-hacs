"""Felles testoppsett."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.stromregnskap_leietaker.const import DOMAIN
from custom_components.stromregnskap_leietaker.storage import Lager

from .data import CFG, perioder, sett_kilder


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Tillat at custom_components/ lastes i alle tester."""
    yield


@pytest.fixture
async def oppsett(hass, hass_storage, tmp_path, freezer):
    """Koordinator med historikk (sep betalt, okt ikke betalt), kilder og mocket e-post/varsel."""
    from custom_components.stromregnskap_leietaker.coordinator import StromregnskapCoordinator

    await hass.config.async_set_time_zone("Europe/Oslo")
    hass.config.config_dir = str(tmp_path)  # ikke skriv inn i testpakken
    hass.config.external_url = "https://eksempel.ui.nabu.casa"
    freezer.move_to("2026-12-03 08:30:00+01:00")

    entry = MockConfigEntry(domain=DOMAIN, data=dict(CFG), entry_id="entry123")
    entry.add_to_hass(hass)
    lager = Lager(hass, entry.entry_id)
    await lager.async_last()
    for p in perioder():
        lager.legg_til(p)
    sett_kilder(hass)
    varsler = async_mock_service(hass, "notify", "varsle_magnar")

    with (
        patch("custom_components.stromregnskap_leietaker.epost.send_epost") as epost,
        patch("custom_components.stromregnskap_leietaker.url.cloud_url", return_value=None),
    ):
        coordinator = StromregnskapCoordinator(hass, entry, lager)
        yield SimpleNamespace(
            coordinator=coordinator,
            lager=lager,
            entry=entry,
            varsler=varsler,
            epost=epost,
            tmp=tmp_path,
            freezer=freezer,
        )


@pytest.fixture
async def integrasjon(hass, hass_storage, tmp_path, freezer):
    """Hele integrasjonen oppsatt (med importert historikk), e-post og varsler mocket."""
    from homeassistant.setup import async_setup_component

    await hass.config.async_set_time_zone("Europe/Oslo")
    hass.config.config_dir = str(tmp_path)
    hass.config.external_url = "https://eksempel.ui.nabu.casa"
    freezer.move_to("2026-11-10 12:00:00+01:00")
    sett_kilder(hass, denne={"mnd": "2026-11", "snitt": 1.5, "leilighet_kr": 40.0}, utility="30.25")
    varsler = async_mock_service(hass, "notify", "varsle_magnar")
    assert await async_setup_component(hass, "http", {})

    entry = MockConfigEntry(domain=DOMAIN, data={**CFG, "importer_historikk": True}, entry_id="e1")
    entry.add_to_hass(hass)
    with (
        patch("custom_components.stromregnskap_leietaker.epost.send_epost") as epost,
        patch("custom_components.stromregnskap_leietaker.url.cloud_url", return_value=None),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield SimpleNamespace(
            entry=entry, epost=epost, varsler=varsler, tmp=tmp_path, freezer=freezer
        )
