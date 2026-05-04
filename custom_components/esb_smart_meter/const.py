"""Constants for the ESB Smart Meter integration."""

from datetime import timedelta

DOMAIN = "esb_smart_meter"
PLATFORMS = ["sensor"]

CONF_IMPORT_PATH = "import_path"
CONF_TIME_SHIFT_MINUTES = "time_shift_minutes"
CONF_CHEAP_START = "cheap_start"
CONF_CHEAP_END = "cheap_end"
CONF_RATES = "rates"

DEFAULT_IMPORT_PATH = "/config/esb_energy"
DEFAULT_TIME_SHIFT_MINUTES = -30
DEFAULT_CHEAP_START = "02:00"
DEFAULT_CHEAP_END = "04:00"
DEFAULT_SCAN_INTERVAL = timedelta(minutes=30)

DEFAULT_RATES = {
    "cheap": 0.08,
    "night": 0.1848,
    "day": 0.3451,
    "peak": 0.3617,
    "other": 0.3451,
}
