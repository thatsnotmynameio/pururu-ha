# Ready-made alerts — design

Version: 0.1.13 (the one after 0.1.12, Alert2's alerts). Branch: `worktree-bridge-cse_01FrS5sRKjmtWV5pHdNBS5pB`, on `main` at #20. Builds on [alerts](2026-09-27-alerts-design.md), [alert notify](2026-09-27-alert-notify-design.md) and [Alert2 config](2026-09-27-alert2-config-design.md).

## Goal

A feature knows what usually goes wrong with it. An appliance's plug goes offline; its cycle runs for too long; it hasn't run in days; it just finished. Today the user writes each of those as an alert by hand (`when`, `is`, `for`, `notify`). Instead, a feature **offers ready-made alerts**: **off** by default, each **enabled with one key** in the feature's own block, with sensible defaults and a `notify` in the user's language out of the box, so Alert2 delivers it with nothing else written.

This spec builds the mechanism, generic in `Feature`, and the **appliance's** catalogue. Other features get theirs later, each in a small change.

```yaml
clothes_washer:
  name: Tanquinho
  appliance:
    power: sensor.washer_plug_power
    running: {threshold: 4, on_delay: {minutes: 1}, off_delay: {minutes: 2}}
    alerts:
      offline:                          # null: every default
      long_cycle: {for: {hours: 3}}     # for is required here
      no_cycle: {for: {days: 2}}
      finished: {lasts: {minutes: 30}, priority: medium}
      no_power:
        notify: {message: O congelador desligou!, done_message: Voltou.}
# → binary_sensor.pururu_clothes_washer_appliance_alert_offline   "Tanquinho Sem conexão"
# → one per other enabled alert, and each one's Alert2 alert in pururu/alert2/alerts.yaml
```

Hand-written alerts (the device's `alerts:` block) stay as they are: a ready-made alert is for the common case, a hand-written one for anything else (a threshold of the user's, another entity).

## The appliance's catalogue

| Alert | On when | Off when | Defaults | Time measured from |
|---|---|---|---|---|
| `offline` | `appliance_power` has no reading (`unavailable`, `unknown`, gone) | a reading returns | `for` 10 min, `medium` | the ordinary `for` |
| `no_power` | `appliance_power` is `0` | the power is above 0 | `for` 10 min, `medium` | the ordinary `for` |
| `long_cycle` | a cycle has been running for longer than `for` | the cycle ends | `for` **required**, `medium` | the running cycle's start |
| `no_cycle` | no cycle has run for longer than `for` since the last one ended | a cycle starts | `for` **required**, `medium` | the last cycle's end, or when the alert was first created if none ever ended |
| `finished` | a cycle ends (`appliance_running` on → off) | a new cycle starts, or `lasts` passes | `lasts` 1 h, `low` | the last cycle's end |

- **What can be set:** `offline`, `no_power`, `long_cycle`, `no_cycle` take `for`, `priority`, `notify`; `finished` takes `lasts`, `priority`, `notify` (no `for`). The name and the condition are fixed: a threshold of the user's is a hand-written alert.
- **`no_power`** is for an appliance that always draws something (a fridge, a freezer, a purifier): a washer between cycles reads 0 W, and the alert would be on almost always. The docs say so.
- **`notify`** replaces the default texts as a whole (`message` and `done_message`, both required, as in a hand-written alert).
- **Priorities** are `low`, `medium`, `high`, as in a hand-written alert.

Why the time is measured from a milestone for three of them: a hand-written alert's `for` starts over at every restart or reload. For 10 minutes that costs little; for `for: {days: 2}` any restart in between would keep `no_cycle` from ever turning on. The milestones survive restarts, so these alerts do too.

## Configuration

- The feature's block takes `alerts:`, a map of **ready-made alert → settings**. A null value (`offline:`) is `{}`. An empty `alerts:` is refused (as the device's `alerts:`), since it enables nothing.
- Refused, with the path in the message: an alert the feature doesn't offer (`appliance: alerts: nope: not a ready-made alert of appliance (offline, no_power, long_cycle, no_cycle, finished)`), a setting that doesn't apply (`lasts` on `offline`, `for` on `finished`), a missing required `for`, a `for`/`lasts` that isn't a positive time period, an unknown priority, an incomplete `notify`.
- A mapping of its own (`vol.Schema`), so the top-level `ALLOW_EXTRA` doesn't let unknown keys through.
- The feature's `example` is unchanged; the contract test enables every ready-made alert on top of it, with the required settings, and checks it is valid.

## Entities

