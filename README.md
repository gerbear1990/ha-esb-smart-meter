# ESB Smart Meter for Home Assistant

A Home Assistant custom integration for ESB Networks smart meter CSV exports. It
reads interval CSV files from a local folder and turns them into sensors for
energy usage, itemised cost, tariff bands, and import health — and backfills
your history onto the Energy dashboard.

This integration does not create or manage your ESB Networks account. It is for
people who can already access their ESB Networks smart meter data and want to
turn those CSV exports into Home Assistant sensors.

## Contents

- [Prerequisites](#prerequisites)
- [Features](#features)
- [Installation](#hacs-installation)
- [How readings are interpreted](#how-readings-are-interpreted) — **read this if your numbers look doubled**
- [Tariff bands](#tariff-bands)
- [How the cost is built](#how-the-cost-is-built)
- [Sensors](#sensors)
- [Services](#services)
- [Energy dashboard history](#energy-dashboard-history)
- [Solar export / microgeneration](#solar-export--microgeneration)
- [Automatic download](#automatic-download-optional)
- [Housekeeping](#housekeeping-prune)
- [YAML configuration](#yaml-configuration)

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

- Imports ESB interval CSV files from a configured Home Assistant folder,
  deduplicating readings by timestamp when multiple files overlap.
- Tracks total imported kWh, today's, yesterday's and this month's usage, the
  most recent complete day, and a 7-day rolling average.
- **Fully configurable tariff bands** — the cheap/boost, night, day, and peak
  window times are set to match *your* supplier plan.
- **Itemised cost** — energy, standing charge, discount, and VAT are each
  reported as their own line, so any total can be checked against a real bill.
- **Configurable VAT and supplier discount**, applied in the order a supplier
  applies them.
- **Energy dashboard backfill** — your CSV history is imported into long-term
  statistics automatically, and stays continuous across pruning.
- **Solar export / microgeneration support**, including feed-in earnings.
- **Optional ESB Networks portal download** — enter your account details and
  Home Assistant can fetch the CSV for you.
- Options flow: change paths, tariff bands, rates, VAT, and discount at any time
  without removing the integration.
- Diagnostics download, and repair issues when no data is found or when the
  newest reading is older than a configurable threshold (default 72 hours).

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

## Manual Installation

Use these steps if you do not use HACS.

1. Download or clone this repository.
2. Copy `custom_components/esb_smart_meter` into your Home Assistant
   `custom_components` directory.
3. Restart Home Assistant.
4. Follow the **Setup** steps below.

The final folder should look like this:

```text
config/
  custom_components/
    esb_smart_meter/
      __init__.py
      config_flow.py
      const.py
      coordinator.py
      diagnostics.py
      downloader.py
      manifest.json
      sensor.py
      services.yaml
      statistics.py
      strings.json
      translations/
        en.json
```

## Setup

[![Open your Home Assistant instance and start configuring this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=esb_smart_meter)

1. Click the button above, or go to **Settings → Devices & services → Add
   integration**.
2. Search for `ESB Smart Meter`.
3. Set the **CSV import path**, for example `/config/esb_energy`.
4. Leave **time shift** at `-30` unless you know you need something else — see
   [How readings are interpreted](#how-readings-are-interpreted).
5. Set your **tariff band times** and **unit rates** to match your plan.
6. Set the **daily standing charge**, **VAT %** (9 in Ireland) and **supplier
   discount %** (0 if you have none). Enter rates and the standing charge
   **ex-VAT**.
7. Optionally set the **export / feed-in rate** if you have microgeneration, and
   your **ESB portal credentials** if you want automatic downloads.
8. Submit, then check the **Records** sensor is greater than zero.

Every one of these is changeable later via the integration's **Configure**
button — you never need to remove and re-add it.

You can rescan the CSV folder at any time with `esb_smart_meter.reload`.

## How readings are interpreted

Two transformations are applied to every row. Both matter, and both explain
differences you might notice against the raw CSV.

### `Read Value` is power, not energy

In an ESB HDF export the value column is headed **`Active Import Interval
(kW)`** — it is the *mean power* sustained across the half-hour interval, not
the energy used in it. Energy is therefore `value × 0.5 h`.

The integration applies that factor. **A row reading `2.000` contributes
`1.0 kWh`, not `2.0 kWh`.** Without this every figure would be exactly double.

If a future export publishes a column whose header already contains `kWh`, the
value is taken at face value and the scaling is skipped.

### Timestamps mark the *end* of each interval

ESB stamps each row with the time the interval **finished**, so a row at `00:30`
covers `00:00`–`00:30`. The default **time shift of `-30` minutes** moves each
reading back to the start of its interval, so it lands in the hour it actually
belongs to.

Leave this at `-30` unless you have a reason not to. Setting it to `0` pushes
every reading into the following hour and skews the tariff banding at band
boundaries.

## Tariff bands

Electricity plans differ by supplier, so the band **times** and **rates** are
yours to set. The ESB HDF export contains only your half-hourly usage, **not**
any pricing or plan information, so bands cannot be detected from the data.

The defaults follow the common Irish smart tariff and are contiguous, so every
half-hour falls into exactly one band and `cheap + night + day + peak` always
sums to the total:

| Band    | Default window            | Notes                                 |
| ------- | ------------------------- | ------------------------------------- |
| `cheap` | 02:00–04:00               | Boost/EV window; checked first        |
| `peak`  | 17:00–19:00               |                                       |
| `night` | 23:00–08:00 (wraps)       | Night start through to day start      |
| `day`   | 08:00–17:00 & 19:00–23:00 | Everything else                       |
| `other` | —                         | Fallback rate only; never assigned    |

Adjust `cheap_start`/`cheap_end`, `night_start`, `day_start`, `peak_start`, and
`peak_end` to match your plan.

`other` is retained for backwards compatibility and is used as the fallback if a
band has no rate configured. With the contiguous defaults above, nothing is ever
bucketed into it.

## How the cost is built

The unit rates and standing charge you enter are treated as **net (ex-VAT)**
amounts. The bill is then assembled the way a supplier assembles one:

```text
  energy    = kWh × rate (per tariff band)
  standing  = daily standing charge × days
  subtotal  = energy + standing
  discount  = subtotal × discount %      ← comes off before VAT
  net       = subtotal − discount
  VAT       = net × VAT %
  total     = net + VAT
```

The discount is applied **before** VAT because VAT is charged on the amount
actually payable, not on the pre-discount figure.

| Setting            | Default | Notes                                   |
| ------------------ | ------- | --------------------------------------- |
| `vat_percent`      | `9`     | Irish domestic electricity rate         |
| `discount_percent` | `0`     | Whatever your plan gives you, e.g. `16` |

Enter both as percentages (`9`, `16`), not decimals.

Three deliberate choices worth knowing:

- **VAT applies to the standing charge**, not just to units — that is how it is
  charged in Ireland.
- **The discount is taken off the whole subtotal**, units *and* standing charge.
  Some plans discount unit rates only; if yours does, the reported figure will be
  slightly low. The discount is exposed as its own sensor and attribute so you
  can check it against a bill.
- **Export earnings carry neither.** Feed-in payments to a domestic
  microgenerator are income rather than a charge, so VAT and the discount do not
  touch them.

Per-bucket costs (`cheap_cost`, `day_cost`, …) stay **net and pre-discount**, so
they sum to `energy_cost`. VAT on a standing charge cannot be attributed to a
usage band, so folding it into the buckets would stop them summing to anything
meaningful — the same reason a bill lists net lines first and VAT once at the
bottom.

### Projected month cost

The month-end projection is **not** a simple scale-up of the month so far. Its
two halves behave differently:

- The **standing charge is deterministic** — it accrues once per day for every
  day of the month whatever the meter does — so it is `rate × days in month`,
  never extrapolated.
- **Energy is extrapolated** from *complete* days only, on both sides of the
  division. Today is still in progress, so including its part-day usage would
  scale a fraction of a day as though it were a whole one.

Discount and VAT are then applied to the projected net. If no complete day of
data exists yet, no projection is offered rather than reporting a standing
charge alone as though it were an estimate.

Every line is exposed as an attribute on the **Projected month cost** sensor.

## Sensors

All sensors belong to one **ESB Smart Meter** device. Entity IDs follow the
device and sensor name, e.g. `sensor.esb_smart_meter_today_cost`.

### Import health

| Sensor                   | Notes                                          |
| ------------------------ | ---------------------------------------------- |
| Last import              | When the folder was last scanned               |
| Last reading             | Timestamp of the newest reading                |
| Last reading age         | Hours since that reading — watch this for a stalled download |
| Records                  | Readings currently loaded                      |
| Coverage days            | Span from first to last reading                |
| Latest interval energy   | Energy in the most recent half-hour            |

### Usage and rate

| Sensor                                    | Notes                          |
| ----------------------------------------- | ------------------------------ |
| Total import                              | Lifetime kWh; never decreases  |
| Current rate bucket                       | Which band applies right now   |
| Current rate                              | That band's configured net rate |
| Today energy                              | Plus cheap / night / day / peak variants |
| Yesterday energy, Month energy            |                                |

### Cost

| Sensor                                   | Notes                           |
| ---------------------------------------- | ------------------------------- |
| Today cost, Yesterday cost, Month cost   | Totals payable, incl. VAT       |
| Today VAT, Month VAT                     | VAT component                   |
| Today discount, Month discount           | Discount applied                |
| Month net cost                           | After discount, before VAT      |
| Month cheap / night / day / peak cost    | Net, pre-discount               |
| Month complete days                      | Full days of data this month    |
| Projected month cost                     | See above; fully itemised in attributes |
| Projected month energy cost              | The extrapolated half alone     |

### Recent history

| Sensor                              | Notes                                   |
| ----------------------------------- | --------------------------------------- |
| Most recent complete date           | Newest day with all 48 intervals        |
| Most recent complete day energy/cost | Plus cheap / night / day / peak breakdowns |
| Cost / Energy, last 7 complete days |                                         |
| Average daily cost / energy (7 day) |                                         |

### Attributes

Several sensors carry a breakdown rather than just a number:

| Sensor                                  | Attributes                                     |
| --------------------------------------- | ---------------------------------------------- |
| Today / Yesterday / Month energy         | Per-band kWh                                   |
| Today / Yesterday cost                   | Full bill itemisation                          |
| Month cost                               | Per-band costs, bill itemisation, complete days |
| Projected month cost                     | Every projected line, plus VAT and discount %   |
| Most recent complete date                | That day's full breakdown                      |
| Cost / Energy, last 7 complete days      | Per-day list                                   |
| Records                                  | Import path, files found, and any message       |

Sensor availability depends on whether valid CSV rows have been imported. The
diagnostic sensors stay available even when no data has been found, so you can
see *why*.

## Services

| Service                             | What it does                                             |
| ----------------------------------- | -------------------------------------------------------- |
| `esb_smart_meter.reload`            | Re-scan the CSV folder and refresh all sensors.           |
| `esb_smart_meter.download_latest`   | Log in to ESB Networks and download the latest CSV.       |
| `esb_smart_meter.import_statistics` | Force a statistics import. Runs automatically anyway; takes an optional `rebuild` flag. |
| `esb_smart_meter.prune`             | Consolidate/trim the CSV folder, keeping `keep_days` (default 90). |

## Energy dashboard history

The regular sensors only accrue from the moment you install the integration, so
your CSV history is pushed into Home Assistant long-term statistics separately,
as external statistics:

| Statistic ID                      | Contents              |
| --------------------------------- | --------------------- |
| `esb_smart_meter:import_energy`   | Imported energy (kWh) |
| `esb_smart_meter:import_cost`     | Imported cost, incl. discount and VAT |
| `esb_smart_meter:export_energy`   | Exported energy (kWh) |
| `esb_smart_meter:export_earnings` | Feed-in earnings      |

**This happens automatically** after every refresh, so history appears on the
Energy dashboard as soon as new CSVs land — no service call needed. Each run
resumes from the newest point already recorded and writes only the new hours, so
it stays cheap at the 30-minute polling interval.

Because the running totals continue from what the recorder holds rather than
being recomputed from the files on disk, `esb_smart_meter.prune` is safe: the
Energy dashboard keeps a continuous series even after old CSVs are trimmed away.

The cost statistic covers **energy only**. The standing charge is a per-day
charge with no per-interval meaning, so spreading it across readings would
attribute fixed cost to usage.

`esb_smart_meter.import_statistics` is still available to trigger an import by
hand. It takes an optional **`rebuild`** flag that rewrites the whole series from
a zero total — a repair tool for a corrupted series only. If old readings have
already been pruned, a rebuild will *not* line up with the older points the
recorder still holds, so leave it off unless you mean it.

> **Upgrading from v0.5.0 or earlier:** cost statistics now include VAT and your
> discount, so newly written hours are on a different basis to hours already
> recorded. Run `import_statistics` once with `rebuild: true` after upgrading to
> put the whole series on a consistent footing.

## Solar export / microgeneration

If your meter exports to the grid, the ESB HDF export contains
`Active Export Interval (kW)` rows alongside the import rows. The integration
splits them automatically and adds export sensors: **Total export**, **Today /
Yesterday / Month export**, and — if you set an **export / feed-in rate** —
**Today / Month export credit**.

Export sensors only appear once export rows are present **or** you configure an
export rate, so import-only accounts stay uncluttered. Set `export_rate` in YAML
or via the options flow to activate them.

Feed-in is paid at a single flat rate rather than a time-of-use band, and carries
neither VAT nor your supplier discount.

## Automatic download (optional)

If you provide your ESB portal email, password, and MPRN during setup, the
`esb_smart_meter.download_latest` service will log in to
[myaccount.esbnetworks.ie](https://myaccount.esbnetworks.ie) and save the latest
interval CSV into your import folder, then refresh the sensors.

> **ESB rate-limits logins heavily** (roughly one or two attempts per day).
> The download is therefore never run automatically on the polling interval —
> trigger it yourself, for example with a once-daily automation:

```yaml
automation:
  - alias: Daily ESB download
    triggers:
      - trigger: time
        at: "06:30:00"
    actions:
      - action: esb_smart_meter.download_latest
```

ESB also applies human verification, so this can fail even with correct
credentials. Watch the **Last reading age** sensor to catch a download that has
quietly stopped working.

## Housekeeping (prune)

Reading history is cheap — thousands of half-hourly rows parse in milliseconds —
so trimming is optional. If you want to tidy the import folder, call
`esb_smart_meter.prune` with a `keep_days` value (default 90). It consolidates
everything into a single `esb_smart_meter_history.csv`, keeping only the most
recent days, and **moves the original files into a `pruned_backup` subfolder**
(nothing is hard-deleted).

Neither the lifetime **Total import** sensor nor your Energy dashboard history is
affected: the sensor holds a high-water mark, and statistics continue from what
the recorder already holds.

## CSV format

The integration expects ESB interval CSV exports with a timestamp column and a
value column. Column names are matched case- and spacing-insensitively.

**Timestamp column**, one of: `Read Date and End Time`, `Read Date And End Time`,
`read_date_and_end_time`, `datetime`, `timestamp` — or any column whose name
contains *read*, *date* and *time*.

**Value column**, one of: `Read Value`, `Read Value (kWh)`, `read_value`, `kWh`,
`kwh`. A header containing `kWh` is treated as energy; anything else is treated
as mean power in kW and halved — see
[How readings are interpreted](#how-readings-are-interpreted).

**Read Type column** (optional): `Read Type` in any casing or spacing. Rows whose
type contains *export* are treated as microgeneration rather than consumption; a
file with no such column is read entirely as consumption.

Timestamps are parsed as `DD-MM-YYYY HH:MM`, `YYYY-MM-DD HH:MM[:SS]`,
`DD/MM/YYYY HH:MM[:SS]`, or ISO format.

A file that cannot be parsed is skipped rather than failing the whole import. If
its timestamp or value column cannot be identified, a warning naming the file and
listing the headers it *does* have is written to the Home Assistant log — check
there first if **Records** stays at zero.

## YAML configuration

The UI setup is recommended, but YAML import is also supported. A sanitized
example is available in `examples/configuration.example.yaml`:

```yaml
esb_smart_meter:
  name: ESB Smart Meter
  import_path: /config/esb_energy
  time_shift_minutes: -30
  currency: EUR
  standing_charge: 0.0        # daily fixed charge, ex-VAT
  vat_percent: 9.0            # Irish domestic electricity VAT
  discount_percent: 0.0       # supplier discount, e.g. 16 for 16% off
  export_rate: 0.0            # feed-in rate per kWh, if you export
  cheap_start: "02:00"
  cheap_end: "04:00"
  night_start: "23:00"
  day_start: "08:00"
  peak_start: "17:00"
  peak_end: "19:00"
  rates:                      # per kWh, ex-VAT — examples only, use your own
    cheap: 0.08
    night: 0.1848
    day: 0.3451
    peak: 0.3617
    other: 0.3451
```

The UI flow additionally accepts optional ESB portal `username`, `password`, and
`mprn` for the download feature.

If you use YAML, restart Home Assistant after editing `configuration.yaml`.

## Privacy

Do not commit your real Home Assistant `configuration.yaml`, `secrets.yaml`,
`.storage` directory, database files, logs, or ESB CSV exports. They can contain
account details, meter identifiers, local network addresses, device names, or
usage patterns.

This repository intentionally contains only sanitized source code and example
configuration. It does not include personal meter data, MPRNs, ESB account
credentials, Home Assistant storage, logs, or local network configuration.

The integration's diagnostics download redacts your username, password, and
MPRN.

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

## License

Released under the [MIT License](LICENSE).
