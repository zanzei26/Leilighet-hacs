"""Tester for øyeblikksbilder av kildetallene og bruken av dem som reserve."""

from datetime import timedelta

from .data import DENNE_DES, NOV_HUS, OKT_HUS, SEP_HUS, sett_kilder

SNAP_NOV = {
    "tid": "2026-11-30T20:00:00+01:00",
    "maned": {
        "mnd": "2026-11",
        "kwh": 2500.0,
        "kraft": 4700.0,
        "nettleie": 1800.0,
        "norgespris": 3400.0,
        "sum": 3100.0,
        "snitt": 1.24,
    },
    "utility": 249.8,
    "maaler": 249.8,
}


def _snap(o, mnd):
    return o.lager.data["snapshots"].get(mnd)


# --- å ta bilder -------------------------------------------------------------------------


async def test_den_timelige_oppdateringen_tar_bilde_av_denne_maneden(hass, oppsett):
    o = oppsett
    await o.coordinator.async_refresh()
    s = _snap(o, "2026-12")
    assert s["maned"]["kwh"] == 50.0 and s["maned"]["snitt"] == 3.4
    assert s["tid"].startswith("2026-12-03T08:30")
    assert s["maaler"] == 21.85  # standard fra sett_kilder


async def test_nytt_bilde_tas_ikke_oftere_enn_hver_sjette_time(hass, oppsett):
    o = oppsett
    await o.coordinator.async_refresh()
    sett_kilder(hass, denne={**DENNE_DES, "kwh": 60.0})
    o.freezer.tick(timedelta(hours=1))
    await o.coordinator.async_refresh()
    assert _snap(o, "2026-12")["maned"]["kwh"] == 50.0
    o.freezer.tick(timedelta(hours=6))
    await o.coordinator.async_refresh()
    assert _snap(o, "2026-12")["maned"]["kwh"] == 60.0


async def test_tall_for_en_annen_maaned_enn_den_inneværende_gir_ikke_bilde(hass, oppsett):
    o = oppsett
    sett_kilder(hass, denne={**DENNE_DES, "mnd": "2026-11"})  # sensoren henger etter
    await o.coordinator.async_refresh()
    assert _snap(o, "2026-12") is None and _snap(o, "2026-11") is None


async def test_ufullstendige_tall_gir_ikke_bilde(hass, oppsett):
    o = oppsett
    sett_kilder(hass, denne={k: v for k, v in DENNE_DES.items() if k != "snitt"})
    await o.coordinator.async_refresh()
    assert _snap(o, "2026-12") is None


async def test_bare_de_seks_siste_manedene_beholdes(hass, oppsett):
    o = oppsett
    for m in range(1, 9):
        o.lager.data["snapshots"][f"2026-{m:02d}"] = {**SNAP_NOV, "maned": {**SNAP_NOV["maned"]}}
    await o.coordinator.async_refresh()
    assert sorted(o.lager.data["snapshots"]) == [
        "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-12",
    ]  # fmt: skip


# --- reserve når regnskapssensoren mangler måneden --------------------------------------------


async def test_reserve_fra_bilde_gir_alltid_godkjenning_og_aldri_utsending(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-12-06 08:00:00+01:00")  # siste sjekkdag, ved varseltidspunktet
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS])  # november mangler i regnskapssensoren
    o.lager.data["snapshots"]["2026-11"] = SNAP_NOV
    await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p["status"] == "venter_godkjenning" and o.epost.call_count == 0
    assert "øyeblikksbilde" in p["notat"] and "2026-11-30" in p["notat"]
    assert p["snitt"] == 1.24 and p["belop"] == 310.0  # 250,0 kWh fra målerstandene × 1,24
    assert "snapshot" in p["kilde"]
    assert any("øyeblikksbilde" in c.data["message"] for c in o.varsler)


async def test_uten_bilde_er_det_fortsatt_manglende_data(hass, oppsett):
    o = oppsett
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS])
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11") is None


