# Programs' and reactions' statistics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every program gets cycle statistics (last run, runs and runtime totals, optional meters), every reaction a trigger count (and optional meters), as sensors in its device.

**Architecture:** `programs.py` and `reactions.py` each declare a `STATISTICS` `Feature` (namespace `program` / `reaction`, `per_item` suffixes, `items` = their block's keys), collected in `device_keys.DEVICE_KEYS`. `__init__.py` walks `FEATURES` and `DEVICE_KEYS` together (`BUILDERS`) wherever it lists, resolves or builds entity keys, but only `FEATURES` count as a device's features. A program's `cycles_total` sensor watches its script and sends each run as a `Cycle` on the existing cycle signals, so `features/cycle/` entities work unchanged. A reaction's `triggered_total` counts HA's `automation_triggered` for its automation.

**Tech Stack:** Home Assistant 2026.9 custom integration, voluptuous, utility_meter, pytest-homeassistant-custom-component, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-28-programs-reactions-statistics-design.md`

## Global Constraints

- Version `0.1.18` in `custom_components/pururu/manifest.json`.
- Entity IDs: `sensor.pururu_<device>_program_<program>_<suffix>`, `sensor.pururu_<device>_reaction_<reaction>_<suffix>`.
- Program suffixes: `last_cycle_start`, `last_cycle_duration`, `last_cycle_end`, `cycles_total`, `runtime_total`, `runtime_<period>`, `cycles_<period>`; reaction suffixes: `triggered_total`, `triggered_<period>`; periods `today`, `week`, `month`, `year`.
- `statistics` per program: `runtime`, `cycles` (lists of periods, each once); per reaction: `triggered`. Optional, default none.
- Totals and last cycle always created; meters only when listed.
- `programs` and `reactions` still don't count as a device's feature.
- A reaction's `when` naming one of **its own** counters is refused: `reactions: <key>: <when> is its own statistic`.
- Translations in `en.json` and `pt-BR.json`, an icon per key; names carry `{program}` / `{reaction}`.

## Review Focus

- A program started from anywhere (UI, a reaction, voice) counts once per run. Task 1 (`script.turn_on` direct) and Task 2 (via a reaction).
- A pururu reload while the program runs counts the run once, with its real start. Task 1.
- A program held (its target disabled): its statistics keep their values and aren't removed. Task 1.
- A reaction whose program was already running still counts the trigger. Task 2.
- A script or automation renamed in the UI: its statistics follow at once. Task 3.

---

### Task 1: programs' statistics, and `DEVICE_KEYS`

**Files:**
- Create: `custom_components/pururu/device_keys.py`
- Modify: `custom_components/pururu/programs.py`, `custom_components/pururu/__init__.py`, `custom_components/pururu/translations/en.json`, `custom_components/pururu/translations/pt-BR.json`, `custom_components/pururu/icons.json`
- Test: `tests/test_programs.py`, `tests/test_features.py`

**Interfaces:**
- Produces: `programs.STATISTICS: Feature`; `programs.PER_PROGRAM: dict[str, Platform]`; `programs.Runs`; `device_keys.DEVICE_KEYS: dict[str, Feature]` (`{"programs": programs.STATISTICS}` now, `reactions` added in Task 2); `__init__.BUILDERS = {**FEATURES, **DEVICE_KEYS}`.

- [ ] **Step 1: Write the failing tests** (end of `tests/test_programs.py`)

```python
# --- statistics --------------------------------------------------------------------

STAT = "sensor.pururu_pool_program_clean_"


def value(hass: HomeAssistant, suffix: str) -> str:
    state = hass.states.get(STAT + suffix)
    assert state is not None, f"no {STAT}{suffix}"
    return state.state


async def test_a_run_is_a_cycle(pool: HomeAssistant, freezer: Any) -> None:
    await start(pool)
    started = dt_util.utcnow()
    assert value(pool, "cycles_total") == "0"
    await tick(pool, freezer, TWO_HOURS)
    await pool.async_block_till_done()
    assert value(pool, "cycles_total") == "1"
    assert value(pool, "last_cycle_duration") == "120.0"
    assert dt_util.parse_datetime(value(pool, "last_cycle_start")) == started
    assert dt_util.parse_datetime(value(pool, "last_cycle_end")) == dt_util.utcnow()
    assert float(value(pool, "runtime_total")) == pytest.approx(2, abs=0.01)


async def test_its_statistics_are_named_by_the_program(pool: HomeAssistant) -> None:
    state = pool.states.get(STAT + "cycles_total")
    assert state is not None
    assert state.attributes["friendly_name"] == "Piscina Limpar cycles"


async def test_meters_are_asked_for(scripts: HomeAssistant) -> None:
    program = {**CLEANING, "statistics": {"runtime": ["today"], "cycles": ["month", "year"]}}
    assert await setup(scripts, devices(clean=program))
    for suffix in ("runtime_today", "cycles_month", "cycles_year"):
        assert scripts.states.get(STAT + suffix) is not None, suffix
    assert scripts.states.get(STAT + "runtime_week") is None


@pytest.mark.parametrize("statistics", [
    {"runtime": ["today", "today"]}, {"runs": ["today"]}, {"cycles": ["daily"]}])
async def test_invalid_statistics_are_refused(ha: HomeAssistant, statistics: dict[str, Any]) -> None:
    assert not await setup(ha, devices(clean={**CLEANING, "statistics": statistics}))


async def test_a_reload_mid_run_counts_it_once_from_its_start(pool: HomeAssistant,
                                                              freezer: Any) -> None:
    await start(pool)
    started = dt_util.utcnow()
    await tick(pool, freezer, 60)
    await reload_while_running(pool, devices())
    await tick(pool, freezer, TWO_HOURS - 60)
    await pool.async_block_till_done()
    assert value(pool, "cycles_total") == "1"
    assert dt_util.parse_datetime(value(pool, "last_cycle_start")) == started


async def test_a_held_program_keeps_its_statistics(pool: HomeAssistant, freezer: Any) -> None:
    await start(pool)
    await tick(pool, freezer, TWO_HOURS)
    await pool.async_block_till_done()
    await disable(pool, PUMP)
    await tick(pool, freezer, 31)
    await pool.async_block_till_done()
    assert value(pool, "cycles_total") == "1"


async def test_a_removed_program_takes_its_statistics(pool: HomeAssistant) -> None:
    wash = {"name": "Lavar", "sequence": [{"turn_on": "switch_pump"}]}
    await reload(pool, devices(wash=wash))
    assert er.async_get(pool).async_get(STAT + "cycles_total") is None
    assert er.async_get(pool).async_get("sensor.pururu_pool_program_wash_cycles_total") is not None
```

Add `from homeassistant.util import dt as dt_util` to its imports. Move these tests below `disable` (they use it).

In `tests/test_features.py`, the `features` fixture becomes:

```python
@pytest.fixture
def features(ha: HomeAssistant) -> dict[str, Any]:
    """Every Feature: a device's features, and the device keys creating entities (programs, reactions)."""
    return {**module("features").FEATURES, **module("device_keys").DEVICE_KEYS}
```

and the module docstring: `The contract, over every Feature in FEATURES and DEVICE_KEYS: a new one is covered here unchanged.`

- [ ] **Step 2: Run, expect FAIL**

Run: `uv run pytest tests/test_programs.py tests/test_features.py -n 0 -q`
Expected: the new tests FAIL (no such sensor; `device_keys` doesn't exist).

- [ ] **Step 3: Implement**

`programs.py` (docstring gains: `Each run is a cycle: its statistics are sensors of its device (STATISTICS).`):

```python
from homeassistant.components.sensor import RestoreSensor  # not needed if Runs only subclasses CyclesTotal
from homeassistant.const import CONF_NAME, STATE_OFF, STATE_ON, Platform
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback, split_entity_id
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event

from .entity import PururuEntity
from .feature import Device, Feature, Item, qualified
from .features.cycle import Cycle, cycle_signal, end_signal
from .features.cycle.last import LAST_CYCLE, LastCycleValue
from .features.cycle.statistics import PERIOD_LIST, PERIODS, Meter
from .features.cycle.totals import CyclesTotal, RuntimeTotal

# What a run records: the last cycle's (no energy: a script uses none), and totals
LAST_RUN = tuple(d for d in LAST_CYCLE if d.key != "last_cycle_energy")
COUNTERS = ("runtime", "cycles")
PER_PROGRAM: dict[str, Platform] = {
    **{description.key: Platform.SENSOR for description in LAST_RUN},
    **{f"{counter}_total": Platform.SENSOR for counter in COUNTERS},
    **{f"{counter}_{period}": Platform.SENSOR for counter in COUNTERS for period in PERIODS},
}
```

`PROGRAM` gains:

```python
        vol.Optional("statistics", default={}): vol.Schema(
            {vol.Optional(counter, default=[]): PERIOD_LIST for counter in COUNTERS}
        ),
```

The run tracker and the build:

```python
class Runs(CyclesTotal):
    """A program's finished runs, all time; it sends each one: its script on, then off.

    The run's start is the `on` state's: a pururu reload while it runs keeps it.
    """

    def __init__(self, device: Device, script: str, *, item: Item) -> None:
        """Count the runs of `script`, the entity of `item`'s program."""
        super().__init__(device, source="cycles_total", item=item)
        self.sources = ()  # the script isn't pururu's: nothing of the device to wait for
        self._script = script
        # The end's own signal last, as a cycle's source sends them
        self._signals = (cycle_signal(device, item), end_signal(device, item))

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the count, count, then watch the script."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(self.hass, self._script, self._changed)
        )

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if old is None or new is None or (old.state, new.state) != (STATE_ON, STATE_OFF):
            return
        run = Cycle(start=old.last_changed, end=new.last_changed, energy_kwh=None)
        for signal in self._signals:
            async_dispatcher_send(self.hass, signal, run)


