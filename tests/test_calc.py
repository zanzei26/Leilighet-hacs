"""Tester for den rene beregningsmodulen (ingen HA-avhengigheter)."""

from datetime import date, datetime, timedelta, timezone

import pytest

from custom_components.stromregnskap_leietaker.calc import (
    Grenser,
    MaalerForbruk,
    auto_status,
    beregn_belop,
    beregn_oppgjor,
    estimat_maned,
    forfall_for_periode,
    forrige_periode,
    forrige_periode_id,
    maaler_forbruk,
    periode_start_slutt,
    sjekk_rimelighet,
    utestaaende,
    velg_leilighet_kwh,
)

OSLO = timezone(timedelta(hours=1))

OKT = {
    "mnd": "2026-10",
    "kwh": 2402.13,
    "kraft": 4635.08,
    "nettleie": 1786.72,
    "kapasitet": 525,
    "fast": 25,
    "norgespris": 3298.51,
    "sum": 3123.3,
    "snitt": 1.3002,
}


# --- beløp ---------------------------------------------------------------


def test_belop_oktober_er_kwh_ganger_snitt_avrundet_til_ore():
    assert beregn_belop(234.0, 1.3002) == 304.25


def test_belop_september_folger_vanlig_avrunding_ikke_oppgitt_tall():
    # Spesifikasjonen oppgir 302,79, men 228,0 × 1,3280 = 302,784 → 302,78.
    # September importeres derfor med det faktisk fakturerte beløpet (302,79)
    # i stedet for å regnes om.
    assert beregn_belop(228.0, 1.3280) == 302.78


def test_belop_runder_halvt_ore_opp_uten_flyttallsfeil():
    # 10,0 × 0,1125 = 1,125 → 1,13 (Pythons round() gir 1,12 på flyttall)
    assert beregn_belop(10.0, 0.1125) == 1.13


# --- perioder og datoer ----------------------------------------------------


def test_forfall_er_valgt_dag_i_maneden_etter_perioden():
    assert forfall_for_periode("2026-10", 15) == date(2026, 11, 15)


def test_forfall_over_arsskifte():
    assert forfall_for_periode("2026-12", 15) == date(2027, 1, 15)


def test_periode_start_og_slutt_er_hele_kalendermaneden():
    assert periode_start_slutt("2026-10") == (date(2026, 10, 1), date(2026, 11, 1))
    assert periode_start_slutt("2026-12") == (date(2026, 12, 1), date(2027, 1, 1))


def test_forrige_periode_fra_tredje_desember_er_november():
    assert forrige_periode_id(date(2026, 12, 3)) == "2026-11"


def test_forrige_periode_over_arsskifte():
    assert forrige_periode_id(date(2027, 1, 3)) == "2026-12"


# --- valg av leilighetens kWh ---------------------------------------------


def test_kwh_bruker_maned_primaert_naar_last_period_stemmer():
    valg = velg_leilighet_kwh(234.0, 234.2)
    assert valg.kwh == 234.0
    assert valg.avvik is None


def test_kwh_faller_tilbake_til_last_period_naar_maned_mangler():
    valg = velg_leilighet_kwh(None, 234.2)
    assert valg.kwh == 234.2
    assert valg.avvik is None


def test_kwh_avvik_over_halv_kwh_blir_flagget_med_begge_tall():
    valg = velg_leilighet_kwh(234.0, 235.0)
    assert valg.kwh == 234.0
    assert "234" in valg.avvik and "235" in valg.avvik


def test_kwh_avvik_paa_noyaktig_halv_kwh_er_ok():
    assert velg_leilighet_kwh(234.0, 234.5).avvik is None


def test_kwh_uten_noen_kilde_gir_ingen_verdi():
    valg = velg_leilighet_kwh(None, None)
    assert valg.kwh is None


# --- rimelighetskontroll ----------------------------------------------------


