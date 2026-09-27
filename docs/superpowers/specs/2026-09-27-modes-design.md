# Modes — design

Version: 0.1.11 (reactions took 0.1.10). Branch: `worktree-feat+appliance-modes`, from `main`.

## Goal

An appliance's cycles can be of **several kinds**. A washer's cycle goes through phases in sequence (`phases`); a water purifier doesn't: it dispenses water, cools, or heats, one at a time, each at its own power. Each of those is a cycle of its own kind: a **mode**. Everything the appliance knows about its cycles (last start, end, duration, energy, counts, runtime, per-period statistics) is known per mode: the appliance goes from one kind of cycle to n.

```yaml
pururu:
  devices:
    water_filter:
      name: Purificador
      appliance:
        power: sensor.filter_plug_power
        energy: sensor.filter_plug_energy
        running: {threshold: 2.9, on_delay: {seconds: 1}, off_delay: {minutes: 1}}
      modes:
        cycle_from: appliance
        sensor: sensor.filter_plug_power
        energy: sensor.filter_plug_energy
        modes:
          bebendo: {name: Bebendo, above: 2.9, below: 4, on_delay: {seconds: 1}, off_delay: {minutes: 1}}
          gelar: {name: Gelar, above: 4, below: 150, on_delay: {seconds: 10}, off_delay: {minutes: 3}}
          quente: {name: Água quente, above: 150, below: 400, on_delay: {seconds: 30}, off_delay: {seconds: 30}}
        statistics:
          runtime: [today, month]
          cycles: [today, month]
          energy: [today, month]
# → sensor.pururu_water_filter_mode_current          bebendo | gelar | quente | idle
#   sensor.pururu_water_filter_mode_gelar_cycles_total "Purificador Ciclos de Gelar"
#   sensor.pururu_water_filter_mode_quente_energy_month
```

## Decisions

