# ESB Smart Meter for Home Assistant

A Home Assistant custom integration for ESB Networks smart meter CSV exports.
It reads interval CSV files from a local folder and creates sensors for energy
usage, estimated cost, rate buckets, import health, and recent totals.

This repository is intended for people who already download their ESB Networks
half-hourly usage data and want Home Assistant sensors from those CSV files.

## Features

- Imports ESB interval CSV files from a configured Home Assistant folder.
- Tracks total imported kWh, today's usage, yesterday's usage, monthly usage,
  and the latest interval reading.
- Estimates energy cost using configurable `cheap`, `night`, `day`, `peak`,
  and `other` rates.
- Exposes the current rate bucket and current rate as sensors.
- Adds a `esb_smart_meter.reload` service to rescan CSV files on demand.
- Deduplicates readings by timestamp when multiple CSV files overlap.

## Install

### HACS custom repository

[![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=gerbear1990&repository=ha-esb-smart-meter&category=integration)

1. Click the button above to add this repository to HACS as a custom
   integration repository.
2. Download the integration in HACS.
3. Restart Home Assistant.
4. Add the integration from Home Assistant:

[![Open your Home Assistant instance and start configuring this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=esb_smart_meter)

The first button requires HACS to already be installed. This repository does not
need to be listed in the default HACS catalog to be added as a custom
repository.

### Manual install

1. Copy `custom_components/esb_smart_meter` into your Home Assistant
   `custom_components` directory.
2. Restart Home Assistant.
3. Add the integration from the Home Assistant UI, or configure it with YAML.

## Configure

You can configure the integration from the Home Assistant UI, or import a YAML
configuration like the sanitized example in
`examples/configuration.example.yaml`:

```yaml
esb_smart_meter:
  name: ESB Smart Meter
  import_path: /config/esb_energy
  time_shift_minutes: -30
  cheap_start: "02:00"
  cheap_end: "04:00"
  rates:
    cheap: 0.08
    night: 0.18
    day: 0.34
    peak: 0.36
    other: 0.34
```

Create the configured folder, for example `/config/esb_energy`, and place your
ESB Networks interval CSV exports there. Home Assistant will scan the folder on
startup and periodically afterward. You can also call the
`esb_smart_meter.reload` service to rescan immediately.

## CSV Format

The integration expects ESB interval CSV exports with a timestamp column and a
kWh value column. It accepts common column names including:

- `Read Date and End Time`
- `Read Date And End Time`
- `read_date_and_end_time`
- `datetime`
- `timestamp`
- `Read Value`
- `Read Value (kWh)`
- `read_value`
- `kWh`
- `kwh`

Timestamp values are parsed using common ESB-style date formats such as
`DD-MM-YYYY HH:MM`, `YYYY-MM-DD HH:MM`, and ISO timestamps.

## Sensors

The integration creates sensors for:

- Last import time and last reading time.
- Imported record count and coverage days.
- Latest interval energy.
- Total imported energy.
- Today, yesterday, and month energy totals.
- Today, yesterday, and month estimated cost.
- Per-rate totals for current-day usage.
- Current rate bucket and current rate.

Sensor availability depends on whether valid CSV rows have been imported. Basic
diagnostic sensors remain available even when no CSV data has been found.

## Privacy

Do not commit your real Home Assistant `configuration.yaml`, `secrets.yaml`,
`.storage` directory, database files, logs, or ESB CSV exports. They can contain
account details, meter identifiers, local network addresses, device names, or
usage patterns.

This repository intentionally contains only sanitized source code and example
configuration. It does not include personal meter data, MPRNs, ESB account
credentials, Home Assistant storage, logs, or local network configuration.

## Acknowledgements

This project builds on work and ideas from two public ESB smart meter projects:

- [badger707/esb-smart-meter-reading-automation](https://github.com/badger707/esb-smart-meter-reading-automation)
  by `badger707`, which documented and implemented an ESB Networks smart meter
  data download flow.
- [raydex79/ESB-Networks-Energy-Data-Automation-Grafana-CSV](https://github.com/raydex79/ESB-Networks-Energy-Data-Automation-Grafana-CSV)
  by `raydex79`, which adapted ESB smart meter data processing for Grafana CSV
  workflows.

Thanks to both creators for publishing their work.

## Disclaimer

This project is unofficial and is not affiliated with, endorsed by, or supported
by ESB Networks or Home Assistant.