def _ok(**over):
    args = dict(leilighet_kwh=234.0, hus_kwh=2402.13, snitt=1.3002, forrige_kwh=228.0)
    args.update(over)
    return sjekk_rimelighet(**args, grenser=Grenser())


def test_rimelig_oppgjor_gir_ingen_brudd():
    assert _ok() == []


def test_snitt_under_minimum_er_brudd():
    assert len(_ok(snitt=0.49)) == 1


def test_snitt_over_maksimum_er_brudd():
    assert len(_ok(snitt=3.01)) == 1


def test_snitt_paa_grensene_er_ok():
    assert _ok(snitt=0.50) == []
    assert _ok(snitt=3.00) == []


def test_null_kwh_er_brudd():
    assert _ok(leilighet_kwh=0.0, forrige_kwh=None)


def test_leilighet_kwh_over_hus_kwh_er_brudd():
    assert _ok(leilighet_kwh=3000.0, forrige_kwh=None)


def test_endring_over_60_prosent_er_brudd():
    assert _ok(leilighet_kwh=228.0 * 1.61)


def test_endring_paa_60_prosent_er_ok():
    assert _ok(leilighet_kwh=228.0 * 1.60) == []


def test_stort_fall_i_forbruk_er_ogsa_brudd():
    assert _ok(leilighet_kwh=228.0 * 0.39)


def test_uten_forrige_periode_hoppes_endringssjekk_over():
    assert _ok(leilighet_kwh=900.0, forrige_kwh=None) == []


def test_flere_brudd_gir_flere_meldinger():
    assert len(_ok(snitt=5.0, leilighet_kwh=3000.0, forrige_kwh=None)) == 2


# --- selve oppgjøret -------------------------------------------------------


def test_oppgjor_for_oktober_har_forventede_felt():
    naa = datetime(2026, 11, 3, 8, 11, tzinfo=OSLO)
    p = beregn_oppgjor(
        periode_id="2026-10",
        maned=OKT,
        leilighet_kwh=234.0,
        forfallsdag=15,
        naa=naa,
        kilde="test",
    )
    assert p["id"] == "2026-10"
    assert p["start"] == "2026-10-01" and p["slutt"] == "2026-11-01"
    assert p["leilighet_kwh"] == 234.0
    assert p["hus_kwh"] == 2402.13
    assert p["kraft"] == 4635.08 and p["nettleie"] == 1786.72
    assert p["norgespris"] == 3298.51 and p["sum"] == 3123.3
    assert p["snitt"] == 1.3002
    assert p["belop"] == 304.25
    assert p["forfall"] == "2026-11-15"
    assert p["status"] == "ikke_betalt"
    assert p["generert"] == naa.isoformat()
    assert p["epost_sendt"] is None
    assert p["epost_ventende_siden"] is None
    assert "epost_ventende" not in p
    assert p["kilde"] == "test"


# --- automatisk betalt-status ------------------------------------------------


def _p(status, forfall="2026-11-15", belop=100.0):
    return {"id": "x", "status": status, "forfall": forfall, "belop": belop}


def test_ikke_betalt_blir_betalt_paa_forfallsdagen():
    assert auto_status(_p("ikke_betalt"), date(2026, 11, 15)) == "betalt"


def test_ikke_betalt_forblir_ikke_betalt_foer_forfall():
    assert auto_status(_p("ikke_betalt"), date(2026, 11, 14)) == "ikke_betalt"


def test_unntak_blir_aldri_betalt_automatisk():
    assert auto_status(_p("unntak_ikke_betalt"), date(2027, 1, 1)) == "unntak_ikke_betalt"


def test_venter_godkjenning_blir_aldri_betalt_automatisk():
    assert auto_status(_p("venter_godkjenning"), date(2027, 1, 1)) == "venter_godkjenning"


def test_betalt_forblir_betalt():
    assert auto_status(_p("betalt"), date(2026, 1, 1)) == "betalt"


# --- utestående -----------------------------------------------------------------


