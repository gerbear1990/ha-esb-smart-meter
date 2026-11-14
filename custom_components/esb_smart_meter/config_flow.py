"""Config and options flow for ESB Smart Meter."""

from __future__ import annotations

from datetime import datetime
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
    CONF_EXPORT_RATE,
    CONF_IMPORT_PATH,
    CONF_MPRN,
    CONF_NIGHT_START,
    CONF_PASSWORD,
    CONF_PEAK_END,
    CONF_PEAK_START,
    CONF_RATES,
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
    DEFAULT_NIGHT_START,
    DEFAULT_PEAK_END,
    DEFAULT_PEAK_START,
    DEFAULT_RATES,
    DEFAULT_STALE_HOURS,
    DEFAULT_STANDING_CHARGE,
    DEFAULT_TIME_SHIFT_MINUTES,
    DEFAULT_VAT_PERCENT,
    DOMAIN,
)

_TIME_FIELDS = (
    CONF_CHEAP_START,
    CONF_CHEAP_END,
    CONF_NIGHT_START,
    CONF_DAY_START,
    CONF_PEAK_START,
    CONF_PEAK_END,
)
_NON_NEGATIVE_FLOAT = vol.All(vol.Coerce(float), vol.Range(min=0))
_PERCENT_FLOAT = vol.All(vol.Coerce(float), vol.Range(min=0, max=100))


def _rates_from_input(data: dict[str, Any]) -> dict[str, float]:
    """Pull the flat rate_* fields into a nested rates dict."""
    return {
        bucket: data.pop(f"{bucket}_rate")
        for bucket in ("cheap", "night", "day", "peak", "other")
    }


