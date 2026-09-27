# pururu

A Home Assistant integration that creates devices, and their entities, from real entities and a few settings. Each device composes **features**; each feature creates entities inside the device.

## Install

With [HACS](https://hacs.xyz):

1. HACS → ⋮ → **Custom repositories**: add `https://github.com/thatsnotmynameio/pururu-ha` with type **Integration**.
2. Find **Pururu** in HACS, **Download** it (pick a release), and restart Home Assistant.

Or by hand: copy `custom_components/pururu/` into your configuration's `custom_components/` and restart.

Then add a `pururu:` block to `configuration.yaml` (below) and restart. **Developer tools → YAML → Pururu** reloads the block afterwards.

## Configure

```yaml
pururu:
  devices:
    laundry_washer:            # the device's key: entity IDs are <platform>.pururu_<key>_<metric>
      name: Máquina de lavar   # the device's name
      appliance:               # features: at least one
        power: sensor.washer_plug_power
        energy: sensor.washer_plug_energy
        running:
          threshold: 4
          on_delay: {minutes: 1}
          off_delay: {minutes: 2}
        statistics:
          runtime: [today, week, month, year]
          cycles: [today, week, month, year]
      phases:
        cycle_from: appliance
        sensor: sensor.washer_plug_power
        defaults:
          stopped: idle
          running: washing
        bands:
          heating: {above: 1000}
          spinning: {above: 50, below: 1000, for: {minutes: 3}}
```

The smallest device is a name and one feature:

```yaml
pururu:
  devices:
    dishwasher:
      name: Lava-louças
      appliance:
        power: sensor.dishwasher_plug_power
        running: {threshold: 3, on_delay: {minutes: 1}, off_delay: {minutes: 5}}
```

`pururu:` can also come from HA packages: HA merges `devices:` from several of them.

## Features

### `appliance`: an appliance on a power-measuring plug

| Key | | |
|---|---|---|
| `power` | required | The plug's power sensor. |
| `energy` | optional | The plug's lifetime energy counter, in any energy unit (none means kWh). |
| `running.threshold` | required | Above it (in `power`'s unit) the appliance works. |
| `running.on_delay` / `off_delay` | required | How long above / at or under the threshold before it starts / ends (ignores button presses, pauses, end tails). |
| `statistics.runtime` / `statistics.cycles` | optional | Periods among `today`, `week`, `month`, `year`. |

Entities: `sensor.pururu_<key>_power` and `_energy_total` (the plug's readings), `binary_sensor.pururu_<key>_running` (holds its state while the plug has no value), `sensor.pururu_<key>_last_cycle_start`, `_last_cycle_end` (written last: trigger on it), `_last_cycle_duration` (min), `_last_cycle_energy` (kWh), `_cycles_total`, `_runtime_total` (h), and `_runtime_<period>` / `_cycles_<period>` for each `statistics` entry. Without `energy` there is no `_energy_total` nor `_last_cycle_energy`.

- A cycle starts when `running` turns on, so `_last_cycle_start` is after `on_delay`; it ends when `running` turns off, so `_last_cycle_end` and the duration include `off_delay`.
- `_last_cycle_energy` is in kWh whatever the counter's unit (Wh, MWh, …); unknown when the counter had no value at the start or the end, or its unit is not an energy unit.
- `_runtime_total` is brought up to date every minute while running: a restart or a reload during a cycle can lose up to a minute of it, and the time HA is down is not counted.

### `phases`: the phase of a cycle from bands of a sensor's value

| Key | | |
|---|---|---|
| `cycle_from` | required | The feature of this device whose cycle it follows (`appliance`). |
| `sensor` | required | The sensor whose value picks the phase. |
| `defaults.stopped` / `defaults.running` | required | The phase outside a cycle / in a cycle when no band holds. |
| `bands` | required | Ordered `name: {above, below, for}`; at least one bound; `above` < `below`, both strict. A band holds once the value stays in it for `for` (a reading without a value restarts that count); the first one listed that holds wins. |

Entity: `sensor.pururu_<key>_phase`, with the attribute `seen` (the bands of the current or last cycle). Its states are the names in the configuration; the translations name `idle`, `washing`, `heating`, `spinning`, `rinsing`, `drying` and `cooling`, and any other name is shown as written.

## Entity IDs

Every entity ID is `<platform>.pururu_<key>_<metric>[_<period>]`. You may rename one in HA's UI: it stays in its device, and whatever follows it (the phase follows `running`, a meter its total) follows the new ID. An ID already taken by another integration is an error in the log: that entity is not created, nor anything that follows it.

## Develop

The code is in `custom_components/pururu/`, its tests in `tests/`. From this folder:

```sh
uv run pytest                                  # the tests and the checks: ruff, format, mypy, hassfest, quality scale
uv run ruff check --fix custom_components/pururu
uv run ruff format custom_components/pururu
uv run mypy custom_components/pururu
```

`ruff.toml` and `mypy.ini` hold core's settings at the pinned Home Assistant. hassfest comes from that release's source, downloaded once into `.hassfest/` (`uv run fetch_hassfest.py` does it by hand).

## Releases

Versions are semantic (`MAJOR.MINOR.PATCH`) and come from `version` in `custom_components/pururu/manifest.json`. A pull request that changes it is a release: once it is merged and the checks pass on `main`, the Release workflow tags `vX.Y.Z` and publishes a GitHub release, which HACS offers. A version that already has its tag is not published again, and a version below the latest release fails the checks (`python3 release.py check`).