def _items(config: Mapping[str, Any]) -> list[Item]:
    return [Item(slug=key, name=program[CONF_NAME]) for key, program in config.items()]


def build(
    hass: HomeAssistant, device: Device, config: dict[str, Any], inputs: Mapping[str, str]
) -> list[PururuEntity]:
    """Each program's runs as cycles: last run, totals, the meters asked for."""
    registry = er.async_get(hass)
    entities: list[PururuEntity] = []
    for item in _items(config):
        unique_id = script_id(device.key, item.slug)
        script = registry.async_get_entity_id(KIND.domain, KIND.domain, unique_id) or (
            f"{KIND.domain}.{unique_id}"
        )
        counted = item.key("cycles_total")
        entities.append(Runs(device, script, item=item))
        entities.extend(
            LastCycleValue(device, description, source=counted, item=item)
            for description in LAST_RUN
        )
        entities.append(RuntimeTotal(device, script, STATE_ON, source=counted, item=item))
        for counter in COUNTERS:
            total = f"{counter}_total"
            source = device.current_entity_id(hass, Platform.SENSOR, item.key(total))
            entities.extend(
                Meter(device, f"{counter}_{period}", total, source, period, item=item)
                for period in config[item.slug]["statistics"][counter]
            )
    return entities


# Not a device's feature: its programs' statistics, as a Feature builds entities
STATISTICS = Feature(
    schema=SCHEMA,
    entity_keys={},
    build=build,
    example={"clean": {"name": "Clean", "sequence": [{"delay": 1}]}},
    namespace=NAMESPACE,
    per_item=PER_PROGRAM,
    items=_items,
)
```

(Drop the `RestoreSensor` import line; it's shown only to note it isn't needed. Import `override` from `typing`, `Mapping` is already imported.)

`device_keys.py`:

```python
"""Device keys that aren't features but create entities of the device: their statistics.

A device's programs and reactions (programs.py, reactions.py) are generated
files; each program's runs and each reaction's triggers are sensors, built as a
Feature's are. They don't count as a device's feature.
"""

