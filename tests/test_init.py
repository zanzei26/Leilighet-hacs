"""Tester for oppsett/nedlasting, sensorer og den uautentiserte leietakersiden."""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.stromregnskap_leietaker.const import DOMAIN

from .data import CFG, sett_kilder

SIDE = "/local/testslug123/index.html"


async def _sett_opp(hass, tmp_path, freezer, **cfg):
    await hass.config.async_set_time_zone("Europe/Oslo")
    hass.config.config_dir = str(tmp_path)
    hass.config.external_url = "https://eksempel.ui.nabu.casa"
    freezer.move_to("2026-11-10 12:00:00+01:00")
    sett_kilder(hass, denne={"mnd": "2026-11", "snitt": 1.5, "leilighet_kr": 40.0}, utility="30.25")
    async_mock_service(hass, "notify", "varsle_magnar")
    entry = MockConfigEntry(
        domain=DOMAIN, data={**CFG, "importer_historikk": True, **cfg}, entry_id="e1"
    )
    entry.add_to_hass(hass)
    with patch("custom_components.stromregnskap_leietaker.url.cloud_url", return_value=None):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_oppsett_importerer_historikk_og_lager_entiteter(
    hass, hass_storage, tmp_path, freezer
):
    entry = await _sett_opp(hass, tmp_path, freezer)
    assert entry.state is ConfigEntryState.LOADED

    lager = entry.runtime_data.lager
    assert [p["id"] for p in lager.perioder] == ["2026-09", "2026-10"]
    sep = lager.finn("2026-09")
    assert sep["belop"] == 302.79 and sep["status"] == "betalt" and sep["kilde"] == "import"
    assert lager.finn("2026-10")["belop"] == 304.25
    assert lager.tilstand["historikk_importert"] is True

    assert hass.states.get("sensor.leietaker_utestaende").state == "304.25"
    assert hass.states.get("sensor.leietaker_utestaende").attributes["antall_perioder"] == 1
    assert hass.states.get("sensor.leietaker_siste_oppgjor").state == "304.25"
    assert hass.states.get("sensor.leietaker_siste_oppgjor").attributes["leilighet_kwh"] == 234.0
    assert hass.states.get("sensor.leietaker_forbruk_hittil").state == "30.25"
    assert hass.states.get("sensor.leietaker_kostnad_hittil").state == "40.0"
    assert hass.states.get("sensor.leietaker_estimat_maned").state == "371.18"
    assert hass.states.get("sensor.leietaker_estimat_maned").attributes["estimat_kwh"] == 285.48
    assert hass.states.get("binary_sensor.leietaker_oppgjor_venter_godkjenning").state == "off"
    side = hass.states.get("sensor.leietaker_side_sist_publisert")
    assert side.state.startswith("2026-11-10T11:00:00")  # UTC
    assert side.attributes["side_url"].endswith(SIDE)


async def test_import_gjentas_ikke_etter_at_perioden_er_slettet(
    hass, hass_storage, tmp_path, freezer
):
    entry = await _sett_opp(hass, tmp_path, freezer)
    await entry.runtime_data.coordinator.async_slett_periode("2026-09", bekreft=True)
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert [p["id"] for p in entry.runtime_data.lager.perioder] == ["2026-10"]


async def test_uten_import_er_historikken_tom(hass, hass_storage, tmp_path, freezer):
    entry = await _sett_opp(hass, tmp_path, freezer, importer_historikk=False)
    assert entry.runtime_data.lager.perioder == []
    assert hass.states.get("sensor.leietaker_utestaende").state == "0.0"


async def test_siden_serveres_uten_innlogging_uten_cache(
    hass, hass_storage, hass_client_no_auth, tmp_path, freezer
):
    assert await async_setup_component(hass, "http", {})
    klient = await hass_client_no_auth()
    await _sett_opp(hass, tmp_path, freezer)
    svar = await klient.get(SIDE)
    assert svar.status == 200
    assert svar.headers["Cache-Control"] == "no-store"
    assert "noindex" in svar.headers["X-Robots-Tag"]
    assert svar.content_type == "text/html"
    html = await svar.text()
    assert "Strømregnskap" in html and "304,25" in html
    # filen ligger også i www/<slug>/ slik at /local fungerer som reserve
    assert (tmp_path / "www" / "testslug123" / "index.html").read_text(encoding="utf-8") == html


async def test_feil_slug_gir_404(hass, hass_storage, hass_client_no_auth, tmp_path, freezer):
    assert await async_setup_component(hass, "http", {})
    klient = await hass_client_no_auth()
    await _sett_opp(hass, tmp_path, freezer)
    assert (await klient.get("/local/annen-slug/index.html")).status == 404


async def test_siden_forsvinner_ved_nedlasting_og_kommer_tilbake_ved_ny_innlasting(
    hass, hass_storage, hass_client_no_auth, tmp_path, freezer
):
    assert await async_setup_component(hass, "http", {})
    klient = await hass_client_no_auth()
    entry = await _sett_opp(hass, tmp_path, freezer)
    assert (await klient.get(SIDE)).status == 200

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert (await klient.get(SIDE)).status == 404

    with patch("custom_components.stromregnskap_leietaker.url.cloud_url", return_value=None):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert (await klient.get(SIDE)).status == 200  # ingen dobbel registrering av ruten


async def test_ingen_side_og_ingen_rute_naar_publisering_er_av(
    hass, hass_storage, hass_client_no_auth, tmp_path, freezer
):
    assert await async_setup_component(hass, "http", {})
    klient = await hass_client_no_auth()
    await _sett_opp(hass, tmp_path, freezer, publiser_side=False)
    assert (await klient.get(SIDE)).status == 404
    assert not (tmp_path / "www").exists()


async def test_endring_av_valg_laster_integrasjonen_paa_nytt(hass, hass_storage, tmp_path, freezer):
    entry = await _sett_opp(hass, tmp_path, freezer)
    forste = entry.runtime_data.coordinator
    hass.config_entries.async_update_entry(entry, options={"forfallsdag": 20})
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.coordinator is not forste
    assert entry.runtime_data.coordinator.cfg["forfallsdag"] == 20


async def test_leietaker_og_utleier_lagres_sammen_med_perioder(
    hass, hass_storage, tmp_path, freezer
):
    entry = await _sett_opp(hass, tmp_path, freezer)
    data = entry.runtime_data.lager.data
    assert data["leietaker"]["navn"] == "Kari Nordmann"
    assert data["utleier"]["kontonummer"] == "1234.56.78903"
