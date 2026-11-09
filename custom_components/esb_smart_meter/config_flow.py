"""Config and options flow for ESB Smart Meter."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback

from .const import (
    CONF_CHEAP_END,
    CONF_CHEAP_START,
    CONF_CURRENCY,
    CONF_DAY_START,
    CONF_DISCOUNT_PERCENT,
    CONF_STALE_HOURS,
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
    DEFAULT_STALE_HOURS,
    DEFAULT_EXPORT_RATE,
    DEFAULT_IMPORT_PATH,
    DEFAULT_NIGHT_START,
    DEFAULT_PEAK_END,
    DEFAULT_PEAK_START,
    DEFAULT_RATES,
    DEFAULT_STANDING_CHARGE,
    DEFAULT_TIME_SHIFT_MINUTES,
    DEFAULT_VAT_PERCENT,
    DOMAIN,
)

_RATE_FIELDS = ("cheap_rate", "night_rate", "day_rate", "peak_rate", "other_rate")


def _rates_from_input(data: dict[str, Any]) -> dict[str, float]:
    """Pull the flat rate_* fields into a nested rates dict."""
    return {
        bucket: data.pop(f"{bucket}_rate")
        for bucket in ("cheap", "night", "day", "peak", "other")
    }


class ESBSmartMeterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle ESB Smart Meter config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ESBOptionsFlow:
        """Return the options flow handler."""
        return ESBOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Create a config entry from the UI."""
        if user_input is not None:
            data = dict(user_input)
            data[CONF_RATES] = _rates_from_input(data)
            await self.async_set_unique_id("default")
            self._abort_if_unique_id_configured(updates=data)
            return self.async_create_entry(title=data[CONF_NAME], data=data)

        return self.async_show_form(step_id="user", data_schema=_user_schema())

    async def async_step_import(
        self, import_config: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Import YAML configuration."""
        await self.async_set_unique_id("default")
        self._abort_if_unique_id_configured(updates=import_config)
        return self.async_create_entry(
            title=import_config.get(CONF_NAME, "ESB Smart Meter"), data=import_config
        )


class ESBOptionsFlow(config_entries.OptionsFlow):
    """Change processing settings after setup, without re-adding."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            options = dict(user_input)
            options[CONF_RATES] = _rates_from_input(options)
            return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="init", data_schema=_options_schema(self.config_entry)
        )


def _current(entry: config_entries.ConfigEntry, key: str, default: Any) -> Any:
    """Return the current effective value (options over data)."""
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


