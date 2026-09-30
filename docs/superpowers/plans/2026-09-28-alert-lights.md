# Alert lights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** pururu's alerts with `lights` borrow lights (groups in `pururu: config: alerts: lights:`): the highest priority's `turn_on` while any of a light's alerts is on, `resolved` for its `for` once the last ends, then `turn_off` and `pururu_alert_lights_released`.

**Architecture:** A new module `alert_lights.py` holds the `config.alerts.lights` schema and a manager started from `async_setup_entry` once HA has started. The manager follows the alerts' and the lights' states and only calls `light.turn_on` / `light.turn_off` on pururu lights. The lights (`features/lights.py`) gain a `Borrowable` base: they show `alert`/`alerts` attributes, restore `alert` across restarts and reloads, and the `Light` drops an effect its `effect_list` lacks. Alerts (`features/alerts.py`, `presets.py`, `elapsed.py`) gain an optional `lights` key.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3 (pinned by `pytest-homeassistant-custom-component`), voluptuous, pytest with the repo's `ha` fixture and `tests/helpers.py`.

**Spec:** `docs/superpowers/specs/2026-09-28-alert-lights-design.md`

## Global Constraints

- Run everything from the worktree root with `uv`: `uv run pytest tests/test_alert_lights.py -n 0 -q`; the whole suite (`uv run pytest`) also runs ruff, ruff format, mypy (strict), hassfest and the quality scale on `custom_components/pururu`.
- Never leave the shell's cwd in `.venv/.../homeassistant/helpers/`.
- Event name: `pururu_alert_lights_released`, data `{"entity_id": <the pururu light's entity ID>}`.
- Attributes on a borrowed pururu light: `alert` (`high` | `medium` | `low` | `resolved`) and `alerts` (entity IDs of its alerts that are on); both absent when free.
- An alert's attribute `lights`: the group's name, absent without lights.
- `lights: true` is the group `default`; `false` or no key: no lights.
- Defaults: high `{color_name: red, brightness_pct: 100, effect: breathe}` repeat 15 s; medium orange, same; low **blue**, same; resolved `{color_name: green, brightness_pct: 50}` for 120 s.
- `repeat` and `for` take `{seconds: N}` only, N a positive integer.
- Log messages (exact):
  - `The alert lights couldn't call light.<service> on <entity_id>: <error>` (warning)
  - `light.<unique id> is not created: the alert lights group <group> goes without it` (warning)
- Configuration errors (exact):
  - `device <key>: alerts: <alert>: there is no default group in config.alerts.lights.groups`
  - `device <key>: <feature>: alerts: <preset>: …` for a ready-made alert, same endings
  - `device <key>: alerts: <alert>: <group> is not a group of config.alerts.lights.groups`
  - `config.alerts.lights.groups: <group>: device <key> is not in devices`
  - `config.alerts.lights.groups: <group>: device <key> has no light <light>`
  - `<name> is not a colour name Home Assistant knows`
  - `a light is listed twice`
- Version: `custom_components/pururu/manifest.json` → `0.1.19`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- MDX: `{` and `<` outside code are JSX: keep them in backticks or code blocks.

## Review Focus

- A reload of pururu (any YAML change) while an alert is on: the light must not flash green nor be released (the alert is `unavailable` or gone for a moment). Pinned in Task 5 (`test_a_reload_with_an_alert_on_neither_greens_nor_releases`, `test_an_alert_without_a_reading_for_a_moment_keeps_the_light`).
- A Zigbee light reporting its new state a moment after the manager's call, possibly after the next `repeat`: it must not be "put back" in a loop. Pinned in Task 4 (`test_the_managers_own_changes_are_not_put_back`, `test_a_late_report_of_an_earlier_call_is_still_the_managers`).
- A light dropping off Zigbee during the green: it isn't someone taking it back, it must not be released early. Pinned in Task 4 (`test_a_light_back_from_no_reading_during_resolved_shows_resolved_again`).
- A typo in a colour name (`reed`): refused in the YAML rather than failing every 15 s. Pinned in Task 1.
- A relay (`switch.*` in `lights:`): it must turn on and off without errors from the colour/effect parameters. Pinned in Task 3 (`test_a_relay_only_turns_on_and_off`).

---

## File Structure

- `custom_components/pururu/const.py` — new names: `CONF_CONFIG`, `CONF_LIGHTS`, `DEFAULT_ALERT_LIGHTS`, `EVENT_ALERT_LIGHTS_RELEASED`.
- `custom_components/pururu/alert_lights.py` (new) — the `config.alerts.lights` schema and defaults, group → light unique IDs, the manager.
- `custom_components/pururu/__init__.py` — `config` in `CONFIG_SCHEMA`, `_alert_lights_resolved`, the manager's start in `async_setup_entry`.
- `custom_components/pururu/features/alerts.py` — `lights_group` validator, `lights` on the alert schema, `ProblemAlert.lights` and its attribute.
- `custom_components/pururu/features/elapsed.py`, `features/presets.py` — `lights` passed through for ready-made alerts.
- `custom_components/pururu/features/lights.py` — `Borrowable`, `Light` dropping an unknown effect.
- `tests/helpers.py` — `config=` on `setup`, `reload`, `restart`.
- `tests/test_alert_lights.py` (new), `tests/test_lights.py`.
- Docs: `docs/concepts/alert-lights.mdx` (new), `docs.json`, `docs/features/alerts.mdx`, `docs/features/lights.mdx`, `docs/reference/configuration.mdx`, `docs/reference/troubleshooting.mdx`, `docs/develop/architecture.mdx`, `CLAUDE.md`.

---

### Task 1: Configuration: `config.alerts.lights` and an alert's `lights`

**Files:**
- Modify: `custom_components/pururu/const.py`
- Create: `custom_components/pururu/alert_lights.py`
- Modify: `custom_components/pururu/__init__.py`
- Modify: `custom_components/pururu/features/alerts.py`
- Modify: `custom_components/pururu/features/elapsed.py`
- Modify: `custom_components/pururu/features/presets.py`
- Modify: `tests/helpers.py`
- Test: `tests/test_alert_lights.py`

**Interfaces:**
- Produces:
  - `const.CONF_CONFIG = "config"`, `const.CONF_LIGHTS = "lights"`, `const.DEFAULT_ALERT_LIGHTS = "default"`, `const.EVENT_ALERT_LIGHTS_RELEASED = "pururu_alert_lights_released"`.
  - `alert_lights.GROUPS = "groups"`, `TURN_ON = "turn_on"`, `REPEAT = "repeat"`, `FOR = "for"`, `RESOLVED = "resolved"`, `alert_lights.SCHEMA` (validates the `lights:` block, filling defaults; `repeat`/`for` become `timedelta`).
  - `features.alerts.lights_group(value) -> str | None`; `ProblemAlert.lights: str | None` (constructor kwarg `lights: str | None = None`, also on `Alert` and `ElapsedAlert`).
  - `helpers.setup(hass, devices, *, floors=None, areas=None, config=None)`, same `config=` on `reload`, and `restart(hass, devices, *saved, config=None)`.

- [ ] **Step 1: Add `config=` to the test helpers**

In `tests/helpers.py`, replace `_config`, `setup`, `reload` and `restart` with:

```python
def _config(devices: dict[str, Any], floors: dict[str, Any] | None,
            areas: dict[str, Any] | None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """A configuration.yaml with this `pururu:` block; `config` is its config: block."""
    block: dict[str, Any] = {"devices": devices, "floors": floors or {}, "areas": areas or {}}
    if config is not None:
        block["config"] = config
    return {DOMAIN: block}
```

```python
async def setup(hass: HomeAssistant, devices: dict[str, Any], *,
                floors: dict[str, Any] | None = None,
                areas: dict[str, Any] | None = None,
                config: dict[str, Any] | None = None) -> bool:
    """Set pururu up from `pururu:`; False when HA refuses the configuration."""
    ok = await async_setup_component(hass, DOMAIN, _config(devices, floors, areas, config))
    await hass.async_block_till_done()
    return ok


async def reload(hass: HomeAssistant, devices: dict[str, Any], *,
                 floors: dict[str, Any] | None = None,
                 areas: dict[str, Any] | None = None,
                 config: dict[str, Any] | None = None) -> None:
    """pururu.reload, with a configuration.yaml holding this `pururu:` block."""
    yaml_config = _config(devices, floors, areas, config)
    # configuration.yaml includes the generated files: automations and scripts reload from them
    with patch("homeassistant.config.load_yaml_config_file",
               side_effect=lambda *_args, **_kwargs: {**yaml_config,
                                                      "automation pururu": generated(hass),
                                                      "script pururu": generated_scripts(hass)}):
        await hass.services.async_call(DOMAIN, "reload", blocking=True)
        await hass.async_block_till_done()


async def restart(hass: HomeAssistant, devices: dict[str, Any],
                  *saved: tuple[State, dict[str, Any]],
                  config: dict[str, Any] | None = None) -> None:
    """Start as after a restart: `saved` is what .storage held (state, extra data)."""
    hass.set_state(CoreState.not_running)
    mock_restore_cache_with_extra_data(hass, list(saved))
    assert await setup(hass, devices, config=config)
    await hass.async_start()
    await hass.async_block_till_done()
```

- [ ] **Step 2: Write the failing configuration tests**

Create `tests/test_alert_lights.py`:

