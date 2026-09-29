# Refactor A1: moves — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin every entity and generated ID with a snapshot, then move the code out of `custom_components/pururu/__init__.py` into modules with one job each, without changing behaviour, and set the version to 0.2.0.

**Architecture:** A pure move. Each function keeps its body; only its module, and for a function now used across modules its leading underscore, change. The existing tests stay as they are and must pass unchanged. A new snapshot test and a per-function coverage comparison prove nothing moved out from under the tests.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3, voluptuous, pytest (+ pytest-homeassistant-custom-component, pytest-cov), ruff, mypy strict, uv.

**Spec:** `docs/superpowers/specs/2026-09-29-yaml-contract-coherence-design.md` — PR A1, and Part 3 (package, layers).

## Global Constraints

- Behaviour identical: every existing test passes **unchanged**. No test is deleted, skipped, loosened or edited in this PR; the only test change is the new `tests/test_ids.py` and its fixtures.
- Coverage kept per function, not just in total: after the moves, no function has more missing lines or branches than before (Task 5 compares them by name).
- Every entity ID, unique ID and generated ID identical (the snapshot of Task 1).
- `uv run pytest` green at every commit: it includes ruff, ruff format, mypy strict, hassfest and the quality scale (`tests/test_code.py`).
- No `condition.py`, `trigger.py`, `repairs.py`, `config.py` or `diagnostics.py` module: HA preloads those names.
- The version in `custom_components/pururu/manifest.json` becomes `0.2.0` (Task 5); `python3 release.py check` passes.
- Commits end with the two attribution lines:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM`.

## Review Focus

1. **A function moved with a changed body.** A move that "tidies" a line changes behaviour the suite may not catch. Diff each moved function against `main` (Task 5, step 3).
2. **Import cycles at load.** `features/alerts.py` imports `alert2_alerts` today; `alert2_alerts` will import `features/alerts`. Task 2 cuts the first edge before Task 4 adds the second.
3. **`builders()` order.** Today's `ChainMap(DEVICE_KEYS, FEATURES)` iterates `FEATURES` first; `{**FEATURES, **DEVICE_KEYS}` must too, or the order in which entities are built, and in which a device's checks report, changes. No ID depends on it, so Task 3 step 2 checks it by reading.
4. **A test that mutates `FEATURES` at runtime** (`tests/test_init.py`'s `demo` fixture adds `gauge`, `echo`…). `builders()` must read `FEATURES` at call time, never copy it at import.
5. **Coverage lost silently.** A function that only ran through a path that moved could lose coverage without a failing test. Task 5 compares coverage per function.

---

## File structure

| File | After A1 |
|---|---|
| `custom_components/pururu/__init__.py` | HA entry points only: `CONFIG_SCHEMA` (imported), `async_setup`, `_async_apply`, `async_setup_entry`, `_rebuild_for`, `async_unload_entry`, `async_remove_entry` |
| `runtime.py` (new) | `PururuConfigEntry` |
| `vocabulary.py` (new) | `NO_READING`, `_number`, `Condition` (from `feature.py`) |
| `texts.py` (new) | `Texts`, `FALLBACK_LANGUAGE`, `async_texts` (from `features/presets.py`) |
| `catalogue.py` (new) | `builders()`, `entity_keys()`, `referable()` |
| `checks.py` (new) | the device checks and the house checks |
| `schema.py` (new) | `_device`, `_feature_block`, `CONFIG_SCHEMA` |
| `build.py` (new) | `build`, `_inputs`, `creatable`, `_holder` |
| `devices.py` (new) | `place`, `remove_stale` |
| `generate.py` (new) | `owned`, `watched_items`, `scripts`, `_acted_on`, `automations`, `_watched`, `_started` |
| `alert2_alerts.py` | gains `items` (today's `_alert2_alerts`) |
| `events.py` | gains `watched` (today's `_event_devices`) |
| `const.py` | gains `ALERT2` (from `alert2_alerts.py`) |
| `feature.py` | loses `Condition`, `NO_READING`, `_number`; gains `PRIORITIES` (from `features/alerts.py`) |
| `sensor.py`, `binary_sensor.py`, `switch.py`, `light.py` | import `PururuConfigEntry` from `.runtime` |
| `tests/test_ids.py`, `tests/fixtures/house.yaml`, `tests/fixtures/house_ids.json` (new) | the ID snapshot |

Leave everything else where it is: `programs.KIND` moves in PR B, not here.

---

### Task 1: ID snapshot and coverage baseline

**Files:**
- Create: `tests/fixtures/house.yaml`
- Create: `tests/fixtures/house_ids.json` (generated in step 4)
- Create: `tests/test_ids.py`
- Create: `.superpowers/a1/.gitignore` (content `*`) and `.superpowers/a1/coverage-before.json` (not committed)

**Interfaces:**
- Produces: `tests/test_ids.py::test_ids_are_pinned`, run by every later task.

- [ ] **Step 1: Record the coverage baseline, before any change**

```bash
mkdir -p .superpowers/a1 && printf '*\n' > .superpowers/a1/.gitignore
uv run pytest --cov --cov-branch --cov-report=json:.superpowers/a1/coverage-before.json -q
```

Expected: the whole suite passes; `.superpowers/a1/coverage-before.json` exists.

- [ ] **Step 2: Write the house, in 0.1.23's syntax**

Every feature, every counter × period on every namespace, every ready-made alert and notification, cross-device references, light groups. `tests/fixtures/house.yaml`:

```yaml
config:
  notify: notify.mobile_app_phone
  alerts:
    lights:
      groups:
        default: {sala: [teto]}
        externas: {sala: [teto, abajur]}