from . import programs
from .feature import Feature

DEVICE_KEYS: dict[str, Feature] = {"programs": programs.STATISTICS}
```

`__init__.py`: import `from .device_keys import DEVICE_KEYS` and define, next to `PururuConfigEntry`:

```python
# Everything that builds entities of a device: its features, then the device keys
# creating some (their statistics). Only FEATURES count as a device's feature.
BUILDERS: dict[str, Feature] = {**FEATURES, **DEVICE_KEYS}
```

Then replace `FEATURES` by `BUILDERS` in: `_references_resolved`'s `owners` (keep the `for name in names` loop over features), `_reactions_on_this_device`'s `keys`, `_programs_on_this_device` (`owners` and `BUILDERS[owners[key]].actions`), `_entity_keys` (loop), `_entity_ids_distinct` (`BUILDERS[name].namespace`), `_referable` (both), `_build`'s outer loop (`for name, feature in BUILDERS.items()`). Leave `FEATURES` in `_device`'s schema and `names`, `_capabilities_provided`, `_real_entities_distinct`, `_no_alert_watches_an_alert` and `_build`'s `requires` lookup. Import `Feature` from `.feature` if it isn't.

`_entity_keys`'s docstring: `(builder, entity key, platform) of every entity the device's features and device keys can create.`