```python
"""Alert lights: a made-up house's alerts borrowing the pool's LED and the porch's relay."""

from datetime import timedelta
from typing import Any

from homeassistant.core import Event, HomeAssistant
import pytest

from helpers import fake, module, setup

HOUSE = "casa"
REAL_LED = "light.pool_led"
LED = "light.pururu_pool_light_led"
REAL_RELAY = "switch.varanda_rele"
RELAY = "light.pururu_varanda_light_rele"
# The LED as Zigbee2MQTT shows it: hs colour, breathe among its effects,
# EFFECT | FLASH | TRANSITION
BULB = {"supported_color_modes": ["hs"], "color_mode": "hs", "brightness": 255,
        "hs_color": [240.0, 100.0], "effect_list": ["blink", "breathe"],
        "supported_features": 44}
# The house's switches: turning one on raises the alert watching it
REAL = {name: f"switch.casa_{name}" for name in ("gate", "smoke", "mail", "leak")}
GROUPS = {"default": {"pool": ["led"]}, "porch": {"varanda": ["rele"]},
          "both": {"pool": ["led"], "varanda": ["rele"]}}
CONFIG = {"alerts": {"lights": {"groups": GROUPS}}}
RED = {"color_name": "red", "brightness_pct": 100, "effect": "breathe"}
ORANGE = {"color_name": "orange", "brightness_pct": 100, "effect": "breathe"}
BLUE = {"color_name": "blue", "brightness_pct": 100, "effect": "breathe"}
GREEN = {"color_name": "green", "brightness_pct": 50}
APPLIANCE: dict[str, Any] = {
    "power": "sensor.lavadora_power",
    "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}


def alert(name: str) -> str:
    return f"binary_sensor.pururu_{HOUSE}_alert_{name}"


def raised(name: str, priority: str, lights: Any = True) -> dict[str, Any]:
    """An alert on while the house's switch `name` is on; lights None: no lights key."""
    block: dict[str, Any] = {"name": name.title(), "when": f"switch_{name}", "is": "on",
                             "priority": priority}
    if lights is not None:
        block["lights"] = lights
    return block


def devices(**alerts: dict[str, Any]) -> dict[str, Any]:
    house: dict[str, Any] = {
        "name": "Casa",
        "switches": {name: {"entity": real, "name": name.title()} for name, real in REAL.items()},
    }
    if alerts:
        house["alerts"] = alerts
    return {
        "pool": {"name": "Piscina", "lights": {"led": {"entity": REAL_LED, "name": "LED"}}},
        "varanda": {"name": "Varanda",
                    "lights": {"rele": {"entity": REAL_RELAY, "name": "Relé"}}},
        HOUSE: house,
    }


def calls(events: list[Event], entity_id: str) -> list[tuple[str, dict[str, Any]]]:
    """The light services called on `entity_id`, and their data without it."""
    return [(event.data["service"],
             {k: v for k, v in event.data["service_data"].items() if k != "entity_id"})
            for event in events
            if event.data["domain"] == "light"
            and event.data["service_data"].get("entity_id") in (entity_id, [entity_id])]


def attributes(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    return dict(hass.states.get(entity_id).attributes)


def errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]


@pytest.fixture
async def house(ha: HomeAssistant) -> HomeAssistant:
    """The real lights and switches, all off, before pururu sets up."""
    await fake(ha, REAL_LED, "off", BULB)
    await fake(ha, REAL_RELAY, "off")
    for real in REAL.values():
        await fake(ha, real, "off")
    return ha


async def turn(hass: HomeAssistant, name: str, state: str) -> None:
    """Turn the house's real switch `name` on or off; its alert and the lights follow."""
    await fake(hass, REAL[name], state)
    await hass.async_block_till_done()


# --- configuration ------------------------------------------------------------------------


async def test_without_config_every_default_applies(house: HomeAssistant) -> None:
    assert await setup(house, devices())
    assert module("alert_lights").SCHEMA({}) == {
        "groups": {},
        "high": {"turn_on": RED, "repeat": timedelta(seconds=15)},
        "medium": {"turn_on": ORANGE, "repeat": timedelta(seconds=15)},
        "low": {"turn_on": BLUE, "repeat": timedelta(seconds=15)},
        "resolved": {"turn_on": GREEN, "for": timedelta(seconds=120)},
    }


async def test_a_priority_written_replaces_its_default_whole(house: HomeAssistant) -> None:
    """No breathe nor repeat left over from the default."""
    assert await setup(house, devices())
    settings = module("alert_lights").SCHEMA({"high": {"turn_on": {"color_name": "purple"}}})
    assert settings["high"] == {"turn_on": {"color_name": "purple"}}
    assert settings["medium"]["turn_on"] == ORANGE


@pytest.mark.parametrize("lights", [
    pytest.param({}, id="empty"),
    pytest.param({"groups": GROUPS}, id="groups"),
    pytest.param({"high": {"turn_on": {"rgb_color": [255, 0, 0], "flash": "long"}}},
                 id="rgb and flash"),
    pytest.param({"low": {"turn_on": {}}}, id="just on"),
    pytest.param({"resolved": {"turn_on": {"color_name": "dark green"}, "for": {"seconds": 5}}},
                 id="resolved"),
])
async def test_valid_alert_lights_are_accepted(house: HomeAssistant, lights: Any) -> None:
    assert await setup(house, devices(), config={"alerts": {"lights": lights}})


def lights_block(**block: Any) -> dict[str, Any]:
    return {"alerts": {"lights": block}}


@pytest.mark.parametrize(("config", "reason"), [
    pytest.param({"nothing": 1}, "'nothing' is an invalid option", id="unknown key in config"),
    pytest.param({"alerts": {"nothing": 1}}, "'nothing' is an invalid option",
                 id="unknown key in alerts"),
    pytest.param(lights_block(colours={}), "'colours' is an invalid option",
                 id="unknown key in lights"),
    pytest.param(lights_block(groups={"Porch": {"varanda": ["rele"]}}), "invalid slug Porch",
                 id="group not a slug"),
    pytest.param(lights_block(groups={"porch": {}}), "length of value must be at least 1",
                 id="empty group"),
    pytest.param(lights_block(groups={"porch": {"varanda": []}}),
                 "length of value must be at least 1", id="no light"),
    pytest.param(lights_block(groups={"porch": {"varanda": ["rele", "rele"]}}),
                 "a light is listed twice", id="a light twice"),
    pytest.param(lights_block(groups={"porch": {"varanda": "rele"}}), "expected a list",
                 id="not a list"),
    pytest.param(lights_block(groups={"porch": {"garagem": ["rele"]}}),
                 "config.alerts.lights.groups: porch: device garagem is not in devices",
                 id="unknown device"),
    pytest.param(lights_block(groups={"porch": {"varanda": ["teto"]}}),
                 "config.alerts.lights.groups: porch: device varanda has no light teto",
                 id="unknown light"),
    pytest.param(lights_block(groups={"porch": {"casa": ["gate"]}}),
                 "config.alerts.lights.groups: porch: device casa has no light gate",
                 id="a switch, not a light"),
    pytest.param(lights_block(high={"turn_on": {"entity_id": LED}}),
                 "'entity_id' is an invalid option", id="entity_id in turn_on"),
    pytest.param(lights_block(high={"turn_on": {"color_name": "reed"}}),
                 "reed is not a colour name Home Assistant knows", id="unknown colour"),
    pytest.param(lights_block(high={"repeat": {"seconds": 15}}),
                 "required key 'turn_on' not provided", id="no turn_on"),
    pytest.param(lights_block(high={"turn_on": {}, "repeat": {"minutes": 1}}),
                 "'minutes' is an invalid option", id="repeat in minutes"),
    pytest.param(lights_block(high={"turn_on": {}, "repeat": {"seconds": 0}}),
                 "value must be at least 1", id="repeat zero"),
    pytest.param(lights_block(high={"turn_on": {}, "repeat": {"seconds": 1.5}}),
                 "expected int", id="repeat not whole"),
    pytest.param(lights_block(high={"turn_on": {}, "for": {"seconds": 5}}),
                 "'for' is an invalid option", id="for on a priority"),
    pytest.param(lights_block(resolved={"turn_on": {}}),
                 "required key 'for' not provided", id="resolved without for"),
    pytest.param(lights_block(resolved={"turn_on": {}, "for": {"seconds": 5},
                                        "repeat": {"seconds": 5}}),
                 "'repeat' is an invalid option", id="repeat on resolved"),
])
async def test_invalid_alert_lights_are_refused(
        house: HomeAssistant, caplog: pytest.LogCaptureFixture, config: dict[str, Any],
        reason: str) -> None:
    """Refused, and for its own reason: a typo in the test would be refused for another one."""
    assert not await setup(house, devices(), config=config)
    assert any(reason in message for message in errors(caplog)), errors(caplog)


# --- an alert's lights ------------------------------------------------------------------------


@pytest.mark.parametrize(("lights", "group"), [
    pytest.param(True, "default", id="true"),
    pytest.param("porch", "porch", id="a group"),
])
async def test_an_alerts_group_is_an_attribute(
        house: HomeAssistant, lights: Any, group: str) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium", lights)), config=CONFIG)
    assert attributes(house, alert("gate"))["lights"] == group


@pytest.mark.parametrize("lights", [pytest.param(None, id="no key"),
                                    pytest.param(False, id="false")])
async def test_an_alert_without_lights_has_no_group(house: HomeAssistant, lights: Any) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium", lights)), config=CONFIG)
    assert "lights" not in attributes(house, alert("gate"))


NO_DEFAULT = ("device casa: alerts: gate: there is no default group in "
              "config.alerts.lights.groups")


@pytest.mark.parametrize(("config", "lights", "reason"), [
    pytest.param(lights_block(groups={"porch": {"varanda": ["rele"]}}), True, NO_DEFAULT,
                 id="no default group"),
    pytest.param(None, True, NO_DEFAULT, id="no config"),
    pytest.param(CONFIG, "outside",
                 "device casa: alerts: gate: outside is not a group of "
                 "config.alerts.lights.groups", id="unknown group"),
    pytest.param(CONFIG, "Porch", "invalid slug Porch", id="group not a slug"),
])
async def test_an_alerts_lights_must_name_a_group(
        house: HomeAssistant, caplog: pytest.LogCaptureFixture, config: Any, lights: Any,
        reason: str) -> None:
    assert not await setup(house, devices(gate=raised("gate", "medium", lights)), config=config)
    assert any(reason in message for message in errors(caplog)), errors(caplog)


async def test_a_ready_made_alerts_lights_must_name_a_group(
        house: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    washer = {"name": "Lavadora",
              "appliance": {**APPLIANCE, "alerts": {"offline": {"lights": "outside"}}}}
    assert not await setup(house, {**devices(), "lavadora": washer}, config=CONFIG)
    reason = ("device lavadora: appliance: alerts: offline: outside is not a group of "
              "config.alerts.lights.groups")
    assert any(reason in message for message in errors(caplog)), errors(caplog)


async def test_a_ready_made_alerts_group_is_an_attribute(house: HomeAssistant) -> None:
    washer = {"name": "Lavadora", "appliance": {**APPLIANCE, "alerts": {"offline": {"lights": True}}}}
    assert await setup(house, {**devices(), "lavadora": washer}, config=CONFIG)
    offline = "binary_sensor.pururu_lavadora_appliance_alert_offline"
    assert attributes(house, offline)["lights"] == "default"
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `uv run pytest tests/test_alert_lights.py -n 0 -q`
Expected: FAIL: `ModuleNotFoundError: No module named 'custom_components.pururu.alert_lights'` in the defaults tests, `'config' is an invalid option` making the valid ones fail, no `lights` attribute.

- [ ] **Step 4: Add the names to `const.py`**

Append to `custom_components/pururu/const.py`:

```python
# pururu: config: settings of the whole house, not of a device
CONF_CONFIG: Final = "config"
# A device's lights, config: alerts: lights:, and an alert's lights
CONF_LIGHTS: Final = "lights"
# The alert lights group of an alert's `lights: true`
DEFAULT_ALERT_LIGHTS: Final = "default"
# Fired when the alert lights hand a light back: {"entity_id": the pururu light}
EVENT_ALERT_LIGHTS_RELEASED: Final = "pururu_alert_lights_released"
```

- [ ] **Step 5: Create `alert_lights.py` with the schema**

Create `custom_components/pururu/alert_lights.py`:

```python
"""Alert lights: the lights pururu's alerts borrow while they are on.

An alert with `lights` names a group of `config: alerts: lights: groups`.
While one of a light's alerts is on, the light shows the highest priority's
`turn_on`; once none is, `resolved`'s for its `for`, then it is turned off and
pururu_alert_lights_released says it is free. Only the light's turn_on and
turn_off are called: the light uses what it has.
"""

