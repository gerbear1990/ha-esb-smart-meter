"""Data coordinator for ESB Smart Meter."""

from __future__ import annotations

import csv
import logging
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CHEAP_END,
    CONF_CHEAP_START,
    CONF_CURRENCY,
    CONF_DAY_START,
    CONF_DISCOUNT_PERCENT,
    CONF_EXPORT_RATE,
    CONF_IMPORT_PATH,
    CONF_MPRN,
    CONF_NIGHT_START,
    CONF_PASSWORD,
    CONF_PEAK_END,
    CONF_PEAK_START,
    CONF_RATES,
    CONF_STANDING_CHARGE,
    CONF_TIME_SHIFT_MINUTES,
    CONF_USERNAME,
    CONF_VAT_PERCENT,
    DEFAULT_CHEAP_END,
    DEFAULT_CHEAP_START,
    DEFAULT_CURRENCY,
    DEFAULT_DAY_START,
    DEFAULT_DISCOUNT_PERCENT,
    DEFAULT_EXPORT_RATE,
    DEFAULT_IMPORT_PATH,
    DEFAULT_NIGHT_START,
    DEFAULT_PEAK_END,
    DEFAULT_PEAK_START,
    DEFAULT_RATES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STANDING_CHARGE,
    DEFAULT_TIME_SHIFT_MINUTES,
    DEFAULT_VAT_PERCENT,
    ENERGY_HEADER_MARKER,
    EXPORT_KEYWORD,
    INTERVAL_HOURS,
    INTERVALS_PER_DAY,
    RATE_BUCKETS,
    READTYPE_COLUMNS,
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
    """One ESB half-hour reading (timezone-aware)."""

    when: datetime
    kwh: float
    source: str
    kind: str = "import"  # "import" or "export"


class ESBSmartMeterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Read ESB smart meter CSV exports and derive useful HA data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self._total_high_water = 0.0
        self._export_high_water = 0.0
        self._reload_settings()
        super().__init__(
            hass,
            LOGGER,
            name=entry.data.get(CONF_NAME, "ESB Smart Meter"),
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

    def _conf(self, key: str, default: Any) -> Any:
        """Read a setting, preferring options over the original data."""
        if key in self.entry.options:
            return self.entry.options[key]
        return self.entry.data.get(key, default)

    def _reload_settings(self) -> None:
        """(Re)load user settings from the config entry and its options."""
        self.import_path = Path(self._conf(CONF_IMPORT_PATH, DEFAULT_IMPORT_PATH))
        self.time_shift = int(
            self._conf(CONF_TIME_SHIFT_MINUTES, DEFAULT_TIME_SHIFT_MINUTES)
        )
        self.cheap_start = _parse_time(
            self._conf(CONF_CHEAP_START, DEFAULT_CHEAP_START), DEFAULT_CHEAP_START
        )
        self.cheap_end = _parse_time(
            self._conf(CONF_CHEAP_END, DEFAULT_CHEAP_END), DEFAULT_CHEAP_END
        )
        self.night_start = _parse_time(
            self._conf(CONF_NIGHT_START, DEFAULT_NIGHT_START), DEFAULT_NIGHT_START
        )
        self.day_start = _parse_time(
            self._conf(CONF_DAY_START, DEFAULT_DAY_START), DEFAULT_DAY_START
        )
        self.peak_start = _parse_time(
            self._conf(CONF_PEAK_START, DEFAULT_PEAK_START), DEFAULT_PEAK_START
        )
        self.peak_end = _parse_time(
            self._conf(CONF_PEAK_END, DEFAULT_PEAK_END), DEFAULT_PEAK_END
        )
        self.rates = DEFAULT_RATES | dict(self._conf(CONF_RATES, {}))
        self.currency = self._conf(CONF_CURRENCY, DEFAULT_CURRENCY)
        self.standing_charge = float(
            self._conf(CONF_STANDING_CHARGE, DEFAULT_STANDING_CHARGE)
        )
        self.export_rate = float(self._conf(CONF_EXPORT_RATE, DEFAULT_EXPORT_RATE))
        # Stored as percentages because that is how they appear on a bill;
        # converted to fractions once here rather than at every use.
        self.vat_percent = float(self._conf(CONF_VAT_PERCENT, DEFAULT_VAT_PERCENT))
        self.discount_percent = float(
            self._conf(CONF_DISCOUNT_PERCENT, DEFAULT_DISCOUNT_PERCENT)
        )

    @property
    def vat_rate(self) -> float:
        """VAT as a fraction, e.g. 0.09 for 9%."""
        return self.vat_percent / 100.0

    @property
    def discount_rate(self) -> float:
        """Supplier discount as a fraction, e.g. 0.16 for 16%."""
        return self.discount_percent / 100.0

    def _bill(self, energy_cost: float, standing_charge: float) -> dict[str, float]:
        """Build the charge lines of a bill from net energy and standing cost.

        Mirrors how a supplier assembles one: net charges, then the discount,
        then VAT on what is actually payable. Returned amounts are unrounded;
        callers round once at the end.
        """
        subtotal = energy_cost + standing_charge
        discount = subtotal * self.discount_rate
        net = subtotal - discount
        vat = net * self.vat_rate
        return {
            "energy_cost": energy_cost,
            "standing_charge": standing_charge,
            "subtotal": subtotal,
            "discount": discount,
            "net_cost": net,
            "vat": vat,
            "cost": net + vat,
        }

    def has_download_credentials(self) -> bool:
        """Return True if ESB portal download is configured."""
        return bool(
            self._conf(CONF_USERNAME, "")
            and self._conf(CONF_PASSWORD, "")
            and self._conf(CONF_MPRN, "")
        )

    async def async_download_latest(self) -> None:
        """Download the latest ESB CSV, then refresh sensors.

        This is intentionally only wired to an explicit service call: ESB
        rate-limits logins heavily (roughly a couple of attempts per day), so
        it must not run on the regular polling interval.
        """
        try:
            await self.hass.async_add_executor_job(self._download_latest)
        except RuntimeError as err:  # ESBDownloadError; downloader is imported lazily
            # A plain RuntimeError shows as "Unknown error" in the UI.
            raise HomeAssistantError(str(err)) from err
        await self.async_request_refresh()

    def _download_latest(self) -> None:
        """Download the latest ESB CSV into the import folder (executor)."""
        # Imported lazily so the optional beautifulsoup4/requests dependency is
        # only touched when the user actually uses the portal download.
        from .downloader import ESBDownloadError, download_latest_csv

        username = self._conf(CONF_USERNAME, "")
        password = self._conf(CONF_PASSWORD, "")
        mprn = self._conf(CONF_MPRN, "")
        if not username or not password or not mprn:
            raise ESBDownloadError(
                "ESB username, password, and MPRN must be configured to download."
            )

        self.import_path.mkdir(parents=True, exist_ok=True)
        result = download_latest_csv(username=username, password=password, mprn=mprn)
        output_path = self.import_path / "esb_latest.csv"
        output_path.write_text(result.csv_text, encoding="utf-8")
        LOGGER.info(
            "Downloaded ESB CSV to %s (%s rows, source filename: %s)",
            output_path,
            result.rows,
            result.filename,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch and process CSV data."""
        return await self.hass.async_add_executor_job(self._read_data)

    def _read_data(self) -> dict[str, Any]:
        """Read CSV data from disk and derive period totals."""
        self.import_path.mkdir(parents=True, exist_ok=True)
        all_readings = self._load_readings()
        now = dt_util.now()

        import_readings = [r for r in all_readings if r.kind == "import"]
        export_readings = [r for r in all_readings if r.kind == "export"]
        export_block = self._export_block(export_readings, now)

        if not import_readings:
            current_bucket = self._bucket_for(now)
            return {
                "available": False,
                "records": 0,
                "files": sorted({r.source for r in all_readings}),
                "last_import": now,
                "current_bucket": current_bucket,
                "current_rate": self._rate(current_bucket),
                "message": f"No ESB CSV rows found in {self.import_path}",
                **export_block,
            }

        readings = import_readings
        readings.sort(key=lambda item: item.when)
        latest = readings[-1]
        today = now.date()
        yesterday = today - timedelta(days=1)
        month_start = today.replace(day=1)

        periods: dict[date, dict[str, float]] = {}
        reading_counts: dict[date, int] = defaultdict(int)
        total_kwh = 0.0

        for reading in readings:
            bucket = self._bucket_for(reading.when)
            cost = reading.kwh * self._rate(bucket)
            total_kwh += reading.kwh

            reading_date = reading.when.date()
            reading_counts[reading_date] += 1
            period = periods.setdefault(reading_date, _empty_one_period())
            _add_bucket(period, bucket, reading.kwh, cost)

        today_period = self._finalize_period(periods.get(today), days=1)
        yesterday_period = self._finalize_period(periods.get(yesterday), days=1)

        month_days = [d for d in periods if month_start <= d <= today]
        month_raw = _empty_one_period()
        for day in month_days:
            _merge_period(month_raw, periods[day])
        month_period = self._finalize_period(month_raw, days=len(month_days))

        # "Complete" days have a full set of half-hour intervals and exclude
        # today (still in progress).
        complete_dates = sorted(
            day
            for day, count in reading_counts.items()
            if count >= INTERVALS_PER_DAY and day < today
        )
        last_7 = [
            _period_summary(day, self._finalize_period(periods[day], days=1))
            for day in complete_dates[-7:]
        ]
        last_7_cost = round(sum(item["cost"] for item in last_7), 3)
        last_7_kwh = round(sum(item["total_kwh"] for item in last_7), 3)

        recent_complete_date = complete_dates[-1] if complete_dates else None
        recent_complete = self._finalize_period(
            periods.get(recent_complete_date) if recent_complete_date else None, days=1
        )

        month_complete_days = [d for d in complete_dates if month_start <= d <= today]
        days_in_month = _days_in_month(today)

        # Only the *energy* part of the bill is extrapolated. The standing
        # charge is deterministic - it accrues once per day for every day of
        # the month whatever the meter does - so the month-end figure is simply
        # rate * days_in_month. Scaling it along with usage inflated the
        # projection by (days_in_month / complete_days - 1) times the standing
        # charge accrued so far, which was invisible while the default rate was
        # 0.0 and dominant once a real rate was configured.
        projected_standing_charge = self.standing_charge * days_in_month

        # Averaged over complete days only, on both sides of the division.
        # `month_period` spans every day with data including today, so using it
        # here would extrapolate a part-finished day as though it were whole.
        complete_energy_cost = sum(
            periods[day]["cost"] for day in month_complete_days
        )
        projected_energy_cost = (
            complete_energy_cost / len(month_complete_days) * days_in_month
            if month_complete_days
            else 0.0
        )

        # Discount and VAT are applied to the projected net, not extrapolated
        # themselves - they are percentages of whatever the bill turns out to
        # be, so they follow from it rather than being estimated separately.
        projected = self._bill(projected_energy_cost, projected_standing_charge)

        # Without a single complete day there is no basis for the usage half of
        # the estimate, so no projection is offered rather than reporting the
        # standing charge alone as though it were one.
        has_projection = bool(month_complete_days)
        projected_month_cost = round(projected["cost"], 2) if has_projection else 0.0

        total_kwh = round(total_kwh, 3)
        if total_kwh < self._total_high_water:
            LOGGER.debug(
                "Computed total import %.3f kWh is below previous high-water "
                "mark %.3f kWh (CSV removed?); holding the higher value",
                total_kwh,
                self._total_high_water,
            )
            total_kwh = self._total_high_water
        else:
            self._total_high_water = total_kwh

        coverage_days = (latest.when.date() - readings[0].when.date()).days + 1
        current_bucket = self._bucket_for(now)

        return {
            "available": True,
            "records": len(readings),
            "files": sorted({reading.source for reading in readings}),
            "last_import": now,
            "first_reading": readings[0].when,
            "last_reading": latest.when,
            "last_interval_kwh": latest.kwh,
            "last_reading_age_hours": round(
                (now - latest.when).total_seconds() / 3600, 1
            ),
            "coverage_days": coverage_days,
            "total_import_kwh": total_kwh,
            "current_bucket": current_bucket,
            "current_rate": self._rate(current_bucket),
            "currency": self.currency,
            "today": today_period,
            "yesterday": yesterday_period,
            "month": month_period,
            "recent_complete_date": recent_complete_date,
            "recent_complete": recent_complete,
            "last_7_complete_days": last_7,
            "last_7_cost": last_7_cost,
            "last_7_energy": last_7_kwh,
            "last_7_average_daily_cost": round(last_7_cost / len(last_7), 3)
            if last_7
            else 0.0,
            "last_7_average_daily_energy": round(last_7_kwh / len(last_7), 3)
            if last_7
            else 0.0,
            "month_complete_day_count": len(month_complete_days),
            "projected_month_cost": projected_month_cost,
            "projected_month_energy_cost": round(projected["energy_cost"], 2)
            if has_projection
            else 0.0,
            "projected_month_standing_charge": round(projected["standing_charge"], 2)
            if has_projection
            else 0.0,
            "projected_month_discount": round(projected["discount"], 2)
            if has_projection
            else 0.0,
            "projected_month_net_cost": round(projected["net_cost"], 2)
            if has_projection
            else 0.0,
            "projected_month_vat": round(projected["vat"], 2)
            if has_projection
            else 0.0,
            "days_in_month": days_in_month,
            "vat_percent": self.vat_percent,
            "discount_percent": self.discount_percent,
            "message": "OK",
            **export_block,
        }

    def costed_readings(self) -> list[tuple[datetime, float, float]]:
        """Return (when, kwh, cost) for every reading, sorted by time.

        Used by the statistics backfill. Import readings only (consumption).

        Costs carry the discount and VAT so the Energy dashboard shows what is
        actually payable. The standing charge is deliberately absent: it is a
        per-day charge with no per-interval meaning, and spreading it over
        readings would attribute fixed cost to usage.
        """
        readings = [r for r in self._load_readings() if r.kind == "import"]
        readings.sort(key=lambda item: item.when)
        # Discount then VAT collapse to a single multiplier on the net energy
        # cost, since neither depends on the amount.
        factor = (1.0 - self.discount_rate) * (1.0 + self.vat_rate)
        return [
            (r.when, r.kwh, r.kwh * self._rate(self._bucket_for(r.when)) * factor)
            for r in readings
        ]

    def exported_readings(self) -> list[tuple[datetime, float, float]]:
        """Return (when, kwh, earnings) for every export reading, sorted by time.

        The microgeneration counterpart of :meth:`costed_readings`. Feed-in is
        paid at a single flat rate rather than a time-of-use bucket, so the
        earnings are simply kWh * export_rate.

        No VAT and no supplier discount here: feed-in payments to a domestic
        microgenerator are income rather than a charge, so neither applies.
        """
        readings = [r for r in self._load_readings() if r.kind == "export"]
        readings.sort(key=lambda item: item.when)
        return [(r.when, r.kwh, r.kwh * self.export_rate) for r in readings]

    async def async_prune(self, keep_days: int) -> dict[str, int]:
        """Trim stored readings to the most recent ``keep_days``, then refresh."""
        result = await self.hass.async_add_executor_job(self._prune, keep_days)
        await self.async_request_refresh()
        return result

    def _prune(self, keep_days: int) -> dict[str, int]:
        """Consolidate readings into one CSV keeping only recent days (executor).

        Originals are moved into a ``pruned_backup`` subfolder (nothing is hard
        deleted), and timestamps are written back un-shifted so the regular
        time-shift re-applies cleanly on the next read. The lifetime
        ``total_import`` sensor is unaffected thanks to the high-water mark.
        """
        keep_days = max(1, int(keep_days))
        readings = self._load_readings()
        if not readings:
            return {"before": 0, "after": 0, "removed": 0}

        readings.sort(key=lambda item: item.when)
        cutoff = readings[-1].when.date() - timedelta(days=keep_days)
        kept = [r for r in readings if r.when.date() >= cutoff]

        backup_dir = self.import_path / "pruned_backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt_util.now().strftime("%Y%m%d_%H%M%S")
        for csv_path in sorted(self.import_path.glob("*.csv")):
            shutil.move(str(csv_path), str(backup_dir / f"{stamp}_{csv_path.name}"))

        shift = timedelta(minutes=self.time_shift)
        history = self.import_path / "esb_smart_meter_history.csv"
        with history.open("w", newline="", encoding="utf-8") as file_obj:
            writer = csv.writer(file_obj)
            writer.writerow(["Read Date and End Time", "Read Value", "Read Type"])
            for reading in kept:
                raw = (reading.when - shift).strftime("%d-%m-%Y %H:%M")
                read_type = (
                    "Active Export Interval (kW)"
                    if reading.kind == "export"
                    else "Active Import Interval (kW)"
                )
                # read_type below is written with a "(kW)" header, so convert the
                # stored energy back to mean power. Without this the interval
                # scaling would be re-applied on the next read and compound.
                writer.writerow(
                    [raw, f"{reading.kwh / INTERVAL_HOURS}", read_type]
                )

        LOGGER.info(
            "Pruned ESB readings: kept %s of %s (keep_days=%s); originals in %s",
            len(kept),
            len(readings),
            keep_days,
            backup_dir,
        )
        return {
            "before": len(readings),
            "after": len(kept),
            "removed": len(readings) - len(kept),
        }

    def _rate(self, bucket: str) -> float:
        """Return the configured rate for a bucket, falling back to 'other'."""
        return self.rates.get(bucket, self.rates.get("other", 0.0))

    def _export_block(
        self, readings: list[Reading], now: datetime
    ) -> dict[str, Any]:
        """Aggregate microgeneration/export readings (kWh) and feed-in credit."""
        today = now.date()
        yesterday = today - timedelta(days=1)
        month_start = today.replace(day=1)

        total = today_kwh = yesterday_kwh = month_kwh = 0.0
        for reading in readings:
            total += reading.kwh
            day = reading.when.date()
            if day == today:
                today_kwh += reading.kwh
            elif day == yesterday:
                yesterday_kwh += reading.kwh
            if month_start <= day <= today:
                month_kwh += reading.kwh

        total = round(total, 3)
        if total < self._export_high_water:
            total = self._export_high_water
        else:
            self._export_high_water = total

        rate = self.export_rate
        return {
            "has_export": bool(readings),
            "total_export_kwh": total,
            "today_export_kwh": round(today_kwh, 3),
            "yesterday_export_kwh": round(yesterday_kwh, 3),
            "month_export_kwh": round(month_kwh, 3),
            "today_export_credit": round(today_kwh * rate, 3),
            "yesterday_export_credit": round(yesterday_kwh * rate, 3),
            "month_export_credit": round(month_kwh * rate, 3),
        }

    def _finalize_period(
        self, period: dict[str, float] | None, *, days: int
    ) -> dict[str, float]:
        """Round a period and build its bill lines.

        `energy_cost`, `standing_charge` and the per-bucket costs are NET
        amounts before discount and VAT, laid out the way a bill is: net lines
        first, then the discount and VAT as their own lines, then the total.
        VAT on the standing charge cannot be attributed to a usage bucket, so
        mixing it into the buckets would make them stop summing to anything
        meaningful.
        """
        period = period or _empty_one_period()
        bill = self._bill(period.get("cost", 0.0), self.standing_charge * days)
        result: dict[str, float] = {
            "total_kwh": round(period.get("total_kwh", 0.0), 3),
            "energy_cost": round(bill["energy_cost"], 3),
            "standing_charge": round(bill["standing_charge"], 3),
            "discount": round(bill["discount"], 3),
            "net_cost": round(bill["net_cost"], 3),
            "vat": round(bill["vat"], 3),
            "cost": round(bill["cost"], 3),
        }
        for bucket in RATE_BUCKETS:
            result[f"{bucket}_kwh"] = round(period.get(f"{bucket}_kwh", 0.0), 3)
            result[f"{bucket}_cost"] = round(period.get(f"{bucket}_cost", 0.0), 3)
        return result

    def _load_readings(self) -> list[Reading]:
        """Load valid readings from all CSV files in the import folder.

        Deduplicated by (timestamp, kind) so import and export readings for the
        same half hour are both kept.
        """
        by_key: dict[tuple[datetime, str], Reading] = {}
        for csv_path in sorted(self.import_path.glob("*.csv")):
            for reading in self._read_csv(csv_path):
                by_key[(reading.when, reading.kind)] = reading
        return list(by_key.values())

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
                datetime_col = _find_column(
                    reader.fieldnames, DATETIME_COLUMNS, fuzzy=True
                )
                value_col = _find_column(reader.fieldnames, VALUE_COLUMNS)
                if datetime_col is None or value_col is None:
                    # Say which column is missing and what the file actually
                    # has. Silently skipping leaves the user with an empty
                    # integration and no way to tell why.
                    missing = " and ".join(
                        label
                        for label, found in (
                            ("timestamp", datetime_col),
                            ("value", value_col),
                        )
                        if found is None
                    )
                    LOGGER.warning(
                        "Ignoring %s: no %s column found. Headers present: %s",
                        csv_path.name,
                        missing,
                        ", ".join(reader.fieldnames),
                    )
                    return []
                readtype_col = _find_column(reader.fieldnames, READTYPE_COLUMNS)

                # "Active Import Interval (kW)" is a mean power held over the
                # half-hour interval, so energy is value * 0.5h. Only skip the
                # scaling if the export already publishes kWh.
                header = value_col.lower().replace(" ", "")
                value_scale = (
                    1.0 if ENERGY_HEADER_MARKER in header else INTERVAL_HOURS
                )

                readings: list[Reading] = []
                for row in reader:
                    when = _parse_datetime(row.get(datetime_col, ""))
                    value = _parse_float(row.get(value_col, ""))
                    if when is None or value is None:
                        continue
                    kwh = value * value_scale
                    if self.time_shift:
                        when += timedelta(minutes=self.time_shift)
                    kind = "import"
                    if readtype_col and EXPORT_KEYWORD in row.get(
                        readtype_col, ""
                    ).lower():
                        kind = "export"
                    readings.append(
                        Reading(
                            when=_as_local(when),
                            kwh=kwh,
                            source=csv_path.name,
                            kind=kind,
                        )
                    )
                return readings
        except Exception as err:  # noqa: BLE001 - keep one bad CSV from killing HA setup
            LOGGER.warning("Unable to parse ESB CSV %s: %s", csv_path, err)
            return []

    def _bucket_for(self, value: datetime | time) -> str:
        """Return the configured rate bucket for a local time.

        All band boundaries are user-configurable because they depend on the
        end user's supplier plan (the ESB CSV contains no tariff data). With the
        default smart-tariff boundaries the bands are contiguous, so every
        half-hour maps to exactly one bucket and cheap + night + day + peak sum
        to the total:

            cheap  configurable boost window (default 02:00-04:00), highest priority
            peak   peak_start-peak_end (default 17:00-19:00)
            night  night_start wrapping to day_start (default 23:00-08:00)
            day    everything else (default 08:00-17:00 and 19:00-23:00)
        """
        local = value.time() if isinstance(value, datetime) else value
        if _time_in_range(local, self.cheap_start, self.cheap_end):
            return "cheap"
        if _time_in_range(local, self.peak_start, self.peak_end):
            return "peak"
        if _time_in_range(local, self.night_start, self.day_start):
            return "night"
        return "day"


def _empty_one_period() -> dict[str, float]:
    """Return empty totals for one period."""
    return defaultdict(float, {"total_kwh": 0.0, "cost": 0.0})


def _add_bucket(target: dict[str, float], bucket: str, kwh: float, cost: float) -> None:
    """Add kWh and cost to a period bucket."""
    target[f"{bucket}_kwh"] += kwh
    target[f"{bucket}_cost"] += cost
    target["total_kwh"] += kwh
    target["cost"] += cost


def _merge_period(target: dict[str, float], other: dict[str, float]) -> None:
    """Accumulate one period's raw totals into another."""
    for key, value in other.items():
        target[key] += value


def _period_summary(day: date, period: dict[str, float]) -> dict[str, Any]:
    """Return a rounded daily summary for the last-7-days attribute."""
    summary: dict[str, Any] = {
        "date": day.isoformat(),
        "total_kwh": period["total_kwh"],
        "cost": period["cost"],
    }
    for bucket in RATE_BUCKETS:
        summary[f"{bucket}_kwh"] = period[f"{bucket}_kwh"]
        summary[f"{bucket}_cost"] = period[f"{bucket}_cost"]
    return summary


def _days_in_month(value: date) -> int:
    """Return number of days in the date's month."""
    if value.month == 12:
        next_month = date(value.year + 1, 1, 1)
    else:
        next_month = date(value.year, value.month + 1, 1)
    return (next_month - date(value.year, value.month, 1)).days


def _find_column(
    fieldnames: list[str], candidates: tuple[str, ...], *, fuzzy: bool = False
) -> str | None:
    """Find a CSV column by exact or normalized name.

    `fuzzy` additionally accepts any header that merely looks like an ESB
    timestamp ("read", "date" and "time" somewhere in it). It has to stay
    opt-in: applied to the value or read-type lookups, that heuristic happily
    returns the timestamp column, which is never a sensible answer for either.
    """
    normalized = {_normalize(name): name for name in fieldnames}
    for candidate in candidates:
        if candidate in fieldnames:
            return candidate
        match = normalized.get(_normalize(candidate))
        if match:
            return match
    if fuzzy:
        for fieldname in fieldnames:
            lower = fieldname.lower()
            if "read" in lower and "date" in lower and "time" in lower:
                return fieldname
    return None


def _normalize(value: str) -> str:
    """Normalize a column name."""
    return value.lower().replace(" ", "").replace("_", "").replace("-", "")


def _parse_datetime(raw: str) -> datetime | None:
    """Parse common ESB timestamp formats (returns naive local wall time)."""
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


def _as_local(value: datetime) -> datetime:
    """Attach or convert to HA's local timezone (DST-aware)."""
    tzinfo = dt_util.DEFAULT_TIME_ZONE or dt_util.UTC
    if value.tzinfo is not None:
        return value.astimezone(tzinfo)
    return value.replace(tzinfo=tzinfo)


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
        except (TypeError, ValueError, AttributeError):
            continue
    return time(0, 0)


def _time_in_range(value: time, start: time, end: time) -> bool:
    """Check if a time is inside a range, including ranges crossing midnight."""
    if start <= end:
        return start <= value < end
    return value >= start or value < end