Translations `en.json`, in `entity.sensor`, after the `mode_*` block:

```json
      "program_last_cycle_start": {"name": "{program} last run start"},
      "program_last_cycle_end": {"name": "{program} last run end"},
      "program_last_cycle_duration": {"name": "{program} last run duration"},
      "program_cycles_total": {"name": "{program} cycles", "unit_of_measurement": "cycles"},
      "program_runtime_total": {"name": "{program} runtime"},
      "program_runtime_today": {"name": "{program} runtime today"},
      "program_runtime_week": {"name": "{program} runtime this week"},
      "program_runtime_month": {"name": "{program} runtime this month"},
      "program_runtime_year": {"name": "{program} runtime this year"},
      "program_cycles_today": {"name": "{program} cycles today"},
      "program_cycles_week": {"name": "{program} cycles this week"},
      "program_cycles_month": {"name": "{program} cycles this month"},
      "program_cycles_year": {"name": "{program} cycles this year"}
```

`pt-BR.json`:

```json
      "program_last_cycle_start": {"name": "Início da última execução de {program}"},
      "program_last_cycle_end": {"name": "Fim da última execução de {program}"},
      "program_last_cycle_duration": {"name": "Duração da última execução de {program}"},
      "program_cycles_total": {"name": "Ciclos de {program}", "unit_of_measurement": "ciclos"},
      "program_runtime_total": {"name": "Tempo de {program}"},
      "program_runtime_today": {"name": "Tempo de {program} hoje"},
      "program_runtime_week": {"name": "Tempo de {program} na semana"},
      "program_runtime_month": {"name": "Tempo de {program} no mês"},
      "program_runtime_year": {"name": "Tempo de {program} no ano"},
      "program_cycles_today": {"name": "Ciclos de {program} hoje"},
      "program_cycles_week": {"name": "Ciclos de {program} na semana"},
      "program_cycles_month": {"name": "Ciclos de {program} no mês"},
      "program_cycles_year": {"name": "Ciclos de {program} no ano"}
```

`icons.json`, `entity.sensor`: the same keys as the `mode_*` ones (`mdi:clock-start`, `mdi:clock-end`, `mdi:timer-outline`, `mdi:counter`, `mdi:timer-sand` for runtime).

- [ ] **Step 4: Run, expect PASS**

Run: `uv run pytest tests/test_programs.py tests/test_features.py tests/test_reactions.py -n 0 -q`