from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components.light import ATTR_COLOR_NAME, LIGHT_TURN_ON_SCHEMA
from homeassistant.helpers import config_validation as cv
from homeassistant.util.color import color_name_to_rgb

from .features.alerts import PRIORITIES

GROUPS = "groups"
TURN_ON = "turn_on"
REPEAT = "repeat"
FOR = "for"
# What a light shows between its last alert's end and its release
RESOLVED = "resolved"


def _known_colour(params: dict[str, Any]) -> dict[str, Any]:
    """Refuse a colour name HA doesn't know: every call would fail."""
    if (name := params.get(ATTR_COLOR_NAME)) is not None:
        try:
            color_name_to_rgb(name)
        except ValueError as err:
            raise vol.Invalid(
                f"{name} is not a colour name Home Assistant knows"
            ) from err
    return params


# light.turn_on's data under its own names; the light is the group's, never given here
TURN_ON_SCHEMA = vol.All(vol.Schema(LIGHT_TURN_ON_SCHEMA), _known_colour)
# A whole number of seconds, written {seconds: N}
SECONDS = vol.All(
    vol.Schema({vol.Required("seconds"): vol.All(int, vol.Range(min=1))}),
    lambda value: timedelta(seconds=value["seconds"]),
)


def _distinct(lights: list[str]) -> list[str]:
    if len(set(lights)) != len(lights):
        raise vol.Invalid("a light is listed twice")
    return lights


# Device key -> keys of that device's lights; __init__ checks them against the devices
GROUP = vol.All(
    vol.Schema({cv.slug: vol.All([cv.slug], vol.Length(min=1), _distinct)}),
    vol.Length(min=1),
)
PRIORITY = vol.Schema(
    {vol.Required(TURN_ON): TURN_ON_SCHEMA, vol.Optional(REPEAT): SECONDS}
)
RESOLVED_SCHEMA = vol.Schema(
    {vol.Required(TURN_ON): TURN_ON_SCHEMA, vol.Required(FOR): SECONDS}
)


def _breathe(colour: str) -> dict[str, Any]:
    """A priority's default: breathe in `colour`, sent again every 15 s (a one-shot effect)."""
    return {
        TURN_ON: {"color_name": colour, "brightness_pct": 100, "effect": "breathe"},
        REPEAT: {"seconds": 15},
    }


# The defaults as the user would write them: validated like what the user writes
DEFAULTS: dict[str, dict[str, Any]] = {
    "high": _breathe("red"),
    "medium": _breathe("orange"),
    "low": _breathe("blue"),
    RESOLVED: {
        TURN_ON: {"color_name": "green", "brightness_pct": 50},
        FOR: {"seconds": 120},
    },
}

# config: alerts: lights:; a priority written replaces its default whole
SCHEMA = vol.Schema(
    {
        vol.Optional(GROUPS, default=dict): vol.Schema({cv.slug: GROUP}),
        **{
            vol.Optional(priority, default=DEFAULTS[priority]): PRIORITY
            for priority in PRIORITIES
        },
        vol.Optional(RESOLVED, default=DEFAULTS[RESOLVED]): RESOLVED_SCHEMA,
    }
)
```

Voluptuous validates a missing key's default like a written value, so `SCHEMA({})` has `timedelta`s; `test_without_config_every_default_applies` pins that.

- [ ] **Step 6: Give alerts their `lights`**

In `custom_components/pururu/features/alerts.py`:

Add to the imports: `from ..const import DEFAULT_ALERT_LIGHTS`.

After `NOTIFY = ...`, add:

```python
def lights_group(value: Any) -> str | None:
    """An alert's alert lights group (alert_lights.py): true is the default group, false none."""
    if isinstance(value, bool):
        return DEFAULT_ALERT_LIGHTS if value else None
    return str(cv.slug(value))
```

In the `ALERT` schema, after `vol.Optional("notify"): NOTIFY,` add `vol.Optional("lights"): lights_group,`.

Replace `ProblemAlert.__init__` with:

```python
    def __init__(
        self,
        *,
        watched: str,
        priority: str,
        notify: Mapping[str, str] | None,
        asks_alert2: bool = True,
        lights: str | None = None,
    ) -> None:
        """Watch `watched`; `notify` is what Alert2 tells, `lights` the group it borrows.

        `asks_alert2` False: its notify is a ready-made alert's own texts, not a
        request of the user's, so no error without Alert2.
        """
        self._watched = watched
        self._asks_alert2 = asks_alert2 and notify is not None
        self.priority = priority
        self.notify = notify
        self.lights = lights
        self._attr_is_on = False
        self._attr_extra_state_attributes = {
            "priority": priority,
            "watches": watched,
            **({"lights": lights} if lights is not None else {}),
            **(notify or {}),
        }
        self._pending: CALLBACK_TYPE | None = None
```

In `Alert.__init__`, add the keyword parameter `lights: str | None = None,` after `asks_alert2: bool = True,` and pass it on:

```python
        super().__init__(
            watched=watched,
            priority=priority,
            notify=notify,
            asks_alert2=asks_alert2,
            lights=lights,
        )
```

In `build()`, add `lights=alert.get("lights"),` after `notify=alert.get("notify"),`.

- [ ] **Step 7: Pass `lights` through the ready-made alerts**

In `custom_components/pururu/features/elapsed.py`, `ElapsedAlert.__init__`: add `lights: str | None = None,` after `asks_alert2: bool = True,` and replace its `super().__init__(...)` with:

```python
        super().__init__(
            watched=watched,
            priority=priority,
            notify=notify,
            asks_alert2=asks_alert2,
            lights=lights,
        )
