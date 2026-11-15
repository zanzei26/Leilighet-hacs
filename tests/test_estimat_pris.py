"""Prisen i månedsanslaget: husets kostnadsprognose (kr ÷ kWh) når den finnes, ellers forrige snitt.

Alle tall her er oppdiktede. Oppgjøret (den 3.) bruker faktisk snitt for avsluttet måned og
skal ikke påvirkes av prognosen.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.stromregnskap_leietaker.calc import (
    ESTIMAT_FORRIGE,
    ESTIMAT_INGEN,
    ESTIMAT_PRIS_FORRIGE,
    ESTIMAT_PRIS_PROGNOSE,
    ESTIMAT_TAKT,
    Grenser,
    velg_estimat,
)
from custom_components.stromregnskap_leietaker.page import render_side

from .data import DENNE_DES, sett_kilder, side_ctx

OSLO_TZ = ZoneInfo("Europe/Oslo")
GRENSER = Grenser(snitt_min=0.40, snitt_maks=3.00, endring_maks_prosent=80.0)
PROGNOSE = "sensor.jarvis_stromkostnad_prognose"


def _t(*args):
    return datetime(*args, tzinfo=OSLO_TZ)


# --- rene beregninger (calc) ------------------------------------------------------------------

MIDT = _t(2026, 11, 16, 0)  # 360 av 720 timer: 120 kWh hittil gir 240 kWh


def test_takt_med_prognose_bruker_kostnad_delt_paa_kwh_som_pris():
    e = velg_estimat(
        MIDT, 120.0, 200.0, 1.30, 10, prognose_kr=3600.0, prognose_kwh=2900.0, grenser=GRENSER
    )
    assert e.metode == ESTIMAT_TAKT and e.kwh == pytest.approx(240.0)
    assert e.pris == 1.2414  # 3600 ÷ 2900, avrundet til fire desimaler som snittprisen
    assert e.pris_kilde == ESTIMAT_PRIS_PROGNOSE
    assert e.kr == 297.94  # 240 × 1,2414


def test_takt_uten_prognose_bruker_forrige_snitt():
    e = velg_estimat(MIDT, 120.0, 200.0, 1.30, 10, grenser=GRENSER)
    assert e.metode == ESTIMAT_TAKT
    assert (e.pris, e.pris_kilde, e.kr) == (1.30, ESTIMAT_PRIS_FORRIGE, 312.0)


@pytest.mark.parametrize(
    ("kr", "kwh"),
    [
        (None, 2900.0),  # kostnaden mangler
        (3600.0, None),  # kWh mangler
        (0.0, 2900.0),  # null kostnad
        (3600.0, 0.0),  # null kWh (og ingen deling på null)
        (-3600.0, 2900.0),  # negativ kostnad
        (3600.0, -2900.0),  # negativt forbruk
    ],
)
def test_prognose_som_mangler_er_null_eller_negativ_gir_forrige_snitt(kr, kwh):
    e = velg_estimat(
        MIDT, 120.0, 200.0, 1.30, 10, prognose_kr=kr, prognose_kwh=kwh, grenser=GRENSER
    )
    assert (e.pris, e.pris_kilde) == (1.30, ESTIMAT_PRIS_FORRIGE)


@pytest.mark.parametrize(
    ("kr", "kwh"),
    [(1000.0, 3000.0), (9300.0, 3000.0)],  # 0,3333 og 3,10: utenfor 0,40–3,00
)
def test_prognosepris_utenfor_grensene_for_snittpris_gir_forrige_snitt(kr, kwh):
    e = velg_estimat(
        MIDT, 120.0, 200.0, 1.30, 10, prognose_kr=kr, prognose_kwh=kwh, grenser=GRENSER
    )
    assert (e.pris, e.pris_kilde) == (1.30, ESTIMAT_PRIS_FORRIGE)


@pytest.mark.parametrize(("kr", "kwh", "pris"), [(1200.0, 3000.0, 0.40), (9000.0, 3000.0, 3.00)])
def test_grensene_for_snittpris_er_inklusive(kr, kwh, pris):
    e = velg_estimat(
        MIDT, 120.0, 200.0, 1.30, 10, prognose_kr=kr, prognose_kwh=kwh, grenser=GRENSER
    )
    assert (e.pris, e.pris_kilde) == (pris, ESTIMAT_PRIS_PROGNOSE)


def test_uten_grenser_er_det_bare_krav_om_positive_tall():
    e = velg_estimat(MIDT, 120.0, 200.0, 1.30, 10, prognose_kr=100.0, prognose_kwh=1000.0)
    assert (e.pris, e.pris_kilde) == (0.10, ESTIMAT_PRIS_PROGNOSE)


def test_foer_72_timer_brukes_forrige_periode_og_forrige_snitt_selv_med_prognose():
    foer = _t(2026, 11, 3, 23, 59)
    e = velg_estimat(
        foer, 30.0, 200.0, 1.30, 10, prognose_kr=3600.0, prognose_kwh=2900.0, grenser=GRENSER
    )
    assert e.metode == ESTIMAT_FORRIGE
    assert e.kwh == pytest.approx(220.0)  # 200 × 1,10
    assert (e.pris, e.pris_kilde, e.kr) == (1.30, ESTIMAT_PRIS_FORRIGE, 286.0)


def test_uten_forrige_periode_er_det_ingen_anslag_og_ingen_pris():
    e = velg_estimat(
        MIDT, 120.0, None, None, 10, prognose_kr=3600.0, prognose_kwh=2900.0, grenser=GRENSER
    )
    assert e[:3] == (None, None, ESTIMAT_INGEN)
    assert (e.pris, e.pris_kilde) == (None, None)


# --- koordinatoren og sensorene ----------------------------------------------------------------


def _novemberkilder(hass):
    sett_kilder(
        hass,
        denne={**DENNE_DES, "mnd": "2026-11", "snitt": 1.5, "leilighet_kr": 40.0},
        utility="30.25",
    )  # 30,3 kWh hittil på 228 av 720 timer: takt 95,68 kWh


def _prognose(hass, kr="3600", kwh=2900, entity=PROGNOSE):
    hass.states.async_set(entity, kr, {"kwh_prognose": kwh} if kwh is not None else {})


async def test_koordinatoren_bruker_husets_prognose_som_pris_i_takten(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-11-10 12:00:00+01:00")
    _novemberkilder(hass)
    _prognose(hass)
    await o.coordinator.async_refresh()
    d = o.coordinator.data
    assert d["estimat_metode"] == "takt"
    assert d["estimat_pris"] == 1.2414 and d["estimat_pris_kilde"] == "husets_prognose"
    assert d["estimat_kr"] == 118.78  # 95,68 kWh × 1,2414


async def test_uten_prognosesensor_brukes_forrige_snitt(hass, oppsett):
    o = oppsett  # sensoren finnes ikke i denne installasjonen
    o.freezer.move_to("2026-11-10 12:00:00+01:00")
    _novemberkilder(hass)
    await o.coordinator.async_refresh()
    d = o.coordinator.data
    assert d["estimat_pris"] == 1.3002 and d["estimat_pris_kilde"] == "forrige_periode"
    assert d["estimat_kr"] == 124.41  # som før: 95,68 × 1,3002


@pytest.mark.parametrize("tilstand", ["unavailable", "unknown", "ikke et tall"])
async def test_utilgjengelig_prognosesensor_gir_forrige_snitt(hass, oppsett, tilstand):
    o = oppsett
    o.freezer.move_to("2026-11-10 12:00:00+01:00")
    _novemberkilder(hass)
    _prognose(hass, kr=tilstand)
    await o.coordinator.async_refresh()
    assert o.coordinator.data["estimat_pris_kilde"] == "forrige_periode"


async def test_prognosesensor_uten_kwh_attributt_gir_forrige_snitt(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-11-10 12:00:00+01:00")
    _novemberkilder(hass)
    _prognose(hass, kwh=None)
    await o.coordinator.async_refresh()
    assert o.coordinator.data["estimat_pris_kilde"] == "forrige_periode"


async def test_prognosepris_utenfor_grensene_i_oppsettet_gir_forrige_snitt(hass, oppsett):
    o = oppsett  # grensene i testoppsettet er snittpris 0,50–3,00
    o.freezer.move_to("2026-11-10 12:00:00+01:00")
    _novemberkilder(hass)
    _prognose(hass, kr="900", kwh=3000)  # 0,30
    await o.coordinator.async_refresh()
    assert o.coordinator.data["estimat_pris_kilde"] == "forrige_periode"


async def test_tom_innstilling_skrur_av_bruken_av_prognosen(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-11-10 12:00:00+01:00")
    _novemberkilder(hass)
    _prognose(hass)
    hass.config_entries.async_update_entry(
        o.entry, data={**o.entry.data, "ent_kostnadsprognose": ""}
    )
    await o.coordinator.async_refresh()
    assert o.coordinator.data["estimat_pris_kilde"] == "forrige_periode"


async def test_annen_entitet_i_innstillingen_brukes(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-11-10 12:00:00+01:00")
    _novemberkilder(hass)
    _prognose(hass)  # standard sensor: skal ikke brukes
    _prognose(hass, kr="3000", kwh=2500, entity="sensor.min_prognose")  # 1,20
    hass.config_entries.async_update_entry(
        o.entry, data={**o.entry.data, "ent_kostnadsprognose": "sensor.min_prognose"}
    )
    await o.coordinator.async_refresh()
    assert o.coordinator.data["estimat_pris"] == 1.2


async def test_de_tre_foerste_doegnene_beholder_forrige_snitt_selv_med_prognose(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-11-02 12:00:00+01:00")
    _prognose(hass)
    await o.coordinator.async_refresh()
    d = o.coordinator.data
    assert d["estimat_metode"] == "forrige_periode"
    assert d["estimat_pris"] == 1.3002 and d["estimat_pris_kilde"] == "forrige_periode"


async def test_oppgjoeret_den_3_paavirkes_ikke_av_prognosen(hass, oppsett):
    o = oppsett  # 3. desember: novemberoppgjøret lages av regnskapssensorens snitt (1,24)
    _prognose(hass, kr="9999", kwh=1000)  # en vilt annen pris, 9,999
    await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p["snitt"] == 1.24 and p["belop"] == 310.0
    assert "estimat_pris" not in p and "pris_kilde" not in p


async def test_sensorene_har_pris_og_kilde_som_attributter_og_foelger_prognosen_live(
    hass, integrasjon
):
    estimat = "sensor.leietaker_estimat_maned"
    hittil = "sensor.leietaker_forbruk_hittil"
    a = hass.states.get(estimat).attributes
    assert a["estimat_pris"] == 1.3002 and a["estimat_pris_kilde"] == "forrige_periode"

    _prognose(hass)  # 3600 ÷ 2900
    await hass.async_block_till_done()
    for entitet in (estimat, hittil):
        a = hass.states.get(entitet).attributes
        assert a["estimat_pris"] == 1.2414 and a["estimat_pris_kilde"] == "husets_prognose"
    assert hass.states.get(estimat).state == "118.78"


# --- siden ---------------------------------------------------------------------------------


def _side(**estimat):
    return render_side(side_ctx(estimat={"kwh": 285.48, "kr": 354.38, **estimat}))


def test_siden_forklarer_at_prisen_er_husets_forventede_snittpris():
    html = _side(pris=1.2414, pris_kilde="husets_prognose")
    assert "ca. 285 kWh" in html
    assert "1,2414 kr/kWh" in html
    assert "forventede snittpris" in html


def test_siden_forklarer_at_prisen_er_forrige_maaneds_snittpris():
    html = _side(pris=1.3002, pris_kilde="forrige_periode")
    assert "1,3002 kr/kWh" in html and "forrige måneds snittpris" in html
    assert "forventede snittpris" not in html


def test_siden_uten_prisopplysning_er_som_for():
    html = _side()  # eldre kontekst uten pris
    assert "ca. 285 kWh" in html
    assert "kr/kWh" not in html.split("Anslått for hele måneden")[1].split("Oppdatert")[0]
