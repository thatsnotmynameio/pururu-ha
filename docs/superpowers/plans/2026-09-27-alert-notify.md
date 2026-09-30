# Alert Notify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An alert can carry `notify: {message, done_message}`, exposed as attributes for one Alert2 generator block to deliver, and logs an error when it has `notify:` but Alert2 isn't set up.

**Architecture:** Everything lives in `features/alerts.py`. The alert schema gains an optional `notify` block of its own. The `Alert` entity adds its two texts to its attributes, and at the start it already waits for (`_start`, run through `async_at_started`), an alert with `notify:` checks `"alert2" in hass.config.components` and logs an error when it isn't. The core is unchanged.

**Tech Stack:** Home Assistant 2026.9.3 custom integration, voluptuous, pytest with `pytest-homeassistant-custom-component`, docs.page MDX, pnpm for the docs CLI.

**Spec:** `docs/superpowers/specs/2026-09-27-alert-notify-design.md`

## Global Constraints

- pururu sends nothing: Alert2 delivers, through one `generator` block the user writes, reading the alert's attributes.
- `notify` is optional; inside it `message` and `done_message` are both required and not empty; unknown keys are refused.
- An alert with `notify:` has the attributes `message` and `done_message`; an alert without it has neither. `priority` and `watches` stay.
- The Alert2 check runs once Home Assistant has started, only for alerts with `notify:`, and logs exactly `<alert entity ID> has notify, but Alert2 isn't set up to deliver it` as an error, once per alert and setup. Nothing else changes.
- No Alert2 dependency in `manifest.json`; the core (`__init__.py`) doesn't change.
- Version: `custom_components/pururu/manifest.json` `version` becomes `0.1.8`.
- Run everything from the worktree root with `uv`. Single test file: `uv run pytest tests/<file>.py -n 0 -q` (never `-p no:xdist`). Never leave the shell's cwd inside `.venv/.../homeassistant/helpers/`.
- ruff and mypy (strict) run on `custom_components/pururu` only, through `tests/test_code.py`. Match the surrounding code.
- Docs: `{` and `<` outside code are JSX in MDX. JavaScript tooling uses pnpm: `npx --yes pnpm@12.6.0 install --frozen-lockfile`, then `npx --yes pnpm@12.6.0 docs:check`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Alert2 loaded after pururu but before Home Assistant finished starting — a person expects no error: the check runs at start, not at setup. Test in Task 1 (`test_alert2_set_up_before_the_start_is_no_error`).
2. An alert without `notify:` on a system without Alert2 — a person using automations expects no error at every start. Test in Task 1 (`test_without_notify_there_is_no_alert2_error`).
3. A `notify:` with only one of the texts, or with a key Alert2 has but pururu doesn't take (`title`) — a person expects a configuration error naming it, not a silent half. Test in Task 1 (`test_invalid_notify_is_refused`).
4. A reload with `notify:` and no Alert2 — a person expects one error per alert per setup, not errors piling up. Test in Task 1 (`test_the_alert2_error_is_logged_once_per_setup`).
5. An alert without `notify:` — Alert2's generator must not pick it up, so it must have no `message` attribute at all (not an empty one). Test in Task 1 (`test_without_notify_there_are_no_texts`).

---

### Task 1: `notify` in the alert

**Files:**
- Modify: `custom_components/pururu/features/alerts.py` (imports, `_LOGGER`, `TEXT`, `NOTIFY`, `ALERT`, `Alert.__init__`, `Alert._start`, `build`)
- Test: `tests/test_alerts.py`