```

In `custom_components/pururu/features/presets.py`:
- Import: `from .alerts import NOTIFY, PRIORITIES, Alert, lights_group`.
- In `_settings`, after `vol.Optional("notify"): NOTIFY,` add `vol.Optional("lights"): lights_group,`.
- In `build()`, add `lights=settings.get("lights"),` to both the `Alert(...)` and the `ElapsedAlert(...)` calls, after `asks_alert2="notify" in settings,`.

- [ ] **Step 8: Validate `config` and cross-check the groups in `__init__.py`**

In `custom_components/pururu/__init__.py`:

Imports: add `alert_lights` to `from . import alert2_alerts, dashboard, generated, places, programs, reactions`; add `CONF_CONFIG`, `CONF_LIGHTS`, `DEFAULT_ALERT_LIGHTS` to the `.const` import; change `from .feature import Device, Feature, preset_keys, qualified` to `from .feature import ALERTS_KEY, Device, Feature, preset_keys, qualified`.

After `_reaction_resolved`/`_referable` (before `CONFIG_SCHEMA`), add:

```python
def _alert_lights_resolved(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse a group's light that isn't a device's, or an alert's group that isn't one."""
    devices = config[CONF_DEVICES]
    groups = config[CONF_CONFIG][CONF_ALERTS][CONF_LIGHTS][alert_lights.GROUPS]
    for group, members in groups.items():
        where = f"config.alerts.lights.groups: {group}"
        for key, lights in members.items():
            if key not in devices:
                raise vol.Invalid(f"{where}: device {key} is not in devices")
            for light in lights:
                if light not in devices[key].get(CONF_LIGHTS, {}):
                    raise vol.Invalid(f"{where}: device {key} has no light {light}")
    for key, device in devices.items():
        for where, group in _alert_light_groups(device):
            if group in groups:
                continue
            if group == DEFAULT_ALERT_LIGHTS:
                raise vol.Invalid(
                    f"device {key}: {where}: there is no default group in "
                    "config.alerts.lights.groups"
                )
            raise vol.Invalid(
                f"device {key}: {where}: {group} is not a group of "
                "config.alerts.lights.groups"
            )
    return config


def _alert_light_groups(device: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """(where, group) of each of the device's alerts with lights, hand-written or ready-made."""
    for alert_key, alert in device.get(CONF_ALERTS, {}).items():
        if (group := alert.get(CONF_LIGHTS)) is not None:
            yield f"{CONF_ALERTS}: {alert_key}", group
    for name, feature in FEATURES.items():
        if not feature.alerts or name not in device:
            continue
        for preset, settings in device[name].get(ALERTS_KEY, {}).items():
            if (group := settings.get(CONF_LIGHTS)) is not None:
                yield f"{name}: {ALERTS_KEY}: {preset}", group
```

In `CONFIG_SCHEMA`, after the `CONF_DEVICES` entry, add:

```python
                    # Settings of the whole house; schemas of their own, so a typo is refused
                    vol.Optional(CONF_CONFIG, default={}): vol.Schema(
                        {
                            vol.Optional(CONF_ALERTS, default={}): vol.Schema(
                                {
                                    vol.Optional(
                                        CONF_LIGHTS, default={}
                                    ): alert_lights.SCHEMA
                                }
                            )
                        }
                    ),
```

and add `_alert_lights_resolved,` after `_reactions_resolved,` in the `vol.All(...)`.

- [ ] **Step 9: Run the tests to see them pass**

Run: `uv run pytest tests/test_alert_lights.py tests/test_alerts.py tests/test_presets.py -n 0 -q`
Expected: PASS. If one invalid case fails only because voluptuous words its message differently (for example `expected int`), check that the failure is for the case's own reason, then change that test's expected text to the exact message; never change the code to fit a wording.

- [ ] **Step 10: Lint and type-check**

Run: `uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu && uv run mypy custom_components/pururu`
Expected: no errors.

- [ ] **Step 11: Commit**

```bash
git add custom_components/pururu tests/helpers.py tests/test_alert_lights.py
git commit -m "pururu: config.alerts.lights and an alert's lights

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: A light the alert lights can borrow

**Files:**
- Modify: `custom_components/pururu/features/lights.py`
- Test: `tests/test_lights.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces, in `features/lights.py`:
  - `ATTR_ALERT = "alert"`, `ATTR_ALERTS = "alerts"`.
  - `class Borrowable(PururuEntity, RestoreEntity)`: `restored_alert: str | None` (what `alert` was before a restart or reload; set in `async_added_to_hass`), `async_show_alert(alert: str | None, alerts: Iterable[str], context: Context) -> None` (a `@callback`; `None` removes both attributes; writes the state with `context`).
  - `Light(Borrowable, LightGroup)` and `SwitchLight(Borrowable, GroupEntity, LightEntity)`.
  - `Light.async_turn_on` drops an `effect` not in its `effect_list`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_lights.py`, change the core import to `from homeassistant.core import Context, CoreState, HomeAssistant, State`, add `from homeassistant.components.light.const import DATA_COMPONENT`, and append:

```python
# --- the alert lights ------------------------------------------------------------------


def light_entity(hass: HomeAssistant, entity_id: str) -> Any:
    """The light entity itself, as the light component holds it."""
    return hass.data[DATA_COMPONENT].get_entity(entity_id)


async def test_an_effect_the_real_light_does_not_list_is_dropped(sala: HomeAssistant) -> None:
    """The alert lights ask every light for breathe: a bulb without it takes the rest."""
    calls = await forwarded(sala, TETO, "turn_on", {"effect": "breathe", "brightness": 100},
                            Context(), REAL_TETO)
    assert len(calls) == 1
    assert "effect" not in calls[0][2]
    assert calls[0][2]["brightness"] == 100


async def test_an_effect_the_real_light_lists_is_passed_on(sala: HomeAssistant) -> None:
    calls = await forwarded(sala, TETO, "turn_on", {"effect": "strobe"}, Context(), REAL_TETO)
    assert calls[0][2]["effect"] == "strobe"


@pytest.mark.parametrize(("entity_id", "real", "block"), [
    pytest.param(TETO, REAL_TETO, LIGHTS["teto"], id="a light"),
    pytest.param(ARANDELA, REAL_ARANDELA, ARANDELA_BLOCK, id="a relay"),
])
async def test_it_shows_what_the_alert_lights_use_it_for(
        ha: HomeAssistant, entity_id: str, real: str, block: dict[str, Any]) -> None:
    await fake(ha, real, "on", BULB if real == REAL_TETO else None)
    key = entity_id.rsplit("_", 1)[1]
    assert await setup(ha, {KEY: {"name": "Sala", "lights": {key: block}}})
    context = Context()
    light_entity(ha, entity_id).async_show_alert("medium", ["binary_sensor.x"], context)
    shown = ha.states.get(entity_id)
    assert shown.attributes["alert"] == "medium"
    assert shown.attributes["alerts"] == ["binary_sensor.x"]
    assert shown.attributes["entity_id"] == [real]
    assert shown.context.id == context.id
    light_entity(ha, entity_id).async_show_alert(None, [], Context())
    free = ha.states.get(entity_id).attributes
    assert "alert" not in free
    assert "alerts" not in free
    assert free["entity_id"] == [real]


async def test_it_remembers_what_the_alert_lights_showed(ha: HomeAssistant) -> None:
    await fake(ha, REAL_TETO, "on", BULB)
    await restart(ha, DEVICES, (State(TETO, "on", {"alert": "resolved"}), {}))
    assert light_entity(ha, TETO).restored_alert == "resolved"
    assert light_entity(ha, ABAJUR).restored_alert is None
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_lights.py -n 0 -q -k "alert_lights or effect"`
Expected: FAIL: the effect is forwarded, `async_show_alert` and `restored_alert` don't exist.

- [ ] **Step 3: Implement `Borrowable` and the effect filter**

In `custom_components/pururu/features/lights.py`:

Imports become:

```python
from collections.abc import Callable, Iterable, Mapping
import logging
from typing import Any, override

from homeassistant.components.group.entity import GroupEntity
from homeassistant.components.group.light import LightGroup
from homeassistant.components.light import ATTR_EFFECT, ColorMode, LightEntity
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import Context, HomeAssistant, callback, split_entity_id
from homeassistant.helpers.restore_state import RestoreEntity
```

Before `class Light`, add:

```python
# What the alert lights show on a light they borrow (alert_lights.py)
ATTR_ALERT = "alert"
ATTR_ALERTS = "alerts"


class Borrowable(PururuEntity, RestoreEntity):
    """A light the alert lights may borrow: says what for, and remembers it across restarts."""

    # What the alert lights showed before a restart or reload; None: nothing
    restored_alert: str | None = None
    _alert: str | None = None
    _alerts: tuple[str, ...] = ()

    @override
    async def async_added_to_hass(self) -> None:
        """Follow the real entity as the group does, then read what the alert lights showed."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self.restored_alert = last.attributes.get(ATTR_ALERT)

    @callback
    def async_show_alert(
        self, alert: str | None, alerts: Iterable[str], context: Context
    ) -> None:
        """Show what the alert lights use it for (None: free), written as their change."""
        self._alert = alert
        self._alerts = tuple(alerts)
        self.async_set_context(context)
        self.async_write_ha_state()

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The group's attributes; while borrowed, what for and by which alerts."""
        attributes = dict(super().extra_state_attributes or {})
        if self._alert is not None:
            attributes[ATTR_ALERT] = self._alert
            attributes[ATTR_ALERTS] = list(self._alerts)
        return attributes
```

Change `class Light(PururuEntity, LightGroup):` to `class Light(Borrowable, LightGroup):` and add to it, after `__init__`:

```python
    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Pass everything on, but an effect the real light doesn't list.

        HA drops an effect only for a light without effects; a bulb with
        others would refuse this one.
        """
        if ATTR_EFFECT in kwargs and kwargs[ATTR_EFFECT] not in (self.effect_list or ()):
            kwargs = {key: value for key, value in kwargs.items() if key != ATTR_EFFECT}
        await super().async_turn_on(**kwargs)
```

Change `class SwitchLight(PururuEntity, GroupEntity, LightEntity):` to `class SwitchLight(Borrowable, GroupEntity, LightEntity):`.

Update the module docstring's first paragraph by appending: `Both kinds can be borrowed by the alert lights (alert_lights.py): they show what for, and remember it across restarts.`

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_lights.py tests/test_switches.py -n 0 -q`
Expected: PASS (the existing light tests too: the group's `entity_id` attribute is kept).

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu && uv run mypy custom_components/pururu`
Expected: no errors.

```bash
git add custom_components/pururu/features/lights.py tests/test_lights.py
git commit -m "pururu: lights the alert lights can borrow

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The manager: lending the lights to the alerts

**Files:**
- Modify: `custom_components/pururu/alert_lights.py`
- Modify: `custom_components/pururu/__init__.py`
- Test: `tests/test_alert_lights.py`

**Interfaces:**
- Consumes: Task 1's `SCHEMA`, `GROUPS`, `TURN_ON`, `REPEAT`, `FOR`, `RESOLVED`, `ProblemAlert.lights`, `const.EVENT_ALERT_LIGHTS_RELEASED`, `CONF_CONFIG`, `CONF_ALERTS`, `CONF_LIGHTS`; Task 2's `Borrowable` (`async_show_alert`, `restored_alert`) and `features.lights.LIGHTS` (its `namespace`, `"light"`).
- Produces, in `alert_lights.py`:
  - `settings(configured: Mapping[str, Any]) -> dict[str, Any]`
  - `light_ids(settings: Mapping[str, Any], devices: Mapping[str, Any]) -> dict[str, list[str]]` (group → unique IDs of its lights)
  - `async_setup(hass, entry, settings, groups, alerts: Iterable[ProblemAlert], lights: Iterable[Borrowable]) -> None`
  - `class _Light` (dataclass: `entity`, `alerts`, `shown`, `recent`, `repeating`, `resolving`; `own()`, `stop_repeating()`, `stop_resolving()`), `class AlertLights` (`start()`, `_update`, `_apply`, `_resolve`, `_release`, `_call`), used by Tasks 4 and 5.

- [ ] **Step 1: Write the failing tests**

In `tests/test_alert_lights.py`, extend the helpers import to `from helpers import capture, fake, module, setup, tick` and append:

```python
# --- lending the lights -------------------------------------------------------------------


async def test_an_alert_with_lights_borrows_its_group(house: HomeAssistant) -> None:
    events = capture(house, "call_service")
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    assert calls(events, LED) == []
    await turn(house, "gate", "on")
    assert calls(events, LED) == [("turn_on", ORANGE)]
    assert attributes(house, LED)["alert"] == "medium"
    assert attributes(house, LED)["alerts"] == [alert("gate")]
    assert calls(events, RELAY) == []


async def test_an_alert_without_lights_borrows_nothing(house: HomeAssistant) -> None:
    events = capture(house, "call_service")
    assert await setup(house, devices(gate=raised("gate", "high", None)), config=CONFIG)
    await turn(house, "gate", "on")
    assert calls(events, LED) == []
    assert "alert" not in attributes(house, LED)


async def test_the_priority_is_sent_again_every_15_seconds(
        house: HomeAssistant, freezer: Any) -> None:
    """breathe is a one-shot effect."""
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    await tick(house, freezer, 14)
    assert calls(events, LED) == []
    await tick(house, freezer, 1)
    assert calls(events, LED) == [("turn_on", ORANGE)]
    await tick(house, freezer, 15)
    assert calls(events, LED) == [("turn_on", ORANGE)] * 2


async def test_the_highest_priority_wins_and_gives_way(house: HomeAssistant) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium"),
                                      smoke=raised("smoke", "high")), config=CONFIG)
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    await turn(house, "smoke", "on")
    assert calls(events, LED) == [("turn_on", RED)]
    assert attributes(house, LED)["alerts"] == [alert("gate"), alert("smoke")]
    await turn(house, "smoke", "off")
    assert calls(events, LED) == [("turn_on", RED), ("turn_on", ORANGE)]
    assert attributes(house, LED)["alert"] == "medium"
    assert attributes(house, LED)["alerts"] == [alert("gate")]


async def test_low_is_blue(house: HomeAssistant) -> None:
    events = capture(house, "call_service")
    assert await setup(house, devices(leak=raised("leak", "low")), config=CONFIG)
    await turn(house, "leak", "on")
    assert calls(events, LED) == [("turn_on", BLUE)]


async def test_another_alert_of_the_same_priority_only_joins(house: HomeAssistant) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium"),
                                      mail=raised("mail", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    await turn(house, "mail", "on")
    assert calls(events, LED) == []
    assert attributes(house, LED)["alerts"] == [alert("gate"), alert("mail")]
    await turn(house, "gate", "off")
    assert calls(events, LED) == []
    assert attributes(house, LED)["alerts"] == [alert("mail")]


async def test_the_last_alert_ending_shows_resolved_then_hands_the_light_back(
        house: HomeAssistant, freezer: Any) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    released = capture(house, "pururu_alert_lights_released")
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    await turn(house, "gate", "off")
    assert calls(events, LED) == [("turn_on", GREEN)]
    assert attributes(house, LED)["alert"] == "resolved"
    assert attributes(house, LED)["alerts"] == []
    await tick(house, freezer, 119)
    assert calls(events, LED) == [("turn_on", GREEN)]
    assert released == []
    await tick(house, freezer, 1)
    assert calls(events, LED) == [("turn_on", GREEN), ("turn_off", {})]
    assert [event.data for event in released] == [{"entity_id": LED}]
    assert "alert" not in attributes(house, LED)


async def test_an_alert_during_resolved_takes_the_light_again(
        house: HomeAssistant, freezer: Any) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    released = capture(house, "pururu_alert_lights_released")
    await turn(house, "gate", "on")
    await turn(house, "gate", "off")
    await tick(house, freezer, 60)
    events = capture(house, "call_service")
    await turn(house, "gate", "on")
    assert calls(events, LED) == [("turn_on", ORANGE)]
    await tick(house, freezer, 61)
    assert "turn_off" not in [service for service, _ in calls(events, LED)]
    assert released == []
    assert attributes(house, LED)["alert"] == "medium"


async def test_an_alert_of_another_group_does_not_hold_the_light(
        house: HomeAssistant, freezer: Any) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium"),
                                      mail=raised("mail", "low", "porch")), config=CONFIG)
    released = capture(house, "pururu_alert_lights_released")
    await turn(house, "gate", "on")
    await turn(house, "mail", "on")
    events = capture(house, "call_service")
    await turn(house, "gate", "off")
    assert calls(events, LED) == [("turn_on", GREEN)]
    assert calls(events, RELAY) == []
    await tick(house, freezer, 120)
    assert calls(events, LED) == [("turn_on", GREEN), ("turn_off", {})]
    assert [event.data for event in released] == [{"entity_id": LED}]
    assert attributes(house, RELAY)["alert"] == "low"


