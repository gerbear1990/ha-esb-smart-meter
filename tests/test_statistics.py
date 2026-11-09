"""Tests for the long-term statistics backfill."""

import pytest
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.esb_smart_meter.const import (
    CONF_DISCOUNT_PERCENT,
    CONF_EXPORT_RATE,
    CONF_IMPORT_PATH,
    CONF_RATES,
    CONF_TIME_SHIFT_MINUTES,
    CONF_VAT_PERCENT,
    DOMAIN,
    STAT_COST_SUFFIX,
    STAT_ENERGY_SUFFIX,
    STAT_EXPORT_ENERGY_SUFFIX,
)
from custom_components.esb_smart_meter.coordinator import ESBSmartMeterCoordinator
from custom_components.esb_smart_meter.statistics import async_backfill_statistics

ENERGY_ID = f"{DOMAIN}:{STAT_ENERGY_SUFFIX}"
COST_ID = f"{DOMAIN}:{STAT_COST_SUFFIX}"
EXPORT_ENERGY_ID = f"{DOMAIN}:{STAT_EXPORT_ENERGY_SUFFIX}"

# Rates flattened to 1.0/kWh so cost equals energy and assertions stay readable.
FLAT_RATES = {"cheap": 1.0, "night": 1.0, "day": 1.0, "peak": 1.0, "other": 1.0}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Enable custom integrations with a recorder, in that order.

    This deliberately shadows the same-named autouse fixture in conftest. The
    recorder's database fixture asserts that `hass` has not been created yet,
    so `recorder_mock` has to be resolved before anything that pulls `hass` in
    - which `enable_custom_integrations` does.
    """
    yield


def _entry(path, **data):
    # The default -30 shift is kept: ESB timestamps an interval by its END, so
    # a row at 00:30 covers 00:00-00:30 and belongs to the 00:00 hour block.
    # Every expectation below assumes that real-world attribution.
    # VAT and discount are switched off so the cost series mirrors the energy
    # series exactly; test_coordinator covers their effect on cost separately.
    payload = {
        CONF_IMPORT_PATH: str(path),
        CONF_TIME_SHIFT_MINUTES: -30,
        CONF_RATES: FLAT_RATES,
        CONF_VAT_PERCENT: 0.0,
        CONF_DISCOUNT_PERCENT: 0.0,
    }
    payload.update(data)
    return MockConfigEntry(domain=DOMAIN, data=payload)


def _write_csv(path, rows: list[tuple[str, float]]) -> None:
    """Write an ESB-shaped CSV of (timestamp, kWh) rows.

    A "Read Value (kWh)" header is used so the coordinator's half-hour power
    scaling is skipped and the numbers below are energy exactly as written.
    """
    lines = ["Read Date and End Time,Read Value (kWh)"]
    lines += [f"{when},{value:.3f}" for when, value in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _sums(hass, statistic_id: str) -> list[tuple[float, float]]:
    """Return [(state, sum)] for every stored hour, oldest first."""
    await async_wait_recording_done(hass)
    stats = await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utc_from_timestamp(0),
        None,
        {statistic_id},
        "hour",
        None,
        {"state", "sum"},
    )
    return [(row["state"], row["sum"]) for row in stats.get(statistic_id, [])]


async def test_backfill_writes_cumulative_hourly_points(hass, tmp_path):
    _write_csv(
        tmp_path / "a.csv",
        [
            ("01-01-2026 00:30", 1.0),
            ("01-01-2026 01:00", 2.0),  # same hour -> one 3.0 kWh point
            ("01-01-2026 02:00", 4.0),
        ],
    )
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    written = await async_backfill_statistics(hass, coordinator)
    assert written == 2

    assert await _sums(hass, ENERGY_ID) == [(3.0, 3.0), (4.0, 7.0)]
    # Cost mirrors energy at the flat 1.0/kWh rate.
    assert await _sums(hass, COST_ID) == [(3.0, 3.0), (4.0, 7.0)]


async def test_second_run_is_a_noop(hass, tmp_path):
    """Re-running with unchanged CSVs must not inflate the totals."""
    _write_csv(tmp_path / "a.csv", [("01-01-2026 00:30", 1.0), ("01-01-2026 02:00", 4.0)])
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))

    await async_backfill_statistics(hass, coordinator)
    before = await _sums(hass, ENERGY_ID)
    await async_backfill_statistics(hass, coordinator)
    after = await _sums(hass, ENERGY_ID)

    assert before == after == [(1.0, 1.0), (4.0, 5.0)]


async def test_new_hours_continue_the_running_total(hass, tmp_path):
    csv_path = tmp_path / "a.csv"
    _write_csv(csv_path, [("01-01-2026 00:30", 1.0)])
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    await async_backfill_statistics(hass, coordinator)

    _write_csv(csv_path, [("01-01-2026 00:30", 1.0), ("01-01-2026 03:00", 2.0)])
    await async_backfill_statistics(hass, coordinator)

    assert await _sums(hass, ENERGY_ID) == [(1.0, 1.0), (2.0, 3.0)]


async def test_partial_hour_is_completed_not_lost(hass, tmp_path):
    """A late second half-hour must be folded into its already-written hour."""
    csv_path = tmp_path / "a.csv"
    _write_csv(csv_path, [("01-01-2026 00:30", 1.0)])
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    await async_backfill_statistics(hass, coordinator)
    assert await _sums(hass, ENERGY_ID) == [(1.0, 1.0)]

    # The 01:00 reading belongs to the same 00:00 hour block.
    _write_csv(csv_path, [("01-01-2026 00:30", 1.0), ("01-01-2026 01:00", 2.0)])
    await async_backfill_statistics(hass, coordinator)

    assert await _sums(hass, ENERGY_ID) == [(3.0, 3.0)]


async def test_pruned_history_does_not_reset_the_sum(hass, tmp_path):
    """The regression this fix targets: pruning must not restart the total.

    Statistics are written for three days, then the CSVs are trimmed to the
    last day only (what `prune` does). The next backfill must keep counting
    from the stored total instead of starting the retained window at zero.
    """
    csv_path = tmp_path / "a.csv"
    _write_csv(
        csv_path,
        [
            ("01-01-2026 00:30", 1.0),
            ("02-01-2026 00:30", 2.0),
            ("03-01-2026 00:30", 4.0),
        ],
    )
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    await async_backfill_statistics(hass, coordinator)
    assert await _sums(hass, ENERGY_ID) == [(1.0, 1.0), (2.0, 3.0), (4.0, 7.0)]

    # Simulate prune: only the most recent day survives on disk.
    _write_csv(csv_path, [("03-01-2026 00:30", 4.0)])
    await async_backfill_statistics(hass, coordinator)

    # Totals stay monotonic; no cliff at the retained-window boundary.
    assert await _sums(hass, ENERGY_ID) == [(1.0, 1.0), (2.0, 3.0), (4.0, 7.0)]


async def test_rebuild_restarts_from_zero(hass, tmp_path):
    csv_path = tmp_path / "a.csv"
    _write_csv(csv_path, [("01-01-2026 00:30", 1.0), ("02-01-2026 00:30", 2.0)])
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    await async_backfill_statistics(hass, coordinator)
    assert await _sums(hass, ENERGY_ID) == [(1.0, 1.0), (2.0, 3.0)]

    _write_csv(csv_path, [("02-01-2026 00:30", 2.0)])
    await async_backfill_statistics(hass, coordinator, rebuild=True)

    # The retained hour is rewritten from a zero baseline. The older point is
    # untouched, which is exactly why rebuild is documented as a repair tool.
    assert (await _sums(hass, ENERGY_ID))[-1] == (2.0, 2.0)


async def test_export_series_is_backfilled(hass, tmp_path):
    (tmp_path / "e.csv").write_text(
        "MPRN,Read Value (kWh),Read Type,Read Date and End Time\n"
        "10,2.000,Active Import Interval,01-01-2026 00:30\n"
        "10,0.500,Active Export Interval,01-01-2026 00:30\n",
        encoding="utf-8",
    )
    coordinator = ESBSmartMeterCoordinator(
        hass, _entry(tmp_path, **{CONF_EXPORT_RATE: 0.2})
    )
    await async_backfill_statistics(hass, coordinator)

    assert await _sums(hass, ENERGY_ID) == [(2.0, 2.0)]
    assert await _sums(hass, EXPORT_ENERGY_ID) == [(0.5, 0.5)]


async def test_no_readings_writes_nothing(hass, tmp_path):
    coordinator = ESBSmartMeterCoordinator(hass, _entry(tmp_path))
    assert await async_backfill_statistics(hass, coordinator) == 0
    assert await _sums(hass, ENERGY_ID) == []


async def test_setup_entry_backfills_automatically(hass, tmp_path):
    """The entry should seed statistics without a service call."""
    _write_csv(tmp_path / "a.csv", [("01-01-2026 00:30", 1.5)])
    entry = _entry(tmp_path)
    entry.add_to_hass(hass)

    # Setting up the entry pulls in the component itself.
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await _sums(hass, ENERGY_ID) == [(1.5, 1.5)]


async def test_refresh_picks_up_new_hours(hass, tmp_path):
    """A later coordinator refresh should extend the series on its own."""
    csv_path = tmp_path / "a.csv"
    _write_csv(csv_path, [("01-01-2026 00:30", 1.0)])
    entry = _entry(tmp_path)
    entry.add_to_hass(hass)

    # Setting up the entry pulls in the component itself.
    assert await hass.config_entries.async_setup(entry.entry_id)
    # The backfill runs as a background task, which a plain block_till_done skips.
    await hass.async_block_till_done(wait_background_tasks=True)
    assert await _sums(hass, ENERGY_ID) == [(1.0, 1.0)]

    _write_csv(csv_path, [("01-01-2026 00:30", 1.0), ("01-01-2026 05:00", 3.0)])
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert await _sums(hass, ENERGY_ID) == [(1.0, 1.0), (3.0, 4.0)]
