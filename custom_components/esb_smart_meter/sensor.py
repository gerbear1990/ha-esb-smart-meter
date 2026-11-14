"""Sensors for ESB Smart Meter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, RATE_BUCKETS
from .coordinator import ESBSmartMeterCoordinator

KWH = UnitOfEnergy.KILO_WATT_HOUR


@dataclass(frozen=True, kw_only=True)
class ESBSensorDescription(SensorEntityDescription):
    """Describe an ESB Smart Meter sensor."""

    value_fn: Callable[[dict[str, Any]], Any]


def _period_value(period: str, key: str) -> Callable[[dict[str, Any]], Any]:
    """Return a getter for a value inside a period dict."""

    def _getter(data: dict[str, Any]) -> Any:
        return _round(data.get(period, {}).get(key, 0.0))

    return _getter


def _recent_value(key: str) -> Callable[[dict[str, Any]], Any]:
    """Return a getter for the most-recent-complete-day period."""
    return _period_value("recent_complete", key)


def _energy(key: str, translation_key: str, value_fn, **kw) -> ESBSensorDescription:
    return ESBSensorDescription(
        key=key,
        translation_key=translation_key,
        native_unit_of_measurement=KWH,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=value_fn,
        **kw,
    )


def _cost(key: str, translation_key: str, value_fn, **kw) -> ESBSensorDescription:
    return ESBSensorDescription(
        key=key,
        translation_key=translation_key,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=value_fn,
        **kw,
    )


SENSORS: tuple[ESBSensorDescription, ...] = (
    # --- diagnostics -------------------------------------------------------
    ESBSensorDescription(
        key="last_import",
        translation_key="last_import",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.get("last_import"),
    ),
    ESBSensorDescription(
        key="last_reading",
        translation_key="last_reading",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: _as_local_timestamp(data.get("last_reading")),
    ),
    ESBSensorDescription(
        key="last_reading_age",
        translation_key="last_reading_age",
        native_unit_of_measurement="h",
        icon="mdi:timer-sand",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _round(data.get("last_reading_age_hours")),
    ),
    ESBSensorDescription(
        key="records",
        translation_key="records",
        icon="mdi:table",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("records", 0),
    ),
    ESBSensorDescription(
        key="coverage_days",
        translation_key="coverage_days",
        icon="mdi:calendar-range",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("coverage_days", 0),
    ),
    ESBSensorDescription(
        key="latest_interval_energy",
        translation_key="latest_interval_energy",
        native_unit_of_measurement=KWH,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _round(data.get("last_interval_kwh")),
    ),
    ESBSensorDescription(
        key="total_import",
        translation_key="total_import",
        native_unit_of_measurement=KWH,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: _round(data.get("total_import_kwh")),
    ),
    ESBSensorDescription(
        key="current_rate_bucket",
        translation_key="current_rate_bucket",
        icon="mdi:clock-outline",
        value_fn=lambda data: data.get("current_bucket"),
    ),
    ESBSensorDescription(
        key="current_rate",
        translation_key="current_rate",
        icon="mdi:cash",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("current_rate"),
    ),
    # --- today -------------------------------------------------------------
    _energy("today_energy", "today_energy", _period_value("today", "total_kwh")),
    _energy("today_cheap_energy", "today_cheap_energy", _period_value("today", "cheap_kwh")),
    _energy("today_night_energy", "today_night_energy", _period_value("today", "night_kwh")),
    _energy("today_day_energy", "today_day_energy", _period_value("today", "day_kwh")),
    _energy("today_peak_energy", "today_peak_energy", _period_value("today", "peak_kwh")),
    _cost("today_cost", "today_cost", _period_value("today", "cost")),
    _cost("today_vat", "today_vat", _period_value("today", "vat")),
    _cost("today_discount", "today_discount", _period_value("today", "discount")),
    # --- yesterday ---------------------------------------------------------
    _energy("yesterday_energy", "yesterday_energy", _period_value("yesterday", "total_kwh")),
    _cost("yesterday_cost", "yesterday_cost", _period_value("yesterday", "cost")),
    # --- month -------------------------------------------------------------
    _energy("month_energy", "month_energy", _period_value("month", "total_kwh")),
    _cost("month_cost", "month_cost", _period_value("month", "cost")),
    _cost("month_net_cost", "month_net_cost", _period_value("month", "net_cost")),
    _cost("month_vat", "month_vat", _period_value("month", "vat")),
    _cost("month_discount", "month_discount", _period_value("month", "discount")),
    _cost("month_cheap_cost", "month_cheap_cost", _period_value("month", "cheap_cost")),
    _cost("month_night_cost", "month_night_cost", _period_value("month", "night_cost")),
    _cost("month_day_cost", "month_day_cost", _period_value("month", "day_cost")),
    _cost("month_peak_cost", "month_peak_cost", _period_value("month", "peak_cost")),
    ESBSensorDescription(
        key="month_complete_days",
        translation_key="month_complete_days",
        icon="mdi:calendar-check",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("month_complete_day_count", 0),
    ),
    ESBSensorDescription(
        key="projected_month_cost",
        translation_key="projected_month_cost",
        icon="mdi:chart-line",
        device_class=SensorDeviceClass.MONETARY,
        value_fn=lambda data: _round(data.get("projected_month_cost")),
    ),
    ESBSensorDescription(
        key="projected_month_energy_cost",
        translation_key="projected_month_energy_cost",
        icon="mdi:chart-line",
        device_class=SensorDeviceClass.MONETARY,
        value_fn=lambda data: _round(data.get("projected_month_energy_cost")),
    ),
    # --- most recent complete day -----------------------------------------
    ESBSensorDescription(
        key="recent_complete_date",
        translation_key="recent_complete_date",
        icon="mdi:calendar-check",
        value_fn=lambda data: data["recent_complete_date"].isoformat()
        if data.get("recent_complete_date")
        else None,
    ),
    _energy("recent_complete_energy", "recent_complete_energy", _recent_value("total_kwh")),
    _cost("recent_complete_cost", "recent_complete_cost", _recent_value("cost")),
    _energy("recent_complete_cheap_energy", "recent_complete_cheap_energy", _recent_value("cheap_kwh")),
    _cost("recent_complete_cheap_cost", "recent_complete_cheap_cost", _recent_value("cheap_cost")),
    _energy("recent_complete_night_energy", "recent_complete_night_energy", _recent_value("night_kwh")),
    _cost("recent_complete_night_cost", "recent_complete_night_cost", _recent_value("night_cost")),
    _energy("recent_complete_day_energy", "recent_complete_day_energy", _recent_value("day_kwh")),
    _cost("recent_complete_day_cost", "recent_complete_day_cost", _recent_value("day_cost")),
    _energy("recent_complete_peak_energy", "recent_complete_peak_energy", _recent_value("peak_kwh")),
    _cost("recent_complete_peak_cost", "recent_complete_peak_cost", _recent_value("peak_cost")),
    # --- 7-day lookback ----------------------------------------------------
    _cost("last_7_complete_day_cost", "last_7_complete_day_cost",
          lambda data: _round(data.get("last_7_cost", 0.0))),
    _energy("last_7_complete_day_energy", "last_7_complete_day_energy",
            lambda data: _round(data.get("last_7_energy", 0.0))),
    ESBSensorDescription(
        key="average_daily_cost_7_day",
        translation_key="average_daily_cost_7_day",
        device_class=SensorDeviceClass.MONETARY,
        value_fn=lambda data: _round(data.get("last_7_average_daily_cost", 0.0)),
    ),
    ESBSensorDescription(
        key="average_daily_energy_7_day",
        translation_key="average_daily_energy_7_day",
        native_unit_of_measurement=KWH,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _round(data.get("last_7_average_daily_energy", 0.0)),
    ),
)

# Export / microgeneration sensors, only added when export data is present or a
# feed-in (export) rate is configured.
EXPORT_SENSORS: tuple[ESBSensorDescription, ...] = (
    ESBSensorDescription(
        key="total_export",
        translation_key="total_export",
        native_unit_of_measurement=KWH,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: _round(data.get("total_export_kwh")),
    ),
    _energy("today_export_energy", "today_export_energy",
            lambda data: _round(data.get("today_export_kwh"))),
    _energy("yesterday_export_energy", "yesterday_export_energy",
            lambda data: _round(data.get("yesterday_export_kwh"))),
    _energy("month_export_energy", "month_export_energy",
            lambda data: _round(data.get("month_export_kwh"))),
    _cost("today_export_credit", "today_export_credit",
          lambda data: _round(data.get("today_export_credit"))),
    _cost("month_export_credit", "month_export_credit",
          lambda data: _round(data.get("month_export_credit"))),
)

# Sensors whose native unit is the configured currency.
_MONETARY_KEYS = {
    d.key
    for d in (*SENSORS, *EXPORT_SENSORS)
    if d.device_class == SensorDeviceClass.MONETARY
}

_EXPORT_KEYS = {d.key for d in EXPORT_SENSORS}

# Diagnostic sensors that stay available even before any CSV data is found.
_ALWAYS_AVAILABLE = {
    "last_import",
    "records",
    "coverage_days",
    "current_rate_bucket",
    "current_rate",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ESB Smart Meter sensors."""
    coordinator: ESBSmartMeterCoordinator = hass.data[DOMAIN][entry.entry_id]
    descriptions = list(SENSORS)
    data = coordinator.data or {}
    export_added = bool(data.get("has_export") or coordinator.export_rate)
    if export_added:
        descriptions += list(EXPORT_SENSORS)
    async_add_entities(
        ESBSmartMeterSensor(coordinator, entry, description)
        for description in descriptions
    )

    if not export_added:
        unsub: Callable[[], None] | None = None

        @callback
        def _maybe_add_export_sensors() -> None:
            nonlocal unsub
            if not (coordinator.data and coordinator.data.get("has_export")):
                return
            if unsub is not None:
                unsub()
                unsub = None
            async_add_entities(
                ESBSmartMeterSensor(coordinator, entry, description)
                for description in EXPORT_SENSORS
            )

        unsub = coordinator.async_add_listener(_maybe_add_export_sensors)
        entry.async_on_unload(unsub)


