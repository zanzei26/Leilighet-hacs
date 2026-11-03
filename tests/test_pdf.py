"""Tester for PDF-skriveren. Resultatet leses med pypdf, en uavhengig leser."""

import io
import re
from datetime import datetime, timedelta, timezone

import pytest
from pypdf import PdfReader

from custom_components.stromregnskap_leietaker.pdf import (
    A4_BREDDE,
    Dokument,
    tekstbredde,
)

TID = datetime(2026, 12, 3, 8, 30, tzinfo=timezone(timedelta(hours=1)))


def _les(data: bytes) -> PdfReader:
    return PdfReader(io.BytesIO(data), strict=True)


def _enkel(tekst="Hei", **kw):
    d = Dokument("Testdokument")
    d.ny_side().tekst(50, 100, tekst, **kw)
    return d.til_bytes(TID)


# --- tekstmål -------------------------------------------------------------------------------


def test_tekstbredde_bruker_helvetica_mal():
    assert tekstbredde("0", 10) == pytest.approx(5.56)
    assert tekstbredde("00", 10) == pytest.approx(11.12)
    assert tekstbredde(" ", 10) == pytest.approx(2.78)


def test_fet_tekst_kan_vaere_bredere():
    assert tekstbredde("tt", 10, fet=True) > tekstbredde("tt", 10)


def test_ukjente_tegn_har_standardbredde_og_krasjer_ikke():
    assert tekstbredde("日", 10) == pytest.approx(5.56)


# --- gyldig PDF ------------------------------------------------------------------------------


def test_dokumentet_er_en_gyldig_pdf_som_streng_leser_godtar():
    data = _enkel("Fakturagrunnlag")
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    leser = _les(data)
    assert len(leser.pages) == 1
    assert "Fakturagrunnlag" in leser.pages[0].extract_text()


def test_tittel_og_opprettelsestidspunkt_ligger_i_metadata_med_norske_tegn():
    d = Dokument("Fakturagrunnlag strøm – leilighet")
    d.ny_side().tekst(50, 100, "x")
    meta = _les(d.til_bytes(TID)).metadata
    assert meta.title == "Fakturagrunnlag strøm – leilighet"
    assert meta.creation_date.year == 2026 and meta.creation_date.month == 12


def test_siden_er_a4():
    boks = _les(_enkel()).pages[0].mediabox
    assert float(boks.width) == pytest.approx(A4_BREDDE, abs=0.01)
    assert float(boks.height) == pytest.approx(841.89, abs=0.01)


def test_norske_tegn_tall_og_tegnsetting_overlever_gjennom_pdf_en():
    tekst = "Strøm æøå ÆØÅ – 1 234,50 kr «ok» ×"
    ut = _les(_enkel(tekst)).pages[0].extract_text()
    for del_ in ("Strøm æøå ÆØÅ", "1 234,50 kr", "«ok»"):
        assert del_ in ut


def test_parenteser_og_omvendt_skråstrek_escapes():
    tekst = r"a (b) c \ d"
    assert tekst in _les(_enkel(tekst)).pages[0].extract_text()


def test_tegn_utenfor_cp1252_blir_spoersmaalstegn():
    ut = _les(_enkel("A日B")).pages[0].extract_text()
    assert "A?B" in ut


def test_samme_innhold_og_tidspunkt_gir_identiske_bytes():
    assert _enkel("Hei") == _enkel("Hei")


# --- layout ------------------------------------------------------------------------------------


def _tm_x(data: bytes, tekst: str) -> float:
    innhold = _les(data).pages[0].get_contents().get_data().decode("cp1252")
    m = re.search(r"1 0 0 1 ([\d.]+) [\d.]+ Tm\s*\(" + re.escape(tekst) + r"\)", innhold)
    assert m, innhold
    return float(m.group(1))


def test_hoyrejustert_tekst_slutter_paa_x():
    data = _enkel("1 234,50", hoyre=True, storrelse=10)
    x = _tm_x(data, "1\xa0234,50")
    # Dokument.ny_side().tekst(50, ...) betyr at høyre kant er 50
    assert x + tekstbredde("1 234,50", 10) == pytest.approx(50, abs=0.01)


def test_sentrert_tekst_er_sentrert_rundt_x():
    data = _enkel("Midt", midt=True, storrelse=12)
    x = _tm_x(data, "Midt")
    assert x + tekstbredde("Midt", 12) / 2 == pytest.approx(50, abs=0.01)


def test_linjer_og_rektangler_tegnes():
    d = Dokument("T")
    s = d.ny_side()
    s.rektangel(50, 50, 100, 20)
    s.linje(50, 80, 150, 80)
    innhold = _les(d.til_bytes(TID)).pages[0].get_contents().get_data().decode("cp1252")
    assert " re\nf" in innhold and " l\nS" in innhold


# --- flere sider ----------------------------------------------------------------------


def test_sidetall_og_bunntekst_settes_paa_alle_sider():
    d = Dokument("Flere", bunntekst="Generert av Home Assistant")
    for n in range(3):
        d.ny_side().tekst(50, 100, f"Side-innhold {n + 1}")
    leser = _les(d.til_bytes(TID))
    assert len(leser.pages) == 3
    for n, side in enumerate(leser.pages, start=1):
        tekst = side.extract_text()
        assert f"Side {n} av 3" in tekst and "Generert av Home Assistant" in tekst
        assert f"Side-innhold {n}" in tekst


def test_dokument_uten_sider_gir_en_tom_side_i_stedet_for_en_ugyldig_pdf():
    assert len(_les(Dokument("Tom").til_bytes(TID)).pages) == 1
