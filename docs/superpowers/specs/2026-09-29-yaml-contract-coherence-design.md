# YAML contract coherence and code architecture — design

**Status:** agreed, not started. **Base:** `main` at 7b5fb5c (0.1.23), which already has [a reaction's retry](2026-09-29-reaction-retry-design.md) (0.1.22) and [notifications](2026-09-29-notifications-design.md) (0.1.23). **Branch:** `worktree-peaceful-bubbling-bee`.

**For:** whoever implements it, person or agent. It says what changes, why, in which PR, and what stays on purpose. Read the Summary and the Glossary first; Parts 1–4 are the detail, and [The whole contract](#the-whole-contract-020) shows the result; PRs says the order. Everything in the Summary is decided; [Open decisions](#open-decisions) lists what isn't, none of which blocks the seven PRs. All seven together are **0.2.0**.

**pururu has one user, its author.** Nothing here keeps backward compatibility (see [Compatibility](#compatibility)).

## Summary of decisions

| # | Decision | Why, in one line | Where | PR |
|---|---|---|---|---|
| D1 | Keep the one `pururu:` block, YAML configuration, entity IDs by concatenation with an error on collision | They follow HA's ADR-0007/0010 and Alert2; nothing to gain | [What stays](#what-stays) | — |
| D2 | Place a concern by **what it can reference**, never by one instance nor by what it generates | One rule the user can apply to any new key | [Part 1](#part-1-the-contracts-model) | B |
| D3 | **Features** are atomic; **device keys** (`alerts`, `programs`, `reactions`) cross features; **aspects** (`statistics`, ready-made `alerts` and `notifications`) are mounted in a block | Features stop carrying concerns that aren't theirs | Part 1 | B |
| D4 | Hand-written `alerts` stops being a feature and becomes a device key | It only watches other builders; as a feature, a device with alerts and only programs or reactions passes with no feature at all | Part 1 | B |
| D5 | **Listen anywhere, act only on yourself** | Devices depend on each other to know, never to act | Part 1 | — (already the rule) |
| D6 | **Decoupling is ownership, not placement**: an aspect's module owns its key's schema wherever the key sits | The key stays next to what it measures, and the feature still imports nothing of it | Part 1 | B |
| D7 | One reference form: `key` (same device), `device.key` (another device), `entity:` (a real entity) | Five forms today | [Part 2](#part-2-the-vocabulary) #1 | C |
| D8 | One condition vocabulary (`state` as text, `above`/`below`, `for`); `is` → `state` (`threshold` → `above` comes with D's `running_program`) | The same syntax compares differently today | Part 2 #2 | C |
| D9 | `notify` always means **where**; an alert's texts are flat `message`/`done_message` | `notify` means two things today | Part 2 #10 | C |
| D10 | `resolved.for` → `resolved.lasts`; every time is an HA time period | `for` means two things; one time format isn't HA's | Part 2 #3 #4 | C |
| D11 | One `Program` type: the appliance's `running_program` (required), `programs: {detected, executable}` in a feature or a device, and `phases`, which are programs without phases. It replaces `modes`, `phases` and `cycle_from` | A cycle is a run of a program with phases; modes, phases and programs were three names for pieces of that | [Part 4](#part-4-programs) | D |
| D12 | `event_entities:`, `config: events:`, `lights: default`, non-empty names | Name clashes, two homes for globals | Part 2 #6–#9 | C |
| D13 | No backward compatibility: no aliases, deprecation issues or migration code | One user | [Compatibility](#compatibility) | all |
| D14 | Code: every concern is one module owning schema, rules, build and output; the wiring and `__init__` walk four lists (`builders()`, `ASPECTS`, `CHECKS`, `STEPS`) | Growing is one module and one line; no god module | [Part 3](#part-3-the-code-architecture) | A |
| D15 | A `Feature` is 5 fields plus a tuple of **roles** (Extension Object), replacing today's 9 optional fields | `Feature` stops growing; each builder lists only what it is | Part 3 | A |
| D16 | Six layers, all enforced by one import test | Dependency direction stays true without review | Part 3 | A2a (part), B (the whole table) |
| D17 | Validate (no `hass`) → plan (a frozen `Built`) → apply (`STEPS`, each guarded) | A broken output can't leave the entry stuck until a restart | Part 3 | A |
| D18 | One automations file for reactions and ready-made notifications | One include, one Repairs issue, one reload per change | Part 3 | B |
| D19 | Seven PRs: A1 (moves), A2a (lifecycle), A2-layout (folders), A2b (model), B (aspects), D (programs), C (vocabulary). Together they are 0.2.0; A1 sets the version, so v0.2.0 is tagged with A1 alone, and the rest lands on `main` under it. An ID snapshot first | Small reviewable steps; one version for one breaking change | [PRs](#prs) | — |
| D20 | No entity ID or unique ID changes in A1–C. D changes the IDs of today's `modes` and `phases` entities (their history is lost, accepted); the appliance's own entities keep theirs | Keep history where it costs nothing | PRs | all |
| D21 | One folder per layer: `core/` (L0), `features/` (L1), `aspects/` and `device_keys/` (L2), `outputs/` (L3), `setup/` (L4 and the lifecycle); at the root only what HA requires there (`__init__`, `config_flow`, `const`, the platforms, manifest, translations, icons, services) | The root had 32 modules and would pass 35; the tree then shows the layers the import test enforces. Replaces the earlier "keep it flat" | [PRs](#prs) | A2-layout |
| D22 | A program's scope: in a feature's block it sees only that feature; at the device it sees the device's features and may run their executable programs. Only an executable program can be started, and one program runs another only from the device to a feature | Placement by what it can reference (D2); no call cycles, fixed depth | Part 4 | D |
| D23 | `__init__.py` holds only HA's entry points, each a few lines; what they do is in `lifecycle.py` and `listener.py` | HA finds them there and reviewers look there; logic belongs to modules with one job | Part 3 | A2 |

## Glossary

| Term | Meaning |
|---|---|
| **house** | The validated `pururu:` block: `config`, `floors`, `areas`, `devices`. |
| **device key** (the concept) | A key of a device that isn't a feature and can reference any of its features: `alerts`, `programs`, `reactions`. Listed in `DEVICE_KEYS`. |
| **device key** (the identifier) | A device's key under `devices:` (`laundry_washer`). The text always says which. |
| **feature** | An atomic component of a device, a key in `FEATURES`: `appliance`, `door`, `window`, `switches`, `lights` (and `phases`, `modes` until D). |
| **builder** | Any entry of `FEATURES` or `DEVICE_KEYS`: a `Feature` value that validates its block and builds entities. `builders()` returns both. |
| **namespace** | A builder's prefix in entity keys: `appliance`, `phase`, `mode`, `switch`, `light`, `alert`, `program`, `reaction`. |
| **entity key** | An entity's ID after `<platform>.pururu_<device>_`: `appliance_running`, `switch_pump`. Local keys (inside a builder) drop the namespace: `running`. |
| **aspect** | A cross-cutting concern mounted in a builder's block (or in each item): `statistics`, a feature's ready-made `alerts`, its ready-made `notifications`. Listed in `ASPECTS`. |
| **offered** | An aspect is offered by a builder when the builder has the role the aspect needs (`statistics` needs `Counters`). Only then does the builder's block accept the aspect's key. |
| **mount** | Taking an offered aspect's key out of a block (or item), validating it with the aspect's schema, and passing the rest to the builder's schema. |
| **role** | A small frozen dataclass a builder composes to declare one thing it is or has: `Provides`, `Counters`, `Presets`… (Part 3). |
| **preset** | The definition of a ready-made alert, in its feature's code (`offline`: `power` has no reading for 10 min). |
| **happening** | The definition of a ready-made notification, in its feature's code (`finished`: `running` goes `on` → `off`). |
| **item** | One entry of a builder whose block is a map of items with entity keys of their own: a program, a phase, a reaction (a mode until D). |
| **program** | A named kind of run (Part 4). **Detected**: pururu tells it runs from a reading (the appliance's `running_program`, a purifier's "gelar"). **Executable**: its steps are written in the YAML and pururu runs them as a script ("limpar"). |
| **phase** | A stage inside a program's run (washing, spinning). A phase is a program that has no phases of its own. |
| **cycle** | One run of a program: start, end, duration, energy, counted. `door`/`window` openings are cycles too (`open`). |
| **`CycleSource`** | The entity base class of a cycle's carrier: it sends state → cycle signal → end signal in that order, which `Running` and `Current` (modes) and `Open` each do by hand today. The `cycle_start`/`cycle_end` attributes stay opt-in: `Running` and `Current` have them, `Open` doesn't, and B doesn't add them. |
| **reference** | How the YAML names an entity: `key`, `device.key`, or `entity: <entity_id>`. `Ref` in code. |
| **`Index`** | device key → entity key → `Target`: every entity key every builder and aspect can create, per device. Built once, from the house. |
| **generated kind** (`Kind`) | A YAML file pururu writes for HA to load, with its registry bookkeeping (`generated.py`): today scripts, reactions' automations, notifications' automations. |
| **held** | A generated item whose target entity is disabled: out of the file, its registry entry and tracked ID kept, back as the user left it once enabled. **Dropped**: out because a target isn't created. |
| **`_creatable`** | Today's fixed point in `__init__.py`: drops an entity whose ID is taken or whose source isn't created, then repeats until nothing more drops. |
| **`_remove_stale`** | Today's cleanup: deletes the entry's registry entries and devices the house no longer builds, which loses the user's customisations of them. |
| **`_place`** | Today's step putting each device in its `area:`. |
| **holder** | Who else holds an entity ID pururu wants (another integration, an entity without unique ID). Today `_holder`; `entity.other_holder` after PR A. |
| **wiring** | The L4 modules that walk the lists: `schema`, `catalogue`, `checks`, `build`, `generate`. |
| **core** | The L0 modules: contracts and shared helpers, naming no concrete builder, aspect or output. |

## Goal

The top of the contract is right: one block under the domain ([ADR-0007](https://github.com/home-assistant/architecture/blob/master/adr/0007-integration-config-yaml-structure.md)), YAML for an integration that processes HA's data and generates automations ([ADR-0010](https://github.com/home-assistant/architecture/blob/master/adr/0010-integration-configuration.md)), entity IDs by concatenation with a configuration error on collision (as [Alert2](https://github.com/redstone99/hass-alert2)). Three things drifted:

1. **The contract's structure.** Features carry concerns that aren't theirs. Per-period statistics are built in five places (`appliance`, `door`/`window`, `modes`, `programs`, `reactions` each import `PERIOD_LIST` and `Meter`). The appliance's ready-made alerts make its schema depend on Alert2 and the alert lights (`features/presets.py` imports `NOTIFY` and `lights_group`). The hand-written `alerts`, which only watches other features, is registered as a feature.
2. **The vocabulary.** Five ways to reference something, the same idea under different names, `notify` meaning two things, one time format that isn't HA's.
3. **The code.** `__init__.py` is 1170 lines: validation (~400), reference resolution, building, the generators' wiring, registry reconciliation, events' devices and the rename listener. `Feature` is a 14-field record that every builder half uses and that gains a field per need.

## What stays

| Kept | Why |
|---|---|
| One `pururu:` block, configured in YAML | ADR-0007 (one block under the domain); ADR-0010 names template, utility_meter, automation, alert and script as integrations YAML suits. Powercalc 1.8 moved to the same shape. |
| Entity IDs by concatenation (`<platform>.pururu_<device>_<namespace>_<key>`), an error on collision, never `_2` | Predictable IDs the user can write; Alert2 does the same; renames in the UI are followed. |
| Device keys and features side by side in a device (no `features:` level) | A closed, validated set: one more level on every device buys nothing. |
| A device needs at least one feature | A device is its entities. A device with only reactions or only programs is refused, as today. |
| An executable program's four step kinds (`turn_on`, `turn_off`, `toggle`, `delay`), on its own device only | A program is a method of its device; anything richer is an HA script of the user's. D adds none; running a feature's executable program from a device's is the only new call (D22). |
| One trigger per reaction; `retry` adds tries of the **same** trigger at later times | Keeps reference validation and rename following simple. A list of triggers is left open. |
| `on_delay`/`off_delay` | An asymmetric debounce, not a hold. HA's Threshold, template and ESPHome use three names for it; renaming would be cosmetic. |
| Input names by role: `power`, `energy`, `contact` | They say more than a generic `sensor`. |
| Ready-made alerts and notifications in their feature's block | Their IDs carry the feature's namespace (`appliance_alert_offline`, `appliance_notification_finished`); Alert2 names and acknowledgements are kept. |

## Part 1: the contract's model

Lands in **PR B** (the YAML users write doesn't change).

### A device is an object

| Part | What it is | Examples |
|---|---|---|
| **Features** | Components: read real entities and their own settings, create their own entities. They know nothing of statistics per period, alerts, notifications, Alert2 or alert lights. | `appliance`, `door`, `window`, `switches`, `lights` (`phases`, `modes` until D) |
| **Device keys** | What exists because of the aggregation: can reference any feature of the device. | `alerts` (invariants the device watches on itself), `programs` (methods: act on its own entities), `reactions` (event handlers: listen anywhere, call its own methods, tell a message) |
| **Aspects** | Cross-cutting concerns applied to one block's own entities, implemented once, mounted wherever a builder offers them. | `statistics`, a feature's ready-made `alerts` and ready-made `notifications` |

### Placement rule

**Where something goes is decided by what it can reference, never by what one instance happens to reference, nor by what it generates.** Statistics become sensors, alerts binary sensors, notifications automations: none of that decides where they're written.

| Concern | Can reference | Where |
|---|---|---|
| `statistics` | one counter of its own block | mounted in the block (a feature's, or each program's and reaction's item) |
| ready-made alerts | only their feature's entities (`offline` watches `power`) | mounted in the feature's block |
| ready-made notifications | only their feature's entities (`finished` watches `running`) | mounted in the feature's block |
| hand-written `alerts` | any feature of the device (`when: phase_current`) | device |
| programs in a feature's block (D) | only that feature (the purifier's "gelar" reads the appliance's power) | mounted in the feature's block |
| programs at the device | the device's features, their executable programs included (`switch_pump`, then `light_teto`) | device |
| `reactions` | any feature, another device, a real entity, a time, the sun | device |

A reaction watching only `light_teto` still goes on the device: otherwise the same thing would live in two places depending on the instance. A hand-written notification is a reaction with a `message`, so it is on the device too.

### Listen anywhere, act only on yourself

A reaction may listen to another device, a real entity or the clock; its `then` only starts one of its own device's programs, and a program only acts on its own device's entities. A device depends on another to **know**, never to **act**. A message is told to people, not done to a device, so a reaction's `message` doesn't break it.

### Decoupling is ownership, not placement

The feature's block holds `statistics:`, `alerts:` and `notifications:` because that's where a reader looks for everything about the feature. What keeps the feature decoupled is that it never imports those concerns: each aspect's module owns its key's schema, validation and entities, and asks the builder for its roles. Putting the keys at the device (`statistics: {appliance: …}`) would be the same matrix transposed, no less coupled, and would spread the appliance over three blocks.

### A feature's catalogue, one shape

Everything ready-made a feature offers is enabled in its own block, one key per aspect: `appliance: {statistics: …, alerts: …, notifications: …}`.

### `alerts` in two places is one aspect with two mounting points

Mounted in a feature's block it's that feature's catalogue; on the device it's the user's own. One schema for the keys they share (`priority`, `notify` (after C: `message`, `done_message`), `lights`), one entity class (`ProblemAlert`), and the ID says where it's mounted: `appliance_alert_offline`, `alert_stuck`. They differ where their nature does: a hand-written alert has `name`, a condition and an optional `for`; a ready-made one has its name and condition fixed by its preset, and its `for` is the preset's (`offline` defaults to 10 minutes; `long_cycle` requires one).

### Why hand-written `alerts` becomes a device key

Today it is in `FEATURES`, so it counts toward "a device needs at least one feature". A device with only `alerts` is refused anyway (an alert must watch another builder's entity), but a device with `alerts` and only `programs` or `reactions` passes, with no feature at all: its alerts watch the reactions' or programs' statistics. It also appears among the features in the docs. As a device key, next to `programs` and `reactions`, such a device fails the existing rule, with its existing message: `a device needs at least one feature (…)`.

## Part 2: the vocabulary

Lands in **PR C**. The problems, numbered as below:

| # | Where | Problem |
|---|---|---|
| 1 | References | Five forms: `when: appliance_running`, `turn_on: switch_pump`, `device:` + `when:` (two fields for one reference), `entity:` for a real ID, and alert light groups `{pool: [led]}`, a bare key without the `light_` namespace. |
| 2 | Conditions | An alert's `is: 1` compares as a number (`1.0` matches); a reaction's `to: 1` as text. (The appliance's `threshold`, `above` in `phases` and `modes`, becomes `above` in D, with `running_program`.) |
| 3 | Durations | `resolved.for` means "how long it shows"; everywhere else `for` means "how long the condition must hold". |
| 4 | Time format | `repeat` and `resolved.for` take only `{seconds: N}` (`alert_lights.py`); every other time takes `{minutes: 1}`, `"00:01:30"` or `90`. |
| 5 | Coupling | `phases`/`modes` say `cycle_from: appliance` and still ask for the power `sensor`, and `modes` for `energy`. Solved by Part 4 (D), not in C: `cycle_from` goes. |
| 6 | Two-typed value | `lights: true \| group`, `true` meaning the group `default`. |
| 7 | Names | `door`/`window`'s `events` (`event.*` entities) clashes with the top-level `events` (bus events). (`modes: modes:` goes with `modes` in D.) |
| 8 | Globals | In two places: `config:` (`notify`, `alerts.lights`) and top-level `events:`. |
| 9 | Validation | A device's, floor's and area's `name` is a plain `cv.string`; every other `name` refuses empty text. `for` defaults to `timedelta(0)` in alerts and to nothing in reactions. |
| 10 | `notify` | In `config`, a reaction and a notification it's **where** (`notify.mobile_app_x`); in an alert it's **what** (`notify: {message, done_message}`). |

### #1 One reference form

| What | Written as |
|---|---|
| An entity of the same device | `appliance_running` |
| An entity of another device | `laundry_washer.appliance_running` |
| A real entity | `entity: sensor.x` (its own key, not a reference) |

`<device>.<key>` already exists: it is the `event_name` `events.py` fires. Not `appliance.running` (a dot between namespace and key): it reads like an entity ID and stops matching the end of the ID the user sees.

Where each form is accepted:

| Place | `key` | `device.key` | `entity:` |
|---|---|---|---|
| a hand-written alert's `when` | yes | no (an alert watches its own device) | no |
| a reaction's `when` | yes | yes | yes (instead of `when`) |
| a reaction's `then` | an executable program key of its device | no | no |
| a program step | yes | no | no |
| `config: alerts: lights: groups` | no | yes, always (groups live outside any device) | no |

A hand-written alert's `when`, `then` and program steps use one `local_key` validator that refuses a `<device>.` prefix with `<x> must be of this device`. A light group reference must resolve to a `lights` entity.

What each referrer may target, once resolved (a `Target`, Part 3):

| Referrer | May target |
|---|---|
| a hand-written alert's `when` | an entity key of another builder of its device that no alerts aspect or device key added (an alert never watches an alert) |
| a reaction's `when` | any entity key of the target device, except the statistics of its own item (it may watch another reaction's) |
| a program step | an entity key of a builder of its device with `Actions` including the step's action |
| a light group entry | an entity key of that device's `lights` |

### #2 One condition vocabulary

One vocabulary in `vocabulary.py`, parsed into one `Condition`, used by hand-written alerts, ready-made alerts, reactions and ready-made notifications:

```yaml
# an alert: a level, "is it a problem now?"
when: <reference>
state: "on"               # text, as HA's condition: state
above: 50                 # number, strict, as numeric_state (with or instead of below)
below: 1000
for: {minutes: 3}         # how long it must hold

# a reaction: an edge, "did it just change?"
when: <reference>         # or entity: <entity_id>
from: "on"                # optional, only with to
to: "off"                 # parsed into Condition.state
above: 50                 # or above/below: crossing into the range
for: {minutes: 5}
```

- An alert writes `state`; a reaction writes `to` (and `from`), HA's trigger words, parsed into the same `Condition.state`. Each refuses the other's word. Both give `state`/`to` **or** `above`/`below`, not both.
- An alert's `is` becomes `state`, compared as text by the same rule as a reaction's `to`/`from`. `"on"`/`"off"` and YAML's booleans are still read as `on`/`off`. `state: 1` matches `1`, not `1.0`: a numeric comparison is `above`/`below`.
- `for` in a hand-written alert and a reaction has no default; absent means at once, the same behaviour as today's `timedelta(0)` in alerts. A ready-made alert's `for` is its preset's (a default, or required), as today.
- `no_power` (power is exactly 0) keeps a numeric equality, in code only: `Condition.equals`, never in YAML and refused by `trigger()`.
- Bands are untouched by C: today's phase bands keep `for` and mode bands `on_delay`/`off_delay` until D makes both programs, which use `on_delay`/`off_delay` (Part 4).
- The module is `vocabulary.py`, not `condition.py`: HA preloads a platform named `condition` for every integration.

### #10 One meaning for `notify`

- `notify` is always **where**: a `notify.<name>` action or a list, in `config`, a reaction, a ready-made notification.
- The text is always **what**, flat on the item: `message`, and for an alert `done_message`. An alert gives both or neither, as today's `notify: {message, done_message}` requires both. A ready-made alert that gives them replaces both default texts.
- An alert goes to the Alert2 file when it has texts: its own, or a ready-made alert's defaults. Where an alert is told stays Alert2's (`defaults: notifier`).

### #3 #4 One time format

- `resolved.for` becomes `resolved.lasts`: how long the light shows `resolved`.
- `repeat` and `resolved.lasts` take any HA time period, each at least one second (`vol.Range(min=timedelta(seconds=1))`), today's minimum: `cv.positive_time_period` alone accepts 0, which `async_track_time_interval` would turn into a busy loop.

### #6–#9 The small ones

- `lights: true` → `lights: default`: always the group's name; absent means none.
- `door`/`window`'s `events:` → `event_entities:`.
- Top-level `events:` → `config: events:`. `config:` is the one place for settings of the whole house.
- The `name` of a device, floor and area refuses empty text, as every other `name` (`schema._device`, `places.FLOOR_SCHEMA`, `places.AREA_SCHEMA`).

## Part 3: the code architecture

Lands in **PR A** (structure, types, lists), except what the B paragraph of [PRs](#prs) lists.

### Thesis

**Every configuration concern is one module that owns its schema, its rules, its build and its output.** No builder, aspect or output is named anywhere but the one line that lists it and the wiring that calls it (`generate.py` calls the planners, `schema.py` composes the schemas of `alert_lights`, `events` and `places`). The wiring (L4) walks the first three lists; `__init__` walks `STEPS`:

| List | Where | Holds | Borrowed from |
|---|---|---|---|
| `builders()` | `catalogue.py` | `{**FEATURES, **DEVICE_KEYS}` | Django `INSTALLED_APPS` |
| `ASPECTS` | `aspects/__init__.py` | statistics, alerts, notifications | VS Code `contributes`, ESPHome filters |
| `CHECKS` | `schema.py` | the rules over the whole house | Django system checks, ESPHome `FINAL_VALIDATE_SCHEMA` |
| `STEPS` | `__init__.py` | the outputs after the platforms | Rails initializers |

Growing is **one new module and one line in a list**, guided by the contract test. **Simple on purpose:** a new type exists only if it deletes a duplication that exists today; each type below says which.

`builders()` is a function that reads `FEATURES` and `DEVICE_KEYS` at call time. Today a `ChainMap` does that as a live view so tests that add to `FEATURES` are seen; the function does the same without the view's precedence rules, and a contract test checks the two dicts' keys are disjoint.

### Package

```
custom_components/pururu/
├── __init__.py       HA's entry points only, no logic: CONFIG_SCHEMA, async_setup, async_setup_entry,
│                       async_unload_entry, async_remove_entry, each a few lines calling lifecycle
├── lifecycle.py      what the entry points do: apply the YAML (reload), the prelude, the STEPS
│                       tuple and its guarded loop, unload, remove
├── listener.py       the registry listener: the one rename rule, disabled targets
├── config_flow.py    unchanged
├── const.py          DOMAIN, PLATFORMS, CONF_*, EVENT_*, ALERT2
├── runtime.py        PururuConfigEntry, Built, Step
├── feature.py        Feature, Aspect, Device, Item, Preset, Elapsed, Happening, PRIORITIES, TEXT
├── roles.py          the roles a builder composes
├── vocabulary.py     Condition and its helpers
├── entity.py         PururuEntity (+ reference), other_holder
├── resolve.py        Ref, Target, Index, find, local_key
├── texts.py          the translations' common texts (aspects, dashboard)
├── messages.py       unchanged
├── files.py          unchanged
├── generated.py      the Kind engine, Planned, async_issue
├── schema.py         CONFIG_SCHEMA, _device, CHECKS
├── catalogue.py      builders(), keys() (today's _entity_keys), mount(), index()
├── checks.py         generic rules: references, one real entity per device, distinct IDs, areas exist
├── build.py          plan(): builds, inputs, _creatable
├── generate.py       Kinds SCRIPTS (today's programs.KIND) and AUTOMATIONS, both from B; the generate step; async_remove
├── devices.py        the devices step: _place, _remove_stale
├── device_keys.py    DEVICE_KEYS = {alerts, programs, reactions}
├── programs.py       device key: schema, script, plan(), Runs, check
├── reactions.py      device key: schema (retry, message), automation, plan(), TriggersTotal, check
├── aspects/
│   ├── __init__.py   ASPECTS
│   ├── statistics.py Meter, PERIODS (the only importer of utility_meter), ASPECT
│   ├── problem.py    ProblemAlert, Alert, the shared alert schema (imported by alerts and elapsed)
│   ├── alerts.py     ASPECT (ready-made) + the device key ALERTS, check
│   ├── elapsed.py    ElapsedAlert (a ProblemAlert)
│   └── notifications.py  ASPECT, plan()
├── alert2_alerts.py  the Alert2 step; its own engine
├── alert_lights.py   schema, the group check, the step
├── events.py         schema (under config:), the step
├── dashboard.py      the step
├── places.py         floors and areas (C: names refuse empty text); floors_exist joins CHECKS
├── sensor.py, binary_sensor.py, switch.py, light.py   import only runtime
└── features/
    ├── appliance/    __init__ composes its roles; alerts.py (PRESETS), notifications.py (HAPPENINGS),
    │                   running.py, mirrors.py
    ├── cycle/        Cycle, signals, CycleSource, last, totals, energy (statistics.py moves to aspects/)
    └── modes/, opening/, phases.py, switches.py, lights.py (Borrowable), standing.py
```

The device key `ALERTS` lives in `aspects/alerts.py` because it shares its schema and its entity class (`ProblemAlert`, in `aspects/problem.py`, so `alerts` and `elapsed` both import it without importing each other) with the ready-made alerts; `programs` and `reactions` have no aspect counterpart and stay top-level.

### Layers

| Layer | Modules | May import |
|---|---|---|
| **L0 core** | const, runtime, feature, roles, vocabulary, entity, resolve, texts, messages, files, generated | L0 only |
| **L1 features** | `features/**` | L0; its own package (`features/<x>/`, or itself for a module `features/<x>.py`); the shared libraries `features/cycle` and `features/standing`. `features/__init__` may import every `features/*` package: it lists `FEATURES`. |
| **L2 cross-cutting** | `aspects/*`, programs, reactions, device_keys | L0; `features/cycle` (shared machinery, not a feature); another `aspects/*` module. `device_keys` may import programs, reactions and `aspects/alerts`. |
| **L3 outputs** | alert2_alerts, alert_lights, events, dashboard, places, devices | L0; L2's `aspects/alerts` (Alert2 reads `ProblemAlert`); `features/lights` (alert lights lend `Borrowable` lights) |
| **L4 wiring** | schema, catalogue, checks, build, generate | L0–L3; the only layer that reads `FEATURES`, `DEVICE_KEYS` and `ASPECTS` |
| **L5 entry** | `__init__`, config_flow, the platforms | L0–L4; the platforms import only `runtime` and `homeassistant` |

`runtime.py` is L0: it imports `feature`, `resolve` and `entity` for `Built`'s types, and the platforms import nothing else of pururu. HA's own registries (entity, device, area) are used wherever needed; "walking the lists" above means pururu's four lists.

**Enforced by one test** (`tests/test_code.py`): it maps every module to its layer and fails on any import the table doesn't allow, with the table's named allowances as the only exceptions, nothing per file (per-file exceptions are how such tests rot). It also fails on a top-level module named after a platform HA preloads (`BASE_PRELOAD_PLATFORMS`: `condition`, `trigger`, `repairs`, `config`, `diagnostics`…), except `config_flow.py`, which is that platform on purpose.

The test lands in two steps, because today's code breaks the table until B moves the ready-made alerts and notifications:

| PR | Rules the test enforces |
|---|---|
| A2a | L0 imports only L0; the platforms import only `runtime` and `homeassistant`; the preload names. (A1 already moved `ALERT2` to `const.py` and `PRIORITIES` to `feature.py`, so L1 stops importing outputs.) |
| B | The whole table: L1 imports no aspect and no output (today `features/alerts.py` imports `alert2_alerts`); L2 imports only what its row allows (today `notifications.py` imports `FEATURES` and `reactions`); L3 imports only what its row allows (today `alert_lights.py` imports `features.alerts`); only `aspects/statistics` imports `utility_meter`. |

### A builder is composed of roles

A `Feature` is five fields every builder has, plus a tuple of **roles**. Each role is a small frozen dataclass in `roles.py`; the wiring and the aspects ask for a role by its type. This is the Extension Object pattern (Unity's `GetComponent<T>()`, Bevy's components, Eclipse's `getAdapter`): composition, no inheritance, and `Feature` never gains a field. It deletes today's nine optional fields (`provides`, `requires`, `configured`, `refers`, `actions`, `per_item`, `items`, `alerts`, `notifications`).

```python
# roles.py (L0): every role there is. It imports Item, Preset, Happening (feature.py) and Ref
# (resolve.py) under TYPE_CHECKING; feature.py imports Role the same way.
@dataclass(frozen=True)
class Provides:            # until D: a capability other builders consume through <capability>_from
    capability: str        # "cycle"
    key: str               # the local entity key carrying it: "running"

@dataclass(frozen=True)
class Requires:           # until D
    capability: str

@dataclass(frozen=True)
class Counters:            # totals the builder builds as f"{counter}_total"; the statistics aspect meters them
    needs: Mapping[str, str | None]            # counter -> the setting it needs (None: always)
    mount: Literal["block", "item"] = "block"  # where `statistics:` sits; with Items, meters repeat per item either way

@dataclass(frozen=True)
class Presets:             # ready-made alerts
    presets: Mapping[str, Preset]

@dataclass(frozen=True)
class Happenings:          # ready-made notifications
    happenings: Mapping[str, Happening]

@dataclass(frozen=True)
class Configured:          # entity keys come from the block's keys, named by each `name`
    platform: Platform

@dataclass(frozen=True)
class Actions:             # what a program step may do to its entities
    actions: tuple[str, ...]

@dataclass(frozen=True)
class Items:               # the block is a map of items with entity keys of their own
    keys: Mapping[str, Platform]               # per item: "<item>_<suffix>"
    items: Callable[[Any], Iterable[Item]]

@dataclass(frozen=True)
class Refers:              # the references its block makes (alerts' and reactions' when, program steps)
    refers: Callable[[Any], Iterable[Ref]]     # its inputs are keyed by each reference's text ("washer.appliance_running")

@dataclass(frozen=True)
class Generates:           # the (domain, object ID) of what it writes to a generated kind
    generates: Callable[[str, Any], Iterable[tuple[str, str]]]

type Role = Provides | Requires | Counters | Presets | Happenings | Configured | Actions | Items | Refers | Generates

# feature.py (L0)
type Build = Callable[[HomeAssistant, Device, dict[str, Any], Mapping[str, str]], list[PururuEntity]]
#             hass, the device in this namespace, the validated block, inputs (entity key -> current entity ID)

@dataclass(frozen=True, kw_only=True)
class Feature:
    namespace: str
    schema: Callable[[Any], Any]
    entity_keys: Mapping[str, Platform]        # local keys it can create itself
    build: Build
    example: Mapping[str, Any]
    roles: tuple[Role, ...] = ()

    def role[R: Role](self, kind: type[R]) -> R | None:
        return next((r for r in self.roles if isinstance(r, kind)), None)
```

Every builder's roles:

| Builder | Roles |
|---|---|
| `appliance` | `Provides("cycle", "running")` (D: `Programs(reading="power", energy="energy")` instead), `Counters({"runtime": None, "cycles": None, "idle_energy": "energy"})` (D: `idle_energy` only; runtime and cycles become `running_program`'s), `Presets(PRESETS)`, `Happenings(HAPPENINGS)` |
| `door`, `window` | `Provides("cycle", "open")` (until D: nothing consumes it after), `Counters({"openings": None, "open_time": None})` |
| `phases` (until D) | `Requires("cycle")` |
| `modes` (until D) | `Requires("cycle")`, `Items(PER_MODE, _modes)`, `Counters({"runtime": None, "cycles": None, "energy": "energy"}, mount="block")` |
| `switches` | `Configured(Platform.SWITCH)`, `Actions(("turn_on", "turn_off", "toggle"))` |
| `lights` | `Configured(Platform.LIGHT)`, `Actions(("turn_on", "turn_off", "toggle"))` |
| `alerts` (device key) | `Configured(Platform.BINARY_SENSOR)`, `Refers(_whens)` |
| `programs` (device key) | `Items(PER_PROGRAM, _programs)`, `Counters({"runtime": None, "cycles": None}, mount="item")`, `Refers(_steps)`, `Generates(_scripts)` |
| `reactions` (device key) | `Items(PER_REACTION, _reactions)`, `Counters({"triggered": None}, mount="item")`, `Refers(_whens)`, `Generates(_automations)` |

- **Who builds what:** the builder builds its own entities, totals included (they need its inner state). The statistics aspect builds only the meters (`<counter>_<period>`, per item `<item>_<counter>_<period>`).
- **Mounting in items:** with `Counters(mount="item")`, the builder's raw block is a map of item key → item, and `mount` takes `statistics` out of each item before the builder's schema sees it. `Aspect.keys(feature)` returns suffixes (`runtime_today`); `catalogue.index` expands them per item (`clean_runtime_today`) when the builder has `Items`. For an item builder, "`f"{c}_total"` is one of its keys" means one of `Items.keys`.
- **A builder's inputs come from its roles:** `Requires` → the provider's entity ID; `Refers` → each reference's current entity ID; `Generates` → the generated IDs it owns. Today `_inputs` gives every device key its owned IDs, which would break `alerts` once it is a device key.
- **Which PR fills which role:** A2 converts today's fields (`Provides`, `Requires` without `inherits`, `Configured`, `Actions`, `Items`, `Refers`, `Presets`, `Happenings`) and adds `Generates`, which replaces `_generated_ids` and `_watched_items` for programs and reactions (until B makes notifications an aspect with its own `generates`, the distinct-ID check keeps today's notifications case); B adds `Counters`, read by the statistics aspect; D removes `Provides`/`Requires` and adds `Programs` (Part 4).
- **Features and device keys are one type:** what a builder is, is its roles; `builders()` stays one dict.
- **The contract test holds the combination rules:** each role type at most once per builder; `Configured` and `Items` never together; a `DEVICE_KEYS` builder has no `Provides`, `Requires` or `Actions`; the entity at `Provides("cycle").key` is a `CycleSource` (after D: every program's entity is); every `Preset.watches`, `Elapsed.since_key` and `Happening.watches` is one of the builder's keys.
- **A new role** is a class in `roles.py` and its rules in the contract test; `Feature` doesn't change.

### Other types

Each deletes something that exists today.

```python
# feature.py
@dataclass(frozen=True, kw_only=True)
class Aspect:                                   # 3 instances; deletes the 5 copies of statistics
    key: str                                    # the block key it mounts: "statistics"
    offered: Callable[[Feature], bool]          # f.role(Counters) is not None, …
    schema: Callable[[Feature, str], Callable[[Any], Any]]   # (builder, its key in the device, for messages)
    keys: Callable[[Feature], Mapping[str, Platform]]        # local entity keys it can add to the builder
    example: Callable[[Feature], Any]           # a valid value, for the contract test
    build: AspectBuild | None = None
    generates: Callable[[str, Feature, Any], Iterable[tuple[str, str]]] | None = None

type AspectBuild = Callable[
    [HomeAssistant, Device, Feature, Any, Mapping[str, str], Mapping[str, str]], list[PururuEntity]
]   # hass, the device in the builder's namespace, the builder, the aspect's validated value,
    # inputs (reference text -> current entity ID), texts (the translations' common texts:
    # ready-made alerts' default message and done_message)

# resolve.py: deletes reference resolution spread over __init__.py (_references_resolved,
# _reaction_resolved, _alert_light_group_resolved, _referable, _watched, _acted_on; _entity_keys becomes catalogue.keys())
@dataclass(frozen=True)
class Ref:
    device: str | None                          # None: this device
    key: str                                    # parse("washer.appliance_running")

@dataclass(frozen=True)
class Target:
    device: Device
    key: str                                    # qualified entity key
    platform: Platform
    builder: str                                # the builder's key in the device
    by: str | None                              # the aspect that added the key; None: the builder's own
    item: str | None                            # the item that owns the key (a mode, program, reaction); None: none
    actions: tuple[str, ...]                    # its builder's Actions, for program steps; () without

type Index = Mapping[str, Mapping[str, Target]] # device key -> entity key -> Target
def find(index: Index, here: str, ref: Ref) -> Target      # raises vol.Invalid with the message
def local_key(value: Any) -> str                            # refuses "<device>."
# `by`, `builder`, `item` and `actions` turn the "may target" table of Part 2 into filters
# over the index: an alert refuses by == "alerts" or builder == "alerts"; a reaction refuses
# a target on its own device with builder == "reactions" and item == its own key; a program
# step refuses a target whose actions lack the step's. Until B adds the alerts aspect, A2
# sets by="alerts" on the keys a builder's Presets role adds, so the rule holds already.
# A2 builds Ref from 0.1.23's syntax: a reaction's device: + when: -> Ref(device, when);
# a light group's {pool: [led]} -> Ref("pool", "light_led"). C only changes the parsing.

# runtime.py: deletes the state today's setup keeps in closures
@dataclass(frozen=True, kw_only=True)
class Built:
    house: Mapping[str, Any]                            # the validated pururu: block
    builders: Mapping[str, Feature]
    index: Index
    texts: Mapping[str, str]                            # the translations' common texts
    entities: Mapping[Platform, tuple[Entity, ...]]     # copied into entry.runtime_data
    by_device: Mapping[str, tuple[PururuEntity, ...]]
    created: frozenset[str]                             # unique IDs created

type Step = Callable[[HomeAssistant, PururuConfigEntry, Built, set[str]], Awaitable[None]]
# adds to the set the entity IDs whose disabling reloads the entry, as soon as it knows
# them: a step that fails partway keeps what it added

# generated.py: deletes the sentinel `dict[str, str] | Literal["held"] | None` of today's _acted_on
@dataclass(frozen=True)
class Planned:
    items: list[generated.Item]                 # what goes in the file (unique_id, config, area)
    held: frozenset[str]                        # IDs kept out while a target is disabled
    targets: frozenset[str]                     # entity IDs the items act on

# vocabulary.py. A1 moves feature.Condition here as is, with NO_READING and _number
# (entity.reading keeps its own parsing; nothing else changes). B moves the state and numeric_state trigger
# builder here from reactions.triggers, as is, as trigger(), so aspects/notifications no
# longer imports reactions. C changes what is marked.
@dataclass(frozen=True, kw_only=True)
class Condition:
    state: str | None = None                    # PR C: text only (today str | float)
    above: float | None = None
    below: float | None = None
    equals: float | None = None                 # PR C: code only (no_power)
    def holds(self, state: State | None) -> bool | None
    # unchanged rules: a state HA restored for an entity not loaded yet is no reading (None);
    # a condition on unavailable/unknown holds while there's no reading, a missing state included
def parse(block: Mapping[str, Any]) -> Condition           # PR C
def band(value: float, above: float | None, below: float | None) -> bool   # PR C
def trigger(entity_id: str, when: Condition, *, from_: str | None = None, hold: timedelta | None = None) -> list[dict[str, Any]]
# B: moved as is; C: takes a Condition, refuses `equals`

# features/cycle: deletes the signal plumbing repeated in Running, Current and Open
class CycleSource(PururuEntity):
    def _send(self, cycle: Cycle, item: Item | None) -> None  # state, then cycle signal, then end signal
# cycle_start/cycle_end attributes stay where they are today (Running, Current); Open gets none.
```

`CycleSource` is an entity base class, as `PururuEntity` is: HA entities are classes, so this is inheritance of behaviour, not of configuration. "Composition, no inheritance" is the rule for builders, not for entities.

### Flow: validate, plan, apply

As Terraform's plan/apply: the plan is a value; validation never touches `hass`.

1. **Structure.** `CONFIG_SCHEMA` runs without `hass`. Every nested mapping is its own `vol.Schema` (the top-level `ALLOW_EXTRA` propagates into plain dicts).
2. **`_device(value)`**, which never knows its device key, in this order:
   1. each block: `mount` takes out the key of every aspect the builder offers and validates its shape; the rest goes to the builder's schema;
   2. at least one feature;
   3. until D, each `Requires`: `<capability>_from` names a feature of the device with the matching `Provides`;
   4. the aspects' checks that depend on settings: a counter whose `needs` setting is missing is refused.
3. **`CHECKS`**, at the domain level: `index = catalogue.index(devices)`, then each check runs as `check(house, index, builders)` (the builders passed in, so a check in an L0–L2 module reads them without importing the registries) and raises `vol.Invalid(msg, path=[devices, key, …])`; voluptuous prepends the path, so HA shows the right place. Each rule lives in its owner's module and is listed once in `CHECKS` (references, one real entity per device, distinct entity and generated IDs, `places.floors_exist`, areas exist, reactions', programs', alert lights' groups, messages have a `notify`).
4. **`async_setup_entry`, the prelude:** `places.async_sync`; `texts`; the index again; the generated IDs the entry owns (every `Generates` and aspect `generates`); `built = build.plan(...)`: builders' builds, then offered aspects' builds, then `_creatable`; `entry.runtime_data = built.entities`; forward to the platforms. Everything that can raise on bad data runs before forwarding.
5. **`STEPS`**, in order, each in `try/except Exception` with `_LOGGER.exception(name)`. Without the guard, a step raising after forwarding leaves the entry stuck until a restart: HA unloads a non-loaded entry without calling `async_unload_entry`.

   | Step | Does |
   |---|---|
   | events | follows state changes; `event_name` is `entity.reference` |
   | devices | `_place`, `_remove_stale` |
   | generate | `programs.plan` → `pururu/scripts/programs.yaml` (unchanged); `reactions.plan(…, scripts)` and `notifications.plan` → `automations.yaml`; adds the programs' targets once the scripts are planned, before the automations. `scripts` maps `(device key, program key)` to the script's current entity ID, or to `None` when the program is held or not generated; `generate.py` builds it from `programs.plan`'s result, so `reactions` never imports `programs` |
   | Alert2 | the `ProblemAlert`s with a message |
   | alert lights | lends and hands back lights |
   | dashboard | `/pururu` |

6. **Listener.** Reloads the entry when one of its entities is renamed; when a script or automation whose `(platform, unique_id)` is tracked in `entry.data[kind.data_key]` is renamed (one rule for every generated kind, instead of today's `_watched_items`, which lists reactions and programs only: nothing refers to a notification's automation, so its rename needs no rebuild, but one rule is simpler than a rule with an exception); when an ID a step added to the targets is disabled (once per burst).

### What `__init__.py` becomes

HA looks up `CONFIG_SCHEMA`, `async_setup`, `async_setup_entry`, `async_unload_entry` and `async_remove_entry` on the package, so they stay in `__init__.py`, and nothing else does: each is a few lines calling `lifecycle.py`. HA's convention (a reviewer opens `__init__` to see the lifecycle) is kept, without logic in it.

- `lifecycle.py`: `async_apply` (re-read the YAML, reload the entry; today's `_async_apply`), the prelude, the `STEPS` tuple and the guarded loop, unload, and remove (`places`, then `generate.async_remove`: automations then scripts, then `alert2_alerts.async_remove`).
- `listener.py`: the registry listener and `rebuild_for`, with the one rename rule.

### Generated files

- **One automations kind** (`generate.AUTOMATIONS`, file `pururu/automations/automations.yaml`, data key `automations`, Repairs issue `automations_not_included`, log word `source="reactions and notifications"`): reactions' items, then notifications'. Today two kinds share the domain `automation`: two files, two Repairs issues with the same include line, two reloads when both change, and a rename rule that missed one of them. `notifications.KIND` and its Repairs issue `notifications_not_included` with its translations go; `automations_not_included`'s title and description (en, pt-BR) stop saying "reactions' automations". `entry.data["notifications"]` stays, unread and harmless (no migration code, D13).
- **Alert2 keeps its own engine:** its identity is the alert's name and its reload is a third party's.
- **`generated.Kind` keeps assuming** the registry platform is the domain. A kind that breaks that (none planned) adds `platform` and `ids()` when it arrives.

### Growing

| Adding | Files | List that gains a line |
|---|---|---|
| A feature | `features/x.py` composing its roles; names and icons of its own keys; `docs/features/x.mdx`, `docs.json` | `FEATURES` |
| An aspect | `aspects/x.py`; its translations, once; its page in `docs/concepts/`; a role in `roles.py` if none fits | `ASPECTS` (and `CHECKS` for its rules) |
| A device key | its module (schema, build, roles); its docs | `DEVICE_KEYS`, `CHECKS` |
| A role | a dataclass in `roles.py`; its rules in the contract test | none |
| A generated kind | a `Kind` and its part of the generate step in `generate.py`; `plan()` in the owner | none |
| A condition operator | `vocabulary.py` | none |

A new feature is a new cycle source or a new kind of real entity; a thing on a power plug is an `appliance`.

### Left out on purpose

Each waits for a second concrete need: an `Output`/`Setup` framework with declared reads; a `Lendable` Protocol (a port with one adapter); Alert2 on the shared `Kind` engine; a factory for plug-driven features; `Kind.platform`; a per-operator trigger flag table (only `equals` is code-only); dependency injection, plugin discovery, stable error codes; pure reducers for the alert lights; an `EntryData` TypedDict.

## Part 4: programs

Lands in **PR D**, after B and before C.

### The model

**A cycle is a run of a program, and a program has phases.** Today three names cover pieces of that: the appliance's `running` (a run), `modes` (the purifier's gelar and quente, each a kind of run) and `phases` (the washer's washing and spinning, stages of a run), next to `programs` (ours, run by pururu). One type, `Program`, replaces them:

| | Detected | Executable |
|---|---|---|
| **pururu knows it runs** | from a reading: a band of the power, with `on_delay`/`off_delay` | because it runs it: the steps in `sequence` |
| **Can be started** (`then:`, a program step) | no | yes |
| **Today** | the appliance's `running`, `modes`, `phases` | `programs` |

- **A phase is a program without phases.** It takes every field a program takes (`name`, the reading fields, `statistics`) except `phases`. Depth is fixed: program → phase, nothing deeper.
- **The appliance's `running_program`** is a detected program with a fixed key, required. It is the appliance running at all; its phases are what today's `modes` and `phases` measure. How a cycle is measured may change later (it's the power today); the fixed key keeps that change local.
- **`programs:`**, with two groups, `detected:` and `executable:`, each a map of key → `Program`. The group says how the program runs, so its items are validated by that group's schema (the reading fields, or `sequence`).
- **Scope (D22).** In a feature's block, `programs:` sees only that feature: a detected program reads the feature's reading. At the device, `programs:` sees the device's features: an executable program acts on their entities and may run a feature's executable program. Only an executable program can be started, and one program runs another only from the device to a feature, so there are no call cycles.

### In the YAML

```yaml
laundry_washer:
  appliance:
    power: sensor.washer_plug_power
    running_program:                  # required: the appliance running
      above: 4
      on_delay: {minutes: 1}
      off_delay: {minutes: 2}
      statistics: {cycles: [today, month]}
      phases:
        heating: {name: Aquecendo, above: 1000}
        spinning: {name: Centrifugando, above: 50, below: 1000, on_delay: {minutes: 3}}
    programs:                         # optional: more detected programs of the appliance
      detected:
        cotton: {name: Algodão, above: 1500, on_delay: {minutes: 5}}   # a program its power alone tells apart

pool:
  switches:
    pump: {entity: switch.pool_pump, name: Bomba}
  programs:                           # at the device
    executable:
      clean:
        name: Limpar
        sequence: [{turn_on: switch_pump}, {delay: {hours: 2}}, {turn_off: switch_pump}]
```

`running_program` needs no check inside `programs:`: it has its own key.

### What goes

- The features `modes` and `phases`, with `features/modes/` and `features/phases.py`.
- `cycle_from`, the roles `Provides` and `Requires`, and the capability check. (C never adds `inherits`: Part 2's #5 is solved here.)
- `modes: modes:` and the phase bands' `for`: a phase uses `on_delay`/`off_delay`, absent meaning at once, as every program.
- The appliance's `running:` block and its `threshold`: `running_program` uses `above`/`below`.
- The device key `programs:` as a flat map: its items move under `programs: executable:`.

### In the code

- **`features/cycle/program.py`** (L1, shared machinery): the detected `Program` schema, the detector (today's band logic of `phases.py` and the one-at-a-time arbitration and delays of `modes/current.py`, merged), and its entities (on `CycleSource`). The appliance builds its `running_program` with it.
- **`aspects/programs.py`** (L2): mounts `programs:` in the block of a builder with the `Programs` role, and is the device key `programs` (today's top-level `programs.py`, moved: the scripts, `plan()`, `Runs`). It imports `features/cycle`, as the L2 row allows.
- **A new role, `Programs(reading: str, energy: str | None = None)`:** the settings a detected program in this builder reads (the appliance: `power`, `energy`). It replaces `Provides`/`Requires`.
- **Statistics:** each program and phase is an item with `Counters` (`runtime`, `cycles`, and `energy` when the builder has an energy setting); the statistics aspect of B meters them, as it meters today's modes.
- `FEATURES` becomes `appliance`, `door`, `window`, `switches`, `lights`; `DEVICE_KEYS` stays `alerts`, `programs`, `reactions`.

### Decided when D starts

Small choices that don't change the model:

1. **Overlapping phases.** Today phases pick the first listed band that holds; modes refuse overlapping bands and keep the running one until its `off_delay`. One rule for all phases.
2. **Entity IDs and names of phases** (today `mode_<key>_*`, `mode_current`, `mode_last`, `phase_current`), and the current phase's state when none holds (today `defaults.stopped`/`running` for phases, `idle` for modes). The appliance's own entities (`appliance_running`, its totals and meters) keep their IDs.

### Not in 0.2.0

- `phases` on an executable program (its steps could be its phases): refused until needed.
- A detected program from another source than a band of a reading (a smart washer's program sensor).
- A device's step running a feature's executable program: no feature offers one yet; the step's syntax comes with the first.
- A door's opening as a detected program.

## The whole contract, 0.2.0

After all seven PRs. Lines marked `←` change from 0.1.23, with the PR that changes them.

```yaml
pururu:
  config:
    notify: notify.mobile_app_celular       # every message's default: one or a list
    events: [state_changed, reading]        # ← was top-level events (C)
    alerts:
      lights:
        groups:
          default: [sala.light_teto]        # ← was {sala: [teto]} (C)
          externas: [sala.light_teto, sala.light_abajur]
        high: {turn_on: {color_name: red, effect: breathe}, repeat: {seconds: 15}}   # ← any time period (C)
        resolved: {turn_on: {color_name: green}, lasts: {minutes: 2}}                # ← was for: {seconds: 120} (C)

  floors:
    terreo: {name: Térreo, level: 0, icon: mdi:home-floor-0, aliases: [embaixo]}
  areas:
    lavanderia: {name: Lavanderia, floor: terreo, icon: mdi:washing-machine}
    entrada: {name: Entrada, floor: terreo}

  devices:
    laundry_washer:
      name: Máquina de lavar
      area: lavanderia
      # features, with their aspects mounted
      appliance:
        power: sensor.washer_plug_power
        energy: sensor.washer_plug_energy
        running_program:                    # ← was running (D): a detected program
          above: 4                          # ← was threshold (D)
          on_delay: {minutes: 1}
          off_delay: {minutes: 2}
          statistics:                       # ← was the appliance's runtime/cycles (D)
            runtime: [today, week, month, year]
            cycles: [today, week, month, year]
          phases:                           # ← was the phases feature (D)
            heating: {name: Aquecendo, above: 1000}
            spinning: {name: Centrifugando, above: 50, below: 1000, on_delay: {minutes: 3}}   # ← was for (D)
        statistics:
          idle_energy: [today, month]       # the appliance's own counter, outside any program
        alerts:                             # ready-made alerts
          offline:
          long_cycle: {for: {hours: 3}, lights: default}   # ← was lights: true (C)
        notifications:                      # ready-made notifications
          finished: {message: Roupa pronta!}
      # device keys
      alerts:
        stuck:
          name: Travada
          when: appliance_running
          state: "on"                       # ← was is (C)
          for: {hours: 4}
          priority: medium
          lights: default                   # ← was lights: true (C)
          message: Rodando há 4h!           # ← was notify: {message, …} (C)
          done_message: Parou.              # ← was notify: {…, done_message} (C)
        overload: {name: Sobrecarga, when: appliance_power, above: 2500, for: {minutes: 1}, priority: high, lights: externas}

    water_filter:
      name: Purificador
      appliance:
        power: sensor.filter_plug_power
        energy: sensor.filter_plug_energy
        running_program:                    # ← was running (D)
          above: 2.9
          on_delay: {seconds: 1}
          off_delay: {minutes: 1}
          phases:                           # ← was the modes feature (D)
            gelar:
              name: Gelar
              above: 4
              below: 150
              on_delay: {seconds: 10}
              off_delay: {minutes: 3}
              statistics: {runtime: [today, month], cycles: [today, month], energy: [today, month]}
            quente: {name: Água quente, above: 150, below: 400, on_delay: {seconds: 30}, off_delay: {seconds: 30}}

    porta_frente:
      name: Porta da frente
      area: entrada
      door:
        contact: binary_sensor.porta_frente
        match: {seconds: 5}
        statistics: {openings: [today, month], open_time: [today]}
        event_entities:                     # ← was events (C)
          - entity: event.porta_frente_access
            types: {access_granted: opening, access_denied: denied}
            fields: {who: actor, how: authentication, direction: direction}
          - entity: event.porta_frente_doorbell
            types: {ring: ring}
      alerts:
        left_open: {name: Aberta, when: door_open, state: "on", for: {minutes: 10}}   # ← was is (C)

    janela_quarto:
      name: Janela do quarto
      window:
        contact: binary_sensor.janela_quarto
        statistics: {open_time: [today, week]}

    garden:
      name: Jardim
      switches:
        valve: {entity: switch.garden_valve, name: Válvula}
      programs:
        executable:                         # ← was programs (D)
          water:
            name: Regar
            sequence: [{turn_on: switch_valve}, {delay: {minutes: 20}}, {turn_off: switch_valve}]
            statistics: {runtime: [month], cycles: [month]}
      reactions:
        afternoon:
          name: Tarde
          at: "13:00"
          then: water                       # an executable program of this device
          retry: {times: 3, every: {hours: 1}}
          statistics: {triggered: [month]}
        dusk: {name: Anoitecer, sun: sunset, offset: {minutes: -30}}

    sala:
      name: Sala
      lights:
        teto: {entity: light.sala_teto, name: Teto}
        abajur: {entity: switch.sonoff_abajur, name: Abajur}
      programs:
        executable:                         # ← was programs (D)
          blink:
            name: Piscar
            sequence: [{turn_on: light_teto}, {delay: 2}, {turn_off: light_teto}]
      reactions:
        teto_on: {name: Teto acendeu, when: light_teto, to: "on"}
        washer_done:
          name: Lavadora terminou
          when: laundry_washer.appliance_running   # ← was device: laundry_washer + when: appliance_running (C)
          from: "on"
          to: "off"
          then: blink                              # its own program, always
          message: A roupa terminou.
          notify: [notify.mobile_app_celular, notify.mobile_app_tablet]
        door: {name: Porta abriu, entity: binary_sensor.porta_lavanderia, to: "on", for: {minutes: 5}}

automation pururu: !include_dir_merge_list pururu/automations
script pururu: !include_dir_merge_named pururu/scripts
alert2:
  alerts: !include_dir_merge_list pururu/alert2
```

## Rejected alternatives

### The contract

- **C1. Aspects at the device, by entity key** (`statistics: {appliance_runtime_total: [month]}`): one rule for every counter, but long names, and the appliance spread over several blocks.
- **C2. Aspects at the device, by feature** (`statistics: {appliance: {runtime: …}}`, `notifications: {appliance: …}`): the block's matrix transposed, no less coupled (D6); depth changes with the namespace (`mode: {gelar: …}`); a namespace and an alert key share a level in `alerts:`. The first notifications design used it for ready-made notifications; 0.1.23 shipped them in the block instead.
- **C3. A `features:` level in each device; a device-level wiring block**: the extra level buys nothing, and after D nothing needs wiring (a program sits in the block it reads).
- **C4. HA's full trigger schema in reactions** (`triggers: [{trigger: …}]`): pururu would lose validating references and following renames.
- **C5. `notify` as the text and `to` as where**: `notify` already means where in `config` and in reactions, and HA's actions are `notify.*`; the text moves, not the target.
- **C6. `appliance.running` as the reference form**: reads like an entity ID.

### How a builder declares what it is

- **A. One wide record**: today's 14 fields plus `catalogue`, `inherits` and `generates`. Every builder half uses it, invalid combinations pass silently, each need adds a field.
- **B. Grouped fields** (`wiring`, `standing`, `items`, `catalogue`): easier to read, but fixed partitions, and a new role still edits `Feature`.
- **C. Two types, `Feature` and `DeviceKey`**: splits along the wrong line (what varies is roles, not the device-key/feature split), and every walk over builders becomes a union.
- **D. Abstract base class plus role mixins** (`class Appliance(Feature, CycleProvider, Counted)`): inheritance carrying data, one instance per class, MRO; the coupling composition avoids.
- **E. `typing.Protocol` roles checked with `isinstance`**: a runtime-checkable Protocol only checks an attribute exists, so a typo means "hasn't the role", silently.
- **F. Roles (chosen)**: see Part 3.

### Programs

- **P1. Keep `modes`, `phases` and `running` as they are**: nothing breaks, but it keeps `cycle_from` and the capability roles for one case, and three names for pieces of one idea (a run of a program with phases).
- **P2. One `programs` list at the device, with a `type` per item**: a detected program there must say which feature's reading it reads (`from:`, `cycle_from` again), and the rules depend on the item's type. The groups `detected`/`executable` keep the discriminator without that.
- **P3. Modes and executable programs as one thing**: an executable program is ours, run by pururu; a mode is a stage of the appliance's run. They share the cycle, not the kind.
- **P4. Programs containing programs (a tree)**: depth without limit. Fixed at program → phase.
- **P5. `running` inside `programs:`**: needs a check that it's there; a fixed `running_program` key needs none.

## Compatibility

pururu has one user, its author. So:

- No aliases, no deprecation Repairs issue, no migration code, no "From 0.1.x" sections; the existing "From 0.1.14 and before" section goes in PR C.
- An old key is voluptuous' `extra keys not allowed`, with HA's file and line.
- One manual step, in PR B (below).
- No entity ID or unique ID changes in A1–C; D changes those of today's `modes` and `phases` (D20). Everything else keeps its history, statistics and dashboards.
- A1 sets the version to 0.2.0: the Release workflow tags v0.2.0 with A1 alone, and A2a–C land on `main` under the same version. That is accepted: 0.2.0 is the sum of the seven PRs.

## PRs

Each leaves the whole suite green. Before merging A1, which bumps the version, check `main` and the releases (two PRs bumping to the same version: the second never ships).

| PR | What | Release |
|---|---|---|
| A1 | ID snapshot; move code out of `__init__.py`, plus three mechanical changes | sets 0.2.0 (tagged) |
| A2a | The lifecycle: entry points only in `__init__`, `lifecycle.py`, `listener.py`, `Built`, `STEPS` and their guard, the one rename rule | stays 0.2.0 |
| A2-layout | Move the modules into one folder per layer (D21), nothing else | stays 0.2.0 |
| A2b | The model: roles, `resolve.py` and the `Index`, `CHECKS` at the domain level, `Planned` and each `plan()` in its owner | stays 0.2.0 |
| B1 | `CycleSource`; `trigger` to the vocabulary | stays 0.2.0 |
| B2 | The statistics aspect: `Aspect`, `mount`, `Counters` | stays 0.2.0 |
| B3 | The alerts aspect; `alerts` becomes a device key | stays 0.2.0 |
| B4 | The notifications aspect; one automations kind; the whole layer table | stays 0.2.0 |
| D | Part 4: programs | stays 0.2.0 |
| C | Part 2: the vocabulary | stays 0.2.0 |

**Why this order.** Each PR builds on the previous one without redoing it:
- **D after B:** programs and phases get their statistics from B's aspect (`Counters` on items) and their entities from B's `CycleSource`. Before B, D would build meters the old way for B to move.
- **D before C:** C applies the vocabulary (references, `state`, `notify`, `lasts`) once, to the final shape; `threshold` → `above` comes with D's `running_program`, and C never adds `cycle_from`'s `inherits`.
- **What D still replaces:** A2b's `Provides`/`Requires` (two small roles and the capability check, needed to express today's `cycle_from`) and B's role tuples for `modes`/`phases`. That's a few dozen lines, against moving statistics twice in any other order.

**A1, moves only.**
1. First `tests/test_ids.py` and `tests/fixtures/house.yaml`: the whole contract above written in 0.1.23's syntax and extended to every counter × period on every namespace, every ready-made alert and every ready-made notification. The test pins the sorted `(platform, unique_id)` of every entity and the `(domain, ID)` of every generated item. It guards against `_remove_stale` deleting customisations when a key fails to build. Only additions may update it, except D, which updates it on purpose for today's `modes` and `phases`; D and C rewrite the fixture in their syntax, and nothing else in the snapshot may change.
2. Split `__init__.py` into `schema`, `catalogue`, `checks`, `build`, `devices` and `generate` without changing code; `texts.py`; `feature.Condition`, `NO_READING` and `_number` moved to `vocabulary.py` as is; `runtime.py` holding only `PururuConfigEntry` (`Built` and `Step` come in A2). The three mechanical changes: `builders()` replaces the `ChainMap`; `ALERT2` moves from `alert2_alerts.py` to `const.py` and `PRIORITIES` from `features/alerts.py` to `feature.py`, so L0 and L1 stop importing outputs.
3. Docs: CLAUDE.md's Architecture, `docs/develop/architecture.mdx`.

**A2 is two PRs**, independent of each other, so each stays reviewable.

**A2a, the lifecycle.** `__init__.py` with only HA's entry points (D23), `lifecycle.py` and `listener.py`; `Built`; `STEPS`, each owned by its output module (`async_step`), the guard, its test and an autouse fixture failing a test on an unexpected guard log; the one rename rule; `generated.async_issue` shared by the kinds and Alert2 (warn once while active); `entity.key` and `entity.reference` (`f"{device.key}.{device.qualified(key)}"`, set in `_identify`), `entity.other_holder`; the import test's A2 rules. Plan: `docs/superpowers/plans/2026-09-29-refactor-a2a-lifecycle.md`.

**A2-layout, the folders (D21).** Right after A2a, before A2b, so the PRs that follow start in the new tree. A pure move (`git mv`, imports rewritten), proved as A1 was: the unchanged suite, `tests/test_ids.py`, and the import test turned into rules per folder. The layout:

```
custom_components/pururu/
├── __init__.py, config_flow.py, const.py, sensor.py, binary_sensor.py, switch.py, light.py
├── core/          runtime, feature, vocabulary, entity, texts, messages, files, generated (A2b adds roles, resolve)
├── features/      unchanged
├── device_keys/   programs, reactions, and DEVICE_KEYS
├── outputs/       events, dashboard, places, devices, alert2_alerts, alert_lights
└── setup/         schema, catalogue, checks, build, generate, lifecycle, listener
```

`notifications.py` goes to `device_keys/` until B moves it to `aspects/`. Sonar suppressions and docs that name a path follow.

**A2b, the model.** `roles.py` and `Feature` with roles; `resolve.py`, `Index`, `Target`, with `Ref` built from 0.1.23's syntax (a reaction's `device:` + `when:`, a light group's `{device: [key]}`), so the old resolvers go now and C only changes the parsing; `CHECKS` at the domain level with paths (error texts and their order may change); `Planned`, and each `plan()` in its owner (`programs.py`, `reactions.py`, `notifications.py`); `Built` gains `builders` and `index`. Docs: `writing-a-feature.mdx`, `testing.mdx`.

**B, the aspects**, in four PRs (B1 to B4 above), split by concern when B started: each is smaller to review and merges on its own, and the owner updates only once 0.2.0 is finished, so the steps between don't matter to them. `aspects/` (statistics, alerts with the `ALERTS` device key, notifications); `features/presets.py`, `features/alerts.py`, `features/elapsed.py`, `features/cycle/statistics.py` and `notifications.py` move there; generic `mount`; `alerts` from `FEATURES` to `DEVICE_KEYS`; one automations kind, and `programs.KIND` moved to `generate.SCRIPTS` next to it (`tests/test_generated.py` reads both from `generate`); the statistics translations owned by the aspect (`<counter>_<period>`, `item_<counter>_<period>` with `{item}`), written so the names shown don't change; `CycleSource`; the contract test's role and aspect rules; the import test's full table; `trigger()` moved to `vocabulary.py`; `presets.validate`'s redirect "{name} is now a notification" goes (D13). Docs: `docs/features/alerts.mdx` to `docs/concepts/alerts.mdx`, a statistics concept page, `docs.json`, `configuration.mdx`.

The manual step, in the PR's text: before updating, remove every `notifications:` block and reload pururu (their automations and registry entries go; the new kind would otherwise find them registered under the old data key and treat them as the user's). Update, delete `pururu/automations/reactions.yaml` and `pururu/automations/notifications.yaml` (HA loads every file in the folder, and they'd repeat `automations.yaml`'s IDs), restart. Put the `notifications:` blocks back and reload.

**D, programs.** Part 4 whole: `features/cycle/program.py`, `aspects/programs.py`, the `Programs` role, `running_program`, `programs: {detected, executable}`, phases as programs; `modes`, `phases`, `cycle_from`, `Provides`, `Requires` go; the two choices of "Decided when D starts". Docs: `docs/features/modes.mdx` and `phases.mdx` go, a programs concept page replaces `concepts/programs.mdx`, `appliance.mdx`, `docs.json`, `configuration.mdx`.

**C, the vocabulary.** Part 2 whole: references with `device.key` and `local_key`; `vocabulary` as marked above; `is` → `state`; `notify` and flat texts; `lasts` and time periods; the small ones, `places`' names included; the "From 0.1.14 and before" section of `docs/concepts/programs.mdx` goes. Tests' helpers, every feature page, `configuration.mdx`, `troubleshooting.mdx`, the fixture rewritten.

## Tests

1. **ID snapshot** (A1, above).
2. **Contract** (`tests/test_features.py`), over `builders() × ASPECTS`: namespaces distinct; `FEATURES` and `DEVICE_KEYS` keys disjoint; the role rules; names (en, pt-BR) and icons, a builder's own keys per builder and an aspect's once; `example` plus each offered aspect's `example` validates and builds; the builder's schema alone refuses each offered aspect's key (no clash); a `Configured` builder offers no block-level aspect; `f"{c}_total"` is one of the builder's keys, and a counter without its needed setting is refused; each `Happening` generates its automation; kinds' data keys distinct and none is `floors` or `areas`; every `FEATURES` key has `docs/features/<key>.mdx` and a `docs.json` entry; a device with only `alerts` is refused.
3. **Imports** (`tests/test_code.py`): the layer table and the preload names.
4. **Units:** `resolve` (every row of the reference table); `vocabulary` (`holds`, `band`, `trigger`, `equals` refused by `trigger`); `repeat: 0` refused; a reaction's `to: 1` and an alert's `state: 1` match the same states.
5. **Integration:** the existing suite, edited with the behaviour; the guard's test (a step raising, the next reload loads the entry).
6. **Programs (D):** the appliance without `running_program` is refused; `phases` inside a phase is refused; an item of `detected` with `sequence`, or of `executable` with reading fields, is refused; a feature's program referencing another feature is refused; `then:` naming a detected program is refused; a device's program may act on its features; today's purifier and washer behaviours (the modes' one-at-a-time arbitration and delays, the phases' `seen`) hold under the new names.

## Open decisions

- **The `STEPS` guard** trades failing loudly for availability; the autouse fixture keeps bugs visible in tests. Keep unless it hides a real failure.
- A reaction with several triggers (`when:` as a list).
- An alert's `notify` as Alert2's per-alert `notifier`, with `config: notify` as its default.

## Sources

The comparison with the community that shaped Parts 1 and 2: HA's [ADR-0007](https://github.com/home-assistant/architecture/blob/master/adr/0007-integration-config-yaml-structure.md) and [ADR-0010](https://github.com/home-assistant/architecture/blob/master/adr/0010-integration-configuration.md), the [2024.10 automation syntax](https://www.home-assistant.io/blog/2024/10/02/release-202410/), the [template](https://www.home-assistant.io/integrations/template/) and [Threshold](https://www.home-assistant.io/integrations/threshold/) integrations, ESPHome's [automations](https://esphome.io/automations/actions/) and [binary sensor filters](https://esphome.io/components/binary_sensor/), [Alert2](https://github.com/redstone99/hass-alert2), and [Powercalc's YAML migration](https://docs.powercalc.nl/configuration/migration/new-yaml-structure/).
