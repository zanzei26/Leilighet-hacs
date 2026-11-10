"""Tester for den valgfrie elbil-laderen: egen teller, samme snittpris, egen linje overalt."""

import io
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pypdf import PdfReader

from custom_components.stromregnskap_leietaker.calc import (
    Grenser,
    beregn_oppgjor,
    har_lader,
    leilighet_belop,
    maaler_forbruk,
    sjekk_rimelighet,
)
from custom_components.stromregnskap_leietaker.flow_skjema import schema_kilder, valider_kilder
from custom_components.stromregnskap_leietaker.mail import bygg_epost, bygg_kopipost
from custom_components.stromregnskap_leietaker.pdf_dokumenter import (
    bygg_fakturagrunnlag,
    bygg_regnskap,
)

from .data import CFG, LEIETAKER, NOV_HUS, UTLEIER, sett_kilder

LADER = "sensor.leilighet_levetidsforbruk"
IMPORT = "sensor.minusmaler_leilighet_import"
NOV_START = "2026-11-01"
DES_START = "2026-12-01"
NBSP = "\u00a0"


def _rad(stand, kilde="live"):
    return {"stand": stand, "kilde": kilde, "tid": "2026-12-01T00:00:20+01:00"}


def _slaa_paa(hass, o, tellere=None):
    """Slår på laderen og legger inn tellerne: 21,3 kWh i november (3073,7 → 3095,0)."""
    hass.config_entries.async_update_entry(
        o.entry, data={**o.entry.data, "lader_aktiv": True, "ent_lader": LADER}
    )
    o.lager.data["laderstander"] = deepcopy(
        tellere
        if tellere is not None
        else {NOV_START: _rad(3073.74, "start"), DES_START: _rad(3095.04)}
    )
    hass.states.async_set(LADER, "3101.04", {})


@pytest.fixture
async def med_lader(hass, oppsett):
    _slaa_paa(hass, oppsett)
    return oppsett


def _pdf(data: bytes) -> str:
    return "\n".join(s.extract_text() for s in PdfReader(io.BytesIO(data), strict=True).pages)


# --- ren beregning ----------------------------------------------------------------------------


def test_beregn_oppgjor_uten_lader_har_ingen_laderfelt():
    p = _beregn()
    assert "lader_kwh" not in p and "leilighet_belop" not in p
    assert p["belop"] == 310.0 and leilighet_belop(p) == 310.0 and not har_lader(p)


def _beregn(lader_kwh=None, leilighet_kwh=250.0, snitt=1.24):
    from datetime import datetime, timedelta, timezone

    return beregn_oppgjor(
        periode_id="2026-11",
        maned={**NOV_HUS, "snitt": snitt},
        leilighet_kwh=leilighet_kwh,
        forfallsdag=15,
        naa=datetime(2026, 12, 3, 8, 30, tzinfo=timezone(timedelta(hours=1))),
        kilde="test",
        lader_kwh=lader_kwh,
    )


def test_beregn_oppgjor_med_lader_gir_egen_linje_og_sum_av_linjene():
    p = _beregn(lader_kwh=21.3)
    assert p["leilighet_belop"] == 310.0
    assert p["lader_kwh"] == 21.3 and p["lader_belop"] == 26.41  # 21,3 × 1,24 = 26,412
    assert p["belop"] == 336.41 and har_lader(p)


def test_totalen_er_summen_av_de_avrundede_linjene_slik_at_papiret_går_opp():
    # 1,0 × 1,2345 = 1,2345 → 1,23 per linje. Samlet 2,0 × 1,2345 = 2,469 → 2,47
    # ville ikke gått opp mot linjene.
    p = _beregn(lader_kwh=1.0, leilighet_kwh=1.0, snitt=1.2345)
    assert p["leilighet_belop"] == 1.23 and p["lader_belop"] == 1.23
    assert p["belop"] == 2.46


def test_lader_med_null_forbruk_gir_belop_uendret_og_skjules():
    p = _beregn(lader_kwh=0.0)
    assert p["lader_kwh"] == 0.0 and p["lader_belop"] == 0.0 and p["belop"] == 310.0
    assert not har_lader(p)


