"""Tester for lagringslaget (Store med versjonering og migrering)."""

import pytest

from custom_components.stromregnskap_leietaker.storage import Lager, standard_data

from .data import OKT, SEP

NOKKEL = "stromregnskap_leietaker.entry123"


async def test_tom_lagring_gir_standarddata(hass, hass_storage):
    lager = Lager(hass, "entry123")
    await lager.async_last()
    assert lager.data == standard_data()
    assert lager.data["perioder"] == []
    assert lager.data["tilstand"]["historikk_importert"] is False


async def test_lagring_bruker_noekkel_med_entry_id_og_overlever_omlasting(hass, hass_storage):
    lager = Lager(hass, "entry123")
    await lager.async_last()
    lager.legg_til(dict(OKT))
    await lager.async_lagre()
    assert NOKKEL in hass_storage
    assert hass_storage[NOKKEL]["version"] == 1

    ny = Lager(hass, "entry123")
    await ny.async_last()
    assert [p["id"] for p in ny.data["perioder"]] == ["2026-10"]


async def test_migrering_fyller_inn_manglende_felt_og_beholder_perioder(hass, hass_storage):
    hass_storage[NOKKEL] = {
        "version": 1,
        "minor_version": 0,
        "key": NOKKEL,
        "data": {"perioder": [dict(SEP)]},
    }
    lager = Lager(hass, "entry123")
    await lager.async_last()
    assert [p["id"] for p in lager.data["perioder"]] == ["2026-09"]
    assert lager.data["tilstand"] == standard_data()["tilstand"]
    assert lager.data["leietaker"] == {}


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
    assert [p["id"] for p in lager.data["perioder"]] == ["2026-09", "2026-10"]
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
    assert lager.data["perioder"] == []


async def test_tomm_historikk_beholder_importflagg(hass, hass_storage):
    lager = Lager(hass, "entry123")
    await lager.async_last()
    lager.data["tilstand"]["historikk_importert"] = True
    lager.data["tilstand"]["varslet"] = ["x"]
    lager.legg_til(dict(OKT))
    lager.tom_historikk()
    assert lager.data["perioder"] == []
    assert lager.data["tilstand"]["varslet"] == []
    assert lager.data["tilstand"]["historikk_importert"] is True
