"""Hele månedsskiftet gjennom den ferdig oppsatte integrasjonen, med klokken stilt frem."""

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .data import sett_kilder

IMPORT = "sensor.minusmaler_leilighet_import"


async def test_midnattslytteren_er_koblet_til_og_lagrer_malerstanden(hass, integrasjon):
    lager = integrasjon.entry.runtime_data.lager
    del lager.data["maalerstander"]["2026-12-01"]
    hass.states.async_set(IMPORT, "250.0", {})
    integrasjon.freezer.move_to("2026-12-01 00:00:20+01:00")
    async_fire_time_changed(hass, dt_util.now())
    await hass.async_block_till_done()
    rad = lager.data["maalerstander"]["2026-12-01"]
    assert rad["stand"] == 250.0 and rad["kilde"] == "live"


async def test_fra_midnatt_til_automatisk_oppgjoer_regnet_fra_maleren(hass, integrasjon):
    lager = integrasjon.entry.runtime_data.lager
    coordinator = integrasjon.entry.runtime_data.coordinator
    assert lager.data["maalerstander"]["2026-11-01"]["kilde"] == "start"  # seedet ved oppsett
    del lager.data["maalerstander"]["2026-12-01"]

    hass.states.async_set(IMPORT, "250.4", {})
    integrasjon.freezer.move_to("2026-12-01 00:00:20+01:00")
    async_fire_time_changed(hass, dt_util.now())
    await hass.async_block_till_done()

    integrasjon.freezer.move_to("2026-12-03 08:30:00+01:00")
    # regnskapssensoren viser nå desember, og måleren har gått 11,6 kWh de første dagene
    sett_kilder(hass, utility="262.0", last_period="250.4")
    await coordinator.async_refresh()

    p = lager.finn("2026-11")
    assert p["leilighet_kwh"] == 250.4  # målerstanden ved månedsskiftet, ikke dagens 262,0
    assert p["status"] == "ikke_betalt" and p["epost_sendt"] is not None
    assert integrasjon.epost.call_count == 1
    assert hass.states.get("binary_sensor.leietaker_datagrunnlag").state == "off"