- Each enabled alert is a problem binary sensor, entity key `alert_<name>` in the **feature's namespace**: `binary_sensor.pururu_<device>_appliance_alert_<name>`. It never meets a hand-written alert (`…_alert_<key>`, namespace `alert`), and the Alert2 name follows the same rule as before: `alert2.pururu_<device>_appliance_alert_<name>`.
- `alert_<name>` is in the feature's `entity_keys` (on `Platform.BINARY_SENSOR`), so ID collisions between devices, translations and icons are checked as for any entity key. A hand-written alert's `when` can't name it: an alert watching an alert is refused, as today for the `alert` namespace, now for every `alert_*` entity key. A reaction's `when` can (`when: appliance_alert_offline`), as it can a hand-written alert.
- **Name:** translated (`entity.binary_sensor.appliance_alert_offline.name`), like every fixed entity key: "Offline" / "Sem conexão", "No power" / "Sem energia", "Long cycle" / "Ciclo longo", "No cycle" / "Sem ciclo", "Finished" / "Terminou".
- **Attributes:** as a hand-written alert: `priority`, `watches` (the entity it watches: the running sensor for the three time-based ones), and `message`, `done_message` (the defaults, or the user's `notify`).
- **Follows** the entity it watches: not created when that one isn't, with the usual log line.

### `appliance_running` gains `cycle_start`

`long_cycle` needs the running cycle's start. `Running` already keeps it (its restored `CycleStart`) but doesn't show it. It becomes an attribute, **`cycle_start`** (a datetime), present while the appliance runs, absent otherwise. It survives restarts, as `CycleStart` does. `last_cycle_start` can't serve: it changes only when a cycle ends, so during a cycle it is the previous one's.

## How it's built

### `feature.py`

```python
@dataclass(frozen=True, kw_only=True)
class Preset:
    """A ready-made alert of a feature: off until the feature's block enables it."""

    # The entity key, in the feature's namespace, it watches (power, running)
    watches: str
    # What makes it a problem: a condition on the watched state, or the time since a milestone
    kind: Condition | Elapsed
    priority: str
    # The default `for`; None: the user must give it. Unused by an Elapsed with `lasts`
    hold: timedelta | None
    # How long it stays on after its milestone (finished); only an Elapsed has it
    lasts: timedelta | None = None


class Feature:
    ...
    # Ready-made alerts it offers, by name: each enabled one is entity key alert_<name>
    alerts: Mapping[str, Preset] = field(default_factory=dict)
```

`Condition` is the one of `features/alerts.py` (moved to `feature.py` or imported, whichever keeps imports acyclic); `Elapsed` is new:

```python
@dataclass(frozen=True, kw_only=True)
class Elapsed:
    """On while the watched entity is `state` and the time since the milestone is in [for, for + lasts)."""

    # The watched entity's state it holds in: "on" (long_cycle) or "off"
    state: str
    # The milestone: an entity key of the feature whose state is a datetime (last_cycle_end)...
    since_key: str | None = None
    # ...or an attribute of the watched entity (cycle_start); exactly one of the two
    since_attribute: str | None = None
    # With no milestone yet, count from the alert's creation (no_cycle)
    or_since_created: bool = False
```

The milestone is also never older than the moment the alert saw the watched entity enter `state` (a real change, not from `unavailable`/`unknown` or a restored state): running goes `off` a moment before `last_cycle_end` is written, and the previous end must not turn `no_cycle` on for that moment.

The appliance's catalogue is `PRESETS` in `features/appliance/alerts.py`, and `APPLIANCE` gets `alerts=PRESETS`.

### The core (`__init__.py`)

- **Schema:** for every feature with `alerts`, its block's schema accepts `alerts:` (the configuration section above). Done where `CONFIG_SCHEMA` is assembled from `FEATURES`, not in each feature.
- **Entity keys:** `alert_<name>` for every offered alert is added to what the feature can create wherever the core reads `entity_keys` (the collision check counts every entity key a feature can create, even one not enabled, as today).
- **Build:** in `_build`, after `feature.build(...)`, the enabled alerts of that feature are built in its namespace, with the current entity IDs of what they watch, and go through `follows`/`_creatable` like any entity.

### The entities

- A base, `ProblemAlert` (problem binary sensor, restored state, the attributes above, what the Alert2 file needs), shared by:
  - **`Alert`** (condition): today's class, behaviour unchanged. `offline` is `is: unavailable`, `no_power` is `is: 0` (compared as a number).
  - **`ElapsedAlert`** (new, `features/elapsed.py`): on while the watched entity is in `state` **and** `for ≤ now − milestone < for + lasts` (no upper bound without `lasts`). It schedules one timer for the next change (the moment it turns on, or off at `lasts`), recomputed at every change of the watched entity or the milestone, at start and after a restore. Without a reading (the watched entity `unavailable`/`unknown`, the milestone unknown) it keeps its state, as a condition alert does.
    - `long_cycle`: watches `running`, state `on`, milestone its `cycle_start` attribute.
    - `no_cycle`: watches `running`, state `off`, milestone `last_cycle_end`; with no milestone ever, the time the alert was first created, kept in its restored extra data.
    - `finished`: watches `running`, state `off`, milestone `last_cycle_end`, `for` 0, `lasts` its setting.
- Like `Alert`, both follow their entities once HA has started (`async_at_started`): entities pass through `unavailable` while HA starts.

### The Alert2 file

`_alert2_alerts` builds the list from the **created** `ProblemAlert`s that have `notify`, instead of from the device's `alerts:` configuration: each knows its object ID, current entity ID, device name, name, priority and texts. Hand-written alerts give exactly the entries they give today; ready-made ones come with them.

The `friendly_name` of a ready-made alert is `<device name> <translated name>`, the translation in HA's language.

### Default texts

- In the translations' `common` block, which the dashboard already uses: `appliance_alert_<name>_message` and `appliance_alert_<name>_done_message` (namespace, `alert_`, name), in `en.json` and `pt-BR.json`.
- Read with HA's translation helper in `hass.config.language`, English when the language has none, at setup (once per setup, before the entities are built).
- They don't repeat the device's name: Alert2 puts the alert's friendly name in every notification.

| Alert | message (en / pt-BR) | done_message (en / pt-BR) |
|---|---|---|
| `offline` | The plug is offline. / A tomada está sem conexão. | The plug is back. / A tomada voltou. |
| `no_power` | There's no power. / Está sem energia. | Power is back. / A energia voltou. |
| `long_cycle` | The cycle is taking too long. / O ciclo está demorando demais. | The cycle ended. / O ciclo terminou. |
| `no_cycle` | It hasn't run in a while. / Não roda há um tempo. | It's running again. / Voltou a funcionar. |
| `finished` | The cycle finished. / O ciclo terminou. | Done. / Pronto. |

## Edge cases

- **Enabling `finished` right after a cycle** that ended less than `lasts` ago: it turns on at once. Accepted; the docs say so.
- **A restart in the middle** of a time-based alert: nothing starts over; the timer is recomputed from the milestone.
- **The milestone moves back** (a user fixes a sensor's value): recomputed like any change.
- **A ready-made alert and a hand-written one with the same name**: different namespaces, different entity IDs; nothing to refuse.
- **An appliance without `statistics`:** the milestones (`last_cycle_end`, `cycle_start`) exist regardless; every alert can be enabled.

## Docs

- `docs/features/appliance.mdx`: a **Ready-made alerts** section (the table, the YAML, the `no_power` warning, the default texts, what can be set) and the `cycle_start` attribute under Entities.
- `docs/features/alerts.mdx`: a pointer to ready-made alerts, for the common cases.
- `docs/reference/configuration.mdx`: the full example enables one; the general rules mention `alerts:` inside a feature.
- `docs/reference/troubleshooting.mdx`: the new configuration errors.
- `docs/develop/writing-a-feature.mdx`: `Feature.alerts`, `Preset`, `Condition`/`Elapsed`, and the contract test's checks. `docs/develop/architecture.mdx` and `CLAUDE.md`: the build step and the Alert2 file from entities.

## Tests

- **`tests/test_presets.py`** (the appliance's catalogue):
  - Schema: null is `{}`; a required `for` missing; an unknown alert; a setting that doesn't apply; an empty `alerts:`; the error texts.
  - Each alert turning on and off in simulated time (`tick`, `fake`); `offline` and `no_power` keep their state without a reading.
  - `long_cycle` and `no_cycle` across a restart (`restart` with saved states): the time already passed counts.
  - `no_cycle` never having had a cycle: counts from its creation, across a restart.
  - `finished`: off at `lasts`; off at once when a new cycle starts.
  - Default texts in English and in Portuguese (`hass.config.language`), and a user `notify` replacing them.
  - The entity ID, the translated friendly name, the attributes, and the entry in `pururu/alert2/alerts.yaml`.
  - Not created when what it watches isn't.
- **`tests/test_features.py`** (contract, over every feature with `alerts`): every ready-made alert has a name and an icon, both default texts in every language, watches an entity key of its own feature, and its settings with the required ones pass the schema.
- **`tests/test_appliance.py`:** `cycle_start` present while running, absent otherwise, kept across a restart.
- **`tests/test_alert2.py`:** unchanged expectations for hand-written alerts (the file now comes from entities).