events: [state_changed, reading]
floors:
  terreo: {name: Térreo, level: 0}
areas:
  lavanderia: {name: Lavanderia, floor: terreo}
  entrada: {name: Entrada, floor: terreo}
devices:
  laundry_washer:
    name: Máquina de lavar
    area: lavanderia
    appliance:
      power: sensor.washer_plug_power
      energy: sensor.washer_plug_energy
      running: {threshold: 4, on_delay: {minutes: 1}, off_delay: {minutes: 2}}
      statistics:
        runtime: [today, week, month, year]
        cycles: [today, week, month, year]
        idle_energy: [today, week, month, year]
      alerts:
        offline:
        no_power:
        long_cycle: {for: {hours: 3}, lights: true}
        no_cycle: {for: {days: 2}}
      notifications:
        finished:
    phases:
      cycle_from: appliance
      sensor: sensor.washer_plug_power
      defaults: {stopped: idle, running: washing}
      bands:
        heating: {above: 1000}
        spinning: {above: 50, below: 1000, for: {minutes: 3}}
    alerts:
      stuck:
        name: Travada
        when: phase_current
        is: spinning
        for: {hours: 1}
        priority: medium
        lights: externas
        notify: {message: Travada!, done_message: Destravou.}
      overload: {name: Sobrecarga, when: appliance_power, above: 2500, for: {minutes: 1}, priority: high}
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
        gelar: {name: Gelar, above: 4, below: 150, on_delay: {seconds: 10}, off_delay: {minutes: 3}}
        quente: {name: Água quente, above: 150, below: 400, on_delay: {seconds: 30}, off_delay: {seconds: 30}}
      statistics:
        runtime: [today, week, month, year]
        cycles: [today, week, month, year]
        energy: [today, week, month, year]
  porta_frente:
    name: Porta da frente
    area: entrada
    door:
      contact: binary_sensor.porta_frente
      match: {seconds: 5}
      statistics:
        openings: [today, week, month, year]
        open_time: [today, week, month, year]
      events:
        - entity: event.porta_frente_access
          types: {access_granted: opening, access_denied: denied}
          fields: {who: actor, how: authentication, direction: direction}
        - entity: event.porta_frente_doorbell
          types: {ring: ring}
  janela_quarto:
    name: Janela do quarto
    window:
      contact: binary_sensor.janela_quarto
      statistics:
        openings: [today, week, month, year]
        open_time: [today, week, month, year]
  pool:
    name: Piscina
    switches:
      pump: {entity: switch.pool_pump, name: Bomba}
    programs:
      clean:
        name: Limpar
        sequence:
          - turn_on: switch_pump
          - delay: {hours: 2}
          - turn_off: switch_pump
        statistics:
          runtime: [today, week, month, year]
          cycles: [today, week, month, year]
    reactions:
      morning:
        name: Manhã
        at: "08:00"
        then: clean
        retry: {times: 2, every: {hours: 1}}
        statistics: {triggered: [today, week, month, year]}
  sala:
    name: Sala
    lights:
      teto: {entity: light.sala_teto, name: Teto}
      abajur: {entity: switch.sonoff_abajur, name: Abajur}
    reactions:
      washer_done:
        name: Lavadora terminou
        device: laundry_washer
        when: appliance_running
        from: "on"
        to: "off"
      night: {name: Noite, at: "22:00", message: Hora de apagar as luzes.}