def test_maaler_forbruk_bruker_navnet_i_feilmeldingen():
    r = maaler_forbruk(100.0, 90.0, stand="Laderens teller", enhet="Laderen")
    assert r.kwh is None
    assert r.feil.startswith("Laderens teller gikk bakover") and "Laderen kan være byttet" in r.feil
    assert maaler_forbruk(100.0, 90.0).feil.startswith("Målerstanden gikk bakover")


def test_ladere_telles_med_mot_husets_forbruk():
    felles = {
        "leilighet_kwh": 250.0,
        "hus_kwh": 300.0,
        "snitt": 1.0,
        "forrige_kwh": None,
        "grenser": Grenser(),
    }
    assert sjekk_rimelighet(**felles) == []
    brudd = sjekk_rimelighet(**felles, ekstra_kwh=60.0)
    assert len(brudd) == 1 and "og laderens 60,0 kWh" in brudd[0]


# --- oppgjør ----------------------------------------------------------------------------------


async def test_oppgjoeret_for_november_har_lader_som_egen_linje(hass, med_lader):
    o = med_lader
    p = await o.coordinator.async_generer_oppgjor("2026-11", send_epost=False)
    assert p["status"] == "ikke_betalt", p["notat"]
    assert p["leilighet_kwh"] == 250.0 and p["leilighet_belop"] == 310.0
    assert p["lader_kwh"] == 21.3 and p["lader_belop"] == 26.41 and p["belop"] == 336.41
    assert (p["lader_start"], p["lader_slutt"]) == (3073.7, 3095.0)
    assert "laderstander" in p["kilde"]
    assert o.lager.finn("2026-11")["belop"] == 336.41  # lagret


async def test_uten_lader_i_oppsettet_er_alt_som_for(hass, oppsett):
    o = oppsett
    p = await o.coordinator.async_generer_oppgjor("2026-11", send_epost=False)
    assert "lader_kwh" not in p and p["belop"] == 310.0


async def test_lader_valgt_men_ikke_slaatt_paa_gir_ingen_lader(hass, oppsett):
    o = oppsett
    hass.config_entries.async_update_entry(o.entry, data={**o.entry.data, "ent_lader": LADER})
    p = await o.coordinator.async_generer_oppgjor("2026-11", send_epost=False)
    assert "lader_kwh" not in p
    assert not o.coordinator.lader_aktiv


async def test_epost_til_leietaker_har_lader_og_riktig_sum(hass, med_lader):
    o = med_lader
    await o.coordinator.async_refresh()  # kjøredagen: oppgjøret lages og sendes
    assert o.epost.call_count == 1
    melding = o.epost.call_args.kwargs["melding"]
    tekst = melding.get_body(("plain",)).get_content()
    assert "Elbil-lader: 21,3 kWh" in tekst
    assert "Beløp leilighet: 310,00 kr" in tekst and "Beløp elbil-lader: 26,41 kr" in tekst
    assert "Beløp å betale: 336,41 kr" in tekst


async def test_laderens_teller_mangler_krever_godkjenning_og_sier_det(hass, med_lader):
    o = med_lader
    del o.lager.data["laderstander"][NOV_START]
    p = await o.coordinator.async_generer_oppgjor("2026-11", send_epost=False)
    assert p["status"] == "venter_godkjenning"
    assert "Laderens teller mangler" in p["notat"] and "uten lader" in p["notat"]
    assert "lader_kwh" not in p and p["belop"] == 310.0  # aldri gjettet


async def test_laderens_teller_som_gaar_bakover_krever_godkjenning(hass, med_lader):
    o = med_lader
    o.lager.data["laderstander"][DES_START] = _rad(10.0)
    p = await o.coordinator.async_generer_oppgjor("2026-11", send_epost=False)
    assert p["status"] == "venter_godkjenning"
    assert "Laderens teller gikk bakover" in p["notat"] and "uten lader" in p["notat"]


