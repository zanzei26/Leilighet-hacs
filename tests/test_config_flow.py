"""Tester for oppsettsflyt, valgflyt og rekonfigurering."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.stromregnskap_leietaker.const import DOMAIN
from custom_components.stromregnskap_leietaker.mail import SmtpFeil

from .data import CFG

STEG_LEIETAKER = {
    "leietaker_navn": "Kari Nordmann",
    "leietaker_epost": "kari@example.com",
    "adresse": "Testveien 1, 1. etasje",
    "innflyttet": "2026-08-30",
    "utleier_navn": "Ola Utleier",
    "utleier_epost": "ola@example.com",
    "kontonummer": "1234.56.78903",
    "forfallsdag": 15,
}
STEG_KILDER = {
    "ent_regnskap": "sensor.jarvis_stromregnskap",
    "ent_utility": "sensor.leilighet_strom_denne_maneden",
    "ent_import": "sensor.minusmaler_leilighet_import",
    "ent_effekt": "sensor.minusmaler_leilighet_effekt",
    "ent_prognose": "sensor.mal_forbruk_prognose",
    "varsel_tjeneste": "notify.varsle_magnar",
}
STEG_EPOST = {
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_bruker": "ola@example.com",
    "smtp_passord": "app-passord-test",
    "cc_utleier": True,
    "send_test": True,
}
STEG_GRENSER = {
    "snitt_min": 0.5,
    "snitt_maks": 3.0,
    "endring_maks_prosent": 60,
    "kjoredag": 3,
    "kjoretid": "08:00:00",
    "siste_sjekkdag": 6,
}


@pytest.fixture(autouse=True)
def varseltjeneste(hass):
    async_mock_service(hass, "notify", "varsle_magnar")


@pytest.fixture
def smtp():
    with patch("custom_components.stromregnskap_leietaker.config_flow.sjekk_smtp") as m:
        yield m


@pytest.fixture(autouse=True)
def ikke_sett_opp():
    with patch(
        "custom_components.stromregnskap_leietaker.async_setup_entry", return_value=True
    ) as m:
        yield m


async def _start(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def _til_epost(hass):
    r = await _start(hass)
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "user"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], STEG_LEIETAKER)
    assert r["step_id"] == "kilder"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], STEG_KILDER)
    assert r["step_id"] == "epost"
    return r


async def test_hele_flyten_lager_entry_med_alle_valg(hass, smtp):
    hass.config.external_url = "https://eksempel.ui.nabu.casa"
    r = await _til_epost(hass)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], STEG_EPOST)
    assert r["step_id"] == "side"
    lenke = r["description_placeholders"]["lenke"]
    assert lenke.startswith("https://eksempel.ui.nabu.casa/local/")
    assert lenke.endswith("/index.html")
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"publiser_side": True})
    assert r["step_id"] == "grenser"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], STEG_GRENSER)
    assert r["step_id"] == "importer"
    assert "2026-09" in r["description_placeholders"]["historikk"]
    assert "304,25" in r["description_placeholders"]["historikk"]
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"importer_historikk": True})

    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["title"] == "Strømregnskap leietaker"
    d = r["data"]
    assert d["leietaker_navn"] == "Kari Nordmann" and d["forfallsdag"] == 15
    assert d["smtp_passord"] == "app-passord-test"
    assert "send_test" not in d
    assert d["importer_historikk"] is True and d["publiser_side"] is True
    assert len(d["slug"]) == 24 and d["slug"] in lenke
    assert d["kjoretid"] == "08:00:00" and d["kjoredag"] == 3 and d["siste_sjekkdag"] == 6
    assert d["ent_prognose"] == "sensor.mal_forbruk_prognose"
    assert isinstance(d["smtp_port"], int) and isinstance(d["kjoredag"], int)


async def test_testepost_sendes_til_utleier_naar_valgt(hass, smtp):
    r = await _til_epost(hass)
    await hass.config_entries.flow.async_configure(r["flow_id"], STEG_EPOST)
    kall = smtp.call_args.kwargs
    assert kall["brukernavn"] == "ola@example.com" and kall["passord"] == "app-passord-test"
    assert "ola@example.com" in kall["testmelding"]["To"]


async def test_uten_testepost_sjekkes_bare_innlogging(hass, smtp):
    r = await _til_epost(hass)
    await hass.config_entries.flow.async_configure(r["flow_id"], {**STEG_EPOST, "send_test": False})
    assert smtp.call_args.kwargs["testmelding"] is None


@pytest.mark.parametrize(
    ("kind", "feil"),
    [("auth", "smtp_auth"), ("connect", "smtp_connect"), ("send", "smtp_send")],
)
async def test_smtp_feil_gir_skjemafeil_og_man_kan_prove_igjen(hass, smtp, kind, feil):
    r = await _til_epost(hass)
    smtp.side_effect = SmtpFeil(kind, "x")
    r = await hass.config_entries.flow.async_configure(r["flow_id"], STEG_EPOST)
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "epost"
    assert r["errors"] == {"base": feil}
    smtp.side_effect = None
    r = await hass.config_entries.flow.async_configure(r["flow_id"], STEG_EPOST)
    assert r["step_id"] == "side"


async def test_ukjent_varseltjeneste_gir_feil(hass, smtp):
    r = await _start(hass)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], STEG_LEIETAKER)
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {**STEG_KILDER, "varsel_tjeneste": "notify.finnes_ikke"}
    )
    assert r["step_id"] == "kilder" and r["errors"] == {"varsel_tjeneste": "tjeneste_finnes_ikke"}


async def test_ugyldig_epostadresse_gir_feil(hass, smtp):
    r = await _start(hass)
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {**STEG_LEIETAKER, "leietaker_epost": "ikke-en-epost"}
    )
    assert r["step_id"] == "user" and r["errors"] == {"leietaker_epost": "ugyldig_epost"}


async def test_ugyldige_grenser_gir_feil(hass, smtp):
    r = await _til_epost(hass)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], STEG_EPOST)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"publiser_side": True})
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {**STEG_GRENSER, "snitt_min": 3.0, "snitt_maks": 1.0}
    )
    assert r["step_id"] == "grenser" and r["errors"] == {"snitt_maks": "snitt_grense"}
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {**STEG_GRENSER, "kjoredag": 7, "siste_sjekkdag": 6}
    )
    assert r["errors"] == {"siste_sjekkdag": "kjoredag_rekkefolge"}


async def test_kun_en_instans(hass, smtp):
    MockConfigEntry(domain=DOMAIN, data=dict(CFG)).add_to_hass(hass)
    r = await _start(hass)
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "single_instance_allowed"


# --- valgflyt -------------------------------------------------------------------


async def _entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=dict(CFG), entry_id="e1")
    entry.add_to_hass(hass)
    return entry


async def test_valgflyt_viser_meny(hass, smtp):
    entry = await _entry(hass)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["type"] is FlowResultType.MENU
    assert set(r["menu_options"]) == {"leietaker", "kilder", "epost", "side", "grenser"}


async def test_valgflyt_endrer_grenser_i_entry_data(hass, smtp):
    entry = await _entry(hass)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "grenser"})
    assert r["step_id"] == "grenser"
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {**STEG_GRENSER, "snitt_maks": 4.0, "kjoredag": 4}
    )
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data["snitt_maks"] == 4.0 and entry.data["kjoredag"] == 4
    assert entry.data["slug"] == CFG["slug"]  # øvrige verdier urørt


async def test_valgflyt_tomt_passord_beholder_gammelt_og_bytte_virker(hass, smtp):
    entry = await _entry(hass)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "epost"})
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {**STEG_EPOST, "smtp_passord": "", "send_test": False}
    )
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data["smtp_passord"] == "app-passord-test"
    assert smtp.call_args.kwargs["passord"] == "app-passord-test"

    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "epost"})
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {**STEG_EPOST, "smtp_passord": "nytt-passord", "send_test": False}
    )
    assert entry.data["smtp_passord"] == "nytt-passord"


async def test_valgflyt_feil_passord_gir_feil_og_endrer_ingenting(hass, smtp):
    entry = await _entry(hass)
    smtp.side_effect = SmtpFeil("auth", "x")
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "epost"})
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {**STEG_EPOST, "smtp_passord": "feil", "send_test": False}
    )
    assert r["errors"] == {"base": "smtp_auth"}
    assert entry.data["smtp_passord"] == "app-passord-test"


async def test_valgflyt_side_viser_lenken_og_kan_skru_av_publisering(hass, smtp):
    hass.config.external_url = "https://eksempel.ui.nabu.casa"
    entry = await _entry(hass)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "side"})
    assert r["description_placeholders"]["lenke"] == (
        "https://eksempel.ui.nabu.casa/local/testslug123/index.html"
    )
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"publiser_side": False})
    assert entry.data["publiser_side"] is False


# --- rekonfigurering --------------------------------------------------------------


async def test_rekonfigurering_oppdaterer_leietakerdata(hass, smtp):
    entry = await _entry(hass)
    r = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "reconfigure"
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"],
        {
            "leietaker_navn": "Per Hansen",
            "leietaker_epost": "per@example.com",
            "adresse": "Testveien 1, 1. etasje",
            "innflyttet": "2027-09-01",
        },
    )
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "reconfigure_successful"
    assert entry.data["leietaker_navn"] == "Per Hansen"
    assert entry.data["innflyttet"] == "2027-09-01"
    assert entry.data["kontonummer"] == "1234.56.78903"  # utleierdata urørt


@pytest.mark.parametrize("felt", ["leietaker_navn", "adresse", "utleier_navn", "kontonummer"])
async def test_tomme_obligatoriske_felt_avvises(hass, smtp, felt):
    r = await _start(hass)
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {**STEG_LEIETAKER, felt: "   "}
    )
    assert r["step_id"] == "user" and r["errors"] == {felt: "paakrevd"}
