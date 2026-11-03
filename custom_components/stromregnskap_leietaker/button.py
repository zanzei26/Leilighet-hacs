"""Knapper: send lenken til leietaker, og merk utestående som betalt."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import StromregnskapCoordinator
from .sensor import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    koordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            SendLenkeKnapp(koordinator, entry.entry_id),
            MerkBetaltKnapp(koordinator, entry.entry_id),
            SendRegnskapKnapp(koordinator, entry.entry_id),
        ]
    )


class _Knapp(CoordinatorEntity[StromregnskapCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _noekkel = ""

    def __init__(self, coordinator: StromregnskapCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_{self._noekkel}"
        self._attr_device_info = device_info(entry_id)


class SendLenkeKnapp(_Knapp):
    """Sender en kort e-post til leietaker med lenken til siden."""

    _noekkel = "send_lenke"
    _attr_name = "Send lenke"
    _attr_icon = "mdi:email-fast-outline"

    async def async_press(self) -> None:
        await self.coordinator.async_send_lenke()


class MerkBetaltKnapp(_Knapp):
    """Merker alle utestående oppgjør som betalt."""

    _noekkel = "merk_som_betalt"
    _attr_name = "Merk som betalt"
    _attr_icon = "mdi:cash-check"

    async def async_press(self) -> None:
        await self.coordinator.async_merk_betalt()


class SendRegnskapKnapp(_Knapp):
    """Sender en kopi med fakturagrunnlag, regnskap og sikkerhetskopi til utleier."""

    _noekkel = "send_regnskap"
    _attr_name = "Send regnskap"
    _attr_icon = "mdi:file-send-outline"

    async def async_press(self) -> None:
        await self.coordinator.async_send_kopi()