async def test_lader_og_leilighet_over_husets_forbruk_krever_godkjenning(hass, med_lader):
    o = med_lader
    o.lager.data["laderstander"][DES_START] = _rad(3073.74 + 2400.0)
    p = await o.coordinator.async_generer_oppgjor("2026-11", send_epost=False)
    assert p["status"] == "venter_godkjenning" and "og laderens" in p["notat"]


async def test_lader_uten_forbruk_i_maaneden_er_greit_og_gir_ingen_ekstra_beloep(hass, med_lader):
    o = med_lader
    o.lager.data["laderstander"][DES_START] = _rad(3073.74)
    p = await o.coordinator.async_generer_oppgjor("2026-11", send_epost=False)
    assert p["status"] == "ikke_betalt", p["notat"]
    assert p["lader_kwh"] == 0.0 and p["belop"] == 310.0
    assert "elbil-lader" not in (await _mail(o, p)).lower()


async def _mail(o, p):
    m = bygg_epost(periode=p, leietaker=LEIETAKER, utleier=UTLEIER, side_url=None, cc_utleier=False)
    return m.get_body(("plain",)).get_content()


async def test_tving_hopper_over_kontrollene_også_for_laderen(hass, med_lader):
    o = med_lader
    del o.lager.data["laderstander"][NOV_START]
    p = await o.coordinator.async_generer_oppgjor("2026-11", tving=True, send_epost=False)
    assert p["status"] == "ikke_betalt" and "lader_kwh" not in p


# --- målerstander for laderen -----------------------------------------------------------------


async def test_midnatt_fanger_laderens_teller_ved_siden_av_leilighetens_maaler(hass, med_lader):
    o = med_lader
    del o.lager.data["maalerstander"][DES_START]
    del o.lager.data["laderstander"][DES_START]
    o.freezer.move_to("2026-12-01 00:00:20+01:00")
    hass.states.async_set(IMPORT, "250.0", {})
    hass.states.async_set(LADER, "3095.04", {})
    await o.coordinator.async_fang_maalerstand(dt_util.now())
    assert o.lager.data["maalerstander"][DES_START]["stand"] == 250.0
    rad = o.lager.data["laderstander"][DES_START]
    assert rad["stand"] == 3095.04 and rad["kilde"] == "live"


async def test_laderens_teller_hentes_fra_statistikk_for_riktig_entitet(hass, med_lader):
    o = med_lader
    del o.lager.data["maalerstander"][DES_START]
    del o.lager.data["laderstander"][DES_START]

    async def statistikk(_grense, entitet=None):
        return {None: 250.0, IMPORT: 250.0, LADER: 3095.04}[entitet]

    with patch.object(o.coordinator, "_stand_fra_statistikk", AsyncMock(side_effect=statistikk)):
        await o.coordinator.async_fang_maalerstand(dt_util.now())  # 3. des 08:30, utenfor vinduet
    assert o.lager.data["maalerstander"][DES_START]["stand"] == 250.0
    assert o.lager.data["laderstander"][DES_START] == {
        "stand": 3095.04,
        "kilde": "statistikk",
        "tid": o.lager.data["laderstander"][DES_START]["tid"],
    }


async def test_feil_med_laderen_stopper_ikke_leilighetens_maaler(hass, med_lader):
    o = med_lader
    del o.lager.data["maalerstander"][DES_START]
    del o.lager.data["laderstander"][DES_START]

    async def statistikk(_grense, entitet=None):
        if entitet == LADER:
            raise RuntimeError("laderen er borte")
        return 250.0

    with patch.object(o.coordinator, "_stand_fra_statistikk", AsyncMock(side_effect=statistikk)):
        await o.coordinator.async_fang_maalerstand(dt_util.now())
    assert o.lager.data["maalerstander"][DES_START]["stand"] == 250.0
    assert DES_START not in o.lager.data["laderstander"]


async def test_en_lagret_lader_avlesning_overskrives_aldri(hass, med_lader):
    o = med_lader
    o.freezer.move_to("2026-12-01 00:00:20+01:00")
    hass.states.async_set(LADER, "9999.0", {})
    await o.coordinator.async_fang_maalerstand(dt_util.now())
    assert o.lager.data["laderstander"][DES_START]["stand"] == 3095.04