async def test_a_light_in_two_groups_shows_the_highest_of_both(house: HomeAssistant) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium"),
                                      smoke=raised("smoke", "high", "both")), config=CONFIG)
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    await turn(house, "smoke", "on")
    assert calls(events, LED) == [("turn_on", RED)]
    assert calls(events, RELAY) == [("turn_on", RED)]
    await turn(house, "smoke", "off")
    assert calls(events, LED) == [("turn_on", RED), ("turn_on", ORANGE)]
    assert calls(events, RELAY) == [("turn_on", RED), ("turn_on", GREEN)]
    await turn(house, "gate", "off")
    assert calls(events, LED)[-1] == ("turn_on", GREEN)


async def test_a_priority_without_repeat_is_sent_once(house: HomeAssistant, freezer: Any) -> None:
    config = {"alerts": {"lights": {"groups": GROUPS,
                                    "high": {"turn_on": {"color_name": "purple"}}}}}
    assert await setup(house, devices(smoke=raised("smoke", "high")), config=config)
    events = capture(house, "call_service")
    await turn(house, "smoke", "on")
    await tick(house, freezer, 60)
    assert calls(events, LED) == [("turn_on", {"color_name": "purple"})]


async def test_a_relay_only_turns_on_and_off(house: HomeAssistant, freezer: Any) -> None:
    """HA drops the colour, brightness and effect a relay can't take."""
    assert await setup(house, devices(mail=raised("mail", "low", "porch")), config=CONFIG)
    events = capture(house, "call_service")
    await turn(house, "mail", "on")
    await turn(house, "mail", "off")
    await tick(house, freezer, 120)
    assert calls(events, RELAY) == [("turn_on", BLUE), ("turn_on", GREEN), ("turn_off", {})]
    relay = [(event.data["service"],
              {k: v for k, v in event.data["service_data"].items() if k != "entity_id"})
             for event in events
             if event.data["domain"] == "switch"
             and event.data["service_data"].get("entity_id") == [REAL_RELAY]]
    assert relay == [("turn_on", {}), ("turn_on", {}), ("turn_off", {})]


async def test_a_ready_made_alert_borrows_its_group(house: HomeAssistant) -> None:
    """offline (medium) is on at once: its plug has no reading."""
    washer = {"name": "Lavadora", "appliance": {
        **APPLIANCE, "alerts": {"offline": {"for": {"seconds": 0}, "lights": True}}}}
    events = capture(house, "call_service")
    assert await setup(house, {**devices(), "lavadora": washer}, config=CONFIG)
    assert calls(events, LED) == [("turn_on", ORANGE)]
    assert attributes(house, LED)["alerts"] == [
        "binary_sensor.pururu_lavadora_appliance_alert_offline"]
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_alert_lights.py -n 0 -q -k "borrow or priority or blue or joins or resolved or group or relay"`
Expected: FAIL: no light call is made (nothing lends the lights yet).

- [ ] **Step 3: Implement the manager**

In `custom_components/pururu/alert_lights.py`, replace the imports with:

```python
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.light import ATTR_COLOR_NAME, LIGHT_TURN_ON_SCHEMA
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_NAME,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    Platform,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.util.color import color_name_to_rgb

from .const import CONF_ALERTS, CONF_CONFIG, CONF_LIGHTS, EVENT_ALERT_LIGHTS_RELEASED
from .feature import Device
from .features.alerts import PRIORITIES, ProblemAlert
from .features.lights import LIGHTS, Borrowable

_LOGGER = logging.getLogger(__name__)
```

After `SCHEMA = ...`, append:

```python
# The manager's contexts a light remembers: a late report of an earlier call is still its own
RECENT = 4


def settings(configured: Mapping[str, Any]) -> dict[str, Any]:
    """The validated config: alerts: lights: of `pururu:`; every default without one."""
    block = configured.get(CONF_CONFIG, {}).get(CONF_ALERTS, {}).get(CONF_LIGHTS)
    return dict(block) if block is not None else SCHEMA({})


def light_ids(
    settings: Mapping[str, Any], devices: Mapping[str, Any]
) -> dict[str, list[str]]:
    """Each group's lights, by unique ID (pururu_<device>_light_<key>)."""
    return {
        group: [
            Device(
                key=key, name=devices[key][CONF_NAME], namespace=LIGHTS.namespace
            ).object_id(light)
            for key, lights in members.items()
            for light in lights
        ]
        for group, members in settings[GROUPS].items()
    }


@dataclass(eq=False)
class _Light:
    """A light some alerts may borrow, and what the manager does to it now."""

    entity: Borrowable
    # The created alerts whose group holds it
    alerts: list[ProblemAlert] = field(default_factory=list)
    # What it shows: a priority, resolved, or None while free
    shown: str | None = None
    # The ids of the manager's latest contexts on it
    recent: deque[str] = field(default_factory=lambda: deque(maxlen=RECENT))
    repeating: CALLBACK_TYPE | None = None
    resolving: CALLBACK_TYPE | None = None

    def own(self) -> Context:
        """A new context for the manager's next change of this light."""
        context = Context()
        self.recent.append(context.id)
        return context

    def stop_repeating(self) -> None:
        """Stop sending the priority again."""
        if self.repeating is not None:
            self.repeating()
            self.repeating = None

    def stop_resolving(self) -> None:
        """Stop counting resolved's `for`."""
        if self.resolving is not None:
            self.resolving()
            self.resolving = None


class AlertLights:
    """Lends each light to its alerts: the highest priority on, then resolved, then free."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        settings: Mapping[str, Any],
        lights: list[_Light],
    ) -> None:
        """Lend `lights` as `settings` say; nothing happens before start()."""
        self._hass = hass
        self._entry = entry
        self._settings = settings
        self._lights = lights
        # Each alert's last on (True) or off: a state that is neither changes nothing
        self._on: dict[str, bool] = {}

    @callback
    def start(self) -> None:
        """Show what each light's alerts say now, then follow them."""
        for light in self._lights:
            for alert in light.alerts:
                state = self._hass.states.get(alert.entity_id)
                self._on[alert.entity_id] = state is not None and state.state == STATE_ON
        for light in self._lights:
            self._update(light)
        self._entry.async_on_unload(self._stop)
        self._entry.async_on_unload(
            async_track_state_change_event(
                self._hass, list(self._on), self._alert_changed
            )
        )

    @callback
    def _stop(self) -> None:
        """Cancel the timers: an unload calls nothing on the lights."""
        for light in self._lights:
            light.stop_repeating()
            light.stop_resolving()

    def _holding(self, light: _Light) -> list[str]:
        """The entity IDs of the light's alerts that are on."""
        return [
            alert.entity_id for alert in light.alerts if self._on.get(alert.entity_id)
        ]

    def _level(self, light: _Light) -> str | None:
        """The highest priority among the light's alerts that are on; None if none is."""
        on = [alert.priority for alert in light.alerts if self._on.get(alert.entity_id)]
        return max(on, key=PRIORITIES.index) if on else None

    @callback
    def _alert_changed(self, event: Event[EventStateChangedData]) -> None:
        """An alert turned on or off: update the lights of its group."""
        new = event.data["new_state"]
        if new is None or new.state not in (STATE_ON, STATE_OFF):
            return
        entity_id = event.data["entity_id"]
        on = new.state == STATE_ON
        if self._on.get(entity_id) == on:
            return
        self._on[entity_id] = on
        for light in self._lights:
            if any(alert.entity_id == entity_id for alert in light.alerts):
                self._update(light)

    @callback
    def _update(self, light: _Light) -> None:
        """Show what the light's alerts say: the highest priority on, resolved once the last ends."""
        level = self._level(light)
        if level is None:
            if light.shown in PRIORITIES:
                self._resolve(light)
            return
        light.stop_resolving()
        if level == light.shown:
            # An alert of the same priority joined or left
            light.entity.async_show_alert(level, self._holding(light), light.own())
            return
        light.stop_repeating()
        self._apply(light, level)
        if (repeat := self._settings[level].get(REPEAT)) is not None:
            light.repeating = async_track_time_interval(
                self._hass, partial(self._repeat, light), repeat
            )

    @callback
    def _repeat(self, light: _Light, _now: datetime) -> None:
        """Send the priority's turn_on again: a one-shot effect has ended by now."""
        if light.shown is not None and light.shown != RESOLVED:
            self._apply(light, light.shown)

    @callback
    def _apply(self, light: _Light, shown: str) -> None:
        """Show `shown` on the light and turn it on as its settings say, as the manager's change."""
        context = light.own()
        light.shown = shown
        light.entity.async_show_alert(shown, self._holding(light), context)
        self._call(light, SERVICE_TURN_ON, self._settings[shown][TURN_ON], context)

    @callback
    def _resolve(self, light: _Light) -> None:
        """Show resolved for its `for`, then hand the light back."""
        light.stop_repeating()
        light.stop_resolving()
        self._apply(light, RESOLVED)
        light.resolving = async_call_later(
            self._hass, self._settings[RESOLVED][FOR], partial(self._resolved, light)
        )

    @callback
    def _resolved(self, light: _Light, _now: datetime) -> None:
        light.resolving = None
        self._release(light, turn_off=True)

    @callback
    def _release(self, light: _Light, *, turn_off: bool) -> None:
        """Free the light: turned off first, unless someone took it back."""
        light.stop_repeating()
        light.stop_resolving()
        context = light.own()
        light.shown = None
        light.entity.async_show_alert(None, (), context)
        released = partial(self._released, light, context)
        if turn_off:
            self._call(light, SERVICE_TURN_OFF, {}, context, then=released)
        else:
            released()

    @callback
    def _released(self, light: _Light, context: Context) -> None:
        """Say the light is free, unless an alert took it again meanwhile."""
        if light.shown is None:
            self._hass.bus.async_fire(
                EVENT_ALERT_LIGHTS_RELEASED,
                {ATTR_ENTITY_ID: light.entity.entity_id},
                context=context,
            )

    @callback
    def _call(
        self,
        light: _Light,
        service: str,
        data: Mapping[str, Any],
        context: Context,
        then: Callable[[], None] | None = None,
    ) -> None:
        """Call light.`service` on the light in a task of the entry; `then` once it returned."""
        self._entry.async_create_task(
            self._hass,
            self._async_call(light.entity.entity_id, service, data, context, then),
            f"pururu alert lights {service}",
        )

    async def _async_call(
        self,
        entity_id: str,
        service: str,
        data: Mapping[str, Any],
        context: Context,
        then: Callable[[], None] | None,
    ) -> None:
        """A failure is a warning: the next repeat or change tries again."""
        try:
            await self._hass.services.async_call(
                Platform.LIGHT,
                service,
                {ATTR_ENTITY_ID: entity_id, **data},
                blocking=True,
                context=context,
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "The alert lights couldn't call light.%s on %s: %s",
                service,
                entity_id,
                err,
            )
        if then is not None:
            then()


