"""Tests for the ESB Smart Meter coordinator."""

from datetime import time

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esb_smart_meter.const import (
    CONF_DISCOUNT_PERCENT,
    CONF_EXPORT_RATE,
    CONF_IMPORT_PATH,
    CONF_RATES,
    CONF_STANDING_CHARGE,
    CONF_TIME_SHIFT_MINUTES,
    CONF_VAT_PERCENT,
    DOMAIN,
)
from custom_components.esb_smart_meter.coordinator import ESBSmartMeterCoordinator


def _entry(path, **data):
    # VAT and discount default to off here so each test opts into them
    # explicitly; the integration's own default VAT is 9%.
    payload = {
        CONF_IMPORT_PATH: str(path),
        CONF_TIME_SHIFT_MINUTES: 0,
        CONF_VAT_PERCENT: 0.0,
        CONF_DISCOUNT_PERCENT: 0.0,
    }
    payload.update(data)
    return MockConfigEntry(domain=DOMAIN, data=payload)


async def test_reads_and_totals(hass, csv_dir):
    coordinator = ESBSmartMeterCoordinator(hass, _entry(csv_dir))
    data = await coordinator._async_update_data()
    assert data["available"] is True
    assert data["records"] == 5
    assert data["total_import_kwh"] == pytest.approx(1.6)  # 3.2 kW/2
    assert data["files"] == ["esb.csv"]


async def test_no_data(hass, tmp_path):
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    data = await coordinator._async_update_data()
    assert data["available"] is False
    assert data["records"] == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (time(3, 0), "cheap"),
        (time(2, 0), "cheap"),
        (time(4, 0), "night"),  # end exclusive
        (time(18, 0), "peak"),
        (time(18, 30), "peak"),
        (time(12, 0), "day"),
        (time(22, 30), "day"),
        (time(7, 30), "night"),
        (time(23, 0), "night"),
    ],
)
async def test_bucket_boundaries(hass, tmp_path, value, expected):
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    assert coordinator._bucket_for(value) == expected


async def test_buckets_partition_the_day(hass, tmp_path):
    """cheap + night + day + peak must cover all 48 half-hours exactly once."""
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    seen = set()
    for hour in range(24):
        for minute in (0, 30):
            bucket = coordinator._bucket_for(time(hour, minute))
            assert bucket in {"cheap", "night", "day", "peak"}
            seen.add(bucket)
    assert seen == {"cheap", "night", "day", "peak"}


async def test_today_costs_and_standing_charge(hass, tmp_path):
    """Net lines, with no VAT or discount configured."""
    day = dt_util.now().strftime("%d-%m-%Y")
    (tmp_path / "today.csv").write_text(
        "Read Date and End Time,Read Value\n" f"{day} 12:00,2.000\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(
        hass,
        _entry(
            tmp_path,
            **{
                CONF_STANDING_CHARGE: 0.5,
                CONF_RATES: {"day": 0.30},
                CONF_VAT_PERCENT: 0.0,
                CONF_DISCOUNT_PERCENT: 0.0,
            },
        ),
    )
    data = await coordinator._async_update_data()
    today = data["today"]
    assert today["total_kwh"] == pytest.approx(1.0)  # 2.0 kW/2
    assert today["day_kwh"] == pytest.approx(1.0)
    assert today["energy_cost"] == pytest.approx(0.3)
    assert today["standing_charge"] == pytest.approx(0.5)
    assert today["discount"] == pytest.approx(0.0)
    assert today["vat"] == pytest.approx(0.0)
    assert today["cost"] == pytest.approx(0.8)


async def test_vat_and_discount_applied_in_bill_order(hass, tmp_path):
    """Discount comes off the net charges, then VAT applies to what remains.

    1 kWh at 0.30 plus a 0.50 standing charge = 0.80 net. A 16% discount
    leaves 0.672, and 9% VAT on that is 0.06048, for 0.73248 payable. Applying
    VAT before the discount, or the discount to only one of the two charge
    lines, all give different answers - hence the explicit ordering here.
    """
    day = dt_util.now().strftime("%d-%m-%Y")
    (tmp_path / "today.csv").write_text(
        "Read Date and End Time,Read Value\n" f"{day} 12:00,2.000\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(
        hass,
        _entry(
            tmp_path,
            **{
                CONF_STANDING_CHARGE: 0.5,
                CONF_RATES: {"day": 0.30},
                CONF_VAT_PERCENT: 9.0,
                CONF_DISCOUNT_PERCENT: 16.0,
            },
        ),
    )
    data = await coordinator._async_update_data()
    today = data["today"]

    # Charge lines stay net and pre-discount, the way a bill itemises them.
    assert today["energy_cost"] == pytest.approx(0.3)
    assert today["standing_charge"] == pytest.approx(0.5)

    # Period figures are rounded to 3dp, so compare at that precision.
    assert today["discount"] == pytest.approx(0.128, abs=0.001)
    assert today["net_cost"] == pytest.approx(0.672, abs=0.001)
    assert today["vat"] == pytest.approx(0.060, abs=0.001)
    assert today["cost"] == pytest.approx(0.732, abs=0.001)

    # Sanity: the itemised lines reconstruct the total.
    assert today["cost"] == pytest.approx(
        today["energy_cost"]
        + today["standing_charge"]
        - today["discount"]
        + today["vat"],
        abs=0.001,
    )