async def test_oppstart_henter_laderens_teller_fra_statistikk(hass, med_lader):
    o = med_lader
    o.lager.data["laderstander"] = {}
    o.freezer.move_to("2026-12-10 12:00:00+01:00")
    with patch.object(o.coordinator, "_stand_fra_statistikk", AsyncMock(return_value=3095.04)):
        await o.coordinator.async_seed_maaler()
    assert o.lager.data["laderstander"][DES_START]["kilde"] == "statistikk"


async def test_oppstart_uten_statistikk_gjetter_aldri_laderens_teller(hass, med_lader):
    o = med_lader
    o.lager.data["laderstander"] = {}
    o.freezer.move_to("2026-12-10 12:00:00+01:00")
    with patch.object(o.coordinator, "_stand_fra_statistikk", AsyncMock(return_value=None)):
        await o.coordinator.async_seed_maaler()
    assert o.lager.data["laderstander"] == {}


async def test_manuell_laderstand_lagres_i_egen_serie(hass, med_lader):
    o = med_lader
    await o.coordinator.async_sett_malerstand("2026-12", 3095.5, "lader")
    assert o.lager.data["laderstander"][DES_START]["stand"] == 3095.5
    assert o.lager.data["laderstander"][DES_START]["kilde"] == "manuell"
    assert o.lager.data["maalerstander"][DES_START]["stand"] == 250.0  # urørt


async def test_laderstand_kan_ikke_settes_når_laderen_er_av(hass, oppsett):
    with pytest.raises(ServiceValidationError, match="ikke slått på"):
        await oppsett.coordinator.async_sett_malerstand("2026-12", 3095.5, "lader")


async def test_ukjent_maaler_avvises(hass, med_lader):
    with pytest.raises(ServiceValidationError, match="Ukjent måler"):
        await med_lader.coordinator.async_sett_malerstand("2026-12", 1.0, "garasje")


# --- hittil og live ---------------------------------------------------------------------------


async def test_hittil_er_leilighet_pluss_lader(hass, med_lader):
    o = med_lader
    hass.states.async_set(IMPORT, "262.04", {})  # 262,0 - 250,0 = 12,0 kWh
    hass.states.async_set(LADER, "3101.04", {})  # 3101,0 - 3095,0 = 6,0 kWh
    await o.coordinator.async_refresh()
    d = o.coordinator.data
    assert d["leilighet_kwh_hittil"] == 12.0 and d["lader_kwh_hittil"] == 6.0
    assert d["kwh_hittil"] == 18.0
    assert d["lader_kostnad_hittil"] == 20.4  # 6,0 × 3,4
    assert d["kostnad_hittil"] == 61.2  # 40,80 + 20,40


async def test_anslaget_bygger_paa_leilighet_pluss_lader(hass, med_lader):
    o = med_lader
    o.freezer.move_to("2026-12-10 12:00:00+01:00")  # 228 av 744 timer
    hass.states.async_set(IMPORT, "262.04", {})  # 12,0 kWh
    hass.states.async_set(LADER, "3101.04", {})  # 6,0 kWh
    await o.coordinator.async_refresh()
    d = o.coordinator.data
    assert d["estimat_metode"] == "takt"
    assert d["estimat_kwh"] == pytest.approx(18.0 * 744 / 228)


async def test_anslaget_uten_laderens_teller_bruker_forrige_periode(hass, med_lader):
    o = med_lader
    o.freezer.move_to("2026-12-10 12:00:00+01:00")
    hass.states.async_set(IMPORT, "262.04", {})
    hass.states.async_set(LADER, "unavailable", {})
    await o.coordinator.async_refresh()
    assert o.coordinator.data["estimat_metode"] == "forrige_periode"


async def test_hittil_uten_laderens_teller_viser_bare_leiligheten(hass, med_lader):
    o = med_lader
    hass.states.async_set(IMPORT, "262.04", {})
    hass.states.async_set(LADER, "unavailable", {})
    await o.coordinator.async_refresh()
    d = o.coordinator.data
    assert d["lader_kwh_hittil"] is None and d["kwh_hittil"] == 12.0
    assert d["kostnad_hittil"] == 40.8


