"""Tests for ESB Smart Meter services and dynamic sensor registration."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esb_smart_meter.const import (
    CONF_IMPORT_PATH,
    CONF_KEEP_DAYS,
    CONF_MPRN,
    CONF_PASSWORD,
    CONF_TIME_SHIFT_MINUTES,
    CONF_USERNAME,
    DOMAIN,
    SERVICE_DOWNLOAD,
    SERVICE_PRUNE,
    SERVICE_RELOAD,
)


def _write_csv(path, rows: list[tuple[str, float, str]]) -> None:
    lines = ["Read Date and End Time,Read Value (kWh),Read Type"]
    for when, value, kind in rows:
        lines.append(f"{when},{value:.3f},{kind}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def test_services_reload_and_prune(hass, tmp_path):
    """reload and prune services refresh and trim CSV files."""
    now = dt_util.now().replace(minute=30, second=0, microsecond=0)
    old_day = (now - timedelta(days=20)).strftime("%d-%m-%Y %H:%M")
    recent_day = (now - timedelta(days=1)).strftime("%d-%m-%Y %H:%M")

    csv_path = tmp_path / "data.csv"
    _write_csv(
        csv_path,
        [
            (old_day, 1.0, "Active Import Interval (kW)"),
            (recent_day, 2.0, "Active Import Interval (kW)"),
        ],
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_IMPORT_PATH: str(tmp_path), CONF_TIME_SHIFT_MINUTES: 0},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.data["records"] == 2

    await hass.services.async_call(
        DOMAIN, SERVICE_PRUNE, {CONF_KEEP_DAYS: 5}, blocking=True
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.data["records"] == 1
    assert (tmp_path / "pruned_backup").is_dir()


async def test_download_service_without_and_with_credentials(hass, tmp_path):
    """download_latest warns when unconfigured and downloads when configured."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_IMPORT_PATH: str(tmp_path)},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Should not raise when credentials are missing.
    await hass.services.async_call(DOMAIN, SERVICE_DOWNLOAD, {}, blocking=True)

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_USERNAME: "ger@example.com",
            CONF_PASSWORD: "pw",
            CONF_MPRN: "10001234567",
        },
    )
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    with patch.object(coordinator, "async_download_latest") as mock_dl:
        await hass.services.async_call(DOMAIN, SERVICE_DOWNLOAD, {}, blocking=True)
        mock_dl.assert_awaited_once()


async def test_export_sensors_added_dynamically_after_setup(hass, tmp_path):
    """Export sensors appear automatically when export data arrives post-setup."""
    csv_path = tmp_path / "data.csv"
    _write_csv(csv_path, [("01-01-2026 00:30", 1.0, "Active Import Interval (kW)")])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_IMPORT_PATH: str(tmp_path)},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.esb_smart_meter_total_export") is None

    _write_csv(
        csv_path,
        [
            ("01-01-2026 00:30", 1.0, "Active Import Interval (kW)"),
            ("01-01-2026 12:30", 0.75, "Active Export Interval (kW)"),
        ],
    )
    await hass.services.async_call(DOMAIN, SERVICE_RELOAD, {}, blocking=True)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.esb_smart_meter_total_export")
    assert state is not None
    assert float(state.state) == 0.75
