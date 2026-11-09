"""Tests for the repair issues and the download error surfaced to the UI."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esb_smart_meter.const import (
    CONF_IMPORT_PATH,
    CONF_MPRN,
    CONF_PASSWORD,
    CONF_STALE_HOURS,
    CONF_TIME_SHIFT_MINUTES,
    CONF_USERNAME,
    DOMAIN,
    SERVICE_DOWNLOAD,
)
from custom_components.esb_smart_meter.downloader import ESBDownloadError

from .conftest import SAMPLE_CSV


async def _setup(hass, path, options=None, **data):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_IMPORT_PATH: str(path), CONF_TIME_SHIFT_MINUTES: -30, **data},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _issue(hass, key, entry):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{key}_{entry.entry_id}")


async def test_stale_raised_then_cleared(hass, csv_dir):
    """Old data raises data_stale; a fresh reading clears it on the next refresh."""
    entry = await _setup(hass, csv_dir)  # SAMPLE_CSV is from January 2026
    assert _issue(hass, "data_stale", entry) is not None
    assert _issue(hass, "no_csv_data", entry) is None

    fresh = (dt_util.now() - timedelta(hours=2)).strftime("%d-%m-%Y %H:00")
    (csv_dir / "fresh.csv").write_text(
        f"Read Date and End Time,Read Value\n{fresh},0.500\n", encoding="utf-8"
    )
    await hass.data[DOMAIN][entry.entry_id].async_refresh()
    await hass.async_block_till_done()
    assert _issue(hass, "data_stale", entry) is None


async def test_no_data_wins_over_stale(hass, tmp_path):
    """With no CSV rows only no_csv_data is raised, never data_stale too."""
    entry = await _setup(hass, tmp_path)
    assert _issue(hass, "no_csv_data", entry) is not None
    assert _issue(hass, "data_stale", entry) is None


async def test_stale_threshold_from_options(hass, csv_dir):
    """A threshold above the data's age keeps the repair away."""
    entry = await _setup(hass, csv_dir, options={CONF_STALE_HOURS: 10**6})
    assert _issue(hass, "data_stale", entry) is None


async def test_download_error_reaches_ui(hass, tmp_path):
    """ESBDownloadError surfaces as HomeAssistantError, not 'Unknown error'."""
    (tmp_path / "esb.csv").write_text(SAMPLE_CSV, encoding="utf-8")
    await _setup(hass, tmp_path, **{CONF_USERNAME: "u", CONF_PASSWORD: "p", CONF_MPRN: "1"})
    with (
        patch(
            "custom_components.esb_smart_meter.downloader.download_latest_csv",
            side_effect=ESBDownloadError("ESB request failed: 404"),
        ),
        pytest.raises(HomeAssistantError, match="404"),
    ):
        await hass.services.async_call(DOMAIN, SERVICE_DOWNLOAD, blocking=True)
