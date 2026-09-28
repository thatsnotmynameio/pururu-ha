# Programs' and reactions' statistics — design

Version: 0.1.18. Builds on reactions running programs (0.1.17) and on the cycle code `appliance` and `modes` share (`features/cycle/`).

## Goal

A program runs, and a reaction fires, and nothing counts it: HA's traces keep the last few runs, and `last_triggered` the last one. This gives every program and every reaction pururu's statistics, automatically, as `appliance` and `modes` have for their cycles: **each run of a program is a cycle**, with its last start, end and duration, all-time totals and optional per-period meters; a reaction counts its triggers.

```yaml
pururu:
  devices:
    pool:
      name: Piscina
      switches:
        pump: {entity: switch.pool_pump, name: Bomba}
      programs:
        clean:
          name: Limpar
          sequence: [{turn_on: switch_pump}, {delay: {hours: 2}}, {turn_off: switch_pump}]
          statistics:
            runtime: [today, month]
            cycles: [month]
      reactions:
        morning:
          name: Manhã
          at: "08:00"
          then: clean
          statistics:
            triggered: [month]
# → sensor.pururu_pool_program_clean_cycles_total        "Piscina Ciclos de Limpar"
#   sensor.pururu_pool_program_clean_runtime_today
#   sensor.pururu_pool_program_clean_last_cycle_duration
#   sensor.pururu_pool_reaction_morning_triggered_total   "Piscina Disparos de Manhã"
#   sensor.pururu_pool_reaction_morning_triggered_month
```

## Decisions

| Question | Decision |
|---|---|
| What a program's run is | A cycle, as a mode's: it starts when its script turns `on` and ends when it turns `off`. Every run counts, whoever started it (a reaction, the UI, a voice assistant), since what's measured is the script. The same suffixes as `modes`, so a program's statistics and a mode's read alike, the ground for issue #25 (one model for native and pururu programs). |
| What a reaction counts | Its triggers: HA's `automation_triggered` for its automation. Since 0.1.17 the "is the program running" check is inside the actions, so every trigger counts, including one whose program was already running; a reaction's triggers minus its program's runs is what was skipped. No duration: a reaction's run ends at once. |
| Automatic or asked for | The totals and the last cycle: always, as `appliance`'s. The per-period meters: listed under `statistics`, as `appliance` and `modes`. |
| Where they live | In the device, as sensors in the `program` and `reaction` namespaces: `sensor.pururu_<device>_program_<program>_<suffix>` and `sensor.pururu_<device>_reaction_<reaction>_<suffix>`. The script and the automation stay where they are (HA keeps them out of any device). |
| How the code gets them | `programs` and `reactions` stay device keys, not `Feature`s: they don't count as a device's feature. But their entities go through the same path as every pururu entity: `per_item` and `items` on a `Feature` value each module declares (`programs.STATISTICS`, `reactions.STATISTICS`), in a `DEVICE_KEYS` map next to `FEATURES`. `_entity_keys`, `_build`, `_creatable`, `_entity_ids_distinct`, `_referable`, stale removal and the contract test then see them with no second path. Rejected: building them apart in `__init__.py` (a second path around `_creatable`, renames and stale removal, which programs' first spec already refused). |
| What starts a program's cycle | A tracker in `programs.py`, not an entity: it listens to the script's state and sends `cycle_signal(device, item)` with the run's start (the `on` state's `last_changed`) and its end. Rejected: a pururu `binary_sensor` mirroring the script's state (a second entity saying what the script already says). |
| A reaction watching statistics | A reaction's `when` can name a program's statistic (`program_clean_last_cycle_end`): they are entity keys of the device. Not its own counters: `when: reaction_morning_triggered_total` in `morning` is refused, it would feed itself. |

## Entities

`<d>` is the device's key, `<p>` a program's, `<r>` a reaction's.

Per program (namespace `program`, `per_item`):

| Suffix | What |
|---|---|
| `last_cycle_start`, `last_cycle_duration`, `last_cycle_end` | As a mode's, for this program's runs. `last_cycle_end` is written last. Restored. |
| `cycles_total` | Finished runs, all time. `total_increasing`, restored. |
| `runtime_total` | Hours the script has been `on`, brought up to date every minute. `total_increasing`, restored. |
| `runtime_<period>`, `cycles_<period>` | A `Meter` of the matching total, one per period in `statistics`. |

Per reaction (namespace `reaction`, `per_item`):

