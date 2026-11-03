"""Tester for koordinatoren: månedsoppgjør, varsler, e-postforsøk og side."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir

from custom_components.stromregnskap_leietaker.const import DOMAIN
from custom_components.stromregnskap_leietaker.mail import SmtpFeil

from .data import DENNE_DES, NOV_HUS, OKT_HUS, SEP_HUS, sett_kilder


def _side(o):
    return (o.tmp / "www" / "testslug123" / "index.html").read_text(encoding="utf-8")


def _issue(hass, issue_id):
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


def _meldinger(o):
    return [c.data["message"] for c in o.varsler]


# --- vellykket oppgjør ---------------------------------------------------------


async def test_foerste_sjekk_i_vinduet_genererer_lagrer_og_sender(hass, oppsett):
    o = oppsett
    await o.coordinator.async_refresh()

    p = o.lager.finn("2026-11")
    assert p["status"] == "ikke_betalt"
    assert p["leilighet_kwh"] == 250.0
    assert p["belop"] == 310.0  # 250,0 × 1,24
    assert p["forfall"] == "2026-12-15"
    assert p["epost_sendt"] is not None
    assert p["epost_ventende_siden"] is None

    assert o.epost.call_count == 1
    kall = o.epost.call_args.kwargs
    assert kall["host"] == "smtp.gmail.com" and kall["port"] == 587
    assert kall["passord"] == "app-passord-test"
    msg = kall["melding"]
    assert "kari@example.com" in msg["To"]
    assert "310,00 kr" in msg.get_body(("plain",)).get_content()
    assert "https://eksempel.ui.nabu.casa/local/testslug123/index.html" in str(msg)

    assert _meldinger(o) == ["Oppgjør 2026-11 sendt: 250,0 kWh × 1,2400 = 310,00 kr"]
    assert "november 2026" in _side(o)


async def test_ingen_generering_for_kjoretidspunktet(hass, oppsett):
    oppsett.freezer.move_to("2026-12-03 07:59:00+01:00")
    await oppsett.coordinator.async_refresh()
    assert oppsett.lager.finn("2026-11") is None
    assert oppsett.epost.call_count == 0


async def test_ingen_generering_etter_sjekkvinduet(hass, oppsett):
    oppsett.freezer.move_to("2026-12-07 08:30:00+01:00")
    await oppsett.coordinator.async_refresh()
    assert oppsett.lager.finn("2026-11") is None


async def test_allerede_generert_gjor_ingenting(hass, oppsett):
    await oppsett.coordinator.async_refresh()
    oppsett.freezer.tick(timedelta(hours=1))
    await oppsett.coordinator.async_refresh()
    assert oppsett.epost.call_count == 1
    assert len(oppsett.varsler) == 1


# --- manglende data ----------------------------------------------------------------


async def test_mangler_data_varsler_foerst_paa_siste_sjekkdag_og_bare_en_gang(hass, oppsett):
    o = oppsett
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS])  # november mangler
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11") is None and o.varsler == []

    o.freezer.move_to("2026-12-05 23:00:00+01:00")
    await o.coordinator.async_refresh()
    assert o.varsler == []

    o.freezer.move_to("2026-12-06 08:30:00+01:00")
    await o.coordinator.async_refresh()
    assert len(o.varsler) == 1
    assert "2026-11" in o.varsler[0].data["message"]
    assert _issue(hass, "mangler_data_2026-11") is not None

    o.freezer.tick(timedelta(hours=1))
    await o.coordinator.async_refresh()
    assert len(o.varsler) == 1  # ikke gjentatt


async def test_data_som_kommer_senere_lager_oppgjor_og_fjerner_issue(hass, oppsett):
    o = oppsett
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS])
    o.freezer.move_to("2026-12-06 08:30:00+01:00")
    await o.coordinator.async_refresh()
    assert _issue(hass, "mangler_data_2026-11") is not None

    sett_kilder(hass)  # nå er november med
    o.freezer.tick(timedelta(hours=1))
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11")["status"] == "ikke_betalt"
    assert _issue(hass, "mangler_data_2026-11") is None


# --- kilder til leilighetens kWh -------------------------------------------------------


async def test_avvik_mellom_kilder_gir_venter_godkjenning_med_begge_tall(hass, oppsett):
    o = oppsett
    sett_kilder(hass, last_period="252.0")
    await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p["status"] == "venter_godkjenning"
    assert "250,0" in p["notat"] and "252,0" in p["notat"]
    assert o.epost.call_count == 0
    assert "250,0" in _meldinger(o)[0] and "252,0" in _meldinger(o)[0]


async def test_last_period_brukes_naar_maned_mangler_leilighet_kwh(hass, oppsett):
    o = oppsett
    uten = {k: v for k, v in NOV_HUS.items() if k not in ("leilighet_kwh", "leilighet_kr")}
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, uten], last_period="248.0")
    o.lager.data["maalerstander"]["2026-12-01"]["stand"] = 248.0  # målerstandene stemmer med den
    await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p["leilighet_kwh"] == 248.0
    assert "last_period" in p["kilde"]
    assert p["status"] == "ikke_betalt"


async def test_ingen_kilde_for_leilighetens_kwh_regnes_som_manglende_data(hass, oppsett):
    o = oppsett
    uten = {k: v for k, v in NOV_HUS.items() if k not in ("leilighet_kwh", "leilighet_kr")}
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, uten], last_period="unavailable")
    o.lager.data["maalerstander"] = {}  # og ingen målerstander heller: ingen kilde i det hele tatt
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11") is None


# --- rimelighetskontroll og godkjenning ------------------------------------------------


async def test_rimelighetsbrudd_gir_venter_godkjenning_varsel_og_repairs(hass, oppsett):
    o = oppsett
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, {**NOV_HUS, "snitt": 3.5}])
    await o.coordinator.async_refresh()

    p = o.lager.finn("2026-11")
    assert p["status"] == "venter_godkjenning"
    assert "Snittprisen" in p["notat"]
    assert o.epost.call_count == 0
    assert "Snittprisen" in _meldinger(o)[0]
    issue = _issue(hass, "venter_godkjenning_2026-11")
    assert issue.is_fixable is True
    assert o.coordinator.data["venter"] == ["2026-11"]
    assert "november 2026" not in _side(o)  # ikke publisert som oppgjør


async def test_godkjenning_sender_epost_publiserer_og_fjerner_issue(hass, oppsett):
    o = oppsett
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, {**NOV_HUS, "snitt": 3.5}])
    await o.coordinator.async_refresh()

    await o.coordinator.async_godkjenn_oppgjor("2026-11")
    p = o.lager.finn("2026-11")
    assert p["status"] == "ikke_betalt"
    assert p["epost_sendt"] is not None
    assert o.epost.call_count == 1
    assert _issue(hass, "venter_godkjenning_2026-11") is None
    assert "november 2026" in _side(o)
    assert o.coordinator.data["venter"] == []


async def test_godkjenning_av_periode_som_ikke_venter_avvises(hass, oppsett):
    with pytest.raises(ServiceValidationError):
        await oppsett.coordinator.async_godkjenn_oppgjor("2026-10")
    with pytest.raises(ServiceValidationError):
        await oppsett.coordinator.async_godkjenn_oppgjor("2099-01")


async def test_venter_godkjenning_varsler_ikke_paa_nytt_hver_time(hass, oppsett):
    o = oppsett
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, {**NOV_HUS, "snitt": 3.5}])
    await o.coordinator.async_refresh()
    o.freezer.tick(timedelta(hours=1))
    await o.coordinator.async_refresh()
    assert len(o.varsler) == 1


# --- e-postfeil -------------------------------------------------------------------------


async def test_epostfeil_beholder_perioden_varsler_og_proever_igjen_neste_time(hass, oppsett):
    o = oppsett
    o.epost.side_effect = SmtpFeil("connect", "nede")
    await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p["epost_sendt"] is None
    assert p["epost_ventende_siden"] is not None
    assert len(o.varsler) == 1 and "feilet" in o.varsler[0].data["message"].lower()

    o.epost.side_effect = None
    o.freezer.tick(timedelta(hours=1))
    await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p["epost_sendt"] is not None and p["epost_ventende_siden"] is None
    assert o.epost.call_count == 2
    assert "sendt" in _meldinger(o)[-1]


async def test_epostfeil_varsler_bare_en_gang_selv_om_det_prøves_flere_ganger(hass, oppsett):
    o = oppsett
    o.epost.side_effect = SmtpFeil("connect", "nede")
    await o.coordinator.async_refresh()
    for _ in range(3):
        o.freezer.tick(timedelta(hours=1))
        await o.coordinator.async_refresh()
    assert o.epost.call_count == 4
    assert len(o.varsler) == 1


async def test_epostfeil_i_48_timer_gir_repairs_og_stopper_automatiske_forsoek(hass, oppsett):
    o = oppsett
    o.epost.side_effect = SmtpFeil("auth", "avvist")
    await o.coordinator.async_refresh()
    assert _issue(hass, "epost_feilet_2026-11") is None

    o.freezer.move_to("2026-12-05 08:31:00+01:00")  # 48 t og 1 min senere
    await o.coordinator.async_refresh()
    assert o.epost.call_count == 1  # ingen nytt forsøk
    assert _issue(hass, "epost_feilet_2026-11") is not None


async def test_send_epost_pa_nytt_etter_repairs_nullstiller_og_fjerner_issue(hass, oppsett):
    o = oppsett
    o.epost.side_effect = SmtpFeil("auth", "avvist")
    await o.coordinator.async_refresh()
    o.freezer.move_to("2026-12-05 09:00:00+01:00")
    await o.coordinator.async_refresh()
    assert _issue(hass, "epost_feilet_2026-11") is not None

    o.epost.side_effect = None
    await o.coordinator.async_send_epost_pa_nytt("2026-11")
    assert o.lager.finn("2026-11")["epost_sendt"] is not None
    assert _issue(hass, "epost_feilet_2026-11") is None


async def test_send_epost_pa_nytt_som_feiler_gir_tjenestefeil(hass, oppsett):
    o = oppsett
    o.epost.side_effect = SmtpFeil("connect", "nede")
    with pytest.raises(HomeAssistantError) as exc:
        await o.coordinator.async_send_epost_pa_nytt("2026-10")
    assert not isinstance(exc.value, ServiceValidationError)  # kjøretidsfeil, ikke ugyldig input


# --- manuell generering -------------------------------------------------------------------


async def test_generer_uten_epost_sender_ikke_og_proever_ikke_igjen(hass, oppsett):
    o = oppsett
    p = await o.coordinator.async_generer_oppgjor("2026-11", send_epost=False)
    assert p["epost_sendt"] is None and p["epost_ventende_siden"] is None
    o.freezer.tick(timedelta(hours=1))
    await o.coordinator.async_refresh()
    assert o.epost.call_count == 0


async def test_generer_tving_hopper_over_rimelighetskontrollen(hass, oppsett):
    o = oppsett
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, {**NOV_HUS, "snitt": 3.5}])
    p = await o.coordinator.async_generer_oppgjor("2026-11", tving=True)
    assert p["status"] == "ikke_betalt"
    assert o.epost.call_count == 1


async def test_generer_for_eksisterende_periode_avvises(hass, oppsett):
    with pytest.raises(ServiceValidationError):
        await oppsett.coordinator.async_generer_oppgjor("2026-10")


async def test_generer_med_ugyldig_periodeformat_avvises(hass, oppsett):
    with pytest.raises(ServiceValidationError):
        await oppsett.coordinator.async_generer_oppgjor("november")


async def test_generer_uten_data_gir_tjenestefeil(hass, oppsett):
    with pytest.raises(ServiceValidationError):
        await oppsett.coordinator.async_generer_oppgjor("2026-08")


async def test_feil_i_varseltjenesten_stopper_ikke_oppgjoeret(hass, oppsett):
    o = oppsett
    hass.services.async_remove("notify", "varsle_magnar")
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11")["epost_sendt"] is not None


# --- status, sletting -----------------------------------------------------------------------


async def test_ikke_betalt_blir_betalt_paa_forfallsdagen_men_unntak_blir_ikke(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-11-14 23:00:00+01:00")
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-10")["status"] == "ikke_betalt"
    o.freezer.move_to("2026-11-15 00:30:00+01:00")
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-10")["status"] == "betalt"
    assert o.coordinator.data["utestaaende"] == 0.0


async def test_unntak_forblir_ikke_betalt(hass, oppsett):
    o = oppsett
    await o.coordinator.async_sett_status("2026-10", "unntak_ikke_betalt")
    o.freezer.move_to("2027-01-20 12:00:00+01:00")
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-10")["status"] == "unntak_ikke_betalt"
    assert o.coordinator.data["utestaaende"] == 304.25


async def test_sett_status_validerer_og_oppdaterer_siden(hass, oppsett):
    o = oppsett
    await o.coordinator.async_sett_status("2026-10", "betalt")
    assert o.lager.finn("2026-10")["status"] == "betalt"
    with pytest.raises(ServiceValidationError):
        await o.coordinator.async_sett_status("2026-10", "oppfunnet")
    with pytest.raises(ServiceValidationError):
        await o.coordinator.async_sett_status("2099-01", "betalt")


async def test_slett_periode_krever_bekreftelse_og_rydder_varsler_og_issues(hass, oppsett):
    o = oppsett
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, {**NOV_HUS, "snitt": 3.5}])
    await o.coordinator.async_refresh()
    assert "venter_godkjenning:2026-11" in o.lager.tilstand["varslet"]
    assert _issue(hass, "venter_godkjenning_2026-11") is not None

    with pytest.raises(ServiceValidationError):
        await o.coordinator.async_slett_periode("2026-11", bekreft=False)
    assert o.lager.finn("2026-11") is not None

    await o.coordinator.async_slett_periode("2026-11", bekreft=True)
    assert o.lager.finn("2026-11") is None
    assert "venter_godkjenning:2026-11" not in o.lager.tilstand["varslet"]
    assert _issue(hass, "venter_godkjenning_2026-11") is None
    with pytest.raises(ServiceValidationError):
        await o.coordinator.async_slett_periode("2026-11", bekreft=True)


# --- data til sensorene og siden -------------------------------------------------------


async def test_data_for_sensorer_med_hittil_og_estimat(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-11-10 12:00:00+01:00")  # før oktober forfaller 15.11.
    sett_kilder(hass, denne={**DENNE_DES, "mnd": "2026-11", "snitt": 1.5, "leilighet_kr": 40.0},
                utility="30.25")  # fmt: skip
    await o.coordinator.async_refresh()
    d = o.coordinator.data
    assert d["utestaaende"] == 304.25
    assert d["antall_utestaaende"] == 1
    assert d["siste"]["id"] == "2026-10"
    assert d["kwh_hittil"] == 30.25
    assert d["snitt_hittil"] == 1.5 and d["kostnad_hittil"] == 40.0
    assert d["estimat_kwh"] == pytest.approx(285.48)  # 234,0 × 1,22
    assert d["estimat_kr"] == 371.18  # × forrige snittpris 1,3002
    assert d["effekt_w"] == 850.0
    assert d["import_kwh"] == 30.25
    assert d["side_url"] == "https://eksempel.ui.nabu.casa/local/testslug123/index.html"


async def test_hittil_fra_forrige_maned_vises_ikke_som_denne_maneden(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-12-01 03:00:00+01:00")  # sensoren viser fortsatt november
    sett_kilder(hass, denne={**DENNE_DES, "mnd": "2026-11"}, utility="0.4")
    await o.coordinator.async_refresh()
    assert o.coordinator.data["kwh_hittil"] == 0.4
    assert o.coordinator.data["snitt_hittil"] is None
    assert o.coordinator.data["kostnad_hittil"] is None


async def test_estimat_mangler_uten_prognose(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-11-20 12:00:00+01:00")
    hass.states.async_set("sensor.mal_forbruk_prognose", "unavailable", {})
    await o.coordinator.async_refresh()
    assert o.coordinator.data["estimat_kwh"] is None
    assert o.coordinator.data["estimat_kr"] is None


async def test_siden_skrives_hver_time_med_hittil_tall(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-11-20 12:00:00+01:00")
    sett_kilder(hass, denne={**DENNE_DES, "mnd": "2026-11", "snitt": 1.5, "leilighet_kr": 40.0},
                utility="30.25")  # fmt: skip
    await o.coordinator.async_refresh()
    html = _side(o)
    assert "30,3 kWh" in html and "1,5000" in html and "40,00 kr" in html
    assert "20.11.2026 12:00" in html
    o.freezer.tick(timedelta(hours=1))
    await o.coordinator.async_refresh()
    assert "20.11.2026 13:00" in _side(o)


async def test_ingen_side_naar_publisering_er_av(hass, oppsett):
    o = oppsett
    hass.config_entries.async_update_entry(o.entry, data={**o.entry.data, "publiser_side": False})
    await o.coordinator.async_refresh()
    assert not (o.tmp / "www").exists()


async def test_side_url_bruker_cloud_foerst_og_faller_tilbake_til_ekstern_url(hass, oppsett):
    o = oppsett
    with patch(
        "custom_components.stromregnskap_leietaker.url.cloud_url",
        return_value="https://abc.ui.nabu.casa",
    ):
        assert o.coordinator.side_url == "https://abc.ui.nabu.casa/local/testslug123/index.html"
    with patch("custom_components.stromregnskap_leietaker.url.cloud_url", return_value=None):
        assert (
            o.coordinator.side_url == "https://eksempel.ui.nabu.casa/local/testslug123/index.html"
        )
        hass.config.external_url = None
        hass.config.internal_url = None
        assert o.coordinator.side_url is None


# --- lenken til leietaker -----------------------------------------------------------

LENKE = "https://eksempel.ui.nabu.casa/local/testslug123/index.html"


async def test_send_lenke_sender_kort_epost_til_leietaker_og_varsler_utleier(hass, oppsett):
    o = oppsett
    await o.coordinator.async_send_lenke()
    assert o.epost.call_count == 1
    msg = o.epost.call_args.kwargs["melding"]
    assert "kari@example.com" in msg["To"] and msg["Subject"].startswith("Din side")
    assert LENKE in msg.get_body(("plain",)).get_content()
    assert any("Lenke sendt" in c.data["title"] for c in o.varsler)


async def test_send_lenke_uten_kjent_adresse_gir_valideringsfeil(hass, oppsett):
    o = oppsett
    hass.config.external_url = None
    hass.config.internal_url = None
    with pytest.raises(ServiceValidationError):
        await o.coordinator.async_send_lenke()
    assert o.epost.call_count == 0


async def test_send_lenke_naar_siden_er_slaatt_av_gir_valideringsfeil(hass, oppsett):
    o = oppsett
    hass.config_entries.async_update_entry(o.entry, data={**o.entry.data, "publiser_side": False})
    with pytest.raises(ServiceValidationError):
        await o.coordinator.async_send_lenke()
    assert o.epost.call_count == 0


async def test_send_lenke_som_feiler_gir_kjoretidsfeil_ikke_valideringsfeil(hass, oppsett):
    o = oppsett
    o.epost.side_effect = SmtpFeil("connect", "nede")
    with pytest.raises(HomeAssistantError) as exc:
        await o.coordinator.async_send_lenke()
    assert not isinstance(exc.value, ServiceValidationError)


async def test_uten_publisert_side_finnes_ingen_lenke_og_oppgjoeret_sendes_uten(hass, oppsett):
    o = oppsett
    hass.config_entries.async_update_entry(o.entry, data={**o.entry.data, "publiser_side": False})
    assert o.coordinator.side_url is None
    await o.coordinator.async_refresh()  # 3. desember: lager og sender oppgjøret
    tekst = o.epost.call_args.kwargs["melding"].get_body(("plain",)).get_content()
    assert "testslug123" not in tekst and "310,00 kr" in tekst
    assert o.coordinator.data["side_url"] is None


# --- merk utestående som betalt -------------------------------------------------------


async def test_merk_betalt_uten_periode_merker_alt_utestaaende(hass, oppsett):
    o = oppsett
    o.lager.finn("2026-09")["status"] = "unntak_ikke_betalt"  # også unntak regnes som utestående
    merket = await o.coordinator.async_merk_betalt()
    assert merket == ["2026-09", "2026-10"]
    assert {p["status"] for p in o.lager.perioder} == {"betalt"}
    assert o.coordinator.data["utestaaende"] == 0.0
    assert "Betalt" in _side(o)


async def test_merk_betalt_for_en_bestemt_periode_roerer_ikke_de_andre(hass, oppsett):
    o = oppsett
    o.lager.finn("2026-09")["status"] = "ikke_betalt"
    assert await o.coordinator.async_merk_betalt("2026-10") == ["2026-10"]
    assert o.lager.finn("2026-10")["status"] == "betalt"
    assert o.lager.finn("2026-09")["status"] == "ikke_betalt"


async def test_merk_betalt_roerer_ikke_oppgjor_som_venter_paa_godkjenning(hass, oppsett):
    o = oppsett
    o.lager.finn("2026-10")["status"] = "unntak_ikke_betalt"  # ellers er den auto-betalt 3. des.
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, {**NOV_HUS, "snitt": 3.5}])
    await o.coordinator.async_refresh()  # november havner i venter_godkjenning
    await o.coordinator.async_merk_betalt()
    assert o.lager.finn("2026-11")["status"] == "venter_godkjenning"
    assert o.lager.finn("2026-10")["status"] == "betalt"


async def test_merk_betalt_uten_noe_utestaaende_gir_valideringsfeil(hass, oppsett):
    o = oppsett
    await o.coordinator.async_merk_betalt()
    with pytest.raises(ServiceValidationError):
        await o.coordinator.async_merk_betalt()


async def test_merk_betalt_for_periode_som_ikke_er_utestaaende_eller_finnes_ikke(hass, oppsett):
    o = oppsett
    with pytest.raises(ServiceValidationError):
        await o.coordinator.async_merk_betalt("2026-09")  # allerede betalt
    with pytest.raises(ServiceValidationError):
        await o.coordinator.async_merk_betalt("2099-01")