async def test_export_earnings_carry_no_vat_or_discount(hass, tmp_path):
    """Feed-in is income, not a charge, so neither VAT nor discount applies."""
    (tmp_path / "e.csv").write_text(
        "MPRN,Read Value (kWh),Read Type,Read Date and End Time\n"
        "10,4.000,Active Export Interval,01-01-2026 12:00\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(
        hass,
        _entry(
            tmp_path,
            **{
                CONF_EXPORT_RATE: 0.20,
                CONF_VAT_PERCENT: 9.0,
                CONF_DISCOUNT_PERCENT: 16.0,
            },
        ),
    )
    data = await coordinator._async_update_data()
    assert data["total_export_kwh"] == pytest.approx(4.0)
    # 4 kWh * 0.20, untouched by the 9% / 16% above.
    earnings = coordinator.exported_readings()
    assert sum(e[2] for e in earnings) == pytest.approx(0.8)


async def test_statistics_costs_carry_vat_and_discount(hass, tmp_path):
    """Energy dashboard cost must be what is payable, not the net figure."""
    (tmp_path / "a.csv").write_text(
        "Read Date and End Time,Read Value (kWh)\n01-01-2026 12:00,1.000\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(
        hass,
        _entry(
            tmp_path,
            **{
                CONF_RATES: {"day": 0.30},
                CONF_VAT_PERCENT: 9.0,
                CONF_DISCOUNT_PERCENT: 16.0,
                CONF_STANDING_CHARGE: 99.0,  # must NOT leak into per-reading cost
            },
        ),
    )
    readings = coordinator.costed_readings()
    assert len(readings) == 1
    assert readings[0][2] == pytest.approx(0.30 * 0.84 * 1.09)