class ESBSmartMeterSensor(CoordinatorEntity[ESBSmartMeterCoordinator], SensorEntity):
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
        if description.key in _MONETARY_KEYS:
            self._attr_native_unit_of_measurement = coordinator.currency
        elif description.key == "current_rate":
            self._attr_native_unit_of_measurement = f"{coordinator.currency}/kWh"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.data.get(CONF_NAME, "ESB Smart Meter"),
            "manufacturer": "ESB Networks",
            "model": "Smart Meter CSV Import",
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if self.entity_description.key in _ALWAYS_AVAILABLE:
            return True
        data = self.coordinator.data or {}
        if self.entity_description.key in _EXPORT_KEYS:
            return bool(data.get("has_export") or data.get("available"))
        return bool(data.get("available"))

    @property
    def native_value(self) -> Any:
        """Return the state."""
        data = self.coordinator.data or {}
        return self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return per-bucket / diagnostic breakdowns for relevant sensors."""
        data = self.coordinator.data or {}
        key = self.entity_description.key

        if key == "records":
            return {
                "import_path": str(self.coordinator.import_path),
                "files": data.get("files", []),
                "message": data.get("message"),
                "last_reading_age_hours": data.get("last_reading_age_hours"),
            }
        if key in ("today_energy", "yesterday_energy", "month_energy"):
            period = data.get(key.split("_")[0], {})
            return {f"{b}_kwh": period.get(f"{b}_kwh") for b in RATE_BUCKETS}
        if key == "month_cost":
            period = data.get("month", {})
            attrs = {f"{b}_cost": period.get(f"{b}_cost") for b in RATE_BUCKETS}
            attrs["complete_days"] = data.get("month_complete_day_count")
            attrs["projected_cost"] = data.get("projected_month_cost")
            attrs.update(_bill_lines(period, data))
            return attrs
        if key in ("today_cost", "yesterday_cost"):
            return _bill_lines(data.get(key.split("_")[0], {}), data)
        if key == "projected_month_cost":
            # Every line is exposed because they are derived differently: usage
            # is extrapolated, the standing charge is fixed, and the discount
            # and VAT follow from whatever the other two come to.
            return {
                "energy_cost": data.get("projected_month_energy_cost"),
                "standing_charge": data.get("projected_month_standing_charge"),
                "discount": data.get("projected_month_discount"),
                "net_cost": data.get("projected_month_net_cost"),
                "vat": data.get("projected_month_vat"),
                "complete_days": data.get("month_complete_day_count"),
                "days_in_month": data.get("days_in_month"),
                "vat_percent": data.get("vat_percent"),
                "discount_percent": data.get("discount_percent"),
            }
        if key == "recent_complete_date":
            return {"breakdown": data.get("recent_complete", {})}
        if key in ("last_7_complete_day_cost", "last_7_complete_day_energy"):
            return {"days": data.get("last_7_complete_days", [])}
        return {}


def _bill_lines(period: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Return the itemised bill breakdown behind a cost sensor."""
    return {
        "energy_cost": period.get("energy_cost"),
        "standing_charge": period.get("standing_charge"),
        "discount": period.get("discount"),
        "net_cost": period.get("net_cost"),
        "vat": period.get("vat"),
        "vat_percent": data.get("vat_percent"),
        "discount_percent": data.get("discount_percent"),
    }


def _round(value: Any) -> Any:
    """Round numeric sensor values."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return round(value, 3)
    return value


def _as_local_timestamp(value: Any) -> Any:
    """Return a local-aware timestamp for HA timestamp sensors."""
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return value
