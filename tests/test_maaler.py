"""Tester for målerstander ved månedsskiftene: fangst, seeding, statistikk og oppgjør."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from custom_components.stromregnskap_leietaker.maaler import stand_fra_rader

from .data import NOV_HUS, OKT_HUS, SEP_HUS, sett_kilder

IMPORT = "sensor.minusmaler_leilighet_import"


def _stand(o, dato):
    return o.lager.data["maalerstander"].get(dato)


# --- rene hjelpere for statistikk ---------------------------------------------------


def test_stand_fra_rader_tar_raden_som_slutter_paa_grensen():
    t = 1_800_000_000.0
    rader = [
        {"start": t - 7200, "end": t - 3600, "state": 10.0},
        {"start": t - 3600, "end": t, "state": 12.5},
    ]
    assert stand_fra_rader(rader, t) == 12.5


def test_stand_fra_rader_uten_treff_eller_uten_verdi_gir_none():
    t = 1_800_000_000.0
    assert stand_fra_rader([], t) is None
    assert stand_fra_rader([{"start": t - 3600, "end": t - 3600 + 1800, "state": 5.0}], t) is None
    assert stand_fra_rader([{"start": t - 3600, "end": t, "state": None}], t) is None


# --- oppgjør regnes fra målerstandene ------------------------------------------------


async def test_oppgjoeret_regnes_fra_malerstandene(hass, oppsett):
    o = oppsett
    o.lager.data["maalerstander"]["2026-12-01"]["stand"] = 250.4  # 0,4 fra sensorene: innenfor
    await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p["leilighet_kwh"] == 250.4 and p["belop"] == 310.5  # 250,4 × 1,24 = 310,496
    assert "maalerstander" in p["kilde"] and p["status"] == "ikke_betalt"


async def test_malerstand_som_avviker_fra_sensorene_krever_godkjenning_med_alle_tall(hass, oppsett):
    o = oppsett
    o.lager.data["maalerstander"]["2026-12-01"]["stand"] = 253.0
    await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p["status"] == "venter_godkjenning" and o.epost.call_count == 0
    assert "253,0" in p["notat"] and "250,0" in p["notat"]
    assert p["leilighet_kwh"] == 253.0  # målerstandene er sannheten


async def test_uten_malerstander_krever_godkjenning_selv_om_sensorene_stemmer(hass, oppsett):
    o = oppsett
    o.lager.data["maalerstander"] = {}
    await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p["status"] == "venter_godkjenning" and o.epost.call_count == 0
    assert "Målerstand" in p["notat"] and "mangler" in p["notat"]
    assert p["leilighet_kwh"] == 250.0  # regnet fra sensorene som reserve


async def test_mangler_bare_startstanden_krever_det_ogsaa_godkjenning(hass, oppsett):
    o = oppsett
    del o.lager.data["maalerstander"]["2026-11-01"]
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11")["status"] == "venter_godkjenning"


async def test_tving_hopper_over_kravet_om_malerstander(hass, oppsett):
    o = oppsett
    o.lager.data["maalerstander"] = {}
    p = await o.coordinator.async_generer_oppgjor("2026-11", tving=True, send_epost=False)
    assert p["status"] == "ikke_betalt"


async def test_malerstand_som_gaar_bakover_krever_godkjenning(hass, oppsett):
    o = oppsett
    o.lager.data["maalerstander"]["2026-11-01"]["stand"] = 500.0
    o.lager.data["maalerstander"]["2026-12-01"]["stand"] = 100.0
    await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p["status"] == "venter_godkjenning" and "bakover" in p["notat"]


# --- fangst av målerstand ------------------------------------------------------------


async def test_midnatt_fanger_malerstanden_og_lagrer_den(hass, oppsett):
    o = oppsett
    del o.lager.data["maalerstander"]["2026-12-01"]
    o.freezer.move_to("2026-12-01 00:00:20+01:00")
    hass.states.async_set(IMPORT, "250.0", {})
    await o.coordinator.async_fang_maalerstand(dt_util.now())
    assert _stand(o, "2026-12-01")["stand"] == 250.0
    assert _stand(o, "2026-12-01")["kilde"] == "live"


async def test_sen_fangst_innen_to_timer_merkes_som_live_sen(hass, oppsett):
    o = oppsett
    del o.lager.data["maalerstander"]["2026-12-01"]
    o.freezer.move_to("2026-12-01 00:50:00+01:00")
    hass.states.async_set(IMPORT, "250.4", {})
    await o.coordinator.async_fang_maalerstand(dt_util.now())
    assert _stand(o, "2026-12-01")["kilde"] == "live_sen"


async def test_fangst_overskriver_aldri_en_eksisterende_avlesning(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-12-01 00:00:20+01:00")
    hass.states.async_set(IMPORT, "999.0", {})
    await o.coordinator.async_fang_maalerstand(dt_util.now())
    assert _stand(o, "2026-12-01")["stand"] == 250.0


async def test_for_sent_for_live_hentes_stand_fra_statistikk(hass, oppsett):
    o = oppsett
    del o.lager.data["maalerstander"]["2026-12-01"]
    with patch.object(o.coordinator, "_stand_fra_statistikk", AsyncMock(return_value=249.9)):
        await o.coordinator.async_fang_maalerstand(dt_util.now())  # 3. des 08:30
    assert _stand(o, "2026-12-01")["stand"] == 249.9
    assert _stand(o, "2026-12-01")["kilde"] == "statistikk"


async def test_uten_statistikk_og_for_sent_lagres_ingenting_og_ingenting_kræsjer(hass, oppsett):
    o = oppsett
    del o.lager.data["maalerstander"]["2026-12-01"]
    with patch.object(o.coordinator, "_stand_fra_statistikk", AsyncMock(return_value=None)):
        await o.coordinator.async_fang_maalerstand(dt_util.now())
    assert _stand(o, "2026-12-01") is None


async def test_utilgjengelig_maaler_ved_midnatt_gir_ingen_avlesning(hass, oppsett):
    o = oppsett
    del o.lager.data["maalerstander"]["2026-12-01"]
    o.freezer.move_to("2026-12-01 00:00:20+01:00")
    hass.states.async_set(IMPORT, "unavailable", {})
    with patch.object(o.coordinator, "_stand_fra_statistikk", AsyncMock(return_value=None)):
        await o.coordinator.async_fang_maalerstand(dt_util.now())
    assert _stand(o, "2026-12-01") is None


async def test_den_timelige_oppdateringen_sikrer_avlesningen_for_maaneden(hass, oppsett):
    o = oppsett
    del o.lager.data["maalerstander"]["2026-12-01"]
    o.freezer.move_to("2026-12-01 00:50:00+01:00")
    hass.states.async_set(IMPORT, "250.2", {})
    await o.coordinator.async_refresh()
    assert _stand(o, "2026-12-01")["stand"] == 250.2


async def test_statistikk_uten_recorder_gir_none(hass, oppsett):
    grense = dt_util.start_of_local_day(dt_util.now().date().replace(day=1))
    assert await oppsett.coordinator._stand_fra_statistikk(grense) is None


# --- seeding ----------------------------------------------------------------------------


async def test_oppstart_uten_avlesninger_bruker_startstanden_fra_oppsettet(hass, oppsett):
    o = oppsett
    o.lager.data["maalerstander"] = {}
    o.freezer.move_to("2026-11-10 12:00:00+01:00")
    await o.coordinator.async_seed_maaler()
    assert _stand(o, "2026-11-01")["stand"] == 0.0
    assert _stand(o, "2026-11-01")["kilde"] == "start"


async def test_oppstart_foretrekker_statistikk_fra_maanedsskiftet(hass, oppsett):
    o = oppsett
    o.lager.data["maalerstander"] = {}
    o.freezer.move_to("2026-11-10 12:00:00+01:00")
    with patch.object(o.coordinator, "_stand_fra_statistikk", AsyncMock(return_value=12.5)):
        await o.coordinator.async_seed_maaler()
    assert _stand(o, "2026-11-01")["stand"] == 12.5
    assert _stand(o, "2026-11-01")["kilde"] == "statistikk"


async def test_seeding_roerer_ikke_eksisterende_avlesninger(hass, oppsett):
    o = oppsett
    for_ = dict(o.lager.data["maalerstander"])
    await o.coordinator.async_seed_maaler()
    assert o.lager.data["maalerstander"] == for_


# --- manuell registrering ---------------------------------------------------------------


async def test_manuell_malerstand_lagres_og_kan_gis_som_aar_maaned(hass, oppsett):
    o = oppsett
    await o.coordinator.async_sett_malerstand("2026-12-01", 251.2)
    assert _stand(o, "2026-12-01")["stand"] == 251.2
    assert _stand(o, "2026-12-01")["kilde"] == "manuell"
    await o.coordinator.async_sett_malerstand("2026-12", 251.5)
    assert _stand(o, "2026-12-01")["stand"] == 251.5


@pytest.mark.parametrize(
    ("dato", "stand"),
    [("2026-12-15", 1.0), ("ikke-en-dato", 1.0), ("2026-13", 1.0), ("2026-12-01", -5.0)],
)
async def test_ugyldig_manuell_malerstand_avvises(hass, oppsett, dato, stand):
    with pytest.raises(ServiceValidationError):
        await oppsett.coordinator.async_sett_malerstand(dato, stand)


async def test_oppgjoeret_lagrer_avrundede_malerstander_slik_at_regnestykket_stemmer(hass, oppsett):
    o = oppsett
    o.lager.data["maalerstander"]["2026-11-01"]["stand"] = 1000.55
    o.lager.data["maalerstander"]["2026-12-01"]["stand"] = 1250.52
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, {**NOV_HUS, "leilighet_kwh": 250.0}])
    p = await o.coordinator.async_generer_oppgjor("2026-11", tving=True, send_epost=False)
    assert p["maaler_start"] == 1000.6 and p["maaler_slutt"] == 1250.5
    assert p["leilighet_kwh"] == 249.9  # 1250,5 - 1000,6
    assert p["belop"] == 309.88  # 249,9 × 1,24 = 309,876
