# ESB Smart Meter for Home Assistant

A Home Assistant custom integration that reads ESB Networks smart meter CSV exports and creates sensors for recent energy usage, cost estimates, current rate bucket, and import health.

## Install

Copy `custom_components/esb_smart_meter` into your Home Assistant `custom_components` directory, then restart Home Assistant.

## Configure

You can configure the integration from the Home Assistant UI, or import a YAML configuration like the sanitized example in `examples/configuration.example.yaml`:

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

Put ESB interval CSV exports in the configured `import_path`, then call the `esb_smart_meter.reload` service to rescan the folder.

## Privacy

Do not commit your real Home Assistant `configuration.yaml`, `secrets.yaml`, `.storage` directory, database files, logs, or ESB CSV exports. They can contain account details, meter identifiers, local network addresses, device names, or usage patterns.