| Question | Decision |
|---|---|
| Phase or mode | A phase changes **within** a cycle, in sequence; a mode is **the whole cycle's** kind. A cycle never has two modes: leaving a mode ends its cycle, entering another starts a new one. |
| Where modes live | A feature of its own, `modes`, taking the cycle through `cycle_from: appliance`, as `phases`. Rejected: `modes:` inside `appliance` replacing `running:` (the user's choice: keep the appliance as it is); `appliance:` as a list (repeats `power` and `energy`, breaks every configuration, no namespace per item). |
| What the appliance's cycle does | It is the **gate**: a mode cycle exists only while the appliance's `running` is on, and ends when it turns off. An appliance cycle can hold several mode cycles (heating, then cooling, the power never dropping). |
| Cycles of any mode | The appliance's `cycles_total`. `modes` adds no sum of its modes: a second total, different from the appliance's whenever the mode changes without the power dropping, would confuse. |
| How a mode is detected | Its own band (`above`, `below`) and delays (`on_delay`, `off_delay`), as `running`'s threshold and delays: the user declares them. |
| A mode armed while another runs | It **waits**: it starts when the running one ends (its `off_delay`, or the gate closing), at that instant, if still armed. Always one mode at a time. Chosen after replaying 10 days of the real purifier's power: a chilling cycle's tail dips to ~3 W, a sip's band, for a few seconds; ending the running mode when another is armed split ~20 chills a day and invented ~7 sips a day. Rejected: the new one ending the previous one at once (the first choice, before the data); overlapping. |
| Overlapping bands | Refused by the schema: one mode at a time, so a reading is never in two bands. Rejected: first listed wins, as `phases`. |
| `on_delay` before the appliance runs | It counts: a mode whose band held for its `on_delay` before `running` turned on starts when `running` turns on. Rejected: counting only once `running` is on (the mode would start late in its own cycle). |
| Mode names | Open: any slug, distinct, not `idle` (the state with no mode). Each mode has a required, untranslated `name`, as `switches`, `lights` and `alerts`. |
| Naming the per-mode entities | A translation key per suffix (`mode_cycles_total`: "Cycles of `{mode}`"), the mode's `name` as its placeholder. |
| `current` and `last` states | The slug; known names are translated (the list `phases` has), others are shown as written. |

## Configuration

`modes:` is a feature (a key of `FEATURES`, namespace `mode`, `requires=("cycle",)`):

- `cycle_from`: required, a feature of this device providing `cycle` (today `appliance`).
- `sensor`: required, entity ID of a numeric sensor, usually the plug's power.
- `energy`: optional, entity ID of a lifetime energy counter; any energy unit, no unit read as kWh (as `appliance`'s).
- `modes`: required, an ordered map of **slug → mode**, at least one. Each mode:
  - `name`: required, not blank.
  - `above`, `below`: `finite_float`; at least one; `above < below`. Strict, as HA's `numeric_state`.
  - `on_delay`, `off_delay`: required, `cv.positive_time_period`.
- `statistics`: optional, `runtime`, `cycles`, `energy`, each a list of distinct periods (`today`, `week`, `month`, `year`).

Refused, with a message naming the problem:

- a mode keyed `idle`;
- two modes whose bands overlap (open intervals intersect: `max(above) < min(below)`, a missing bound being infinite);
- `statistics.energy` without `energy`.

The nested maps get their own `vol.Schema(...)` (the `ALLOW_EXTRA` gotcha).

## Behaviour

The detector is the `current` sensor, in the role `Running` has in the appliance. At every reading of `sensor`, the band that contains the value is at most one mode's (`inside`). With `A` the running mode, if any:

- **Pending start.** When `inside` is a mode `B` other than `A`, `B`'s `on_delay` is scheduled (if it isn't already); any other pending start is cancelled. When `inside` is `A` or none, the pending start is cancelled.
- **Armed.** When `B`'s `on_delay` passes, `B` is armed. It stays armed until a reading outside its band.
- **Start.** An armed mode starts when the appliance's cycle entity is `on` and no mode runs: at once if so, else when the cycle turns on, or when `A` ends (at that instant), whichever comes last.
- **Pending end.** A reading outside `A`'s band schedules `A`'s `off_delay` (if not already); a reading back inside cancels it. When it passes, `A` ends.
- **The gate closes.** The cycle entity turning `off` ends `A` at once and cancels its pending end. Armed modes stay armed, and `A` is armed again when the sensor's value is still in its band (a sensor other than the gate's plug): no new reading would arm it.
- **The cycle entity `unknown` or `unavailable`**, or not there yet: it isn't `on`, so no mode starts (an armed one waits), and it isn't a turn `off`, so the running mode isn't ended by it; its own `off_delay` still ends it.
- **A reading without a value** (`unknown`, `unavailable`, not a number): every pending start and end is cancelled; the running mode and armed modes stay. The next reading starts counting again, as `running` and `phases`.
- **Restart or reload.** `current` restores its state and, as `ExtraStoredData`, the running mode's start and energy at start. The cycle keeps its start and is counted once when it ends. Nothing is armed after a restore until a reading. Nothing ends when `current` is added, even with the cycle entity already `off`: the other entities of `modes` may not listen yet. The first reading out of the band ends the restored mode after its `off_delay`, or the cycle entity's next turn `off` does.
- **A cycle ends**: `Cycle(start, end=now, energy_kwh)`, energy computed as `appliance`'s (counter at end minus at start, kWh, never negative, `None` without a reading or an energy unit at either end). It is sent on the mode's cycle signal, then on its end signal.

`current` is the running mode, or `idle`. At a handover it goes from one mode straight to the next, written once: never `idle` in between, which an automation on `idle` would take for an end.

## Entities

`<key>` is the device's key, `<m>` a mode's slug. Entity keys are in the `mode` namespace.

Fixed:

| Entity key | Platform | What |
|---|---|---|
| `current` | sensor | The running mode or `idle`. Device class `enum`; options `idle` and every slug. |
| `last` | sensor | The mode of the last mode cycle that ended. `enum`, restored, `unknown` until the first. |

Per mode (`per_item`, suffix → platform):

| Suffix | What |
|---|---|
| `last_cycle_start`, `last_cycle_duration`, `last_cycle_end` | As `appliance`'s, for this mode's cycles. `last_cycle_end` is written last. |
| `last_cycle_energy` | kWh of this mode's last cycle. *With `energy`.* |
| `cycles_total` | This mode's finished cycles. `total_increasing`, restored. |
| `runtime_total` | Hours `current` has been this mode, brought up to date every minute. `total_increasing`, restored. |
| `energy_total` | kWh summed over this mode's cycles; a cycle with unknown energy adds nothing. `total_increasing`, restored. *With `energy`.* |
| `runtime_<period>`, `cycles_<period>`, `energy_<period>` | A `Meter` of the matching total, one per period listed in `statistics`. |

