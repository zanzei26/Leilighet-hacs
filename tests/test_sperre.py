"""Regnskapssensoren kan sperre en måned med feltet «sperre» (for eksempel når huset har brukt
mer enn 5 000 kWh og Norgespris-modellen ikke gjelder). Da skal ingenting som ser plausibelt ut
kunne bli til et oppgjør: verken tall fra raden eller et gammelt, delvis øyeblikksbilde.
"""

from datetime import timedelta

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from custom_components.stromregnskap_leietaker.generering import ManglerData

from .data import DENNE_DES, NOV_HUS, OKT_HUS, SEP_HUS, sett_kilder

SPERRE = "over 400 kWh – Norgespris-modellen gjelder ikke, legg inn nettokraft fra fakturaen"

# Slik jarvis sperrer: snitt og leilighetens kr er tomme, og raden forklarer hvorfor.
SPERRET_NOV = {**NOV_HUS, "snitt": None, "leilighet_kr": None, "sperre": SPERRE}

# Slik raden ser ut når fakturaens nettokraft er lagt inn (manuell overstyring): fullstendig,
# regnet fra fakturaen, og uten sperre.
FAKTURA_NOV = {**NOV_HUS, "sperre": None, "nettokraft_kilde": "faktura"}

# Et gammelt, fullstendig øyeblikksbilde fra før grensen ble passert (derfor «plausibelt»).
BILDE_NOV = {
    "tid": "2026-11-27T20:00:00+01:00",
    "maned": {
        "mnd": "2026-11",
        "kwh": 2490.0,
        "kraft": 4600.0,
        "nettleie": 1750.0,
        "norgespris": 3380.0,
        "sum": 2970.0,
        "snitt": 1.19,
    },
    "utility": 249.8,
    "maaler": 249.8,
}


def _meldinger(o):
    return [c.data["message"] for c in o.varsler]


# --- oppgjøret ----------------------------------------------------------------------------


async def test_sperret_maaned_gir_mangler_data_og_reserven_fra_bilde_brukes_ikke(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-12-06 08:00:00+01:00")  # siste sjekkdag, ved varseltidspunktet
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, SPERRET_NOV])
    o.lager.data["snapshots"]["2026-11"] = BILDE_NOV
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11") is None  # ikke engang et forslag til godkjenning
    assert o.epost.call_count == 0
    melding = _meldinger(o)[-1]
    assert "mangler data" in melding.lower() and "over 400 kWh" in melding


async def test_sperret_maaned_stopper_ogsaa_naar_tallene_ellers_er_fullstendige(hass, oppsett):
    o = oppsett
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, {**NOV_HUS, "sperre": SPERRE}])
    await o.coordinator.async_refresh()  # 3. desember, i kjørevinduet
    assert o.lager.finn("2026-11") is None and o.epost.call_count == 0


@pytest.mark.parametrize("tving", [False, True])
async def test_manuell_generering_av_sperret_maaned_gir_forklaring_selv_med_tving(
    hass, oppsett, tving
):
    o = oppsett
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, SPERRET_NOV])
    o.lager.data["snapshots"]["2026-11"] = BILDE_NOV
    with pytest.raises(ManglerData, match="sperret") as feil:
        await o.coordinator.async_generer_oppgjor("2026-11", tving=tving, send_epost=False)
    assert "over 400 kWh" in str(feil.value)
    assert isinstance(feil.value, ServiceValidationError)
    assert o.lager.finn("2026-11") is None


@pytest.mark.parametrize("tom", [None, "", "  ", False])
async def test_tomt_sperrefelt_betyr_ingen_sperre(hass, oppsett, tom):
    o = oppsett
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, {**NOV_HUS, "sperre": tom}])
    await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p is not None and p["status"] == "ikke_betalt" and o.epost.call_count == 1


async def test_oppgjoeret_lages_av_seg_selv_naar_sperren_er_fjernet(hass, oppsett):
    o = oppsett
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, SPERRET_NOV])
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11") is None

    # jarvis har fått fakturaens tall: raden er fullstendig og uten sperre
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, FAKTURA_NOV])
    o.freezer.tick(timedelta(hours=1))
    await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p is not None and p["snitt"] == 1.24 and p["status"] == "ikke_betalt"
    assert "snapshot" not in p["kilde"] and o.epost.call_count == 1


