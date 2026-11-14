"""Tests for ESB Smart Meter diagnostics."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esb_smart_meter.const import (
    CONF_IMPORT_PATH,
    CONF_MPRN,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)
from custom_components.esb_smart_meter.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_redacts_credentials(hass, tmp_path):
    """Diagnostics must redact username, password, and MPRN in data and options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_IMPORT_PATH: str(tmp_path),
            CONF_USERNAME: "ger@example.com",
            CONF_PASSWORD: "super-secret-password",
            CONF_MPRN: "10001234567",
        },
        options={
            CONF_USERNAME: "ger2@example.com",
            CONF_PASSWORD: "other-password",
            CONF_MPRN: "10009999999",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)

    for section in ("data", "options"):
        assert diag["entry"][section][CONF_USERNAME] == "**REDACTED**"
        assert diag["entry"][section][CONF_PASSWORD] == "**REDACTED**"
        assert diag["entry"][section][CONF_MPRN] == "**REDACTED**"
    assert diag["settings"]["download_configured"] is True
    assert diag["settings"]["import_path"] == str(tmp_path)
