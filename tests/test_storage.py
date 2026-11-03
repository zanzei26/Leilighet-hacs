"""Tester for lagringslaget: fast nøkkel, flytting, sikkerhetskopier og gjenoppretting."""

import json
from unittest.mock import patch

import pytest

from custom_components.stromregnskap_leietaker.storage import Lager, standard_data

from .data import OKT, SEP

NOKKEL = "stromregnskap_leietaker"
GAMMEL_NOKKEL = "stromregnskap_leietaker.entry123"


@pytest.fixture(autouse=True)
def config_i_tmp(hass, tmp_path):
    """Skriv ikke sikkerhetskopier inn i testpakken."""
    hass.config.config_dir = str(tmp_path)
    return tmp_path


def _kopier(tmp_path):
    return sorted((tmp_path / "stromregnskap_leietaker" / "sikkerhetskopi").glob("data-*.json"))


async def test_tom_lagring_gir_standarddata(hass, hass_storage):
    lager = Lager(hass, "entry123")
    await lager.async_last()
    assert {k: v for k, v in lager.data.items() if k != "tilstand"} == {
        k: v for k, v in standard_data().items() if k != "tilstand"
    }
    assert lager.data["perioder"] == []
    assert lager.data["maalerstander"] == {} and lager.data["snapshots"] == {}
    assert lager.tilstand["historikk_importert"] is False


async def test_opprettet_settes_en_gang(hass, hass_storage, freezer):
    freezer.move_to("2026-11-03 12:00:00+01:00")
    lager = Lager(hass, "entry123")
    await lager.async_last()
    forste = lager.tilstand["opprettet"]
    assert forste.startswith("2026-11-03")
    freezer.move_to("2026-12-03 12:00:00+01:00")
    ny = Lager(hass, "entry123")
    await lager.async_lagre()
    await ny.async_last()
    assert ny.tilstand["opprettet"] == forste


async def test_noekkelen_er_fast_og_uavhengig_av_entry_id(hass, hass_storage):
    lager = Lager(hass, "entry123")
    await lager.async_last()
    lager.legg_til(dict(OKT))
    await lager.async_lagre()
    assert NOKKEL in hass_storage and hass_storage[NOKKEL]["version"] == 1

    annen_entry = Lager(hass, "helt-annen-id")  # fjernet og lagt til på nytt
    await annen_entry.async_last()
    assert [p["id"] for p in annen_entry.perioder] == ["2026-10"]


async def test_data_fra_gammel_noekkel_flyttes_og_lagres_under_den_nye(hass, hass_storage):
    hass_storage[GAMMEL_NOKKEL] = {
        "version": 1,
        "minor_version": 1,
        "key": GAMMEL_NOKKEL,
        "data": {"perioder": [dict(SEP), dict(OKT)], "tilstand": {"historikk_importert": True}},
    }
    lager = Lager(hass, "entry123")
    await lager.async_last()
    assert [p["id"] for p in lager.perioder] == ["2026-09", "2026-10"]
    assert lager.tilstand["historikk_importert"] is True
    assert lager.migrert_fra_gammel is True
    assert NOKKEL in hass_storage  # lagret under ny nøkkel med en gang
    assert [p["id"] for p in hass_storage[NOKKEL]["data"]["perioder"]] == ["2026-09", "2026-10"]


async def test_sikkerhetskopi_skrives_ved_hver_lagring(hass, hass_storage, config_i_tmp):
    lager = Lager(hass, "entry123")
    await lager.async_last()
    lager.legg_til(dict(OKT))
    await lager.async_lagre()
    kopier = _kopier(config_i_tmp)
    assert len(kopier) == 1
    innhold = json.loads(kopier[0].read_text(encoding="utf-8"))
    assert [p["id"] for p in innhold["data"]["perioder"]] == ["2026-10"]
    assert lager.siste_kopi and lager.kopi_feil is None


async def test_mangler_hovedlageret_gjenopprettes_fra_siste_kopi(hass, hass_storage):
    lager = Lager(hass, "entry123")
    await lager.async_last()
    lager.legg_til(dict(SEP))
    lager.legg_til(dict(OKT))
    await lager.async_lagre()

    hass_storage.pop(NOKKEL)  # lagringsfilen er borte eller ødelagt (HA flytter den til side)
    ny = Lager(hass, "entry123")
    await ny.async_last()
    assert [p["id"] for p in ny.perioder] == ["2026-09", "2026-10"]
    assert ny.gjenopprettet_fra and ny.gjenopprettet_fra.startswith("data-")
    assert NOKKEL in hass_storage  # og er lagret tilbake


