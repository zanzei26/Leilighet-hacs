"""Tester for tidlig varsel om datagrunnlaget, etterslep og sikkerhetskopieringsstatus."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.helpers import issue_registry as ir

from custom_components.stromregnskap_leietaker.const import DOMAIN

from .data import DENNE_DES, sett_kilder

IMPORT = "sensor.minusmaler_leilighet_import"


def _issue(hass, issue_id):
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


def _push(o):
    return [c.data["message"] for c in o.varsler]


def _problemer(o):
    return o.coordinator.data["datagrunnlag"]


# --- vurdering -------------------------------------------------------------------------------


async def test_alt_er_ok_naar_kilder_og_malerstander_er_paa_plass(hass, oppsett):
    o = oppsett
    await o.coordinator.async_refresh()
    assert _problemer(o) == []


async def test_utilgjengelig_regnskapssensor_er_et_problem(hass, oppsett):
    o = oppsett
    hass.states.async_set("sensor.jarvis_stromregnskap", "unavailable")
    await o.coordinator.async_refresh()
    assert any("Regnskapssensoren" in p and "utilgjengelig" in p for p in _problemer(o))


async def test_regnskapssensor_som_viser_feil_maaned_er_et_problem(hass, oppsett):
    o = oppsett
    sett_kilder(hass, denne={**DENNE_DES, "mnd": "2026-11"})
    await o.coordinator.async_refresh()
    assert any("inneværende måned" in p for p in _problemer(o))


async def test_utilgjengelig_maaler_er_et_problem(hass, oppsett):
    o = oppsett
    hass.states.async_set(IMPORT, "unavailable")
    await o.coordinator.async_refresh()
    assert any("Måleren" in p for p in _problemer(o))


async def test_manglende_malerstand_ved_manedsskiftet_er_et_problem_med_veiledning(hass, oppsett):
    o = oppsett
    del o.lager.data["maalerstander"]["2026-12-01"]
    with patch.object(o.coordinator, "_stand_fra_statistikk", return_value=None):
        await o.coordinator.async_refresh()
    treff = [p for p in _problemer(o) if "01.12.2026" in p]
    assert treff and "Sett målerstand" in treff[0]


async def test_for_gammelt_oyeblikksbilde_er_et_problem_fra_tredje_dag(hass, oppsett):
    o = oppsett
    await o.coordinator.async_refresh()  # tar et bilde
    hass.states.async_set("sensor.jarvis_stromregnskap", "unavailable")  # ingen nye
    o.freezer.tick(timedelta(hours=49))
    await o.coordinator.async_refresh()
    assert any("øyeblikksbilde" in p for p in _problemer(o))


async def test_feilende_sikkerhetskopiering_er_et_problem(hass, oppsett):
    o = oppsett
    with patch(
        "custom_components.stromregnskap_leietaker.storage.skriv_kopi",
        side_effect=OSError("disken er full"),
    ):
        await o.coordinator.async_refresh()  # øyeblikksbildet lagres, men kopien feiler
    assert any("Sikkerhetskopiering" in p and "disken er full" in p for p in _problemer(o))


# --- varsling ---------------------------------------------------------------------------------


async def test_ingen_push_og_ingen_issue_foer_den_25_selv_om_det_er_problemer(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-12-10 12:00:00+01:00")
    hass.states.async_set(IMPORT, "unavailable")
    await o.coordinator.async_refresh()
    assert _problemer(o) and _push(o) == [] and _issue(hass, "datagrunnlag_2026-12") is None


async def test_fra_den_25_kommer_ett_varsel_per_dag_og_et_issue(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-12-26 12:00:00+01:00")
    hass.states.async_set(IMPORT, "unavailable")
    await o.coordinator.async_refresh()
    assert len(o.varsler) == 1 and "Måleren" in _push(o)[0]
    assert _issue(hass, "datagrunnlag_2026-12").is_fixable is False

    o.freezer.tick(timedelta(hours=3))
    await o.coordinator.async_refresh()
    assert len(o.varsler) == 1  # samme dag: ikke flere

    o.freezer.tick(timedelta(days=1))
    await o.coordinator.async_refresh()
    assert len(o.varsler) == 2  # ny dag: påminnelse


async def test_issue_fjernes_naar_problemet_er_borte(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-12-26 12:00:00+01:00")
    hass.states.async_set(IMPORT, "unavailable")
    await o.coordinator.async_refresh()
    assert _issue(hass, "datagrunnlag_2026-12") is not None
    hass.states.async_set(IMPORT, "260.0", {})
    o.freezer.tick(timedelta(hours=1))
    await o.coordinator.async_refresh()
    assert _problemer(o) == [] and _issue(hass, "datagrunnlag_2026-12") is None


async def test_issue_fra_forrige_maaned_ryddes_bort_naar_ny_maaned_er_i_gang(hass, oppsett):
    o = oppsett
    o.freezer.move_to("2026-12-26 12:00:00+01:00")
    hass.states.async_set(IMPORT, "unavailable")
    await o.coordinator.async_refresh()
    assert _issue(hass, "datagrunnlag_2026-12") is not None
    hass.states.async_set(IMPORT, "260.0", {})
    o.freezer.move_to("2027-01-02 12:00:00+01:00")
    await o.coordinator.async_refresh()
    assert _issue(hass, "datagrunnlag_2026-12") is None


# --- etterslep ---------------------------------------------------------------------------


async def test_oppgjor_som_ikke_er_laget_etter_vinduet_gir_issue_og_daglig_varsel(hass, oppsett):
    o = oppsett
    o.lager.tilstand["opprettet"] = "2026-11-03T20:00:00+01:00"
    sett_kilder(hass, maneder=[])  # ingenting å lage oppgjør av, og ingen bilde
    o.freezer.move_to("2026-12-07 08:30:00+01:00")  # vinduet (3.–6.) er over
    await o.coordinator.async_refresh()
    assert o.lager.finn("2026-11") is None
    issue = _issue(hass, "etterslep_2026-11")
    assert issue is not None and issue.is_fixable is True
    etterslep = [m for m in _push(o) if "2026-11" in m and "ikke laget" in m]
    assert len(etterslep) == 1

    o.freezer.tick(timedelta(hours=2))
    await o.coordinator.async_refresh()
    assert len([m for m in _push(o) if "ikke laget" in m]) == 1  # samme dag
    o.freezer.tick(timedelta(days=1))
    await o.coordinator.async_refresh()
    assert len([m for m in _push(o) if "ikke laget" in m]) == 2  # ny dag


async def test_ingen_etterslepsvarsel_for_perioder_som_sluttet_foer_integrasjonen_fantes(
    hass, oppsett
):
    o = oppsett  # opprettet = 3. des (fixturen), november sluttet 1. des
    sett_kilder(hass, maneder=[])
    o.freezer.move_to("2026-12-07 08:30:00+01:00")
    await o.coordinator.async_refresh()
    assert _issue(hass, "etterslep_2026-11") is None
    assert not any("ikke laget" in m for m in _push(o))


async def test_etterslepsissue_fjernes_naar_oppgjoeret_er_laget(hass, oppsett):
    o = oppsett
    o.lager.tilstand["opprettet"] = "2026-11-03T20:00:00+01:00"
    sett_kilder(hass, maneder=[])
    o.freezer.move_to("2026-12-07 08:30:00+01:00")
    await o.coordinator.async_refresh()
    assert _issue(hass, "etterslep_2026-11") is not None
    sett_kilder(hass)  # dataene er på plass igjen
    await o.coordinator.async_generer_oppgjor("2026-11", send_epost=False)
    await o.coordinator.async_refresh()
    assert _issue(hass, "etterslep_2026-11") is None


async def test_ingen_etterslep_foer_vinduet_er_over(hass, oppsett):
    o = oppsett
    o.lager.tilstand["opprettet"] = "2026-11-03T20:00:00+01:00"
    sett_kilder(hass, maneder=[])
    o.freezer.move_to("2026-12-05 08:30:00+01:00")  # midt i vinduet
    await o.coordinator.async_refresh()
    assert _issue(hass, "etterslep_2026-11") is None