@callback
def async_setup(
    hass: HomeAssistant,
    entry: ConfigEntry,
    settings: Mapping[str, Any],
    groups: Mapping[str, list[str]],
    alerts: Iterable[ProblemAlert],
    lights: Iterable[Borrowable],
) -> None:
    """Lend the created lights to the created alerts with lights, once HA has started.

    `groups`: each group's lights, by unique ID. A disabled light is left out:
    HA never added it.
    """
    registry = er.async_get(hass)
    enabled = {
        str(light.unique_id): light for light in lights if _enabled(registry, light)
    }
    borrowed: dict[str, _Light] = {}
    for alert in alerts:
        if alert.lights is None:
            continue
        for unique_id in groups[alert.lights]:
            if (entity := enabled.get(unique_id)) is not None:
                borrowed.setdefault(unique_id, _Light(entity)).alerts.append(alert)
    manager = AlertLights(hass, entry, settings, list(borrowed.values()))

    @callback
    def start(_hass: HomeAssistant) -> None:
        manager.start()

    entry.async_on_unload(async_at_started(hass, start))


def _enabled(registry: er.EntityRegistry, light: Borrowable) -> bool:
    """Whether the user left the light enabled."""
    registered = registry.async_get(light.entity_id)
    return registered is None or not registered.disabled
```

- [ ] **Step 4: Start the manager from `async_setup_entry`**

In `custom_components/pururu/__init__.py`:
- Add `from .features.lights import Borrowable` next to `from .features.alerts import ProblemAlert`.
- After `await alert2_alerts.async_sync(hass, entry, _alert2_alerts(hass, built))`, add:

```python
    lights_settings = alert_lights.settings(configured)
    alert_lights.async_setup(
        hass,
        entry,
        lights_settings,
        alert_lights.light_ids(lights_settings, devices),
        [
            entity
            for entity in built[Platform.BINARY_SENSOR]
            if isinstance(entity, ProblemAlert)
        ],
        [entity for entity in built[Platform.LIGHT] if isinstance(entity, Borrowable)],
    )
```

- In the `async_setup_entry` docstring, replace `The dashboard comes last:` with `The alert lights start after them: their alerts and lights are created. The dashboard comes last:`.

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run pytest tests/test_alert_lights.py -n 0 -q`
Expected: PASS.

- [ ] **Step 6: Run the neighbouring suites, lint, type-check**

Run: `uv run pytest tests/test_alerts.py tests/test_presets.py tests/test_lights.py tests/test_init.py -n 0 -q && uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu && uv run mypy custom_components/pururu`
Expected: PASS, no lint or type errors.

- [ ] **Step 7: Commit**

```bash
git add custom_components/pururu tests/test_alert_lights.py
git commit -m "pururu: alert lights lend lights to their alerts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Someone else changing a borrowed light

**Files:**
- Modify: `custom_components/pururu/alert_lights.py`
- Test: `tests/test_alert_lights.py`

**Interfaces:**
- Consumes: Task 3's `AlertLights`, `_Light.recent`, `_apply`, `_release`.
- Produces: `AlertLights._light_changed(event)`, the `_by_id: dict[str, _Light]` map; `NO_READING` imported from `.feature`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_alert_lights.py`, change the core imports to `from homeassistant.core import Event, HomeAssistant, State`, add `from homeassistant.exceptions import HomeAssistantError`, extend the helpers import with `settle`, and append:

```python
# --- someone else changing a borrowed light -------------------------------------------


async def test_a_change_by_someone_else_during_an_alert_is_put_back(house: HomeAssistant) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    await fake(house, REAL_LED, "on", {**BULB, "hs_color": [120.0, 100.0]})
    await house.async_block_till_done()
    assert calls(events, LED) == [("turn_on", ORANGE)]


def own_calls(events: list[Event]) -> list[Event]:
    return [event for event in events if event.data["domain"] == "light"
            and event.data["service_data"].get("entity_id") == LED]


async def test_the_managers_own_changes_are_not_put_back(house: HomeAssistant) -> None:
    """The real light reports what the manager asked, with the manager's context."""
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    events = capture(house, "call_service")
    await turn(house, "gate", "on")
    [call] = own_calls(events)
    house.states.async_set(REAL_LED, "on", {**BULB, "hs_color": [30.0, 100.0]},
                           context=call.context)
    await settle()
    await house.async_block_till_done()
    assert len(calls(events, LED)) == 1


async def test_a_late_report_of_an_earlier_call_is_still_the_managers(
        house: HomeAssistant, freezer: Any) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    events = capture(house, "call_service")
    await turn(house, "gate", "on")
    await tick(house, freezer, 15)
    first, _repeat = own_calls(events)
    house.states.async_set(REAL_LED, "on", {**BULB, "hs_color": [30.0, 100.0]},
                           context=first.context)
    await settle()
    await house.async_block_till_done()
    assert len(calls(events, LED)) == 2


async def test_a_change_during_resolved_hands_the_light_back_without_turning_it_off(
        house: HomeAssistant, freezer: Any) -> None:
    """Whoever changed it took it back on purpose: the alert is over."""
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    await turn(house, "gate", "off")
    released = capture(house, "pururu_alert_lights_released")
    events = capture(house, "call_service")
    await fake(house, REAL_LED, "on", {**BULB, "hs_color": [240.0, 100.0]})
    await house.async_block_till_done()
    assert [event.data for event in released] == [{"entity_id": LED}]
    assert "alert" not in attributes(house, LED)
    await tick(house, freezer, 120)
    assert calls(events, LED) == []


async def test_a_light_back_from_no_reading_during_resolved_shows_resolved_again(
        house: HomeAssistant, freezer: Any) -> None:
    """A bulb dropping off Zigbee isn't someone taking it back."""
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    await turn(house, "gate", "off")
    released = capture(house, "pururu_alert_lights_released")
    events = capture(house, "call_service")
    await fake(house, REAL_LED, "unavailable")
    await house.async_block_till_done()
    assert calls(events, LED) == []
    await fake(house, REAL_LED, "off", BULB)
    await house.async_block_till_done()
    assert calls(events, LED) == [("turn_on", GREEN)]
    assert released == []
    await tick(house, freezer, 120)
    assert calls(events, LED) == [("turn_on", GREEN), ("turn_off", {})]
    assert [event.data for event in released] == [{"entity_id": LED}]


async def test_a_light_gone_unavailable_is_left_until_it_comes_back(house: HomeAssistant) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    await fake(house, REAL_LED, "unavailable")
    await house.async_block_till_done()
    assert calls(events, LED) == []
    await fake(house, REAL_LED, "off", BULB)
    await house.async_block_till_done()
    assert calls(events, LED) == [("turn_on", ORANGE)]


async def test_a_free_light_is_left_alone(house: HomeAssistant) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    events = capture(house, "call_service")
    await fake(house, REAL_LED, "on", BULB)
    await house.async_block_till_done()
    assert calls(events, LED) == []


async def test_a_failing_call_is_a_warning_and_the_repeat_tries_again(
        house: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse(self: Any, **kwargs: Any) -> None:
        raise HomeAssistantError("Zigbee2MQTT refused it")

    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    monkeypatch.setattr(module("features.lights").Light, "async_turn_on", refuse)
    events = capture(house, "call_service")
    await turn(house, "gate", "on")
    assert ("The alert lights couldn't call light.turn_on on light.pururu_pool_light_led: "
            "Zigbee2MQTT refused it") in caplog.text
    await tick(house, freezer, 15)
    assert calls(events, LED) == [("turn_on", ORANGE)] * 2
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_alert_lights.py -n 0 -q -k "someone or own or late or resolved_hands or no_reading or unavailable or free or failing"`
Expected: FAIL: `test_a_change_by_someone_else_during_an_alert_is_put_back`, `test_a_change_during_resolved_…`, `test_a_light_back_from_no_reading_…` and `test_a_light_gone_unavailable_…` fail (nothing follows the lights yet). The own-change, free-light and failing-call tests already pass: they pin behaviour this task must keep.

- [ ] **Step 3: Follow the lights**

In `custom_components/pururu/alert_lights.py`:

Add `from .feature import NO_READING, Device` (replacing `from .feature import Device`).

In `AlertLights.__init__`, after `self._lights = lights`, add:

```python
        self._by_id = {light.entity.entity_id: light for light in lights}
```

In `start()`, append after the alerts' subscription:

```python
        self._entry.async_on_unload(
            async_track_state_change_event(
                self._hass, list(self._by_id), self._light_changed
            )
        )
```

Add the method after `_alert_changed`:

```python
    @callback
    def _light_changed(self, event: Event[EventStateChangedData]) -> None:
        """Someone else changed a borrowed light: put it back, or during resolved let it go.

        The manager's own changes carry one of its recent contexts. A light
        without a reading was taken by nobody; one back from it during
        resolved shows resolved again, its `for` running on.
        """
        light = self._by_id[event.data["entity_id"]]
        old, new = event.data["old_state"], event.data["new_state"]
        if light.shown is None or old is None or new is None:
            return
        if new.state in NO_READING or event.context.id in light.recent:
            return
        if light.shown != RESOLVED:
            self._apply(light, light.shown)
        elif old.state in NO_READING:
            self._apply(light, RESOLVED)
        else:
            self._release(light, turn_off=False)
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_alert_lights.py -n 0 -q`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu && uv run mypy custom_components/pururu`
Expected: no errors.

```bash
git add custom_components/pururu/alert_lights.py tests/test_alert_lights.py
git commit -m "pururu: alert lights put a borrowed light back

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Start, restart, reload, and lights left out

**Files:**
- Modify: `custom_components/pururu/alert_lights.py`
- Test: `tests/test_alert_lights.py`

**Interfaces:**
- Consumes: Task 2's `Borrowable.restored_alert`; Task 3's `async_setup`, `AlertLights.start`, `_resolve`.
- Produces: the start table (restored `alert` with no alert on → `_resolve`), restored lights outside every group, the "not created" warning.

- [ ] **Step 1: Write the failing tests**

