"""Binærsensor: står et oppgjør og venter på godkjenning?"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
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
        [VenterGodkjenning(koordinator, entry.entry_id), Datagrunnlag(koordinator, entry.entry_id)]
    )


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


class Datagrunnlag(CoordinatorEntity[StromregnskapCoordinator], BinarySensorEntity):
    """On (problem) når noe hindrer at neste månedsoppgjør kan lages trygt."""

    _attr_has_entity_name = True
    _attr_name = "Datagrunnlag"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: StromregnskapCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_datagrunnlag"
        self._attr_device_info = device_info(entry_id)

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data["datagrunnlag"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data
        return {
            "problemer": d["datagrunnlag"],
            "malerstander": d["maalerstander"],
            "siste_oyeblikksbilde": d["siste_bilde"],
            "siste_sikkerhetskopi": d["siste_sikkerhetskopi"],
            "sikkerhetskopimappe": d["kopimappe"],
        }
