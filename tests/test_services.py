"""Tester for tjenestene (generer, godkjenn, send på nytt, status, publiser, slett, ny)."""

import json

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.stromregnskap_leietaker.const import DOMAIN
from custom_components.stromregnskap_leietaker.mail import SmtpFeil

from .data import NOV_HUS, OKT_HUS, SEP_HUS, sett_kilder


async def _kall(hass, tjeneste, data=None, **kw):
    return await hass.services.async_call(DOMAIN, tjeneste, data or {}, blocking=True, **kw)


def _lager(i):
    return i.entry.runtime_data.lager


async def test_alle_tjenester_er_registrert(hass, integrasjon):
    forventet = {
        "generer_oppgjor",
        "godkjenn_oppgjor",
        "send_epost_pa_nytt",
        "sett_status",
        "publiser_side",
        "slett_periode",
        "ny_leietaker",
        "send_lenke",
        "merk_betalt",
        "sett_malerstand",
        "send_regnskap",
        "send_faktura",
    }
    assert forventet <= set(hass.services.async_services()[DOMAIN])


async def test_generer_oppgjor_for_angitt_periode_uten_epost(hass, integrasjon):
    svar = await _kall(
        hass,
        "generer_oppgjor",
        {"periode": "2026-11", "send_epost": False},
        return_response=True,
    )
    p = _lager(integrasjon).finn("2026-11")
    assert p["belop"] == 310.0 and p["epost_sendt"] is None
    assert integrasjon.epost.call_count == 0
    assert svar == {"periode": "2026-11", "status": "ikke_betalt", "belop": 310.0}
    assert hass.states.get("sensor.leietaker_utestaende").state == "614.25"


async def test_generer_oppgjor_sender_epost_som_standard(hass, integrasjon):
    await _kall(hass, "generer_oppgjor", {"periode": "2026-11"})
    assert integrasjon.epost.call_count == 1


async def test_generer_oppgjor_uten_periode_bruker_forrige_maaned_som_allerede_finnes(
    hass, integrasjon
):
    with pytest.raises(ServiceValidationError):
        await _kall(hass, "generer_oppgjor")  # forrige måned = oktober, importert


async def test_generer_tving_overstyrer_rimelighetskontroll(hass, integrasjon):
    sett_kilder(
        hass,
        maneder=[SEP_HUS, OKT_HUS, {**NOV_HUS, "snitt": 3.5}],
        denne={"mnd": "2026-11", "snitt": 1.5, "leilighet_kr": 40.0},
        utility="30.25",
    )
    await _kall(hass, "generer_oppgjor", {"periode": "2026-11", "tving": True, "send_epost": False})
    assert _lager(integrasjon).finn("2026-11")["status"] == "ikke_betalt"


async def test_godkjenn_oppgjor_sender_ventende_periode(hass, integrasjon):
    sett_kilder(
        hass,
        maneder=[SEP_HUS, OKT_HUS, {**NOV_HUS, "snitt": 3.5}],
        denne={"mnd": "2026-11", "snitt": 1.5, "leilighet_kr": 40.0},
        utility="30.25",
    )
    await _kall(hass, "generer_oppgjor", {"periode": "2026-11"})
    assert _lager(integrasjon).finn("2026-11")["status"] == "venter_godkjenning"
    assert hass.states.get("binary_sensor.leietaker_oppgjor_venter_godkjenning").state == "on"
    await _kall(hass, "godkjenn_oppgjor", {"periode": "2026-11"})
    assert _lager(integrasjon).finn("2026-11")["status"] == "ikke_betalt"
    assert integrasjon.epost.call_count == 1
    assert hass.states.get("binary_sensor.leietaker_oppgjor_venter_godkjenning").state == "off"


async def test_send_epost_pa_nytt(hass, integrasjon):
    await _kall(hass, "send_epost_pa_nytt", {"periode": "2026-10"})
    assert integrasjon.epost.call_count == 1
    assert _lager(integrasjon).finn("2026-10")["epost_sendt"] is not None


async def test_send_epost_pa_nytt_feiler_med_tjenestefeil(hass, integrasjon):
    integrasjon.epost.side_effect = SmtpFeil("connect", "nede")
    with pytest.raises(HomeAssistantError):
        await _kall(hass, "send_epost_pa_nytt", {"periode": "2026-10"})


async def test_sett_status(hass, integrasjon):
    await _kall(hass, "sett_status", {"periode": "2026-10", "status": "betalt"})
    assert _lager(integrasjon).finn("2026-10")["status"] == "betalt"
    assert hass.states.get("sensor.leietaker_utestaende").state == "0.0"


async def test_sett_status_med_ugyldig_verdi_avvises_av_skjemaet(hass, integrasjon):
    with pytest.raises(vol.Invalid):
        await _kall(hass, "sett_status", {"periode": "2026-10", "status": "venter_godkjenning"})


async def test_publiser_side_skriver_filen_paa_nytt(hass, integrasjon):
    fil = integrasjon.tmp / "www" / "testslug123" / "index.html"
    fil.unlink()
    await _kall(hass, "publiser_side")
    assert "304,25" in fil.read_text(encoding="utf-8")


async def test_slett_periode_krever_bekreft(hass, integrasjon):
    with pytest.raises(ServiceValidationError):
        await _kall(hass, "slett_periode", {"periode": "2026-10", "bekreft": False})
    with pytest.raises(vol.Invalid):
        await _kall(hass, "slett_periode", {"periode": "2026-10"})  # bekreft er påkrevd
    await _kall(hass, "slett_periode", {"periode": "2026-10", "bekreft": True})
    assert _lager(integrasjon).finn("2026-10") is None