```

- [ ] **Step 3: Write the test**

`tests/test_ids.py`:

```python
"""Every ID the whole house creates, pinned: a refactor that loses or renames one fails here.

`_remove_stale` deletes the registry entries of whatever isn't built, and with them
the user's customisations. PURURU_UPDATE_IDS=1 rewrites the snapshot; do it only
for IDs a change adds, never to accept one that moved or went.
"""

import json
import os
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import yaml

from helpers import DOMAIN, setup

FIXTURES = Path(__file__).parent / "fixtures"
HOUSE = yaml.safe_load((FIXTURES / "house.yaml").read_text())
SNAPSHOT = FIXTURES / "house_ids.json"
# The entry's data keys holding the IDs of generated scripts and automations
GENERATED = ("scripts", "automations", "notifications")


def ids(hass: HomeAssistant) -> dict[str, list[list[str]]]:
    """The entry's entities as (platform, unique ID), and its generated items as (data key, ID), sorted."""
    [entry] = hass.config_entries.async_entries(DOMAIN)
    registry = er.async_get(hass)
    entities = sorted(
        [registered.domain, registered.unique_id]
        for registered in er.async_entries_for_config_entry(registry, entry.entry_id)
    )
    generated = sorted(
        [key, unique_id] for key in GENERATED for unique_id in entry.data.get(key, [])
    )
    return {"entities": entities, "generated": generated}


async def test_ids_are_pinned(ha: HomeAssistant) -> None:
    """The whole house builds exactly the pinned IDs, no more, no fewer."""
    assert await setup(
        ha,
        HOUSE["devices"],
        floors=HOUSE["floors"],
        areas=HOUSE["areas"],
        events=HOUSE["events"],
        config=HOUSE["config"],
    )
    found: dict[str, Any] = ids(ha)
    if os.environ.get("PURURU_UPDATE_IDS") == "1":
        SNAPSHOT.write_text(json.dumps(found, indent=1) + "\n")
    assert found == json.loads(SNAPSHOT.read_text())
