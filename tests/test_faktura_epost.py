"""Regningen som PDF-vedlegg: handlingen send_faktura og den automatiske oppgjørs-e-posten."""

import io
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pypdf import PdfReader

from custom_components.stromregnskap_leietaker.const import DOMAIN
from custom_components.stromregnskap_leietaker.mail import SmtpFeil, bygg_epost, bygg_fakturapost

from .data import LEIETAKER, OKT, UTLEIER

URL = "https://abc123.ui.nabu.casa/local/hemmelig/index.html"
LENKE = "https://eksempel.ui.nabu.casa/local/testslug123/index.html"
PDF = b"%PDF-1.4 testinnhold"
OKT_NAVN = "fakturagrunnlag-strom-leilighet-2026-10.pdf"
VEDLEGG_OKT = [(OKT_NAVN, "application/pdf", PDF)]


def _faktura(**over):
    args = dict(
        periode=OKT,
        leietaker=LEIETAKER,
        utleier=UTLEIER,
        side_url=URL,
        vedlegg=VEDLEGG_OKT,
        cc_utleier=True,
    )
    args.update(over)
    return bygg_fakturapost(**args)


def _tekst(msg):
    return msg.get_body(("plain",)).get_content()


def _html(msg):
    return msg.get_body(("html",)).get_content()


def _vedlegg(msg):
    return {d.get_filename(): d for d in msg.iter_attachments()}


def _pdf_tekst(innhold: bytes) -> str:
    return "\n".join(s.extract_text() for s in PdfReader(io.BytesIO(innhold)).pages)


# --- e-posten bygget av bygg_fakturapost ---------------------------------------------------


def test_fakturaposten_har_emne_avsender_til_og_cc():
    msg = _faktura()
    assert msg["Subject"] == "Strømregning oktober 2026 – Testveien 1"
    assert "ola@example.com" in msg["From"] and "Ola Utleier" in msg["From"]
    assert "kari@example.com" in msg["To"]
    assert "ola@example.com" in msg["Cc"]


def test_fakturaposten_kan_sendes_uten_kopi():
    assert _faktura(cc_utleier=False)["Cc"] is None


def test_fakturaposten_har_lenke_regning_og_betalingsinformasjon():
    msg = _faktura()
    tekst = _tekst(msg)
    assert tekst.startswith("Hei Kari,")
    for forventet in (
        URL,
        "oktober 2026",
        "304,25 kr",
        "15.11.2026",
        "1234.56.78903",
        "Strøm – oktober 2026",
        "vedlagt",
    ):
        assert forventet in tekst, forventet
    assert 'href="' + URL + '"' in _html(msg)


def test_fakturaposten_nevner_regnskapet_og_at_forbruket_denne_maaneden_er_live():
    tekst = _tekst(_faktura()).lower()
    assert "regnskapet" in tekst and "pdf" in tekst
    assert "live" in tekst and "inneværende måned" in tekst


def test_fakturaposten_ber_om_a_ikke_dele_lenken():
    assert "ikke del" in _tekst(_faktura()).lower()


def test_fakturaposten_har_regningen_som_eneste_vedlegg():
    msg = _faktura()
    v = _vedlegg(msg)
    assert list(v) == [OKT_NAVN]
    assert v[OKT_NAVN].get_content_type() == "application/pdf"
    assert v[OKT_NAVN].get_content() == PDF


def test_fakturaposten_escaper_html():
    msg = _faktura(leietaker={**LEIETAKER, "navn": "<b>Eva</b>"})
    assert "<b>Eva</b>" not in _html(msg)


# --- vedlegg på den vanlige oppgjørs-e-posten ----------------------------------------------


def _oppgjor(**over):
    args = dict(periode=OKT, leietaker=LEIETAKER, utleier=UTLEIER, side_url=URL, cc_utleier=True)
    args.update(over)
    return bygg_epost(**args)


def test_oppgjorsposten_med_vedlegg_har_regningen_og_sier_det():
    msg = _oppgjor(vedlegg=VEDLEGG_OKT)
    assert list(_vedlegg(msg)) == [OKT_NAVN]
    assert "vedlagt som pdf" in _tekst(msg).lower()
    assert "vedlagt som pdf" in _html(msg).lower()


def test_oppgjorsposten_uten_vedlegg_er_uendret():
    msg = _oppgjor()
    assert list(msg.iter_attachments()) == []
    assert "vedlagt" not in _tekst(msg).lower()


# --- den automatiske utsendingen ----------------------------------------------------------


async def test_oppgjoeret_som_sendes_automatisk_har_regningen_vedlagt_som_pdf(hass, oppsett):
    o = oppsett
    await o.coordinator.async_refresh()  # 3. desember: november lages og sendes
    msg = o.epost.call_args.kwargs["melding"]
    assert "kari@example.com" in msg["To"]
    v = _vedlegg(msg)
    assert list(v) == ["fakturagrunnlag-strom-leilighet-2026-11.pdf"]
    pdf = _pdf_tekst(v["fakturagrunnlag-strom-leilighet-2026-11.pdf"].get_content())
    assert "310,00" in pdf and "november 2026" in pdf


async def test_oppgjoeret_sendt_paa_nytt_har_ogsaa_regningen_vedlagt(hass, oppsett):
    o = oppsett
    await o.coordinator.async_send_epost_pa_nytt("2026-10")
    assert list(_vedlegg(o.epost.call_args.kwargs["melding"])) == [OKT_NAVN]


