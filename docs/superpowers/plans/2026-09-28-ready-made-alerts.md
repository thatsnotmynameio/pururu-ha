# Ready-made alerts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A feature offers ready-made alerts, off by default, each enabled with one key in its own block (`appliance: alerts: offline:`), with defaults and a translated `notify`; the appliance offers `offline`, `no_power`, `long_cycle`, `no_cycle`, `finished`.

**Architecture:** `Feature.alerts` maps a name to a `Preset` (watched entity key, a `Condition` or an `Elapsed`, defaults). `Feature.validate` adds the `alerts:` settings to the feature's schema; the preset entity keys `alert_<name>` sit in the feature's `entity_keys`, so collisions, translations, icons and references already cover them. `features/presets.py` builds the enabled ones in `_build`: condition presets are today's `Alert`, time presets a new `ElapsedAlert`, both on a shared `ProblemAlert` base. The Alert2 file is built from the created `ProblemAlert`s.

**Tech Stack:** Home Assistant 2026.9.3 custom integration, voluptuous, pytest-homeassistant-custom-component, docs.page MDX.

**Spec:** `docs/superpowers/specs/2026-09-28-ready-made-alerts-design.md`

## Global Constraints

- Version: `custom_components/pururu/manifest.json` `0.1.12` → `0.1.13`.
- Entity ID of a ready-made alert: `binary_sensor.pururu_<device>_<namespace>_alert_<name>` (appliance: `…_appliance_alert_offline`); entity key `alert_<name>`, `Platform.BINARY_SENSOR`, translation key `<namespace>_alert_<name>`.
- Catalogue (appliance): `offline` (`is: unavailable`, `for` 10 min, `medium`), `no_power` (`is: 0`, `for` 10 min, `medium`), `long_cycle` (running `on`, since its `cycle_start` attribute, `for` required, `medium`), `no_cycle` (running `off`, since `last_cycle_end` or its creation, `for` required, `medium`), `finished` (running `off`, since `last_cycle_end`, `for` 0, `lasts` default 1 h, `low`).
- Settings: `for`, `priority`, `notify` — except `finished`: `lasts`, `priority`, `notify`. A null value is `{}`; an empty `alerts:` is refused.
- Default texts in the translations' `common` block: `<namespace>_alert_<name>_message`, `<namespace>_alert_<name>_done_message`; read in `hass.config.language`, English for what it lacks.
- Names (en / pt-BR): Offline / Sem conexão, No power / Sem energia, Long cycle / Ciclo longo, No cycle / Sem ciclo, Finished / Terminou.
- Texts (en / pt-BR), message then done_message: offline "The plug is offline." / "A tomada está sem conexão.", "The plug is back." / "A tomada voltou."; no_power "There's no power." / "Está sem energia.", "Power is back." / "A energia voltou."; long_cycle "The cycle is taking too long." / "O ciclo está demorando demais.", "The cycle ended." / "O ciclo terminou."; no_cycle "It hasn't run in a while." / "Não roda há um tempo.", "It's running again." / "Voltou a rodar."; finished "The cycle finished." / "O ciclo terminou.", "Done." / "Pronto.".
- `appliance_running` gains the attribute `cycle_start` (datetime) while on, absent while off.
- A hand-written alert's `when` can't name an `alert_*` entity key of another feature; a reaction's `when` can.
- Ruff/mypy strict on `custom_components/pururu` (run by `uv run pytest` through `tests/test_code.py`). MDX: `{`/`<` outside code in backticks.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- `no_cycle` at the end of every cycle: running goes `off` a moment before `last_cycle_end` updates; the alert must not flicker on (Alert2 would notify). Pinned in Task 4 (`test_no_cycle_does_not_flicker_at_a_cycle_end`).
- A plug reconnecting (`running` unavailable → off) is no cycle end: `finished` must not turn on. Pinned in Task 4.
- HA in a language pururu doesn't translate (`de`): the default texts are English. Pinned in Task 3.
- `when: appliance_alert_offline` in a hand-written alert is refused; the same in a reaction is accepted. Pinned in Task 2.
- A restart in the middle of `long_cycle`'s `for`: the time before the restart counts. Pinned in Task 4.

---

## File Structure

- Modify `custom_components/pururu/features/appliance/running.py`: the `cycle_start` attribute.
- Modify `custom_components/pururu/feature.py`: `Condition` (moved from `features/alerts.py`), `Elapsed`, `Preset`, `preset_keys()`, `Feature.alerts`, `Feature.validate()`.
- Create `custom_components/pururu/features/appliance/alerts.py`: `PRESETS`.
- Modify `custom_components/pururu/features/appliance/__init__.py`: `alerts=PRESETS`, preset keys in `entity_keys`.
- Modify `custom_components/pururu/features/alerts.py`: `ProblemAlert` base, `Alert` on it, `Condition` imported.
- Create `custom_components/pururu/features/elapsed.py`: `ElapsedAlert`.
- Create `custom_components/pururu/features/presets.py`: settings schema, default texts, building the enabled alerts.
- Modify `custom_components/pururu/__init__.py`: `feature.validate`, the alert-watching-an-alert rule, `_build` with presets and texts, `_alert2_alerts` from entities.
- Modify translations (`en.json`, `pt-BR.json`) and `icons.json`.
- Tests: create `tests/test_presets.py`; modify `tests/test_features.py`, `tests/test_appliance.py`.
- Docs: `docs/features/appliance.mdx`, `docs/features/alerts.mdx`, `docs/reference/configuration.mdx`, `docs/reference/troubleshooting.mdx`, `docs/develop/writing-a-feature.mdx`, `docs/develop/architecture.mdx`, `CLAUDE.md`; manifest.

---

### Task 1: `appliance_running` shows `cycle_start`

**Files:**
- Modify: `custom_components/pururu/features/appliance/running.py`
- Test: `tests/test_appliance.py`

**Interfaces:**
- Produces: while on, `hass.states.get("binary_sensor.pururu_<key>_appliance_running").attributes["cycle_start"]` is the running cycle's start (a `datetime`, UTC); the key is absent while off.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_appliance.py` (it already imports `datetime`, `timedelta`, `State`, `dt_util`, `restart`):

```python
# --- cycle_start -------------------------------------------------------------


async def test_cycle_start_is_shown_while_running(washer: HomeAssistant, freezer: Any) -> None:
    assert "cycle_start" not in washer.states.get(RUNNING).attributes
    started = dt_util.utcnow() + timedelta(seconds=65)
    await start_cycle(washer, freezer)
    assert washer.states.get(RUNNING).attributes["cycle_start"] == started
    await end_cycle(washer, freezer)
    assert "cycle_start" not in washer.states.get(RUNNING).attributes


async def test_cycle_start_is_kept_across_a_restart(ha: HomeAssistant) -> None:
    since = dt_util.utcnow() - timedelta(minutes=20)
    await restart(ha, DEVICES, (State(RUNNING, "on"),
                                {"since": since.isoformat(), "since_energy": 100.0}))
    assert ha.states.get(RUNNING).attributes["cycle_start"] == since
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_appliance.py -n 0 -q -k cycle_start`
Expected: FAIL, `KeyError: 'cycle_start'`.

- [ ] **Step 3: Add the attribute**

In `Running` (after `extra_restore_state_data`), add:

```python
    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The running cycle's start, while there is one."""
        if not self._attr_is_on or self._data.since is None:
            return None
        return {"cycle_start": self._data.since}
```

Add `from typing import Any` to the imports if it isn't there (keep `override`).

- [ ] **Step 4: Run the appliance tests**

Run: `uv run pytest tests/test_appliance.py -n 0 -q`
Expected: all PASS. (`start_cycle` ticks 65 s from the first reading above the threshold: the cycle starts then.)