async def test_total_never_drops(hass, tmp_path):
    csv_path = tmp_path / "h.csv"
    csv_path.write_text(
        "Read Date and End Time,Read Value\n01-01-2026 12:00,2.000\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    first = await coordinator._async_update_data()
    assert first["total_import_kwh"] == pytest.approx(1.0)  # 2.0 kW/2

    # Rewrite with a smaller value: the high-water mark should hold the total.
    csv_path.write_text(
        "Read Date and End Time,Read Value\n01-01-2026 12:00,1.000\n",
        encoding="utf-8",
    )
    second = await coordinator._async_update_data()
    assert second["total_import_kwh"] == pytest.approx(1.0)


async def test_import_export_split(hass, tmp_path):
    (tmp_path / "e.csv").write_text(
        "MPRN,Meter Serial Number,Read Value,Read Type,Read Date and End Time\n"
        "10,1,2.000,Active Import Interval (kW),01-01-2026 12:00\n"
        "10,1,0.500,Active Export Interval (kW),01-01-2026 12:00\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path, **{CONF_EXPORT_RATE: 0.2}))
    data = await coordinator._async_update_data()
    # Import and export share a timestamp; both survive dedup.
    assert data["records"] == 1
    assert data["total_import_kwh"] == pytest.approx(1.0)  # 2.0 kW/2
    assert data["has_export"] is True
    assert data["total_export_kwh"] == pytest.approx(0.25)


def _full_day_csv(day) -> str:
    lines = ["Read Date and End Time,Read Value"]
    for hour in range(24):
        for minute in (0, 30):
            lines.append(f"{day.strftime('%d-%m-%Y')} {hour:02d}:{minute:02d},0.100")
    return "\n".join(lines) + "\n"


async def test_recent_complete_day(hass, tmp_path):
    from datetime import timedelta

    yesterday = dt_util.now().date() - timedelta(days=1)
    (tmp_path / "y.csv").write_text(_full_day_csv(yesterday), encoding="utf-8")
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    data = await coordinator._async_update_data()
    assert data["recent_complete_date"] == yesterday
    assert data["recent_complete"]["total_kwh"] == pytest.approx(2.4)  # 48 * 0.1 kW/2


async def test_prune_keeps_recent_and_backs_up(hass, tmp_path):
    (tmp_path / "multi.csv").write_text(
        "Read Date and End Time,Read Value\n"
        "01-01-2026 12:00,1.000\n"
        "02-01-2026 12:00,1.000\n"
        "03-01-2026 12:00,1.000\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    result = await hass.async_add_executor_job(coordinator._prune, 1)
    assert result == {"before": 3, "after": 2, "removed": 1}
    assert (tmp_path / "pruned_backup").is_dir()
    assert (tmp_path / "esb_smart_meter_history.csv").exists()

    # The consolidated file must re-read to exactly the kept rows.
    data = await coordinator._async_update_data()
    assert data["records"] == 2


async def test_projection_does_not_extrapolate_standing_charge(
    hass, tmp_path, freezer
):
    """The standing charge is fixed per day, so it must not be scaled.

    Six complete days plus a part-finished today, at a 0.8259/day standing
    charge. The standing half of the projection is exactly rate * days in the
    month; only the energy half is extrapolated from the complete days.
    """
    from datetime import timedelta

    # Frozen mid-month so six prior complete days stay inside the same month
    # (August has 31 days, matching the reported real-world case).
    freezer.move_to("2026-08-11 12:00:00")
    today = dt_util.now().date()

    lines = ["Read Date and End Time,Read Value (kWh)"]
    for offset in range(1, 7):  # six complete days before today
        day = today - timedelta(days=offset)
        for hour in range(24):
            for minute in (0, 30):
                stamp = f"{day.strftime('%d-%m-%Y')} {hour:02d}:{minute:02d}"
                lines.append(f"{stamp},0.010")
    # Today, partially through: a single reading.
    lines.append(f"{today.strftime('%d-%m-%Y')} 00:30,0.500")
    (tmp_path / "m.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    coordinator = ESBSmartMeterCoordinator(
        hass,
        _entry(
            tmp_path,
            **{
                CONF_STANDING_CHARGE: 0.8259,
                CONF_RATES: dict.fromkeys(
                    ("cheap", "night", "day", "peak", "other"), 1.0
                ),
            },
        ),
    )
    data = await coordinator._async_update_data()

    days_in_month = data["days_in_month"]
    assert days_in_month == 31
    assert data["month_complete_day_count"] == 6

    # Deterministic: never divided by complete days, never extrapolated.
    assert data["projected_month_standing_charge"] == pytest.approx(
        round(0.8259 * days_in_month, 2)
    )

    # Energy: 48 * 0.010 = 0.48/day at 1.0/kWh, averaged over complete days
    # only, so today's partial 0.5 must not appear in the numerator.
    assert data["projected_month_energy_cost"] == pytest.approx(
        round(0.48 * days_in_month, 2), abs=0.02
    )
    assert data["projected_month_cost"] == pytest.approx(
        data["projected_month_standing_charge"]
        + data["projected_month_energy_cost"],
        abs=0.01,
    )

    # The old formula scaled the whole figure, standing charge included, and
    # divided a 7-day numerator by 6 complete days. It must now be lower.
    old_formula = data["month"]["cost"] / 6 * days_in_month
    assert data["projected_month_cost"] < old_formula


async def test_projection_zero_without_a_complete_day(hass, tmp_path):
    """No complete day means no usage basis, so no projection is offered."""
    day = dt_util.now().strftime("%d-%m-%Y")
    (tmp_path / "p.csv").write_text(
        f"Read Date and End Time,Read Value (kWh)\n{day} 00:30,1.000\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(
        hass, _entry(tmp_path, **{CONF_STANDING_CHARGE: 0.8259})
    )
    data = await coordinator._async_update_data()
    assert data["month_complete_day_count"] == 0
    assert data["projected_month_cost"] == 0.0


async def test_unknown_value_column_is_reported_not_guessed(hass, tmp_path, caplog):
    """A file with no recognisable value column must be skipped and explained.

    The timestamp lookup accepts any header that looks like an ESB timestamp.
    That heuristic used to run for the value lookup too, so a file like this
    matched the timestamp column as its value column - the rows then failed to
    parse as floats and the file yielded nothing, with no clue as to why.
    """
    (tmp_path / "odd.csv").write_text(
        "Read Date and End Time,Consumption\n01-01-2026 12:00,2.000\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    data = await coordinator._async_update_data()

    assert data["records"] == 0
    assert "no value column found" in caplog.text
    # The message has to name the headers, or it does not help anyone.
    assert "Consumption" in caplog.text
    assert "odd.csv" in caplog.text


async def test_timestamp_column_still_matched_loosely(hass, tmp_path):
    """The loose timestamp match is deliberate and must survive the fix."""
    (tmp_path / "loose.csv").write_text(
        "MPRN,Read Date & End Time (GMT),Read Value (kWh)\n"
        "10,01-01-2026 12:00,2.000\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    data = await coordinator._async_update_data()
    assert data["records"] == 1
    assert data["total_import_kwh"] == pytest.approx(2.0)


async def test_peak_bucket_is_reported_for_month_and_recent_day(hass, tmp_path):
    """Peak had energy sensors but no month/recent-day cost counterpart."""
    from datetime import timedelta

    yesterday = dt_util.now().date() - timedelta(days=1)
    lines = ["Read Date and End Time,Read Value (kWh)"]
    for hour in range(24):
        for minute in (0, 30):
            lines.append(
                f"{yesterday.strftime('%d-%m-%Y')} {hour:02d}:{minute:02d},0.100"
            )
    (tmp_path / "y.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    coordinator = ESBSmartMeterCoordinator(
        hass,
        _entry(
            tmp_path,
            **{
                CONF_RATES: dict.fromkeys(
                    ("cheap", "night", "day", "peak", "other"), 1.0
                )
            },
        ),
    )
    data = await coordinator._async_update_data()

    # 17:00-19:00 is four half-hours at 0.1 kWh.
    assert data["month"]["peak_kwh"] == pytest.approx(0.4)
    assert data["month"]["peak_cost"] == pytest.approx(0.4)
    assert data["recent_complete"]["peak_kwh"] == pytest.approx(0.4)
    assert data["recent_complete"]["peak_cost"] == pytest.approx(0.4)

    # Every band must be present for the four to sum to the whole day.
    month = data["month"]
    assert sum(month[f"{b}_kwh"] for b in ("cheap", "night", "day", "peak")) == (
        pytest.approx(month["total_kwh"])
    )


async def test_kw_readings_are_scaled_to_kwh(hass, tmp_path):
    """"Read Value" is mean kW over a half hour, so energy is half of it."""
    (tmp_path / "kw.csv").write_text(
        "Read Date and End Time,Read Value\n01-01-2026 12:00,2.000\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    data = await coordinator._async_update_data()
    assert data["total_import_kwh"] == pytest.approx(1.0)


async def test_kwh_headers_are_not_rescaled(hass, tmp_path):
    """A column already published in kWh must be taken at face value."""
    (tmp_path / "kwh.csv").write_text(
        "Read Date and End Time,Read Value (kWh)\n01-01-2026 12:00,2.000\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    data = await coordinator._async_update_data()
    assert data["total_import_kwh"] == pytest.approx(2.0)


async def test_time_shift_applied(hass, tmp_path):
    (tmp_path / "s.csv").write_text(
        "Read Date and End Time,Read Value\n01-01-2026 00:00,1.000\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(
        hass, _entry(tmp_path, **{CONF_TIME_SHIFT_MINUTES: -30})
    )
    readings = coordinator.costed_readings()
    assert len(readings) == 1
    # 00:00 shifted back 30 minutes -> previous day 23:30.
    assert readings[0][0].hour == 23
    assert readings[0][0].minute == 30


async def test_aware_iso_timestamp_converted_to_local_tz(hass, tmp_path):
    """Aware UTC ISO timestamps are converted to HA's local timezone."""
    await hass.config.async_set_time_zone("Europe/Dublin")
    csv_path = tmp_path / "utc.csv"
    # 01:30Z in July is 02:30 IST (Europe/Dublin, UTC+1). With -30 min shift
    # that becomes 02:00 local (cheap bucket), not 01:00 UTC (night bucket).
    csv_path.write_text(
        "Read Date and End Time,Read Value (kWh)\n2026-07-15T01:30:00Z,1.0\n",
        encoding="utf-8",
    )
    entry = _entry(
        tmp_path,
        **{
            CONF_TIME_SHIFT_MINUTES: -30,
            CONF_RATES: {"cheap": 0.10, "night": 0.20, "day": 0.30, "peak": 0.40},
        },
    )
    coordinator = ESBSmartMeterCoordinator(hass, entry)
    readings = coordinator.costed_readings()
    assert len(readings) == 1
    when, _, cost = readings[0]
    assert when.hour == 2
    assert when.minute == 0
    assert cost == pytest.approx(0.10)
