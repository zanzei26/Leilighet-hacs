"""Tester for oppsett/nedlasting, sensorer og den uautentiserte leietakersiden."""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
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
    async_mock_service(hass, "notify", "varsle_utleier")
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
    assert hass.states.get("sensor.leietaker_forbruk_hittil").state == "30.3"
    assert hass.states.get("sensor.leietaker_kostnad_hittil").state == "45.45"
    estimat = hass.states.get("sensor.leietaker_estimat_maned")
    assert estimat.state == "124.41"  # takt: 30,3 kWh etter 228 av 720 timer
    assert estimat.attributes["estimat_kwh"] == 95.68
    assert estimat.attributes["estimat_metode"] == "takt"
    hittil = hass.states.get("sensor.leietaker_forbruk_hittil")
    assert hittil.attributes["estimat_metode"] == "takt"
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
    hass, hass_storage, http_klient, tmp_path, freezer
):
    klient = http_klient
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


async def test_feil_slug_gir_404(hass, hass_storage, http_klient, tmp_path, freezer):
    klient = http_klient
    await _sett_opp(hass, tmp_path, freezer)
    assert (await klient.get("/local/annen-slug/index.html")).status == 404


async def test_siden_forsvinner_ved_nedlasting_og_kommer_tilbake_ved_ny_innlasting(
    hass, hass_storage, http_klient, tmp_path, freezer
):
    klient = http_klient
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
    hass, hass_storage, http_klient, tmp_path, freezer
):
    klient = http_klient
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


async def test_lenken_er_en_egen_sensor_og_en_knapp_sender_den(
    hass, hass_storage, tmp_path, freezer
):
    from unittest.mock import patch as _patch

    with _patch("custom_components.stromregnskap_leietaker.epost.send_epost") as epost:
        await _sett_opp(hass, tmp_path, freezer)
        lenke = hass.states.get("sensor.leietaker_lenke")
        assert lenke.state == "https://eksempel.ui.nabu.casa/local/testslug123/index.html"
        assert hass.states.get("button.leietaker_send_lenke") is not None
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.leietaker_send_lenke"}, blocking=True
        )
        assert epost.call_count == 1
        assert "kari@example.com" in epost.call_args.kwargs["melding"]["To"]


async def test_lenke_sensoren_er_ukjent_naar_siden_ikke_publiseres(
    hass, hass_storage, tmp_path, freezer
):
    await _sett_opp(hass, tmp_path, freezer, publiser_side=False)
    assert hass.states.get("sensor.leietaker_lenke").state == "unknown"


async def test_entitetene_samles_paa_en_enhet_og_navnene_dobles_ikke(
    hass, hass_storage, tmp_path, freezer
):
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    entry = await _sett_opp(hass, tmp_path, freezer)
    ent = er.async_get(hass)
    ider = {e.entity_id for e in er.async_entries_for_config_entry(ent, entry.entry_id)}
    assert ider == {
        "sensor.leietaker_utestaende",
        "sensor.leietaker_siste_oppgjor",
        "sensor.leietaker_forbruk_hittil",
        "sensor.leietaker_kostnad_hittil",
        "sensor.leietaker_estimat_maned",
        "sensor.leietaker_side_sist_publisert",
        "sensor.leietaker_lenke",
        "binary_sensor.leietaker_oppgjor_venter_godkjenning",
        "binary_sensor.leietaker_datagrunnlag",
        "button.leietaker_send_lenke",
        "button.leietaker_merk_som_betalt",
        "button.leietaker_send_regnskap",
    }
    assert hass.states.get("sensor.leietaker_utestaende").name == "Leietaker Utestående"
    assert hass.states.get("button.leietaker_send_lenke").name == "Leietaker Send lenke"
    enheter = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(enheter) == 1 and enheter[0].name == "Leietaker"


async def test_knappen_merk_som_betalt_oppdaterer_utestaaende(
    hass, hass_storage, tmp_path, freezer
):
    await _sett_opp(hass, tmp_path, freezer)
    assert hass.states.get("sensor.leietaker_utestaende").state == "304.25"
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.leietaker_merk_som_betalt"}, blocking=True
    )
    assert hass.states.get("sensor.leietaker_utestaende").state == "0.0"


async def test_knappen_send_regnskap_sender_kopi_til_utleier(hass, hass_storage, tmp_path, freezer):
    from unittest.mock import patch as _patch

    with _patch("custom_components.stromregnskap_leietaker.epost.send_epost") as epost:
        await _sett_opp(hass, tmp_path, freezer)
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.leietaker_send_regnskap"}, blocking=True
        )
        assert epost.call_count == 1
        assert "ola@example.com" in epost.call_args.kwargs["melding"]["To"]


async def test_lenkesensoren_har_lenker_til_pdf_ene_som_attributter(
    hass, hass_storage, tmp_path, freezer
):
    await _sett_opp(hass, tmp_path, freezer)
    a = hass.states.get("sensor.leietaker_lenke").attributes
    base = "https://eksempel.ui.nabu.casa/stromregnskap/testslug123"
    assert a["regnskap_pdf"] == f"{base}/regnskap-strom-leilighet.pdf"
    assert a["siste_faktura_pdf"] == f"{base}/fakturagrunnlag-strom-leilighet-2026-10.pdf"