If the friendly name differs (HA composes device name + entity name), assert what HA shows and ledger it.

- [ ] **Step 5: Whole suite** — `uv run pytest -q` (ruff, mypy, hassfest). Fix `mypy` on `Runs.__init__` if `super().__init__` typing needs it.

- [ ] **Step 6: Commit**

```bash
git add custom_components/pururu tests
git commit -m "programs: each run is a cycle, with its statistics"
```

### Task 2: reactions' trigger counts

**Files:**
- Modify: `custom_components/pururu/reactions.py`, `custom_components/pururu/device_keys.py`, `custom_components/pururu/__init__.py` (`_reactions_on_this_device`), translations, icons
- Test: `tests/test_reactions.py`

**Interfaces:**
- Consumes: `BUILDERS`, `DEVICE_KEYS` (Task 1).
- Produces: `reactions.STATISTICS`, `reactions.PER_REACTION`, `reactions.TriggersTotal`.

- [ ] **Step 1: Write the failing tests** (end of `tests/test_reactions.py`)

```python
# --- statistics --------------------------------------------------------------------

TRIGGERED = "sensor.pururu_pool_reaction_clean_triggered_total"


def count(ha: HomeAssistant, entity_id: str = TRIGGERED) -> str:
    state = ha.states.get(entity_id)
    assert state is not None, f"no {entity_id}"
    return state.state


async def test_every_trigger_counts_even_one_its_program_skips(ha: HomeAssistant,
                                                              both: None) -> None:
    await fake(ha, DOOR, "off")
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, pool())
    assert count(ha) == "0"
    await fake(ha, DOOR, "on")
    await fake(ha, DOOR, "off")
    await fake(ha, DOOR, "on")
    await settle()
    assert count(ha) == "2"
    assert ha.states.get("sensor.pururu_pool_program_clean_cycles_total").state == "0"


async def test_a_reaction_without_then_counts_too(ha: HomeAssistant, freezer: Any,
                                                 automations: None) -> None:
    assert await setup(ha, devices(soon={"name": "Logo", "at": "10:05"}))
    await tick(ha, freezer, 300)
    assert count(ha, "sensor.pururu_lights_reaction_soon_triggered_total") == "1"


async def test_its_meters_are_asked_for(ha: HomeAssistant) -> None:
    assert await setup(ha, pool(clean={**DOOR_OPENS, "then": "clean",
                                       "statistics": {"triggered": ["month"]}}))
    assert ha.states.get("sensor.pururu_pool_reaction_clean_triggered_month") is not None
    assert ha.states.get("sensor.pururu_pool_reaction_clean_triggered_today") is None


async def test_a_reaction_on_its_own_counter_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    it = {"name": "Eu", "when": "reaction_it_triggered_total", "above": 3}
    assert not await setup(ha, devices(it=it))
    assert "reactions: it: reaction_it_triggered_total is its own statistic" in caplog.text


async def test_a_reaction_on_a_programs_statistic(ha: HomeAssistant) -> None:
    done = {"name": "Limpou", "when": "program_clean_last_cycle_end", "to": "unknown"}
    assert await setup(ha, pool(done=done))
    trigger = generated(ha)[0]["triggers"][0]
    assert trigger["entity_id"] == "sensor.pururu_pool_program_clean_last_cycle_end"
```

- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/test_reactions.py -n 0 -q`

- [ ] **Step 3: Implement**

`reactions.py`:

```python
# HA's event when an automation runs (its conditions passed): its data names it.
# A string, not automation's constant: pururu doesn't depend on that integration
AUTOMATION_TRIGGERED = "automation_triggered"
PER_REACTION: dict[str, Platform] = {
    "triggered_total": Platform.SENSOR,
    **{f"triggered_{period}": Platform.SENSOR for period in PERIODS},
}