def _user_schema() -> vol.Schema:
    """Return the initial UI config schema."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default="ESB Smart Meter"): str,
            vol.Required(CONF_IMPORT_PATH, default=DEFAULT_IMPORT_PATH): str,
            vol.Required(
                CONF_TIME_SHIFT_MINUTES, default=DEFAULT_TIME_SHIFT_MINUTES
            ): int,
            vol.Required(CONF_CHEAP_START, default=DEFAULT_CHEAP_START): str,
            vol.Required(CONF_CHEAP_END, default=DEFAULT_CHEAP_END): str,
            vol.Required(CONF_NIGHT_START, default=DEFAULT_NIGHT_START): str,
            vol.Required(CONF_DAY_START, default=DEFAULT_DAY_START): str,
            vol.Required(CONF_PEAK_START, default=DEFAULT_PEAK_START): str,
            vol.Required(CONF_PEAK_END, default=DEFAULT_PEAK_END): str,
            vol.Required(CONF_CURRENCY, default=DEFAULT_CURRENCY): str,
            vol.Required(
                CONF_STANDING_CHARGE, default=DEFAULT_STANDING_CHARGE
            ): vol.Coerce(float),
            vol.Required(
                CONF_EXPORT_RATE, default=DEFAULT_EXPORT_RATE
            ): vol.Coerce(float),
            vol.Required(
                CONF_VAT_PERCENT, default=DEFAULT_VAT_PERCENT
            ): vol.Coerce(float),
            vol.Required(
                CONF_DISCOUNT_PERCENT, default=DEFAULT_DISCOUNT_PERCENT
            ): vol.Coerce(float),
            vol.Required("cheap_rate", default=DEFAULT_RATES["cheap"]): vol.Coerce(float),
            vol.Required("night_rate", default=DEFAULT_RATES["night"]): vol.Coerce(float),
            vol.Required("day_rate", default=DEFAULT_RATES["day"]): vol.Coerce(float),
            vol.Required("peak_rate", default=DEFAULT_RATES["peak"]): vol.Coerce(float),
            vol.Required("other_rate", default=DEFAULT_RATES["other"]): vol.Coerce(float),
            vol.Optional(CONF_USERNAME, default=""): str,
            vol.Optional(CONF_PASSWORD, default=""): str,
            vol.Optional(CONF_MPRN, default=""): str,
        }
    )


def _options_schema(entry: config_entries.ConfigEntry) -> vol.Schema:
    """Return the options schema, pre-filled with current values."""
    rates = {**DEFAULT_RATES, **_current(entry, CONF_RATES, {})}
    return vol.Schema(
        {
            vol.Required(
                CONF_IMPORT_PATH,
                default=_current(entry, CONF_IMPORT_PATH, DEFAULT_IMPORT_PATH),
            ): str,
            vol.Required(
                CONF_TIME_SHIFT_MINUTES,
                default=_current(
                    entry, CONF_TIME_SHIFT_MINUTES, DEFAULT_TIME_SHIFT_MINUTES
                ),
            ): int,
            vol.Required(
                CONF_CHEAP_START,
                default=_current(entry, CONF_CHEAP_START, DEFAULT_CHEAP_START),
            ): str,
            vol.Required(
                CONF_CHEAP_END,
                default=_current(entry, CONF_CHEAP_END, DEFAULT_CHEAP_END),
            ): str,
            vol.Required(
                CONF_NIGHT_START,
                default=_current(entry, CONF_NIGHT_START, DEFAULT_NIGHT_START),
            ): str,
            vol.Required(
                CONF_DAY_START,
                default=_current(entry, CONF_DAY_START, DEFAULT_DAY_START),
            ): str,
            vol.Required(
                CONF_PEAK_START,
                default=_current(entry, CONF_PEAK_START, DEFAULT_PEAK_START),
            ): str,
            vol.Required(
                CONF_PEAK_END,
                default=_current(entry, CONF_PEAK_END, DEFAULT_PEAK_END),
            ): str,
            vol.Required(
                CONF_CURRENCY,
                default=_current(entry, CONF_CURRENCY, DEFAULT_CURRENCY),
            ): str,
            vol.Required(
                CONF_STANDING_CHARGE,
                default=_current(entry, CONF_STANDING_CHARGE, DEFAULT_STANDING_CHARGE),
            ): vol.Coerce(float),
            vol.Required(
                CONF_EXPORT_RATE,
                default=_current(entry, CONF_EXPORT_RATE, DEFAULT_EXPORT_RATE),
            ): vol.Coerce(float),
            vol.Required(
                CONF_VAT_PERCENT,
                default=_current(entry, CONF_VAT_PERCENT, DEFAULT_VAT_PERCENT),
            ): vol.Coerce(float),
            vol.Required(
                CONF_DISCOUNT_PERCENT,
                default=_current(
                    entry, CONF_DISCOUNT_PERCENT, DEFAULT_DISCOUNT_PERCENT
                ),
            ): vol.Coerce(float),
            vol.Required("cheap_rate", default=rates["cheap"]): vol.Coerce(float),
            vol.Required("night_rate", default=rates["night"]): vol.Coerce(float),
            vol.Required("day_rate", default=rates["day"]): vol.Coerce(float),
            vol.Required("peak_rate", default=rates["peak"]): vol.Coerce(float),
            vol.Required("other_rate", default=rates["other"]): vol.Coerce(float),
            vol.Required(
                CONF_STALE_HOURS,
                default=_current(entry, CONF_STALE_HOURS, DEFAULT_STALE_HOURS),
            ): vol.All(vol.Coerce(int), vol.Range(min=1)),
        }
    )
