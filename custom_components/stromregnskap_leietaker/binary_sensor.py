"""Binærsensor: står et oppgjør og venter på godkjenning?"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import StromregnskapCoordinator
from .sensor import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([VenterGodkjenning(entry.runtime_data.coordinator, entry.entry_id)])


class VenterGodkjenning(CoordinatorEntity[StromregnskapCoordinator], BinarySensorEntity):
    """On når minst én periode står i status «venter_godkjenning»."""

    _attr_has_entity_name = True
    _attr_name = "Oppgjør venter godkjenning"

    def __init__(self, coordinator: StromregnskapCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_venter_godkjenning"
        self._attr_device_info = device_info(entry_id)

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data["venter"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"perioder": self.coordinator.data["venter"]}