class TriggersTotal(PururuEntity, RestoreSensor):
    """A reaction's triggers, all time, whether its program started or not."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, device: Device, automation: str, *, item: Item) -> None:
        """Count the runs of `automation`, the entity of `item`'s reaction."""
        self._identify(device, Platform.SENSOR, "triggered_total", item=item)
        self._automation = automation
        self._triggers = 0

    @property
    @override
    def native_value(self) -> int:
        """The count."""
        return self._triggers

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the count, then count."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and isinstance(last.native_value, int | float | Decimal):
            self._triggers = int(last.native_value)
        self.async_on_remove(
            self.hass.bus.async_listen(
                AUTOMATION_TRIGGERED, self._count, event_filter=self._of_it
            )
        )

    @callback
    def _of_it(self, data: Mapping[str, Any]) -> bool:
        return data.get("entity_id") == self._automation

    @callback
    def _count(self, _event: Event) -> None:
        self._triggers += 1
        self.async_write_ha_state()


def _items(config: Mapping[str, Any]) -> list[Item]:
    return [Item(slug=key, name=reaction[CONF_NAME]) for key, reaction in config.items()]


def build(
    hass: HomeAssistant, device: Device, config: dict[str, Any], inputs: Mapping[str, str]
) -> list[PururuEntity]:
    """Each reaction's trigger count, and the meters asked for."""
    registry = er.async_get(hass)
    entities: list[PururuEntity] = []
    for item in _items(config):
        unique_id = automation_id(device.key, item.slug)
        automation = registry.async_get_entity_id(
            KIND.domain, KIND.domain, unique_id
        ) or f"{KIND.domain}.{unique_id}"
        entities.append(TriggersTotal(device, automation, item=item))
        source = device.current_entity_id(hass, Platform.SENSOR, item.key("triggered_total"))
        entities.extend(
            Meter(device, f"triggered_{period}", "triggered_total", source, period, item=item)
            for period in config[item.slug]["statistics"]["triggered"]
        )
    return entities


# Not a device's feature: its reactions' statistics, as a Feature builds entities
STATISTICS = Feature(
    schema=SCHEMA,
    entity_keys={},
    build=build,
    example={"night": {"name": "Night", "at": "22:00"}},
    namespace=NAMESPACE,
    per_item=PER_REACTION,
    items=_items,
)
```

`REACTION`'s schema gains `vol.Optional("statistics", default={}): vol.Schema({vol.Optional("triggered", default=[]): PERIOD_LIST})`. Imports: `Decimal`, `override`, `RestoreSensor`, `SensorStateClass`, `Platform`, `Event`, `HomeAssistant`, `callback`, `er`, `PururuEntity`, `Device`, `Feature`, `Item`, `PERIOD_LIST`, `PERIODS`, `Meter`. `STATISTICS` must be defined after `SCHEMA` and `automation_id`. Module docstring gains: `Each reaction's triggers are counted: sensors of its device (STATISTICS).`

`device_keys.py`: `DEVICE_KEYS = {"programs": programs.STATISTICS, "reactions": reactions.STATISTICS}`, importing `reactions`.

`__init__.py`, `_reactions_on_this_device`, inside the loop, before the `device`/`when` check:

```python
        own = {qualified(reactions.NAMESPACE, key + "_" + s) for s in reactions.PER_REACTION}
        if "device" not in reaction and reaction.get("when") in own:
            raise vol.Invalid(
                f"reactions: {key}: {reaction['when']} is its own statistic"
            )
```

Translations `en.json`:

```json
      "reaction_triggered_total": {"name": "{reaction} triggers", "unit_of_measurement": "triggers"},
      "reaction_triggered_today": {"name": "{reaction} triggers today"},
      "reaction_triggered_week": {"name": "{reaction} triggers this week"},
      "reaction_triggered_month": {"name": "{reaction} triggers this month"},
      "reaction_triggered_year": {"name": "{reaction} triggers this year"}
```

`pt-BR.json`:

