"""Data coordinator for ESB Smart Meter."""

from __future__ import annotations

from collections import defaultdict
import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CHEAP_END,
    CONF_CHEAP_START,
    CONF_IMPORT_PATH,
    CONF_RATES,
    CONF_TIME_SHIFT_MINUTES,
    DEFAULT_CHEAP_END,
    DEFAULT_CHEAP_START,
    DEFAULT_IMPORT_PATH,
    DEFAULT_RATES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIME_SHIFT_MINUTES,
    DOMAIN,
)

LOGGER = logging.getLogger(__name__)

DATETIME_COLUMNS = (
    "Read Date and End Time",
    "Read Date And End Time",
    "read_date_and_end_time",
    "datetime",
    "timestamp",
)
VALUE_COLUMNS = (
    "Read Value",
    "Read Value (kWh)",
    "read_value",
    "kWh",
    "kwh",
)


@dataclass(frozen=True)
class Reading:
    """One ESB half-hour reading."""

    when: datetime
    kwh: float
    source: str


class ESBSmartMeterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Read ESB smart meter CSV exports and derive useful HA data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.import_path = Path(
            entry.data.get(CONF_IMPORT_PATH, DEFAULT_IMPORT_PATH)
        )
        self.time_shift = int(
            entry.data.get(CONF_TIME_SHIFT_MINUTES, DEFAULT_TIME_SHIFT_MINUTES)
        )
        self.cheap_start = _parse_time(
            entry.data.get(CONF_CHEAP_START, DEFAULT_CHEAP_START),
            DEFAULT_CHEAP_START,
        )
        self.cheap_end = _parse_time(
            entry.data.get(CONF_CHEAP_END, DEFAULT_CHEAP_END),
            DEFAULT_CHEAP_END,
        )
        self.rates = DEFAULT_RATES | dict(entry.data.get(CONF_RATES, {}))
        super().__init__(
            hass,
            LOGGER,
            name=entry.data.get(CONF_NAME, "ESB Smart Meter"),
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch and process CSV data."""
        return await self.hass.async_add_executor_job(self._read_data)

    def _read_data(self) -> dict[str, Any]:
        """Read CSV data from disk."""
        self.import_path.mkdir(parents=True, exist_ok=True)
        readings = self._load_readings()
        now = dt_util.now()

        if not readings:
            current_bucket = self._bucket_for(now.time())
            return {
                "available": False,
                "records": 0,
                "files": [],
                "last_import": now,
                "current_bucket": current_bucket,
                "current_rate": self.rates.get(current_bucket, self.rates["other"]),
                "message": f"No ESB CSV rows found in {self.import_path}",
            }

        readings.sort(key=lambda item: item.when)
        latest = readings[-1]
        today = now.date()
        yesterday = today - timedelta(days=1)
        month_start = today.replace(day=1)

        daily = _empty_bucket_totals()
        month = _empty_one_period()
        total_kwh = 0.0

        for reading in readings:
            bucket = self._bucket_for(reading.when.time())
            cost = reading.kwh * self.rates.get(bucket, self.rates["other"])
            total_kwh += reading.kwh

            reading_date = reading.when.date()
            if reading_date == today:
                _add_bucket(daily["today"], bucket, reading.kwh, cost)
            if reading_date == yesterday:
                _add_bucket(daily["yesterday"], bucket, reading.kwh, cost)
            if reading_date >= month_start:
                _add_bucket(month, bucket, reading.kwh, cost)

        coverage_days = (readings[-1].when.date() - readings[0].when.date()).days + 1
        current_bucket = self._bucket_for(now.time())

        return {
            "available": True,
            "records": len(readings),
            "files": sorted({reading.source for reading in readings}),
            "last_import": now,
            "first_reading": readings[0].when,
            "last_reading": latest.when,
            "last_interval_kwh": latest.kwh,
            "coverage_days": coverage_days,
            "total_import_kwh": round(total_kwh, 3),
            "current_bucket": current_bucket,
            "current_rate": self.rates.get(current_bucket, self.rates["other"]),
            "today": daily["today"],
            "yesterday": daily["yesterday"],
            "month": month,
            "message": "OK",
        }

    def _load_readings(self) -> list[Reading]:
        """Load valid readings from all CSV files in the import folder."""
        by_timestamp: dict[datetime, Reading] = {}
        for csv_path in sorted(self.import_path.glob("*.csv")):
            for reading in self._read_csv(csv_path):
                by_timestamp[reading.when] = reading
        return list(by_timestamp.values())

    def _read_csv(self, csv_path: Path) -> list[Reading]:
        """Read a single CSV file if it looks like an ESB interval file."""
        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
                sample = file_obj.read(4096)
                file_obj.seek(0)
                dialect = csv.Sniffer().sniff(sample) if sample else csv.excel
                reader = csv.DictReader(file_obj, dialect=dialect)
                if not reader.fieldnames:
                    return []
                datetime_col = _find_column(reader.fieldnames, DATETIME_COLUMNS)
                value_col = _find_column(reader.fieldnames, VALUE_COLUMNS)
                if datetime_col is None or value_col is None:
                    return []

                readings: list[Reading] = []
                for row in reader:
                    when = _parse_datetime(row.get(datetime_col, ""))
                    kwh = _parse_float(row.get(value_col, ""))
                    if when is None or kwh is None:
                        continue
                    if self.time_shift:
                        when += timedelta(minutes=self.time_shift)
                    readings.append(Reading(when=when, kwh=kwh, source=csv_path.name))
                return readings
        except Exception as err:  # noqa: BLE001 - keep one bad CSV from killing HA setup
            LOGGER.warning("Unable to parse ESB CSV %s: %s", csv_path, err)
            return []

    def _bucket_for(self, value: time) -> str:
        """Return the configured rate bucket for a local time."""
        if _time_in_range(value, self.cheap_start, self.cheap_end):
            return "cheap"
        if time(17, 0) <= value <= time(18, 30):
            return "peak"
        if time(0, 0) <= value <= time(7, 30) or time(23, 0) <= value <= time(23, 30):
            return "night"
        if time(8, 0) <= value <= time(16, 30) or time(19, 0) <= value <= time(22, 30):
            return "day"
        return "other"


def _empty_bucket_totals() -> dict[str, Any]:
    """Return an empty bucket total structure."""
    return {
        "today": _empty_one_period(),
        "yesterday": _empty_one_period(),
    }


def _empty_one_period() -> dict[str, float]:
    """Return empty totals for one period."""
    return defaultdict(float, {"total_kwh": 0.0, "cost": 0.0})


def _add_bucket(target: dict[str, float], bucket: str, kwh: float, cost: float) -> None:
    """Add kWh and cost to a period bucket."""
    target[f"{bucket}_kwh"] += kwh
    target["total_kwh"] += kwh
    target["cost"] += cost


def _find_column(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    """Find a CSV column by exact or normalized name."""
    normalized = {_normalize(name): name for name in fieldnames}
    for candidate in candidates:
        if candidate in fieldnames:
            return candidate
        match = normalized.get(_normalize(candidate))
        if match:
            return match
    for fieldname in fieldnames:
        lower = fieldname.lower()
        if "read" in lower and "date" in lower and "time" in lower:
            return fieldname
    return None


def _normalize(value: str) -> str:
    """Normalize a column name."""
    return value.lower().replace(" ", "").replace("_", "").replace("-", "")


def _parse_datetime(raw: str) -> datetime | None:
    """Parse common ESB timestamp formats."""
    value = raw.strip()
    if not value:
        return None
    for fmt in (
        "%d-%m-%Y %H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_float(raw: str | None) -> float | None:
    """Parse a float value."""
    if raw is None:
        return None
    value = raw.strip().replace(",", "")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_time(raw: str, fallback: str) -> time:
    """Parse HH:MM time."""
    for value in (raw, fallback):
        try:
            hour, minute = value.split(":", 1)
            return time(int(hour), int(minute))
        except (TypeError, ValueError):
            continue
    return time(0, 0)


def _time_in_range(value: time, start: time, end: time) -> bool:
    """Check if a time is inside a range, including ranges crossing midnight."""
    if start <= end:
        return start <= value < end
    return value >= start or value < end