async def test_hittil_uten_snittpris_gir_lader_kwh_men_ingen_kostnad(hass, med_lader):
    o = med_lader
    hass.states.async_set(IMPORT, "262.04", {})
    sett_kilder(hass, denne={"mnd": "2026-11"})  # regnskapssensoren viser en annen måned
    hass.states.async_set(IMPORT, "262.04", {})
    hass.states.async_set(LADER, "3101.04", {})
    await o.coordinator.async_refresh()
    d = o.coordinator.data
    assert d["lader_kwh_hittil"] == 6.0 and d["lader_kostnad_hittil"] is None
    assert d["kostnad_hittil"] is None


async def test_siden_viser_lader_hittil(hass, med_lader):
    o = med_lader
    hass.states.async_set(IMPORT, "262.04", {})
    await o.coordinator.async_refresh()
    html = o.coordinator.bygg_side_html(dt_util.now())
    assert "Herav elbil-lader" in html
    assert "6,0 kWh / 20,40 kr" in html
    assert "18,0 kWh" in html and "61,20 kr" in html


async def test_siden_viser_lader_i_historikken_bare_når_den_har_forbruk(hass, med_lader):
    o = med_lader
    p = await o.coordinator.async_generer_oppgjor("2026-11", send_epost=False)
    html = o.coordinator.bygg_side_html(dt_util.now())
    assert '+ elbil-lader <span class="nb">21,3 kWh</span>' in html and "336,41" in html
    assert "Elbil-laderen har sin egen teller" in html
    assert p["belop"] == 336.41


async def test_siden_skjuler_lader_i_historikken_når_den_ikke_har_forbruk(hass, med_lader):
    o = med_lader
    o.lager.data["laderstander"][DES_START] = _rad(3073.74)  # ingen lading i november
    p = await o.coordinator.async_generer_oppgjor("2026-11", send_epost=False)
    html = o.coordinator.bygg_side_html(dt_util.now())
    assert p["lader_kwh"] == 0.0 and "+ elbil-lader" not in html
    assert "Elbil-laderen har sin egen teller" not in html


def test_kildeentiteter_har_laderen_bare_når_den_er_på(hass, oppsett):
    o = oppsett
    assert LADER not in o.coordinator.kildeentiteter()
    _slaa_paa(hass, o)
    assert LADER in o.coordinator.kildeentiteter()


async def test_sensoren_oppdateres_med_en_gang_når_laderens_teller_endrer_seg(hass, integrasjon):
    entry = integrasjon.entry
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "lader_aktiv": True, "ent_lader": LADER}
    )
    hass.states.async_set(LADER, "3090.0", {})
    await hass.async_block_till_done()  # oppdateringen laster integrasjonen på nytt
    koordinator = entry.runtime_data.coordinator
    koordinator.lager.data["laderstander"]["2026-11-01"] = _rad(3080.0)
    hass.states.async_set(LADER, "3084.04", {})
    await hass.async_block_till_done()
    stat = hass.states.get("sensor.leietaker_forbruk_hittil")
    assert stat.attributes["lader_kwh_hittil"] == 4.0
    assert stat.state == "34.3"  # 30,3 fra leilighetens måler + 4,0 fra laderen


async def test_attributtene_finnes_også_når_laderen_er_av(hass, integrasjon):
    attr = hass.states.get("sensor.leietaker_forbruk_hittil").attributes
    assert attr["lader_kwh_hittil"] is None and attr["lader_kostnad_hittil"] is None
    assert attr["leilighet_kwh_hittil"] == 30.3


# --- datagrunnlag -----------------------------------------------------------------------------


async def test_datagrunnlaget_sier_fra_om_utilgjengelig_lader(hass, med_lader):
    o = med_lader
    hass.states.async_set(LADER, "unavailable", {})
    problemer = o.coordinator.vurder_datagrunnlag(dt_util.now())
    assert any("Laderens teller" in p and "utilgjengelig" in p for p in problemer)