In `tests/test_alert_lights.py`, add `from homeassistant.helpers import entity_registry as er`, extend the helpers import with `reload, restart`, and append:

```python
# --- start, restart, reload -------------------------------------------------------------


async def test_a_restart_with_an_alert_on_shows_it(house: HomeAssistant) -> None:
    await fake(house, REAL["gate"], "on")
    events = capture(house, "call_service")
    await restart(house, devices(gate=raised("gate", "medium")),
                  (State(alert("gate"), "on"), {}),
                  (State(LED, "on", {"alert": "medium"}), {}), config=CONFIG)
    assert calls(events, LED) == [("turn_on", ORANGE)]


async def test_a_restart_during_resolved_hands_the_light_back(
        house: HomeAssistant, freezer: Any) -> None:
    released = capture(house, "pururu_alert_lights_released")
    events = capture(house, "call_service")
    await restart(house, devices(gate=raised("gate", "medium")),
                  (State(alert("gate"), "off"), {}),
                  (State(LED, "on", {"alert": "resolved"}), {}), config=CONFIG)
    assert calls(events, LED) == [("turn_on", GREEN)]
    await tick(house, freezer, 120)
    assert calls(events, LED) == [("turn_on", GREEN), ("turn_off", {})]
    assert [event.data for event in released] == [{"entity_id": LED}]


async def test_a_restart_after_the_alert_ended_hands_the_light_back(house: HomeAssistant) -> None:
    events = capture(house, "call_service")
    await restart(house, devices(gate=raised("gate", "medium")),
                  (State(alert("gate"), "off"), {}),
                  (State(LED, "on", {"alert": "medium"}), {}), config=CONFIG)
    assert calls(events, LED) == [("turn_on", GREEN)]


async def test_a_restart_with_nothing_borrowed_calls_nothing(house: HomeAssistant) -> None:
    events = capture(house, "call_service")
    await restart(house, devices(gate=raised("gate", "medium")),
                  (State(alert("gate"), "off"), {}), (State(LED, "off"), {}), config=CONFIG)
    assert calls(events, LED) == []


async def test_a_light_out_of_every_group_is_handed_back(
        house: HomeAssistant, freezer: Any) -> None:
    """The YAML dropped it from its group while an alert had it."""
    released = capture(house, "pururu_alert_lights_released")
    events = capture(house, "call_service")
    await restart(house, devices(mail=raised("mail", "low", "porch")),
                  (State(LED, "on", {"alert": "high"}), {}),
                  config={"alerts": {"lights": {"groups": {"porch": {"varanda": ["rele"]}}}}})
    assert calls(events, LED) == [("turn_on", GREEN)]
    await tick(house, freezer, 120)
    assert [event.data for event in released] == [{"entity_id": LED}]


async def test_a_reload_with_an_alert_on_neither_greens_nor_releases(house: HomeAssistant) -> None:
    config = devices(gate=raised("gate", "medium"))
    assert await setup(house, config, config=CONFIG)
    await turn(house, "gate", "on")
    released = capture(house, "pururu_alert_lights_released")
    events = capture(house, "call_service")
    await reload(house, config, config=CONFIG)
    await house.async_block_till_done()
    assert ("turn_on", GREEN) not in calls(events, LED)
    assert "turn_off" not in [service for service, _ in calls(events, LED)]
    assert released == []
    assert attributes(house, LED)["alert"] == "medium"


async def test_an_alert_without_a_reading_for_a_moment_keeps_the_light(
        house: HomeAssistant) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    house.states.async_set(alert("gate"), "unavailable")
    await settle()
    house.states.async_set(alert("gate"), "on")
    await settle()
    await house.async_block_till_done()
    assert calls(events, LED) == []
    assert attributes(house, LED)["alert"] == "medium"


async def test_a_light_not_created_is_left_out_of_its_group(
        house: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(house).async_get_or_create(
        "light", "template", "someone_else", suggested_object_id="pururu_pool_light_led")
    events = capture(house, "call_service")
    assert await setup(house, devices(mail=raised("mail", "low", "both")), config=CONFIG)
    await turn(house, "mail", "on")
    assert calls(events, RELAY) == [("turn_on", BLUE)]
    assert calls(events, LED) == []
    assert ("light.pururu_pool_light_led is not created: the alert lights group both "
            "goes without it") in caplog.text


async def test_a_disabled_light_is_left_out_quietly(
        house: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(house).async_get_or_create(
        "light", "pururu", "pururu_pool_light_led", suggested_object_id="pururu_pool_light_led",
        disabled_by=er.RegistryEntryDisabler.USER)
    events = capture(house, "call_service")
    assert await setup(house, devices(mail=raised("mail", "low", "both")), config=CONFIG)
    await turn(house, "mail", "on")
    assert calls(events, RELAY) == [("turn_on", BLUE)]
    assert calls(events, LED) == []
    assert "goes without it" not in caplog.text
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_alert_lights.py -n 0 -q -k "restart or reload or reading or created or disabled"`
Expected: FAIL: `test_a_restart_during_resolved_…`, `test_a_restart_after_the_alert_ended_…`, `test_a_light_out_of_every_group_…` (nothing hands a restored light back) and `test_a_light_not_created_…` (no warning). The others pin behaviour Task 3 already has.

- [ ] **Step 3: Hand back restored lights, warn about lights not created**

In `custom_components/pururu/alert_lights.py`:

In `AlertLights.start()`, replace

```python
        for light in self._lights:
            self._update(light)
```

with

```python
        for light in self._lights:
            if self._level(light) is None and light.entity.restored_alert is not None:
                # Borrowed before the restart or reload, and none of its alerts is on now
                self._resolve(light)
            else:
                self._update(light)
```

Replace `async_setup` with:

```python
@callback
def async_setup(
    hass: HomeAssistant,
    entry: ConfigEntry,
    settings: Mapping[str, Any],
    groups: Mapping[str, list[str]],
    alerts: Iterable[ProblemAlert],
    lights: Iterable[Borrowable],
) -> None:
    """Lend the created lights to the created alerts with lights, once HA has started.

    `groups`: each group's lights, by unique ID. A light of a group that isn't
    created is logged and left out; a disabled one is left out, as HA never
    added it. A light the alert lights had before a restart or reload is
    handed back even when it is in no group now.
    """
    registry = er.async_get(hass)
    built = list(lights)
    created = {str(light.unique_id) for light in built}
    for group, members in groups.items():
        for unique_id in members:
            if unique_id not in created:
                _LOGGER.warning(
                    "%s.%s is not created: the alert lights group %s goes without it",
                    Platform.LIGHT,
                    unique_id,
                    group,
                )
    enabled = {
        str(light.unique_id): light for light in built if _enabled(registry, light)
    }
    borrowed: dict[str, _Light] = {}
    for alert in alerts:
        if alert.lights is None:
            continue
        for unique_id in groups[alert.lights]:
            if (entity := enabled.get(unique_id)) is not None:
                borrowed.setdefault(unique_id, _Light(entity)).alerts.append(alert)
    for unique_id, entity in enabled.items():
        if unique_id not in borrowed and entity.restored_alert is not None:
            borrowed[unique_id] = _Light(entity)
    manager = AlertLights(hass, entry, settings, list(borrowed.values()))

    @callback
    def start(_hass: HomeAssistant) -> None:
        manager.start()

    entry.async_on_unload(async_at_started(hass, start))
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_alert_lights.py -n 0 -q`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu && uv run mypy custom_components/pururu`
Expected: no errors.

```bash
git add custom_components/pururu/alert_lights.py tests/test_alert_lights.py
git commit -m "pururu: alert lights across restarts and reloads

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Docs, version, the whole suite

**Files:**
- Create: `docs/concepts/alert-lights.mdx`
- Modify: `docs.json`, `docs/features/alerts.mdx`, `docs/features/lights.mdx`, `docs/reference/configuration.mdx`, `docs/reference/troubleshooting.mdx`, `docs/develop/architecture.mdx`, `CLAUDE.md`, `custom_components/pururu/manifest.json`
- Test: `tests/test_alert_lights.py`

**Interfaces:**
- Consumes: `alert_lights.SCHEMA`; the helpers `setup(..., config=)`.

- [ ] **Step 1: Write the failing docs tests**

In `tests/test_alert_lights.py`, add `from pathlib import Path`, `import re`, `import yaml` to the imports, and append:

```python
# --- the docs ----------------------------------------------------------------------------

PAGE = Path(__file__).resolve().parents[1] / "docs/concepts/alert-lights.mdx"


def yaml_blocks() -> list[Any]:
    return [yaml.safe_load(block)
            for block in re.findall(r"```yaml[^\n]*\n(.*?)```", PAGE.read_text(), re.DOTALL)]


async def test_the_pages_example_is_valid(ha: HomeAssistant) -> None:
    example = yaml_blocks()[0]["pururu"]
    assert await setup(ha, example["devices"], config=example["config"])


def test_the_documented_defaults_are_the_defaults(ha: HomeAssistant) -> None:
    [defaults] = [block["pururu"]["config"]["alerts"]["lights"] for block in yaml_blocks()
                  if "pururu" in block and "high" in block["pururu"]["config"]["alerts"]["lights"]]
    schema = module("alert_lights").SCHEMA
    assert schema(defaults) == schema({})
```

Run: `uv run pytest tests/test_alert_lights.py -n 0 -q -k docs`
Expected: FAIL: `FileNotFoundError` for `docs/concepts/alert-lights.mdx`.

- [ ] **Step 2: Write the concept page**

Create `docs/concepts/alert-lights.mdx`:

````mdx
---
title: Alert lights
description: Lights that show pururu's alerts while they are on, in the colour of the most serious one, and are handed back when they end.
---

While an [alert](/features/alerts) is on, some lights can show it: the pool's LED breathing orange for a washer running too long, red for a leak. When the last alert that uses a light ends, the light turns green for a while, then off, and pururu says it's free so whoever used it before can take it back.

An alert opts in with `lights`. The lights come in **groups**, under `config:`:

```yaml title="configuration.yaml"
pururu:
  config:
    alerts:
      lights:
        groups:
          default: {pool: [led]}
          externas: {pool: [led], varanda: [teto]}
  devices:
    pool:
      name: Piscina
      lights:
        led: {entity: light.pool_led, name: LED}
    varanda:
      name: Varanda
      lights:
        teto: {entity: light.varanda_teto, name: Teto}
    laundry_washer:
      name: Máquina de lavar
      appliance:
        power: sensor.washer_plug_power
        running: {threshold: 4, on_delay: {minutes: 1}, off_delay: {minutes: 2}}
        alerts:
          long_cycle: {for: {hours: 3}, lights: true}
      alerts:
        overload: {name: Sobrecarga, when: appliance_power, above: 2500, priority: high, lights: externas}
```

`long_cycle` (medium) borrows the `default` group: `light.pururu_pool_light_led` breathes orange. `overload` (high) borrows `externas`: both lights breathe red. The LED is in both groups, so while both alerts are on it shows red, the higher of the two.