async def test_gyldig_hovedlager_overstyres_aldri_av_kopier(hass, hass_storage):
    lager = Lager(hass, "entry123")
    await lager.async_last()
    lager.legg_til(dict(OKT))
    await lager.async_lagre()
    lager.fjern("2026-10")  # brukeren slettet bevisst
    await lager.async_lagre()

    ny = Lager(hass, "entry123")
    await ny.async_last()
    assert ny.perioder == [] and ny.gjenopprettet_fra is None


async def test_ingen_lager_og_ingen_kopi_starter_tomt(hass, hass_storage):
    lager = Lager(hass, "entry123")
    await lager.async_last()
    assert lager.perioder == [] and lager.gjenopprettet_fra is None


async def test_feil_ved_sikkerhetskopi_stopper_ikke_lagringen(hass, hass_storage):
    lager = Lager(hass, "entry123")
    await lager.async_last()
    lager.legg_til(dict(OKT))
    with patch(
        "custom_components.stromregnskap_leietaker.storage.skriv_kopi",
        side_effect=OSError("disken er full"),
    ):
        await lager.async_lagre()  # skal ikke kaste
    assert "disken er full" in lager.kopi_feil
    assert [p["id"] for p in hass_storage[NOKKEL]["data"]["perioder"]] == [
        "2026-10"
    ]  # lagret likevel
    await lager.async_lagre()
    assert lager.kopi_feil is None  # og nullstilles når det virker igjen


async def test_migrering_fyller_inn_manglende_felt_og_beholder_perioder(hass, hass_storage):
    hass_storage[NOKKEL] = {
        "version": 1,
        "minor_version": 0,
        "key": NOKKEL,
        "data": {"perioder": [dict(SEP)]},
    }
    lager = Lager(hass, "entry123")
    await lager.async_last()
    assert [p["id"] for p in lager.perioder] == ["2026-09"]
    assert lager.data["leietaker"] == {} and lager.data["maalerstander"] == {}


async def test_nyere_hovedversjon_avvises(hass, hass_storage):
    hass_storage[NOKKEL] = {"version": 2, "minor_version": 0, "key": NOKKEL, "data": {}}
    lager = Lager(hass, "entry123")
    with pytest.raises(NotImplementedError):
        await lager.async_last()


async def test_perioder_holdes_sortert_og_unike(hass, hass_storage):
    lager = Lager(hass, "entry123")
    await lager.async_last()
    lager.legg_til(dict(OKT))
    lager.legg_til(dict(SEP))
    assert [p["id"] for p in lager.perioder] == ["2026-09", "2026-10"]
    with pytest.raises(ValueError):
        lager.legg_til(dict(OKT))


async def test_finn_og_fjern(hass, hass_storage):
    lager = Lager(hass, "entry123")
    await lager.async_last()
    lager.legg_til(dict(OKT))
    assert lager.finn("2026-10")["belop"] == 304.25
    assert lager.finn("2099-01") is None
    assert lager.fjern("2026-10") is True
    assert lager.fjern("2026-10") is False


async def test_tom_historikk_beholder_importflagg_og_maalerstander(hass, hass_storage):
    lager = Lager(hass, "entry123")
    await lager.async_last()
    lager.tilstand["historikk_importert"] = True
    lager.tilstand["varslet"] = ["x"]
    lager.data["maalerstander"]["2026-11-01"] = {"stand": 0.0}
    lager.legg_til(dict(OKT))
    lager.tom_historikk()
    assert lager.data["perioder"] == [] and lager.tilstand["varslet"] == []
    assert lager.tilstand["historikk_importert"] is True
    assert lager.data["maalerstander"]["2026-11-01"]["stand"] == 0.0  # måleren glemmer vi aldri


async def test_uendrede_data_gir_ikke_en_ny_kopi(hass, hass_storage, config_i_tmp):
    lager = Lager(hass, "entry123")
    await lager.async_last()
    lager.legg_til(dict(OKT))
    await lager.async_lagre()
    await lager.async_lagre()
    await lager.async_lagre()
    assert len(_kopier(config_i_tmp)) == 1
    lager.fjern("2026-10")
    await lager.async_lagre()
    assert len(_kopier(config_i_tmp)) == 2
