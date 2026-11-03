"""Sensorer for Strømregnskap leietaker."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import StromregnskapCoordinator

KRONER = "NOK"


def device_info(entry_id: str) -> DeviceInfo:
    """Én enhet for alle entiteter. Enhetsnavnet står først i entitetenes navn."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name="Leietaker",
        model="Strømregnskap leietaker",
    )


def _rund(verdi: float | None, desimaler: int = 2) -> float | None:
    return None if verdi is None else round(verdi, desimaler)


@dataclass(frozen=True, kw_only=True)
class StromSensorBeskrivelse(SensorEntityDescription):
    """Beskrivelse med funksjoner som henter verdi og attributter fra koordinatordata."""

    verdi: Callable[[dict[str, Any]], Any]
    attributter: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _siste_attributter(d: dict[str, Any]) -> dict[str, Any]:
    return dict(d["siste"]) if d["siste"] else {}


SENSORER: tuple[StromSensorBeskrivelse, ...] = (
    StromSensorBeskrivelse(
        key="utestaaende",
        name="Utestående",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=KRONER,
        suggested_display_precision=2,
        verdi=lambda d: d["utestaaende"],
        attributter=lambda d: {
            "antall_perioder": d["antall_utestaaende"],
            "side_url": d["side_url"],
        },
    ),
    StromSensorBeskrivelse(
        key="siste_oppgjor",
        name="Siste oppgjør",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=KRONER,
        suggested_display_precision=2,
        verdi=lambda d: d["siste"]["belop"] if d["siste"] else None,
        attributter=_siste_attributter,
    ),
    StromSensorBeskrivelse(
        key="forbruk_hittil",
        name="Forbruk hittil",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        verdi=lambda d: d["kwh_hittil"],
        attributter=lambda d: {
            "snitt_hittil": d["snitt_hittil"],
            "kostnad_hittil": d["kostnad_hittil"],
            "estimat_kwh": _rund(d["estimat_kwh"]),
            "estimat_kr": d["estimat_kr"],
            "endring_prosent": d["endring_prosent"],
            "effekt_w": d["effekt_w"],
            "maaler_total_kwh": d["import_kwh"],
            "kilde_hittil": d["hittil_kilde"],
            "leilighet_kwh_hittil": d["leilighet_kwh_hittil"],
            "lader_kwh_hittil": d["lader_kwh_hittil"],
            "lader_kostnad_hittil": d["lader_kostnad_hittil"],
        },
    ),
    StromSensorBeskrivelse(
        key="kostnad_hittil",
        name="Kostnad hittil",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=KRONER,
        suggested_display_precision=2,
        verdi=lambda d: d["kostnad_hittil"],
    ),
    StromSensorBeskrivelse(
        key="estimat_maned",
        name="Estimat måned",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=KRONER,
        suggested_display_precision=0,
        verdi=lambda d: d["estimat_kr"],
        attributter=lambda d: {"estimat_kwh": _rund(d["estimat_kwh"])},
    ),
    StromSensorBeskrivelse(
        key="side_sist_publisert",
        name="Side sist publisert",
        device_class=SensorDeviceClass.TIMESTAMP,
        verdi=lambda d: d["side_sist_publisert"],
        attributter=lambda d: {"side_url": d["side_url"]},
    ),
    StromSensorBeskrivelse(
        key="lenke",
        name="Lenke",
        icon="mdi:link-variant",
        verdi=lambda d: d["side_url"],
        attributter=lambda d: {
            "regnskap_pdf": d["regnskap_pdf_url"],
            "siste_faktura_pdf": d["siste_faktura_pdf_url"],
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    koordinator = entry.runtime_data.coordinator
    async_add_entities(StromSensor(koordinator, entry.entry_id, b) for b in SENSORER)


class StromSensor(CoordinatorEntity[StromregnskapCoordinator], SensorEntity):
    """En sensor som leser fra koordinatorens data."""

    entity_description: StromSensorBeskrivelse
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: StromregnskapCoordinator,
        entry_id: str,
        beskrivelse: StromSensorBeskrivelse,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = beskrivelse
        self._attr_unique_id = f"{entry_id}_{beskrivelse.key}"
        self._attr_device_info = device_info(entry_id)

    @property
    def native_value(self) -> Any:
        verdi = self.entity_description.verdi(self.coordinator.data)
        if isinstance(verdi, float):
            return round(verdi, 2)
        return verdi

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributter is None:
            return None
        return self.entity_description.attributter(self.coordinator.data)