# --- øyeblikksbildet ----------------------------------------------------------------------


async def test_sperret_inneværende_maaned_sletter_maanedens_delvise_bilde(hass, oppsett):
    o = oppsett  # 3. desember: inneværende måned er 2026-12
    o.lager.data["snapshots"]["2026-12"] = {**BILDE_NOV, "maned": {**BILDE_NOV["maned"]}}
    o.lager.data["snapshots"]["2026-12"]["maned"]["mnd"] = "2026-12"
    sett_kilder(hass, denne={**DENNE_DES, "snitt": None, "leilighet_kr": None, "sperre": SPERRE})
    await o.coordinator.async_refresh()
    assert "2026-12" not in o.lager.data["snapshots"]  # og det tas ikke noe nytt av sperret tall


async def test_bilde_av_andre_maaneder_beholdes_mens_denne_maaneden_er_sperret(hass, oppsett):
    o = oppsett
    o.lager.data["snapshots"]["2026-11"] = BILDE_NOV
    sett_kilder(hass, denne={**DENNE_DES, "snitt": None, "leilighet_kr": None, "sperre": SPERRE})
    await o.coordinator.async_refresh()
    assert "2026-11" in o.lager.data["snapshots"]


async def test_bilde_tas_som_for_naar_det_ikke_er_noen_sperre(hass, oppsett):
    o = oppsett
    await o.coordinator.async_refresh()
    assert o.lager.data["snapshots"]["2026-12"]["maned"]["kwh"] == 50.0


# --- tidlig varsel ------------------------------------------------------------------------


async def test_datagrunnlaget_forklarer_sperren_i_klartekst(hass, oppsett):
    o = oppsett
    sett_kilder(hass, denne={**DENNE_DES, "snitt": None, "leilighet_kr": None, "sperre": SPERRE})
    await o.coordinator.async_refresh()
    problemer = o.coordinator.vurder_datagrunnlag(dt_util.now())
    assert any("sperret" in p and "over 400 kWh" in p for p in problemer)
    assert not any("ikke komplette tall" in p for p in problemer)  # én forklaring, ikke to


# --- manuell overstyring fra fakturaen ------------------------------------------------------


@pytest.mark.parametrize("sperre", [None, "", SPERRE])
async def test_rad_regnet_fra_fakturaen_gir_normalt_oppgjoer_selv_om_sperreteksten_blir_staaende(
    hass, oppsett, sperre
):
    o = oppsett
    o.lager.data["snapshots"]["2026-11"] = BILDE_NOV
    rad = {**NOV_HUS, "sperre": sperre, "nettokraft_kilde": "faktura"}
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, rad])
    await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p is not None and p["snitt"] == 1.24 and p["status"] == "ikke_betalt"
    assert "snapshot" not in p["kilde"] and o.epost.call_count == 1


async def test_faktura_som_kilde_hjelper_ikke_naar_tallene_fortsatt_mangler(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-12-06 08:00:00+01:00")
    rad = {**SPERRET_NOV, "nettokraft_kilde": "faktura"}  # snitt er fortsatt tom
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, rad])
    o.lager.data["snapshots"]["2026-11"] = BILDE_NOV
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11") is None and "over 400 kWh" in _meldinger(o)[-1]


async def test_annen_nettokraftkilde_enn_faktura_loefter_ikke_sperren(hass, oppsett):
    o = oppsett
    rad = {**NOV_HUS, "sperre": SPERRE, "nettokraft_kilde": "modell"}
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, rad])
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11") is None and o.epost.call_count == 0


async def test_inneværende_maaned_regnet_fra_fakturaen_er_ikke_sperret(hass, oppsett):
    o = oppsett
    denne = {**DENNE_DES, "sperre": SPERRE, "nettokraft_kilde": "faktura"}
    sett_kilder(hass, denne=denne)
    await o.coordinator.async_refresh()
    assert o.lager.data["snapshots"]["2026-12"]["maned"]["kwh"] == 50.0  # bilde tas som vanlig
    problemer = o.coordinator.vurder_datagrunnlag(dt_util.now())
    assert not any("sperret" in p for p in problemer)
