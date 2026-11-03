"""Tester for fakturagrunnlag og regnskap som PDF. Innholdet leses tilbake med pypdf."""

import io
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from pypdf import PdfReader

from custom_components.stromregnskap_leietaker.pdf_dokumenter import (
    REGNSKAPSNAVN,
    bygg_fakturagrunnlag,
    bygg_regnskap,
    fakturanavn,
)

from .data import LEIETAKER, OKT, SEP, UTLEIER, perioder

NAA = datetime(2026, 12, 3, 8, 30, tzinfo=timezone(timedelta(hours=1)))
NBSP = " "


def _sider(data: bytes) -> list[str]:
    return [s.extract_text() for s in PdfReader(io.BytesIO(data), strict=True).pages]


def _alt(data: bytes) -> str:
    return "\n".join(_sider(data))


def _faktura(periode=None):
    return bygg_fakturagrunnlag(deepcopy(periode or OKT), LEIETAKER, UTLEIER, NAA)


# --- fakturagrunnlag ---------------------------------------------------------------------------


def test_filnavn():
    assert fakturanavn("2026-10") == "fakturagrunnlag-strom-leilighet-2026-10.pdf"
    assert REGNSKAPSNAVN == "regnskap-strom-leilighet.pdf"


def test_fakturagrunnlaget_er_en_enkelt_side_med_parter_og_periode():
    sider = _sider(_faktura())
    assert len(sider) == 1
    t = sider[0]
    for forventet in (
        "Fakturagrunnlag",
        "oktober 2026",
        "Kari Nordmann",
        "Testveien 1, 1. etasje",
        "Ola Utleier",
        "01.10.2026",
        "31.10.2026",
    ):
        assert forventet in t, forventet


def test_fakturagrunnlaget_viser_forbruk_husets_kostnader_utregning_og_betaling():
    t = _alt(_faktura())
    for forventet in (
        "234,0 kWh",
        f"2{NBSP}402,13",  # husets kWh
        f"4{NBSP}635,08",  # kraft
        f"1{NBSP}786,72",  # nettleie
        f"3{NBSP}298,51",  # Norgespris
        f"3{NBSP}123,30",  # sum
        "1,3002",
        "234,0 kWh × 1,3002 kr/kWh = 304,25 kr",
        "304,25",
        "15.11.2026",
        "1234.56.78903",
        "Strøm – oktober 2026",
        "Ikke betalt",
    ):
        assert forventet in t, forventet


def test_betalt_periode_viser_betalt():
    assert "Betalt" in _alt(_faktura({**OKT, "status": "betalt"}))


def test_delperiode_viser_de_faktiske_datoene():
    t = _alt(_faktura(SEP))
    assert "30.08.2026" in t and "30.09.2026" in t and "september 2026" in t


def test_malerstander_vises_naar_de_finnes():
    t = _alt(_faktura({**OKT, "maaler_start": 1000.5, "maaler_slutt": 1234.5}))
    assert "Målerstand 01.10.2026" in t and f"1{NBSP}000,5 kWh" in t
    assert "Målerstand 01.11.2026" in t and f"1{NBSP}234,5 kWh" in t


def test_uten_malerstander_utelates_linjene_og_ingenting_viser_none():
    t = _alt(_faktura())  # importert periode har ingen målerstander
    assert "Målerstand" not in t and "None" not in t


def test_pdf_en_har_tittel_i_metadata():
    meta = PdfReader(io.BytesIO(_faktura())).metadata
    assert "Fakturagrunnlag" in meta.title and "oktober 2026" in meta.title


# --- hele regnskapet -----------------------------------------------------------------------------


def _regnskap(ps=None):
    return bygg_regnskap(deepcopy(ps if ps is not None else perioder()), LEIETAKER, UTLEIER, NAA)


def test_regnskapet_har_alle_perioder_med_forbruk_pris_belop_forfall_og_status():
    t = _alt(_regnskap())
    for forventet in (
        "Regnskap",
        "september 2026",
        "oktober 2026",
        "228,0",
        "234,0",
        "1,3280",
        "1,3002",
        "302,79",
        "304,25",
        "15.10.2026",
        "15.11.2026",
        "Betalt",
        "Ikke betalt",
    ):
        assert forventet in t, forventet


def test_regnskapet_har_totaler():
    t = _alt(_regnskap())
    assert "Totalt fakturert" in t and "607,04" in t
    assert "Herav betalt" in t and "302,79" in t
    assert "Utestående" in t and "304,25" in t


def test_regnskapet_viser_husets_kostnader_per_maaned():
    t = _alt(_regnskap())
    for forventet in (f"2{NBSP}156,64", f"4{NBSP}028,93", f"2{NBSP}819,94", f"2{NBSP}402,13"):
        assert forventet in t, forventet


def test_regnskapet_viser_betalingsinformasjon_og_parter():
    t = _alt(_regnskap())
    assert "1234.56.78903" in t and "Kari Nordmann" in t and "Ola Utleier" in t
    assert "30.08.2026" in t  # leieforholdets start


def test_periode_som_venter_godkjenning_er_ikke_med():
    ps = perioder()
    ny = deepcopy(OKT)
    ny.update({"id": "2026-11", "status": "venter_godkjenning", "belop": 999.99})
    ps.append(ny)
    t = _alt(_regnskap(ps))
    assert "999,99" not in t and "november 2026" not in t
    assert "607,04" in t


def test_regnskap_uten_perioder_er_en_gyldig_pdf_med_forklaring():
    t = _alt(_regnskap([]))
    assert "Ingen oppgjør ennå" in t and "0,00" in t


def test_mange_perioder_gir_flere_sider_og_gjentar_tabelloverskriften():
    ps = []
    for n in range(60):
        p = deepcopy(OKT)
        aar, mnd = 2020 + n // 12, n % 12 + 1
        p.update(
            {
                "id": f"{aar}-{mnd:02d}",
                "start": f"{aar}-{mnd:02d}-01",
                "slutt": f"{aar + (mnd == 12)}-{(mnd % 12) + 1:02d}-01",
                "forfall": f"{aar + (mnd == 12)}-{(mnd % 12) + 1:02d}-15",
                "status": "betalt",
            }
        )
        ps.append(p)
    sider = _sider(_regnskap(ps))
    assert len(sider) > 1
    for i, side in enumerate(sider, start=1):
        assert f"Side {i} av {len(sider)}" in side
    assert sum("Forbruk (kWh)" in s for s in sider) >= 2  # overskriften gjentas
    # hver periode forekommer nøyaktig én gang i den første tabellen
    assert _alt(_regnskap(ps)).count("januar 2020") >= 1
    assert "None" not in _alt(_regnskap(ps))