```

- [ ] **Step 4: Generate the snapshot and read it**

```bash
PURURU_UPDATE_IDS=1 uv run pytest tests/test_ids.py -n 0 -q
```

Expected: PASS. If `setup` returns False, the fixture is invalid: read HA's log line in the output and fix `house.yaml` (never the code) until it validates.

Then open `tests/fixtures/house_ids.json` and check it holds, at least: `binary_sensor` `pururu_laundry_washer_appliance_running`, the four `appliance_alert_*`, `alert_stuck`, `alert_overload`; `sensor` `pururu_laundry_washer_appliance_runtime_today` … `_idle_energy_year`, `pururu_laundry_washer_phase_current`, `pururu_water_filter_mode_gelar_energy_year`, `pururu_porta_frente_door_last_opened_by`, `_last_denied`, `_last_ring`, `pururu_pool_program_clean_cycles_year`, `pururu_pool_reaction_morning_triggered_year`, `pururu_sala_reaction_washer_done_triggered_total`; `switch` `pururu_pool_switch_pump`; `light` `pururu_sala_light_teto`, `pururu_sala_light_abajur`; generated `["scripts", "pururu_pool_program_clean"]`, `["automations", "pururu_pool_reaction_morning"]`, `["automations", "pururu_sala_reaction_washer_done"]`, `["automations", "pururu_sala_reaction_night"]`, `["notifications", "pururu_laundry_washer_appliance_notification_finished"]`. A missing one means the fixture doesn't enable it: fix the fixture and regenerate.

- [ ] **Step 5: Run it as the check it will be**

```bash
uv run pytest tests/test_ids.py -n 0 -q
```

Expected: PASS without the variable.

- [ ] **Step 6: Commit**

```bash
git add tests/test_ids.py tests/fixtures/house.yaml tests/fixtures/house_ids.json
git commit -m "tests: pin every ID of the whole house (refactor A1)"
```

---

### Task 2: Leaf moves: `runtime`, `vocabulary`, `texts`, `ALERT2`, `PRIORITIES`

**Files:**
- Create: `custom_components/pururu/runtime.py`, `custom_components/pururu/vocabulary.py`, `custom_components/pururu/texts.py`
- Modify: `__init__.py` (the `PururuConfigEntry` alias), `sensor.py`, `binary_sensor.py`, `switch.py`, `light.py`, `feature.py`, `const.py`, `alert2_alerts.py`, `features/alerts.py`, `features/presets.py`, `features/elapsed.py`, `features/appliance/alerts.py`, `alert_lights.py`

**Interfaces:**
- Produces: `runtime.PururuConfigEntry`; `vocabulary.NO_READING`, `vocabulary.Condition`; `texts.Texts`, `texts.async_texts`; `const.ALERT2`; `feature.PRIORITIES`. Later tasks import these names from these modules.

- [ ] **Step 1: `runtime.py`**

```python
"""What an entry of pururu carries at runtime: the entities each platform adds."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.helpers.entity import Entity

type PururuConfigEntry = ConfigEntry[dict[Platform, list[Entity]]]
```

In `__init__.py`, delete the `type PururuConfigEntry = …` line and add `from .runtime import PururuConfigEntry`. In `sensor.py`, `binary_sensor.py`, `switch.py` and `light.py`, replace `from . import PururuConfigEntry` with `from .runtime import PururuConfigEntry`.

- [ ] **Step 2: `vocabulary.py`**

Move verbatim from `feature.py`: the comment and `NO_READING`, `_number` and `Condition` (lines 122–169 on `main`), with the imports they need (`dataclass`, `math`, `ATTR_RESTORED`, `STATE_UNAVAILABLE`, `STATE_UNKNOWN`, `State`). Module docstring: `"""The vocabulary of conditions: what makes a watched state hold."""`. Fix `_number`'s docstring, which names a caller that no longer uses it: `"""A state's finite number, or None."""`.

In `feature.py`, delete them, drop the imports only they used, and add `from .vocabulary import Condition` (`Preset.kind` names it). Update the importers:
- `features/alerts.py`, `features/presets.py`, `features/appliance/alerts.py`: take `Condition` from `..vocabulary` / `...vocabulary`, the rest from `feature` as before.
- `features/elapsed.py`, `alert_lights.py`: take `NO_READING` from `vocabulary`.

- [ ] **Step 3: `texts.py`**

Move verbatim from `features/presets.py`: the comment, `type Texts`, `FALLBACK_LANGUAGE` and `async_texts`, with their imports (`Mapping`, `HomeAssistant`, `async_get_translations`, `DOMAIN`). Docstring: `"""The translations' common texts, in HA's language with English for what it lacks."""`. In `features/presets.py`, import `Texts` from `..texts`. In `__init__.py`, replace `presets.async_texts(hass)` with `texts.async_texts(hass)` and `presets.Texts` with `texts.Texts` (import `texts`; name the local variable `common` if it clashes).

- [ ] **Step 4: `ALERT2` and `PRIORITIES`**

Move `ALERT2 = "alert2"` from `alert2_alerts.py` to `const.py` (as `ALERT2: Final = "alert2"`, next to the other constants); `alert2_alerts.py` and `features/alerts.py` import it from `const`. Move `PRIORITIES = ("low", "medium", "high")` from `features/alerts.py` to `feature.py`; `features/alerts.py`, `features/presets.py` and `alert_lights.py` import it from `feature`. After this step, `features/alerts.py` no longer imports `alert2_alerts`.

- [ ] **Step 5: Run the whole suite**

```bash
uv run pytest -q
```

Expected: every test passes, `tests/test_code.py` included (ruff, format, mypy).

- [ ] **Step 6: Commit**

```bash
git add -A custom_components/pururu
git commit -m "pururu: runtime, vocabulary and texts modules; ALERT2 and PRIORITIES to the core (refactor A1)"
```

---

### Task 3: Validation out of `__init__`: `catalogue`, `checks`, `schema`

**Files:**
- Create: `custom_components/pururu/catalogue.py`, `checks.py`, `schema.py`
- Modify: `custom_components/pururu/__init__.py`

