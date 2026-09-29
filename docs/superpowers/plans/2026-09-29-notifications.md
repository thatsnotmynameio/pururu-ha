# Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reaction can send a message through HA's `notify` actions, a device can enable its features' ready-made notifications (`notifications: appliance: finished`), and the ready-made alert `finished` (with `lasts`) leaves the alerts.

**Architecture:** Every notification is an automation pururu generates. A reaction's `message` adds notify actions to its existing automation (`pururu/automations/reactions.yaml`). A ready-made notification is a `Happening` a feature offers (`Feature.notifications`). Each enabled one becomes an automation of a second `generated.Kind` (`pururu/automations/notifications.yaml`, same folder, same include line). The notify schema, the text escape and the notify actions live in a new leaf module, `messages.py`.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3 custom integration, voluptuous, pytest with `pytest-homeassistant-custom-component`, uv, docs.page MDX.

**Spec:** `docs/superpowers/specs/2026-09-29-notifications-design.md`

## Global Constraints

- Run everything from the worktree root with `uv run ...`; `uv run pytest` also runs ruff, ruff format, mypy (strict) and hassfest (`tests/test_code.py`). Use `-n 0` for a single process.
- Lint/type scope is `custom_components/pururu` only; tests are not linted, but follow the style of their neighbours (long lines, `pytest.param(..., id=...)`).
- Code comments and docstrings match the surrounding density and tone: short, plain English, say *why*.
- Every automation ID is `pururu_<device>_<...>`: a reaction's `pururu_<device>_reaction_<key>`, a notification's `pururu_<device>_<namespace>_notification_<name>`.
- A notify action is `notify.` followed by a slug; `config: notify` and a reaction's or notification's `notify` take one or a list; the own one **replaces** the default.
- Message and title are text, never templates: `{` goes through `messages.escaped`.
- The title of every message is the device's name.
- A reaction's program starts **before** its notify actions; each notify action has `continue_on_error: true`.
- The appliance's `finished` happening: watches `running`, `from: "on"`, `to: "off"`. Texts: en `Finished` / `The cycle finished.`, pt-BR `Terminou` / `O ciclo terminou.`
- Removed: the ready-made alert `finished`, `Preset.lasts`, `ElapsedAlert`'s `lasts`. `appliance: alerts: finished` → `finished is now a notification: notifications: appliance: finished`.
- `pt-BR.json` must have exactly `en.json`'s keys (`test_translation_files_match`).
- MDX: `{` and `<` outside code are JSX; keep them in backticks or code blocks. Use pnpm, never npm.
- Version: `custom_components/pururu/manifest.json` → `0.1.22`.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01XHpvmVKUrrYejX5EQVAJU7
  ```

## Review Focus

- **A plug reconnecting or a reload** (`running`: `unavailable → off`, or `on → unavailable → on`) must not send "finished"; only a real `on → off` does. Test: Task 4, `test_a_plug_reconnecting_tells_nobody`.
- **A message with `{`** (`"Roupa {pronta}"`, `"{% raw %}"`) must reach the phone as written, not rendered or failing. Test: Task 1, `test_a_message_is_text` (end to end through HA's automation, not only the dict).
- **A notify action that doesn't exist** must not keep the reaction's program from starting. Test: Task 2, `test_a_missing_notify_action_does_not_keep_the_program_from_starting`.
- **Two devices whose reaction and notification IDs meet** (device `a`'s reaction `x_appliance_notification_finished` and device `a_reaction_x`'s `finished`, both `pururu_a_reaction_x_appliance_notification_finished`): the configuration is refused, not one automation silently lost. Test: Task 3, `test_a_notification_and_a_reaction_with_one_id_are_refused`.
- **Upgrading with `appliance: alerts: finished`** must fail with a message that says where it went, not a generic "not a ready-made alert". Test: Task 5, `test_finished_as_an_alert_says_where_it_went`.

---

### Task 1: `messages.py`: where a message goes, and how it is written

**Files:**
- Create: `custom_components/pururu/messages.py`
- Modify: `custom_components/pururu/alert2_alerts.py` (drop `_text`, use `messages.escaped`)
- Modify: `custom_components/pururu/const.py` (add `CONF_NOTIFY`, `CONF_MESSAGE`, `CONF_NOTIFICATIONS`)
- Test: `tests/test_messages.py` (create)

**Interfaces:**
- Produces:
  - `messages.TARGETS: Callable[[Any], list[str]]`: validates `notify.<slug>` or a list of them (at least one) into a list.
  - `messages.escaped(text: str) -> str`: the text as HA's templates show it (raw block).
  - `messages.actions(targets: Sequence[str], title: str, message: str) -> list[dict[str, Any]]`.
  - `const.CONF_NOTIFY = "notify"`, `const.CONF_MESSAGE = "message"`, `const.CONF_NOTIFICATIONS = "notifications"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_messages.py`:

```python
"""Messages: where they go (notify actions) and how they are written (text, never a template)."""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
import pytest
import voluptuous as vol

from helpers import module


@pytest.mark.parametrize(("value", "expected"), [
    pytest.param("notify.mobile_app_phone", ["notify.mobile_app_phone"], id="one"),
    pytest.param(["notify.a", "notify.b"], ["notify.a", "notify.b"], id="a list"),
])
def test_targets_are_a_list_of_notify_actions(ha: HomeAssistant, value: Any, expected: list[str]) -> None:
    assert module("messages").TARGETS(value) == expected


@pytest.mark.parametrize("value", [
    pytest.param("mobile_app_phone", id="no domain"),
    pytest.param("script.phone", id="another domain"),
    pytest.param("notify.Phone", id="not a slug"),
    pytest.param("notify.", id="no name"),
    pytest.param([], id="none"),
    pytest.param(None, id="null"),
])
def test_anything_else_is_refused(ha: HomeAssistant, value: Any) -> None:
    with pytest.raises(vol.Invalid):
        module("messages").TARGETS(value)


@pytest.mark.parametrize("text", [
    "A máquina terminou.", "Roupa {pronta}", "{{ states('x') }}", "{% raw %}", "{% endraw %}", "a {% b",
])
def test_escaped_text_renders_as_written(ha: HomeAssistant, text: str) -> None:
    rendered = Template(module("messages").escaped(text), ha).async_render(parse_result=False)
    assert rendered == text


def test_text_without_a_brace_is_left_alone(ha: HomeAssistant) -> None:
    assert module("messages").escaped("A máquina terminou.") == "A máquina terminou."


def test_each_target_is_told_the_title_and_the_message(ha: HomeAssistant) -> None:
    assert module("messages").actions(["notify.a", "notify.b"], "Máquina", "Terminou {x}") == [
        {"action": "notify.a", "data": {"title": "Máquina", "message": "{% raw %}Terminou {x}{% endraw %}"},
         "continue_on_error": True},
        {"action": "notify.b", "data": {"title": "Máquina", "message": "{% raw %}Terminou {x}{% endraw %}"},
         "continue_on_error": True},
    ]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_messages.py -n 0 -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'custom_components.pururu.messages'`.

- [ ] **Step 3: Write `messages.py`, and move the escape out of `alert2_alerts.py`**

`custom_components/pururu/messages.py`:

```python
"""Messages: the notify actions they go to, and their text as HA shows it.

A reaction's message and a ready-made notification are told through HA's
notify actions, from the automations pururu generates. Their text is the
user's, never a template.
"""

from collections.abc import Sequence
from typing import Any

import voluptuous as vol

from homeassistant.helpers import config_validation as cv

# A notify action: notify.<name>, as mobile_app's notify.mobile_app_<phone>
ACTION = vol.All(
    cv.string,
    vol.Match(r"^notify\.[a-z0-9_]+$", msg="a notify action is notify.<name>"),
)
# config: notify, and a reaction's or a notification's own: one or a list
TARGETS = vol.All(cv.ensure_list, vol.Length(min=1), [ACTION])


def escaped(text: str) -> str:
    """`text` as HA's templates show it: every template delimiter starts with {.

    In a raw block, as Alert2's own jinja2Escape does: each {% in the text
    (an {% endraw %} would end the block) leaves it, is written as a string,
    and opens it again.
    """
    if "{" not in text:
        return text
    escaped_text = text.replace("{%", '{% endraw %}{{ "{%" }}{% raw %}')
    return f"{{% raw %}}{escaped_text}{{% endraw %}}"


def actions(targets: Sequence[str], title: str, message: str) -> list[dict[str, Any]]:
    """Tell each target the title and the message; one failing doesn't keep the next from being told."""
    data = {"title": escaped(title), "message": escaped(message)}
    return [
        {"action": target, "data": dict(data), "continue_on_error": True}
        for target in targets
    ]
```

In `custom_components/pururu/alert2_alerts.py`: delete `_text` (lines 40-51), add `from .messages import escaped` next to `from . import files`, and replace the three `_text(` calls in `alert()` with `escaped(`.

In `custom_components/pururu/const.py`, after `CONF_REACTIONS`:

```python
# A reaction's message, and where messages go (a reaction's, a notification's, config's)
CONF_MESSAGE: Final = "message"
CONF_NOTIFY: Final = "notify"
# A device's ready-made notifications: feature key -> name -> settings
CONF_NOTIFICATIONS: Final = "notifications"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_messages.py tests/test_alert2.py -n 0 -q`
Expected: PASS (the Alert2 tests prove the moved escape is unchanged).

- [ ] **Step 5: Commit**

```bash
git add custom_components/pururu/messages.py custom_components/pururu/alert2_alerts.py custom_components/pururu/const.py tests/test_messages.py
git commit -m "pururu: messages, their notify actions and text"   # plus the two trailer lines
```

---

### Task 2: a reaction's `message`, and `config: notify`

**Files:**
- Modify: `custom_components/pururu/reactions.py` (schema, `_consistent`, `automation`)
- Modify: `custom_components/pururu/__init__.py` (`CONFIG_SCHEMA`'s `config`, `_messages_sent`, `_automations`)
- Modify: `custom_components/pururu/features/alerts.py:62` (the `NOTIFY` comment only if ruff flags a name clash: none expected)
- Test: `tests/test_reactions.py`

**Interfaces:**
- Consumes: `messages.TARGETS`, `messages.actions`, `const.CONF_NOTIFY`, `const.CONF_MESSAGE`.
- Produces:
  - `reactions.automation(device_key, device_name, reaction_key, reaction, entity_id, script=None, notify: Sequence[str] = ()) -> dict[str, Any]`: `notify` is where its message goes (its own or the default), ignored without `message`.
  - `__init__._messages_sent(config: dict[str, Any]) -> dict[str, Any]`, a whole-block validator (Task 3 extends it to notifications).

- [ ] **Step 1: Write the failing tests**

Append to the configuration section of `tests/test_reactions.py` (after `test_an_empty_block_is_refused`):

```python
PHONE = "notify.phone"
TOLD = {**DOOR_OPENS, "message": "A porta abriu."}


@pytest.mark.parametrize(("reaction", "config"), [
    pytest.param(TOLD, {"notify": PHONE}, id="the default"),
    pytest.param({**TOLD, "notify": PHONE}, None, id="its own"),
    pytest.param({**TOLD, "notify": [PHONE, "notify.tablet"]}, {"notify": "notify.x"}, id="its own list"),
])
async def test_a_message_that_goes_somewhere_is_accepted(
        ha: HomeAssistant, reaction: dict[str, Any], config: dict[str, Any] | None) -> None:
    assert await setup(ha, devices(it=reaction), config=config)


@pytest.mark.parametrize(("reaction", "reason"), [
    pytest.param({**DOOR_OPENS, "message": " "}, "length of value must be at least 1", id="blank message"),
    pytest.param({**DOOR_OPENS, "notify": PHONE}, "a reaction's notify goes with message",
                 id="notify without message"),
    pytest.param({**TOLD, "notify": "phone"}, "a notify action is notify.<name>", id="not a notify action"),
    pytest.param(TOLD, "device lights: reactions: it: message needs notify, here or in config.notify",
                 id="nowhere to go"),
])
async def test_a_message_that_cant_go_is_refused(ha: HomeAssistant, caplog: pytest.LogCaptureFixture,
                                                 reaction: dict[str, Any], reason: str) -> None:
    assert not await setup(ha, devices(it=reaction))
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(reason in message for message in errors), errors


async def test_config_notify_is_a_notify_action(ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    assert not await setup(ha, devices(it=TOLD), config={"notify": "phone"})
    assert "a notify action is notify.<name>" in caplog.text
```

Append to the translation section (after `test_then_starts_its_program_unless_it_runs`):

```python
def test_a_message_is_told_after_its_program_starts(ha: HomeAssistant) -> None:
    reactions = module("reactions")
    reaction = reactions.REACTION({**TOLD, "then": "clean"})
    script = "script.pururu_lights_program_clean"
    actions = reactions.automation(LIGHTS, "Luzes", "door", reaction, DOOR, script,
                                   ["notify.a", "notify.b"])["actions"]
    assert actions[0]["then"] == [{"action": "script.turn_on", "target": {"entity_id": script}}]
    assert actions[1:] == [
        {"action": target, "data": {"title": "Luzes", "message": "A porta abriu."}, "continue_on_error": True}
        for target in ("notify.a", "notify.b")
    ]


def test_without_a_message_nobody_is_told(ha: HomeAssistant) -> None:
    reactions = module("reactions")
    reaction = reactions.REACTION(DOOR_OPENS)
    assert reactions.automation(LIGHTS, "Luzes", "door", reaction, DOOR, None, ["notify.a"])["actions"] == []
```

Append to the generation section (after `test_a_state_reaction_fires`):

```python
async def test_the_default_or_its_own_notify(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(door=TOLD, mine={**TOLD, "notify": "notify.tablet"}),
                       config={"notify": [PHONE]})
    told = {a["id"]: [action["action"] for action in a["actions"]] for a in generated(ha)}
    assert told == {"pururu_lights_reaction_door": [PHONE],
                    "pururu_lights_reaction_mine": ["notify.tablet"]}


async def test_a_message_is_text(ha: HomeAssistant, automations: None) -> None:
    """Through HA's own automation: the phone gets the message as written."""
    calls = async_mock_service(ha, "notify", "phone")
    await fake(ha, DOOR, "off")
    assert await setup(ha, devices(door={**TOLD, "message": "Porta {{ aberta }} {% raw %}"}),
                       config={"notify": PHONE})
    await fake(ha, DOOR, "on")
    await ha.async_block_till_done()
    assert [call.data for call in calls] == [{"title": "Luzes", "message": "Porta {{ aberta }} {% raw %}"}]
```

Append to the `then` section (after the tests that use the `both` fixture):

```python
async def test_a_missing_notify_action_does_not_keep_the_program_from_starting(
        ha: HomeAssistant, both: None) -> None:
    await fake(ha, DOOR, "off")
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, pool(clean={**DOOR_OPENS, "then": "clean", "message": "Limpando",
                                       "notify": "notify.nobody"}))
    await fake(ha, DOOR, "on")
    await ha.async_block_till_done()
    assert ha.states.get(CLEAN).state == "on"
```

Add `from pytest_homeassistant_custom_component.common import async_mock_service` to the imports.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_reactions.py -n 0 -q`
Expected: FAIL: `'message' is an invalid option`, and `automation()` takes no `notify`.

- [ ] **Step 3: Implement**

`custom_components/pururu/reactions.py`:

- Imports: `from collections.abc import Mapping, Sequence`; `from . import messages`; `from .const import CONF_AUTOMATIONS, CONF_MESSAGE, CONF_NOTIFY, ENTITY_PREFIX`.
- Module docstring, second paragraph: "It starts one of its device's programs (then), tells its message (message, notify), or does nothing: …".
- In `_consistent`, first thing after the sources check:

```python
    if CONF_NOTIFY in reaction and CONF_MESSAGE not in reaction:
        raise vol.Invalid("a reaction's notify goes with message")
```

- In `REACTION`'s schema, after `then`:

```python
            # Told when the reaction fires, to its own notify or config's
            vol.Optional(CONF_MESSAGE): TEXT,
            vol.Optional(CONF_NOTIFY): messages.TARGETS,
```

- `automation`:

```python
def automation(
    device_key: str,
    device_name: str,
    reaction_key: str,
    reaction: Mapping[str, Any],
    entity_id: str | None,
    script: str | None = None,
    notify: Sequence[str] = (),
) -> dict[str, Any]:
    """The automation of a reaction; `script` is the current entity ID of its program's.

    `notify` is where its message goes, its own or config's; the program starts
    first: a notify action that doesn't exist fails the run, whatever
    continue_on_error says.
    """
    told = (
        messages.actions(notify, device_name, reaction[CONF_MESSAGE])
        if CONF_MESSAGE in reaction
        else []
    )
    return {
        "id": automation_id(device_key, reaction_key),
        "alias": f"{device_name} {reaction[CONF_NAME]}",
        "description": f"pururu: {device_key}, {reaction_key}",
        "triggers": triggers(reaction, entity_id),
        "actions": [*actions(script), *told],
    }
```

`custom_components/pururu/__init__.py`:

- Imports: add `messages` to `from . import (...)`; add `CONF_MESSAGE, CONF_NOTIFY` to the `.const` import; `from collections.abc import Collection, Iterator, Mapping, Sequence`.
- In `CONFIG_SCHEMA`'s `config` schema, next to `CONF_ALERTS`:

```python
                            # Where every message goes, unless its own notify says
                            vol.Optional(CONF_NOTIFY): messages.TARGETS,
```

- Add `_messages_sent` after `_alert_lights_resolved` in the `vol.All(...)` list, and define it after `_reaction_resolved`:

```python
def _messages_sent(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse a message that goes nowhere: no notify of its own, none in config.notify."""
    if config[CONF_CONFIG].get(CONF_NOTIFY):
        return config
    for key, device in config[CONF_DEVICES].items():
        for reaction_key, reaction in device.get(CONF_REACTIONS, {}).items():
            if CONF_MESSAGE in reaction and CONF_NOTIFY not in reaction:
                raise vol.Invalid(
                    f"device {key}: reactions: {reaction_key}: message needs notify, "
                    "here or in config.notify"
                )
    return config
```

- `_automations` takes `notify: Sequence[str]` (last parameter, docstring: "`notify` is config's: where a message without its own goes") and passes `notify=reaction.get(CONF_NOTIFY, notify)` to `reactions.automation(...)`.
- In `async_setup_entry`, before the call to `_automations`:

```python
    # Where a message goes without a notify of its own
    notify = configured.get(CONF_CONFIG, {}).get(CONF_NOTIFY, [])
```

and pass it: `_automations(hass, devices, created, generated_scripts, held, notify)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_reactions.py tests/test_generated.py -n 0 -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/pururu/reactions.py custom_components/pururu/__init__.py tests/test_reactions.py
git commit -m "pururu: a reaction tells its message"   # plus the two trailer lines
```

---

### Task 3: ready-made notifications, validated: `Happening`, `Feature.notifications`, the device key

**Files:**
- Modify: `custom_components/pururu/feature.py` (add `Happening`, `Feature.notifications`)
- Create: `custom_components/pururu/features/appliance/notifications.py`
- Modify: `custom_components/pururu/features/appliance/__init__.py` (`notifications=HAPPENINGS`)
- Create: `custom_components/pururu/notifications.py` (schema part only in this task)
- Modify: `custom_components/pururu/__init__.py` (`_device`, `_notifications_on_this_device`, `_generated_ids_distinct`, `_messages_sent`)
- Modify: `custom_components/pururu/translations/en.json`, `pt-BR.json` (`common` texts)
- Test: `tests/test_notifications.py` (create), `tests/test_features.py`

**Interfaces:**
- Consumes: `messages.TARGETS`, `const.CONF_NOTIFICATIONS/CONF_MESSAGE/CONF_NOTIFY`.
- Produces:
  - `feature.Happening(watches: str, to: str, from_: str | None = None)` (frozen, kw_only).
  - `Feature.notifications: Mapping[str, Happening]` (default empty).
  - `features.appliance.notifications.HAPPENINGS: dict[str, Happening]` = `{"finished": ...}`.
  - `notifications.NAMESPACE = "notification"`.
  - `notifications.validate(value: Any) -> dict[str, dict[str, dict[str, Any]]]`: feature key → name → settings (`{}` for null).
  - `notifications.automation_id(device_key: str, namespace: str, name: str) -> str`.
  - Translation keys in `common`: `<namespace>_notification_<name>_name`, `<namespace>_notification_<name>_message`.

- [ ] **Step 1: Write the failing tests**

`tests/test_notifications.py`:

```python
"""Ready-made notifications: a made-up washer tells when its cycle finishes."""

from typing import Any

from homeassistant.core import HomeAssistant
import pytest

from helpers import setup

KEY = "washer"
POWER = "sensor.demo_plug_power"
PHONE = "notify.phone"
APPLIANCE: dict[str, Any] = {
    "power": POWER,
    "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}


def devices(notifications: Any, **device: Any) -> dict[str, Any]:
    return {KEY: {"name": "Máquina", "appliance": APPLIANCE, "notifications": notifications, **device}}


# --- configuration ------------------------------------------------------------------------


@pytest.mark.parametrize("notifications", [
    pytest.param({"appliance": {"finished": None}}, id="null is every default"),
    pytest.param({"appliance": {"finished": {}}}, id="empty is every default"),
    pytest.param({"appliance": {"finished": {"message": "Roupa pronta!", "notify": "notify.tablet"}}},
                 id="all set"),
])
async def test_valid_notifications_are_accepted(ha: HomeAssistant, notifications: Any) -> None:
    assert await setup(ha, devices(notifications), config={"notify": PHONE})


@pytest.mark.parametrize(("notifications", "reason"), [
    pytest.param({"nope": {"finished": None}}, "nope is not a feature", id="not a feature"),
    pytest.param({"switches": {"on": None}}, "switches offers no ready-made notification",
                 id="a feature offering none"),
    pytest.param({"appliance": {"nope": None}},
                 "appliance: nope is not a ready-made notification of appliance: finished", id="unknown name"),
    pytest.param({"appliance": {"finished": {"lasts": 1}}}, "'lasts' is an invalid option", id="unknown setting"),
    pytest.param({"appliance": {"finished": {"message": ""}}}, "length of value must be at least 1",
                 id="blank message"),
    pytest.param({"appliance": {}}, "length of value must be at least 1", id="no name"),
    pytest.param({}, "length of value must be at least 1", id="empty"),
])
async def test_invalid_notifications_are_refused(ha: HomeAssistant, caplog: pytest.LogCaptureFixture,
                                                 notifications: Any, reason: str) -> None:
    assert not await setup(ha, devices(notifications), config={"notify": PHONE})
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(reason in message for message in errors), errors


async def test_a_feature_the_device_lacks_is_refused(ha: HomeAssistant,
                                                     caplog: pytest.LogCaptureFixture) -> None:
    config = {KEY: {"name": "Máquina", "switches": {"x": {"entity": "switch.x", "name": "X"}},
                    "notifications": {"appliance": {"finished": None}}}}
    assert not await setup(ha, config, config={"notify": PHONE})
    assert "notifications: appliance: the device has no appliance" in caplog.text


async def test_a_notification_needs_somewhere_to_go(ha: HomeAssistant,
                                                    caplog: pytest.LogCaptureFixture) -> None:
    assert not await setup(ha, devices({"appliance": {"finished": None}}))
    assert ("device washer: notifications: appliance: finished needs notify, here or in config.notify"
            in caplog.text)


async def test_its_own_notify_is_enough(ha: HomeAssistant) -> None:
    assert await setup(ha, devices({"appliance": {"finished": {"notify": PHONE}}}))


async def test_notifications_alone_are_not_a_feature(ha: HomeAssistant,
                                                     caplog: pytest.LogCaptureFixture) -> None:
    config = {KEY: {"name": "Máquina", "notifications": {"appliance": {"finished": None}}}}
    assert not await setup(ha, config, config={"notify": PHONE})


async def test_a_notification_and_a_reaction_with_one_id_are_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """a's reaction appliance_notification_finished and a_reaction's notification: one automation ID."""
    door = {"name": "Porta", "entity": "binary_sensor.door", "to": "on"}
    config = {
        "a": {"name": "A", "appliance": APPLIANCE, "reactions": {"x_appliance_notification_finished": door}},
        "a_reaction_x": {"name": "B", "appliance": {**APPLIANCE, "power": "sensor.other"},
                         "notifications": {"appliance": {"finished": None}}},
    }
    assert not await setup(ha, config, config={"notify": PHONE})
    assert ("device a_reaction_x: automation.pururu_a_reaction_x_appliance_notification_finished "
            "is already a reaction of device a") in caplog.text
```

Append to `tests/test_features.py`:

```python
def test_ready_made_notifications_line_up(features: dict[str, Any]) -> None:
    """Every ready-made notification watches its own feature's entity key and has both texts."""
    feature_module = module("feature")
    en, pt = load("translations/en.json"), load("translations/pt-BR.json")
    offering = [name for name, feature in features.items() if feature.notifications]
    assert offering, "no feature offers ready-made notifications"
    for name in offering:
        feature = features[name]
        for notification, happening in feature.notifications.items():
            assert cv.slug(notification) == notification, name
            assert happening.watches in feature.entity_keys, f"{name}: {notification}"
            key = feature_module.qualified(feature.namespace, f"notification_{notification}")
            for translations in (en, pt):
                assert translations["common"][f"{key}_name"], key
                assert translations["common"][f"{key}_message"], key
        validate = module("notifications").validate
        assert validate({name: dict.fromkeys(feature.notifications)}) == {
            name: {notification: {} for notification in feature.notifications}}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_notifications.py tests/test_features.py -n 0 -q`
Expected: FAIL: `'notifications' is an invalid option`; `Feature` has no `notifications`.

- [ ] **Step 3: Implement**

`custom_components/pururu/feature.py`, after `preset_keys`:

```python
@dataclass(frozen=True, kw_only=True)
class Happening:
    """A ready-made notification of a feature: what happens, as a reaction's trigger.

    Off until the device's `notifications` enables it; it creates no entity.
    """

    # The entity key, in the feature's namespace, it watches
    watches: str
    # The state it goes to, and from: a reaction's to and from
    to: str
    from_: str | None = None
```

and in `Feature`, after `alerts`:

```python
    # Ready-made notifications it offers, by name: each enabled one, in the
    # device's `notifications`, is an automation (notifications.py)
    notifications: Mapping[str, Happening] = field(default_factory=dict)
```

`custom_components/pururu/features/appliance/notifications.py`:

```python
"""The appliance's ready-made notifications: its cycles."""

from homeassistant.const import STATE_OFF, STATE_ON

from ...feature import Happening

HAPPENINGS: dict[str, Happening] = {
    # A cycle ends exactly when running goes off; from on, so a plug
    # reconnecting (unavailable → off) or a reload tells nobody
    "finished": Happening(watches="running", from_=STATE_ON, to=STATE_OFF),
}
```

In `features/appliance/__init__.py`: `from .notifications import HAPPENINGS` and `notifications=HAPPENINGS,` after `alerts=PRESETS,`.

`custom_components/pururu/notifications.py` (the generation part comes in Task 4):

```python
"""Ready-made notifications: what a device's features offer to tell, as automations pururu generates.

A device's `notifications` enables them, by feature and name: each is a
Happening of the feature (Feature.notifications), told once through HA's notify
actions (messages.py). Each becomes an automation in
pururu/automations/notifications.yaml, next to the reactions' in the folder
configuration.yaml includes (generated.py).
"""

from typing import Any

import voluptuous as vol

from homeassistant.helpers import config_validation as cv

from . import messages
from .const import CONF_MESSAGE, CONF_NOTIFY, ENTITY_PREFIX
from .feature import TEXT, qualified
from .features import FEATURES

# The namespace of a notification's automation ID, inside its feature's
NAMESPACE = "notification"
# What one takes: its text, where it goes; a schema of its own, so unknown keys are refused
SETTINGS = vol.Schema(
    {vol.Optional(CONF_MESSAGE): TEXT, vol.Optional(CONF_NOTIFY): messages.TARGETS}
)
# feature key -> name -> settings (null: every default); schemas of their own:
# ALLOW_EXTRA would let a key that isn't a slug through
_BLOCK = vol.All(
    vol.Schema(
        {
            cv.slug: vol.All(
                vol.Schema({cv.slug: vol.Any(None, dict)}), vol.Length(min=1)
            )
        }
    ),
    vol.Length(min=1),
)


def validate(value: Any) -> dict[str, dict[str, dict[str, Any]]]:
    """The device's `notifications`: every feature one that offers them, every name one it offers."""
    enabled: dict[str, dict[str, dict[str, Any]]] = {}
    for key, names in _BLOCK(value).items():
        if (feature := FEATURES.get(key)) is None:
            raise vol.Invalid(f"{key} is not a feature", path=[key])
        if not feature.notifications:
            raise vol.Invalid(f"{key} offers no ready-made notification", path=[key])
        offered = ", ".join(feature.notifications)
        enabled[key] = {}
        for name, settings in names.items():
            if name not in feature.notifications:
                raise vol.Invalid(
                    f"{key}: {name} is not a ready-made notification of {key}: {offered}",
                    path=[key, name],
                )
            enabled[key][name] = SETTINGS(settings or {})
    return enabled


def automation_id(device_key: str, namespace: str, name: str) -> str:
    """The automation's ID, and the object ID of its entity ID: the pururu pattern."""
    return f"{ENTITY_PREFIX}_{device_key}_{qualified(namespace, qualified(NAMESPACE, name))}"
```

`custom_components/pururu/__init__.py`:

- Add `notifications` to `from . import (...)`, `CONF_NOTIFICATIONS` to the `.const` import.
- In `_device`'s schema: `vol.Optional(CONF_NOTIFICATIONS): notifications.validate,` after `CONF_PROGRAMS`; call `_notifications_on_this_device(device)` after `_programs_on_this_device(device)`, and add to the docstring "and a ready-made notification is of one of its features".

```python
def _notifications_on_this_device(device: dict[str, Any]) -> None:
    """Refuse a ready-made notification of a feature the device doesn't have."""
    for key in device.get(CONF_NOTIFICATIONS, {}):
        if key not in device:
            raise vol.Invalid(f"notifications: {key}: the device has no {key}")
```

- Replace `_generated_ids_distinct` with:

```python
def _generated_ids(key: str, device: dict[str, Any]) -> Iterator[tuple[str, str, str]]:
    """(domain, ID, what) of every automation and script the device generates."""
    for reaction_key in device.get(CONF_REACTIONS, {}):
        yield (
            reactions.KIND.domain,
            reactions.automation_id(key, reaction_key),
            "reaction",
        )
    for name, enabled in device.get(CONF_NOTIFICATIONS, {}).items():
        namespace = FEATURES[name].namespace
        for notification in enabled:
            yield (
                notifications.KIND.domain,
                notifications.automation_id(key, namespace, notification),
                "notification",
            )
    for program in device.get(CONF_PROGRAMS, {}):
        yield programs.KIND.domain, programs.script_id(key, program), "program"


def _generated_ids_distinct(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse two automations, or two scripts, that would share an ID.

    Device `lights` with the reaction `b_reaction_c` and device `lights_reaction_b`
    with the reaction `c` would both have pururu_lights_reaction_b_reaction_c; a
    reaction's and a notification's may meet the same way.
    """
    owners: dict[tuple[str, str], tuple[str, str]] = {}  # (domain, ID) -> (device, what)
    for key, device in config[CONF_DEVICES].items():
        for domain, unique_id, what in _generated_ids(key, device):
            if (owner := owners.get((domain, unique_id))) is not None:
                raise vol.Invalid(
                    f"device {key}: {domain}.{unique_id} is already a {owner[1]} "
                    f"of device {owner[0]}"
                )
            owners[domain, unique_id] = (key, what)
    return config
```

`notifications.KIND` doesn't exist until Task 4; in this task add it now to `notifications.py`, after `NAMESPACE` (Task 4 uses it):

```python
KIND = Kind(
    domain="automation",
    folder="pururu/automations",
    file="pururu/automations/notifications.yaml",
    merge="list",
    issue="notifications_not_included",
    data_key=CONF_NOTIFICATIONS,
    one="an automation",
    plural="automations",
    source="notifications",
)
```

with `from .generated import Kind` and `CONF_NOTIFICATIONS` in the `.const` import.

- Extend `_messages_sent`, inside the device loop after the reactions:

```python
        for name, enabled in device.get(CONF_NOTIFICATIONS, {}).items():
            for notification, settings in enabled.items():
                if CONF_NOTIFY not in settings:
                    raise vol.Invalid(
                        f"device {key}: notifications: {name}: {notification} needs "
                        "notify, here or in config.notify"
                    )
```

and its docstring: "Refuse a message that goes nowhere, a reaction's or a notification's: …".

Translations, `common` block, after the `appliance_alert_*` texts:
- `en.json`: `"appliance_notification_finished_name": "Finished",` `"appliance_notification_finished_message": "The cycle finished."`
- `pt-BR.json`: `"appliance_notification_finished_name": "Terminou",` `"appliance_notification_finished_message": "O ciclo terminou."`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_notifications.py tests/test_features.py tests/test_reactions.py tests/test_programs.py -n 0 -q`
Expected: PASS (reactions and programs keep their ID-collision tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/pururu tests/test_notifications.py tests/test_features.py
git commit -m "pururu: ready-made notifications, validated"   # plus the two trailer lines
```

---

### Task 4: generate the ready-made notifications' automations

**Files:**
- Modify: `custom_components/pururu/notifications.py` (`automation`, `items`)
- Modify: `custom_components/pururu/__init__.py` (`async_setup_entry`, `async_remove_entry`, docstrings)
- Modify: `custom_components/pururu/translations/en.json`, `pt-BR.json` (`issues.notifications_not_included`)
- Modify: `tests/helpers.py` (`NOTIFICATIONS`, `generated_notifications`, `reload` loads both files)
- Modify: `tests/test_places.py:242,265` (`entry.data` gains `"notifications": []`)
- Test: `tests/test_notifications.py`

**Interfaces:**
- Consumes: `notifications.KIND`, `notifications.automation_id`, `feature.Happening`, `reactions.triggers(reaction: Mapping[str, Any], entity_id: str | None)`, `messages.actions`, `presets.Texts`, `generated.Item`, `generated.async_sync(hass, entry, kind, items, held=())`, `generated.async_remove(hass, entry, kind)`.
- Produces:
  - `notifications.automation(device: Device, name: str, happening: Happening, entity_id: str, *, alias: str, message: str, notify: Sequence[str]) -> dict[str, Any]`.
  - `notifications.items(hass, devices: Mapping[str, Mapping[str, Any]], created: Collection[str], texts: Mapping[str, str], notify: Sequence[str]) -> list[generated.Item]`.
  - `helpers.generated_notifications(hass) -> list[dict[str, Any]]`.

- [ ] **Step 1: Write the failing tests**

In `tests/helpers.py`, after `AUTOMATIONS`:

```python
# The ready-made notifications' automations, in the same folder
NOTIFICATIONS = "pururu/automations/notifications.yaml"
```

after `generated`:

```python
def generated_notifications(hass: HomeAssistant) -> list[dict[str, Any]]:
    """The ready-made notifications' automations pururu wrote."""
    path = Path(hass.config.path(NOTIFICATIONS))
    if not path.is_file():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []
```

and in `reload`, the patched configuration's automations are both files, as the folder include merges them:

```python
                                                      "automation pururu": [*generated(hass),
                                                                            *generated_notifications(hass)],
```

(the comment above becomes "configuration.yaml includes the generated files' folders: automations and scripts reload from them").

In `tests/test_places.py`, both exact `entry.data` assertions gain `"notifications": []` after `"automations": []`.

Append to `tests/test_notifications.py` (add imports: `from collections.abc import AsyncIterator`, `from unittest.mock import patch`, `from homeassistant.helpers import issue_registry as ir`, `from homeassistant.setup import async_setup_component`, `from pytest_homeassistant_custom_component.common import async_mock_service`, and from helpers `fake, generated, generated_notifications, reload, tick`):

```python
RUNNING = "binary_sensor.pururu_washer_appliance_running"
FINISHED = "automation.pururu_washer_appliance_notification_finished"
ENABLED = {"appliance": {"finished": None}}


# --- the automation -----------------------------------------------------------------------


async def test_the_file_holds_the_notifications_automation(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    assert generated_notifications(ha) == [{
        "id": "pururu_washer_appliance_notification_finished",
        "alias": "Máquina Finished",
        "description": "pururu: washer, appliance notification finished",
        "triggers": [{"trigger": "state", "entity_id": RUNNING, "from": "on", "to": "off"}],
        "actions": [{"action": PHONE, "data": {"title": "Máquina", "message": "The cycle finished."},
                     "continue_on_error": True}],
    }]
    assert generated(ha) == []


async def test_in_hass_language(ha: HomeAssistant) -> None:
    ha.config.language = "pt-BR"
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    [automation] = generated_notifications(ha)
    assert automation["alias"] == "Máquina Terminou"
    assert automation["actions"][0]["data"]["message"] == "O ciclo terminou."


async def test_its_own_message_and_notify(ha: HomeAssistant) -> None:
    mine = {"appliance": {"finished": {"message": "Roupa {pronta}!", "notify": ["notify.a", "notify.b"]}}}
    assert await setup(ha, devices(mine), config={"notify": PHONE})
    [automation] = generated_notifications(ha)
    assert [action["action"] for action in automation["actions"]] == ["notify.a", "notify.b"]
    assert automation["actions"][0]["data"]["message"] == "{% raw %}Roupa {pronta}!{% endraw %}"


async def test_it_follows_a_renamed_running(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    er.async_get(ha).async_update_entity(RUNNING, new_entity_id="binary_sensor.washer_running")
    await ha.async_block_till_done()
    assert generated_notifications(ha)[0]["triggers"][0]["entity_id"] == "binary_sensor.washer_running"


async def test_not_generated_when_running_is_not_created(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    ha.states.async_set(RUNNING, "off")  # another integration's entity holds the ID
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    assert generated_notifications(ha) == []
    assert (f"{FINISHED} follows {RUNNING}, which is not created; not generating it") in caplog.text


async def test_dropped_from_the_yaml_it_goes(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    await reload(ha, {KEY: {"name": "Máquina", "appliance": APPLIANCE}}, config={"notify": PHONE})
    assert generated_notifications(ha) == []


# --- told -----------------------------------------------------------------------------------


@pytest.fixture
async def automations(ha: HomeAssistant) -> AsyncIterator[None]:
    """HA's automations, from a configuration.yaml whose include merges both of pururu's files."""
    def both(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"automation pururu": [*generated(ha), *generated_notifications(ha)]}
    with patch("homeassistant.config.load_yaml_config_file", side_effect=both):
        assert await async_setup_component(ha, "automation", both())
        yield


async def cycle(ha: HomeAssistant, freezer: Any) -> None:
    """A washing cycle: running on after on_delay, off after off_delay."""
    await fake(ha, POWER, "100")
    await tick(ha, freezer, 60)
    assert ha.states.get(RUNNING).state == "on"
    await fake(ha, POWER, "0")
    await tick(ha, freezer, 120)
    assert ha.states.get(RUNNING).state == "off"
    await ha.async_block_till_done()


async def test_the_phone_is_told_when_a_cycle_finishes(ha: HomeAssistant, freezer: Any,
                                                       automations: None) -> None:
    calls = async_mock_service(ha, "notify", "phone")
    await fake(ha, POWER, "0")
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    await cycle(ha, freezer)
    assert [call.data for call in calls] == [{"title": "Máquina", "message": "The cycle finished."}]


async def test_a_plug_reconnecting_tells_nobody(ha: HomeAssistant, freezer: Any,
                                               automations: None) -> None:
    calls = async_mock_service(ha, "notify", "phone")
    await fake(ha, POWER, "0")
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    await fake(ha, POWER, "unavailable")
    await fake(ha, POWER, "0")
    await tick(ha, freezer, 180)
    assert calls == []


async def test_a_reload_tells_nobody(ha: HomeAssistant, freezer: Any, automations: None) -> None:
    calls = async_mock_service(ha, "notify", "phone")
    await fake(ha, POWER, "100")
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    await tick(ha, freezer, 60)
    await reload(ha, devices(ENABLED), config={"notify": PHONE})
    await tick(ha, freezer, 60)
    assert calls == []


async def test_the_automation_has_the_pururu_entity_id(ha: HomeAssistant, automations: None) -> None:
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    state = ha.states.get(FINISHED)
    assert state is not None
    assert state.attributes["friendly_name"] == "Máquina Finished"


async def test_a_repair_while_the_file_is_not_loaded(ha: HomeAssistant, freezer: Any) -> None:
    """A configuration.yaml without the include: the notification isn't loaded."""
    with patch("homeassistant.config.load_yaml_config_file", side_effect=lambda *_a, **_k: {}):
        assert await async_setup_component(ha, "automation", {})
        assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    await tick(ha, freezer, 5)
    issue = ir.async_get(ha).async_get_issue("pururu", "notifications_not_included")
    assert issue is not None
    assert issue.translation_placeholders == {
        "include": "automation pururu: !include_dir_merge_list pururu/automations",
        "file": "pururu/automations/notifications.yaml",
    }


async def test_removing_the_entry_empties_the_file(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(ENABLED), config={"notify": PHONE})
    entry = ha.config_entries.async_entries("pururu")[0]
    await ha.config_entries.async_remove(entry.entry_id)
    await ha.async_block_till_done()
    assert generated_notifications(ha) == []
```

(`er` is `from homeassistant.helpers import entity_registry as er`.)

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_notifications.py tests/test_places.py -n 0 -q`
Expected: FAIL: no `notifications.yaml`; `entry.data` has no `notifications`.

- [ ] **Step 3: Implement**

`custom_components/pururu/notifications.py`, add imports `import logging`, `from collections.abc import Collection, Mapping, Sequence`, `from homeassistant.const import CONF_NAME`, `from homeassistant.core import HomeAssistant`, `from . import generated, messages, reactions` (instead of `from . import messages`), `from .feature import TEXT, Device, Happening, qualified`, `_LOGGER = logging.getLogger(__name__)`, then:

```python
def automation(
    device: Device,
    name: str,
    happening: Happening,
    entity_id: str,
    *,
    alias: str,
    message: str,
    notify: Sequence[str],
) -> dict[str, Any]:
    """The automation of notification `name` of the feature `device` is in; `entity_id` is what it watches."""
    trigger: dict[str, Any] = {"to": happening.to}
    if happening.from_ is not None:
        trigger["from"] = happening.from_
    return {
        "id": automation_id(device.key, device.namespace, name),
        "alias": f"{device.name} {alias}",
        "description": f"pururu: {device.key}, {device.namespace} {NAMESPACE} {name}",
        "triggers": reactions.triggers(trigger, entity_id),
        "actions": messages.actions(notify, device.name, message),
    }


def items(
    hass: HomeAssistant,
    devices: Mapping[str, Mapping[str, Any]],
    created: Collection[str],
    texts: Mapping[str, str],
    notify: Sequence[str],
) -> list[generated.Item]:
    """An automation per enabled notification of every device; one on an entity not created is logged.

    `texts` are the common texts in HA's language (its name, its default
    message); `notify` is config's, where one without its own goes.
    """
    found: list[generated.Item] = []
    for key, config in devices.items():
        for name, enabled in config.get(CONF_NOTIFICATIONS, {}).items():
            feature = FEATURES[name]
            device = Device(key=key, name=config[CONF_NAME], namespace=feature.namespace)
            for notification, settings in enabled.items():
                happening = feature.notifications[notification]
                platform = feature.entity_keys[happening.watches]
                unique_id = automation_id(key, feature.namespace, notification)
                if device.object_id(happening.watches) not in created:
                    _LOGGER.error(
                        "automation.%s follows %s, which is not created; not generating it",
                        unique_id,
                        device.entity_id(platform, happening.watches),
                    )
                    continue
                text = device.qualified(qualified(NAMESPACE, notification))
                found.append(
                    generated.Item(
                        unique_id=unique_id,
                        config=automation(
                            device,
                            notification,
                            happening,
                            device.current_entity_id(hass, platform, happening.watches),
                            alias=texts[f"{text}_name"],
                            message=settings.get(CONF_MESSAGE, texts[f"{text}_message"]),
                            notify=settings.get(CONF_NOTIFY, notify),
                        ),
                    )
                )
    return found
```

Replace `from .generated import Kind` with the `generated` module import and write `KIND = generated.Kind(...)`.

`custom_components/pururu/__init__.py`, in `async_setup_entry`, right after the reactions' `generated.async_sync(...)`:

```python
    await generated.async_sync(
        hass,
        entry,
        notifications.KIND,
        notifications.items(hass, devices, created, texts, notify),
    )
```

Update its docstring: "The reactions' and the ready-made notifications' automations, the programs' scripts and Alert2's alerts come after the entities: …". In `async_remove_entry`, after the reactions' `async_remove`: `await generated.async_remove(hass, entry, notifications.KIND)`, and its docstring names "its reactions' and notifications' automations".

Translations, `issues`, after `automations_not_included`:
- `en.json`:
  ```json
    "notifications_not_included": {
      "title": "The notifications' automations aren't loaded",
      "description": "pururu writes an automation for each ready-made notification to `{file}`, but Home Assistant hasn't loaded them. Add this line to `configuration.yaml`:\n\n`{include}`\n\nThen reload automations in **Developer tools → YAML → Automations**, or restart Home Assistant."
    },
  ```
- `pt-BR.json`:
  ```json
    "notifications_not_included": {
      "title": "As automações das notificações não estão carregadas",
      "description": "O pururu escreve uma automação para cada notificação pronta em `{file}`, mas o Home Assistant não as carregou. Adicione esta linha ao `configuration.yaml`:\n\n`{include}`\n\nDepois recarregue as automações em **Ferramentas de desenvolvedor → YAML → Automações**, ou reinicie o Home Assistant."
    },
  ```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_notifications.py tests/test_places.py tests/test_reactions.py tests/test_generated.py -n 0 -q`
Expected: PASS. The repair test follows `tests/test_generated.py::test_the_warning_is_logged_once_while_the_issue_is_open`: a patched configuration without the include, then quiet time for the check.

- [ ] **Step 5: Commit**

```bash
git add custom_components/pururu tests/helpers.py tests/test_places.py tests/test_notifications.py
git commit -m "pururu: ready-made notifications as automations"   # plus the two trailer lines
```

---

### Task 5: `finished` leaves the alerts, and `lasts` with it

**Files:**
- Modify: `custom_components/pururu/features/appliance/alerts.py` (drop `finished`)
- Modify: `custom_components/pururu/feature.py` (`Preset` without `lasts`; `Elapsed` docstring)
- Modify: `custom_components/pururu/features/presets.py` (`_settings`, `validate`, `build`)
- Modify: `custom_components/pururu/features/elapsed.py` (no `lasts`, `_end`, `_keep`)
- Modify: `custom_components/pururu/__init__.py` (`partial(presets.validate, feature, key=name)`)
- Modify: `custom_components/pururu/translations/en.json`, `pt-BR.json`, `icons.json` (drop `appliance_alert_finished*`)
- Test: `tests/test_presets.py`, `tests/test_features.py:175`

**Interfaces:**
- Consumes: `Feature.notifications` (Task 3).
- Produces: `presets.validate(feature: Feature, value: Any, key: str = "") -> Any`: `key` is the feature's key in the device, for the moved-name message; `ElapsedAlert(...)` without `lasts`.

- [ ] **Step 1: Write the failing test, and drop the `finished` tests**

In `tests/test_presets.py`:
- `test_valid_alerts_are_accepted`: replace the two `finished` params with `pytest.param({"no_power": None}, id="no_power")`.
- `test_invalid_alerts_are_refused`: the unknown-alert reason becomes `"nope is not a ready-made alert: offline, no_power, long_cycle, no_cycle"`; delete the `for on finished` param (the test below covers `finished`).

- Delete `test_finished_turns_on_at_the_end_and_off_after_lasts`, `test_finished_turns_off_when_a_new_cycle_starts`, `test_finished_still_turns_off_at_lasts_without_a_reading` and `test_a_plug_reconnecting_is_no_finished_cycle` (the last one's case is covered by `test_a_plug_reconnecting_tells_nobody`).
- `test_time_alerts_watch_running_and_are_alert2_alerts` uses `no_cycle` instead:

```python
async def test_time_alerts_watch_running_and_are_alert2_alerts(ha: HomeAssistant) -> None:
    assert await setup(ha, devices({"no_cycle": {"for": {"days": 2}}}))
    found = ha.states.get(alert("no_cycle"))
    assert found.attributes["watches"] == RUNNING
    assert found.attributes["priority"] == "medium"
    assert found.attributes["message"] == "It hasn't run in a while."
    path = Path(ha.config.path("pururu/alert2/alerts.yaml"))
    [entry] = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert entry["name"] == "demo_washer_appliance_alert_no_cycle"
```

- Add, after `test_invalid_alerts_are_refused`:

```python
async def test_finished_as_an_alert_says_where_it_went(ha: HomeAssistant,
                                                      caplog: pytest.LogCaptureFixture) -> None:
    """Upgrading from 0.1.21 with appliance: alerts: finished: the error says what to write."""
    assert not await setup(ha, devices({"offline": None, "finished": {"lasts": {"minutes": 30}}}))
    assert "finished is now a notification: notifications: appliance: finished" in caplog.text
```

In `tests/test_features.py:175`: `settings[alert] = {} if preset.hold is not None else {"for": {"hours": 1}}`.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_presets.py -n 0 -q`
Expected: FAIL: the unknown-alert list still names `finished`; `finished` is still accepted.

- [ ] **Step 3: Implement**

`features/appliance/alerts.py`: delete the `"finished": Preset(...)` entry.

`feature.py`:
- `Preset`: delete `lasts` and its comment; the `hold` comment becomes `# The default `for`; None: the user gives it`.
- `Elapsed` docstring first line: `"""On while the watched entity is `state` and the time since a milestone is longer than `for`.`

`features/presets.py`:

```python
def _settings(preset: Preset) -> vol.Schema:
    """What one alert takes: for, priority, notify, lights."""
    timing: dict[Any, Any] = (
        {vol.Required("for"): cv.positive_time_period}
        if preset.hold is None
        else {vol.Optional("for", default=preset.hold): cv.positive_time_period}
    )
    return vol.Schema(
        {
            **timing,
            vol.Optional("priority", default=preset.priority): vol.In(PRIORITIES),
            vol.Optional("notify"): NOTIFY,
            vol.Optional("lights"): lights_group,
        }
    )
```

```python
def validate(feature: Feature, value: Any, key: str = "") -> Any:
    """A feature's block: its schema, and `alerts` when it offers ready-made alerts.

    `key` is the feature's in the device: a ready-made alert that became a
    notification says where it went.
    """
    if not feature.alerts or not isinstance(value, dict) or ALERTS_KEY not in value:
        return feature.schema(value)
    if isinstance(given := value[ALERTS_KEY], dict):
        for name in given:
            if name in feature.notifications and name not in feature.alerts:
                raise vol.Invalid(
                    f"{name} is now a notification: notifications: "
                    f"{key or feature.namespace}: {name}",
                    path=[ALERTS_KEY, name],
                )
    block = {each: setting for each, setting in value.items() if each != ALERTS_KEY}
    enabled = vol.Schema({ALERTS_KEY: settings_schema(feature.alerts)})(
        {ALERTS_KEY: value[ALERTS_KEY]}
    )
    return {**feature.schema(block), **enabled}
```

In `build`, the `ElapsedAlert(...)` call: `hold=settings.get("for", preset.hold or timedelta(0)),` stays; delete `lasts=settings.get("lasts"),`.

`features/elapsed.py`:
- Module docstring unchanged; class docstring: `"""On while the watched entity is in its state and the time since the milestone is longer than `for`."""`
- `__init__`: delete the `lasts` parameter, `self._lasts`, and `self._end` with its comment.
- Replace `_evaluate` and delete `_keep`:

```python
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
        start = since + self._hold
        now = dt_util.utcnow()
        self._set(on=start <= now)
        if now < start:
            self._schedule(start)
```

- Remove `timedelta` from its imports if ruff reports it unused.

`__init__.py`, `_device`'s schema: `vol.Optional(name): partial(presets.validate, feature, key=name)`.

Translations: delete `appliance_alert_finished_message`, `appliance_alert_finished_done_message` (`common`) and `"appliance_alert_finished": {"name": ...}` (`entity.binary_sensor`) in both files (mind the trailing commas: `appliance_alert_no_cycle_done_message` becomes the last before the notification texts added in Task 3); delete `appliance_alert_finished` from `icons.json`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_presets.py tests/test_features.py tests/test_alerts.py tests/test_alert2.py tests/test_alert_lights.py -n 0 -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/pururu tests/test_presets.py tests/test_features.py
git commit -m "pururu: finished is a notification, not an alert"   # plus the two trailer lines
```

---

### Task 6: docs, CLAUDE.md, version 0.1.22

**Files:**
- Create: `docs/concepts/notifications.mdx`
- Modify: `docs.json` (sidebar, Concepts group, after Reactions)
- Modify: `docs/concepts/reactions.mdx`, `docs/features/appliance.mdx`, `docs/features/alerts.mdx`, `docs/reference/configuration.mdx`, `docs/reference/troubleshooting.mdx`, `docs/getting-started/first-device.mdx`, `docs/develop/writing-a-feature.mdx`, `docs/develop/architecture.mdx`, `CLAUDE.md`
- Modify: `custom_components/pururu/manifest.json` (`"version": "0.1.22"`)
- Test: `tests/test_notifications.py` (docs test)

**Interfaces:**
- Consumes: everything above; the page must say what the code does.

- [ ] **Step 1: Write the failing docs test**

Append to `tests/test_notifications.py` (imports `import re`, `from pathlib import Path`, `module` from helpers):

```python
# --- the docs ----------------------------------------------------------------------------

PAGE = Path(__file__).resolve().parents[1] / "docs/concepts/notifications.mdx"


def test_the_page_lists_every_ready_made_notification(ha: HomeAssistant) -> None:
    page = PAGE.read_text(encoding="utf-8")
    section = re.search(r"## Ready-made notifications\n(.*?)\n## ", page, re.DOTALL)
    assert section is not None, "no Ready-made notifications section"
    for name, feature in module("features").FEATURES.items():
        for notification in feature.notifications:
            assert f"`{name}: {notification}`" in section[1], notification
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_notifications.py::test_the_page_lists_every_ready_made_notification -n 0 -q`
Expected: FAIL, `FileNotFoundError`.

- [ ] **Step 3: Write the docs**

`docs/concepts/notifications.mdx`:

````mdx
---
title: Notifications
description: Simple news, told once to your phone. How it differs from an alert, and how a device tells it.
---

An **alert** is something you find critical: a problem that lasts, such as a door open that shouldn't be or a plug gone offline. It's a binary sensor, on while the problem lasts, and [Alert2](/features/alerts#getting-notified) tells you about it with reminders until it's resolved.

A **notification** is simple news, told **once**: the washer finished. It has no state, nothing to resolve, no reminder. pururu tells it through Home Assistant's `notify` actions, from an automation it generates.

```yaml title="configuration.yaml"
pururu:
  config:
    notify: notify.mobile_app_phone          # where every message goes
  devices:
    laundry_washer:
      name: Máquina de lavar
      appliance:
        power: sensor.washer_plug_power
        running: {threshold: 4, on_delay: {minutes: 1}, off_delay: {minutes: 2}}
      notifications:
        appliance:
          finished:                           # "The cycle finished."
      reactions:
        door_open:
          name: Porta aberta
          entity: binary_sensor.porta_lavanderia
          to: "on"
          message: A porta da lavanderia abriu.

automation pururu: !include_dir_merge_list pururu/automations
```

Your phone gets **Máquina de lavar** / **The cycle finished.** when a wash ends, and **Máquina de lavar** / **A porta da lavanderia abriu.** when the door opens.

## Where a message goes

<Property name="config.notify" type="notify action or list" optional>
  Where every message goes: a `notify` action such as `notify.mobile_app_phone`, or a list of them. A reaction's or a notification's own `notify` replaces it.
</Property>

A message with no `notify` of its own and no `config.notify` is a configuration error: `device laundry_washer: reactions: door_open: message needs notify, here or in config.notify`.

- The title is always the device's name.
- The message is shown **as you wrote it**: a `{` isn't a template.
- Whether the action exists is Home Assistant's to say when it runs: the automation's trace and the log show a `notify` action that doesn't exist.

## A reaction's message

Any [reaction](/concepts/reactions) can tell something when it fires:

<Property name="message" type="string" optional>
  What to tell. It can't be empty.
</Property>

---

<Property name="notify" type="notify action or list" optional>
  Where this message goes, instead of `config.notify`. Only with `message`.
</Property>

With `then`, the program starts first, then the message is told. One phone that can't be told doesn't keep the next one from being told.

## Ready-made notifications

A feature may offer notifications for what happens to it. Enable one with one key under the device's `notifications`, as `<feature>: <notification>`:

| Notification | Told when | Name | Default message |
|---|---|---|---|
| `appliance: finished` | a cycle ends (`appliance_running` goes from `on` to `off`) | Finished / Terminou | The cycle finished. / O ciclo terminou. |

Each one takes `message`, which replaces its text, and `notify`, which replaces `config.notify`. `finished:` alone, with nothing after it, is every default.

```yaml
notifications:
  appliance:
    finished: {message: Roupa pronta!, notify: notify.mobile_app_tablet}
```

- Each one is `automation.pururu_<key>_<feature namespace>_notification_<notification>`, shown as the device's name and its own: `automation.pururu_laundry_washer_appliance_notification_finished`, **Máquina de lavar Finished** (in your Home Assistant's language).
- A plug reconnecting or a reload tells nobody: `finished` needs `running` to go from `on` straight to `off`.
- If the entity it watches isn't created, it isn't generated either, and the log says why.
- `notifications` isn't a feature: a device still needs one.

## The file and the include

pururu writes the ready-made notifications' automations to `pururu/automations/notifications.yaml`, next to the reactions' `reactions.yaml`. The same line of `configuration.yaml` includes both:

```yaml title="configuration.yaml"
automation pururu: !include_dir_merge_list pururu/automations
```

Until it's there, **Settings → Repairs** shows **The notifications' automations aren't loaded**. See [Reactions: the include](/concepts/reactions#the-include).

## Coming from the `finished` alert

pururu 0.1.21 and earlier had a ready-made alert `finished`. It's a notification now: replace `appliance: alerts: finished` with `notifications: appliance: finished`. Left in `alerts`, it's refused with `finished is now a notification: notifications: appliance: finished`. Its binary sensor and its Alert2 alert go away.
````

`docs.json`: in the Concepts group, after `{ "title": "Reactions", "href": "/concepts/reactions" },` add `{ "title": "Notifications", "href": "/concepts/notifications" },`.

`docs/concepts/reactions.mdx`:
- Intro paragraph: after "it can start one of the device's [programs](/concepts/programs)" add ", and tell a [message](/concepts/notifications#a-reactions-message)".
- In `### What it does` (line 125), add the two `Property` blocks of `message` and `notify` exactly as in the notifications page, then: "With `then`, the program starts first. See [Notifications](/concepts/notifications)."

`docs/features/appliance.mdx`, section `## Ready-made alerts` (line 142):
- Example block: delete `finished: {lasts: {minutes: 30}}`.
- Table: delete the `finished` row; the table's intro list: `Each one takes `for`, `priority`, ...` (drop "(`finished`: `lasts` instead)"); delete "Enabled right after a cycle, `finished` turns on at once for what's left of `lasts`."; "`long_cycle` counts from the cycle's start, and `no_cycle` from the last cycle's end"; delete the `finished` row of the default texts table.
- Add before `## Provides`:

```mdx
## Ready-made notifications

`notifications: appliance: finished` tells you when a cycle ends. See [Notifications](/concepts/notifications#ready-made-notifications).
```

`docs/features/alerts.mdx`, after the first paragraph: "An alert is for what you find **critical**. For simple news, such as the washer finishing, use a [notification](/concepts/notifications)."

`docs/reference/configuration.mdx`:
- In the big example: delete `finished: {lasts: {minutes: 30}}` (line 41); under `config:` add `notify: notify.mobile_app_phone`; under `laundry_washer`, after `appliance:`'s block, add `notifications: {appliance: {finished: }}` written as
  ```yaml
        notifications:
          appliance:
            finished:
  ```
- `## config`: add a `Property` `notify` (`notify action or list`, optional): "Where every message goes, a reaction's or a notification's, unless its own `notify` says. See [Notifications](/concepts/notifications#where-a-message-goes)."
- `## devices`, after the `reactions` property: a `Property` `notifications` (`map`, optional): "The ready-made notifications of the device's features to tell, as `<feature>: {<notification>: settings}`. It isn't a feature. See [Notifications](/concepts/notifications#ready-made-notifications)." In the `reactions` property add: "A reaction's `message` is told to `notify` or `config.notify`."

`docs/reference/troubleshooting.mdx`:
- Line 25: `nope is not a ready-made alert: offline, no_power, long_cycle, no_cycle`, `long_cycle` or `no_cycle` without `for`, or `lasts` (`'lasts' is an invalid option`). Add a bullet: "`finished is now a notification: notifications: appliance: finished`: see [Coming from the finished alert](/concepts/notifications#coming-from-the-finished-alert)." and one: "`message needs notify, here or in config.notify`: add `config.notify`, or a `notify` to that reaction or notification."
- Next to the "reactions' automations aren't loaded" repair, add `### The notifications' automations aren't loaded` with: "The same include line loads both files: add `automation pururu: !include_dir_merge_list pururu/automations` to `configuration.yaml` and reload automations."

`docs/getting-started/first-device.mdx`, `## Step 5`: before the existing automation, add:

````mdx
The shortest way is a [ready-made notification](/concepts/notifications): your phone is told **The cycle finished.**

```yaml title="configuration.yaml"
pururu:
  config:
    notify: notify.mobile_app_phone
  devices:
    laundry_washer:
      # ... as above
      notifications:
        appliance:
          finished:
```

For a message with the cycle's numbers, write the automation yourself.
````

and change the sentence before the existing automation to start "`sensor.pururu_laundry_washer_appliance_last_cycle_end` changes once per finished cycle…" unchanged.

`docs/develop/writing-a-feature.mdx`:
- Line 192: `- `priority` and `hold` (the default `for`, or `None` when the user must give it).`
- After the ready-made alerts paragraph (line 194), add:

```mdx
**Ready-made notifications.** A feature can offer notifications for what happens to it, off until the device's `notifications` enables them. Set `notifications` to a mapping of name → `Happening` (`feature.py`): the entity key it watches and the state it goes `to` (and `from_`), as `features/appliance/notifications.py` does. It creates no entity: `notifications.py` validates the device's block and generates an automation per enabled one. Add its name and default message under `<namespace>_notification_<name>_name` and `_message` in the translations' `common` block, and a row to the table of [Notifications](/concepts/notifications#ready-made-notifications).
```

- In the contract table (line 215), add: `| `test_ready_made_notifications_line_up` | Every ready-made notification watches its own feature's entity key, has its name and message in both languages, and validates |`.

`docs/develop/architecture.mdx`: in the mermaid chart, the step 6 node reads "6. generated.async_sync<br/>scripts, then automations (reactions, notifications)"; in step 6's paragraph add: "The ready-made notifications' automations are a second automation `Kind` (`notifications.py`, `pururu/automations/notifications.yaml`, `entry.data["notifications"]`, the issue `notifications_not_included`), generated after the reactions'. A reaction's message and a notification are told through `messages.py` (the notify actions, the text escape the Alert2 file shares)."

`CLAUDE.md`, Architecture:
- Step 6: after "`pururu/automations/reactions.yaml` and `pururu/scripts/programs.yaml`," insert "then the ready-made notifications' automations (`notifications.py`, a second automation `Kind`: `pururu/automations/notifications.yaml`, same include, `entry.data["notifications"]`),"; and after "a reaction's `then` starts its device's program …" add "a reaction's `message` is told after it, to its `notify` or `config: notify` (`messages.py`: notify actions, text escaped, title the device's name)".
- Features: after the ready-made alerts bullet, add "- A feature can offer ready-made notifications (`Feature.notifications`: name → `Happening`, the entity key it watches and its `to`/`from_`), enabled by the device key `notifications: <feature>: {<name>: settings}`: no entity, an automation each (`notifications.py`), default texts in the translations' `common`. An alert is what's critical and lasts; a notification is news told once."
- Entity IDs: "a notification's automation is `automation.pururu_<device>_<namespace>_notification_<name>`".

`custom_components/pururu/manifest.json`: `"version": "0.1.22"`.

- [ ] **Step 4: Run the checks**

Run: `uv run pytest -q` (everything: tests, ruff, ruff format, mypy, hassfest, quality scale)
Expected: PASS.

Run: `python3 release.py check`
Expected: passes (0.1.22 above the latest release 0.1.21). Before opening the PR, check `gh pr list --state open` and `git log origin/main -1` for another PR bumping to 0.1.22.

Run: `pnpm install && pnpm docs:check`
Expected: no broken links.

- [ ] **Step 5: Commit**

```bash
git add docs docs.json CLAUDE.md custom_components/pururu/manifest.json tests/test_notifications.py
git commit -m "pururu: notifications (0.1.22)"   # plus the two trailer lines
```