```json
      "reaction_triggered_total": {"name": "Disparos de {reaction}", "unit_of_measurement": "disparos"},
      "reaction_triggered_today": {"name": "Disparos de {reaction} hoje"},
      "reaction_triggered_week": {"name": "Disparos de {reaction} na semana"},
      "reaction_triggered_month": {"name": "Disparos de {reaction} no mês"},
      "reaction_triggered_year": {"name": "Disparos de {reaction} no ano"}
```

Icons: `mdi:gesture-tap` for all five.

- [ ] **Step 4: Run, expect PASS** — `uv run pytest tests/test_reactions.py tests/test_features.py -n 0 -q`, then `uv run pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add custom_components/pururu tests
git commit -m "reactions: each one counts its triggers"
```

### Task 3: statistics follow a renamed script or automation

**Files:**
- Modify: `custom_components/pururu/__init__.py` (`_started_scripts` → `_watched_items`, `_rebuild_for`)
- Test: `tests/test_reactions.py`, `tests/test_programs.py`

**Interfaces:**
- Consumes: `_rebuild_for(entry_id, registered, changes, started, targets)` from 0.1.17.
- Produces: `_watched_items(devices) -> set[tuple[str, str]]` (domain, unique ID) of every program's script and reaction's automation.

- [ ] **Step 1: Write the failing tests**