async def test_ufullstendig_bilde_brukes_ikke(hass, oppsett):
    o = oppsett
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS])
    o.lager.data["snapshots"]["2026-11"] = {
        **SNAP_NOV,
        "maned": {k: v for k, v in SNAP_NOV["maned"].items() if k != "norgespris"},
    }
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11") is None


async def test_tving_med_reserve_hopper_over_godkjenningen(hass, oppsett):
    o = oppsett
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS])
    o.lager.data["snapshots"]["2026-11"] = SNAP_NOV
    p = await o.coordinator.async_generer_oppgjor("2026-11", tving=True, send_epost=False)
    assert p["status"] == "ikke_betalt"


async def test_regnskapssensoren_har_forrang_naar_den_har_maaneden(hass, oppsett):
    o = oppsett
    o.lager.data["snapshots"]["2026-11"] = {
        **SNAP_NOV,
        "maned": {**SNAP_NOV["maned"], "snitt": 9.99},
    }
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11")["snitt"] == 1.24  # fra sensoren, ikke bildet


# --- reserven brukes først når kilden har hatt hele vinduet til å rette seg -----------------------


def _uten_november(hass):
    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS])  # malen/Amperium har ikke rullet ennå


async def test_automatisk_kjoering_venter_med_reserven_de_foerste_dagene(hass, oppsett):
    o = oppsett  # 3. des kl. 08:30, i kjørevinduet
    _uten_november(hass)
    o.lager.data["snapshots"]["2026-11"] = SNAP_NOV
    for _ in range(3):
        await o.coordinator.async_refresh()
        o.freezer.tick(timedelta(hours=1))
    assert o.lager.finn("2026-11") is None
    assert o.epost.call_count == 0 and len(o.varsler) == 0  # ingen støy underveis


async def test_venting_leges_av_seg_selv_naar_kilden_ruller_over(hass, oppsett):
    o = oppsett
    _uten_november(hass)
    o.lager.data["snapshots"]["2026-11"] = SNAP_NOV
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11") is None

    sett_kilder(hass, maneder=[SEP_HUS, OKT_HUS, NOV_HUS])
    o.freezer.tick(timedelta(hours=1))
    await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p is not None and "snapshot" not in p["kilde"]
    assert p["snitt"] == 1.24 and p["status"] == "ikke_betalt"
    assert o.epost.call_count == 1


async def test_reserven_brukes_ikke_rett_foer_varseltidspunktet_paa_siste_sjekkdag(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-12-06 07:30:00+01:00")  # varseltidspunktet er 08:00
    _uten_november(hass)
    o.lager.data["snapshots"]["2026-11"] = SNAP_NOV
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11") is None and len(o.varsler) == 0


async def test_reserven_brukes_fra_varseltidspunktet_paa_siste_sjekkdag(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-12-06 08:00:00+01:00")
    _uten_november(hass)
    o.lager.data["snapshots"]["2026-11"] = SNAP_NOV
    await o.coordinator.async_refresh()
    p = o.lager.finn("2026-11")
    assert p["status"] == "venter_godkjenning" and "snapshot" in p["kilde"]
    assert o.epost.call_count == 0
    assert any("øyeblikksbilde" in c.data["message"] for c in o.varsler)


async def test_uten_bilde_gir_siste_sjekkdag_varsel_om_manglende_data(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-12-06 08:00:00+01:00")
    _uten_november(hass)
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11") is None
    assert any("mangler data" in c.data["message"] for c in o.varsler)


async def test_manuell_generering_bruker_reserven_med_en_gang(hass, oppsett):
    o = oppsett  # 3. des: den som ber om oppgjøret selv, skal ikke måtte vente til 6. des
    _uten_november(hass)
    o.lager.data["snapshots"]["2026-11"] = SNAP_NOV
    p = await o.coordinator.async_generer_oppgjor("2026-11", send_epost=False)
    assert p["status"] == "venter_godkjenning" and "snapshot" in p["kilde"]
