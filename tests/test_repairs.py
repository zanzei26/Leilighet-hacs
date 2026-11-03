"""Tester for Repairs-fiksflytene, gjennom HAs ekte repairs-API."""

from datetime import timedelta

from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from custom_components.stromregnskap_leietaker.const import DOMAIN
from custom_components.stromregnskap_leietaker.mail import SmtpFeil

from .data import NOV_HUS, OKT_HUS, SEP_HUS, sett_kilder


async def _kall(hass, tjeneste, data):
    return await hass.services.async_call(DOMAIN, tjeneste, data, blocking=True)


def _issue(hass, issue_id):
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def _start_fiks(hass, issue_id):
    assert await async_setup_component(hass, "repairs", {})
    manager = repairs_flow_manager(hass)
    return manager, await manager.async_init(DOMAIN, data={"issue_id": issue_id})


async def _bekreft(manager, flow_id):
    return await manager.async_configure(flow_id, {})


async def _ventende_periode(hass):
    sett_kilder(
        hass,
        maneder=[SEP_HUS, OKT_HUS, {**NOV_HUS, "snitt": 3.5}],
        denne={"mnd": "2026-11", "snitt": 1.5, "leilighet_kr": 40.0},
        utility="30.25",
    )
    await _kall(hass, "generer_oppgjor", {"periode": "2026-11"})


async def test_godkjenn_via_repairs_sender_oppgjoeret_og_fjerner_issue(hass, integrasjon):
    await _ventende_periode(hass)
    assert _issue(hass, "venter_godkjenning_2026-11").is_fixable is True
    assert integrasjon.epost.call_count == 0

    manager, steg = await _start_fiks(hass, "venter_godkjenning_2026-11")
    assert steg["type"] is FlowResultType.FORM and steg["step_id"] == "confirm"
    assert steg["description_placeholders"]["periode"] == "2026-11"

    ferdig = await _bekreft(manager, steg["flow_id"])
    assert ferdig["type"] is FlowResultType.CREATE_ENTRY
    assert integrasjon.entry.runtime_data.lager.finn("2026-11")["status"] == "ikke_betalt"
    assert integrasjon.epost.call_count == 1
    assert _issue(hass, "venter_godkjenning_2026-11") is None


async def test_send_pa_nytt_via_repairs_etter_48_timers_epostfeil(hass, integrasjon):
    integrasjon.epost.side_effect = SmtpFeil("auth", "avvist")
    await _kall(hass, "generer_oppgjor", {"periode": "2026-11"})
    integrasjon.freezer.tick(timedelta(hours=49))
    await integrasjon.entry.runtime_data.coordinator.async_refresh()
    assert _issue(hass, "epost_feilet_2026-11").is_fixable is True

    integrasjon.epost.side_effect = None
    manager, steg = await _start_fiks(hass, "epost_feilet_2026-11")
    ferdig = await _bekreft(manager, steg["flow_id"])
    assert ferdig["type"] is FlowResultType.CREATE_ENTRY
    assert integrasjon.entry.runtime_data.lager.finn("2026-11")["epost_sendt"] is not None
    assert _issue(hass, "epost_feilet_2026-11") is None


async def test_fiks_som_feiler_avbrytes_med_forklaring_og_issue_blir(hass, integrasjon):
    integrasjon.epost.side_effect = SmtpFeil("auth", "avvist")
    await _kall(hass, "generer_oppgjor", {"periode": "2026-11"})
    integrasjon.freezer.tick(timedelta(hours=49))
    await integrasjon.entry.runtime_data.coordinator.async_refresh()

    manager, steg = await _start_fiks(hass, "epost_feilet_2026-11")
    ferdig = await _bekreft(manager, steg["flow_id"])
    assert ferdig["type"] is FlowResultType.ABORT and ferdig["reason"] == "handling_feilet"
    assert "auth" in ferdig["description_placeholders"]["feil"]
    assert _issue(hass, "epost_feilet_2026-11") is not None


async def test_fiks_etter_at_perioden_er_slettet_avbrytes(hass, integrasjon):
    await _ventende_periode(hass)
    manager, steg = await _start_fiks(hass, "venter_godkjenning_2026-11")
    await _kall(hass, "slett_periode", {"periode": "2026-11", "bekreft": True})
    ferdig = await _bekreft(manager, steg["flow_id"])
    assert ferdig["type"] is FlowResultType.ABORT and ferdig["reason"] == "handling_feilet"