- [ ] **Step 5: Commit**

```bash
git add custom_components/pururu/features/appliance/running.py tests/test_appliance.py
git commit -m "pururu: appliance_running shows its cycle's start

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Presets in the contract, the settings, the catalogue

**Files:**
- Modify: `custom_components/pururu/feature.py`
- Modify: `custom_components/pururu/features/alerts.py` (`Condition` moves out)
- Create: `custom_components/pururu/features/presets.py` (settings schema only in this task)
- Create: `custom_components/pururu/features/appliance/alerts.py`
- Modify: `custom_components/pururu/features/appliance/__init__.py`
- Modify: `custom_components/pururu/__init__.py` (`_device`, `_references_resolved`)
- Modify: `custom_components/pururu/translations/en.json`, `pt-BR.json`, `custom_components/pururu/icons.json`
- Test: `tests/test_presets.py`, `tests/test_features.py`

**Interfaces:**
- Produces (in `feature.py`):
  - `Condition(state: str | float | None, above: float | None, below: float | None)` with `holds(state: State | None) -> bool | None` (moved verbatim from `features/alerts.py`).
  - `Elapsed(state: str, since_key: str | None = None, since_attribute: str | None = None, or_since_created: bool = False)`.
  - `Preset(watches: str, kind: Condition | Elapsed, priority: str, hold: timedelta | None, lasts: timedelta | None = None)`.
  - `preset_keys(presets: Mapping[str, Preset]) -> dict[str, Platform]` → `{"alert_<name>": Platform.BINARY_SENSOR}`.
  - `ALERTS_KEY = "alerts"`; `Feature.alerts: Mapping[str, Preset]`; `Feature.validate(value: Any) -> Any`.
- Produces (in `features/presets.py`): `settings_schema(presets: Mapping[str, Preset]) -> Callable[[Any], dict[str, dict[str, Any]]]` — validated settings per enabled alert: `{"for": timedelta, "priority": str, "notify": {...}?}` or, with `lasts`, `{"lasts": timedelta, "priority": str, "notify"?}`.
- Produces (appliance): `features/appliance/alerts.PRESETS: dict[str, Preset]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_presets.py`:

```python
"""Ready-made alerts: an appliance's own, on a made-up washer."""

from typing import Any

from homeassistant.core import HomeAssistant
import pytest

from helpers import setup

