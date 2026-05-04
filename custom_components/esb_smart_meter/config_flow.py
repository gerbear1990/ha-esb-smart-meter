"""Config flow for ESB Smart Meter."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME

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
    DEFAULT_TIME_SHIFT_MINUTES,
    DOMAIN,
)


class ESBSmartMeterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle ESB Smart Meter config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Create a config entry from the UI."""
        if user_input is not None:
            data = dict(user_input)
            data[CONF_RATES] = {
                "cheap": data.pop("cheap_rate"),
                "night": data.pop("night_rate"),
                "day": data.pop("day_rate"),
                "peak": data.pop("peak_rate"),
                "other": data.pop("other_rate"),
            }
            await self.async_set_unique_id("default")
            self._abort_if_unique_id_configured(updates=data)
            return self.async_create_entry(title=data[CONF_NAME], data=data)

        return self.async_show_form(step_id="user", data_schema=_schema())

    async def async_step_import(
        self, import_config: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Import YAML configuration."""
        await self.async_set_unique_id("default")
        self._abort_if_unique_id_configured(updates=import_config)
        return self.async_create_entry(
            title=import_config.get(CONF_NAME, "ESB Smart Meter"), data=import_config
        )


def _schema() -> vol.Schema:
    """Return the UI config schema."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default="ESB Smart Meter"): str,
            vol.Required(CONF_IMPORT_PATH, default=DEFAULT_IMPORT_PATH): str,
            vol.Required(
                CONF_TIME_SHIFT_MINUTES, default=DEFAULT_TIME_SHIFT_MINUTES
            ): int,
            vol.Required(CONF_CHEAP_START, default=DEFAULT_CHEAP_START): str,
            vol.Required(CONF_CHEAP_END, default=DEFAULT_CHEAP_END): str,
            vol.Required("cheap_rate", default=DEFAULT_RATES["cheap"]): float,
            vol.Required("night_rate", default=DEFAULT_RATES["night"]): float,
            vol.Required("day_rate", default=DEFAULT_RATES["day"]): float,
            vol.Required("peak_rate", default=DEFAULT_RATES["peak"]): float,
            vol.Required("other_rate", default=DEFAULT_RATES["other"]): float,
        }
    )
