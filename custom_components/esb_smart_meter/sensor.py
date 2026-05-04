"""Sensors for ESB Smart Meter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import ESBSmartMeterCoordinator


@dataclass(frozen=True, kw_only=True)
class ESBSensorDescription(SensorEntityDescription):
    """Describe an ESB Smart Meter sensor."""

    value_fn: Callable[[dict[str, Any]], Any]


def _period_value(period: str, key: str) -> Callable[[dict[str, Any]], Any]:
    """Return a period value getter."""

    def _getter(data: dict[str, Any]) -> Any:
        return _round(data.get(period, {}).get(key, 0.0))

    return _getter


SENSORS: tuple[ESBSensorDescription, ...] = (
    ESBSensorDescription(
        key="last_import",
        translation_key="last_import",
        name="Last Import",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.get("last_import"),
    ),
    ESBSensorDescription(
        key="last_reading",
        translation_key="last_reading",
        name="Last Reading",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: _as_local_timestamp(data.get("last_reading")),
    ),
    ESBSensorDescription(
        key="records",
        translation_key="records",
        name="Records",
        icon="mdi:table",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("records", 0),
    ),
    ESBSensorDescription(
        key="coverage_days",
        translation_key="coverage_days",
        name="Coverage Days",
        icon="mdi:calendar-range",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("coverage_days", 0),
    ),
    ESBSensorDescription(
        key="latest_interval_energy",
        translation_key="latest_interval_energy",
        name="Latest Interval Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _round(data.get("last_interval_kwh")),
    ),
    ESBSensorDescription(
        key="total_import",
        translation_key="total_import",
        name="Total Import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: _round(data.get("total_import_kwh")),
    ),
    ESBSensorDescription(
        key="today_energy",
        translation_key="today_energy",
        name="Today Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=_period_value("today", "total_kwh"),
    ),
    ESBSensorDescription(
        key="today_cheap_energy",
        translation_key="today_cheap_energy",
        name="Today Cheap Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=_period_value("today", "cheap_kwh"),
    ),
    ESBSensorDescription(
        key="today_night_energy",
        translation_key="today_night_energy",
        name="Today Night Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=_period_value("today", "night_kwh"),
    ),
    ESBSensorDescription(
        key="today_day_energy",
        translation_key="today_day_energy",
        name="Today Day Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=_period_value("today", "day_kwh"),
    ),
    ESBSensorDescription(
        key="today_peak_energy",
        translation_key="today_peak_energy",
        name="Today Peak Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=_period_value("today", "peak_kwh"),
    ),
    ESBSensorDescription(
        key="today_cost",
        translation_key="today_cost",
        name="Today Cost",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=_period_value("today", "cost"),
    ),
    ESBSensorDescription(
        key="yesterday_energy",
        translation_key="yesterday_energy",
        name="Yesterday Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=_period_value("yesterday", "total_kwh"),
    ),
    ESBSensorDescription(
        key="yesterday_cost",
        translation_key="yesterday_cost",
        name="Yesterday Cost",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=_period_value("yesterday", "cost"),
    ),
    ESBSensorDescription(
        key="month_energy",
        translation_key="month_energy",
        name="Month Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=_period_value("month", "total_kwh"),
    ),
    ESBSensorDescription(
        key="month_cost",
        translation_key="month_cost",
        name="Month Cost",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=_period_value("month", "cost"),
    ),
    ESBSensorDescription(
        key="current_rate_bucket",
        translation_key="current_rate_bucket",
        name="Current Rate Bucket",
        icon="mdi:clock-outline",
        value_fn=lambda data: data.get("current_bucket"),
    ),
    ESBSensorDescription(
        key="current_rate",
        translation_key="current_rate",
        name="Current Rate",
        native_unit_of_measurement="EUR/kWh",
        icon="mdi:cash",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("current_rate"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ESB Smart Meter sensors."""
    coordinator: ESBSmartMeterCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ESBSmartMeterSensor(coordinator, entry, description)
        for description in SENSORS
    )


class ESBSmartMeterSensor(
    CoordinatorEntity[ESBSmartMeterCoordinator], SensorEntity
):
    """Representation of an ESB Smart Meter sensor."""

    entity_description: ESBSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ESBSmartMeterCoordinator,
        entry: ConfigEntry,
        description: ESBSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.data.get(CONF_NAME, "ESB Smart Meter"),
            "manufacturer": "ESB Networks",
            "model": "Smart Meter CSV Import",
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self.entity_description.key in {
            "last_import",
            "records",
            "coverage_days",
            "current_rate_bucket",
            "current_rate",
        }:
            return True
        return bool(self.coordinator.data and self.coordinator.data.get("available"))

    @property
    def native_value(self) -> Any:
        """Return the state."""
        data = self.coordinator.data or {}
        return self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for diagnostics."""
        data = self.coordinator.data or {}
        if self.entity_description.key != "records":
            return {}
        return {
            "import_path": str(self.coordinator.import_path),
            "files": data.get("files", []),
            "message": data.get("message"),
        }


def _round(value: Any) -> Any:
    """Round numeric sensor values."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(value, 3)
    return value


def _as_local_timestamp(value: Any) -> Any:
    """Return a local-aware timestamp for HA timestamp sensors."""
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return value
