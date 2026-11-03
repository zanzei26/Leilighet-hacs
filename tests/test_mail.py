"""Tester for e-postbygging og SMTP-sending."""

import smtplib
from unittest.mock import MagicMock, patch

import pytest

from custom_components.stromregnskap_leietaker.mail import (
    SmtpFeil,
    bygg_epost,
    bygg_kopipost,
    bygg_lenkepost,
    bygg_testepost,
    send_epost,
)

from .data import LEIETAKER, OKT, UTLEIER

URL = "https://abc123.ui.nabu.casa/local/hemmelig/index.html"


def _msg(**over):
    args = dict(periode=OKT, leietaker=LEIETAKER, utleier=UTLEIER, side_url=URL, cc_utleier=True)
    args.update(over)
    return bygg_epost(**args)


def _deler(msg):
    tekst = msg.get_body(preferencelist=("plain",)).get_content()
    html = msg.get_body(preferencelist=("html",)).get_content()
    return tekst, html


def test_emne_har_maaned_aar_og_gateadresse_uten_etasje():
    assert _msg()["Subject"] == "Strømoppgjør oktober 2026 – Testveien 1"


def test_avsender_til_og_cc():
    msg = _msg()
    assert "ola@example.com" in msg["From"] and "Ola Utleier" in msg["From"]
    assert "kari@example.com" in msg["To"]
    assert "ola@example.com" in msg["Cc"]


def test_cc_kan_skrus_av():
    assert _msg(cc_utleier=False)["Cc"] is None


def test_tekstdelen_har_alle_nokkeltall_og_lenke():
    tekst, _ = _deler(_msg())
    assert tekst.startswith("Hei Kari,")
    for forventet in (
        "234,0 kWh",
        "1,3002 kr/kWh",
        "304,25 kr",
        "15.11.2026",
        "1234.56.78903",
        "Strøm – oktober 2026",
        URL,
        "målte forbruk",
    ):
        assert forventet in tekst, forventet


def test_html_delen_har_samme_nokkeltall():
    _, html = _deler(_msg())
    for forventet in ("234,0 kWh", "304,25 kr", "15.11.2026", "1234.56.78903", URL):
        assert forventet in html, forventet


def test_html_i_navn_blir_escapet():
    _, html = _deler(_msg(leietaker={**LEIETAKER, "navn": "<b>Eva</b>"}))
    assert "<b>Eva</b>" not in html


def test_uten_lenke_utelates_lenkeavsnittet_helt():
    msg = _msg(side_url=None)
    tekst, html = _deler(msg)
    assert "None" not in tekst and "None" not in html
    assert "historikk" not in tekst and "href" not in html
    assert "304,25 kr" in tekst


def test_ingen_vedlegg():
    assert list(_msg().iter_attachments()) == []


def test_testepost_gaar_til_utleier():
    msg = bygg_testepost(UTLEIER)
    assert "ola@example.com" in msg["To"]
    assert "Test" in msg["Subject"]


@pytest.fixture
def smtp():
    with patch("custom_components.stromregnskap_leietaker.mail.smtplib.SMTP") as klasse:
        instans = MagicMock()
        klasse.return_value.__enter__.return_value = instans
        yield klasse, instans


def test_send_bruker_starttls_login_og_send_message(smtp):
    klasse, instans = smtp
    msg = _msg()
    send_epost(host="smtp.gmail.com", port=587, brukernavn="u", passord="p", melding=msg)
    assert klasse.call_args.args[:2] == ("smtp.gmail.com", 587)
    instans.starttls.assert_called_once()
    instans.login.assert_called_once_with("u", "p")
    instans.send_message.assert_called_once_with(msg)


def test_feil_passord_gir_smtpfeil_auth_uten_passord_i_meldingen(smtp):
    _, instans = smtp
    instans.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad")
    with pytest.raises(SmtpFeil) as exc:
        send_epost(host="h", port=587, brukernavn="u", passord="hemmelig123", melding=_msg())
    assert exc.value.kind == "auth"
    assert "hemmelig123" not in str(exc.value)


def test_nettverksfeil_gir_smtpfeil_connect(smtp):
    klasse, _ = smtp
    klasse.side_effect = OSError("nede")
    with pytest.raises(SmtpFeil) as exc:
        send_epost(host="h", port=587, brukernavn="u", passord="p", melding=_msg())
    assert exc.value.kind == "connect"


