"""ESB Smart Meter integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

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
    PLATFORMS,
)
from .coordinator import ESBSmartMeterCoordinator

LOGGER = logging.getLogger(__name__)

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
                vol.Optional(CONF_RATES, default=DEFAULT_RATES): RATE_SCHEMA,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


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
        """Refresh all ESB Smart Meter coordinators."""
        for coordinator in hass.data[DOMAIN].values():
            if isinstance(coordinator, ESBSmartMeterCoordinator):
                await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, "reload", handle_reload)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up an ESB Smart Meter config entry."""
    coordinator = ESBSmartMeterCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an ESB Smart Meter config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