**Interfaces:**
- Consumes: Task 2's modules.
- Produces:
  - `catalogue.builders() -> dict[str, Feature]`
  - `catalogue.entity_keys(device: dict[str, Any]) -> Iterator[tuple[str, str, Platform]]`
  - `catalogue.referable(key: str, config: dict[str, Any]) -> dict[str, tuple[Device, str, Platform]]`
  - `schema.CONFIG_SCHEMA`

- [ ] **Step 1: `catalogue.py`**

```python
"""Every builder of a device, and the entity keys they can create."""

from collections.abc import Iterator
from typing import Any

from homeassistant.const import CONF_NAME, Platform

from .device_keys import DEVICE_KEYS
from .feature import Device, Feature, qualified
from .features import FEATURES


def builders() -> dict[str, Feature]:
    """Everything that builds entities of a device: its features, then the device keys.

    Read at every call, so a feature added to FEATURES is seen. Only FEATURES
    count as a device's features.
    """
    return {**FEATURES, **DEVICE_KEYS}
```

Then move verbatim, renamed: `_entity_keys` → `entity_keys`, `_referable` → `referable`. In both bodies replace `BUILDERS` by `builders()` (call it once per function into a local `found = builders()` where the body reads it more than once). Update their docstrings' cross-references only if they name a moved function.

- [ ] **Step 2: Check `builders()` keeps today's order and lookups**

By reading, since no ID depends on it: `ChainMap(DEVICE_KEYS, FEATURES)` iterates its last map first, so `FEATURES` then `DEVICE_KEYS`; `{**FEATURES, **DEVICE_KEYS}` has the same key order. Lookups are equal because the two dicts' keys are disjoint (`features`, `alerts`… vs `programs`, `reactions`). Put this sentence in the commit message (step 7).

- [ ] **Step 3: `checks.py`**

