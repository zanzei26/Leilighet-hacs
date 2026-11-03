"""Tester for live oppdatering: kildene endrer seg, sensorene og siden følger med med en gang."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .data import DENNE_DES, sett_kilder

IMPORT = "sensor.minusmaler_leilighet_import"
HITTIL = "sensor.leietaker_forbruk_hittil"
KOSTNAD = "sensor.leietaker_kostnad_hittil"
SIDE = "/local/testslug123/index.html"


# --- hittil regnes fra måleren ----------------------------------------------------------------


async def test_forbruk_hittil_er_malerstand_naa_minus_malerstand_ved_manedsskiftet(hass, oppsett):
    o = oppsett  # Dec 3, målerstand 1. des = 250,0
    hass.states.async_set(IMPORT, "262.04", {})
    await o.coordinator.async_refresh()
    d = o.coordinator.data
    assert d["kwh_hittil"] == 12.0  # 262,0 - 250,0 (begge avrundet til én desimal)
    assert d["hittil_kilde"] == "maaler"
    assert d["snitt_hittil"] == 3.4
    assert d["kostnad_hittil"] == 40.8  # 12,0 × 3,4


async def test_uten_malerstand_ved_manedsskiftet_brukes_utility_meter_som_reserve(hass, oppsett):
    o = oppsett
    del o.lager.data["maalerstander"]["2026-12-01"]
    sett_kilder(hass, utility="21.85", denne={**DENNE_DES, "leilighet_kr": 66.6})
    with patch.object(o.coordinator, "_stand_fra_statistikk", return_value=None):
        await o.coordinator.async_refresh()
    d = o.coordinator.data
    assert d["kwh_hittil"] == 21.85 and d["hittil_kilde"] == "utility_meter"
    assert d["kostnad_hittil"] == 66.6  # som regnskapssensoren oppgir


async def test_maaler_som_gaar_bakover_gir_reserve_og_ikke_negativt_forbruk(hass, oppsett):
    o = oppsett
    hass.states.async_set(IMPORT, "100.0", {})  # lavere enn 250,0 ved månedsskiftet
    await o.coordinator.async_refresh()
    assert o.coordinator.data["hittil_kilde"] == "utility_meter"


async def test_regnskapssensoren_borte_et_oyeblikk_stopper_ikke_forbruket_hittil(hass, oppsett):
    """Under en omlegging av kildene kan husets regnskapssensor være utilgjengelig en stund."""
    o = oppsett
    hass.states.async_set("sensor.jarvis_stromregnskap", "unavailable")
    hass.states.async_set(IMPORT, "262.04", {})
    await o.coordinator.async_refresh()
    d = o.coordinator.data
    assert d["kwh_hittil"] == 12.0 and d["hittil_kilde"] == "maaler"  # måleren er uavhengig
    assert d["snitt_hittil"] is None and d["kostnad_hittil"] is None  # ingen pris, ingen gjetting
    assert "12,0 kWh" in o.coordinator.bygg_side_html(dt_util.now())


# --- live oppdatering av sensorene --------------------------------------------------------------


async def test_sensorene_oppdateres_med_en_gang_naar_maaleren_endrer_seg(hass, integrasjon):
    assert hass.states.get(HITTIL).state == "30.3"  # 30,25 fra oppsettet, én desimal
    hass.states.async_set(IMPORT, "35.04", {})
    await hass.async_block_till_done()
    assert hass.states.get(HITTIL).state == "35.0"
    assert hass.states.get(KOSTNAD).state == "52.5"  # 35,0 × 1,5 (snittpris hittil i oppsettet)


async def test_mange_raske_endringer_slaas_sammen_til_hoyst_en_oppdatering_per_femten_sekund(
    hass, integrasjon
):
    hass.states.async_set(IMPORT, "40.0", {})
    await hass.async_block_till_done()
    assert hass.states.get(HITTIL).state == "40.0"  # første endring: med en gang

    for verdi in ("41.0", "42.0", "43.0"):
        hass.states.async_set(IMPORT, verdi, {})
    await hass.async_block_till_done()
    assert hass.states.get(HITTIL).state == "40.0"  # innenfor 15 s: ennå ikke

    integrasjon.freezer.tick(timedelta(seconds=16))
    async_fire_time_changed(hass, dt_util.now() + timedelta(seconds=16))
    await hass.async_block_till_done()
    assert hass.states.get(HITTIL).state == "43.0"  # siste verdi vinner


async def test_live_oppdatering_utsetter_ikke_den_timelige_kjoringen(hass, integrasjon):
    koordinator = integrasjon.entry.runtime_data.coordinator
    with patch.object(koordinator, "async_set_updated_data") as sett:
        hass.states.async_set(IMPORT, "37.0", {})
        await hass.async_block_till_done()
    assert hass.states.get(HITTIL).state == "37.0"
    sett.assert_not_called()  # ville ellers startet timeren på nytt og sultet ut timekjøringen


async def test_endring_i_prognosen_og_regnskapssensoren_gir_ogsaa_live_oppdatering(
    hass, integrasjon
):
    estimat = "sensor.leietaker_estimat_maned"
    for_ = hass.states.get(estimat).state
    hass.states.async_set("sensor.mal_forbruk_prognose", "3000", {"endring_prosent": 40})
    await hass.async_block_till_done()
    assert hass.states.get(estimat).state != for_


async def test_ingen_lytter_igjen_etter_nedlasting(hass, integrasjon):
    assert await hass.config_entries.async_unload(integrasjon.entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set(IMPORT, "99.0", {})  # skal ikke krasje eller gjøre noe
    await hass.async_block_till_done()


# --- leietakersiden er alltid fersk ---------------------------------------------------------------


async def test_siden_bygges_ferskt_ved_hver_forespoersel(hass, integrasjon, hass_client_no_auth):
    klient = await hass_client_no_auth()
    for_ = await (await klient.get(SIDE)).text()
    assert "30,3 kWh" in for_
    hass.states.async_set(IMPORT, "35.04", {})  # ingen oppdatering eller sidegenerering avventes
    na = await (await klient.get(SIDE)).text()
    assert "35,0 kWh" in na and "30,3 kWh" not in na


async def test_siden_laster_seg_selv_paa_nytt_hvert_minutt_uten_javascript(
    hass, integrasjon, hass_client_no_auth
):
    klient = await hass_client_no_auth()
    html = await (await klient.get(SIDE)).text()
    assert '<meta http-equiv="refresh" content="60">' in html
    assert "<script" not in html


async def test_siden_faller_tilbake_til_filen_hvis_byggingen_feiler(
    hass, integrasjon, hass_client_no_auth
):
    klient = await hass_client_no_auth()
    koordinator = integrasjon.entry.runtime_data.coordinator
    with patch.object(koordinator, "bygg_side_html", side_effect=RuntimeError("feil")):
        svar = await klient.get(SIDE)
    assert svar.status == 200 and "304,25" in await svar.text()  # filen fra siste lagring
