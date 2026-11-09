"""ESB Smart Meter integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import issue_registry as ir

from .const import (
    CONF_CHEAP_END,
    CONF_CHEAP_START,
    CONF_CURRENCY,
    CONF_DAY_START,
    CONF_DISCOUNT_PERCENT,
    CONF_EXPORT_RATE,
    CONF_IMPORT_PATH,
    CONF_KEEP_DAYS,
    CONF_MPRN,
    CONF_NIGHT_START,
    CONF_PASSWORD,
    CONF_PEAK_END,
    CONF_PEAK_START,
    CONF_RATES,
    CONF_REBUILD,
    CONF_STALE_HOURS,
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
    DEFAULT_KEEP_DAYS,
    DEFAULT_NIGHT_START,
    DEFAULT_PEAK_END,
    DEFAULT_PEAK_START,
    DEFAULT_RATES,
    DEFAULT_STALE_HOURS,
    DEFAULT_STANDING_CHARGE,
    DEFAULT_TIME_SHIFT_MINUTES,
    DEFAULT_VAT_PERCENT,
    DOMAIN,
    PLATFORMS,
    SERVICE_DOWNLOAD,
    SERVICE_IMPORT_STATISTICS,
    SERVICE_PRUNE,
    SERVICE_RELOAD,
)
from .coordinator import ESBSmartMeterCoordinator
from .statistics import async_backfill_statistics

LOGGER = logging.getLogger(__name__)
ISSUE_NO_DATA = "no_csv_data"
ISSUE_STALE = "data_stale"

RATE_SCHEMA = vol.Schema(
    {
        vol.Optional("cheap", default=DEFAULT_RATES["cheap"]): vol.Coerce(float),
        vol.Optional("night", default=DEFAULT_RATES["night"]): vol.Coerce(float),
        vol.Optional("day", default=DEFAULT_RATES["day"]): vol.Coerce(float),
        vol.Optional("peak", default=DEFAULT_RATES["peak"]): vol.Coerce(float),
        vol.Optional("other", default=DEFAULT_RATES["other"]): vol.Coerce(float),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_NAME, default="ESB Smart Meter"): cv.string,
                vol.Optional(CONF_IMPORT_PATH, default=DEFAULT_IMPORT_PATH): cv.string,
                vol.Optional(
                    CONF_TIME_SHIFT_MINUTES, default=DEFAULT_TIME_SHIFT_MINUTES
                ): vol.Coerce(int),
                vol.Optional(CONF_CHEAP_START, default=DEFAULT_CHEAP_START): cv.string,
                vol.Optional(CONF_CHEAP_END, default=DEFAULT_CHEAP_END): cv.string,
                vol.Optional(CONF_NIGHT_START, default=DEFAULT_NIGHT_START): cv.string,
                vol.Optional(CONF_DAY_START, default=DEFAULT_DAY_START): cv.string,
                vol.Optional(CONF_PEAK_START, default=DEFAULT_PEAK_START): cv.string,
                vol.Optional(CONF_PEAK_END, default=DEFAULT_PEAK_END): cv.string,
                vol.Optional(CONF_CURRENCY, default=DEFAULT_CURRENCY): cv.string,
                vol.Optional(
                    CONF_STANDING_CHARGE, default=DEFAULT_STANDING_CHARGE
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_EXPORT_RATE, default=DEFAULT_EXPORT_RATE
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_VAT_PERCENT, default=DEFAULT_VAT_PERCENT
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_DISCOUNT_PERCENT, default=DEFAULT_DISCOUNT_PERCENT
                ): vol.Coerce(float),
                vol.Optional(CONF_RATES, default=DEFAULT_RATES): RATE_SCHEMA,
                vol.Optional(CONF_USERNAME): cv.string,
                vol.Optional(CONF_PASSWORD): cv.string,
                vol.Optional(CONF_MPRN): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


def _coordinators(hass: HomeAssistant) -> list[ESBSmartMeterCoordinator]:
    """Return all loaded ESB coordinators."""
    return [
        value
        for value in hass.data.get(DOMAIN, {}).values()
        if isinstance(value, ESBSmartMeterCoordinator)
    ]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up ESB Smart Meter from YAML import and register services."""
    hass.data.setdefault(DOMAIN, {})

    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data=dict(config[DOMAIN]),
            )
        )

    async def handle_reload(call: ServiceCall) -> None:
        """Refresh all ESB Smart Meter coordinators from disk."""
        for coordinator in _coordinators(hass):
            await coordinator.async_request_refresh()

    async def handle_download(call: ServiceCall) -> None:
        """Download the latest CSV from the ESB portal (if configured)."""
        downloaded = False
        for coordinator in _coordinators(hass):
            if coordinator.has_download_credentials():
                await coordinator.async_download_latest()
                downloaded = True
        if not downloaded:
            LOGGER.warning(
                "esb_smart_meter.download called but no entry has ESB "
                "username/password/MPRN configured"
            )

    async def handle_import_statistics(call: ServiceCall) -> None:
        """Backfill CSV history into long-term statistics."""
        rebuild = call.data.get(CONF_REBUILD, False)
        for coordinator in _coordinators(hass):
            await async_backfill_statistics(hass, coordinator, rebuild=rebuild)

    async def handle_prune(call: ServiceCall) -> None:
        """Trim stored readings to the most recent keep_days."""
        keep_days = call.data.get(CONF_KEEP_DAYS, DEFAULT_KEEP_DAYS)
        for coordinator in _coordinators(hass):
            result = await coordinator.async_prune(keep_days)
            LOGGER.info(
                "ESB prune (%s): kept %s, removed %s of %s readings",
                coordinator.name,
                result["after"],
                result["removed"],
                result["before"],
            )

    hass.services.async_register(DOMAIN, SERVICE_RELOAD, handle_reload)
    hass.services.async_register(DOMAIN, SERVICE_DOWNLOAD, handle_download)
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_STATISTICS,
        handle_import_statistics,
        schema=vol.Schema({vol.Optional(CONF_REBUILD, default=False): cv.boolean}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PRUNE,
        handle_prune,
        schema=vol.Schema(
            {
                vol.Optional(CONF_KEEP_DAYS, default=DEFAULT_KEEP_DAYS): vol.All(
                    vol.Coerce(int), vol.Range(min=1)
                )
            }
        ),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up an ESB Smart Meter config entry."""
    coordinator = ESBSmartMeterCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    @callback
    def _set_issue(key: str, active: bool, placeholders: dict[str, str]) -> None:
        """Raise or clear one repair issue for this entry."""
        issue_id = f"{key}_{entry.entry_id}"
        if not active:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            return
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders=placeholders,
        )

    @callback
    def _sync_repair_issue() -> None:
        """Raise or clear the 'no data' and 'stale data' repair issues."""
        data = coordinator.data or {}
        available = bool(data.get("available"))
        # Absent from the no-data payload, so the no-data issue wins.
        age = data.get("last_reading_age_hours")
        threshold = entry.options.get(CONF_STALE_HOURS, DEFAULT_STALE_HOURS)
        _set_issue(
            ISSUE_NO_DATA, not available, {"path": str(coordinator.import_path)}
        )
        _set_issue(
            ISSUE_STALE,
            available and age is not None and age > threshold,
            {"age": str(round(age or 0)), "threshold": str(threshold)},
        )

    _sync_repair_issue()
    entry.async_on_unload(coordinator.async_add_listener(_sync_repair_issue))
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Keep long-term statistics in step with the CSVs automatically. The
    # backfill resumes from the newest stored point, so each run only writes
    # the handful of hours that are actually new and this stays cheap at the
    # coordinator's 30-minute cadence. The import_statistics service remains
    # for forcing a full rebuild.
    stats_lock = asyncio.Lock()

    async def _run_backfill() -> None:
        """Import any newly available hours into long-term statistics."""
        if stats_lock.locked():
            # A previous run is still going; the next refresh will catch up.
            return
        async with stats_lock:
            try:
                await async_backfill_statistics(hass, coordinator)
            except Exception:  # noqa: BLE001 - never let this break the entry
                LOGGER.exception("ESB statistics backfill failed")

    @callback
    def _schedule_backfill() -> None:
        """Queue a statistics backfill after a successful refresh."""
        if "recorder" not in hass.config.components:
            return
        if not (coordinator.data and coordinator.data.get("available")):
            return
        entry.async_create_background_task(
            hass, _run_backfill(), f"{DOMAIN}_statistics_{entry.entry_id}"
        )

    entry.async_on_unload(coordinator.async_add_listener(_schedule_backfill))
    # The first refresh already happened above, so seed history right away
    # rather than waiting for the next poll.
    _schedule_backfill()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an ESB Smart Meter config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        for key in (ISSUE_NO_DATA, ISSUE_STALE):
            ir.async_delete_issue(hass, DOMAIN, f"{key}_{entry.entry_id}")
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
