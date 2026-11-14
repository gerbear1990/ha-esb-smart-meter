"""Backfill ESB history into Home Assistant long-term statistics.

The regular sensors only accrue from the moment the integration is set up.
Because ESB CSV exports contain months of half-hourly history, we can push
that history straight into the recorder as *external* statistics so it shows
up on the Energy dashboard with the correct dates.

Cumulative sums are always continued from whatever the recorder already holds
rather than recomputed from zero. The CSVs on disk are a moving window - the
`prune` service deliberately trims them - so rebuilding the running total from
the current files would restart it partway through history and leave a cliff in
the Energy dashboard at the boundary. Seeding from the stored sum keeps the
series monotonic no matter how much of the source data has aged out.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    STAT_COST_SUFFIX,
    STAT_ENERGY_SUFFIX,
    STAT_EXPORT_EARNINGS_SUFFIX,
    STAT_EXPORT_ENERGY_SUFFIX,
)
from .coordinator import ESBSmartMeterCoordinator

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _LastPoint:
    """The newest statistics point already stored for one statistic_id."""

    start: datetime
    total: float
    """Cumulative sum through and including :attr:`start`."""
    value: float
    """That hour's own value, i.e. the sum contributed by :attr:`start`."""

    @property
    def total_before(self) -> float:
        """Cumulative sum *before* this hour, so it can be re-emitted."""
        return self.total - self.value


@dataclass(frozen=True)
class _Resume:
    """Where to resume writing, and the running totals to resume from."""

    after: datetime | None = None
    energy_offset: float = 0.0
    money_offset: float = 0.0


async def async_backfill_statistics(
    hass: HomeAssistant,
    coordinator: ESBSmartMeterCoordinator,
    *,
    rebuild: bool = False,
) -> int:
    """Import CSV history as external statistics.

    By default only hours at or after the newest stored point are written, and
    their sums continue from the stored running total, so this is cheap enough
    to run after every coordinator refresh.

    Set ``rebuild`` to rewrite every hour present in the CSVs from a zero
    baseline. That is the escape hatch for a corrupted series; note it will
    disagree with older retained points if the CSVs no longer reach back as far
    as the recorder does.

    Returns the number of hourly statistic points written for imported energy.
    """
    readings = await hass.async_add_executor_job(coordinator.costed_readings)
    exported = await hass.async_add_executor_job(coordinator.exported_readings)

    if not readings and not exported:
        LOGGER.warning("ESB statistics backfill found no readings to import")
        return 0

    written = 0

    if readings:
        written = await _write_pair(
            hass,
            coordinator,
            readings,
            rebuild=rebuild,
            energy_suffix=STAT_ENERGY_SUFFIX,
            energy_label="imported energy",
            money_suffix=STAT_COST_SUFFIX,
            money_label="imported cost",
        )
    else:
        LOGGER.debug("ESB statistics backfill found no import readings")

    # Microgeneration history gets the same treatment, so exported energy and
    # feed-in earnings appear on the Energy dashboard with their real dates
    # rather than only accruing from setup time.
    if exported:
        await _write_pair(
            hass,
            coordinator,
            exported,
            rebuild=rebuild,
            energy_suffix=STAT_EXPORT_ENERGY_SUFFIX,
            energy_label="exported energy",
            money_suffix=STAT_EXPORT_EARNINGS_SUFFIX,
            money_label="export earnings",
        )
    else:
        LOGGER.debug("ESB statistics backfill found no export readings")

    return written