async def test_datagrunnlaget_sier_fra_om_manglende_laderstand_ved_maanedsskiftet(hass, med_lader):
    o = med_lader
    del o.lager.data["laderstander"][DES_START]
    problemer = o.coordinator.vurder_datagrunnlag(dt_util.now())
    assert any("Laderens teller ved månedsskiftet 01.12.2026 mangler" in p for p in problemer)


async def test_datagrunnlaget_ignorerer_laderen_når_den_er_av(hass, oppsett):
    o = oppsett
    o.lager.data["laderstander"] = {}
    hass.states.async_set(LADER, "unavailable", {})
    assert not [p for p in o.coordinator.vurder_datagrunnlag(dt_util.now()) if "lader" in p.lower()]


# --- lagring ----------------------------------------------------------------------------------


async def test_laderstander_overlever_ny_leietaker(hass, med_lader):
    o = med_lader
    await o.coordinator.async_generer_oppgjor("2026-11", send_epost=False)
    o.lager.tom_historikk()
    assert o.lager.data["laderstander"][NOV_START]["stand"] == 3073.74


# --- dokumenter -------------------------------------------------------------------------------


@pytest.fixture
def periode_med_lader():
    return _beregn(lader_kwh=21.3)


def test_fakturagrunnlaget_har_lader_som_egen_linje_paa_en_side(periode_med_lader):
    p = {**periode_med_lader, "maaler_start": 0.0, "maaler_slutt": 250.0}
    p |= {"lader_start": 3073.7, "lader_slutt": 3095.0}
    from datetime import datetime, timedelta, timezone

    naa = datetime(2026, 12, 3, 8, 30, tzinfo=timezone(timedelta(hours=1)))
    data = bygg_fakturagrunnlag(p, LEIETAKER, UTLEIER, naa)
    leser = PdfReader(io.BytesIO(data), strict=True)
    assert len(leser.pages) == 1
    t = _pdf(data).replace(NBSP, " ")
    for forventet in (
        "Ditt forbruk i leiligheten",
        "Elbil-laderens teller 01.11.2026",
        "3 073,7 kWh",
        "3 095,0 kWh",
        "Forbruk elbil-lader i perioden",
        "21,3 kWh",
        "Elbil-lader (samme snittpris):",
        "21,3 kWh × 1,2400 kr/kWh = 26,41 kr",
        "250,0 kWh × 1,2400 kr/kWh = 310,00 kr",
        "336,41 kr",
    ):
        assert forventet in t, forventet
    assert "336,41 kr" in t.split("Beløp å betale")[1]


def test_fakturagrunnlaget_uten_lader_er_uendret(periode_med_lader):
    from datetime import datetime, timedelta, timezone

    naa = datetime(2026, 12, 3, 8, 30, tzinfo=timezone(timedelta(hours=1)))
    t = _pdf(bygg_fakturagrunnlag(_beregn(), LEIETAKER, UTLEIER, naa))
    assert "lader" not in t.lower() and "Ditt forbruk i perioden" in t


def test_regnskapet_har_laderkolonne_bare_når_en_periode_har_lader(periode_med_lader):
    from datetime import datetime, timedelta, timezone

    naa = datetime(2026, 12, 3, 8, 30, tzinfo=timezone(timedelta(hours=1)))
    uten = {**_beregn(), "id": "2026-10", "start": "2026-10-01", "slutt": "2026-11-01"}
    uten["forfall"] = "2026-11-15"
    uten["status"] = "betalt"
    med = {**periode_med_lader, "status": "ikke_betalt"}
    t = _pdf(bygg_regnskap([uten, med], LEIETAKER, UTLEIER, naa)).replace(NBSP, " ")
    assert "Lader kWh" in t and "Leilighet kWh" in t and "21,3" in t and "336,41" in t
    assert "–" in t  # oktober hadde ingen lader
    t2 = _pdf(bygg_regnskap([uten], LEIETAKER, UTLEIER, naa))
    assert "lader" not in t2.lower()


