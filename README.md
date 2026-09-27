# pururu

A Home Assistant integration that turns the entities you already have into well-organised floors, areas and devices, from a few lines of YAML. A washing machine on a smart plug, for example, becomes a device that knows when it's running, which phase it's in, and how long and how much energy each wash took.

**📖 Documentation: [docs.page/thatsnotmynameio/pururu-ha](https://docs.page/thatsnotmynameio/pururu-ha)**

## Install

With [HACS](https://hacs.xyz): **⋮ → Custom repositories**, add `https://github.com/thatsnotmynameio/pururu-ha` as an **Integration**, download **Pururu**, and restart Home Assistant. Or copy `custom_components/pururu/` into your configuration's `custom_components/` and restart.

## Configure

Add a `pururu:` block to `configuration.yaml` and restart once. After that, reload it with **Developer tools → YAML → Pururu**.

```yaml
pururu:
  devices:
    dishwasher:
      name: Lava-louças
      appliance:
        power: sensor.dishwasher_plug_power
        running: {threshold: 3, on_delay: {minutes: 1}, off_delay: {minutes: 5}}
```

This creates the device **Lava-louças**, with `binary_sensor.pururu_dishwasher_running`, its last cycle's start, end and duration, and its total runtime and cycle count.

- [Your first device](https://docs.page/thatsnotmynameio/pururu-ha/getting-started/first-device): a step-by-step tutorial.
- [Configuration reference](https://docs.page/thatsnotmynameio/pururu-ha/reference/configuration): every key.
- [Troubleshooting](https://docs.page/thatsnotmynameio/pururu-ha/reference/troubleshooting): what each logged error means.

## Develop

```sh
uv run pytest    # the tests, plus ruff, ruff format, mypy, hassfest and the quality scale
```

The [Develop](https://docs.page/thatsnotmynameio/pururu-ha/develop) tab covers the architecture, writing a feature, testing and releases.