async def test_tjeneste_uten_oppsatt_integrasjon_gir_feil(hass, integrasjon):
    assert await hass.config_entries.async_unload(integrasjon.entry.entry_id)
    with pytest.raises(ServiceValidationError):
        await _kall(hass, "publiser_side")


async def test_ny_leietaker_arkiverer_tommer_bytter_lenke_og_starter_rekonfigurering(
    hass, integrasjon, hass_client_no_auth
):
    klient = await hass_client_no_auth()
    gammel_url = "/local/testslug123/index.html"
    assert (await klient.get(gammel_url)).status == 200

    svar = await _kall(hass, "ny_leietaker", return_response=True)
    await hass.async_block_till_done()

    # arkivfil med historikken
    arkiv = integrasjon.tmp / "stromregnskap_leietaker" / "arkiv"
    filer = list(arkiv.glob("*.json"))
    assert len(filer) == 1 and filer[0].name == "kari_nordmann_2026-11-10.json"
    innhold = json.loads(filer[0].read_text(encoding="utf-8"))
    assert [p["id"] for p in innhold["perioder"]] == ["2026-09", "2026-10"]
    assert innhold["leietaker"]["navn"] == "Kari Nordmann"
    assert svar["arkiv"] == str(filer[0])

    # historikk tømt, ny slug, gammel side borte
    assert _lager(integrasjon).perioder == []
    ny_slug = integrasjon.entry.data["slug"]
    assert ny_slug != "testslug123" and len(ny_slug) == 24
    assert svar["ny_lenke"] == f"https://eksempel.ui.nabu.casa/local/{ny_slug}/index.html"
    assert not (integrasjon.tmp / "www" / "testslug123").exists()
    assert (await klient.get(gammel_url)).status == 404
    assert (await klient.get(f"/local/{ny_slug}/index.html")).status == 200

    # reconfigure-flyt er åpnet
    flyter = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flyter] == [config_entries.SOURCE_RECONFIGURE]


async def test_ny_leietaker_overskriver_ikke_eksisterende_arkivfil(hass, integrasjon):
    await _kall(hass, "ny_leietaker", return_response=True)
    await hass.async_block_till_done()
    await _kall(hass, "ny_leietaker", return_response=True)
    await hass.async_block_till_done()
    filer = sorted(
        p.name for p in (integrasjon.tmp / "stromregnskap_leietaker" / "arkiv").glob("*.json")
    )
    assert filer == ["kari_nordmann_2026-11-10.json", "kari_nordmann_2026-11-10_2.json"]


async def test_send_lenke_tjenesten_sender_lenken_til_leietaker(hass, integrasjon):
    await _kall(hass, "send_lenke")
    assert integrasjon.epost.call_count == 1
    msg = integrasjon.epost.call_args.kwargs["melding"]
    assert "kari@example.com" in msg["To"]
    assert "/local/testslug123/index.html" in msg.get_body(("plain",)).get_content()


async def test_send_lenke_tjenesten_feiler_med_tjenestefeil_ved_smtp_feil(hass, integrasjon):
    integrasjon.epost.side_effect = SmtpFeil("auth", "avvist")
    with pytest.raises(HomeAssistantError):
        await _kall(hass, "send_lenke")


async def test_merk_betalt_tjenesten(hass, integrasjon):
    await _kall(hass, "merk_betalt")
    assert _lager(integrasjon).finn("2026-10")["status"] == "betalt"
    assert hass.states.get("sensor.leietaker_utestaende").state == "0.0"
    with pytest.raises(ServiceValidationError):
        await _kall(hass, "merk_betalt")  # ingenting utestående lenger


async def test_merk_betalt_tjenesten_med_periode(hass, integrasjon):
    await _kall(hass, "merk_betalt", {"periode": "2026-10"})
    assert _lager(integrasjon).finn("2026-10")["status"] == "betalt"


async def test_sett_malerstand_tjenesten_lagrer_manuell_avlesning(hass, integrasjon):
    await _kall(hass, "sett_malerstand", {"dato": "2026-12", "stand": 251.2})
    rad = _lager(integrasjon).data["maalerstander"]["2026-12-01"]
    assert rad["stand"] == 251.2 and rad["kilde"] == "manuell"
    assert "251.2" in str(hass.states.get("binary_sensor.leietaker_datagrunnlag").attributes)


async def test_sett_malerstand_tjenesten_avviser_ugyldig_dato_og_stand(hass, integrasjon):
    with pytest.raises(ServiceValidationError):
        await _kall(hass, "sett_malerstand", {"dato": "2026-12-15", "stand": 1})
    with pytest.raises(vol.Invalid):
        await _kall(hass, "sett_malerstand", {"dato": "2026-12-01"})  # stand mangler


async def test_send_regnskap_tjenesten_sender_kopi_med_pdf_og_sikkerhetskopi(hass, integrasjon):
    await _kall(hass, "send_regnskap")
    msg = integrasjon.epost.call_args.kwargs["melding"]
    assert "ola@example.com" in msg["To"] and msg["Subject"].startswith("Fakturagrunnlag strøm")
    assert len(list(msg.iter_attachments())) == 3


async def test_send_regnskap_tjenesten_med_periode_og_feil(hass, integrasjon):
    await _kall(hass, "send_regnskap", {"periode": "2026-09"})
    assert "september 2026" in integrasjon.epost.call_args.kwargs["melding"]["Subject"]
    with pytest.raises(ServiceValidationError):
        await _kall(hass, "send_regnskap", {"periode": "2099-01"})
    integrasjon.epost.side_effect = SmtpFeil("connect", "nede")
    with pytest.raises(HomeAssistantError):
        await _kall(hass, "send_regnskap")
