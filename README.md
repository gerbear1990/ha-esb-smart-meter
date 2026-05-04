# ESB Smart Meter for Home Assistant

A Home Assistant custom integration for ESB Networks smart meter CSV exports.
It reads interval CSV files from a local folder and creates sensors for energy
usage, estimated cost, rate buckets, import health, and recent totals.

This integration does not create or manage your ESB Networks account. It is for
people who can already access their ESB Networks smart meter data and want to
turn those CSV exports into Home Assistant sensors.

## Prerequisites

Before installing this integration, set up access to your ESB smart meter data:

1. Create an ESB Networks account at
   [myaccount.esbnetworks.ie](https://myaccount.esbnetworks.ie).
2. Link your electricity meter MPRN in your ESB Networks account.
3. Download one or more smart meter interval CSV exports from ESB Networks.
4. Create a folder in Home Assistant for those CSV files, for example
   `/config/esb_energy`.
5. Copy your ESB CSV exports into that folder.

The ESB account and linked MPRN steps are essential. Without them, you will not
have the interval CSV files this integration reads.

## Features

- Imports ESB interval CSV files from a configured Home Assistant folder.
- Tracks total imported kWh, today's usage, yesterday's usage, monthly usage,
  and the latest interval reading.
- Estimates energy cost using configurable `cheap`, `night`, `day`, `peak`,
  and `other` rates.
- Exposes the current rate bucket and current rate as sensors.
- Adds a `esb_smart_meter.reload` service to rescan CSV files on demand.
- Deduplicates readings by timestamp when multiple CSV files overlap.

## HACS Installation

Use these steps if you already have HACS installed in Home Assistant.

[![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=gerbear1990&repository=ha-esb-smart-meter&category=integration)

1. Click the button above.
2. Choose your Home Assistant instance if prompted.
3. Confirm the repository details:
   - Repository: `gerbear1990/ha-esb-smart-meter`
   - Category: `Integration`
4. Add the repository to HACS.
5. In HACS, download `ESB Smart Meter`.
6. Restart Home Assistant.

This repository does not need to be listed in the default HACS catalog. The
button adds it as a HACS custom repository.

## Home Assistant Integration Setup

After installing the files with HACS or manually, add and configure the
integration in Home Assistant.

[![Open your Home Assistant instance and start configuring this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=esb_smart_meter)

1. Click the button above, or go to **Settings > Devices & services > Add
   integration**.
2. Search for `ESB Smart Meter`.
3. Set the CSV import path, for example `/config/esb_energy`.
4. Set the time shift if your ESB readings need adjusting. The default is
   `-30` minutes.
5. Set your cheap-rate window and unit rates.
6. Submit the form.
7. Check that sensors are created and that the record count is greater than
   zero after valid CSV files are found.

You can rescan the CSV folder at any time by calling the
`esb_smart_meter.reload` service.

## Manual Installation

Use these steps if you do not use HACS.

1. Download or clone this repository.
2. Copy `custom_components/esb_smart_meter` into your Home Assistant
   `custom_components` directory.
3. Restart Home Assistant.
4. Follow the **Home Assistant Integration Setup** steps above.

The final folder should look like this:

```text
config/
  custom_components/
    esb_smart_meter/
      __init__.py
      config_flow.py
      const.py
      coordinator.py
      manifest.json
      sensor.py
      services.yaml
```

## YAML Configuration

The UI setup is recommended, but YAML import is also supported. A sanitized
example is available in `examples/configuration.example.yaml`:

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

If you use YAML, restart Home Assistant after editing `configuration.yaml`.

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
  by `badger707`, which documented the ESB Networks account and MPRN
  requirements and implemented an ESB Networks smart meter data download flow.
- [raydex79/ESB-Networks-Energy-Data-Automation-Grafana-CSV](https://github.com/raydex79/ESB-Networks-Energy-Data-Automation-Grafana-CSV)
  by `raydex79`, which adapted ESB smart meter data processing for Grafana CSV
  workflows.

Thanks to both creators for publishing their work.

## Disclaimer

This project is unofficial and is not affiliated with, endorsed by, or supported
by ESB Networks or Home Assistant.
