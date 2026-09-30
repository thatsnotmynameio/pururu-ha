# Alert2 config, written by pururu — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** pururu writes an Alert2 alert for every alert with `notify` to `pururu/alert2/alerts.yaml`, reloads Alert2 when needed, and raises a Repairs issue while the user's `alert2:` block doesn't include it: the Alert2 generator goes away.

**Architecture:** A new module `alert2_alerts.py` mirrors `reactions.py`: build the list, write the file (shared writer moved to `files.py`), and once HA has started, in an entry task, reload Alert2 when the file changed or an alert isn't running, then check the include. `__init__.py` builds the list from the created alerts and calls it after the reactions.

**Tech Stack:** Home Assistant 2026.9.3 custom integration, voluptuous, pytest-homeassistant-custom-component, docs.page MDX.

**Spec:** `docs/superpowers/specs/2026-09-27-alert2-config-design.md`

## Global Constraints

- Version: `custom_components/pururu/manifest.json` goes from `0.1.11` to `0.1.12`.
- File: `pururu/alert2/alerts.yaml`; include line: `alerts: !include_dir_merge_list pururu/alert2` (inside the user's `alert2:` block).
- Alert2 alert: `domain: pururu`, `name: <device key>_alert_<alert key>` (the binary sensor's object ID without `pururu_`), so its entity is `alert2.pururu_<device key>_alert_<alert key>`; Alert2's unique ID is `d=pururu-n=<name>`.
- Only alerts with `notify` that are created go in the file; the file is `[]` otherwise.
- `friendly_name`, `message`, `done_message` containing `{` are wrapped in `{% raw %}…{% endraw %}`.
- Repairs issue ID `alert2_not_included`, placeholders `include` and `file`, severity warning, not fixable.
- Nothing ever fails the setup: write and reload failures are logged.
- Ruff/mypy strict on `custom_components/pururu` (`uv run pytest` runs them via `tests/test_code.py`). Tests are not linted but follow the existing style.
- Docs are MDX: `{` and `<` outside code must be in backticks or code blocks.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- Alert2 set up but its reload fails (or its service is missing): logged `Alert2 is not reloaded: …`, no Repairs issue, retried at the next pururu reload (Task 3 tests).
- A `message` containing `{{ … }}`: Alert2 must show it literally, not render it (Task 2 test).
- At start, Alert2's alert is a restored placeholder: it counts as not running, so Alert2 is reloaded (Task 3 test).
- An Alert2 alert the user disabled: not "missing", so no reload loop and no issue (Task 3 test).
- An alert not created (its `when` not built): not written, so no Alert2 condition names a missing entity (Task 2 test).

---

## File Structure

- Create `custom_components/pururu/files.py`: the header and the atomic, byte-compared write of a generated YAML file; shared by reactions and Alert2.
- Modify `custom_components/pururu/reactions.py`: use `files`.
- Create `custom_components/pururu/alert2_alerts.py`: the Alert2 alert of a pururu alert, the write, the reload, the include check, the removal.
- Modify `custom_components/pururu/features/alerts.py`: take `ALERT2` from `alert2_alerts`.
- Modify `custom_components/pururu/__init__.py`: build the list, call `alert2_alerts.async_sync` / `async_remove`.
- Modify `custom_components/pururu/translations/en.json`, `pt-BR.json`: the issue.
- Create `tests/test_alert2.py`. Modify `tests/test_reactions.py` (patch target), `tests/test_alerts.py` (generator tests go).
- Docs: `docs/features/alerts.mdx`, `docs/reference/troubleshooting.mdx`, `docs/reference/configuration.mdx` (if it mentions the generator; it doesn't today, so only if a mention is found), `docs/develop/architecture.mdx`, `CLAUDE.md`, manifest version.

---

### Task 1: Move the generated-file writer to `files.py`

**Files:**
- Create: `custom_components/pururu/files.py`
- Modify: `custom_components/pururu/reactions.py` (`HEADER`, `_write`, `_async_write`, their imports)
- Modify: `tests/test_reactions.py` (the four `patch.object(reactions, "write_utf8_file_atomic", …)`)

**Interfaces:**
- Produces: `files.HEADER: str`; `async def files.async_write(hass: HomeAssistant, file: str, what: str, items: list[dict[str, Any]]) -> bool | None` — `True` written, `False` unchanged, `None` failed (logged as `"<what> are not written to <file>: <err>"`).

- [ ] **Step 1: Point the reactions tests at the new module**

In `tests/test_reactions.py`, replace every

```python
    reactions = module("reactions")
    with patch.object(reactions, "write_utf8_file_atomic", side_effect=WriteError("disk full")):
```

with

```python
    files = module("files")
    with patch.object(files, "write_utf8_file_atomic", side_effect=WriteError("disk full")):
```

(four places: `test_a_failed_write_is_logged_and_the_setup_goes_on`, `test_a_failed_write_drops_nothing_stale`, `test_a_failed_write_raises_no_include_issue`, `test_a_failed_removal_keeps_the_automations_ids`).

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_reactions.py -n 0 -q -k failed`
Expected: FAIL, `ModuleNotFoundError: No module named 'custom_components.pururu.files'`.

- [ ] **Step 3: Create `files.py`**

```python
"""Files pururu generates next to configuration.yaml, which the configuration includes."""

import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.file import write_utf8_file_atomic
from homeassistant.util.yaml import dump

_LOGGER = logging.getLogger(__name__)

HEADER = (
    "# Generated by pururu from its configuration. "
    "Don't edit: it is rewritten on every reload.\n"
)


def _write(path: Path, content: str) -> bool:
    """Write `content` unless the file already holds it; whether it wrote.

    Bytes are compared: a file saved in another encoding is rewritten, not an error.
    """
    if path.is_file() and path.read_bytes() == content.encode("utf-8"):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    write_utf8_file_atomic(str(path), content)
    return True


async def async_write(
    hass: HomeAssistant, file: str, what: str, items: list[dict[str, Any]]
) -> bool | None:
    """Write `items` to `file` if it changed; whether it did, or None on failure.

    `file` is relative to the configuration folder; `what` names the items in
    the log. A failure is logged, never raised: the caller must tell
    "unchanged" (False) from "failed" (None).
    """
    try:
        return await hass.async_add_executor_job(
            _write, Path(hass.config.path(file)), HEADER + dump(items)
        )
    except (OSError, HomeAssistantError) as err:
        _LOGGER.error("%s are not written to %s: %s", what, file, err)
        return None
```

- [ ] **Step 4: Use it in `reactions.py`**

Delete `HEADER`, `_write` and `_async_write` from `reactions.py`, and the now-unused imports `from pathlib import Path`, `from homeassistant.util.file import write_utf8_file_atomic`, `from homeassistant.util.yaml import dump` (keep `HomeAssistantError`: `_async_reload` uses it). Add `from . import files` after the `homeassistant` imports (before `from .const import …`). Add, next to `FILE`:

```python
# How the log names what the file holds
WHAT = "The automations"
```

Replace the two calls:

```python
    written = await _async_write(hass, kept)
```
→
```python
    written = await files.async_write(hass, FILE, WHAT, kept)
```

and in `async_remove`:

```python
    if await _async_write(hass, []) and hass.is_running:
```
→
```python
    if await files.async_write(hass, FILE, WHAT, []) and hass.is_running:
```

- [ ] **Step 5: Run the reactions tests**

Run: `uv run pytest tests/test_reactions.py -n 0 -q`
Expected: all PASS (the log line `The automations are not written to pururu/automations/reactions.yaml: disk full` is unchanged).

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check custom_components/pururu && uv run ruff format --check custom_components/pururu && uv run mypy custom_components/pururu`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add custom_components/pururu/files.py custom_components/pururu/reactions.py tests/test_reactions.py
git commit -m "pururu: the generated-file writer, shared

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Write the Alert2 alerts file

**Files:**
- Create: `custom_components/pururu/alert2_alerts.py` (the file part; Task 3 adds reload and include check)
- Modify: `custom_components/pururu/__init__.py`
- Modify: `custom_components/pururu/features/alerts.py` (`ALERT2` import)
- Test: `tests/test_alert2.py`

**Interfaces:**
- Consumes: `files.async_write` (Task 1).
- Produces: `alert2_alerts.ALERT2 = "alert2"`, `FOLDER`, `FILE = "pururu/alert2/alerts.yaml"`, `INCLUDE`, `WHAT`; `alert2_alerts.alert(object_id: str, entity_id: str, friendly_name: str, priority: str, notify: Mapping[str, str]) -> dict[str, Any]`; `async def alert2_alerts.async_sync(hass: HomeAssistant, entry: ConfigEntry, alerts: list[dict[str, Any]]) -> None`; `async def alert2_alerts.async_remove(hass: HomeAssistant) -> None`. In `__init__.py`: `_alert2_alerts(hass, devices, created) -> list[dict[str, Any]]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_alert2.py`:

```python
"""Alert2's alerts: pururu writes one per alert with notify, for a made-up washer."""

from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util.yaml import load_yaml_dict
import pytest
import yaml

from helpers import setup

KEY = "dummy_washer"
POWER = "sensor.dummy_plug_power"
APPLIANCE: dict[str, Any] = {
    "power": POWER,
    "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}
NOTIFY = {"message": "Overload!", "done_message": "Back to normal."}
OVERLOAD = {"name": "Overload", "when": "appliance_power", "above": 2500}
FILE = "pururu/alert2/alerts.yaml"
INCLUDE = "alerts: !include_dir_merge_list pururu/alert2"
SENSOR = "binary_sensor.pururu_dummy_washer_alert_overload"


def devices(**alerts: dict[str, Any]) -> dict[str, Any]:
    device: dict[str, Any] = {"name": "Dummy washer", "appliance": APPLIANCE}
    if alerts:
        device["alerts"] = alerts
    return {KEY: device}


def written(hass: HomeAssistant) -> list[dict[str, Any]]:
    """The Alert2 alerts pururu wrote, as the include reads them."""
    path = Path(hass.config.path(FILE))
    if not path.is_file():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


# --- the file ---------------------------------------------------------------------------


async def test_an_alert_with_notify_is_an_alert2_alert(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(overload={**OVERLOAD, "priority": "high", "notify": NOTIFY}))
    text = Path(ha.config.path(FILE)).read_text(encoding="utf-8")
    assert text.startswith("# Generated by pururu from its configuration. Don't edit: ")
    assert written(ha) == [{
        "domain": "pururu",
        "name": "dummy_washer_alert_overload",
        "friendly_name": "Dummy washer Overload",
        "condition_on": f"{{{{ is_state('{SENSOR}', 'on') }}}}",
        "condition_off": f"{{{{ is_state('{SENSOR}', 'off') }}}}",
        "priority": "high",
        "message": "Overload!",
        "done_message": "Back to normal.",
    }]


@pytest.mark.parametrize("alerts", [
    pytest.param({"overload": OVERLOAD}, id="without notify"),
    pytest.param({}, id="without alerts"),
])
async def test_the_file_is_an_empty_list_without_notify(ha: HomeAssistant,
                                                        alerts: dict[str, Any]) -> None:
    assert await setup(ha, devices(**alerts))
    assert Path(ha.config.path(FILE)).is_file()
    assert written(ha) == []


async def test_text_with_a_brace_is_not_a_template(ha: HomeAssistant) -> None:
    """Alert2 renders these fields: what the user wrote must show as written."""
    notify = {"message": "{{ 1 + 1 }} W", "done_message": "ok"}
    assert await setup(ha, devices(overload={**OVERLOAD, "name": "{x}", "notify": notify}))
    [entry] = written(ha)
    assert entry["message"] == "{% raw %}{{ 1 + 1 }} W{% endraw %}"
    assert entry["friendly_name"] == "{% raw %}Dummy washer {x}{% endraw %}"
    assert entry["done_message"] == "ok"


async def test_the_conditions_follow_a_renamed_alert(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(overload={**OVERLOAD, "notify": NOTIFY}))
    er.async_get(ha).async_update_entity(SENSOR, new_entity_id="binary_sensor.mine")
    await ha.async_block_till_done()
    [entry] = written(ha)
    assert entry["name"] == "dummy_washer_alert_overload"
    assert entry["condition_on"] == "{{ is_state('binary_sensor.mine', 'on') }}"


async def test_an_alert_not_created_is_not_written(ha: HomeAssistant) -> None:
    month = {"name": "Month", "when": "appliance_runtime_month", "above": 1, "notify": NOTIFY}
    assert await setup(ha, devices(month=month, overload={**OVERLOAD, "notify": NOTIFY}))
    assert [entry["name"] for entry in written(ha)] == ["dummy_washer_alert_overload"]


async def test_the_include_tolerates_a_missing_folder_and_reads_the_file(
        ha: HomeAssistant) -> None:
    """Before pururu has written anything, HA still loads its configuration."""
    configuration = Path(ha.config.path("configuration.yaml"))
    configuration.write_text(f"alert2:\n  {INCLUDE}\n", encoding="utf-8")
    assert load_yaml_dict(configuration) == {"alert2": {"alerts": []}}
    assert await setup(ha, devices(overload={**OVERLOAD, "notify": NOTIFY}))
    assert load_yaml_dict(configuration) == {"alert2": {"alerts": written(ha)}}
    assert written(ha) != []
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_alert2.py -n 0 -q`
Expected: FAIL (no file written).

- [ ] **Step 3: Create `alert2_alerts.py` (file part)**

```python
"""Alert2's alerts: one for each pururu alert with notify, which Alert2 delivers.

pururu writes them to pururu/alert2/alerts.yaml; the user's alert2: block
includes its folder as its alerts. Alert2 renders these fields as templates:
what the user wrote is kept as text.
"""

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import files
from .const import DOMAIN, ENTITY_PREFIX

# Alert2 (HACS) delivers what an alert's notify says
ALERT2 = "alert2"
# Relative to HA's configuration folder, as the alert2: block's include names it
FOLDER = "pururu/alert2"
FILE = f"{FOLDER}/alerts.yaml"
# A folder, not the file: a missing folder loads as no alerts
INCLUDE = f"alerts: !include_dir_merge_list {FOLDER}"
# How the log names what the file holds
WHAT = "The Alert2 alerts"


def _text(text: str) -> str:
    """`text` as Alert2 shows it: every template delimiter starts with {."""
    return f"{{% raw %}}{text}{{% endraw %}}" if "{" in text else text


def alert(
    object_id: str,
    entity_id: str,
    friendly_name: str,
    priority: str,
    notify: Mapping[str, str],
) -> dict[str, Any]:
    """The Alert2 alert of the pururu alert `object_id`, whose entity ID is now `entity_id`.

    Named after the object ID, so alert2.pururu_<object ID without pururu_>
    whatever the user renamed; on and off conditions, so an unavailable pururu
    alert (during a reload) leaves the Alert2 one as it is.
    """
    return {
        "domain": DOMAIN,
        "name": object_id.removeprefix(f"{ENTITY_PREFIX}_"),
        "friendly_name": _text(friendly_name),
        "condition_on": f"{{{{ is_state('{entity_id}', 'on') }}}}",
        "condition_off": f"{{{{ is_state('{entity_id}', 'off') }}}}",
        "priority": priority,
        "message": _text(notify["message"]),
        "done_message": _text(notify["done_message"]),
    }


async def async_sync(
    hass: HomeAssistant, entry: ConfigEntry, alerts: list[dict[str, Any]]
) -> None:
    """Write the Alert2 alerts."""
    await files.async_write(hass, FILE, WHAT, alerts)


async def async_remove(hass: HomeAssistant) -> None:
    """Write no alerts: an empty file, still valid for the include."""
    await files.async_write(hass, FILE, WHAT, [])
```

- [ ] **Step 4: Take `ALERT2` from it in `features/alerts.py`**

Delete these lines from `custom_components/pururu/features/alerts.py`:

```python
# Alert2 (HACS) delivers what an alert's notify says
ALERT2 = "alert2"
```

and add, next to the other relative imports:

```python
from ..alert2_alerts import ALERT2
```

- [ ] **Step 5: Build the list and call it in `__init__.py`**

Change the import line `from . import dashboard, places, reactions` to:

```python
from . import alert2_alerts, dashboard, places, reactions
```

In `async_setup_entry`, right after the `hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_AUTOMATIONS: generated})` call and before `dashboard.async_setup(hass, entry)`, add:

```python
    await alert2_alerts.async_sync(
        hass, entry, _alert2_alerts(hass, devices, created)
    )
```

Update its docstring's second paragraph sentence to: `The reactions' automations and Alert2's alerts come after the entities: they watch the ones created.`

In `async_remove_entry`, after `await reactions.async_remove(hass, entry)`:

```python
    await alert2_alerts.async_remove(hass)
```

and its docstring becomes `"""Delete the floors and areas the entry managed, its reactions' automations and its Alert2 alerts."""`.

Add at the end of the module:

```python
def _alert2_alerts(
    hass: HomeAssistant, devices: dict[str, dict[str, Any]], created: set[str]
) -> list[dict[str, Any]]:
    """An Alert2 alert per created alert with notify; one not created would watch nothing."""
    alerts: list[dict[str, Any]] = []
    for key, config in devices.items():
        device = Device(
            key=key, name=config[CONF_NAME], namespace=FEATURES[CONF_ALERTS].namespace
        )
        for alert_key, alert in config.get(CONF_ALERTS, {}).items():
            object_id = device.object_id(alert_key)
            if "notify" not in alert or object_id not in created:
                continue
            alerts.append(
                alert2_alerts.alert(
                    object_id,
                    device.current_entity_id(hass, Platform.BINARY_SENSOR, alert_key),
                    f"{config[CONF_NAME]} {alert[CONF_NAME]}",
                    alert["priority"],
                    alert["notify"],
                )
            )
    return alerts
```

Add to `const.py`, after `CONF_REACTIONS`:

```python
# A device's alerts: the feature whose alerts with notify Alert2 delivers
CONF_ALERTS: Final = "alerts"
```

and `CONF_ALERTS` to the `from .const import (…)` list in `__init__.py` (alphabetical: after `CONF_AREA`? keep ruff's isort order — `CONF_ALERTS` sorts before `CONF_AREA`).

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_alert2.py tests/test_alerts.py tests/test_reactions.py -n 0 -q`
Expected: all PASS.

- [ ] **Step 7: Lint and type-check**

Run: `uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu && uv run mypy custom_components/pururu`
Expected: no errors. (`entry` is unused in `async_sync` until Task 3; the ruff config doesn't enable `ARG`, so that's fine.)

- [ ] **Step 8: Commit**

```bash
git add custom_components/pururu tests/test_alert2.py
git commit -m "pururu: Alert2's alerts, written for every alert with notify

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Reload Alert2, check the include, Repairs

**Files:**
- Modify: `custom_components/pururu/alert2_alerts.py`
- Modify: `custom_components/pururu/translations/en.json`, `custom_components/pururu/translations/pt-BR.json`
- Test: `tests/test_alert2.py`

**Interfaces:**
- Consumes: Task 2's `alert2_alerts` names, `files.async_write`.
- Produces: `alert2_alerts.ISSUE = "alert2_not_included"`; `async_sync` and `async_remove` keep their signatures.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_alert2.py` (and add the imports `from unittest.mock import patch`, `from homeassistant.core import ServiceCall`, `from homeassistant.exceptions import HomeAssistantError`, `from homeassistant.helpers import issue_registry as ir`, `from homeassistant.util.file import WriteError`, and `module, reload` from `helpers`):

```python
# --- Alert2, reloads, the include --------------------------------------------------------


class FakeAlert2:
    """Alert2 as pururu sees it: its reload reads the included file into its alerts."""

    def __init__(self, hass: HomeAssistant, *, included: bool = True) -> None:
        self.hass = hass
        self.included = included
        self.fails = False
        self.reloads = 0
        hass.config.components.add("alert2")
        hass.services.async_register("alert2", "reload", self._reload)

    async def _reload(self, _call: ServiceCall) -> None:
        if self.fails:
            raise HomeAssistantError("boom")
        self.reloads += 1
        for entity_id in self.hass.states.async_entity_ids("alert2"):
            self.hass.states.async_remove(entity_id)
        if self.included:
            for each in written(self.hass):
                self.hass.states.async_set(f"alert2.{each['domain']}_{each['name']}", "off")


@pytest.fixture
def alert2(ha: HomeAssistant) -> FakeAlert2:
    return FakeAlert2(ha)


ALERT2 = "alert2.pururu_dummy_washer_alert_overload"
WITH_NOTIFY = {"overload": {**OVERLOAD, "notify": NOTIFY}}


def issue(ha: HomeAssistant) -> ir.IssueEntry | None:
    return ir.async_get(ha).async_get_issue("pururu", "alert2_not_included")


async def test_a_new_file_reloads_alert2(ha: HomeAssistant, alert2: FakeAlert2) -> None:
    assert await setup(ha, devices(**WITH_NOTIFY))
    assert alert2.reloads == 1
    assert ha.states.get(ALERT2) is not None
    assert issue(ha) is None


async def test_an_unchanged_file_reloads_nothing(ha: HomeAssistant, alert2: FakeAlert2) -> None:
    assert await setup(ha, devices(**WITH_NOTIFY))
    await reload(ha, devices(**WITH_NOTIFY))
    assert alert2.reloads == 1


async def test_a_changed_file_reloads_alert2(ha: HomeAssistant, alert2: FakeAlert2) -> None:
    assert await setup(ha, devices(**WITH_NOTIFY))
    await reload(ha, devices(other={**OVERLOAD, "notify": NOTIFY}))
    assert alert2.reloads == 2
    assert ha.states.get(ALERT2) is None
    assert ha.states.get("alert2.pururu_dummy_washer_alert_other") is not None


async def test_a_restored_placeholder_is_not_running(ha: HomeAssistant,
                                                    alert2: FakeAlert2) -> None:
    """At start, HA shows Alert2's registered alert as restored until Alert2 declares it."""
    assert await setup(ha, devices(**WITH_NOTIFY))
    ha.states.async_set(ALERT2, "unavailable", {"restored": True})
    await reload(ha, devices(**WITH_NOTIFY))
    assert alert2.reloads == 2
    assert not ha.states.get(ALERT2).attributes.get("restored")


INCLUDE_WARNING = ("Alert2 doesn't run pururu's alerts: add \"alerts: !include_dir_merge_list "
                   "pururu/alert2\" to the alert2: block of configuration.yaml")


async def test_without_the_include_an_issue_says_what_to_add(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    FakeAlert2(ha, included=False)
    assert await setup(ha, devices(**WITH_NOTIFY))
    found = issue(ha)
    assert found is not None
    assert found.severity == ir.IssueSeverity.WARNING
    assert not found.is_fixable
    assert found.translation_placeholders == {"include": INCLUDE, "file": FILE}
    assert INCLUDE_WARNING in caplog.text


async def test_once_included_the_next_reload_retries_and_the_issue_goes(
        ha: HomeAssistant) -> None:
    alert2 = FakeAlert2(ha, included=False)
    assert await setup(ha, devices(**WITH_NOTIFY))
    alert2.included = True
    await reload(ha, devices(**WITH_NOTIFY))
    assert alert2.reloads == 2
    assert ha.states.get(ALERT2) is not None
    assert issue(ha) is None


async def test_without_alerts_with_notify_there_is_no_issue(ha: HomeAssistant) -> None:
    FakeAlert2(ha, included=False)
    assert await setup(ha, devices(overload=OVERLOAD))
    assert issue(ha) is None


async def test_without_alert2_nothing_is_reloaded_and_there_is_no_issue(
        ha: HomeAssistant) -> None:
    assert await setup(ha, devices(**WITH_NOTIFY))
    assert written(ha) != []
    assert issue(ha) is None


async def test_a_disabled_alert2_alert_is_no_missing_include(ha: HomeAssistant) -> None:
    er.async_get(ha).async_get_or_create(
        "alert2", "alert2", "d=pururu-n=dummy_washer_alert_overload",
        suggested_object_id="pururu_dummy_washer_alert_overload",
        disabled_by=er.RegistryEntryDisabler.USER)
    alert2 = FakeAlert2(ha, included=False)
    assert await setup(ha, devices(**WITH_NOTIFY))
    await reload(ha, devices(**WITH_NOTIFY))
    assert alert2.reloads == 1
    assert issue(ha) is None


async def test_a_failed_reload_is_logged_raises_no_issue_and_is_retried(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    alert2 = FakeAlert2(ha)
    alert2.fails = True
    assert await setup(ha, devices(**WITH_NOTIFY))
    assert "Alert2 is not reloaded: boom" in caplog.text
    assert issue(ha) is None
    alert2.fails = False
    await reload(ha, devices(**WITH_NOTIFY))
    assert alert2.reloads == 1
    assert ha.states.get(ALERT2) is not None


async def test_a_failed_write_is_logged_and_reloads_nothing(
        ha: HomeAssistant, alert2: FakeAlert2, caplog: pytest.LogCaptureFixture) -> None:
    with patch.object(module("files"), "write_utf8_file_atomic",
                      side_effect=WriteError("disk full")):
        assert await setup(ha, devices(**WITH_NOTIFY))
    assert f"The Alert2 alerts are not written to {FILE}: disk full" in caplog.text
    assert alert2.reloads == 0
    assert issue(ha) is None
    assert ha.states.get(SENSOR) is not None


async def test_removing_the_entry_empties_the_file_and_reloads(
        ha: HomeAssistant) -> None:
    alert2 = FakeAlert2(ha, included=False)
    assert await setup(ha, devices(**WITH_NOTIFY))
    assert issue(ha) is not None
    entry = ha.config_entries.async_entries("pururu")[0]
    await ha.config_entries.async_remove(entry.entry_id)
    await ha.async_block_till_done()
    assert written(ha) == []
    assert alert2.reloads == 2
    assert issue(ha) is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_alert2.py -n 0 -q`
Expected: the new tests FAIL (no reload, no issue); Task 2's still PASS.

- [ ] **Step 3: Add reload, running check and include check to `alert2_alerts.py`**

Replace the imports block with:

```python
from collections.abc import Iterable, Mapping
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_RESTORED, SERVICE_RELOAD
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.start import async_at_started

from . import files
from .const import DOMAIN, ENTITY_PREFIX

_LOGGER = logging.getLogger(__name__)
```

Add after `WHAT`:

```python
ISSUE = "alert2_not_included"
```

Replace `async_sync` and `async_remove` with:

```python
def _unique_id(name: str) -> str:
    """Alert2's unique ID of its alert `name` in pururu's domain."""
    return f"d={DOMAIN}-n={name}"


@callback
def _missing(hass: HomeAssistant, names: Iterable[str]) -> list[str]:
    """The Alert2 alerts Alert2 doesn't run; a disabled one never runs, and isn't missing.

    Found by unique ID, as the user may rename one. A restored placeholder
    (HA shows a registered alert so until Alert2 declares it) isn't running.
    """
    registry = er.async_get(hass)
    missing = []
    for name in names:
        entity_id = registry.async_get_entity_id(ALERT2, ALERT2, _unique_id(name))
        registered = registry.async_get(entity_id) if entity_id is not None else None
        if registered is not None and registered.disabled_by is not None:
            continue
        state = hass.states.get(entity_id or f"{ALERT2}.{DOMAIN}_{name}")
        if state is None or state.attributes.get(ATTR_RESTORED):
            missing.append(name)
    return missing


async def _async_reload(hass: HomeAssistant) -> bool:
    """Reload Alert2; whether it did. A failure is logged, never raised."""
    try:
        await hass.services.async_call(ALERT2, SERVICE_RELOAD, blocking=True)
    except HomeAssistantError as err:
        _LOGGER.error("Alert2 is not reloaded: %s", err)
        return False
    return True


@callback
def _check_included(hass: HomeAssistant, names: Iterable[str]) -> None:
    """Raise the Repairs issue while Alert2 doesn't run an alert of the file, else delete it."""
    if not _missing(hass, names):
        ir.async_delete_issue(hass, DOMAIN, ISSUE)
        return
    _LOGGER.warning(
        'Alert2 doesn\'t run pururu\'s alerts: add "%s" to the alert2: block '
        "of configuration.yaml",
        INCLUDE,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE,
        translation_placeholders={"include": INCLUDE, "file": FILE},
    )


async def _finish(hass: HomeAssistant, changed: bool, names: list[str]) -> None:
    """Once HA has started: reload Alert2 if it doesn't run the file as written, check the include.

    Without Alert2 there is nothing to reload nor include: each alert with
    notify logs so. A reload that failed is retried at the next reload, since
    the alerts still aren't running then; it raises no issue, the include may be there.
    """
    if ALERT2 not in hass.config.components:
        ir.async_delete_issue(hass, DOMAIN, ISSUE)
        return
    if (changed or _missing(hass, names)) and not await _async_reload(hass):
        return
    _check_included(hass, names)


async def async_sync(
    hass: HomeAssistant, entry: ConfigEntry, alerts: list[dict[str, Any]]
) -> None:
    """Write the Alert2 alerts; once HA has started, have Alert2 run them.

    Alert2 loaded the file as it was at start; the rest waits for HA to have
    started (Alert2 may set up after pururu), in a task the entry's unload
    waits for. After a failed write the file is the previous one: nothing is
    reloaded nor checked.
    """
    written = await files.async_write(hass, FILE, WHAT, alerts)
    if written is None:
        return
    names = [each["name"] for each in alerts]

    @callback
    def finish(_hass: HomeAssistant) -> None:
        entry.async_create_task(
            hass, _finish(hass, written, names), "pururu alert2", eager_start=False
        )

    entry.async_on_unload(async_at_started(hass, finish))


async def async_remove(hass: HomeAssistant) -> None:
    """Write no alerts: an empty file, still valid for the include; Alert2 drops them."""
    if (
        await files.async_write(hass, FILE, WHAT, [])
        and hass.is_running
        and ALERT2 in hass.config.components
    ):
        await _async_reload(hass)
    ir.async_delete_issue(hass, DOMAIN, ISSUE)
```

(`Mapping` stays used by `alert`.)

- [ ] **Step 4: Add the issue's translations**

In `custom_components/pururu/translations/en.json`, inside `"issues"`, after `automations_not_included`'s block (add a comma after its closing brace):

```json
    "alert2_not_included": {
      "title": "Alert2 doesn't run pururu's alerts",
      "description": "pururu writes an Alert2 alert for each alert with `notify` to `{file}`, but Alert2 hasn't loaded them. Add this line to the `alert2:` block of `configuration.yaml`, as its `alerts`:\n\n`{include}`\n\nThen reload Alert2 in **Developer tools → YAML → Alert2**, or restart Home Assistant. If Alert2's generator for pururu is still there, remove it."
    }
```

In `pt-BR.json`, same place:

```json
    "alert2_not_included": {
      "title": "O Alert2 não roda os alertas do pururu",
      "description": "O pururu escreve um alerta do Alert2 para cada alerta com `notify` em `{file}`, mas o Alert2 não os carregou. Adicione esta linha ao bloco `alert2:` do `configuration.yaml`, como os seus `alerts`:\n\n`{include}`\n\nDepois recarregue o Alert2 em **Ferramentas de desenvolvedor → YAML → Alert2**, ou reinicie o Home Assistant. Se o generator do Alert2 para o pururu ainda estiver lá, remova-o."
    }
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_alert2.py tests/test_alerts.py tests/test_reactions.py -n 0 -q`
Expected: all PASS.

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu && uv run mypy custom_components/pururu`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add custom_components/pururu tests/test_alert2.py
git commit -m "pururu: reload Alert2, and a repair while its include is missing

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Docs, the generator's tests, release

**Files:**
- Modify: `docs/features/alerts.mdx` (section `## Getting notified`)
- Modify: `docs/reference/troubleshooting.mdx`
- Modify: `docs/develop/architecture.mdx` (step 6, add step for Alert2)
- Modify: `CLAUDE.md` (Architecture, `async_setup_entry` steps)
- Modify: `tests/test_alerts.py` (generator tests go), `tests/test_alert2.py` (docs test)
- Modify: `custom_components/pururu/manifest.json` (`0.1.12`)

**Interfaces:**
- Consumes: `alert2_alerts.INCLUDE`, `FILE` (Tasks 2–3).

- [ ] **Step 1: Write the docs test**

Append to `tests/test_alert2.py` (add `import re`):

```python
# --- the docs ----------------------------------------------------------------------------

ALERTS_PAGE = Path(__file__).resolve().parents[1] / "docs/features/alerts.mdx"


def test_the_documented_include_is_the_one_pururu_asks_for(ha: HomeAssistant) -> None:
    block = re.search(r"```yaml[^\n]*\n(alert2:\n.*?)```", ALERTS_PAGE.read_text(), re.DOTALL)
    assert block is not None, "no alert2: block on the alerts page"
    assert f"  {module('alert2_alerts').INCLUDE}\n" in block[1]
    assert "generator" not in block[1]
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_alert2.py -n 0 -q -k documented`
Expected: FAIL (the page still shows the generator).

- [ ] **Step 3: Rewrite "Getting notified" in `docs/features/alerts.mdx`**

Replace the paragraph under the example at the top that says "[Alert2] does the telling (phones, reminders, acknowledging): see [Getting notified](#getting-notified)." — keep it. Replace everything from `## Getting notified` up to (not including) `**Without \`notify\`**` with:

````mdx
## Getting notified

pururu sends nothing itself. [Alert2](https://github.com/redstone99/hass-alert2) delivers the alerts that have `notify`. pururu writes an Alert2 alert for each of them to `pururu/alert2/alerts.yaml`, next to `configuration.yaml`, and Alert2 reads that folder through **one line** you add once, as the `alerts` of your `alert2:` block:

```yaml title="configuration.yaml"
alert2:
  defaults:
    notifier: mobile_app_phone         # who is told
    reminder_frequency_mins: [8, 20]   # while the problem lasts
  alerts: !include_dir_merge_list pururu/alert2
```

Then restart Home Assistant, or reload Alert2 in **Developer tools → YAML → Alert2**. From then on pururu reloads Alert2 itself whenever its alerts change: adding or removing `notify`, a new alert, a changed message.

For the `long_cycle` alert above, pururu writes:

```yaml
- domain: pururu
  name: clothes_washer_alert_long_cycle
  friendly_name: Tanquinho Ciclo longo
  condition_on: "{{ is_state('binary_sensor.pururu_clothes_washer_alert_long_cycle', 'on') }}"
  condition_off: "{{ is_state('binary_sensor.pururu_clothes_washer_alert_long_cycle', 'off') }}"
  priority: medium
  message: A máquina passou de 3 horas ligada!
  done_message: A máquina terminou.
```

- **What each alert says** comes from its `notify`. **How** it's told is the same for every alert, in Alert2's `defaults`: who is told, reminders, acknowledging. See Alert2's documentation.
- Each Alert2 alert is named after the rest of the pururu alert's ID: `binary_sensor.pururu_clothes_washer_alert_long_cycle` becomes `alert2.pururu_clothes_washer_alert_long_cycle`, even after you rename the pururu alert.
- Only the alerts with `notify` are written, and only those that are created.
- A message or name with `{` is shown as you wrote it, not as a template.
- `condition_on` and `condition_off`, rather than one `condition`, keep the Alert2 alert as it is while the pururu alert is briefly `unavailable`, as during a pururu reload.
- Until the line is there, **Settings → Repairs** shows **Alert2 doesn't run pururu's alerts**, with the line to add. See [Troubleshooting](/reference/troubleshooting#alert2-doesnt-run-pururus-alerts).
- If an alert has `notify` and Alert2 isn't set up once Home Assistant has started, the log says so: `binary_sensor.pururu_clothes_washer_alert_long_cycle has notify, but Alert2 isn't set up to deliver it`. The alert still works as a binary sensor.

<Warning>
  `alerts:` is the include alone: a YAML list can't be both written out and included. Create **your own** Alert2 alerts in Alert2's UI instead. Don't put files in `pururu/alert2` and don't edit `alerts.yaml`: the include loads every file there, and pururu rewrites it whenever the configuration changes.
</Warning>

### Coming from the generator

pururu 0.1.11 and earlier asked for a `generator` in Alert2's `alerts`. Replace it with the line above. The alerts keep their Alert2 entities, history and acknowledgements: they have the same names. Kept next to the include, the generator declares every alert twice, and Alert2 reports `Duplicate declaration of alert for domain=pururu`.

````

- [ ] **Step 4: Update `docs/reference/troubleshooting.mdx`**

In the `### \`… has notify, but Alert2 isn't set up to deliver it\`` section, replace the fix line:

```
**Fix:** install Alert2 and add pururu's generator, or remove `notify` from the alert.
```

with

```
**Fix:** install Alert2 and add [the include](/features/alerts#getting-notified) to its `alert2:` block, or remove `notify` from the alert.
```

Right after that section (before `### \`… is a pururu switch (or light)…`), add:

````mdx
### Alert2 doesn't run pururu's alerts

**Settings → Repairs** shows it, and the log says:

```
Alert2 doesn't run pururu's alerts: add "alerts: !include_dir_merge_list pururu/alert2" to the alert2: block of configuration.yaml
```

**Fix:** add that line as the `alerts` of your `alert2:` block, then reload Alert2 in **Developer tools → YAML → Alert2**. See [Getting notified](/features/alerts#getting-notified).

### `Duplicate declaration of alert for domain=pururu …`

Alert2 reports it when its old pururu `generator` is still in its `alerts` next to the include. **Fix:** remove the generator. See [Coming from the generator](/features/alerts#coming-from-the-generator).

### `Alert2 is not reloaded: …`

pururu couldn't reload Alert2. The alerts keep working as binary sensors; Alert2 keeps what it had. pururu tries again at its next reload.

### `The Alert2 alerts are not written to pururu/alert2/alerts.yaml: …`

pururu couldn't write the file, usually because of permissions on the configuration folder. Alert2 keeps the last written alerts.
````

- [ ] **Step 5: Update `docs/develop/architecture.mdx` and `CLAUDE.md`**

In `docs/develop/architecture.mdx`, after the item `6. **Generate the reactions' automations** …` insert a new item, and renumber the following one (`7.` → `8.`):

```mdx
7. **Write Alert2's alerts** (`alert2_alerts.py`): each created alert with `notify` becomes an Alert2 condition alert (`domain: pururu`, named after its object ID, conditions on its current entity ID, text with `{` wrapped in `{% raw %}`) in `pururu/alert2/alerts.yaml`, which the user's `alert2:` block includes as its `alerts` (`!include_dir_merge_list pururu/alert2`). Once HA has started, in an entry task, Alert2 is reloaded when the file changed or Alert2 doesn't run an alert it holds (a restored placeholder doesn't count, a disabled one isn't missing), and a Repairs issue says when the include is missing. Nothing is tracked in `entry.data`: Alert2 drops what its config no longer has. The file writer is shared with the reactions (`files.py`).
```

(The inline code keeps the `{` safe in MDX.)

In `CLAUDE.md`, in the `async_setup_entry` list, insert after step 6 (reactions):

```markdown
    7. Write Alert2's alerts (`alert2_alerts.py`): `pururu/alert2/alerts.yaml`, one condition alert per created alert with `notify`, which the user's `alert2:` block includes as its `alerts` (`!include_dir_merge_list pururu/alert2`); Alert2 reloaded when it changed or doesn't run an alert of it, in an entry task, a Repairs issue while it isn't included. The writer is shared with reactions (`files.py`).
```

and renumber `7. Show the dashboard` to `8.`.

- [ ] **Step 6: Remove the generator's tests from `tests/test_alerts.py`**

Delete the section `# --- the Alert2 generator of the docs ---` entirely: `ALERTS_PAGE`, `documented_generator`, `entity_regex`, `generated`, `rendered`, `test_the_documented_generator_picks_the_alerts_with_notify`, `test_the_documented_generator_leaves_an_unavailable_alert_as_it_is`. Remove the imports only they used: `ast`, `Iterable`, `Iterator`, `Path`, `re`, `State`, `Template`, `yaml` (check each with `grep -n` in the file before removing). Change the docstring of `test_without_notify_there_are_no_texts` to `"""Only an alert with notify carries what to tell."""`.

- [ ] **Step 7: Bump the version**

In `custom_components/pururu/manifest.json`: `"version": "0.1.11"` → `"version": "0.1.12"`.

- [ ] **Step 8: Run everything**

Run: `uv run pytest`
Expected: all PASS (includes ruff, format, mypy, hassfest, quality scale).

Run: `python3 release.py check`
Expected: OK.

Run: `pnpm install && pnpm docs:check`
Expected: no broken links (the anchors `#getting-notified`, `#coming-from-the-generator`, `#alert2-doesnt-run-pururus-alerts` must resolve; fix the anchor if docs.page slugs the apostrophe differently).

- [ ] **Step 9: Commit**

```bash
git add docs CLAUDE.md tests custom_components/pururu/manifest.json
git commit -m "pururu: docs for Alert2's alerts, the generator gone (0.1.12)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