In `tests/test_reactions.py`, **replace** `test_renaming_a_script_no_reaction_starts_reloads_nothing` (0.1.17's) by:

```python
async def test_renaming_a_script_no_reaction_starts_still_reloads(ha: HomeAssistant) -> None:
    """Its statistics watch it: they follow the new ID."""
    assert await setup(ha, pool(night={"name": "Noite", "at": "22:00"}))
    with patch.object(ha.config_entries, "async_schedule_reload") as reloading:
        er.async_get(ha).async_update_entity(CLEAN, new_entity_id="script.limpar_piscina")
        await ha.async_block_till_done()
    reloading.assert_called_once()


async def test_renaming_ones_own_script_reloads_nothing(ha: HomeAssistant) -> None:
    er.async_get(ha).async_get_or_create("script", "script", "mine", suggested_object_id="mine")
    assert await setup(ha, pool())
    with patch.object(ha.config_entries, "async_schedule_reload") as reloading:
        er.async_get(ha).async_update_entity("script.mine", new_entity_id="script.minha")
        await ha.async_block_till_done()
    reloading.assert_not_called()


async def test_the_count_follows_its_automation_renamed(ha: HomeAssistant, both: None) -> None:
    await fake(ha, DOOR, "off")
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, pool())
    er.async_get(ha).async_update_entity("automation.pururu_pool_reaction_clean",
                                         new_entity_id="automation.porta_limpa")
    await ha.async_block_till_done()
    await fake(ha, DOOR, "on")
    await settle()
    assert count(ha) == "1"
```

In `tests/test_programs.py`:

```python
async def test_its_statistics_follow_the_script_renamed(pool: HomeAssistant, freezer: Any) -> None:
    er.async_get(pool).async_update_entity(CLEAN, new_entity_id="script.limpar_piscina")
    await pool.async_block_till_done()
    await start(pool, "script.limpar_piscina")
    await tick(pool, freezer, TWO_HOURS)
    await pool.async_block_till_done()
    assert value(pool, "cycles_total") == "1"
```

- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/test_reactions.py tests/test_programs.py -n 0 -q -k "renam"`

- [ ] **Step 3: Implement** in `__init__.py`

```python
def _watched_items(devices: dict[str, dict[str, Any]]) -> set[tuple[str, str]]:
    """(domain, ID) of every generated script and automation: renamed, what watches it follows."""
    return {
        *(
            (programs.KIND.domain, programs.script_id(key, program))
            for key, config in devices.items()
            for program in config.get(CONF_PROGRAMS, {})
        ),
        *(
            (reactions.KIND.domain, reactions.automation_id(key, reaction))
            for key, config in devices.items()
            for reaction in config.get(CONF_REACTIONS, {})
        ),
    }
```

`async_setup_entry`: `started = _started_scripts(devices)` → `watched_items = _watched_items(devices)`, passed to `_rebuild_for` (parameter `watched: set[tuple[str, str]]`), whose rename branch becomes:

```python
    if "entity_id" in changes:
        generated_item = (registered.platform, registered.unique_id) in watched
        return "renamed" if ours or generated_item else None
```

Docstrings: `_rebuild_for`: `Renamed: one of the entry's entities, or a script or automation it generates (a reaction starts one, statistics watch them).`; `changed`: `…or of a script or automation it generates (a reaction's action and the statistics would watch an ID that no longer is).` Remove `_started_scripts`.

- [ ] **Step 4: Run, expect PASS** — the two files, then `uv run pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add custom_components/pururu tests
git commit -m "statistics follow their script or automation renamed"
```

### Task 4: docs, spec, CLAUDE.md, version

**Files:** `docs/concepts/programs.mdx`, `docs/concepts/reactions.mdx`, `docs/concepts/entity-ids.mdx`, `docs/concepts/devices-and-features.mdx`, `docs/reference/configuration.mdx`, `docs/develop/architecture.mdx`, `docs/develop/writing-a-feature.mdx`, `docs/superpowers/specs/2026-09-28-programs-reactions-statistics-design.md`, `CLAUDE.md`, `custom_components/pururu/manifest.json`

- [ ] **Step 1: `docs/concepts/programs.mdx`**: `statistics` under Settings (`runtime`, `cycles`, periods as appliance's, link `/features/appliance#settings`); a `## Statistics` section: each run is a cycle; the entities table (suffix, unit, what); behaviour bullets from the spec's table (any start counts; reload mid-run counted once with its start; restart mid-run not counted, its runtime until then is; held program keeps them; removed program takes them; renamed script followed).
- [ ] **Step 2: `docs/concepts/reactions.mdx`**: `statistics.triggered` under Settings; `## Statistics`: `triggered_total` counts every trigger, including one whose program was already running (triggers minus the program's cycles = skipped); a reaction watching a program's statistic (example with `program_clean_last_cycle_end`); its own counters refused.
- [ ] **Step 3: `entity-ids.mdx`** and **`devices-and-features.mdx`**: `program` and `reaction` namespaces create sensors; programs and reactions still aren't features.
- [ ] **Step 4: `reference/configuration.mdx`**: `statistics` in the example's program and reaction.
- [ ] **Step 5: `develop/architecture.mdx`** and **`writing-a-feature.mdx`**: `DEVICE_KEYS`/`BUILDERS`, the contract test over both; the sentence "`reactions` and `programs` are device keys, not `Feature`s: they create no pururu entity" becomes "…not features of a device: their statistics are built by a `Feature` each in `DEVICE_KEYS`".
- [ ] **Step 6: The spec**: in Decisions, "What starts a program's cycle": the `cycles_total` sensor watches the script and sends the cycles (as `current` for modes), no entity added; the Behaviour row "The script renamed": followed at once; `DEVICE_KEYS` in `device_keys.py`, `BUILDERS` in `__init__.py`.
- [ ] **Step 7: `CLAUDE.md`**: under Features, a bullet: `programs` and `reactions` aren't features, but their statistics are built by a `Feature` each in `DEVICE_KEYS` (`device_keys.py`); `__init__` walks `BUILDERS` (`FEATURES` + `DEVICE_KEYS`) to list and build entity keys; a program's run is a cycle sent by its `cycles_total` (`Runs`), a reaction counts `automation_triggered`. In the rename bullet: any generated script or automation renamed reloads the entry.
- [ ] **Step 8: `manifest.json`** `0.1.18`; `python3 release.py check`; `pnpm docs:check`.
- [ ] **Step 9: Commit**

```bash
git add docs CLAUDE.md custom_components/pururu/manifest.json
git commit -m "docs: programs' and reactions' statistics (0.1.18)"
```