def _validate_times(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate that all time-band fields use 24-hour HH:MM format."""
    errors: dict[str, str] = {}
    for field in _TIME_FIELDS:
        raw = str(user_input.get(field, "")).strip()
        try:
            datetime.strptime(raw, "%H:%M")
        except ValueError:
            errors[field] = "invalid_time"
    return errors


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
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_times(user_input)
            if not errors:
                data = dict(user_input)
                data[CONF_RATES] = _rates_from_input(data)
                await self.async_set_unique_id("default")
                self._abort_if_unique_id_configured(updates=data)
                return self.async_create_entry(title=data[CONF_NAME], data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input),
            errors=errors,
        )

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
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_times(user_input)
            if not errors:
                options = dict(user_input)
                options[CONF_RATES] = _rates_from_input(options)
                return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(self.config_entry, user_input),
            errors=errors,
        )


def _current(entry: config_entries.ConfigEntry, key: str, default: Any) -> Any:
    """Return the current effective value (options over data)."""
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


def _shared_schema(
    defaults: dict[str, Any],
    *,
    include_name: bool = False,
    include_stale: bool = False,
) -> vol.Schema:
    """Build the shared config/options schema."""
    fields: dict[vol.Marker, Any] = {}
    if include_name:
        fields[vol.Required(CONF_NAME, default=defaults[CONF_NAME])] = str

    fields.update(
        {
            vol.Required(CONF_IMPORT_PATH, default=defaults[CONF_IMPORT_PATH]): str,
            vol.Required(
                CONF_TIME_SHIFT_MINUTES, default=defaults[CONF_TIME_SHIFT_MINUTES]
            ): int,
            vol.Required(CONF_CHEAP_START, default=defaults[CONF_CHEAP_START]): str,
            vol.Required(CONF_CHEAP_END, default=defaults[CONF_CHEAP_END]): str,
            vol.Required(CONF_NIGHT_START, default=defaults[CONF_NIGHT_START]): str,
            vol.Required(CONF_DAY_START, default=defaults[CONF_DAY_START]): str,
            vol.Required(CONF_PEAK_START, default=defaults[CONF_PEAK_START]): str,
            vol.Required(CONF_PEAK_END, default=defaults[CONF_PEAK_END]): str,
            vol.Required(CONF_CURRENCY, default=defaults[CONF_CURRENCY]): str,
            vol.Required(
                CONF_STANDING_CHARGE, default=defaults[CONF_STANDING_CHARGE]
            ): _NON_NEGATIVE_FLOAT,
            vol.Required(
                CONF_EXPORT_RATE, default=defaults[CONF_EXPORT_RATE]
            ): _NON_NEGATIVE_FLOAT,
            vol.Required(
                CONF_VAT_PERCENT, default=defaults[CONF_VAT_PERCENT]
            ): _PERCENT_FLOAT,
            vol.Required(
                CONF_DISCOUNT_PERCENT, default=defaults[CONF_DISCOUNT_PERCENT]
            ): _PERCENT_FLOAT,
            vol.Required("cheap_rate", default=defaults["cheap_rate"]): _NON_NEGATIVE_FLOAT,
            vol.Required("night_rate", default=defaults["night_rate"]): _NON_NEGATIVE_FLOAT,
            vol.Required("day_rate", default=defaults["day_rate"]): _NON_NEGATIVE_FLOAT,
            vol.Required("peak_rate", default=defaults["peak_rate"]): _NON_NEGATIVE_FLOAT,
            vol.Required("other_rate", default=defaults["other_rate"]): _NON_NEGATIVE_FLOAT,
        }
    )

    if include_stale:
        fields[vol.Required(CONF_STALE_HOURS, default=defaults[CONF_STALE_HOURS])] = (
            vol.All(vol.Coerce(int), vol.Range(min=1))
        )

    fields.update(
        {
            vol.Optional(CONF_USERNAME, default=defaults[CONF_USERNAME]): str,
            vol.Optional(CONF_PASSWORD, default=defaults[CONF_PASSWORD]): str,
            vol.Optional(CONF_MPRN, default=defaults[CONF_MPRN]): str,
        }
    )
    return vol.Schema(fields)


def _user_schema(user_input: dict[str, Any] | None = None) -> vol.Schema:
    """Return the initial UI config schema."""
    defaults: dict[str, Any] = {
        CONF_NAME: "ESB Smart Meter",
        CONF_IMPORT_PATH: DEFAULT_IMPORT_PATH,
        CONF_TIME_SHIFT_MINUTES: DEFAULT_TIME_SHIFT_MINUTES,
        CONF_CHEAP_START: DEFAULT_CHEAP_START,
        CONF_CHEAP_END: DEFAULT_CHEAP_END,
        CONF_NIGHT_START: DEFAULT_NIGHT_START,
        CONF_DAY_START: DEFAULT_DAY_START,
        CONF_PEAK_START: DEFAULT_PEAK_START,
        CONF_PEAK_END: DEFAULT_PEAK_END,
        CONF_CURRENCY: DEFAULT_CURRENCY,
        CONF_STANDING_CHARGE: DEFAULT_STANDING_CHARGE,
        CONF_EXPORT_RATE: DEFAULT_EXPORT_RATE,
        CONF_VAT_PERCENT: DEFAULT_VAT_PERCENT,
        CONF_DISCOUNT_PERCENT: DEFAULT_DISCOUNT_PERCENT,
        "cheap_rate": DEFAULT_RATES["cheap"],
        "night_rate": DEFAULT_RATES["night"],
        "day_rate": DEFAULT_RATES["day"],
        "peak_rate": DEFAULT_RATES["peak"],
        "other_rate": DEFAULT_RATES["other"],
        CONF_USERNAME: "",
        CONF_PASSWORD: "",
        CONF_MPRN: "",
    }
    if user_input:
        defaults.update(user_input)
    return _shared_schema(defaults, include_name=True)


def _options_schema(
    entry: config_entries.ConfigEntry, user_input: dict[str, Any] | None = None
) -> vol.Schema:
    """Return the options schema, pre-filled with current values."""
    rates = {**DEFAULT_RATES, **_current(entry, CONF_RATES, {})}
    defaults: dict[str, Any] = {
        CONF_IMPORT_PATH: _current(entry, CONF_IMPORT_PATH, DEFAULT_IMPORT_PATH),
        CONF_TIME_SHIFT_MINUTES: _current(
            entry, CONF_TIME_SHIFT_MINUTES, DEFAULT_TIME_SHIFT_MINUTES
        ),
        CONF_CHEAP_START: _current(entry, CONF_CHEAP_START, DEFAULT_CHEAP_START),
        CONF_CHEAP_END: _current(entry, CONF_CHEAP_END, DEFAULT_CHEAP_END),
        CONF_NIGHT_START: _current(entry, CONF_NIGHT_START, DEFAULT_NIGHT_START),
        CONF_DAY_START: _current(entry, CONF_DAY_START, DEFAULT_DAY_START),
        CONF_PEAK_START: _current(entry, CONF_PEAK_START, DEFAULT_PEAK_START),
        CONF_PEAK_END: _current(entry, CONF_PEAK_END, DEFAULT_PEAK_END),
        CONF_CURRENCY: _current(entry, CONF_CURRENCY, DEFAULT_CURRENCY),
        CONF_STANDING_CHARGE: _current(
            entry, CONF_STANDING_CHARGE, DEFAULT_STANDING_CHARGE
        ),
        CONF_EXPORT_RATE: _current(entry, CONF_EXPORT_RATE, DEFAULT_EXPORT_RATE),
        CONF_VAT_PERCENT: _current(entry, CONF_VAT_PERCENT, DEFAULT_VAT_PERCENT),
        CONF_DISCOUNT_PERCENT: _current(
            entry, CONF_DISCOUNT_PERCENT, DEFAULT_DISCOUNT_PERCENT
        ),
        "cheap_rate": rates["cheap"],
        "night_rate": rates["night"],
        "day_rate": rates["day"],
        "peak_rate": rates["peak"],
        "other_rate": rates["other"],
        CONF_STALE_HOURS: _current(entry, CONF_STALE_HOURS, DEFAULT_STALE_HOURS),
        CONF_USERNAME: _current(entry, CONF_USERNAME, ""),
        CONF_PASSWORD: _current(entry, CONF_PASSWORD, ""),
        CONF_MPRN: _current(entry, CONF_MPRN, ""),
    }
    if user_input:
        defaults.update(user_input)
    return _shared_schema(defaults, include_stale=True)
