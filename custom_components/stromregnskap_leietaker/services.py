"""Tjenester: generer, godkjenn, send på nytt, sett status, publiser, slett, ny leietaker."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .calc import GYLDIGE_MANUELLE_STATUSER
from .const import DOMAIN
from .coordinator import StromregnskapCoordinator

PERIODE_PAAKREVD = {vol.Required("periode"): cv.string}

SKJEMA_GENERER = vol.Schema(
    {
        vol.Optional("periode"): cv.string,
        vol.Optional("tving", default=False): cv.boolean,
        vol.Optional("send_epost", default=True): cv.boolean,
    }
)
SKJEMA_PERIODE = vol.Schema(PERIODE_PAAKREVD)
SKJEMA_STATUS = vol.Schema(
    {**PERIODE_PAAKREVD, vol.Required("status"): vol.In(GYLDIGE_MANUELLE_STATUSER)}
)
SKJEMA_SLETT = vol.Schema({**PERIODE_PAAKREVD, vol.Required("bekreft"): cv.boolean})
SKJEMA_TOM = vol.Schema({})


def _koordinator(hass: HomeAssistant) -> StromregnskapCoordinator:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("Strømregnskap leietaker er ikke satt opp eller ikke lastet.")
    return entries[0].runtime_data.coordinator


async def _generer(call: ServiceCall) -> dict[str, Any]:
    p = await _koordinator(call.hass).async_generer_oppgjor(
        call.data.get("periode"),
        tving=call.data["tving"],
        send_epost=call.data["send_epost"],
    )
    return {"periode": p["id"], "status": p["status"], "belop": p["belop"]}


async def _godkjenn(call: ServiceCall) -> None:
    await _koordinator(call.hass).async_godkjenn_oppgjor(call.data["periode"])


async def _send_pa_nytt(call: ServiceCall) -> None:
    await _koordinator(call.hass).async_send_epost_pa_nytt(call.data["periode"])


async def _sett_status(call: ServiceCall) -> None:
    await _koordinator(call.hass).async_sett_status(call.data["periode"], call.data["status"])


async def _publiser(call: ServiceCall) -> None:
    await _koordinator(call.hass).async_publiser_side()


async def _slett(call: ServiceCall) -> None:
    await _koordinator(call.hass).async_slett_periode(
        call.data["periode"], bekreft=call.data["bekreft"]
    )


async def _ny_leietaker(call: ServiceCall) -> dict[str, Any]:
    return await _koordinator(call.hass).async_ny_leietaker()


def async_registrer_tjenester(hass: HomeAssistant) -> None:
    """Registreres én gang i async_setup, uavhengig av om entry'en er lastet."""
    reg = hass.services.async_register
    reg(
        DOMAIN,
        "generer_oppgjor",
        _generer,
        SKJEMA_GENERER,
        supports_response=SupportsResponse.OPTIONAL,
    )
    reg(DOMAIN, "godkjenn_oppgjor", _godkjenn, SKJEMA_PERIODE)
    reg(DOMAIN, "send_epost_pa_nytt", _send_pa_nytt, SKJEMA_PERIODE)
    reg(DOMAIN, "sett_status", _sett_status, SKJEMA_STATUS)
    reg(DOMAIN, "publiser_side", _publiser, SKJEMA_TOM)
    reg(DOMAIN, "slett_periode", _slett, SKJEMA_SLETT)
    reg(
        DOMAIN,
        "ny_leietaker",
        _ny_leietaker,
        SKJEMA_TOM,
        supports_response=SupportsResponse.OPTIONAL,
    )