**Interfaces:**
- Produces: `NOTIFY` schema; `Alert(..., notify: Mapping[str, str] | None)`; the log line `"%s has notify, but Alert2 isn't set up to deliver it"` (argument: the alert's entity ID).

- [ ] **Step 1: Write the tests**

In `tests/test_alerts.py`, the import from `homeassistant.core` becomes:

```python
from homeassistant.core import CoreState, HomeAssistant, State
```

Add after `test_a_when_of_no_entity_key_names_it`:

```python
NOTIFY = {"message": "Overload!", "done_message": "Back to normal."}
NOTIFY_PATH = "pururu->devices->dummy_washer->alerts->overload->notify"


@pytest.mark.parametrize(("notify", "reason"), [
    pytest.param({"done_message": "OK"}, "required key 'message' not provided", id="no message"),
    pytest.param({"message": "X"}, "required key 'done_message' not provided",
                 id="no done_message"),
    pytest.param({**NOTIFY, "message": " "},
                 f"length of value must be at least 1 for dictionary value '{NOTIFY_PATH}->message'",
                 id="empty message"),
    pytest.param({**NOTIFY, "title": "X"},
                 f"'title' is an invalid option for 'pururu', check: {NOTIFY_PATH}->title",
                 id="unknown key"),
])
async def test_invalid_notify_is_refused(ha: HomeAssistant, caplog: pytest.LogCaptureFixture,
                                         notify: dict[str, Any], reason: str) -> None:
    assert not await setup(ha, devices(overload={**OVERLOAD, "notify": notify}))
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(reason in message for message in errors), errors
```

Add at the end of `# --- the entity ---`, after `test_the_name_is_the_same_in_portuguese`:

```python
async def test_notify_texts_are_attributes(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(overload={**OVERLOAD, "notify": NOTIFY}))
    attributes = ha.states.get(alert("overload")).attributes
    assert attributes["message"] == "Overload!"
    assert attributes["done_message"] == "Back to normal."


async def test_without_notify_there_are_no_texts(ha: HomeAssistant) -> None:
    """Alert2's generator picks the alerts that have a message attribute."""
    assert await setup(ha, devices(overload=OVERLOAD))
    attributes = ha.states.get(alert("overload")).attributes
    assert "message" not in attributes
    assert "done_message" not in attributes


# --- Alert2 ------------------------------------------------------------------------------

NOTIFY_ERROR = "has notify, but Alert2 isn't set up to deliver it"


def notify_errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.levelname == "ERROR" and NOTIFY_ERROR in r.getMessage()]


async def test_notify_without_alert2_is_an_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    assert await setup(ha, devices(overload={**OVERLOAD, "notify": NOTIFY}, other=OVERLOAD))
    assert notify_errors(caplog) == [f"{alert('overload')} {NOTIFY_ERROR}"]


async def test_notify_with_alert2_is_no_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    ha.config.components.add("alert2")
    assert await setup(ha, devices(overload={**OVERLOAD, "notify": NOTIFY}))
    assert notify_errors(caplog) == []


async def test_without_notify_there_is_no_alert2_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    assert await setup(ha, devices(overload=OVERLOAD))
    assert notify_errors(caplog) == []


async def test_alert2_set_up_before_the_start_is_no_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Alert2 may load after pururu: the check waits for Home Assistant to start."""
    ha.set_state(CoreState.not_running)
    assert await setup(ha, devices(overload={**OVERLOAD, "notify": NOTIFY}))
    ha.config.components.add("alert2")
    await ha.async_start()
    await ha.async_block_till_done()
    assert notify_errors(caplog) == []


async def test_the_alert2_error_is_logged_once_per_setup(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    config = devices(overload={**OVERLOAD, "notify": NOTIFY})
    assert await setup(ha, config)
    caplog.clear()
    await reload(ha, config)
    assert notify_errors(caplog) == [f"{alert('overload')} {NOTIFY_ERROR}"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_alerts.py -n 0 -q -k "notify or alert2"`
Expected: FAIL: `test_notify_texts_are_attributes` and every test with `notify` fail because `notify` is an invalid option (setup returns False); `test_notify_without_alert2_is_an_error` and `test_the_alert2_error_is_logged_once_per_setup` fail on it too. `test_without_notify_there_are_no_texts` and `test_without_notify_there_is_no_alert2_error` pass already (they pin what must not change). The four `test_invalid_notify_is_refused` cases fail on their reason (the refusal is `'notify' is an invalid option`).

- [ ] **Step 3: `features/alerts.py`**

Imports: add `import logging` with the other standard imports (after `from datetime import datetime, timedelta`), keeping them sorted as ruff wants:

```python
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any, override
```

After the imports, before `PRIORITIES`:

```python
_LOGGER = logging.getLogger(__name__)

# Alert2 (HACS) delivers what an alert's notify says
ALERT2 = "alert2"
```

Before `ALERT`, add:

```python
# Text a person reads: a blank one would say nothing
TEXT = vol.All(cv.string, vol.Strip, vol.Length(min=1))
# What to tell, for Alert2 to deliver; a schema of its own, so unknown keys are refused
NOTIFY = vol.Schema({vol.Required("message"): TEXT, vol.Required("done_message"): TEXT})
```

`ALERT`'s `name` line becomes `vol.Required("name"): TEXT,` (keep its comment), and after `priority` add:

```python
            vol.Optional("notify"): NOTIFY,
```

`Alert.__init__` gains a keyword parameter after `priority: str,`:

```python
        notify: Mapping[str, str] | None,
```

and its attributes and a flag become:

```python
        self._attr_extra_state_attributes = {
            "priority": priority,
            "watches": watched,
            **(notify or {}),
        }
        self._notifies = notify is not None
```

`Alert._start` becomes:

```python
    @callback
    def _start(self, _hass: HomeAssistant) -> None:
        """Follow the watched entity: while HA starts, entities pass through unavailable.

        Also the time to know whether Alert2, which delivers `notify`, is set up:
        it may load after pururu.
        """
        if self._notifies and ALERT2 not in self.hass.config.components:
            _LOGGER.error(
                "%s has notify, but Alert2 isn't set up to deliver it", self.entity_id
            )
        self.async_on_remove(
            async_track_state_change_event(self.hass, self._watched, self._changed)
        )
        # Not there yet, as the device's other platforms set up alongside: no reading
        if (state := self.hass.states.get(self._watched)) is not None:
            self._evaluate(state)
```

In `build`, after `priority=alert["priority"],` add:

```python
            notify=alert.get("notify"),
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_alerts.py -n 0 -q`
Expected: PASS.

Run: `uv run pytest`
Expected: PASS, including `tests/test_code.py` (ruff, ruff format, mypy, hassfest). If only `test_ruff_format` fails, run `uv run ruff format custom_components/pururu/features/alerts.py` and run it again.

- [ ] **Step 5: Commit**

```bash
git add custom_components/pururu/features/alerts.py tests/test_alerts.py
git commit -m "pururu: an alert's notify, for Alert2 to deliver

notify: {message, done_message} becomes the alert's attributes; once HA
has started, an alert with notify logs an error when Alert2 isn't set up.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Docs and the release

**Files:**
- Modify: `docs/features/alerts.mdx`, `docs/reference/configuration.mdx`, `docs/reference/troubleshooting.mdx`, `custom_components/pururu/manifest.json`

**Interfaces:**
- Consumes: the `notify` keys, the attributes and the log line of Task 1.

- [ ] **Step 1: `docs/features/alerts.mdx`**

- The paragraph starting `pururu only **detects** the problem.` becomes:

```mdx
pururu **detects** the problem and, with `notify`, says what to tell. [Alert2](https://github.com/redstone99/hass-alert2) does the telling (phones, reminders, acknowledging): see [Getting notified](#getting-notified).
```

- In the first example, `long_cycle` becomes a block with `notify`:

```yaml
      alerts:
        long_cycle:
          name: Ciclo longo
          when: appliance_running
          is: "on"
          for: {hours: 3}
          priority: medium
          notify:
            message: A máquina passou de 3 horas ligada!
            done_message: A máquina terminou.
        overload: {name: Sobrecarga, when: appliance_power, above: 2500, for: {minutes: 1}, priority: high}
        plug_offline: {name: Tomada offline, when: appliance_power, is: unavailable, for: {minutes: 10}}
```

- After the `priority` property, before `An alert needs **either**`, add:

```mdx
---

<Property name="notify" type="map" optional>
  What to tell, for Alert2 to deliver: `message` when the alert fires and `done_message` when it's resolved. Both are required and can't be empty. Without `notify`, Alert2 leaves the alert alone. See [Getting notified](#getting-notified).
</Property>
```

- Under `## Entity`, the attributes sentence becomes:

```mdx
Its attributes are **`priority`** and **`watches`**, the entity it watches, and, with `notify`, **`message`** and **`done_message`**. It's in the device, so it's in the device's area.
```

- Replace the whole `## Getting notified` section (to the end of the file) with:

````mdx
## Getting notified

pururu sends nothing itself. [Alert2](https://github.com/redstone99/hass-alert2) delivers the alerts that have `notify`, with one `generator` you add to Alert2's configuration once. It covers every alert with `notify`, including the ones you add later:

```yaml
alert2:
  defaults:
    notifier: mobile_app_phone         # who is told
    reminder_frequency_mins: [8, 20]   # while the problem lasts
  alerts:
    - generator_name: pururu
      generator: "{{ states.binary_sensor | selectattr('attributes.message', 'defined') | entity_regex('binary_sensor\\.pururu_(.+_alert_.+)$') | list }}"
      domain: pururu
      name: "{{ genGroups[0] }}"
      condition: "{{ is_state(genEntityId, 'on') }}"
      friendly_name: "{{ state_attr(genEntityId, 'friendly_name') }}"
      priority: "{{ state_attr(genEntityId, 'priority') }}"
      message: "{{ state_attr(genEntityId, 'message') }}"
      done_message: "{{ state_attr(genEntityId, 'done_message') }}"
```

- **What each alert says** comes from its `notify`. **How** it's told is the same for every alert, in Alert2's `defaults` or in this block: who is told, reminders, acknowledging, a title. See Alert2's documentation.
- It picks only the alerts with `notify` (they alone have a `message`).
- Each Alert2 alert is named after the rest of the pururu alert's ID: `binary_sensor.pururu_clothes_washer_alert_long_cycle` becomes `alert2.pururu_clothes_washer_alert_long_cycle`, whatever the device and alert keys contain.
- If an alert has `notify` and Alert2 isn't set up once Home Assistant has started, the log says so: `binary_sensor.pururu_clothes_washer_alert_long_cycle has notify, but Alert2 isn't set up to deliver it`. The alert still works as a binary sensor.

**Without `notify`**, the alert is yours to use: an automation triggered by it turning on, or Home Assistant's [`alert`](https://www.home-assistant.io/integrations/alert/):

```yaml
alert:
  washer_long_cycle:
    name: Tanquinho Ciclo longo
    entity_id: binary_sensor.pururu_clothes_washer_alert_long_cycle
    repeat: 30
    notifiers: [mobile_app_phone]
```
````

- [ ] **Step 2: `docs/reference/configuration.mdx`**

The `long_cycle` line in the example becomes:

```yaml
        long_cycle:
          name: Ciclo longo
          when: appliance_running
          is: "on"
          for: {hours: 3}
          priority: medium
          notify: {message: A máquina passou de 3 horas ligada!, done_message: A máquina terminou.}
```

- [ ] **Step 3: `docs/reference/troubleshooting.mdx`**

In the list of configuration causes, after the line starting `- An alert with both \`is\``, add:

```mdx
- An alert's `notify` without `message` or `done_message`, with an empty one, or with another key.
```

After the section `### \`… watches …, which this device's settings don't create …\`` (its **Fix** line), add:

````mdx
### `… has notify, but Alert2 isn't set up to deliver it`

```
binary_sensor.pururu_clothes_washer_alert_long_cycle has notify, but Alert2 isn't set up to deliver it
```

An alert with `notify` is delivered by [Alert2](/features/alerts#getting-notified), which isn't installed, or failed to set up. The alert still works as a binary sensor; nobody is told.

**Fix:** install Alert2 and add pururu's generator, or remove `notify` from the alert.
````

- [ ] **Step 4: The version**

In `custom_components/pururu/manifest.json`, `"version": "0.1.7"` → `"version": "0.1.8"`.

Run: `python3 release.py check`
Expected: `release: v0.1.8 will be published`.

- [ ] **Step 5: Verify**

Run: `npx --yes pnpm@12.6.0 install --frozen-lockfile`, then `npx --yes pnpm@12.6.0 docs:check`
Expected: `No documentation issues found.`

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add docs custom_components/pururu/manifest.json
git commit -m "Docs and release: alert notify (0.1.8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
