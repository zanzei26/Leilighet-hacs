"""Oppgradering fra 0.1.0: gammelt oppsett (uten de nyere feltene) og gammel lagringsnøkkel."""

from copy import deepcopy
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.stromregnskap_leietaker.const import DOMAIN

from .conftest import tillat_ruter_etter_oppstart
from .data import CFG, OKT, SEP, sett_kilder

NYE_FELT = ("maaler_start_stand", "kopi_til_utleier", "lader_aktiv", "ent_lader")
NY_NOKKEL = "stromregnskap_leietaker"


async def test_oppsett_fra_0_1_0_laster_og_beholder_historikken(
    hass, hass_storage, tmp_path, freezer
):
    await hass.config.async_set_time_zone("Europe/Oslo")
    hass.config.config_dir = str(tmp_path)
    hass.config.external_url = "https://eksempel.ui.nabu.casa"
    freezer.move_to("2026-11-10 12:00:00+01:00")
    sett_kilder(hass, denne={"mnd": "2026-11", "snitt": 1.5, "leilighet_kr": 40.0}, utility="30.25")
    async_mock_service(hass, "notify", "varsle_utleier")
    assert await async_setup_component(hass, "http", {})
    tillat_ruter_etter_oppstart(hass)

    # Slik 0.1.0 lagret ting: oppsettet har ingen av de nyere feltene, og dataene ligger under
    # en nøkkel med entry-id (versjon 1.1), uten målerstander og øyeblikksbilder.
    gammelt_oppsett = {k: v for k, v in CFG.items() if k not in NYE_FELT}
    gammel_nokkel = f"{NY_NOKKEL}.e1"
    hass_storage[gammel_nokkel] = {
        "version": 1,
        "minor_version": 1,
        "key": gammel_nokkel,
        "data": {
            "perioder": [deepcopy(SEP), deepcopy(OKT)],
            "tilstand": {"historikk_importert": True, "varslet": []},
        },
    }
    entry = MockConfigEntry(domain=DOMAIN, data=gammelt_oppsett, entry_id="e1")
    entry.add_to_hass(hass)

    with (
        patch("custom_components.stromregnskap_leietaker.epost.send_epost") as epost,
        patch("custom_components.stromregnskap_leietaker.url.cloud_url", return_value=None),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    lager = entry.runtime_data.lager
    assert lager.migrert_fra_gammel is True  # dataene ble hentet fra 0.1.0-nøkkelen
    assert [p["id"] for p in lager.perioder] == ["2026-09", "2026-10"]  # historikken er der
    assert [p["id"] for p in hass_storage[NY_NOKKEL]["data"]["perioder"]] == ["2026-09", "2026-10"]
    # de nyere seriene finnes og er tomme, og laderen er av
    assert lager.data["laderstander"] == {} and not entry.runtime_data.coordinator.lader_aktiv
    # målerstand ved månedsskiftet er seedet fra startstanden (standard 0 når feltet mangler)
    assert lager.data["maalerstander"]["2026-11-01"]["kilde"] == "start"
    assert lager.data["maalerstander"]["2026-11-01"]["stand"] == 0.0

    # sensorene har verdier, og det er ikke sendt noen e-post bare fordi vi oppgraderte
    assert hass.states.get("sensor.leietaker_utestaende").state == "304.25"
    assert hass.states.get("sensor.leietaker_forbruk_hittil").state == "30.3"
    assert epost.call_count == 0

    # e-postkopien er på som standard også for et oppsett som ikke har feltet (0.1.0)
    assert entry.runtime_data.coordinator.cfg.get("kopi_til_utleier", True) is True