def test_avvist_mottaker_gir_smtpfeil_send(smtp):
    _, instans = smtp
    instans.send_message.side_effect = smtplib.SMTPRecipientsRefused({})
    with pytest.raises(SmtpFeil) as exc:
        send_epost(host="h", port=587, brukernavn="u", passord="p", melding=_msg())
    assert exc.value.kind == "send"


# --- e-post med bare lenken -------------------------------------------------------


def _lenke(**over):
    args = dict(leietaker=LEIETAKER, utleier=UTLEIER, side_url=URL, cc_utleier=True)
    args.update(over)
    return bygg_lenkepost(**args)


def test_lenkeposten_har_emne_avsender_til_og_cc():
    msg = _lenke()
    assert msg["Subject"] == "Din side for strømoppgjør – Testveien 1"
    assert "ola@example.com" in msg["From"]
    assert "kari@example.com" in msg["To"]
    assert "ola@example.com" in msg["Cc"]


def test_lenkeposten_kan_sendes_uten_kopi():
    assert _lenke(cc_utleier=False)["Cc"] is None


def test_lenkeposten_forklarer_hva_siden_viser_og_ber_om_a_ikke_dele_lenken():
    msg = _lenke()
    tekst = msg.get_body(("plain",)).get_content()
    html = msg.get_body(("html",)).get_content()
    assert tekst.startswith("Hei Kari,")
    assert URL in tekst and URL in html
    assert 'href="' + URL + '"' in html
    for ord_ in ("utestående", "historikk", "forbruk"):
        assert ord_ in tekst.lower()
    assert "ikke del" in tekst.lower()
    assert "1234.56.78903" not in tekst  # kontonummeret hører hjemme i selve oppgjøret


def test_lenkeposten_har_ingen_vedlegg_og_escaper_html():
    msg = _lenke(leietaker={**LEIETAKER, "navn": "<b>Eva</b>"})
    assert list(msg.iter_attachments()) == []
    assert "<b>Eva</b>" not in msg.get_body(("html",)).get_content()


def test_epost_viser_kwh_med_en_desimal():
    msg = _msg(periode={**OKT, "leilighet_kwh": 250.123})
    assert "250,1 kWh" in msg.get_body(("plain",)).get_content()


# --- kopi til utleier -----------------------------------------------------------------------


VEDLEGG = [
    ("fakturagrunnlag-strom-leilighet-2026-10.pdf", "application/pdf", b"%PDF-1.4 faktura"),
    ("regnskap-strom-leilighet.pdf", "application/pdf", b"%PDF-1.4 regnskap"),
    ("sikkerhetskopi.json", "application/json", b'{"data": {}}'),
]


def _kopi(**over):
    args = dict(periode=OKT, leietaker=LEIETAKER, utleier=UTLEIER, vedlegg=VEDLEGG)
    args.update(over)
    return bygg_kopipost(**args)


def test_kopien_har_emnet_fakturagrunnlag_strom_leilighet_og_gaar_bare_til_utleier():
    msg = _kopi()
    assert msg["Subject"] == "Fakturagrunnlag strøm leilighet – oktober 2026"
    assert "ola@example.com" in msg["To"] and "ola@example.com" in msg["From"]
    assert msg["Cc"] is None
    assert "kari@example.com" not in str(msg["To"]) + str(msg["From"])


def test_kopien_forklarer_hva_som_er_sendt_og_hva_vedleggene_er():
    tekst = _kopi().get_body(("plain",)).get_content()
    for forventet in (
        "Kari Nordmann",
        "kari@example.com",
        "304,25 kr",
        "15.11.2026",
        "oktober 2026",
        "fakturagrunnlag-strom-leilighet-2026-10.pdf",
        "regnskap-strom-leilighet.pdf",
        "sikkerhetskopi.json",
        "Ta vare på",
    ):
        assert forventet in tekst, forventet


def test_kopien_har_alle_vedlegg_med_riktig_innhold_og_type():
    deler = list(_kopi().iter_attachments())
    assert [(d.get_filename(), d.get_content_type()) for d in deler] == [
        (navn, typen) for navn, typen, _ in VEDLEGG
    ]
    assert [d.get_content() for d in deler] == [data for _, _, data in VEDLEGG]
