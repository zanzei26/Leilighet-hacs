"""Fiksflyter for Repairs: godkjenn et ventende oppgjør, eller send e-post på nytt."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .coordinator import StromregnskapCoordinator
from .varsler import ISSUE_EPOST, ISSUE_VENTER


class _BekreftFlow(RepairsFlow):
    """Felles skjelett: vis bekreftelse, utfør handling, avbryt med forklaring ved feil."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._periode: str = data["periode"]
        self._entry_id: str = data["entry_id"]

    def _koordinator(self) -> StromregnskapCoordinator | None:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or not hasattr(entry, "runtime_data"):
            return None
        return entry.runtime_data.coordinator

    async def _utfor(self, koordinator: StromregnskapCoordinator) -> None:
        raise NotImplementedError

    async def async_step_init(self, user_input: dict[str, str] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, str] | None = None) -> FlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                description_placeholders={"periode": self._periode},
            )
        koordinator = self._koordinator()
        if koordinator is None:
            return self.async_abort(
                reason="handling_feilet",
                description_placeholders={"feil": "Integrasjonen er ikke lastet."},
            )
        try:
            await self._utfor(koordinator)
        except HomeAssistantError as err:
            return self.async_abort(
                reason="handling_feilet", description_placeholders={"feil": str(err)}
            )
        return self.async_create_entry(data={})


class GodkjennFlow(_BekreftFlow):
    async def _utfor(self, koordinator: StromregnskapCoordinator) -> None:
        await koordinator.async_godkjenn_oppgjor(self._periode)


class EpostFlow(_BekreftFlow):
    async def _utfor(self, koordinator: StromregnskapCoordinator) -> None:
        await koordinator.async_send_epost_pa_nytt(self._periode)


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Velger fiksflyt ut fra hvilken type issue det gjelder."""
    assert data is not None
    if issue_id.startswith(f"{ISSUE_VENTER}_"):
        return GodkjennFlow(data)
    if issue_id.startswith(f"{ISSUE_EPOST}_"):
        return EpostFlow(data)
    raise ValueError(f"Ukjent issue: {issue_id}")