KEY = "demo_washer"
POWER = "sensor.demo_plug_power"
APPLIANCE: dict[str, Any] = {
    "power": POWER,
    "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}


def devices(alerts: Any, **device: Any) -> dict[str, Any]:
    return {KEY: {"name": "Demo washer", "appliance": {**APPLIANCE, "alerts": alerts}, **device}}


# --- configuration ------------------------------------------------------------------------


@pytest.mark.parametrize("alerts", [
    pytest.param({"offline": None}, id="null is every default"),
    pytest.param({"offline": {}}, id="empty is every default"),
    pytest.param({"offline": {"for": {"minutes": 1}, "priority": "high",
                              "notify": {"message": "m", "done_message": "d"}}}, id="all set"),
    pytest.param({"long_cycle": {"for": {"hours": 3}}}, id="required for"),
    pytest.param({"no_cycle": {"for": {"days": 2}}}, id="no_cycle"),
    pytest.param({"finished": None, "no_power": None}, id="finished and no_power"),
    pytest.param({"finished": {"lasts": {"minutes": 30}}}, id="lasts"),
])
async def test_valid_alerts_are_accepted(ha: HomeAssistant, alerts: Any) -> None:
    assert await setup(ha, devices(alerts))


@pytest.mark.parametrize(("alerts", "reason"), [
    pytest.param({"nope": None}, "nope is not a ready-made alert: offline, no_power, "
                 "long_cycle, no_cycle, finished", id="unknown alert"),
    pytest.param({"long_cycle": None}, "required key 'for' not provided", id="for missing"),
    pytest.param({"offline": {"lasts": {"minutes": 1}}}, "extra keys not allowed",
                 id="lasts on offline"),
    pytest.param({"finished": {"for": {"minutes": 1}}}, "extra keys not allowed",
                 id="for on finished"),
    pytest.param({"offline": {"priority": "urgent"}}, "value must be one of",
                 id="unknown priority"),
    pytest.param({"offline": {"notify": {"message": "m"}}}, "required key 'done_message'",
                 id="incomplete notify"),
    pytest.param({}, "length of value must be at least 1", id="empty"),
    pytest.param({"offline": {"for": {"minutes": -1}}}, "offline", id="negative for"),
])
async def test_invalid_alerts_are_refused(ha: HomeAssistant, caplog: pytest.LogCaptureFixture,
                                          alerts: Any, reason: str) -> None:
    assert not await setup(ha, devices(alerts))
    assert reason in caplog.text


async def test_a_hand_written_alert_cannot_watch_a_ready_made_one(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    watching = {"it": {"name": "It", "when": "appliance_alert_offline", "is": "on"}}
    assert not await setup(ha, devices({"offline": None}, alerts=watching))
    assert "appliance_alert_offline is an alert: an alert can't watch another" in caplog.text


async def test_a_reaction_can_react_to_a_ready_made_alert(ha: HomeAssistant) -> None:
    reaction = {"off": {"name": "Offline", "when": "appliance_alert_offline", "to": "on"}}
    assert await setup(ha, devices({"offline": None}, reactions=reaction))
```

In `tests/test_features.py`, add after `test_every_per_item_name_has_its_placeholder`:

```python
def test_ready_made_alerts_line_up(features: dict[str, Any]) -> None:
    """Every ready-made alert is an entity key, watches its own feature's, has both texts, validates."""
    feature_module = module("feature")
    en, pt = load("translations/en.json"), load("translations/pt-BR.json")
    for name, feature in features.items():
        if not feature.alerts:
            continue
        assert feature_module.preset_keys(feature.alerts).items() <= feature.entity_keys.items(), name
        settings = {}
        for alert, preset in feature.alerts.items():
            assert cv.slug(alert) == alert, name
            assert preset.watches in feature.entity_keys, f"{name}: {alert}"
            if isinstance(preset.kind, feature_module.Elapsed) and preset.kind.since_key:
                assert preset.kind.since_key in feature.entity_keys, f"{name}: {alert}"
            key = feature_module.qualified(feature.namespace, f"alert_{alert}")
            for translations in (en, pt):
                assert translations["common"][f"{key}_message"], key
                assert translations["common"][f"{key}_done_message"], key
            settings[alert] = {} if preset.hold is not None or preset.lasts else {"for": {"hours": 1}}
        feature.validate({**feature.example, "alerts": settings})
        with pytest.raises(vol.Invalid):
            feature.validate({**feature.example, "alerts": {"not_an_alert": None}})
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_presets.py tests/test_features.py -n 0 -q`
Expected: the valid-alerts tests FAIL (`extra keys not allowed … alerts`); `test_ready_made_alerts_line_up` passes vacuously or fails on `feature.validate` missing — either way not all green.

- [ ] **Step 3: Move `Condition` to `feature.py` and add the preset types**

In `custom_components/pururu/features/alerts.py`, cut the `Condition` class and `NO_READING` constant, and add to its imports `from ..feature import Condition` (keep `TEXT, Device, Feature, finite_float, state_text`). `Alert` and `build` use `Condition` unchanged.

In `custom_components/pururu/feature.py`, add to the imports:

```python
from datetime import timedelta

from homeassistant.const import (
    ATTR_RESTORED,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import HomeAssistant, State
```

(`State` next to `HomeAssistant`; `ATTR_RESTORED`, `STATE_UNAVAILABLE`, `STATE_UNKNOWN` join `STATE_OFF, STATE_ON, Platform`.) The `reading` helper lives in `entity.py`, which imports `feature.py`: define `Condition` so it doesn't need `entity.py` — paste it with a local copy of the number parsing:

```python
# States that are no reading, unless the condition is about them
NO_READING = (STATE_UNAVAILABLE, STATE_UNKNOWN)


def _number(state: State) -> float | None:
    """A state's finite number, or None (entity.reading, which imports this module)."""
    try:
        value = float(state.state)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


@dataclass(frozen=True, kw_only=True)
class Condition:
    """What makes the watched entity's state a problem: a state, a number, or a range."""

    state: str | float | None = None
    above: float | None = None
    below: float | None = None

    def holds(self, state: State | None) -> bool | None:
        """Whether `state` is a problem; None when it is no reading.

        A condition on unavailable or unknown holds while the entity has no
        reading, either state or missing: a plug reconnecting passes from one to
        the other. A state HA restored for an entity not loaded yet (at start,
        during a reload) is no reading, for every condition.
        """
        if state is not None and state.attributes.get(ATTR_RESTORED):
            return None
        if isinstance(self.state, str):
            return self._is(STATE_UNAVAILABLE if state is None else state.state)
        if state is None or (value := _number(state)) is None:
            return None
        if self.state is not None:  # a number
            return value == self.state
        return (self.above is None or value > self.above) and (
            self.below is None or value < self.below
        )

    def _is(self, current: str) -> bool | None:
        """`is` a state: no reading for other states, unless it is about no reading."""
        if self.state in NO_READING:
            return current in NO_READING
        if current in NO_READING:
            return None
        return current == self.state


@dataclass(frozen=True, kw_only=True)
class Elapsed:
    """On while the watched entity is `state` and the time since a milestone is in [for, for + lasts).

    The milestone is the state (a datetime) of `since_key`, an entity key of the
    feature, or the watched entity's attribute `since_attribute`: exactly one.
    With `or_since_created`, an alert with no milestone yet counts from its creation.
    """

    state: str
    since_key: str | None = None
    since_attribute: str | None = None
    or_since_created: bool = False


@dataclass(frozen=True, kw_only=True)
class Preset:
    """A ready-made alert of a feature: off until the feature's block enables it."""

    # The entity key, in the feature's namespace, it watches
    watches: str
    kind: Condition | Elapsed
    priority: str
    # The default `for`; None: the user gives it. An alert with `lasts` takes no `for`
    hold: timedelta | None
    # How long it stays on after its milestone; the user may change it
    lasts: timedelta | None = None


# The key of a feature's block that enables its ready-made alerts
ALERTS_KEY = "alerts"


def preset_keys(presets: Mapping[str, Preset]) -> dict[str, Platform]:
    """The entity keys of a feature's ready-made alerts: alert_<name>, binary sensors."""
    return {f"alert_{name}": Platform.BINARY_SENSOR for name in presets}
```

(`entity.reading` stays as it is; `features/alerts.py` imported `reading` only for `Condition` — remove that import if ruff flags it unused.)

In `Feature`, add the field after `items`:

```python
    # Ready-made alerts it offers, by name: each enabled one is the entity key
    # alert_<name> (put preset_keys in entity_keys), enabled in its block's `alerts`
    alerts: Mapping[str, "Preset"] = field(default_factory=dict)

    def validate(self, value: Any) -> Any:
        """Its block: `schema`, and `alerts` when it offers ready-made alerts."""
        if not self.alerts or not isinstance(value, dict) or ALERTS_KEY not in value:
            return self.schema(value)
        from .features.presets import settings_schema  # noqa: PLC0415 - features import this module

        block = {key: each for key, each in value.items() if key != ALERTS_KEY}
        enabled = vol.Schema({ALERTS_KEY: settings_schema(self.alerts)})(
            {ALERTS_KEY: value[ALERTS_KEY]}
        )
        return {**self.schema(block), **enabled}
```

(Define `Condition`, `Elapsed`, `Preset`, `ALERTS_KEY`, `preset_keys` above `Feature`; then the annotation needs no quotes — use `Mapping[str, Preset]`.)

- [ ] **Step 4: The settings schema (`features/presets.py`)**

```python
"""Ready-made alerts: the settings that enable them, and the alerts they build.

A feature offers them (Feature.alerts); its block's `alerts` enables each one
with one key, its defaults and texts ready.
"""

from collections.abc import Callable, Mapping
from typing import Any

import voluptuous as vol

from homeassistant.helpers import config_validation as cv

from ..feature import Preset
from .alerts import NOTIFY, PRIORITIES


def _settings(preset: Preset) -> vol.Schema:
    """What one alert takes: for (or lasts), priority, notify."""
    timing: dict[Any, Any]
    if preset.lasts is not None:
        timing = {vol.Optional("lasts", default=preset.lasts): cv.positive_time_period}
    elif preset.hold is None:
        timing = {vol.Required("for"): cv.positive_time_period}
    else:
        timing = {vol.Optional("for", default=preset.hold): cv.positive_time_period}
    return vol.Schema(
        {
            **timing,
            vol.Optional("priority", default=preset.priority): vol.In(PRIORITIES),
            vol.Optional("notify"): NOTIFY,
        }
    )


def settings_schema(
    presets: Mapping[str, Preset],
) -> Callable[[Any], dict[str, dict[str, Any]]]:
    """The block's `alerts`: ready-made alert -> its settings; null is every default."""
    known = ", ".join(presets)
    each = {name: _settings(preset) for name, preset in presets.items()}

    def validate(value: Any) -> dict[str, dict[str, Any]]:
        alerts = vol.All(vol.Schema({cv.slug: vol.Any(None, dict)}), vol.Length(min=1))(
            value
        )
        enabled: dict[str, dict[str, Any]] = {}
        for name, settings in alerts.items():
            if name not in each:
                raise vol.Invalid(
                    f"{name} is not a ready-made alert: {known}", path=[name]
                )
            enabled[name] = vol.Schema({name: each[name]})(
                {name: settings or {}}
            )[name]
        return enabled

    return validate
```

`features/alerts.py` must export `NOTIFY` and `PRIORITIES` (it defines both today).

- [ ] **Step 5: The appliance's catalogue**

Create `custom_components/pururu/features/appliance/alerts.py`:

```python
"""The appliance's ready-made alerts: its plug, its cycles."""

from datetime import timedelta

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE

from ...feature import Condition, Elapsed, Preset

PRESETS: dict[str, Preset] = {
    # The plug has no reading
    "offline": Preset(
        watches="power",
        kind=Condition(state=STATE_UNAVAILABLE),
        priority="medium",
        hold=timedelta(minutes=10),
    ),
    # It draws nothing: for an appliance that always draws something
    "no_power": Preset(
        watches="power",
        kind=Condition(state=0.0),
        priority="medium",
        hold=timedelta(minutes=10),
    ),
    "long_cycle": Preset(
        watches="running",
        kind=Elapsed(state=STATE_ON, since_attribute="cycle_start"),
        priority="medium",
        hold=None,
    ),
    "no_cycle": Preset(
        watches="running",
        kind=Elapsed(state=STATE_OFF, since_key="last_cycle_end", or_since_created=True),
        priority="medium",
        hold=None,
    ),
    "finished": Preset(
        watches="running",
        kind=Elapsed(state=STATE_OFF, since_key="last_cycle_end"),
        priority="low",
        hold=timedelta(0),
        lasts=timedelta(hours=1),
    ),
}
```

In `features/appliance/__init__.py`: import `from ...feature import Device, Feature, finite_float, preset_keys` and `from .alerts import PRESETS`; set `entity_keys={**ENTITY_KEYS, **preset_keys(PRESETS)}` and add `alerts=PRESETS,` to `APPLIANCE`.

- [ ] **Step 6: The core validates with it, and refuses an alert watching an alert**

In `custom_components/pururu/__init__.py`, in `_device`, change

```python
        **{vol.Optional(name): feature.schema for name, feature in FEATURES.items()},
```
to
```python
        **{vol.Optional(name): feature.validate for name, feature in FEATURES.items()},
```

In `_references_resolved`, inside `for key in feature.refers(device[name]):`, after the existing `owners.get(key, name) == name` check, add:

```python
            owner = FEATURES[owners[key]]
            if name == CONF_ALERTS and key in {
                qualified(owner.namespace, alert) for alert in preset_keys(owner.alerts)
            }:
                raise vol.Invalid(
                    f"{name}: {key} is an alert: an alert can't watch another"
                )
```

and import `preset_keys` from `.feature` (next to `Device, qualified`).

- [ ] **Step 7: Names, icons, texts**

In `translations/en.json`, under `entity.binary_sensor`, add:

```json
      "appliance_alert_offline": {"name": "Offline"},
      "appliance_alert_no_power": {"name": "No power"},
      "appliance_alert_long_cycle": {"name": "Long cycle"},
      "appliance_alert_no_cycle": {"name": "No cycle"},
      "appliance_alert_finished": {"name": "Finished"}
```

and under `common`:

```json
    "appliance_alert_offline_message": "The plug is offline.",
    "appliance_alert_offline_done_message": "The plug is back.",
    "appliance_alert_no_power_message": "There's no power.",
    "appliance_alert_no_power_done_message": "Power is back.",
    "appliance_alert_long_cycle_message": "The cycle is taking too long.",
    "appliance_alert_long_cycle_done_message": "The cycle ended.",
    "appliance_alert_no_cycle_message": "It hasn't run in a while.",
    "appliance_alert_no_cycle_done_message": "It's running again.",
    "appliance_alert_finished_message": "The cycle finished.",
    "appliance_alert_finished_done_message": "Done."
```

In `pt-BR.json`, the same keys: names `Sem conexão`, `Sem energia`, `Ciclo longo`, `Sem ciclo`, `Terminou`; texts `A tomada está sem conexão.` / `A tomada voltou.`, `Está sem energia.` / `A energia voltou.`, `O ciclo está demorando demais.` / `O ciclo terminou.`, `Não roda há um tempo.` / `Voltou a rodar.`, `O ciclo terminou.` / `Pronto.`.

In `icons.json`, under `entity.binary_sensor`:

```json
      "appliance_alert_offline": {"default": "mdi:power-plug-off-outline"},
      "appliance_alert_no_power": {"default": "mdi:flash-off-outline"},
      "appliance_alert_long_cycle": {"default": "mdi:timer-alert-outline"},
      "appliance_alert_no_cycle": {"default": "mdi:sleep"},
      "appliance_alert_finished": {"default": "mdi:check-circle-outline"}
```

(Keep each file's existing formatting; validate with `python3 -m json.tool` on each.)

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/test_presets.py tests/test_features.py tests/test_alerts.py tests/test_appliance.py -n 0 -q`
Expected: all PASS. If a refusal test's message differs only by voluptuous' path formatting, fix the expected substring to the real message and keep the rest; ledger it as a ruling.

- [ ] **Step 9: Lint, type-check, commit**

Run: `uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu && uv run mypy custom_components/pururu`
Expected: no errors.

```bash
git add custom_components/pururu tests/test_presets.py tests/test_features.py
git commit -m "pururu: a feature's ready-made alerts, in its contract and its block

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Condition presets built, default texts, Alert2 from entities

**Files:**
- Modify: `custom_components/pururu/features/alerts.py` (`ProblemAlert`, `Alert` on it)
- Modify: `custom_components/pururu/features/presets.py` (texts, build)
- Modify: `custom_components/pururu/__init__.py` (`_build`, `async_setup_entry`, `_alert2_alerts`)
- Test: `tests/test_presets.py`, `tests/test_alert2.py` (must stay green unchanged)

**Interfaces:**
- Consumes: Task 2's `Preset`, `Condition`, `Elapsed`, `ALERTS_KEY`, `PRESETS`.
- Produces:
  - `features/alerts.ProblemAlert` with public `priority: str`, `notify: Mapping[str, str] | None`, `_follow(self) -> None` (abstract hook called once HA has started), `_set(*, on: bool)`, `_cancel()`.
  - `features/alerts.Alert(device, entity_key, *, name: str | None, watched: str, condition: Condition, hold: timedelta, priority: str, notify: Mapping[str, str] | None, follows: tuple[str, ...] = (), sources: tuple[str, ...] = ())`.
  - `features/presets.Texts = Mapping[str, str]` (common key → text); `async def async_texts(hass) -> Texts`; `def build(hass, device: Device, feature: Feature, block: Mapping[str, Any], texts: Texts) -> list[PururuEntity]`.
  - `__init__._build(hass, key, config, texts)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_presets.py` (imports: add `from datetime import timedelta`, `from pathlib import Path`, `import yaml`, `from homeassistant.core import State`, and `fake, held, restart, tick` from `helpers`):

```python
# --- condition alerts ---------------------------------------------------------------------


def alert(name: str) -> str:
    return f"binary_sensor.pururu_{KEY}_appliance_alert_{name}"


def state(ha: HomeAssistant, entity_id: str) -> str:
    found = ha.states.get(entity_id)
    assert found is not None, entity_id
    return found.state


async def test_only_enabled_alerts_are_created(ha: HomeAssistant) -> None:
    assert await setup(ha, devices({"offline": None}))
    assert alert("offline") in held(ha, KEY)
    assert ha.states.get(alert("no_power")) is None


async def test_offline_turns_on_after_ten_minutes_without_a_reading(
        ha: HomeAssistant, freezer: Any) -> None:
    assert await setup(ha, devices({"offline": None}))
    await fake(ha, POWER, "3")
    await fake(ha, POWER, "unavailable")
    await tick(ha, freezer, 599)
    assert state(ha, alert("offline")) == "off"
    await tick(ha, freezer, 1)
    assert state(ha, alert("offline")) == "on"
    await fake(ha, POWER, "3")
    assert state(ha, alert("offline")) == "off"


async def test_no_power_turns_on_at_zero_and_keeps_its_state_without_a_reading(
        ha: HomeAssistant, freezer: Any) -> None:
    assert await setup(ha, devices({"no_power": {"for": {"minutes": 1}}}))
    await fake(ha, POWER, "0.0")
    await tick(ha, freezer, 60)
    assert state(ha, alert("no_power")) == "on"
    await fake(ha, POWER, "unavailable")
    assert state(ha, alert("no_power")) == "on"
    await fake(ha, POWER, "0.4")
    assert state(ha, alert("no_power")) == "off"


async def test_its_name_attributes_and_default_texts(ha: HomeAssistant) -> None:
    assert await setup(ha, devices({"offline": {"priority": "high"}}))
    found = ha.states.get(alert("offline"))
    assert found.attributes["friendly_name"] == "Demo washer Offline"
    assert found.attributes["device_class"] == "problem"
    assert found.attributes["priority"] == "high"
    assert found.attributes["watches"] == "sensor.pururu_demo_washer_appliance_power"
    assert found.attributes["message"] == "The plug is offline."
    assert found.attributes["done_message"] == "The plug is back."


async def test_default_texts_in_the_language_of_home_assistant(ha: HomeAssistant) -> None:
    ha.config.language = "pt-BR"
    assert await setup(ha, devices({"offline": None}))
    found = ha.states.get(alert("offline"))
    assert found.attributes["message"] == "A tomada está sem conexão."
    assert found.attributes["done_message"] == "A tomada voltou."


async def test_a_language_without_translations_gets_english_texts(ha: HomeAssistant) -> None:
    ha.config.language = "de"
    assert await setup(ha, devices({"offline": None}))
    assert ha.states.get(alert("offline")).attributes["message"] == "The plug is offline."


async def test_notify_replaces_the_default_texts(ha: HomeAssistant) -> None:
    notify = {"message": "Sem Wi-Fi!", "done_message": "Voltou."}
    assert await setup(ha, devices({"offline": {"notify": notify}}))
    found = ha.states.get(alert("offline"))
    assert found.attributes["message"] == "Sem Wi-Fi!"
    assert found.attributes["done_message"] == "Voltou."


async def test_it_is_an_alert2_alert(ha: HomeAssistant) -> None:
    assert await setup(ha, devices({"offline": None}))
    path = Path(ha.config.path("pururu/alert2/alerts.yaml"))
    [entry] = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert entry == {
        "domain": "pururu",
        "name": "demo_washer_appliance_alert_offline",
        "friendly_name": "Demo washer Offline",
        "condition_on": f"{{{{ is_state('{alert('offline')}', 'on') }}}}",
        "condition_off": f"{{{{ is_state('{alert('offline')}', 'off') }}}}",
        "priority": "medium",
        "message": "The plug is offline.",
        "done_message": "The plug is back.",
    }


async def test_a_ready_made_alert_comes_back_as_it_was(ha: HomeAssistant) -> None:
    await restart(ha, devices({"offline": None}), (State(alert("offline"), "on"), {}))
    assert state(ha, alert("offline")) == "on"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_presets.py -n 0 -q`
Expected: the new tests FAIL (no `binary_sensor.pururu_demo_washer_appliance_alert_*`).

- [ ] **Step 3: `ProblemAlert` and `Alert` on it (`features/alerts.py`)**

Replace the `Alert` class with:

```python
class ProblemAlert(PururuEntity, BinarySensorEntity, RestoreEntity):
    """On while something is wrong: what it watches, its priority, what to tell.

    Restores its state; follows what it watches once HA has started (entities
    pass through unavailable while it starts).
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self, *, watched: str, priority: str, notify: Mapping[str, str] | None
    ) -> None:
        """Watch `watched`; `notify` is what Alert2 tells."""
        self._watched = watched
        self.priority = priority
        self.notify = notify
        self._attr_is_on = False
        self._attr_extra_state_attributes = {
            "priority": priority,
            "watches": watched,
            **(notify or {}),
        }
        self._pending: CALLBACK_TYPE | None = None

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the state, then follow what it watches once HA has started."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == STATE_ON
        self.async_on_remove(self._cancel)
        self.async_on_remove(async_at_started(self.hass, self._start))

    @callback
    def _start(self, _hass: HomeAssistant) -> None:
        """Follow; also the time to know whether Alert2, which delivers `notify`, is set up."""
        if self.notify is not None and ALERT2 not in self.hass.config.components:
            _LOGGER.error(
                "%s has notify, but Alert2 isn't set up to deliver it", self.entity_id
            )
        self._follow()

    @callback
    def _follow(self) -> None:
        """Track what it watches and evaluate it now."""
        raise NotImplementedError

    @callback
    def _cancel(self) -> None:
        if self._pending is not None:
            self._pending()
            self._pending = None

    @callback
    def _set(self, *, on: bool) -> None:
        if on != self._attr_is_on:
            self._attr_is_on = on
            self.async_write_ha_state()


class Alert(ProblemAlert):
    """On while its condition holds, after `for`; holds while the watched entity has no reading."""

    def __init__(
        self,
        device: Device,
        entity_key: str,
        *,
        name: str | None,
        watched: str,
        condition: Condition,
        hold: timedelta,
        priority: str,
        notify: Mapping[str, str] | None,
        follows: tuple[str, ...] = (),
        sources: tuple[str, ...] = (),
    ) -> None:
        """Watch `watched` for `condition` held for `hold`; `name` None: translated."""
        super().__init__(watched=watched, priority=priority, notify=notify)
        self._identify(device, Platform.BINARY_SENSOR, entity_key, name)
        self.follows = follows
        self.sources = sources
        self._condition = condition
        self._hold = hold

    @override
    @callback
    def _follow(self) -> None:
        self.async_on_remove(
            async_track_state_change_event(self.hass, self._watched, self._changed)
        )
        # Not there yet, as the device's other platforms set up alongside: no reading
        if (state := self.hass.states.get(self._watched)) is not None:
            self._evaluate(state)

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        self._evaluate(event.data["new_state"])

    @callback
    def _evaluate(self, state: State | None) -> None:
        """Turn off at once, start `for` towards on, or, without a reading, keep the state."""
        holds = self._condition.holds(state)
        if not holds:
            self._cancel()
            if holds is False:
                self._set(on=False)
        elif not self._attr_is_on and self._pending is None:
            if self._hold:
                self._pending = async_call_later(self.hass, self._hold, self._turn_on)
            else:
                self._set(on=True)

    @callback
    def _turn_on(self, _now: datetime) -> None:
        self._pending = None
        self._set(on=True)
```

In `build` of `features/alerts.py`, the call becomes `Alert(device, entity_key, name=alert["name"], watched=inputs[alert["when"]], condition=…, hold=alert["for"], priority=alert["priority"], notify=alert.get("notify"), follows=(alert["when"],))` (drop `when=`).

- [ ] **Step 4: Texts and building (`features/presets.py`)**

Add to the imports:

```python
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from ..const import DOMAIN
from ..entity import PururuEntity
from ..feature import ALERTS_KEY, Condition, Device, Elapsed, Feature, Preset
from .alerts import NOTIFY, PRIORITIES, Alert
```

and append:

```python
# Default texts, by their key in the translations' common block
type Texts = Mapping[str, str]
FALLBACK_LANGUAGE = "en"


async def async_texts(hass: HomeAssistant) -> Texts:
    """The common texts in HA's language; English for what it lacks."""
    prefix = f"component.{DOMAIN}.common."
    english = await async_get_translations(hass, FALLBACK_LANGUAGE, "common", [DOMAIN])
    local = await async_get_translations(hass, hass.config.language, "common", [DOMAIN])
    return {
        key.removeprefix(prefix): local.get(key) or text
        for key, text in english.items()
        if key.startswith(prefix)
    }


def _notify(device: Device, entity_key: str, settings: Mapping[str, Any], texts: Texts) -> dict[str, str]:
    """The user's notify, or the default texts of this alert."""
    if "notify" in settings:
        return dict(settings["notify"])
    key = device.qualified(entity_key)
    return {
        "message": texts[f"{key}_message"],
        "done_message": texts[f"{key}_done_message"],
    }


def build(
    hass: HomeAssistant,
    device: Device,
    feature: Feature,
    block: Mapping[str, Any],
    texts: Texts,
) -> list[PururuEntity]:
    """The block's enabled ready-made alerts, in the feature's namespace."""
    entities: list[PururuEntity] = []
    for name, settings in block.get(ALERTS_KEY, {}).items():
        preset = feature.alerts[name]
        entity_key = f"alert_{name}"
        watched = device.current_entity_id(
            hass, feature.entity_keys[preset.watches], preset.watches
        )
        notify = _notify(device, entity_key, settings, texts)
        if isinstance(preset.kind, Condition):
            entities.append(
                Alert(
                    device,
                    entity_key,
                    name=None,
                    watched=watched,
                    condition=preset.kind,
                    hold=settings["for"],
                    priority=settings["priority"],
                    notify=notify,
                    sources=(preset.watches,),
                )
            )
    return entities
```

(`Elapsed` presets are built in Task 4; until then they are skipped here, and Task 2's tests that enable them only validate.)

- [ ] **Step 5: The core builds them and writes Alert2 from the entities (`__init__.py`)**

Import `from .features import FEATURES, presets` (or `from .features import presets`) and `from .features.alerts import ProblemAlert`; `ATTR_FRIENDLY_NAME` from `homeassistant.const`.

In `async_setup_entry`, before the device loop: `texts = await presets.async_texts(hass)`, and pass it: `_build(hass, key, config, texts)`.

`_build` gains `texts: presets.Texts` and, in its per-feature loop, iterates:

```python
        for entity in (
            *feature.build(hass, device, config[name], inputs),
            *presets.build(hass, device, feature, config[name], texts),
        ):
```

Replace `_alert2_alerts(hass, devices, created)` by `_alert2_alerts(hass, built)`, called as `alert2_alerts.async_sync(hass, entry, _alert2_alerts(hass, built))`, and rewrite it:

```python
def _alert2_alerts(
    hass: HomeAssistant, built: dict[Platform, list[Entity]]
) -> list[dict[str, Any]]:
    """An Alert2 alert per created alert with notify, hand-written or ready-made.

    Named as HA shows it: its device's name and its own, translated or not.
    """
    alerts: list[dict[str, Any]] = []
    for entity in built[Platform.BINARY_SENSOR]:
        if not isinstance(entity, ProblemAlert) or entity.notify is None:
            continue
        state = hass.states.get(entity.entity_id)
        name = state.attributes.get(ATTR_FRIENDLY_NAME) if state else None
        alerts.append(
            alert2_alerts.alert(
                str(entity.unique_id),
                entity.entity_id,
                str(name or entity.entity_id),
                entity.priority,
                entity.notify,
            )
        )
    return alerts
```

Remove the now-unused `CONF_ALERTS` import only if nothing else uses it (Task 2's `_references_resolved` does: keep it).

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_presets.py tests/test_alerts.py tests/test_alert2.py tests/test_reactions.py -n 0 -q`
Expected: all PASS — `tests/test_alert2.py` unchanged (hand-written alerts give the same entries, in the same order).

- [ ] **Step 7: Lint, type-check, commit**

Run: `uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu && uv run mypy custom_components/pururu`

```bash
git add custom_components/pururu tests/test_presets.py
git commit -m "pururu: an appliance's offline and no_power, ready-made

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Time since a milestone: `long_cycle`, `no_cycle`, `finished`

**Files:**
- Create: `custom_components/pururu/features/elapsed.py`
- Modify: `custom_components/pururu/features/presets.py` (build `Elapsed`)
- Test: `tests/test_presets.py`

**Interfaces:**
- Consumes: `ProblemAlert` (Task 3), `Elapsed` (Task 2), `cycle_start` (Task 1).
- Produces: `features/elapsed.ElapsedAlert(device, entity_key, *, watched: str, milestone: str | None, elapsed: Elapsed, hold: timedelta, lasts: timedelta | None, priority: str, notify: Mapping[str, str] | None, sources: tuple[str, ...])`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_presets.py`:

```python
# --- time since a milestone ---------------------------------------------------------------

RUNNING = f"binary_sensor.pururu_{KEY}_appliance_running"
LAST_END = f"sensor.pururu_{KEY}_appliance_last_cycle_end"


async def start_cycle(ha: HomeAssistant, freezer: Any) -> None:
    await fake(ha, POWER, "120")
    await tick(ha, freezer, 65)
    assert state(ha, RUNNING) == "on"


async def end_cycle(ha: HomeAssistant, freezer: Any) -> None:
    await fake(ha, POWER, "1")
    await tick(ha, freezer, 125)
    assert state(ha, RUNNING) == "off"


async def idle(ha: HomeAssistant, freezer: Any, alerts: Any) -> None:
    assert await setup(ha, devices(alerts))
    await fake(ha, POWER, "1")
    await tick(ha, freezer, 125)


async def test_long_cycle_turns_on_after_for_and_off_when_the_cycle_ends(
        ha: HomeAssistant, freezer: Any) -> None:
    await idle(ha, freezer, {"long_cycle": {"for": {"hours": 1}}})
    await start_cycle(ha, freezer)
    await tick(ha, freezer, 3599)
    assert state(ha, alert("long_cycle")) == "off"
    await tick(ha, freezer, 1)
    assert state(ha, alert("long_cycle")) == "on"
    await end_cycle(ha, freezer)
    assert state(ha, alert("long_cycle")) == "off"


async def test_long_cycle_counts_the_time_before_a_restart(ha: HomeAssistant, freezer: Any) -> None:
    from homeassistant.util import dt as dt_util  # noqa: PLC0415
    since = dt_util.utcnow() - timedelta(minutes=50)
    await restart(ha, devices({"long_cycle": {"for": {"hours": 1}}}),
                  (State(RUNNING, "on"), {"since": since.isoformat(), "since_energy": None}))
    await fake(ha, POWER, "120")
    await tick(ha, freezer, 599)
    assert state(ha, alert("long_cycle")) == "off"
    await tick(ha, freezer, 1)
    assert state(ha, alert("long_cycle")) == "on"


async def test_no_cycle_counts_from_its_creation_without_a_cycle(
        ha: HomeAssistant, freezer: Any) -> None:
    await idle(ha, freezer, {"no_cycle": {"for": {"hours": 2}}})
    await tick(ha, freezer, 2 * 3600 - 125 - 1)
    assert state(ha, alert("no_cycle")) == "off"
    await tick(ha, freezer, 1)
    assert state(ha, alert("no_cycle")) == "on"
    await start_cycle(ha, freezer)
    assert state(ha, alert("no_cycle")) == "off"


async def test_no_cycle_counts_from_the_last_cycles_end(ha: HomeAssistant, freezer: Any) -> None:
    await idle(ha, freezer, {"no_cycle": {"for": {"hours": 2}}})
    await start_cycle(ha, freezer)
    await end_cycle(ha, freezer)
    await tick(ha, freezer, 7199)
    assert state(ha, alert("no_cycle")) == "off"
    await tick(ha, freezer, 1)
    assert state(ha, alert("no_cycle")) == "on"


async def test_no_cycle_does_not_flicker_at_a_cycle_end(ha: HomeAssistant, freezer: Any) -> None:
    """Running goes off before last_cycle_end is written: the old end must not turn it on."""
    from helpers import capture  # noqa: PLC0415
    await idle(ha, freezer, {"no_cycle": {"for": {"hours": 1}}})
    await tick(ha, freezer, 3600)
    assert state(ha, alert("no_cycle")) == "on"
    await start_cycle(ha, freezer)
    changes = capture(ha, "state_changed")
    await end_cycle(ha, freezer)
    assert [e.data["new_state"].state for e in changes
            if e.data["entity_id"] == alert("no_cycle")] == []


async def test_no_cycle_counts_across_a_restart(ha: HomeAssistant, freezer: Any) -> None:
    from homeassistant.util import dt as dt_util  # noqa: PLC0415
    end = dt_util.utcnow() - timedelta(minutes=50)
    await restart(ha, devices({"no_cycle": {"for": {"hours": 1}}}),
                  (State(RUNNING, "off"), {"since": None, "since_energy": None}),
                  (State(LAST_END, end.isoformat()),
                   {"native_value": end.isoformat(), "native_unit_of_measurement": None}))
    await fake(ha, POWER, "1")
    await tick(ha, freezer, 599)
    assert state(ha, alert("no_cycle")) == "off"
    await tick(ha, freezer, 1)
    assert state(ha, alert("no_cycle")) == "on"


async def test_finished_turns_on_at_the_end_and_off_after_lasts(
        ha: HomeAssistant, freezer: Any) -> None:
    await idle(ha, freezer, {"finished": {"lasts": {"minutes": 30}}})
    assert state(ha, alert("finished")) == "off"
    await start_cycle(ha, freezer)
    await end_cycle(ha, freezer)
    assert state(ha, alert("finished")) == "on"
    await tick(ha, freezer, 1799)
    assert state(ha, alert("finished")) == "on"
    await tick(ha, freezer, 1)
    assert state(ha, alert("finished")) == "off"


async def test_finished_turns_off_when_a_new_cycle_starts(ha: HomeAssistant, freezer: Any) -> None:
    await idle(ha, freezer, {"finished": None})
    await start_cycle(ha, freezer)
    await end_cycle(ha, freezer)
    await start_cycle(ha, freezer)
    assert state(ha, alert("finished")) == "off"


async def test_a_plug_reconnecting_is_no_finished_cycle(ha: HomeAssistant, freezer: Any) -> None:
    await idle(ha, freezer, {"finished": None})
    ha.states.async_set(RUNNING, "unavailable")
    await fake(ha, RUNNING, "off")
    assert state(ha, alert("finished")) == "off"


async def test_time_alerts_watch_running_and_are_alert2_alerts(ha: HomeAssistant) -> None:
    assert await setup(ha, devices({"finished": None}))
    found = ha.states.get(alert("finished"))
    assert found.attributes["watches"] == RUNNING
    assert found.attributes["priority"] == "low"
    assert found.attributes["message"] == "The cycle finished."
    path = Path(ha.config.path("pururu/alert2/alerts.yaml"))
    [entry] = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert entry["name"] == "demo_washer_appliance_alert_finished"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_presets.py -n 0 -q -k "cycle or finished or reconnecting or time_alerts"`
Expected: FAIL (the alerts aren't created).

- [ ] **Step 3: `ElapsedAlert` (`features/elapsed.py`)**

```python
"""An alert on the time since a milestone: a cycle's start or end, or its own creation.

Measured from a datetime HA keeps across restarts, so a restart in between
starts nothing over.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Self, override

from homeassistant.const import ATTR_RESTORED, STATE_UNAVAILABLE, STATE_UNKNOWN, Platform
from homeassistant.core import Event, EventStateChangedData, State, callback
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.restore_state import ExtraStoredData
from homeassistant.util import dt as dt_util

from ..feature import Device, Elapsed
from .alerts import ProblemAlert

NO_READING = (STATE_UNAVAILABLE, STATE_UNKNOWN)


@dataclass
class Created(ExtraStoredData):
    """When the alert was first created: its milestone until there is one."""

    at: datetime | None = None

    @override
    def as_dict(self) -> dict[str, Any]:
        return {"at": self.at.isoformat() if self.at else None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        at = data.get("at")
        return cls(at=dt_util.parse_datetime(at) if isinstance(at, str) else None)


def _datetime(value: Any) -> datetime | None:
    """A milestone read from a state or an attribute."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return dt_util.parse_datetime(value)
    return None


class ElapsedAlert(ProblemAlert):
    """On while the watched entity is in its state and the time since the milestone is in [for, for + lasts)."""

    def __init__(
        self,
        device: Device,
        entity_key: str,
        *,
        watched: str,
        milestone: str | None,
        elapsed: Elapsed,
        hold: timedelta,
        lasts: timedelta | None,
        priority: str,
        notify: Mapping[str, str] | None,
        sources: tuple[str, ...],
    ) -> None:
        """`milestone`: the entity whose state is the milestone; None: the watched one's attribute."""
        super().__init__(watched=watched, priority=priority, notify=notify)
        self._identify(device, Platform.BINARY_SENSOR, entity_key)
        self.sources = sources
        self._milestone = milestone
        self._elapsed = elapsed
        self._hold = hold
        self._lasts = lasts
        self._created = Created()
        # When this entity saw the watched one enter its state: newer than a
        # milestone not written yet (running goes off before last_cycle_end is)
        self._entered: datetime | None = None

    @property
    @override
    def extra_restore_state_data(self) -> Created:
        return self._created

    @override
    async def async_added_to_hass(self) -> None:
        if (extra := await self.async_get_last_extra_data()) is not None:
            self._created = Created.from_dict(extra.as_dict())
        if self._created.at is None:
            self._created = Created(at=dt_util.utcnow())
        await super().async_added_to_hass()

    @override
    @callback
    def _follow(self) -> None:
        followed = [self._watched, *([self._milestone] if self._milestone else [])]
        self.async_on_remove(
            async_track_state_change_event(self.hass, followed, self._changed)
        )
        self._evaluate()

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        data = event.data
        old, new = data["old_state"], data["new_state"]
        if (
            data["entity_id"] == self._watched
            and new is not None
            and new.state == self._elapsed.state
            and old is not None
            and old.state not in (*NO_READING, self._elapsed.state)
            and not old.attributes.get(ATTR_RESTORED)
        ):
            self._entered = new.last_changed
        self._evaluate()

    def _since(self, watched: State) -> datetime | None:
        """The milestone: the newest of what the entities say and what this one saw."""
        if self._milestone is None:
            said = _datetime(watched.attributes.get(self._elapsed.since_attribute or ""))
        else:
            state = self.hass.states.get(self._milestone)
            said = _datetime(state.state) if state is not None else None
        if said is None and self._elapsed.or_since_created:
            said = self._created.at
        known = [each for each in (said, self._entered) if each is not None]
        return max(known) if known else None

    @callback
    def _evaluate(self, _now: datetime | None = None) -> None:
        """Set the state for now and schedule the next change; without a reading, keep it."""
        self._cancel()
        watched = self.hass.states.get(self._watched)
        if (
            watched is None
            or watched.state in NO_READING
            or watched.attributes.get(ATTR_RESTORED)
        ):
            return
        if watched.state != self._elapsed.state:
            self._entered = None
            self._set(on=False)
            return
        if (since := self._since(watched)) is None:
            return
        now = dt_util.utcnow()
        start = since + self._hold
        end = start + self._lasts if self._lasts is not None else None
        self._set(on=start <= now and (end is None or now < end))
        upcoming = start if now < start else end if end is not None and now < end else None
        if upcoming is not None:
            self._pending = async_track_point_in_utc_time(
                self.hass, self._evaluate, upcoming
            )
```

- [ ] **Step 4: Build `Elapsed` presets (`features/presets.py`)**

Import `from .elapsed import ElapsedAlert`, and in `build` add the `else` branch after the `Condition` one:

```python
        else:
            kind = preset.kind
            milestone = (
                None
                if kind.since_key is None
                else device.current_entity_id(
                    hass, feature.entity_keys[kind.since_key], kind.since_key
                )
            )
            entities.append(
                ElapsedAlert(
                    device,
                    entity_key,
                    watched=watched,
                    milestone=milestone,
                    elapsed=kind,
                    hold=settings.get("for", preset.hold or timedelta(0)),
                    lasts=settings.get("lasts"),
                    priority=settings["priority"],
                    notify=notify,
                    sources=(
                        preset.watches,
                        *((kind.since_key,) if kind.since_key else ()),
                    ),
                )
            )
```

(add `from datetime import timedelta`). Make the `if isinstance(preset.kind, Condition):` / `else:` branches exhaustive (mypy narrows `kind` to `Elapsed`).

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_presets.py tests/test_appliance.py tests/test_alerts.py -n 0 -q`
Expected: all PASS. If `test_no_cycle_counts_from_its_creation_without_a_cycle` is off by the 125 s the fixture idles, the creation is at `setup` (before `idle`'s tick): the expected ticks already account for it; if the `restart` extra data format for `LAST_END` differs from what `RestoreSensor` saves, read `tests/test_appliance.py`'s restart of a last-cycle sensor and match it — that's a test fix, ledgered.

- [ ] **Step 6: Lint, type-check, commit**

Run: `uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu && uv run mypy custom_components/pururu`

```bash
git add custom_components/pururu tests/test_presets.py
git commit -m "pururu: long_cycle, no_cycle and finished, measured from a cycle's milestones

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Docs and release

**Files:**
- Modify: `docs/features/appliance.mdx`, `docs/features/alerts.mdx`, `docs/reference/configuration.mdx`, `docs/reference/troubleshooting.mdx`, `docs/develop/writing-a-feature.mdx`, `docs/develop/architecture.mdx`, `CLAUDE.md`, `custom_components/pururu/manifest.json`
- Test: `tests/test_presets.py` (docs test)

- [ ] **Step 1: The docs test**

Append to `tests/test_presets.py` (add `import re`):

```python
APPLIANCE_PAGE = Path(__file__).resolve().parents[1] / "docs/features/appliance.mdx"


def test_the_appliance_page_lists_every_ready_made_alert(ha: HomeAssistant) -> None:
    from helpers import module  # noqa: PLC0415
    page = APPLIANCE_PAGE.read_text(encoding="utf-8")
    section = re.search(r"## Ready-made alerts\n(.*?)\n## ", page, re.DOTALL)
    assert section is not None, "no Ready-made alerts section"
    for name in module("features").FEATURES["appliance"].alerts:
        assert f"`{name}`" in section[1], name
```

Run: `uv run pytest tests/test_presets.py -n 0 -q -k appliance_page` → FAIL.

- [ ] **Step 2: `docs/features/appliance.mdx`**

Before `## Provides`, add a `## Ready-made alerts` section:

````mdx
## Ready-made alerts

An appliance offers alerts for what usually goes wrong. They're **off** until you enable them in its `alerts`, one key each; with [Alert2](/features/alerts#getting-notified) set up, each one is delivered with its own texts, in Home Assistant's language.

```yaml
appliance:
  power: sensor.washer_plug_power
  running: {threshold: 4, on_delay: {minutes: 1}, off_delay: {minutes: 2}}
  alerts:
    offline:                          # every default
    long_cycle: {for: {hours: 3}}
    finished: {lasts: {minutes: 30}}
```

| Alert | On when | Off when | Defaults |
|---|---|---|---|
| `offline` | the power sensor has no reading | a reading returns | `for` 10 min, `medium` |
| `no_power` | the power is 0 | the power is above 0 | `for` 10 min, `medium` |
| `long_cycle` | a cycle has run for longer than `for` | the cycle ends | `for` required, `medium` |
| `no_cycle` | no cycle has run for longer than `for` | a cycle starts | `for` required, `medium` |
| `finished` | a cycle ends | a new cycle starts, or `lasts` passes | `lasts` 1 h, `low` |

- Each one takes `for` (`finished`: `lasts` instead), `priority` and [`notify`](/features/alerts#settings), which replaces its texts. Anything else is a configuration error.
- `offline:` alone, with nothing after it, enables it with every default.
- `no_power` is for an appliance that always draws something, such as a fridge: a washer between cycles reads 0 W, so it would be on almost always.
- `long_cycle` counts from the cycle's start, `no_cycle` and `finished` from the last cycle's end: a restart in between starts nothing over. `no_cycle` counts from when you enabled it until a first cycle ends.
- Enabled right after a cycle, `finished` turns on at once for what's left of `lasts`.
- Each is `binary_sensor.pururu_<key>_appliance_alert_<alert>`, device class `problem`, shown as **Máquina de lavar Sem conexão** and so on, with the attributes of any [alert](/features/alerts#entity). A reaction can react to one (`when: appliance_alert_offline`); another alert can't watch it.
- For anything else (a threshold of yours, another entity), write an [alert](/features/alerts) yourself.
````

Under `## Entities`, in the row or text for `binary_sensor.pururu_<key>_appliance_running`, add: its attribute **`cycle_start`**, the running cycle's start, present while it runs.

- [ ] **Step 3: The other pages**

- `docs/features/alerts.mdx`, after the first paragraph: `For the common cases, a feature may offer **ready-made alerts** you enable with one key: see the [appliance's](/features/appliance#ready-made-alerts).`
- `docs/reference/configuration.mdx`: in the full example's `laundry_washer.appliance`, add `alerts: {offline: , finished: }` as block lines:
  ```yaml
        alerts:
          offline:
          finished: {lasts: {minutes: 30}}
  ```
  and under **General rules**: `- A feature's own \`alerts\` enables its ready-made alerts, one key each: see the [appliance's](/features/appliance#ready-made-alerts). The device's \`alerts\` is for alerts you write.`
- `docs/reference/troubleshooting.mdx`, in the configuration-errors list next to the alerts' ones: `- A ready-made alert the feature doesn't offer (\`nope is not a ready-made alert: offline, no_power, long_cycle, no_cycle, finished\`), \`long_cycle\` or \`no_cycle\` without \`for\`, \`lasts\` on another alert than \`finished\`, \`for\` on \`finished\`.` and `- An alert whose \`when\` is a ready-made alert: \`alerts: appliance_alert_offline is an alert: an alert can't watch another\`.`
- `docs/develop/writing-a-feature.mdx`: a `### Ready-made alerts` subsection: `Feature.alerts` maps a name to a `Preset` (`watches`, `kind` — a `Condition` as a hand-written alert's, or an `Elapsed`: a state of the watched entity and a milestone, a datetime entity key or attribute — `priority`, `hold` the default `for` or `None` for required, `lasts`); put `preset_keys(PRESETS)` in `entity_keys`; add each `<namespace>_alert_<name>` name and icon, and `<namespace>_alert_<name>_message` / `_done_message` in the translations' `common`. `test_ready_made_alerts_line_up` checks all of it.
- `docs/develop/architecture.mdx`: in step 2 (Build every device's entities), add: `Then the enabled ready-made alerts of each feature (features/presets.py): Alert for a Condition, ElapsedAlert for an Elapsed, with the default texts read once per setup in HA's language.`; in step 7 (Alert2), replace "each created alert with `notify`" by "each created alert with `notify`, hand-written or ready-made, taken from the created entities".
- `CLAUDE.md`, Features bullet list: add `- A feature can offer ready-made alerts (\`Feature.alerts\`: name → \`Preset\`), off until its block's \`alerts\` enables them; entity key \`alert_<name>\` (in \`entity_keys\` through \`preset_keys\`), built by \`features/presets.py\` as \`Alert\` or \`ElapsedAlert\` (time since a milestone, kept across restarts), default texts in the translations' \`common\`. The Alert2 file is built from the created alerts.`

- [ ] **Step 4: Version**

`custom_components/pururu/manifest.json`: `"version": "0.1.12"` → `"version": "0.1.13"`.

- [ ] **Step 5: Run everything**

Run: `uv run pytest -q` → all PASS. `python3 release.py check` → `v0.1.13 will be published`. `mise exec pnpm@12.6.0 -- pnpm docs:check` (or `pnpm docs:check` where pnpm is on PATH) → no issues.

- [ ] **Step 6: Commit**

```bash
git add docs CLAUDE.md tests/test_presets.py custom_components/pururu/manifest.json
git commit -m "pururu: docs for ready-made alerts (0.1.13)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