async def test_feil_ved_bygging_av_regningen_stopper_ikke_utsendingen_og_utleier_faar_beskjed(
    hass, oppsett
):
    o = oppsett
    with patch(
        "custom_components.stromregnskap_leietaker.eksport.bygg_fakturagrunnlag",
        side_effect=RuntimeError("pdf-feil"),
    ):
        await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p["epost_sendt"] is not None  # oppgjøret kom frem
    msg = o.epost.call_args.kwargs["melding"]
    assert list(msg.iter_attachments()) == []
    assert "vedlagt" not in _tekst(msg).lower()  # teksten lover ikke noe vedlegg
    assert [c for c in o.varsler if "vedlegg" in c.data["title"].lower()]


# --- handlingen send_faktura --------------------------------------------------------------


async def test_send_faktura_sender_siste_periode_med_regning_og_lenke(hass, oppsett):
    o = oppsett
    await o.coordinator.async_send_faktura()
    assert o.epost.call_count == 1
    msg = o.epost.call_args.kwargs["melding"]
    assert "kari@example.com" in msg["To"] and "ola@example.com" in msg["Cc"]
    assert msg["Subject"] == "Strømregning oktober 2026 – Testveien 1"
    assert LENKE in _tekst(msg)
    v = _vedlegg(msg)
    assert list(v) == [OKT_NAVN]
    pdf = _pdf_tekst(v[OKT_NAVN].get_content())
    assert "304,25" in pdf and "oktober 2026" in pdf
    assert any("Faktura sendt" in c.data["title"] for c in o.varsler)


async def test_send_faktura_for_bestemt_periode(hass, oppsett):
    o = oppsett
    await o.coordinator.async_send_faktura("2026-09")
    msg = o.epost.call_args.kwargs["melding"]
    assert "september 2026" in msg["Subject"]
    assert list(_vedlegg(msg)) == ["fakturagrunnlag-strom-leilighet-2026-09.pdf"]


async def test_send_faktura_endrer_ikke_perioden(hass, oppsett):
    o = oppsett
    for_ = dict(o.lager.finn("2026-10"))
    await o.coordinator.async_send_faktura("2026-10")
    assert o.lager.finn("2026-10") == for_


async def test_send_faktura_for_ukjent_eller_ventende_periode_gir_valideringsfeil(hass, oppsett):
    o = oppsett
    with pytest.raises(ServiceValidationError):
        await o.coordinator.async_send_faktura("2099-01")
    o.lager.finn("2026-10")["status"] = "venter_godkjenning"
    with pytest.raises(ServiceValidationError):
        await o.coordinator.async_send_faktura("2026-10")
    assert o.epost.call_count == 0


async def test_send_faktura_uten_perioder_gir_valideringsfeil(hass, oppsett):
    o = oppsett
    for p in list(o.lager.perioder):
        o.lager.fjern(p["id"])
    with pytest.raises(ServiceValidationError):
        await o.coordinator.async_send_faktura()


async def test_send_faktura_uten_lenke_gir_valideringsfeil_og_sender_ingenting(hass, oppsett):
    o = oppsett
    hass.config.external_url = None
    hass.config.internal_url = None
    with pytest.raises(ServiceValidationError):
        await o.coordinator.async_send_faktura()
    hass.config_entries.async_update_entry(o.entry, data={**o.entry.data, "publiser_side": False})
    with pytest.raises(ServiceValidationError):
        await o.coordinator.async_send_faktura()
    assert o.epost.call_count == 0


async def test_send_faktura_som_feiler_gir_kjoretidsfeil_ikke_valideringsfeil(hass, oppsett):
    o = oppsett
    o.epost.side_effect = SmtpFeil("connect", "nede")
    with pytest.raises(HomeAssistantError) as exc:
        await o.coordinator.async_send_faktura()
    assert not isinstance(exc.value, ServiceValidationError)
    assert not [c for c in o.varsler if "Faktura sendt" in c.data["title"]]


async def test_send_faktura_uten_kopi_naar_den_er_slaatt_av(hass, oppsett):
    o = oppsett
    hass.config_entries.async_update_entry(o.entry, data={**o.entry.data, "cc_utleier": False})
    await o.coordinator.async_send_faktura()
    assert o.epost.call_args.kwargs["melding"]["Cc"] is None


# --- som tjeneste -------------------------------------------------------------------------


async def _kall(hass, data=None):
    return await hass.services.async_call(DOMAIN, "send_faktura", data or {}, blocking=True)


async def test_tjenesten_send_faktura_er_registrert_og_sender_siste_periode(hass, integrasjon):
    assert "send_faktura" in hass.services.async_services()[DOMAIN]
    await _kall(hass)
    msg = integrasjon.epost.call_args.kwargs["melding"]
    assert "kari@example.com" in msg["To"]
    assert list(_vedlegg(msg)) == [OKT_NAVN]


async def test_tjenesten_send_faktura_med_periode_og_feil(hass, integrasjon):
    await _kall(hass, {"periode": "2026-09"})
    assert "september 2026" in integrasjon.epost.call_args.kwargs["melding"]["Subject"]
    with pytest.raises(ServiceValidationError):
        await _kall(hass, {"periode": "2099-01"})
    integrasjon.epost.side_effect = SmtpFeil("auth", "avvist")
    with pytest.raises(HomeAssistantError):
        await _kall(hass)