Entity IDs: `sensor.pururu_<key>_mode_<m>_<suffix>`. Every per-mode entity has `sources = ("current",)`: it isn't created when `current` isn't. `last` too.

A per-mode entity key can't equal a fixed one or another mode's: every suffix ends differently from `current` and `last`, and no suffix is another's with a word in front.

## Feature contract

Two new fields in `Feature`:

```python
# Entity keys repeated for every item of its block: suffix -> platform. The
# entity key is <item>_<suffix>, its translation key <namespace>_<suffix>, with
# the item's name as the placeholder named after the namespace ({mode})
per_item: Mapping[str, Platform] = field(default_factory=dict)
# The items of its validated block
items: Callable[[Any], Iterable[Item]] | None = None
```

- `Item` (`feature.py`): a frozen dataclass `slug`, `name`, with `key(suffix)` → `<slug>_<suffix>`.
- `_entity_keys` (`__init__.py`) yields `<item>_<suffix>` for every item and suffix, so `refers`, reactions' `when`, `_entity_ids_distinct`, `_referable` and stale removal see them with no other change.
- `PururuEntity._identify` takes an optional translation key and placeholders, for the per-mode entities.
- `tests/test_features.py` checks translations and icons of every suffix in `per_item`, that `items` is set exactly when `per_item` is, and that no suffix repeats the namespace.

## Shared cycle code

What `appliance` has about cycles moves to `features/cycle/`, used by both features. `appliance` behaves exactly as before: `tests/test_appliance.py` passes unchanged.

- `Cycle`, the signals, `LastCycleDescription`, `LAST_CYCLE`, `LastCycleValue`, `CyclesTotal`: the signals and the entity key are parameters, not `running`'s.
- `RuntimeTotal`: hours an entity is in a state (`on` for `running`, `<m>` for `current`).
- `EnergyTotal`: new, kWh summed over the cycles on a signal.
- `Meter`, `PERIODS`, `PERIOD_LIST`.
- The counter in kWh and the energy used (from `Running._energy_now` and `_energy_used`).

## Errors

- The appliance's `running` can't be created (ID taken): `modes` isn't created (`requires`).
- `current` can't be created: nothing of `modes` is (`sources`).
- Invalid configuration: refused by the schema, the whole `pururu:` block, as every feature.

## Translations and icons

`en.json` and `pt-BR.json`: `mode_current` ("Mode" / "Modo") and `mode_last` ("Last mode" / "Último modo"), with the state names `phase_current` has plus `dispensing`; one entry per suffix with `{mode}` ("Cycles of `{mode}`" / "Ciclos de `{mode}`", "`{mode}` energy this month" / "Energia de `{mode}` este mês"...). An icon per fixed key and per suffix.

## Tests

`tests/test_modes.py`, in the style of `test_phases.py` and `test_appliance.py`:

- A mode cycle starts after `on_delay` with the gate open and ends after `off_delay`; `current`, `last`, the `last_cycle_*` and totals follow.
- A mode armed while another runs waits, and starts at the instant the other ends; a dip into another band shorter than the running mode's `off_delay` doesn't split its cycle.
- A reading back in the band during `off_delay` cancels the end.
- `on_delay` passed before the gate opens: the mode starts when it opens. The gate closing ends the mode at once.
- The cycle entity `unknown`: nothing starts or ends.
- A reading without a value cancels pending starts and ends and keeps the mode.
- Restart and reload in the middle of a mode cycle: start kept, counted once.
- Energy: per cycle, `energy_total`, a cycle with no reading adds nothing; units other than kWh.
- Runtime per mode; the meters.
- The schema's refusals: `idle`, overlapping bands, `above >= below`, no bound, no `name`, `statistics.energy` without `energy`.
- Entity IDs and names (placeholder), a per-mode entity referred to by another feature (an alert), collision between two devices.

The contract test covers `MODES` with no change beyond the new fields.

## Docs

- `docs/features/modes.mdx`, and `modes` after `phases` in `docs.json`'s sidebar.
- `phases.mdx`: a short "phase or mode?" paragraph linking to `modes`.
- `concepts/devices-and-features.mdx`, `reference/configuration.mdx`: `modes`.
- `develop/writing-a-feature.mdx`: `per_item` and `items`.

## Release

`manifest.json` `0.1.11`. No new platform: no Sonar suppression.