## Settings

### An alert's `lights`

<Property name="lights" type="true | group" optional>
  In an alert you write, or in a feature's ready-made one. `true` borrows the group `default`; a group's name borrows that group. Without it, or with `false`, the alert borrows nothing.
</Property>

### `config: alerts: lights:`

Every key is optional.

<Property name="groups" type="map" optional>
  A map of **group name → device key → list of that device's `lights`**, such as `externas: {pool: [led], varanda: [teto]}`. A group holds at least one light, a light may be in several groups, and a group may hold lights of several devices. Relays (`switch.*` in `lights`) are welcome: they only turn on and off.
</Property>

---

<Property name="high, medium, low" type="map" optional>
  What a light shows while its most serious alert on has this priority:

  - `turn_on`: the data of Home Assistant's [`light.turn_on`](https://www.home-assistant.io/integrations/light/#action-lightturn_on), under its own names (`color_name`, `rgb_color`, `brightness_pct`, `effect`, `flash`, `transition`…). No `entity_id`: the light is the group's. `{}` just turns it on.
  - `repeat`: optional, `{seconds: N}`. The same `turn_on` again every N seconds while the priority lasts, for a one-shot effect such as Zigbee2MQTT's `breathe`.

  Writing a priority replaces its default whole: `high: {turn_on: {color_name: purple}}` sends no `breathe` and doesn't repeat.
</Property>

---

<Property name="resolved" type="map" optional>
  What a light shows once its last alert ended: `turn_on`, as above, and `for: {seconds: N}`, how long before it's turned off and handed back. Both are required.
</Property>

The defaults, which today's configurations get without writing anything:

```yaml
pururu:
  config:
    alerts:
      lights:
        high: {turn_on: {color_name: red, brightness_pct: 100, effect: breathe}, repeat: {seconds: 15}}
        medium: {turn_on: {color_name: orange, brightness_pct: 100, effect: breathe}, repeat: {seconds: 15}}
        low: {turn_on: {color_name: blue, brightness_pct: 100, effect: breathe}, repeat: {seconds: 15}}
        resolved: {turn_on: {color_name: green, brightness_pct: 50}, for: {seconds: 120}}
```

## Each light uses what it has

pururu only calls the light's `turn_on` and `turn_off`. The light takes what it can: a bulb without colour ignores `color_name`, one without effects ignores `effect`, a pururu light ignores an effect its bulb doesn't list, and a relay only turns on. The same settings work for every light in a group, and replacing a bulb needs no change.

## What a light goes through

| When | The light |
|---|---|
| One of its alerts turns on | `turn_on` of that alert's priority, again every `repeat` |
| Another of its alerts turns on or off | the highest priority among its alerts on; nothing sent if it didn't change |
| The last of its alerts turns off | `turn_on` of `resolved`, for its `for` |
| One of its alerts turns on during `resolved` | taken again: that priority's `turn_on` |
| `resolved`'s `for` ends | `turn_off`, then the event `pururu_alert_lights_released` |

- **Only its own alerts hold it.** An alert that doesn't use a light never keeps it: the LED is handed back once its alerts are off, whatever else is on.
- **Its attributes say what it's doing:** `alert` (`high`, `medium`, `low` or `resolved`) and `alerts`, the entity IDs of its alerts that are on. Both are gone once it's free.
- **An alert that is briefly `unavailable`**, as during a pururu reload, changes nothing.

## Someone else changes a borrowed light

- **During an alert**, pururu puts the light back at once: an automation or a person turning it off, or to another colour, doesn't hide the alert. Only the alert ending frees the light.
- **During `resolved`**, whoever changed the light took it back on purpose: pururu hands it back at once, without turning it off, and fires the event.
- **A light going `unavailable`** isn't taken by anyone: pururu waits, and shows what it should once the light is back.
- pururu knows its own changes by their context: a bulb reporting what pururu asked is never "put back".

## Taking the light back

pururu doesn't know what the light did before the alert: whoever used it does. Listen to the event:

```yaml
automation:
  - alias: Pool LED back to blue
    triggers:
      - trigger: event
        event_type: pururu_alert_lights_released
        event_data: {entity_id: light.pururu_pool_light_led}
    conditions:
      - condition: state
        entity_id: switch.pururu_pool_switch_filter
        state: "on"
    actions:
      - action: light.turn_on
        target: {entity_id: light.pururu_pool_light_led}
        data: {color_name: blue}
```

## Restarts and reloads

- The lights follow the alerts once Home Assistant has started.
- A light keeps its `alert` across restarts and reloads. If none of its alerts is on when Home Assistant starts, as when one ended while it was off or it restarted during the green, the light goes through `resolved` and is handed back. So does a light taken out of every group while an alert had it.
- A reload while an alert is on sends that alert's `turn_on` again: no green, no release.

## Good to know

- A light of a group that isn't created, because its ID is taken, is left out of the group, and the log says so. A light you disabled is left out quietly.
- A call that fails, a light unavailable or Zigbee2MQTT refusing, is a warning in the log. The next `repeat` or change tries again.
- Alert2's **Ignorar** stops the reminders on the phones. It doesn't reach the lights: they show the alert until it ends.
````

- [ ] **Step 3: Run the docs tests**

Run: `uv run pytest tests/test_alert_lights.py -n 0 -q -k docs`
Expected: PASS.

- [ ] **Step 4: Update the other pages**

`docs.json`: in the "Concepts" group, after `{ "title": "Programs", "href": "/concepts/programs" },` add `{ "title": "Alert lights", "href": "/concepts/alert-lights" },`.

`docs/features/alerts.mdx`:
- After the `notify` `<Property>` block (ending with `See [Getting notified](#getting-notified).\n</Property>`), add:

```mdx

---

<Property name="lights" type="true | group" optional>
  Lights that show the alert while it's on: `true` for the group `default`, or a group's name, from `config: alerts: lights: groups`. See [Alert lights](/concepts/alert-lights).
</Property>
```

- In the "Entity" section, replace the sentence

  `Its attributes are **`priority`** and **`watches`**, the entity it watches, and, with `notify`, **`message`** and **`done_message`**.`

  with

  `Its attributes are **`priority`** and **`watches`**, the entity it watches; with `notify`, **`message`** and **`done_message`**; with `lights`, **`lights`**, the name of the group it borrows.`

`docs/features/lights.mdx`: before `## Good to know`, add:

```mdx
## Alert lights

A light in a group of [alert lights](/concepts/alert-lights) shows alerts: while it does, its attributes **`alert`** (`high`, `medium`, `low` or `resolved`) and **`alerts`** say what for, and it keeps `alert` across restarts. Asked for an effect its bulb doesn't list, it passes on the rest without it.
```

`docs/reference/configuration.mdx`:
- In the big example, after `pururu:` and before `  floors:`, add:

```yaml
  config:
    alerts:
      lights:
        groups:
          default: {sala: [teto]}
```

  and give the `long_cycle` alert `lights: true` (add the line `          lights: true` after `          priority: medium`).
- Change `- `pururu:` has three optional keys: `floors`, `areas` and `devices`. Any other key is an error.` to `- `pururu:` has four optional keys: `config`, `floors`, `areas` and `devices`. Any other key is an error.`
- Before `## floors`, add:

```mdx
## config

Settings of the whole house, not of a device.

<Property name="alerts.lights" type="map" optional>
  The alert lights: `groups` of lights that alerts borrow with `lights`, and what a light shows for each priority (`high`, `medium`, `low`) and once its alerts ended (`resolved`). See [Alert lights](/concepts/alert-lights#settings).
</Property>
```

`docs/reference/troubleshooting.mdx`: after the `### A light is `unavailable`` section (before `### The cycle ends too early, or never starts`), add:

```mdx
### `light.… is not created: the alert lights group … goes without it`

A light of an [alert lights](/concepts/alert-lights) group isn't created, usually because its ID is taken (see `… is already taken by …`). The group's other lights still show its alerts. Free the ID, or take the light out of the group.

### `The alert lights couldn't call light.… on …: …`

Turning a borrowed light on or off failed: it's unavailable, or its integration refused the call. The alert lights go on: the next `repeat`, or the next change of the light or its alerts, tries again.
```

`docs/develop/architecture.mdx`:
- In the mermaid chart, replace `    P7 --> P8["8. dashboard.async_setup"]` with:

```
    P7 --> P8["8. alert_lights.async_setup<br/>lights for the alerts"]
    P8 --> P9["9. dashboard.async_setup"]
```

- Replace the list item `8. **Show the dashboard.** It comes last because it lists everything above.` with:

```mdx
8. **Lend lights to the alerts** (`alert_lights.py`): the created alerts with `lights` and the created pururu lights of their groups (`config.alerts.lights.groups`, resolved to unique IDs) go to a manager that starts once HA has started. It keeps, per light, only what the alerts can't tell: whether it is in `resolved` (its `for` timer) and its `repeat` timer; the level is computed from the alerts' states each time. It calls only `light.turn_on`/`turn_off` on the pururu light, each call with a new `Context` whose id the light remembers (the last few), so a state change carrying one is its own. A light is a `Borrowable` (`features/lights.py`): it shows `alert`/`alerts` and restores `alert`, which is how a light borrowed before a restart or reload is handed back.
9. **Show the dashboard.** It comes last because it lists everything above.
```

`CLAUDE.md`, in the Architecture list of `async_setup_entry`:
- Replace `    8. Show the dashboard (`dashboard.py`).` with:

```markdown
    8. Lend lights to the alerts (`alert_lights.py`): an alert's `lights` (`true` is the group `default`) borrows a group of `config: alerts: lights: groups` (device key → its `lights` keys); a light shows the highest priority's `turn_on` among its alerts on (`repeat` for one-shot effects), `resolved` for its `for` once the last ends, then `turn_off` and `pururu_alert_lights_released`. Only `light.turn_on`/`turn_off` on the pururu light, which uses what it has (`Borrowable`: `alert`/`alerts` attributes, `alert` restored, an unknown effect dropped); a change without one of the manager's recent contexts is put back (during `resolved`: released, not turned off); a light restored with `alert` and none of its alerts on goes through `resolved`.
    9. Show the dashboard (`dashboard.py`).
```

- [ ] **Step 5: Bump the version**

In `custom_components/pururu/manifest.json`, change `"version": "0.1.18"` to `"version": "0.1.19"`.

Run: `python3 release.py check`
Expected: exits 0.

- [ ] **Step 6: Check the docs' links**

Run: `pnpm install && pnpm docs:check`
Expected: no broken links.

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest`
Expected: PASS, including ruff, ruff format, mypy, hassfest and the quality scale (`tests/test_code.py`).

- [ ] **Step 8: Commit**

```bash
git add docs docs.json CLAUDE.md custom_components/pururu/manifest.json tests/test_alert_lights.py
git commit -m "pururu: alert lights docs (0.1.19)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