async def _write_pair(
    hass: HomeAssistant,
    coordinator: ESBSmartMeterCoordinator,
    readings: list[tuple[datetime, float, float]],
    *,
    rebuild: bool,
    energy_suffix: str,
    energy_label: str,
    money_suffix: str,
    money_label: str,
) -> int:
    """Write one energy/money statistics pair, continuing from stored sums."""
    energy_id = f"{DOMAIN}:{energy_suffix}"
    money_id = f"{DOMAIN}:{money_suffix}"

    resume = _Resume()
    if not rebuild:
        resume = await _resume_from(hass, energy_id, money_id)

    energy_stats, money_stats = _build_hourly(
        readings,
        after=resume.after,
        energy_offset=resume.energy_offset,
        money_offset=resume.money_offset,
    )

    if not energy_stats:
        LOGGER.debug(
            "ESB statistics for %s are already up to date (nothing at or after %s)",
            energy_id,
            resume.after,
        )
        return 0

    async_add_external_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{coordinator.name} {energy_label}",
            source=DOMAIN,
            statistic_id=energy_id,
            unit_class="energy",
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        ),
        energy_stats,
    )
    async_add_external_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{coordinator.name} {money_label}",
            source=DOMAIN,
            statistic_id=money_id,
            unit_class=None,
            unit_of_measurement=coordinator.currency,
        ),
        money_stats,
    )
    LOGGER.info(
        "ESB statistics wrote %s hourly points to %s and %s (resumed from %s)",
        len(energy_stats),
        energy_id,
        money_id,
        resume.after if resume.after else "start of history",
    )
    return len(energy_stats)


async def _resume_from(
    hass: HomeAssistant, energy_id: str, money_id: str
) -> _Resume:
    """Work out where to resume a statistics pair from.

    The two series are written together and must stay in lockstep. If either is
    missing, unreadable, or they disagree on where they end, there is no sound
    baseline to continue from and the pair is rebuilt from zero rather than
    resumed at a guessed offset.
    """
    energy_last = await _last_point(hass, energy_id)
    money_last = await _last_point(hass, money_id)

    if energy_last is None or money_last is None:
        return _Resume()

    if energy_last.start != money_last.start:
        LOGGER.warning(
            "ESB statistics %s and %s end at different hours (%s vs %s); "
            "rebuilding both from the available CSV history",
            energy_id,
            money_id,
            energy_last.start,
            money_last.start,
        )
        return _Resume()

    return _Resume(
        after=energy_last.start,
        energy_offset=energy_last.total_before,
        money_offset=money_last.total_before,
    )


async def _last_point(hass: HomeAssistant, statistic_id: str) -> _LastPoint | None:
    """Return the newest stored point for a statistic_id, if it is usable.

    The recorder stores statistics timestamps as float epoch seconds; they are
    converted back to aware datetimes so callers can compare them directly
    against reading timestamps.
    """
    result = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, True, {"sum", "state"}
    )
    rows = result.get(statistic_id)
    if not rows:
        return None

    row = rows[0]
    start = row.get("start")
    total = row.get("sum")
    value = row.get("state")
    if start is None or total is None or value is None:
        # Without the hour's own value the running total before it is unknown,
        # so the series cannot be safely resumed.
        LOGGER.debug("Statistics row for %s is incomplete: %s", statistic_id, row)
        return None

    return _LastPoint(
        start=dt_util.utc_from_timestamp(float(start)),
        total=float(total),
        value=float(value),
    )


def _build_hourly(
    readings: list[tuple[datetime, float, float]],
    *,
    after: datetime | None = None,
    energy_offset: float = 0.0,
    money_offset: float = 0.0,
) -> tuple[list[StatisticData], list[StatisticData]]:
    """Aggregate half-hourly readings into cumulative hourly statistics.

    ``after`` is the start of the last hour already stored. That hour is
    re-emitted rather than skipped, because a further half-hour reading may
    have landed in it since it was written; the offsets are the sums recorded
    *before* it, so re-adding its energy reproduces the correct running total.
    """
    hourly_energy: dict[datetime, float] = defaultdict(float)
    hourly_money: dict[datetime, float] = defaultdict(float)
    for when, kwh, money in readings:
        hour = when.replace(minute=0, second=0, microsecond=0)
        if after is not None and hour < after:
            continue
        hourly_energy[hour] += kwh
        hourly_money[hour] += money

    energy_stats: list[StatisticData] = []
    money_stats: list[StatisticData] = []
    running_energy = energy_offset
    running_money = money_offset
    for hour in sorted(hourly_energy):
        running_energy += hourly_energy[hour]
        running_money += hourly_money[hour]
        energy_stats.append(
            StatisticData(
                start=hour,
                state=round(hourly_energy[hour], 3),
                sum=round(running_energy, 3),
            )
        )
        money_stats.append(
            StatisticData(
                start=hour,
                state=round(hourly_money[hour], 4),
                sum=round(running_money, 4),
            )
        )
    return energy_stats, money_stats
