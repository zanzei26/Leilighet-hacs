"""Vern mot at kilden skriver forrige måneds tall under den nye måneden.

Scenario: regnskapssensoren (malen) skriver «2026-11» med oktobertall fordi Amperium ennå ikke har
rullet «forrige måned». Snittprisen er da 1,3002, som ligger innenfor grensene, og ingen av de
vanlige kontrollene ville stoppet oppgjøret.
"""

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.stromregnskap_leietaker.calc import er_kopi_av_forrige, forrige_maaned_id
from custom_components.stromregnskap_leietaker.generering import ManglerData

from .data import NOV_HUS, OKT, OKT_HUS, SEP_HUS, sett_kilder

KOPI_AV_OKT = {**OKT_HUS, "mnd": "2026-11", "leilighet_kwh": 250.0}


def _med_kopi(hass):
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, KOPI_AV_OKT])


def _med_riktige_tall(hass):
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, NOV_HUS])


# --- rene funksjoner ------------------------------------------------------------------------------


def test_forrige_maaned_id():
    assert forrige_maaned_id("2026-11") == "2026-10"
    assert forrige_maaned_id("2026-01") == "2025-12"


def test_identiske_tall_er_en_kopi():
    assert er_kopi_av_forrige(KOPI_AV_OKT, OKT)


def test_avrunding_til_to_desimaler_gir_fortsatt_kopi():
    assert er_kopi_av_forrige({**KOPI_AV_OKT, "kwh": 2402.1304, "sum": 3123.301}, OKT)


@pytest.mark.parametrize(
    "endring",
    [{"kwh": 2402.14}, {"sum": 3123.31}, {"kwh": 2500.0, "sum": 3100.0}],
)
def test_ulike_tall_er_ikke_en_kopi(endring):
    assert not er_kopi_av_forrige({**KOPI_AV_OKT, **endring}, OKT)


def test_uten_forrige_periode_eller_med_ufullstendige_tall_er_det_ikke_en_kopi():
    assert not er_kopi_av_forrige(KOPI_AV_OKT, None)
    assert not er_kopi_av_forrige({"mnd": "2026-11"}, OKT)
    assert not er_kopi_av_forrige({"kwh": "x", "sum": None}, OKT)


# --- oppgjøret ------------------------------------------------------------------------------------


async def test_kopi_av_forrige_maaned_stopper_oppgjoeret_uten_aa_lagre_noe(hass, oppsett):
    o = oppsett
    _med_kopi(hass)
    with pytest.raises(ManglerData, match="identiske med 2026-10"):
        await o.coordinator.async_generer_oppgjor("2026-11", send_epost=False)
    assert o.lager.finn("2026-11") is None
    assert o.epost.call_count == 0


async def test_automatisk_kjoering_lager_ikke_oppgjoer_av_kopien_men_leges_naar_kilden_rettes(
    hass, oppsett
):
    o = oppsett  # 3. des kl. 08:30, i kjørevinduet
    _med_kopi(hass)
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11") is None and o.epost.call_count == 0

    _med_riktige_tall(hass)  # malen/Amperium har rullet
    await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p is not None and p["snitt"] == 1.24 and p["status"] == "ikke_betalt"
    assert o.epost.call_count == 1


async def test_siste_sjekkdag_gir_varsel_om_manglende_data_med_forklaringen(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-12-06 08:30:00+01:00")  # siste sjekkdag, etter varseltidspunktet
    _med_kopi(hass)
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11") is None
    assert len(o.varsler) >= 1
    melding = o.varsler[-1].data["message"]
    assert "identiske med 2026-10" in melding


async def test_tving_hopper_over_verne(hass, oppsett):
    o = oppsett
    _med_kopi(hass)
    p = await o.coordinator.async_generer_oppgjor("2026-11", tving=True, send_epost=False)
    assert p["snitt"] == 1.3002  # brukerens eget valg, på eget ansvar


async def test_uten_forrige_periode_i_lageret_er_det_ingen_kopi_aa_sammenligne_med(hass, oppsett):
    o = oppsett
    o.lager.fjern("2026-10")
    _med_kopi(hass)
    p = await o.coordinator.async_generer_oppgjor("2026-11", send_epost=False)
    assert p["id"] == "2026-11"


async def test_vanlige_tall_gir_oppgjoer_som_for(hass, oppsett):
    o = oppsett
    _med_riktige_tall(hass)
    p = await o.coordinator.async_generer_oppgjor("2026-11", send_epost=False)
    assert p["status"] == "ikke_betalt" and p["belop"] == 310.0


def test_feilen_er_en_vanlig_tjenestefeil_som_vises_til_brukeren():
    assert issubclass(ManglerData, ServiceValidationError)