| Suffix | What |
|---|---|
| `triggered_total` | Triggers, all time. `total_increasing`, restored. |
| `triggered_<period>` | A `Meter` of it, one per period in `statistics`. |

Names: the device's name, then the translation with the item's name as the placeholder named after the namespace (`{program}`, `{reaction}`), as `modes`' `{mode}`: "Ciclos de Limpar", "Disparos de Manhã".

## Configuration

`programs.<key>.statistics` and `reactions.<key>.statistics`, optional, with the periods of `appliance` (`today`, `week`, `month`, `year`, each once):

| Block | Keys |
|---|---|
| a program's `statistics` | `runtime`, `cycles` |
| a reaction's `statistics` | `triggered` |

## Behaviour

| When | What happens |
|---|---|
| The script turns `on`, then `off` | One cycle: `last_cycle_*` set, `cycles_total` + 1, the runtime counted |
| pururu reloaded while the program runs | The tracker starts again; at `off`, the cycle's start is the `on` state's `last_changed`: counted once, with its real start |
| HA restarted while the program runs | HA loses the running script (it's `off` after the restart, with no `on → off` seen): that run isn't counted. Its runtime until the restart is |
| The script renamed in the UI | Followed when pururu reloads: at once when a reaction starts it, else at the next reload |
| The program not generated (dropped or held) | Its statistics stay, with their values and history, and count nothing until it's generated again |
| The program removed from the YAML | Its statistics go, as any stale entity |
| The reaction fires | `triggered_total` + 1, whether its program started or not |
| The automation turned off in the UI | It doesn't fire, so nothing counts |

## Code

- `programs.py`: `statistics` in `PROGRAM`; `STATISTICS`, a `Feature` in namespace `program` with `per_item` (the cycle suffixes above) and `items` (one `Item` per program), whose `build()` makes the `features/cycle/` entities per program and the tracker.
- `reactions.py`: `statistics` in `REACTION`; `STATISTICS` in namespace `reaction`, whose `build()` makes a `TriggersTotal` per reaction: restored, counting `automation_triggered` for its automation's current entity ID.
- `features/cycle/`: `CyclesTotal`, `RuntimeTotal`, `LastCycleValue` and `Meter` reused unchanged; a `TriggersTotal` (a count on an event) next to `CyclesTotal` if it fits there.
- `__init__.py`: a `DEVICE_KEYS` map (`programs`, `reactions` → their `STATISTICS`) that `_entity_keys` and `_build` walk after `FEATURES`; it doesn't count as a feature in `_device`. `_reactions_on_this_device` refuses a reaction watching its own counters.
- Translations (`en.json`, `pt-BR.json`) and icons for every suffix.

## Testing

- `tests/test_programs.py`: a run is a cycle (`last_cycle_*`, `cycles_total`, `runtime_total`); started from a reaction and from `script.turn_on` alike; a reload mid-run counts it once with its real start; a restart mid-run; the meters; the program held, then back, its statistics kept; removed, its statistics gone.
- `tests/test_reactions.py`: `triggered_total` counts every trigger, including one skipped because its program runs; the meter; a reaction watching a program's `last_cycle_end`; a reaction watching its own counter refused.
- `tests/test_features.py`: the contract runs over `DEVICE_KEYS` too (translations, icons, suffixes that don't repeat the namespace).
- Entity IDs across devices: `_entity_ids_distinct` catches a program's statistic colliding with another device's entity.

## Docs

- `docs/concepts/programs.mdx` and `docs/concepts/reactions.mdx`: a Statistics section each, the entities table, `statistics` under Settings.
- `docs/reference/configuration.mdx`: both `statistics` blocks.
- `docs/develop/architecture.mdx` and `writing-a-feature.mdx`: `DEVICE_KEYS`.
- `CLAUDE.md`: programs and reactions create entities now (their statistics), through `DEVICE_KEYS`.

## Release

0.1.18 in `manifest.json`. Nothing breaks; every program and reaction gains sensors.

## Later

- Finished versus stopped runs (`script.turn_off`, a failed step, a restart).
- Execution modes (`parallel`, `queued`): a program running twice at once isn't one cycle; the tracker then counts runs, not `on` spans.
- Issue #25: one model for `modes` and programs.

## Risks

- **`programs` and `reactions` start creating entities**, which their specs avoided. `DEVICE_KEYS` keeps it on the one path every entity takes; the contract test must cover it.
- **Every program and reaction gains sensors (five per program, one per reaction)** without asking. They are cheap (restored counters), and the meters stay opt-in.