def test_epost_med_lader_er_riktig_i_både_tekst_og_html(periode_med_lader):
    m = bygg_epost(periode=periode_med_lader, leietaker=LEIETAKER, utleier=UTLEIER, side_url=None)
    html = m.get_body(("html",)).get_content()
    assert "Elbil-lader" in html and "26,41 kr" in html and "336,41 kr" in html


def test_kopien_til_utleier_nevner_laderen(periode_med_lader):
    m = bygg_kopipost(
        periode=periode_med_lader,
        leietaker=LEIETAKER,
        utleier=UTLEIER,
        vedlegg=[("a.pdf", "application/pdf", b"%PDF")],
    )
    tekst = m.get_body(("plain",)).get_content()
    assert "Elbil-lader: 21,3 kWh × 1,2400 kr/kWh = 26,41 kr" in tekst
    assert "Beløp: 336,41 kr" in tekst


# --- oppsett ----------------------------------------------------------------------------------


def test_kildeskjemaet_har_valgfri_lader():
    nokler = {str(k): k for k in schema_kilder({}).schema}
    assert "lader_aktiv" in nokler and "ent_lader" in nokler
    assert not isinstance(nokler["ent_lader"].default, str)  # ingen forhåndsvalgt sensor


def test_kildeskjemaet_husker_valgt_lader():
    nokler = {str(k): k for k in schema_kilder({"ent_lader": LADER, "lader_aktiv": True}).schema}
    assert nokler["ent_lader"].description == {"suggested_value": LADER}


async def test_validering_krever_laderens_teller_når_laderen_er_på(hass):
    from pytest_homeassistant_custom_component.common import async_mock_service

    async_mock_service(hass, "notify", "varsle_utleier")
    inn = {"varsel_tjeneste": "notify.varsle_utleier", "lader_aktiv": True}
    assert valider_kilder(hass, inn) == {"ent_lader": "lader_mangler"}
    assert valider_kilder(hass, {**inn, "ent_lader": LADER}) == {}
    assert valider_kilder(hass, {**inn, "lader_aktiv": False}) == {}


async def test_valgflyten_slår_på_laderen(hass):
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
        async_mock_service,
    )

    from custom_components.stromregnskap_leietaker.const import DOMAIN

    async_mock_service(hass, "notify", "varsle_utleier")
    entry = MockConfigEntry(domain=DOMAIN, data=dict(CFG), entry_id="e1")
    entry.add_to_hass(hass)
    skjema = {
        k: CFG[k]
        for k in (
            "ent_regnskap",
            "ent_utility",
            "ent_import",
            "maaler_start_stand",
            "ent_effekt",
            "ent_prognose",
            "varsel_tjeneste",
        )
    }
    with patch("custom_components.stromregnskap_leietaker.async_setup_entry", return_value=True):
        r = await hass.config_entries.options.async_init(entry.entry_id)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"next_step_id": "kilder"}
        )
        feil = await hass.config_entries.options.async_configure(
            r["flow_id"], {**skjema, "lader_aktiv": True}
        )
        assert feil["type"] is FlowResultType.FORM and feil["errors"] == {
            "ent_lader": "lader_mangler"
        }
        ok = await hass.config_entries.options.async_configure(
            feil["flow_id"], {**skjema, "lader_aktiv": True, "ent_lader": LADER}
        )
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data["lader_aktiv"] is True and entry.data["ent_lader"] == LADER
    assert config_entries.ConfigEntryState is not None


def test_laderlinjen_i_historikken_kan_brytes(periode_med_lader):
    """Målt i nettleser: en linje som ikke kan brytes gjorde tabellen 26-66 px for bred på mobil."""
    from custom_components.stromregnskap_leietaker.page import render_side

    from .data import side_ctx

    html = render_side(side_ctx(perioder=[{**periode_med_lader, "status": "ikke_betalt"}]))
    linje = html.split("+ elbil-lader")[0].rsplit("<span", 1)[1]
    assert "nb" not in linje  # selve linjen kan brytes; bare tallet holdes samlet
    assert '<span class="nb">21,3 kWh</span>' in html
