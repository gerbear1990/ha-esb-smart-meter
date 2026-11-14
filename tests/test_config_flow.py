"""Tests for the ESB Smart Meter config and options flows."""

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esb_smart_meter.const import CONF_RATES, DOMAIN


def _full_input(import_path: str) -> dict:
    return {
        "name": "ESB Smart Meter",
        "import_path": import_path,
        "time_shift_minutes": -30,
        "cheap_start": "02:00",
        "cheap_end": "04:00",
        "night_start": "23:00",
        "day_start": "08:00",
        "peak_start": "17:00",
        "peak_end": "19:00",
        "currency": "EUR",
        "standing_charge": 0.0,
        "cheap_rate": 0.08,
        "night_rate": 0.18,
        "day_rate": 0.34,
        "peak_rate": 0.36,
        "other_rate": 0.34,
    }


async def test_user_flow_creates_entry(hass: HomeAssistant, tmp_path):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _full_input(str(tmp_path))
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[CONF_RATES] == {
        "cheap": 0.08,
        "night": 0.18,
        "day": 0.34,
        "peak": 0.36,
        "other": 0.34,
    }
    # Flat rate_* fields should have been folded into the nested dict.
    assert "cheap_rate" not in data


async def test_single_instance_only(hass: HomeAssistant, tmp_path):
    MockConfigEntry(domain=DOMAIN, data={}, unique_id="default").add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _full_input(str(tmp_path))
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_updates_settings(hass: HomeAssistant, tmp_path):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=_full_input(str(tmp_path)) | {CONF_RATES: {"day": 0.34}},
        unique_id="default",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM

    new_options = {
        "import_path": str(tmp_path),
        "time_shift_minutes": -30,
        "cheap_start": "02:00",
        "cheap_end": "05:00",
        "night_start": "23:00",
        "day_start": "08:00",
        "peak_start": "17:00",
        "peak_end": "19:00",
        "currency": "EUR",
        "standing_charge": 0.45,
        "cheap_rate": 0.07,
        "night_rate": 0.18,
        "day_rate": 0.40,
        "peak_rate": 0.36,
        "other_rate": 0.34,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], new_options
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_RATES]["day"] == 0.40
    assert entry.options["standing_charge"] == 0.45
    assert entry.options["cheap_end"] == "05:00"


async def test_invalid_time_shows_form_error(hass: HomeAssistant, tmp_path):
    """Invalid HH:MM time strings are rejected in both user and options flows."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    bad = _full_input(str(tmp_path)) | {"cheap_start": "25:99"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], bad)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"cheap_start": "invalid_time"}


async def test_options_flow_can_set_portal_credentials(hass: HomeAssistant, tmp_path):
    """Portal credentials can be added or updated via the options flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=_full_input(str(tmp_path)) | {CONF_RATES: {"day": 0.34}},
        unique_id="default",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.has_download_credentials() is False

    result = await hass.config_entries.options.async_init(entry.entry_id)
    options = {
        "import_path": str(tmp_path),
        "time_shift_minutes": -30,
        "cheap_start": "02:00",
        "cheap_end": "04:00",
        "night_start": "23:00",
        "day_start": "08:00",
        "peak_start": "17:00",
        "peak_end": "19:00",
        "currency": "EUR",
        "standing_charge": 0.0,
        "cheap_rate": 0.08,
        "night_rate": 0.18,
        "day_rate": 0.34,
        "peak_rate": 0.36,
        "other_rate": 0.34,
        "username": "ger@example.com",
        "password": "secret",
        "mprn": "10001234567",
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], options
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.has_download_credentials() is True