def test_utestaaende_teller_ikke_betalt_og_unntak_men_ikke_betalt_eller_ventende():
    perioder = [
        _p("betalt", belop=302.79),
        _p("ikke_betalt", belop=304.25),
        _p("unntak_ikke_betalt", belop=100.10),
        _p("venter_godkjenning", belop=999.0),
    ]
    assert utestaaende(perioder) == 404.35


def test_utestaaende_er_null_uten_perioder():
    assert utestaaende([]) == 0.0


# --- månedsestimat ---------------------------------------------------------------


def test_estimat_er_forrige_kwh_ganger_endring_priset_til_forrige_snitt():
    kwh, kr = estimat_maned(forrige_kwh=234.0, endring_prosent=22, forrige_snitt=1.3002)
    assert kwh == pytest.approx(285.48)
    assert kr == 371.18


def test_estimat_med_negativ_endring():
    kwh, _ = estimat_maned(forrige_kwh=200.0, endring_prosent=-10, forrige_snitt=1.0)
    assert kwh == pytest.approx(180.0)


# --- forrige periode ------------------------------------------------------------


def test_forrige_periode_er_den_nyeste_med_lavere_id():
    ps = [_p("betalt") | {"id": "2026-09"}, _p("ikke_betalt") | {"id": "2026-10"}]
    assert forrige_periode(ps, "2026-11")["id"] == "2026-10"
    assert forrige_periode(ps, "2026-10")["id"] == "2026-09"
    assert forrige_periode(ps, "2026-09") is None


def test_forrige_periode_hopper_over_de_som_venter_godkjenning():
    ps = [_p("betalt") | {"id": "2026-09"}, _p("venter_godkjenning") | {"id": "2026-10"}]
    assert forrige_periode(ps, "2026-11")["id"] == "2026-09"


# --- målerstander ---------------------------------------------------------------


def test_maalerforbruk_er_differansen_mellom_to_avlesninger():
    assert maaler_forbruk(0.0, 250.1234) == MaalerForbruk(250.123, None)
    assert maaler_forbruk(1000.5, 1234.5) == MaalerForbruk(234.0, None)


def test_maalerforbruk_er_null_hvis_stand_ikke_endret():
    assert maaler_forbruk(100.0, 100.0) == MaalerForbruk(0.0, None)


def test_maalerforbruk_mangler_en_avlesning_gir_ingen_verdi_og_ingen_feil():
    assert maaler_forbruk(None, 10.0) == MaalerForbruk(None, None)
    assert maaler_forbruk(10.0, None) == MaalerForbruk(None, None)


def test_maalerstand_som_gaar_bakover_gir_feil_med_begge_tall():
    r = maaler_forbruk(500.0, 120.5)
    assert r.kwh is None
    assert "500,0" in r.feil and "120,5" in r.feil


def test_maaleren_er_primaerkilde_foran_sensorene():
    valg = velg_leilighet_kwh(251.0, 250.0, maaler=250.2)
    assert valg.kwh == 250.2
    assert "maalerstander" in valg.kilde
    assert "251,0" in valg.avvik  # 251,0 er 0,8 kWh fra målerverdien, over grensen på 0,5


def test_maaleren_alene_er_nok():
    valg = velg_leilighet_kwh(None, None, maaler=250.2)
    assert valg.kwh == 250.2 and valg.avvik is None


def test_alle_tre_kilder_som_stemmer_gir_ingen_avvik():
    valg = velg_leilighet_kwh(250.0, 250.2, maaler=250.1)
    assert valg.kwh == 250.1 and valg.avvik is None
    assert "maalerstander" in valg.kilde and "last_period" in valg.kilde


def test_avvik_mellom_maaler_og_sensor_lister_alle_tre_tall():
    valg = velg_leilighet_kwh(250.0, 250.2, maaler=253.0)
    assert valg.kwh == 253.0
    for tall in ("253,0", "250,0", "250,2"):
        assert tall in valg.avvik
    assert "målerstander" in valg.avvik