Move verbatim, renamed without the underscore where `schema.py` calls them:
- device checks (called by `_device`): `_capabilities_provided` → `capabilities_provided`, `_real_entities_distinct` → `real_entities_distinct`, `_references_resolved` → `references_resolved`, `_no_alert_watches_an_alert` → `no_alert_watches_an_alert`, `_reactions_on_this_device` → `reactions_on_this_device`, `_programs_on_this_device` → `programs_on_this_device`;
- house checks (in `CONFIG_SCHEMA`'s `vol.All`): `_areas_exist` → `areas_exist`, `_entity_ids_distinct` → `entity_ids_distinct`, `_generated_ids_distinct` → `generated_ids_distinct`, `_reactions_resolved` → `reactions_resolved`, `_alert_lights_resolved` → `alert_lights_resolved`, `_messages_sent` → `messages_sent`;
- their private helpers, names unchanged: `_own_statistics`, `_generated_ids`, `_reaction_resolved`, `_alert_light_group_resolved`, `_alert_light_groups`.

In the bodies: `BUILDERS[…]` → `builders()[…]` (a local `found = builders()` when used more than once), `_entity_keys` → `entity_keys`, `_referable` → `referable` (from `.catalogue`). Module docstring: `"""The rules a configuration must follow beyond each block's own schema."""`.

- [ ] **Step 4: `schema.py`**

Move verbatim: `_device`, `_feature_block` and `CONFIG_SCHEMA` (with its comments), calling the renamed checks from `.checks`. Module docstring: `"""The pururu: block's schema: each device, then the rules over the whole house."""`.

- [ ] **Step 5: Slim `__init__.py`**

Delete everything moved, and `BUILDERS` with its comment. Add `from .schema import CONFIG_SCHEMA`. `_build` and `_inputs` (still in `__init__` until Task 4) use `builders()` and `referable` from `.catalogue`. Remove imports that are now unused (ruff will list them).

- [ ] **Step 6: Run the whole suite**

```bash
uv run pytest -q
```

Expected: every test passes unchanged, `tests/test_ids.py` included.

- [ ] **Step 7: Commit**

```bash
git add -A custom_components/pururu
git commit -m "pururu: validation out of __init__: catalogue, checks, schema (refactor A1)

builders() is {**FEATURES, **DEVICE_KEYS}: the ChainMap(DEVICE_KEYS, FEATURES)
it replaces iterated FEATURES first too, and the keys are disjoint."
```

---

### Task 4: Setup out of `__init__`: `build`, `devices`, `generate`, Alert2's items, events' devices

**Files:**
- Create: `custom_components/pururu/build.py`, `devices.py`, `generate.py`
- Modify: `__init__.py`, `alert2_alerts.py`, `events.py`

**Interfaces:**
- Consumes: `catalogue.builders`, `catalogue.referable`, `runtime.PururuConfigEntry`, `texts.Texts`.
- Produces (the calls `async_setup_entry` makes):
  - `build.build(hass, key, config, texts, owned) -> tuple[list[tuple[PururuEntity, set[str]]], dict[str, str]]`
  - `build.creatable(hass, registry, built, watched) -> list[PururuEntity]`
  - `devices.place(hass, entry, devices) -> None`, `devices.remove_stale(hass, entry, keys) -> None`
  - `generate.owned(hass, entry, devices) -> dict[str, str]`, `generate.watched_items(devices) -> set[tuple[str, str]]`
  - `generate.scripts(hass, devices, created) -> tuple[list[generated.Item], set[str], set[str]]`
  - `generate.automations(hass, devices, created, scripts, held_scripts, notify) -> tuple[list[generated.Item], set[str]]`
  - `alert2_alerts.items(hass, built) -> list[dict[str, Any]]`
  - `events.watched(devices, created_by) -> list[events.Watched]`

- [ ] **Step 1: `build.py`**

Move verbatim: `_build` → `build`, `_inputs` (private), `_creatable` → `creatable`, `_holder` (private). `BUILDERS` → `builders()`, `_referable` → `referable`. Docstring: `"""Every entity of a device, from its builders, and which of them can be created."""`.

- [ ] **Step 2: `devices.py`**

Move verbatim: `_place` → `place`, `_remove_stale` → `remove_stale`. Docstring: `"""The devices the entry built: each in its area, and nothing stale left."""`.

- [ ] **Step 3: `generate.py`**

Move verbatim: `_owned` → `owned`, `_watched_items` → `watched_items`, `_scripts` → `scripts`, `_acted_on` (private), `_automations` → `automations`, `_watched` (private), `_started` (private). `_referable` → `referable`. Docstring: `"""The scripts and automations the entry generates: what each holds, and what it watches."""`.

- [ ] **Step 4: Alert2's items and events' devices**

Move `_alert2_alerts` into `alert2_alerts.py` as `items` (it imports `ProblemAlert` from `.features.alerts`: safe now that Task 2 cut `features/alerts.py`'s import of `alert2_alerts`). Move `_event_devices` into `events.py` as `watched` (it needs `CONF_NAME`, `ENTITY_PREFIX` and `Entity`).

- [ ] **Step 5: `async_setup_entry` calls the new names**

In `__init__.py`: `_owned` → `generate.owned`, `_build` → `build.build`, `_creatable` → `build.creatable`, `_event_devices` → `events.watched`, `_place` → `devices.place`, `_remove_stale` → `devices.remove_stale`, `_scripts` → `generate.scripts`, `_automations` → `generate.automations`, `_watched_items` → `generate.watched_items`, `_alert2_alerts` → `alert2_alerts.items`. The local variable `devices` (the configured devices) shadows the module: import the module as `from . import devices as device_steps` or rename the local to `configured_devices`; pick one and use it throughout. Nothing else in `async_setup_entry` changes: same calls, same order, same arguments. Delete the moved functions and the imports they leave unused.

- [ ] **Step 6: Run the whole suite**

```bash
uv run pytest -q
```

Expected: every test passes unchanged. `__init__.py` is now about 250 lines (the entry points and `_rebuild_for`).

- [ ] **Step 7: Commit**

```bash
git add -A custom_components/pururu
git commit -m "pururu: setup out of __init__: build, devices, generate (refactor A1)"
```

---

### Task 5: Coverage kept per function, version 0.2.0, docs

**Files:**
- Modify: `custom_components/pururu/manifest.json`, `CLAUDE.md`, `docs/develop/architecture.mdx`, `docs/develop/writing-a-feature.mdx`
- Create (not committed): `.superpowers/a1/coverage-after.json`, `.superpowers/a1/compare.py`

**Interfaces:**
- Consumes: `.superpowers/a1/coverage-before.json` from Task 1.

- [ ] **Step 1: Coverage after**

```bash
uv run pytest --cov --cov-branch --cov-report=json:.superpowers/a1/coverage-after.json -q
```

- [ ] **Step 2: Compare per function**

`.superpowers/a1/compare.py`:

```python
"""Fail if any function lost coverage: more missing lines or branches after the move than before.

A function is matched by its name without the leading underscore of its last part,
ignoring its module: a moved function keeps its name or loses only that underscore
(`_build` -> `build`, `Condition.holds` -> `Condition.holds`). Functions sharing a
name (each platform's `async_setup_entry`) are summed on both sides.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent


def functions(report: str) -> dict[str, tuple[int, int]]:
    """function name -> (missing lines, missing branches), summed over every file."""
    data = json.loads((HERE / report).read_text())
    found: dict[str, list[int]] = {}
    for file in data["files"].values():
        for name, summary in file.get("functions", {}).items():
            if not name:  # the module's top level
                continue
            *owner, last = name.split(".")
            key = ".".join([*owner, last.lstrip("_")])
            totals = found.setdefault(key, [0, 0])
            totals[0] += summary["summary"]["missing_lines"]
            totals[1] += summary["summary"].get("missing_branches", 0)
    return {key: (lines, branches) for key, (lines, branches) in found.items()}


before, after = functions("coverage-before.json"), functions("coverage-after.json")
worse = sorted(
    name
    for name in before.keys() & after.keys()
    if after[name][0] > before[name][0] or after[name][1] > before[name][1]
)
gone = sorted(before.keys() - after.keys())
for name in worse:
    print(f"LOST COVERAGE {name}: missing (lines, branches) {before[name]} -> {after[name]}")
for name in gone:
    print(f"ONLY BEFORE {name}")
sys.exit(1 if worse or gone else 0)
```

```bash
uv run python .superpowers/a1/compare.py
```

Expected: exit 0, nothing printed. Any line is a failure to fix: find the path that stopped running and restore it, never by editing or loosening an existing test.

- [ ] **Step 3: Every moved body unchanged**

```bash
git diff main --stat -- custom_components/pururu
git diff main -- custom_components/pururu/__init__.py | grep '^-def \|^-async def ' 
```

For each removed function, open its new home and compare the body with `git show main:custom_components/pururu/__init__.py`: only the name, `BUILDERS` → `builders()` and the renamed calls may differ.

- [ ] **Step 4: Version 0.2.0**

In `custom_components/pururu/manifest.json`, `"version": "0.1.23"` → `"version": "0.2.0"`. Then:

```bash
git fetch origin && git log --oneline origin/main -3 && gh release list --limit 3
python3 release.py check
```

Expected: no other open PR or release already at 0.2.0; `release.py check` passes.

- [ ] **Step 5: Docs**

- `CLAUDE.md`, Architecture: where it names `__init__`'s functions or `BUILDERS`, name the new homes: validation in `schema.py`/`checks.py`/`catalogue.py` (`builders()` instead of the live `ChainMap`), building in `build.py` (`_creatable` → `build.creatable`), `_place`/`_remove_stale` in `devices.py`, the scripts' and automations' planning in `generate.py`, `PururuConfigEntry` in `runtime.py`, `Condition` in `vocabulary.py`, the common texts in `texts.py`. Keep its style: short, no new sections.
- `docs/develop/architecture.mdx`: the same renames (`_device in __init__.py` → `schema.py`, `_build`, `_creatable`, `_scripts`, `_automations`, `_rebuild_for` stays, `BUILDERS` → `builders()`).
- `docs/develop/writing-a-feature.mdx`: any mention of `__init__.py`'s functions, renamed the same way.
- Check: `pnpm docs:check`.

- [ ] **Step 6: Whole suite and commit**

```bash
uv run pytest -q
git add custom_components/pururu/manifest.json CLAUDE.md docs/develop
git commit -m "pururu: 0.2.0 starts; docs follow the moves (refactor A1)"
```

- [ ] **Step 7: Open the PR**

Rename the branch, push and open the PR (title `pururu: refactor A1, code out of __init__ (0.2.0)`), body: what moved where, "no behaviour change", the snapshot, the coverage comparison's result, and that v0.2.0 is tagged with A1 alone (spec, D19). Then watch reviews, checks and Sonar until merged (see the repo's merge rules).
