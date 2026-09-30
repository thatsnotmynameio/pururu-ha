# Programs as Scripts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** pururu writes each program as a real Home Assistant script in a generated file, as it already writes reactions as automations, and the in-memory `button` goes.

**Architecture:** The generated-file machinery leaves `reactions.py` for a new `generated.py`, parametrised by a `Kind` per HA domain (`automation`, `script`). `reactions.py` and a new root `programs.py` keep only their schema and translation to HA's syntax; `programs` stops being a `Feature` and becomes a device key, as `reactions`.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3 (`script` and `automation` integrations, entity/area/issue registries), voluptuous, pytest with `pytest-homeassistant-custom-component`, uv.

**Spec:** `docs/superpowers/specs/2026-09-27-programs-as-scripts-design.md`

## Global Constraints

- Every command runs from the repo root with `uv run` (see `CLAUDE.md`); single-process test runs use `-n 0`.
- ruff, ruff format and mypy (strict) must pass on `custom_components/pururu`; `uv run pytest` runs them (`tests/test_code.py`).
- A program's script ID: `pururu_<device key>_program_<program key>`; entity ID `script.<that>`.
- Generated file: `pururu/scripts/programs.yaml`; include line: `script pururu: !include_dir_merge_named pururu/scripts`.
- Reactions' file and include stay: `pururu/automations/reactions.yaml`, `automation pururu: !include_dir_merge_list pururu/automations`.
- Entry data keys: `automations` (unchanged), `scripts` (new).
- Repairs issues: `automations_not_included` (unchanged), `scripts_not_included` (new).
- Every existing automations log message keeps its exact text.
- Version: `0.1.12` in `custom_components/pururu/manifest.json`.
- Never leave the shell's cwd inside `.venv/.../homeassistant/helpers/`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- **A target disabled, then enabled, while a reaction's automation starts the program:** the script disappears and comes back after HA's 30 s entry reload; nothing is left half-registered (the registry entry of the dropped script goes once HA stops running it). Pinned in Task 2 (`test_a_disabled_target_drops_the_program`, `test_it_comes_back_when_the_target_is_enabled`).
- **The Repairs warning while the include is missing:** now checked on every `state_changed` of the domain, it must be logged once, not at every automation trigger. Pinned in Task 1 (`test_the_warning_is_logged_once_while_the_issue_is_open`) and again per kind in Task 3.
- **A user who renamed the script in the UI:** a pururu reload must keep the renamed entity ID and not create `script.pururu_…` again. Pinned in Task 2 (`test_renamed_it_still_runs_and_stays_renamed`).
- **Upgrading from 0.1.11 with a program button in the registry:** the button is removed at first setup. Pinned in Task 2 (`test_the_old_button_is_removed`).
- **Two devices whose programs would share a script ID:** refused at validation with a clear message, as reactions. Pinned in Task 2 (`test_two_programs_with_one_script_id_are_refused`).

---

## File Structure

- Create `custom_components/pururu/generated.py`: `Kind`, `Item`, `period`, `async_sync`, `async_remove` and their private helpers, for any domain.
- Modify `custom_components/pururu/reactions.py`: keeps schema, checks, `automation_id`, `triggers`, `automation`; gains `KIND`.
- Create `custom_components/pururu/programs.py`: schema, `targets`, `script_id`, `script`, `KIND`.
- Delete `custom_components/pururu/concepts/programs.py`, `custom_components/pururu/button.py`.
- Modify `custom_components/pururu/__init__.py`, `const.py`, `feature.py`, `features/__init__.py`, `translations/en.json`, `translations/pt-BR.json`, `manifest.json`, `sonar-project.properties`.
- Tests: create `tests/test_generated.py`; rewrite `tests/test_programs.py`; trim `tests/test_reactions.py`; modify `tests/helpers.py`, `tests/test_features.py`, `tests/test_places.py`.
- Docs: move `docs/concepts/programs.mdx` to `docs/concepts/programs.mdx`; update `docs.json`, `CLAUDE.md` and the pages listed in Task 4.

---

### Task 1: `generated.py`, for the reactions' automations

Move the machinery out of `reactions.py`, generalised by `Kind`, with three changes: an item "runs" when its registry entity has a non-restored state (not by the `id` attribute), the include is checked again at the end of every `_finish` and on `state_changed` of the domain once HA has started (instead of `automation_reloaded`), and the warning is logged only when the issue is raised. `async_sync` also stores the tracked IDs in the entry. Areas are supported (`Item.area`) but reactions pass none.

**Files:**
- Create: `custom_components/pururu/generated.py`
- Modify: `custom_components/pururu/reactions.py` (imports, constants at lines 1-60; delete lines 122-131 `_period` and 183-404)
- Modify: `custom_components/pururu/__init__.py` (import at line 35, `async_setup_entry` lines 350-358, `async_remove_entry` lines 382-385, `_automations` lines 554-580)
- Modify: `sonar-project.properties` (the `reactions_failure` resourceKey)
- Test: `tests/test_reactions.py`

**Interfaces:**
- Produces:
  - `generated.Kind(*, domain: str, folder: str, file: str, merge: str, issue: str, data_key: str, one: str, plural: str, source: str)`, frozen; property `include -> str`.
  - `generated.Item(*, unique_id: str, config: Mapping[str, Any], area: str | None = None)`, frozen.
  - `generated.period(value: timedelta) -> str`.
  - `async generated.async_sync(hass, entry, kind: Kind, items: list[Item]) -> None` (writes `entry.data[kind.data_key]`).
  - `async generated.async_remove(hass, entry, kind: Kind) -> None`.
  - `reactions.KIND: Kind`.

- [ ] **Step 1: Write the failing test**

In `tests/test_reactions.py`, add after `test_without_the_include_an_issue_says_what_to_add`:

```python
async def test_the_warning_is_logged_once_while_the_issue_is_open(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """The include is checked at every automation's state change: the log says it once."""
    with patch("homeassistant.config.load_yaml_config_file",
               side_effect=lambda *_args, **_kwargs: {}):
        assert await async_setup_component(ha, "automation", {})
        assert await setup(ha, devices(door=DOOR_OPENS))
    ha.states.async_set("automation.mine", "on")
    ha.states.async_set("automation.mine", "off")
    await ha.async_block_till_done()
    assert issue(ha) is not None
    warned = [r for r in caplog.records if "are not loaded: add" in r.getMessage()]
    assert len(warned) == 1
```

Also change the four `patch.object(reactions, "write_utf8_file_atomic", …)` in `test_a_failed_write_is_logged_and_the_setup_goes_on`, `test_a_failed_write_drops_nothing_stale`, `test_a_failed_write_raises_no_include_issue` and `test_a_failed_removal_keeps_the_automations_ids` to patch the new module: replace each `reactions = module("reactions")` there with `generated = module("generated")` and `patch.object(reactions, …)` with `patch.object(generated, …)`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_reactions.py -n 0 -q`
Expected: FAIL: `ModuleNotFoundError: No module named 'custom_components.pururu.generated'` in the four patched tests.

- [ ] **Step 3: Write `generated.py`**

```python
"""What pururu writes for Home Assistant to run: automations and scripts, a file per kind.

Each kind is a file in a folder that configuration.yaml includes once, under
HA's own domain: HA loads it, runs it and shows it (traces, on/off, its list).
pururu gives each item the pururu entity ID, drops what the configuration no
longer has once HA no longer runs it, and raises a Repairs issue while HA
doesn't load what the file holds.
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
import logging
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_RESTORED, EVENT_STATE_CHANGED, SERVICE_RELOAD
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
    split_entity_id,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.util.file import write_utf8_file_atomic
from homeassistant.util.yaml import dump

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

HEADER = (
    "# Generated by pururu from its configuration. "
    "Don't edit: it is rewritten on every reload.\n"
)


@dataclass(frozen=True, kw_only=True)
class Kind:
    """An HA domain pururu generates items of: where they go, how HA includes them."""

    # HA's domain, and the platform of its items' registry entries
    domain: str
    # Relative to HA's configuration folder, as configuration.yaml's include names them
    folder: str
    file: str
    # How the include merges the folder, and so how the file is dumped: "list"
    # (automations, each with its id) or "named" (scripts, object ID -> script)
    merge: str
    # The Repairs issue while an item isn't loaded, and its translation key
    issue: str
    # The key of the entry's data holding the IDs of the items it tracks
    data_key: str
    # Words of the log messages: "an automation", "automations", "reactions"
    one: str
    plural: str
    source: str

    @property
    def include(self) -> str:
        """configuration.yaml's line for the folder.

        A folder, not the file: a missing folder loads as nothing, while a plain
        include of a missing file stops HA from loading its configuration.
        """
        return f"{self.domain} pururu: !include_dir_merge_{self.merge} {self.folder}"


@dataclass(frozen=True, kw_only=True)
class Item:
    """A generated item: its ID (its entity ID's object ID too), its HA config, its area."""

    unique_id: str
    config: Mapping[str, Any]
    # The area its registry entry goes in; None leaves it where it is
    area: str | None = None


def period(value: timedelta) -> str:
    """A time period as HA reads it: [-]HH:MM:SS, and the fraction of a second if any."""
    sign = "-" if value < timedelta(0) else ""
    minutes, seconds = divmod(abs(value), timedelta(minutes=1))
    hours, minutes = divmod(minutes, 60)
    text = f"{sign}{hours:02}:{minutes:02}:{seconds.seconds:02}"
    if seconds.microseconds:
        text += f".{seconds.microseconds:06}"
    return text


def _content(kind: Kind, items: Iterable[Item]) -> str:
    """The file: the header, then the items as the include merges them."""
    if kind.merge == "list":
        return HEADER + dump([dict(item.config) for item in items])
    return HEADER + dump({item.unique_id: dict(item.config) for item in items})


def _write(path: Path, content: str) -> bool:
    """Write `content` unless the file already holds it; whether it wrote.

    Bytes are compared: a file saved in another encoding is rewritten, not an error.
    """
    if path.is_file() and path.read_bytes() == content.encode("utf-8"):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    write_utf8_file_atomic(str(path), content)
    return True


def _free(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    kind: Kind,
    unique_id: str,
    managed: Collection[str],
) -> bool:
    """Whether <domain>.<ID> is free, or already this item's; the holder logged.

    An item with this ID is this one only if the entry manages it: else it is
    someone's own, which keeps its ID and what it does.
    """
    entity_id = f"{kind.domain}.{unique_id}"
    if (
        same := registry.async_get_entity_id(kind.domain, kind.domain, unique_id)
    ) is not None:
        if unique_id in managed:
            return True
        holder = f"{same}, {kind.one} with the same ID"
    elif (registered := registry.async_get(entity_id)) is not None:
        holder = f"the {registered.platform} integration"
    elif (state := hass.states.get(entity_id)) is not None and not state.attributes.get(
        ATTR_RESTORED
    ):
        holder = "an entity without a unique ID"
    else:
        return True
    _LOGGER.error("%s is already taken by %s; not generating it", entity_id, holder)
    return False


def _register(
    hass: HomeAssistant, registry: er.EntityRegistry, kind: Kind, item: Item
) -> None:
    """Register the item's entity ID before HA loads it, so it gets the pururu one; place it.

    HA would derive an automation's from its alias. An area that isn't created
    is left out: the device's placement already logs it.
    """
    registered = registry.async_get_or_create(
        kind.domain, kind.domain, item.unique_id, suggested_object_id=item.unique_id
    )
    if (
        item.area is not None
        and registered.area_id != item.area
        and ar.async_get(hass).async_get_area(item.area) is not None
    ):
        registry.async_update_entity(registered.entity_id, area_id=item.area)


def _remove(registry: er.EntityRegistry, kind: Kind, unique_ids: Iterable[str]) -> None:
    """Remove the entity registry entries of these items, by their IDs."""
    for unique_id in unique_ids:
        entity_id = registry.async_get_entity_id(kind.domain, kind.domain, unique_id)
        if entity_id is not None:
            registry.async_remove(entity_id)


async def _async_write(
    hass: HomeAssistant, kind: Kind, items: list[Item]
) -> bool | None:
    """Write the file if it changed; whether it did, or None on failure.

    A failure is logged, never raised: the caller must tell "unchanged" (False)
    from "failed" (None), since a failed write must drop nothing stale.
    """
    content = _content(kind, items)
    try:
        return await hass.async_add_executor_job(
            _write, Path(hass.config.path(kind.file)), content
        )
    except (OSError, HomeAssistantError) as err:
        _LOGGER.error("The %s are not written to %s: %s", kind.plural, kind.file, err)
        return None


async def _async_reload(hass: HomeAssistant, kind: Kind) -> bool:
    """Reload HA's domain, if HA has it; whether it did. A failure is logged, never raised."""
    if kind.domain not in hass.config.components:
        return False
    try:
        await hass.services.async_call(kind.domain, SERVICE_RELOAD, blocking=True)
    except HomeAssistantError as err:
        _LOGGER.error("The %s are not reloaded: %s", kind.plural, err)
        return False
    return True


@callback
def _runs(
    hass: HomeAssistant, registry: er.EntityRegistry, kind: Kind, unique_id: str
) -> bool:
    """Whether HA runs the item: its entity has a state, and not a restored placeholder.

    One HA doesn't run but has registered gets a restored placeholder at start.
    """
    entity_id = registry.async_get_entity_id(kind.domain, kind.domain, unique_id)
    state = hass.states.get(entity_id) if entity_id is not None else None
    return state is not None and not state.attributes.get(ATTR_RESTORED)


@callback
def _missing(
    hass: HomeAssistant, registry: er.EntityRegistry, kind: Kind, ids: Iterable[str]
) -> list[str]:
    """The generated items HA doesn't run; a disabled one never runs, and isn't missing."""
    missing = []
    for unique_id in ids:
        entity_id = registry.async_get_entity_id(kind.domain, kind.domain, unique_id)
        registered = registry.async_get(entity_id) if entity_id is not None else None
        if not _runs(hass, registry, kind, unique_id) and (
            registered is None or registered.disabled_by is None
        ):
            missing.append(unique_id)
    return missing


@callback
def _check_included(
    hass: HomeAssistant, registry: er.EntityRegistry, kind: Kind, ids: Iterable[str]
) -> None:
    """Raise the Repairs issue while a generated item isn't loaded, else delete it.

    The warning is logged when the issue is raised: this runs at every state
    change of the domain.
    """
    if not _missing(hass, registry, kind, ids):
        ir.async_delete_issue(hass, DOMAIN, kind.issue)
        return
    if ir.async_get(hass).async_get_issue(DOMAIN, kind.issue) is None:
        _LOGGER.warning(
            'The %s of pururu\'s %s are not loaded: add "%s" to configuration.yaml',
            kind.plural,
            kind.source,
            kind.include,
        )
    ir.async_create_issue(
        hass,
        DOMAIN,
        kind.issue,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=kind.issue,
        translation_placeholders={"include": kind.include, "file": kind.file},
    )


async def _finish(
    hass: HomeAssistant,
    entry: ConfigEntry,
    kind: Kind,
    changed: bool,
    ids: list[str],
    stale: set[str],
    checked: list[str],
) -> None:
    """Once HA has started: apply the file, drop what HA no longer runs, check the include.

    HA reloads when the file changed, and also when it doesn't run the file as
    written (a reload that failed, the include added since): the reload is
    retried. A dropped item HA still runs keeps its entity ID, and stays
    tracked, until a reload drops it. The reload is blocking: the include is
    checked on what it loaded.
    """
    registry = er.async_get(hass)
    if (
        changed
        or _missing(hass, registry, kind, checked)
        or any(_runs(hass, registry, kind, unique_id) for unique_id in stale)
    ):
        await _async_reload(hass, kind)
    running = {
        unique_id for unique_id in stale if _runs(hass, registry, kind, unique_id)
    }
    _remove(registry, kind, stale - running)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, kind.data_key: [*ids, *sorted(running)]}
    )
    _check_included(hass, registry, kind, checked)


async def async_sync(
    hass: HomeAssistant, entry: ConfigEntry, kind: Kind, items: list[Item]
) -> None:
    """Generate the items, and keep in the entry the IDs it tracks.

    Each entity ID is registered first. At start, HA has already loaded the
    file; the rest waits for HA to have started, in a task the entry's unload
    waits for, so a reload never overlaps the previous one. The tracked IDs are
    the generated ones and the dropped ones still registered: their entries go
    once HA no longer runs them. After a failed write, the file is the previous
    one: only what it holds is checked for the include. Once HA has started, a
    state change of the domain (a user's own reload) checks the include again.
    """
    registry = er.async_get(hass)
    previous = entry.data.get(kind.data_key, [])
    kept = [
        item
        for item in items
        if _free(hass, registry, kind, item.unique_id, previous)
    ]
    for item in kept:
        _register(hass, registry, kind, item)
    ids = [item.unique_id for item in kept]
    written = await _async_write(hass, kind, kept)
    stale = {
        unique_id
        for unique_id in previous
        if unique_id not in ids
        and registry.async_get_entity_id(kind.domain, kind.domain, unique_id)
        is not None
    }
    checked = ids if written is not None else [i for i in ids if i in previous]
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, kind.data_key: [*ids, *sorted(stale)]}
    )

    @callback
    def of_kind(data: EventStateChangedData) -> bool:
        return split_entity_id(data["entity_id"])[0] == kind.domain

    @callback
    def changed(_event: Event[EventStateChangedData]) -> None:
        _check_included(hass, registry, kind, checked)

    @callback
    def finish(_hass: HomeAssistant) -> None:
        entry.async_create_task(
            hass,
            _finish(hass, entry, kind, bool(written), ids, stale, checked),
            f"pururu {kind.plural}",
            eager_start=False,
        )
        entry.async_on_unload(
            hass.bus.async_listen(EVENT_STATE_CHANGED, changed, event_filter=of_kind)
        )

    entry.async_on_unload(async_at_started(hass, finish))


async def async_remove(hass: HomeAssistant, entry: ConfigEntry, kind: Kind) -> None:
    """Generate nothing: an empty file, still valid for the include.

    An item HA still runs (the file couldn't be written, or the reload failed)
    keeps its entity ID.
    """
    if await _async_write(hass, kind, []) and hass.is_running:
        await _async_reload(hass, kind)
    registry = er.async_get(hass)
    _remove(
        registry,
        kind,
        [
            unique_id
            for unique_id in entry.data.get(kind.data_key, [])
            if not _runs(hass, registry, kind, unique_id)
        ],
    )
    ir.async_delete_issue(hass, DOMAIN, kind.issue)
```

- [ ] **Step 4: Trim `reactions.py`**

Replace lines 1-60 (docstring, imports, constants up to `EVENT_AUTOMATION_RELOADED`) with:

```python
"""Reactions: what a device listens to, as Home Assistant automations pururu generates.

A reaction is one source (an entity of a device, a real entity, a time of day,
the sun) and, for an entity, a condition. Each becomes an automation in
pururu/automations/reactions.yaml, whose folder configuration.yaml includes
(generated.py). It has no actions yet: it fires, and its trace shows when and why.
"""

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_NAME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import config_validation as cv

from .const import CONF_AUTOMATIONS, ENTITY_PREFIX
from .feature import TEXT, finite_float, qualified, state_text
from .generated import Kind, period

# The namespace of every reaction's automation ID
NAMESPACE = "reaction"
SOURCES = ("when", "entity", "at", "sun")
# Keys that only a reaction on an entity's state takes
STATE_KEYS = ("to", "from", "above", "below", "for")
KIND = Kind(
    domain="automation",
    folder="pururu/automations",
    file="pururu/automations/reactions.yaml",
    merge="list",
    issue="automations_not_included",
    data_key=CONF_AUTOMATIONS,
    one="an automation",
    plural="automations",
    source="reactions",
)
```

Delete `_period` (lines 122-131) and, in `triggers`, replace both `_period(` calls with `period(`. Delete everything from `def _write(` to the end of the file (lines 183-404).

- [ ] **Step 5: Use it in `__init__.py`**

Line 35: `from . import dashboard, generated, places, reactions`. Remove `CONF_AUTOMATIONS` from the `.const` import.

In `async_setup_entry`, replace

```python
    generated = await reactions.async_sync(
        hass, entry, _automations(hass, devices, created)
    )
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_AUTOMATIONS: generated}
    )
```

with

```python
    await generated.async_sync(
        hass, entry, reactions.KIND, _automations(hass, devices, created)
    )
```

In `async_remove_entry`, replace `await reactions.async_remove(hass, entry)` with `await generated.async_remove(hass, entry, reactions.KIND)`.

In `_automations`, change the return type to `list[generated.Item]`, the local to `automations: list[generated.Item] = []`, and the append to:

```python
            automations.append(
                generated.Item(
                    unique_id=reactions.automation_id(key, reaction_key),
                    config=reactions.automation(
                        key, config[CONF_NAME], reaction_key, reaction, entity_id
                    ),
                )
            )
```

- [ ] **Step 6: Sonar**

In `sonar-project.properties`, change `sonar.issue.ignore.multicriteria.reactions_failure.resourceKey=custom_components/pururu/reactions.py` to `…/generated.py`, and its comment's first line to `# The same for a generated file that can't be written (OSError: permissions,` and `automations or scripts that can't be reloaded (HomeAssistantError): an`.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_reactions.py -n 0 -q`
Expected: PASS, including `test_the_warning_is_logged_once_while_the_issue_is_open` and `test_the_issue_goes_once_the_include_is_there` (now via `state_changed`).

Run: `uv run pytest`
Expected: PASS (ruff, format, mypy included). Fix any formatting with `uv run ruff format custom_components/pururu`.

- [ ] **Step 8: Commit**

```bash
git add custom_components/pururu/generated.py custom_components/pururu/reactions.py custom_components/pururu/__init__.py sonar-project.properties tests/test_reactions.py
git commit -m "pururu: generated.py, the reactions' file machinery for any HA domain

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: programs as scripts

`programs` leaves `FEATURES` for a device key, generating `script.pururu_<device>_program_<key>` through `generated.py`. The button, `button.py`, `Platform.BUTTON` and `Feature.acts` go.

**Files:**
- Create: `custom_components/pururu/programs.py`
- Delete: `custom_components/pururu/concepts/programs.py`, `custom_components/pururu/button.py`
- Modify: `custom_components/pururu/const.py`, `custom_components/pururu/features/__init__.py`, `custom_components/pururu/feature.py:144-150`, `custom_components/pururu/__init__.py`, `custom_components/pururu/translations/en.json`, `custom_components/pururu/translations/pt-BR.json`, `sonar-project.properties`
- Test: `tests/test_programs.py` (rewritten), `tests/helpers.py`, `tests/test_features.py`, `tests/test_places.py`

**Interfaces:**
- Consumes: `generated.Kind`, `generated.Item`, `generated.period`, `generated.async_sync`, `generated.async_remove` (Task 1).
- Produces:
  - `programs.KIND: Kind`, `programs.SCHEMA`, `programs.ACTIONS: tuple[str, ...]`.
  - `programs.targets(program: Mapping[str, Any]) -> Iterator[tuple[str, str]]` (action, entity key).
  - `programs.script_id(device_key: str, program_key: str) -> str`.
  - `programs.script(device_key: str, device_name: str, program_key: str, program: Mapping[str, Any], entity_ids: Mapping[str, str]) -> dict[str, Any]`.
  - `const.CONF_PROGRAMS = "programs"`, `const.CONF_SCRIPTS = "scripts"`.
  - `tests/helpers.py`: `SCRIPTS = "pururu/scripts/programs.yaml"`, `generated_scripts(hass) -> dict[str, Any]`.

- [ ] **Step 1: Test helpers**

In `tests/helpers.py`, after `AUTOMATIONS`:

```python
# The scripts pururu generates, relative to the configuration folder
SCRIPTS = "pururu/scripts/programs.yaml"
```

After `generated`:

```python
def generated_scripts(hass: HomeAssistant) -> dict[str, Any]:
    """The scripts pururu wrote, as configuration.yaml's include reads them."""
    path = Path(hass.config.path(SCRIPTS))
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
```

In `reload`, make the patched configuration include both files:

```python
    # configuration.yaml includes the generated files: automations and scripts reload from them
    with patch("homeassistant.config.load_yaml_config_file",
               side_effect=lambda *_args, **_kwargs: {**config,
                                                      "automation pururu": generated(hass),
                                                      "script pururu": generated_scripts(hass)}):
```

- [ ] **Step 2: Write the failing tests**

Replace `tests/test_programs.py` entirely with:

```python
"""Programs: a made-up greenhouse's cleaning, turning its sprinkler on for two hours, as an HA script."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

from homeassistant.core import Context, Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from helpers import capture, fake, generated_scripts, held, reload, settle, setup, tick

KEY = "greenhouse"
REAL_SPRINKLER = "switch.greenhouse_sprinkler"
SPRINKLER = "switch.pururu_greenhouse_switch_sprinkler"
CLEAN = "script.pururu_greenhouse_program_clean"
SWITCHES: dict[str, Any] = {"sprinkler": {"entity": REAL_SPRINKLER, "name": "Irrigador"}}
TWO_HOURS = 2 * 60 * 60
CLEANING: dict[str, Any] = {"name": "Limpar", "sequence": [
    {"turn_on": "switch_sprinkler"}, {"delay": {"hours": 2}}, {"turn_off": "switch_sprinkler"}]}
APPLIANCE = {"power": "sensor.greenhouse_sprinkler_power",
             "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}}}


def devices(**programs: Any) -> dict[str, Any]:
    return {KEY: {"name": "Estufa", "switches": SWITCHES, "programs": programs or {"clean": CLEANING}}}


def reached(calls: list[Event], entity_id: str = REAL_SPRINKLER) -> list[str]:
    """The services called on `entity_id`, in order."""
    found = []
    for event in calls:
        ids = event.data["service_data"].get("entity_id")
        if ids == entity_id or (isinstance(ids, list) and entity_id in ids):
            found.append(event.data["service"])
    return found


async def start(hass: HomeAssistant, entity_id: str = CLEAN, context: Context | None = None) -> None:
    await hass.services.async_call("script", "turn_on", {"entity_id": entity_id}, blocking=True,
                                   context=context)
    await settle()


@pytest.fixture
async def scripts(ha: HomeAssistant) -> AsyncIterator[HomeAssistant]:
    """HA's scripts, from a configuration.yaml that includes pururu's file."""
    with patch("homeassistant.config.load_yaml_config_file",
               side_effect=lambda *_args, **_kwargs: {"script pururu": generated_scripts(ha)}):
        assert await async_setup_component(ha, "script", {"script pururu": generated_scripts(ha)})
        yield ha


@pytest.fixture
async def greenhouse(scripts: HomeAssistant) -> HomeAssistant:
    await fake(scripts, REAL_SPRINKLER, "off")
    assert await setup(scripts, devices())
    return scripts


# --- schema and the device ---------------------------------------------------------


@pytest.mark.parametrize("program", [
    pytest.param({"name": "Limpar"}, id="no sequence"),
    pytest.param({"name": "Limpar", "sequence": []}, id="empty sequence"),
    pytest.param({"sequence": [{"turn_on": "switch_sprinkler"}]}, id="no name"),
    pytest.param({"name": " ", "sequence": [{"turn_on": "switch_sprinkler"}]}, id="blank name"),
    pytest.param({"name": "Limpar", "sequence": [{"action": "switch.turn_on"}]}, id="an HA action"),
    pytest.param({"name": "Limpar", "sequence": [{"turn_on": "switch_sprinkler", "delay": 5}]},
                 id="two keys in a step"),
    pytest.param({"name": "Limpar", "sequence": [{}]}, id="an empty step"),
    pytest.param({"name": "Limpar", "sequence": ["turn_on"]}, id="a step that isn't a mapping"),
    pytest.param({"name": "Limpar", "sequence": [{"delay": -5}]}, id="a negative delay"),
    pytest.param({"name": "Limpar", "sequence": [{"turn_on": REAL_SPRINKLER}]}, id="a real entity ID"),
    pytest.param({"name": "Limpar", "sequence": [{"turn_on": "switch_sprinkler"}], "icon": "mdi:greenhouse"},
                 id="unknown key"),
])
async def test_invalid_program_is_refused(ha: HomeAssistant, program: dict[str, Any]) -> None:
    assert not await setup(ha, devices(clean=program))


@pytest.mark.parametrize("target", [
    pytest.param("switch_greenhouse_sprinkler", id="not an entity key of the device"),
    pytest.param("switch_heater", id="a switch the device doesn't have"),
    pytest.param("program_clean", id="a program"),
])
async def test_a_target_not_of_another_feature_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, target: str) -> None:
    assert not await setup(ha, devices(clean={"name": "Limpar", "sequence": [{"turn_on": target}]}))
    assert f"programs: {target} is not an entity key of another feature of this device" in caplog.text


async def test_programs_alone_are_not_a_feature(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    assert not await setup(ha, {KEY: {"name": "Estufa", "programs": {"clean": CLEANING}}})
    assert "a device needs at least one feature" in caplog.text


async def test_an_action_the_target_does_not_take_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    program = {"name": "Ligar", "sequence": [{"turn_on": "appliance_power"}]}
    assert not await setup(ha, {KEY: {"name": "Estufa", "appliance": APPLIANCE,
                                      "programs": {"start": program}}})
    assert "programs: appliance_power does not take turn_on" in caplog.text


async def test_two_programs_with_one_script_id_are_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """greenhouse's b_program_c and greenhouse_program_b's c would both be pururu_greenhouse_program_b_program_c."""
    config = devices(b_program_c=CLEANING)
    config["greenhouse_program_b"] = {
        "name": "Outra", "switches": {"x": {"entity": "switch.dummy_x", "name": "X"}},
        "programs": {"c": {"name": "C", "sequence": [{"turn_on": "switch_x"}]}},
    }
    assert not await setup(ha, config)
    assert ("device greenhouse_program_b: script.pururu_greenhouse_program_b_program_c is already "
            "a program of device greenhouse") in caplog.text


# --- the generated script ------------------------------------------------------------


async def test_the_file_holds_a_script_per_program(ha: HomeAssistant) -> None:
    assert await setup(ha, devices())
    assert generated_scripts(ha) == {"pururu_greenhouse_program_clean": {
        "alias": "Estufa Limpar",
        "description": "pururu: greenhouse, clean",
        "mode": "single",
        "sequence": [
            {"action": "switch.turn_on", "target": {"entity_id": SPRINKLER}},
            {"delay": "02:00:00"},
            {"action": "switch.turn_off", "target": {"entity_id": SPRINKLER}},
        ],
    }}
    cv.SCRIPT_SCHEMA(generated_scripts(ha)["pururu_greenhouse_program_clean"]["sequence"])


async def test_it_is_a_script_named_by_the_configuration(greenhouse: HomeAssistant) -> None:
    state = greenhouse.states.get(CLEAN)
    assert state is not None
    assert state.state == "off"
    assert state.attributes["friendly_name"] == "Estufa Limpar"
    entry = er.async_get(greenhouse).async_get(CLEAN)
    assert entry is not None
    assert (entry.platform, entry.unique_id) == ("script", "pururu_greenhouse_program_clean")
    assert held(greenhouse, KEY) == {SPRINKLER}
    assert greenhouse.states.async_entity_ids("button") == []


async def test_it_is_in_its_devices_area(scripts: HomeAssistant) -> None:
    config = devices()
    config[KEY]["area"] = "patio"
    assert await setup(scripts, config, areas={"patio": {"name": "Pátio"}})
    entry = er.async_get(scripts).async_get(CLEAN)
    assert entry is not None
    assert entry.area_id == "patio"


# --- running -------------------------------------------------------------------------


async def test_turning_it_on_runs_the_sequence(greenhouse: HomeAssistant, freezer: Any) -> None:
    calls = capture(greenhouse, "call_service")
    await start(greenhouse)
    assert reached(calls) == ["turn_on"]
    await tick(greenhouse, freezer, TWO_HOURS - 1)
    assert reached(calls) == ["turn_on"]
    await tick(greenhouse, freezer, 1)
    assert reached(calls) == ["turn_on", "turn_off"]


async def test_toggle_flips_the_switch(scripts: HomeAssistant) -> None:
    await fake(scripts, REAL_SPRINKLER, "on")
    assert await setup(scripts, devices(flip={"name": "Inverter", "sequence": [{"toggle": "switch_sprinkler"}]}))
    calls = capture(scripts, "call_service")
    await start(scripts, "script.pururu_greenhouse_program_flip")
    assert reached(calls) == ["turn_off"]


@pytest.mark.parametrize(("real", "attributes"), [
    pytest.param("light.biblioteca_teto", {"supported_color_modes": ["onoff"], "color_mode": "onoff"},
                 id="a real light"),
    pytest.param("switch.sonoff_teto", {}, id="a relay driving a lamp"),
])
async def test_it_turns_a_light_on_and_off(
        scripts: HomeAssistant, freezer: Any, real: str, attributes: dict[str, Any]) -> None:
    await fake(scripts, real, "off", attributes)
    evening = {"name": "Noite", "sequence": [
        {"turn_on": "light_teto"}, {"delay": {"minutes": 30}}, {"turn_off": "light_teto"}]}
    assert await setup(scripts, {"biblioteca": {"name": "Biblioteca",
                                          "lights": {"teto": {"entity": real, "name": "Teto"}},
                                          "programs": {"evening": evening}}})
    calls = capture(scripts, "call_service")
    await start(scripts, "script.pururu_biblioteca_program_evening")
    await tick(scripts, freezer, 30 * 60)
    assert reached(calls, real) == ["turn_on", "turn_off"]


async def test_it_returns_at_once_and_is_on_while_it_runs(greenhouse: HomeAssistant) -> None:
    """As before with the button: an automation starting it doesn't wait two hours."""
    async with asyncio.timeout(5):
        await greenhouse.services.async_call("script", "turn_on", {"entity_id": CLEAN}, blocking=True)
    await settle()
    assert greenhouse.states.get(CLEAN).state == "on"


async def test_turning_it_off_stops_it(greenhouse: HomeAssistant, freezer: Any) -> None:
    calls = capture(greenhouse, "call_service")
    await start(greenhouse)
    await tick(greenhouse, freezer, 60)
    await greenhouse.services.async_call("script", "turn_off", {"entity_id": CLEAN}, blocking=True)
    await settle()
    assert greenhouse.states.get(CLEAN).state == "off"
    await tick(greenhouse, freezer, TWO_HOURS)
    assert reached(calls) == ["turn_on"]


async def test_what_it_does_carries_the_callers_context(greenhouse: HomeAssistant) -> None:
    """The logbook names who started it."""
    calls = capture(greenhouse, "call_service")
    context = Context()
    await start(greenhouse, context=context)
    real = [event for event in calls if reached([event]) == ["turn_on"]]
    assert real
    assert all(context.id in (event.context.id, event.context.parent_id) for event in real)


async def test_starting_it_while_it_runs_is_ignored(
        greenhouse: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    calls = capture(greenhouse, "call_service")
    await start(greenhouse)
    await tick(greenhouse, freezer, 60)
    await start(greenhouse)
    assert "Estufa Limpar: Already running" in caplog.text
    await tick(greenhouse, freezer, TWO_HOURS)
    assert reached(calls) == ["turn_on", "turn_off"]


async def test_an_unavailable_switch_does_not_stop_it(scripts: HomeAssistant, freezer: Any) -> None:
    """No real switch: the pururu switch is unavailable, HA skips it, the program goes on."""
    assert await setup(scripts, devices())
    calls = capture(scripts, "call_service")
    await start(scripts)
    await tick(scripts, freezer, TWO_HOURS)
    assert reached(calls, SPRINKLER) == ["turn_on", "turn_off"]


async def test_a_failing_step_stops_it_and_is_logged(
        greenhouse: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    calls = capture(greenhouse, "call_service")
    with patch("homeassistant.components.group.switch.SwitchGroup.async_turn_on",
               side_effect=HomeAssistantError("the relay is stuck")):
        await start(greenhouse)
    await tick(greenhouse, freezer, TWO_HOURS)
    assert reached(calls, SPRINKLER) == ["turn_on"]
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any("Estufa Limpar" in message and "the relay is stuck" in message
               for message in errors), errors


# --- a disabled target -----------------------------------------------------------------


async def disable(hass: HomeAssistant, entity_id: str, disabled: bool = True) -> None:
    er.async_get(hass).async_update_entity(
        entity_id, disabled_by=er.RegistryEntryDisabler.USER if disabled else None)
    await hass.async_block_till_done()


async def test_a_disabled_target_drops_the_program(
        greenhouse: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    """A script that looks usable and does part of its job would mislead: it goes, logged."""
    await disable(greenhouse, SPRINKLER)
    await tick(greenhouse, freezer, 31)  # HA reloads the entry once an entity of it is disabled
    await greenhouse.async_block_till_done()
    assert generated_scripts(greenhouse) == {}
    assert greenhouse.states.get(CLEAN) is None
    assert er.async_get(greenhouse).async_get(CLEAN) is None
    assert f"{CLEAN} acts on {SPRINKLER}, which is disabled; not generating it" in caplog.text


async def test_it_comes_back_when_the_target_is_enabled(greenhouse: HomeAssistant, freezer: Any) -> None:
    await disable(greenhouse, SPRINKLER)
    await tick(greenhouse, freezer, 31)
    await disable(greenhouse, SPRINKLER, disabled=False)
    await tick(greenhouse, freezer, 31)
    await greenhouse.async_block_till_done()
    calls = capture(greenhouse, "call_service")
    await start(greenhouse)
    assert reached(calls) == ["turn_on"]


# --- reloads, renames, taken IDs, upgrades ------------------------------------------------


async def test_a_reload_keeps_an_unchanged_program_running(greenhouse: HomeAssistant, freezer: Any) -> None:
    calls = capture(greenhouse, "call_service")
    await start(greenhouse)
    await reload(greenhouse, devices())
    await tick(greenhouse, freezer, TWO_HOURS)
    assert reached(calls) == ["turn_on", "turn_off"]


async def test_a_reload_that_changes_the_program_stops_it(greenhouse: HomeAssistant, freezer: Any) -> None:
    """HA loads the new script: what the old one did stays, the sprinkler stays on."""
    longer = {**CLEANING, "sequence": [
        {"turn_on": "switch_sprinkler"}, {"delay": {"hours": 3}}, {"turn_off": "switch_sprinkler"}]}
    calls = capture(greenhouse, "call_service")
    await start(greenhouse)
    await reload(greenhouse, devices(clean=longer))
    await tick(greenhouse, freezer, TWO_HOURS)
    assert reached(calls) == ["turn_on"]
    assert greenhouse.states.get(CLEAN).state == "off"


async def test_a_reload_that_drops_it_removes_it(greenhouse: HomeAssistant) -> None:
    await reload(greenhouse, {KEY: {"name": "Estufa", "switches": SWITCHES}})
    assert generated_scripts(greenhouse) == {}
    assert greenhouse.states.get(CLEAN) is None
    assert er.async_get(greenhouse).async_get(CLEAN) is None
    assert greenhouse.config_entries.async_entries("pururu")[0].data["scripts"] == []


async def test_it_follows_its_target_renamed(greenhouse: HomeAssistant) -> None:
    er.async_get(greenhouse).async_update_entity(SPRINKLER, new_entity_id="switch.estufa_irrigador")
    await greenhouse.async_block_till_done()
    calls = capture(greenhouse, "call_service")
    await start(greenhouse)
    assert reached(calls, "switch.estufa_irrigador") == ["turn_on"]
    assert reached(calls) == ["turn_on"]


async def test_renamed_it_still_runs_and_stays_renamed(greenhouse: HomeAssistant) -> None:
    er.async_get(greenhouse).async_update_entity(CLEAN, new_entity_id="script.limpar_estufa")
    await greenhouse.async_block_till_done()
    calls = capture(greenhouse, "call_service")
    await start(greenhouse, "script.limpar_estufa")
    assert reached(calls) == ["turn_on"]
    await reload(greenhouse, devices())
    renamed = er.async_get(greenhouse).async_get("script.limpar_estufa")
    assert renamed is not None
    assert renamed.unique_id == "pururu_greenhouse_program_clean"
    assert greenhouse.states.get(CLEAN) is None


async def test_an_id_taken_by_another_integration_is_not_generated(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(
        "script", "template", "someone_else", suggested_object_id="pururu_greenhouse_program_clean")
    assert await setup(ha, devices())
    assert generated_scripts(ha) == {}
    assert (f"{CLEAN} is already taken by the template integration; "
            "not generating it") in caplog.text


async def test_a_script_of_ones_own_with_the_same_id_is_not_adopted(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(
        "script", "script", "pururu_greenhouse_program_clean", suggested_object_id="mine")
    assert await setup(ha, devices())
    assert generated_scripts(ha) == {}
    assert (f"{CLEAN} is already taken by script.mine, a script with the same ID; "
            "not generating it") in caplog.text


async def test_a_program_whose_target_is_not_created_is_not_generated(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(
        "switch", "template", "someone_else", suggested_object_id="pururu_greenhouse_switch_sprinkler")
    assert await setup(ha, devices())
    assert generated_scripts(ha) == {}
    assert f"{CLEAN} follows {SPRINKLER}, which is not created; not generating it" in caplog.text


async def test_the_old_button_is_removed(ha: HomeAssistant) -> None:
    """Up to 0.1.11 a program was button.pururu_<device>_program_<key>."""
    entry = MockConfigEntry(domain="pururu", source="import", data={})
    entry.add_to_hass(ha)
    er.async_get(ha).async_get_or_create(
        "button", "pururu", "pururu_greenhouse_program_clean", config_entry=entry,
        suggested_object_id="pururu_greenhouse_program_clean")
    assert await setup(ha, devices())
    assert er.async_get(ha).async_get("button.pururu_greenhouse_program_clean") is None
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_programs.py -n 0 -q`
Expected: FAIL: most tests fail on `generated_scripts(...) == {}` or a missing `script.pururu_greenhouse_program_clean` state (programs still builds buttons).

- [ ] **Step 4: `const.py`**

After `CONF_AUTOMATIONS`:

```python
# A device's programs: each one a script pururu generates
CONF_PROGRAMS: Final = "programs"
# The key of the entry's data holding the IDs of the scripts it generated
CONF_SCRIPTS: Final = "scripts"
```

Remove `Platform.BUTTON,` from `PLATFORMS`.

- [ ] **Step 5: `programs.py`**

Create `custom_components/pururu/programs.py`:

```python
"""Programs: sequences of actions on a device's own entities, as Home Assistant scripts.

A program is a method of its device: something starts it, and it turns the
device's own switches and lights on and off, with delays between. Its steps are
pururu's, translated to HA's script syntax in pururu/scripts/programs.yaml,
whose folder configuration.yaml includes (generated.py); HA runs it. No step
can reach outside the device.
"""

from collections.abc import Iterator, Mapping
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_NAME
from homeassistant.core import split_entity_id
from homeassistant.helpers import config_validation as cv

from .const import CONF_SCRIPTS, ENTITY_PREFIX
from .feature import qualified
from .generated import Kind, period

# The namespace of every program's script ID
NAMESPACE = "program"
DELAY = "delay"
# What a step can do to an entity; the device schema checks its feature takes it
ACTIONS = ("turn_on", "turn_off", "toggle")
KIND = Kind(
    domain="script",
    folder="pururu/scripts",
    file="pururu/scripts/programs.yaml",
    merge="named",
    issue="scripts_not_included",
    data_key=CONF_SCRIPTS,
    one="a script",
    plural="scripts",
    source="programs",
)

STEP = vol.Schema(
    {
        vol.Optional(DELAY): cv.positive_time_period,
        **{vol.Optional(action): cv.slug for action in ACTIONS},
    }
)


def _step(value: Any) -> dict[str, Any]:
    """One of delay, turn_on, turn_off, toggle, with its value: exactly one key."""
    step: dict[str, Any] = STEP(value)
    if len(step) != 1:
        raise vol.Invalid(f"a step is exactly one of {DELAY}, {', '.join(ACTIONS)}")
    return step


PROGRAM = vol.Schema(
    {
        # A blank name would show the program as its device's name alone
        vol.Required(CONF_NAME): vol.All(cv.string, vol.Strip, vol.Length(min=1)),
        vol.Required("sequence"): vol.All([_step], vol.Length(min=1)),
    }
)
# A schema of its own: ALLOW_EXTRA would let a key that isn't a slug through
SCHEMA = vol.All(vol.Schema({cv.slug: PROGRAM}), vol.Length(min=1))


def targets(program: Mapping[str, Any]) -> Iterator[tuple[str, str]]:
    """(action, entity key) of each step that acts on an entity, in order."""
    for step in program["sequence"]:
        yield from ((action, key) for action, key in step.items() if action != DELAY)


def script_id(device_key: str, program_key: str) -> str:
    """The script's object ID, and its unique ID: the pururu pattern."""
    return f"{ENTITY_PREFIX}_{device_key}_{qualified(NAMESPACE, program_key)}"


def _translated(step: Mapping[str, Any], entity_ids: Mapping[str, str]) -> dict[str, Any]:
    """A step in HA's script syntax."""
    ((action, value),) = step.items()
    if action == DELAY:
        return {DELAY: period(value)}
    entity_id = entity_ids[value]
    return {
        "action": f"{split_entity_id(entity_id)[0]}.{action}",
        "target": {"entity_id": entity_id},
    }


def script(
    device_key: str,
    device_name: str,
    program_key: str,
    program: Mapping[str, Any],
    entity_ids: Mapping[str, str],
) -> dict[str, Any]:
    """The script of a program; `entity_ids` maps each entity key it acts on to its current ID.

    single: a start while it runs is ignored, and HA logs it.
    """
    return {
        "alias": f"{device_name} {program[CONF_NAME]}",
        "description": f"pururu: {device_key}, {program_key}",
        "mode": "single",
        "sequence": [_translated(step, entity_ids) for step in program["sequence"]],
    }
```

Delete `custom_components/pururu/concepts/programs.py` and `custom_components/pururu/button.py` (`git rm`). In `features/__init__.py`, remove `from .programs import PROGRAMS` and the `"programs": PROGRAMS,` line.

- [ ] **Step 6: `feature.py`**

Replace lines 144-150:

```python
    # Services its entities take, on their own platform (turn_on → switch.turn_on
    # for a switch): a program can call them
    actions: tuple[str, ...] = ()
    # (action, entity key in its namespace) of every entity its validated block
    # acts on: each entity key is in refers too, and its feature must take the action
    acts: Callable[[Any], Iterable[tuple[str, str]]] | None = None
```

with

```python
    # Services its entities take, on their own platform (turn_on → switch.turn_on
    # for a switch): a program's step can call them (programs.py)
    actions: tuple[str, ...] = ()
```

- [ ] **Step 7: `__init__.py`**

Imports: `from . import dashboard, generated, places, programs, reactions`, and add `CONF_PROGRAMS` to the `.const` import.

In `_device`'s schema, after `vol.Optional(CONF_REACTIONS): reactions.SCHEMA,` add `vol.Optional(CONF_PROGRAMS): programs.SCHEMA,`. After `_reactions_on_this_device(device)` add `_programs_on_this_device(device)`. In `_device`'s docstring, change "that feature takes every action done to it" to "a program's step acts on another feature's entity key that takes the action".

In `_references_resolved`, delete the three lines from `# Every key it acts on is one it refers to: its owner is known` to the `raise` for `does not take`, and shorten its docstring to `"""Refuse a reference that isn't another feature's entity key."""`.

After `_reactions_on_this_device` add:

```python
def _programs_on_this_device(device: dict[str, Any]) -> None:
    """Refuse a step on what isn't a feature's entity key of the device taking its action."""
    owners = {
        qualified(FEATURES[name].namespace, entity_key): name
        for name, entity_key, _ in _entity_keys(device)
    }
    for program in device.get(CONF_PROGRAMS, {}).values():
        for action, key in programs.targets(program):
            if key not in owners:
                raise vol.Invalid(
                    f"programs: {key} is not an entity key of another feature "
                    "of this device"
                )
            if action not in FEATURES[owners[key]].actions:
                raise vol.Invalid(f"programs: {key} does not take {action}")
```

Replace `_reaction_ids_distinct` with:

```python
def _generated_ids_distinct(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse two reactions, or two programs, whose automations or scripts would share an ID.

    Device `lights` with the reaction `b_reaction_c` and device `lights_reaction_b`
    with the reaction `c` would both have pururu_lights_reaction_b_reaction_c.
    """
    blocks = (
        (CONF_REACTIONS, reactions.KIND, reactions.automation_id, "reaction"),
        (CONF_PROGRAMS, programs.KIND, programs.script_id, "program"),
    )
    for block, kind, id_of, what in blocks:
        owners: dict[str, str] = {}  # ID -> the device that has it
        for key, device in config[CONF_DEVICES].items():
            for item_key in device.get(block, {}):
                unique_id = id_of(key, item_key)
                if unique_id in owners:
                    raise vol.Invalid(
                        f"device {key}: {kind.domain}.{unique_id} is already a {what} "
                        f"of device {owners[unique_id]}"
                    )
                owners[unique_id] = key
    return config
```

and in `CONFIG_SCHEMA` replace `_reaction_ids_distinct,` with `_generated_ids_distinct,`.

In `async_setup_entry`, after the reactions' `await generated.async_sync(...)`:

```python
    await generated.async_sync(
        hass, entry, programs.KIND, _scripts(hass, devices, created)
    )
```

Update its docstring: "The reactions' automations and the programs' scripts come after the entities: they watch and act on the ones created."

In `async_remove_entry`, after the reactions' removal: `await generated.async_remove(hass, entry, programs.KIND)`, and its docstring: "…and its reactions' automations and programs' scripts."

After `_automations` add:

```python
def _scripts(
    hass: HomeAssistant, devices: dict[str, dict[str, Any]], created: set[str]
) -> list[generated.Item]:
    """A script per program of every device, in the device's area; one that can't act is logged."""
    registry = er.async_get(hass)
    scripts: list[generated.Item] = []
    for key, config in devices.items():
        referable = _referable(key, config)
        for program_key, program in config.get(CONF_PROGRAMS, {}).items():
            script_id = programs.script_id(key, program_key)
            entity_ids = _acted_on(hass, registry, referable, script_id, program, created)
            if entity_ids is None:
                continue
            scripts.append(
                generated.Item(
                    unique_id=script_id,
                    config=programs.script(
                        key, config[CONF_NAME], program_key, program, entity_ids
                    ),
                    area=config.get(CONF_AREA),
                )
            )
    return scripts


def _acted_on(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    referable: dict[str, tuple[Device, str, Platform]],
    script_id: str,
    program: dict[str, Any],
    created: set[str],
) -> dict[str, str] | None:
    """Each entity key the program acts on -> its current entity ID.

    None, logged, when one isn't there to act on: not created, or disabled (HA
    reloads the entry once it is enabled again).
    """
    entity_ids: dict[str, str] = {}
    for _, key in programs.targets(program):
        owner, entity_key, platform = referable[key]
        entity_id = owner.current_entity_id(hass, platform, entity_key)
        if owner.object_id(entity_key) not in created:
            _LOGGER.error(
                "script.%s follows %s, which is not created; not generating it",
                script_id,
                entity_id,
            )
            return None
        if (registered := registry.async_get(entity_id)) is not None and (
            registered.disabled
        ):
            _LOGGER.error(
                "script.%s acts on %s, which is disabled; not generating it",
                script_id,
                entity_id,
            )
            return None
        entity_ids[key] = entity_id
    return entity_ids
```

- [ ] **Step 8: Translations**

In `translations/en.json` `issues`, after `automations_not_included`:

```json
    "scripts_not_included": {
      "title": "The programs' scripts aren't loaded",
      "description": "pururu writes a script for each program to `{file}`, but Home Assistant hasn't loaded them. Add this line to `configuration.yaml`:\n\n`{include}`\n\nThen reload scripts in **Developer tools → YAML → Scripts**, or restart Home Assistant."
    }
```

In `translations/pt-BR.json`:

```json
    "scripts_not_included": {
      "title": "Os scripts dos programas não estão carregados",
      "description": "O pururu escreve um script para cada programa em `{file}`, mas o Home Assistant não os carregou. Adicione esta linha ao `configuration.yaml`:\n\n`{include}`\n\nDepois recarregue os scripts em **Ferramentas de desenvolvedor → YAML → Scripts**, ou reinicie o Home Assistant."
    }
```

- [ ] **Step 9: Other tests and Sonar**

- `tests/test_features.py`: delete `test_what_a_feature_acts_on_it_refers_to` (the `acts` test); in `test_every_action_is_a_service_of_its_platform`'s docstring write "A program's step calls <platform>.<action> on the entity: the platform must have that service."
- `tests/test_places.py:242` and `:265`: add `"scripts": []` to both expected `entry.data`.
- `sonar-project.properties`: remove `unused_hass_button,async_setup_button,` from the `multicriteria` list, the four `…_button` lines, and `and button.py` from the comment (`switch.py and light.py have their own`).

- [ ] **Step 10: Run the tests**

Run: `uv run pytest tests/test_programs.py tests/test_reactions.py tests/test_features.py tests/test_places.py -n 0 -q`
Expected: PASS.

Run: `uv run pytest`
Expected: PASS, including ruff, mypy, hassfest.

- [ ] **Step 11: Commit**

```bash
git add -A custom_components tests sonar-project.properties
git commit -m "pururu: programs as Home Assistant scripts, the button removed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `tests/test_generated.py`, the machinery's cases for both kinds

Move the generic tests of `tests/test_reactions.py` into a file parametrised over automations and scripts. No production code changes; if a script case fails, the fix goes in `generated.py`.

**Files:**
- Create: `tests/test_generated.py`
- Modify: `tests/test_reactions.py`

**Interfaces:**
- Consumes: `helpers.generated`, `helpers.generated_scripts`, `helpers.reload`, `helpers.restart`, `helpers.setup`, `helpers.capture`, `helpers.module`, `helpers.settle` (Tasks 1-2).

- [ ] **Step 1: Write the tests**

```python
"""generated.py over both kinds: the reactions' automations and the programs' scripts."""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import CoreState, Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util.file import WriteError
from homeassistant.util.yaml import load_yaml_dict
import pytest
import yaml

from helpers import capture, module, reload, restart, settle, setup

LOADER = "homeassistant.config.load_yaml_config_file"
HEADER = "# Generated by pururu from its configuration. Don't edit: it is rewritten on every reload.\n"


@dataclass(frozen=True)
class Case:
    """A kind, and a device generating its items."""

    domain: str
    folder: str
    file: str
    merge: str
    issue: str
    data_key: str
    one: str
    plural: str
    source: str
    empty: Any
    device: str
    namespace: str
    block: str
    feature: dict[str, Any]
    item: dict[str, Any]
    process: str

    @property
    def include_key(self) -> str:
        return f"{self.domain} pururu"

    @property
    def include(self) -> str:
        return f"{self.include_key}: !include_dir_merge_{self.merge} {self.folder}"

    def unique_id(self, key: str) -> str:
        return f"pururu_{self.device}_{self.namespace}_{key}"

    def entity_id(self, key: str) -> str:
        return f"{self.domain}.{self.unique_id(key)}"

    def devices(self, *keys: str) -> dict[str, Any]:
        device: dict[str, Any] = {"name": "Coisa", **self.feature}
        if keys:
            device[self.block] = {key: dict(self.item) for key in keys}
        return {self.device: device}


AUTOMATION = Case(
    domain="automation", folder="pururu/automations", file="pururu/automations/reactions.yaml",
    merge="list", issue="automations_not_included", data_key="automations",
    one="an automation", plural="automations", source="reactions", empty=[],
    device="lights", namespace="reaction", block="reactions",
    feature={"lights": {"teto": {"entity": "light.dummy_teto", "name": "Teto"}}},
    item={"name": "Noite", "at": "22:00"},
    process="homeassistant.components.automation._async_process_config",
)
SCRIPT = Case(
    domain="script", folder="pururu/scripts", file="pururu/scripts/programs.yaml",
    merge="named", issue="scripts_not_included", data_key="scripts",
    one="a script", plural="scripts", source="programs", empty={},
    device="greenhouse", namespace="program", block="programs",
    feature={"switches": {"sprinkler": {"entity": "switch.greenhouse_sprinkler", "name": "Irrigador"}}},
    item={"name": "Limpar", "sequence": [{"turn_on": "switch_sprinkler"}]},
    process="homeassistant.components.script._async_process_config",
)


@pytest.fixture(params=[AUTOMATION, SCRIPT], ids=lambda case: case.domain)
def case(request: pytest.FixtureRequest) -> Case:
    return request.param


def read(ha: HomeAssistant, case: Case) -> Any:
    """The file, as configuration.yaml's include reads it."""
    path = Path(ha.config.path(case.file))
    if not path.is_file():
        return case.empty
    return yaml.safe_load(path.read_text(encoding="utf-8")) or case.empty


def ids(ha: HomeAssistant, case: Case) -> list[str]:
    content = read(ha, case)
    return [item["id"] for item in content] if case.merge == "list" else list(content)


def including(ha: HomeAssistant, case: Case) -> Callable[..., dict[str, Any]]:
    """configuration.yaml, including pururu's file."""
    return lambda *_args, **_kwargs: {case.include_key: read(ha, case)}


def reloads(calls: list[Event], case: Case) -> list[Event]:
    return [event for event in calls
            if (event.data["domain"], event.data["service"]) == (case.domain, "reload")]


def issue(ha: HomeAssistant, case: Case) -> ir.IssueEntry | None:
    return ir.async_get(ha).async_get_issue("pururu", case.issue)


def loaded(ha: HomeAssistant, case: Case, key: str) -> bool:
    """Whether HA runs the item, not a restored placeholder."""
    state = ha.states.get(case.entity_id(key))
    return state is not None and not state.attributes.get("restored")


def entry_data(ha: HomeAssistant, case: Case) -> list[str]:
    return ha.config_entries.async_entries("pururu")[0].data[case.data_key]


@pytest.fixture
async def included(ha: HomeAssistant, case: Case) -> AsyncIterator[None]:
    """HA's domain, from a configuration.yaml that includes pururu's file."""
    with patch(LOADER, side_effect=including(ha, case)):
        assert await async_setup_component(ha, case.domain, {case.include_key: read(ha, case)})
        yield


# --- the file ----------------------------------------------------------------------------


async def test_the_file_has_the_header_and_an_item_per_key(ha: HomeAssistant, case: Case) -> None:
    assert await setup(ha, case.devices("door", "night"))
    assert Path(ha.config.path(case.file)).read_text(encoding="utf-8").startswith(HEADER)
    assert ids(ha, case) == [case.unique_id("door"), case.unique_id("night")]


async def test_without_items_the_file_is_empty(ha: HomeAssistant, case: Case) -> None:
    assert await setup(ha, case.devices())
    assert Path(ha.config.path(case.file)).is_file()
    assert read(ha, case) == case.empty


async def test_the_item_has_the_pururu_entity_id(ha: HomeAssistant, case: Case,
                                                 included: None) -> None:
    assert await setup(ha, case.devices("door"))
    assert loaded(ha, case, "door")
    registered = er.async_get(ha).async_get(case.entity_id("door"))
    assert registered is not None
    assert registered.unique_id == case.unique_id("door")


async def test_an_id_taken_by_another_integration_is_not_generated(
        ha: HomeAssistant, case: Case, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(case.domain, "template", "someone_else",
                                         suggested_object_id=case.unique_id("door"))
    assert await setup(ha, case.devices("door"))
    assert ids(ha, case) == []
    assert (f"{case.entity_id('door')} is already taken by the template integration; "
            "not generating it") in caplog.text
    assert er.async_get(ha).async_get(f"{case.entity_id('door')}_2") is None


async def test_an_item_of_ones_own_with_the_same_id_is_not_adopted(
        ha: HomeAssistant, case: Case, caplog: pytest.LogCaptureFixture) -> None:
    """An item pururu never generated keeps its ID and what it does."""
    er.async_get(ha).async_get_or_create(case.domain, case.domain, case.unique_id("door"),
                                         suggested_object_id="mine")
    assert await setup(ha, case.devices("door"))
    assert ids(ha, case) == []
    assert (f"{case.entity_id('door')} is already taken by {case.domain}.mine, {case.one} "
            "with the same ID; not generating it") in caplog.text


async def test_an_unchanged_file_is_neither_rewritten_nor_reloaded(
        ha: HomeAssistant, case: Case, included: None) -> None:
    assert await setup(ha, case.devices("door"))
    path = Path(ha.config.path(case.file))
    before = path.stat().st_ino
    calls = capture(ha, "call_service")
    await reload(ha, case.devices("door"))
    assert reloads(calls, case) == []
    assert path.stat().st_ino == before


async def test_a_file_in_another_encoding_is_rewritten(ha: HomeAssistant, case: Case) -> None:
    """A file the user saved as Latin-1 is no error: pururu writes its own UTF-8 over it."""
    path = Path(ha.config.path(case.file))
    path.parent.mkdir(parents=True)
    path.write_bytes("# Máquina\n".encode("latin-1"))
    assert await setup(ha, case.devices("door"))
    assert ha.config_entries.async_entries("pururu")[0].state is ConfigEntryState.LOADED
    assert ids(ha, case) == [case.unique_id("door")]


async def test_a_changed_file_reloads_its_domain(ha: HomeAssistant, case: Case,
                                                 included: None) -> None:
    assert await setup(ha, case.devices("door"))
    calls = capture(ha, "call_service")
    await reload(ha, case.devices("door", "night"))
    assert len(reloads(calls, case)) == 1
    assert loaded(ha, case, "night")


async def test_a_dropped_item_leaves_the_file_and_the_registry(
        ha: HomeAssistant, case: Case, included: None) -> None:
    assert await setup(ha, case.devices("door", "night"))
    await reload(ha, case.devices("night"))
    assert ids(ha, case) == [case.unique_id("night")]
    assert er.async_get(ha).async_get(case.entity_id("door")) is None
    assert ha.states.get(case.entity_id("door")) is None
    assert entry_data(ha, case) == [case.unique_id("night")]


# --- the include ---------------------------------------------------------------------------


async def test_the_include_tolerates_a_missing_folder_and_reads_the_file(
        ha: HomeAssistant, case: Case) -> None:
    """Before pururu has written anything, HA still loads its configuration."""
    configuration = Path(ha.config.path("configuration.yaml"))
    configuration.write_text(f"{case.include}\n", encoding="utf-8")
    assert not Path(ha.config.path(case.folder)).exists()
    assert load_yaml_dict(configuration) == {case.include_key: case.empty}
    assert await setup(ha, case.devices("door"))
    assert load_yaml_dict(configuration) == {case.include_key: read(ha, case)}
    assert read(ha, case) != case.empty


async def test_without_the_include_an_issue_says_what_to_add(
        ha: HomeAssistant, case: Case, caplog: pytest.LogCaptureFixture) -> None:
    with patch(LOADER, side_effect=lambda *_args, **_kwargs: {}):
        assert await async_setup_component(ha, case.domain, {})
        assert await setup(ha, case.devices("door"))
    found = issue(ha, case)
    assert found is not None
    assert found.severity == ir.IssueSeverity.WARNING
    assert not found.is_fixable
    assert found.translation_placeholders == {"include": case.include, "file": case.file}
    assert (f"The {case.plural} of pururu's {case.source} are not loaded: "
            f'add "{case.include}" to configuration.yaml') in caplog.text


async def test_the_warning_is_logged_once_while_the_issue_is_open(
        ha: HomeAssistant, case: Case, caplog: pytest.LogCaptureFixture) -> None:
    with patch(LOADER, side_effect=lambda *_args, **_kwargs: {}):
        assert await async_setup_component(ha, case.domain, {})
        assert await setup(ha, case.devices("door"))
    ha.states.async_set(f"{case.domain}.mine", "on")
    ha.states.async_set(f"{case.domain}.mine", "off")
    await settle()
    assert issue(ha, case) is not None
    assert len([r for r in caplog.records if "are not loaded: add" in r.getMessage()]) == 1


async def test_the_issue_goes_once_the_include_is_there(ha: HomeAssistant, case: Case) -> None:
    """The user adds the include and reloads the domain: no reload of pururu needed."""
    with patch(LOADER, side_effect=lambda *_args, **_kwargs: {}) as loader:
        assert await async_setup_component(ha, case.domain, {})
        assert await setup(ha, case.devices("door"))
        assert issue(ha, case) is not None
        loader.side_effect = including(ha, case)
        await ha.services.async_call(case.domain, "reload", blocking=True)
        await ha.async_block_till_done()
    assert issue(ha, case) is None
    assert loaded(ha, case, "door")


async def test_with_the_include_there_is_no_issue(ha: HomeAssistant, case: Case,
                                                  included: None) -> None:
    assert await setup(ha, case.devices("door"))
    assert issue(ha, case) is None


async def test_without_items_there_is_no_issue(ha: HomeAssistant, case: Case) -> None:
    assert await setup(ha, case.devices())
    assert issue(ha, case) is None


async def test_a_disabled_item_is_no_missing_include(ha: HomeAssistant, case: Case,
                                                     included: None) -> None:
    assert await setup(ha, case.devices("door"))
    er.async_get(ha).async_update_entity(case.entity_id("door"),
                                         disabled_by=er.RegistryEntryDisabler.USER)
    await ha.async_block_till_done()
    await ha.services.async_call(case.domain, "reload", blocking=True)
    await ha.async_block_till_done()
    assert issue(ha, case) is None


# --- failures, removal, start-up -----------------------------------------------------------


def failing_write() -> Any:
    return patch.object(module("generated"), "write_utf8_file_atomic",
                        side_effect=WriteError("disk full"))


async def test_a_failed_write_is_logged_and_the_setup_goes_on(
        ha: HomeAssistant, case: Case, caplog: pytest.LogCaptureFixture) -> None:
    with failing_write():
        assert await setup(ha, case.devices("door"))
    assert f"The {case.plural} are not written to {case.file}: disk full" in caplog.text
    assert ha.config_entries.async_entries("pururu")[0].state is ConfigEntryState.LOADED


async def test_removing_the_entry_leaves_an_empty_file(ha: HomeAssistant, case: Case,
                                                      included: None) -> None:
    assert await setup(ha, case.devices("door"))
    entry = ha.config_entries.async_entries("pururu")[0]
    await ha.config_entries.async_remove(entry.entry_id)
    await ha.async_block_till_done()
    assert Path(ha.config.path(case.file)).is_file()
    assert read(ha, case) == case.empty
    assert er.async_get(ha).async_get(case.entity_id("door")) is None
    assert ha.states.get(case.entity_id("door")) is None
    assert issue(ha, case) is None


async def test_a_failed_write_drops_nothing_stale(ha: HomeAssistant, case: Case,
                                                  included: None) -> None:
    """A dropped item whose write failed keeps its registry entry and its entry data."""
    assert await setup(ha, case.devices("door", "night"))
    with failing_write():
        await reload(ha, case.devices("night"))
    assert er.async_get(ha).async_get(case.entity_id("door")) is not None
    assert case.unique_id("door") in entry_data(ha, case)


async def test_a_failed_write_raises_no_include_issue(ha: HomeAssistant, case: Case,
                                                      included: None) -> None:
    """An item that never reached the file says nothing about the include."""
    assert await setup(ha, case.devices("door"))
    with failing_write():
        await reload(ha, case.devices("door", "night"))
    assert issue(ha, case) is None


async def test_a_failed_removal_keeps_the_items_ids(ha: HomeAssistant, case: Case,
                                                    included: None) -> None:
    """The file still holds them: HA loads them again with their pururu IDs."""
    assert await setup(ha, case.devices("door"))
    entry = ha.config_entries.async_entries("pururu")[0]
    with failing_write():
        await ha.config_entries.async_remove(entry.entry_id)
        await ha.async_block_till_done()
    assert er.async_get(ha).async_get(case.entity_id("door")) is not None


async def test_at_first_start_the_new_file_is_reloaded_once_and_included(
        ha: HomeAssistant, case: Case) -> None:
    with patch(LOADER, side_effect=including(ha, case)):
        assert await async_setup_component(ha, case.domain, {case.include_key: read(ha, case)})
        calls = capture(ha, "call_service")
        await restart(ha, case.devices("door"))
    state = ha.states.get(case.entity_id("door"))
    assert state is not None
    assert state.state != STATE_UNAVAILABLE
    assert loaded(ha, case, "door")
    assert len(reloads(calls, case)) == 1
    assert issue(ha, case) is None


async def test_a_restart_with_an_unchanged_file_reloads_nothing(
        ha: HomeAssistant, case: Case) -> None:
    """Every restart: HA loads the file it already holds, then pururu finds it unchanged."""
    assert await setup(ha, case.devices("door"))
    entry = ha.config_entries.async_entries("pururu")[0]
    await ha.config_entries.async_unload(entry.entry_id)
    await ha.async_block_till_done()
    ha.set_state(CoreState.not_running)
    with patch(LOADER, side_effect=including(ha, case)):
        assert await async_setup_component(ha, case.domain, {case.include_key: read(ha, case)})
        calls = capture(ha, "call_service")
        assert await ha.config_entries.async_setup(entry.entry_id)
        await ha.async_start()
        await ha.async_block_till_done()
    assert reloads(calls, case) == []
    assert loaded(ha, case, "door")
    assert issue(ha, case) is None


async def test_items_not_loaded_are_reloaded_at_the_next_reload(
        ha: HomeAssistant, case: Case) -> None:
    """A reload that didn't take (no include yet, or it failed) is retried, the file unchanged."""
    with patch(LOADER, side_effect=lambda *_args, **_kwargs: {}) as loader:
        assert await async_setup_component(ha, case.domain, {})
        assert await setup(ha, case.devices("door"))
        assert not loaded(ha, case, "door")
        loader.side_effect = including(ha, case)
        calls = capture(ha, "call_service")
        await reload(ha, case.devices("door"))
    assert len(reloads(calls, case)) == 1
    assert loaded(ha, case, "door")
    assert issue(ha, case) is None


async def test_a_failed_reload_keeps_what_is_still_loaded_and_is_retried(
        ha: HomeAssistant, case: Case, included: None,
        caplog: pytest.LogCaptureFixture) -> None:
    """A dropped item HA still runs keeps its pururu ID until a reload drops it."""
    assert await setup(ha, case.devices("door", "night"))
    with patch(case.process, side_effect=HomeAssistantError("boom")):
        await reload(ha, case.devices("night"))
    assert f"The {case.plural} are not reloaded: boom" in caplog.text
    assert loaded(ha, case, "door")
    assert er.async_get(ha).async_get(case.entity_id("door")) is not None
    assert case.unique_id("door") in entry_data(ha, case)
    await reload(ha, case.devices("night"))
    assert not loaded(ha, case, "door")
    assert er.async_get(ha).async_get(case.entity_id("door")) is None
    assert entry_data(ha, case) == [case.unique_id("night")]
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/test_generated.py -n 0 -q`
Expected: PASS for both `[automation]` and `[script]` ids. A `[script]`-only failure is a real gap in `generated.py` for scripts: fix it there (not in the test), rerun `tests/test_programs.py` too.

- [ ] **Step 3: Trim `tests/test_reactions.py`**

Delete the tests now in `test_generated.py`: `test_without_reactions_the_file_is_an_empty_list`, `test_an_automation_id_already_taken_is_not_generated`, `test_an_automation_of_ones_own_with_the_same_id_is_not_adopted`, `test_an_unchanged_file_is_neither_rewritten_nor_reloaded`, `test_a_file_in_another_encoding_is_rewritten`, `test_a_changed_file_reloads_automations`, `test_a_dropped_reaction_leaves_the_file_and_the_registry`, and everything from the `# --- the include, failures, removal` comment to the end of the file (with `issue`, `INCLUDE`, `NIGHT`, `loaded`, and Task 1's `test_the_warning_is_logged_once_while_the_issue_is_open`). In `test_the_file_holds_an_automation_per_reaction`, delete the `text = …` and header assertion lines. Remove the imports no longer used (`ConfigEntryState`, `STATE_UNAVAILABLE`, `CoreState`, `HomeAssistantError`, `ir`, `WriteError`, `load_yaml_dict`, `Path`, `AUTOMATIONS`, `capture`, `module` only if unused, `restart`).

- [ ] **Step 4: Run everything**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_generated.py tests/test_reactions.py
git commit -m "tests: generated.py's cases over automations and scripts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: docs, CLAUDE.md, release

**Files:**
- Move: `docs/concepts/programs.mdx` → `docs/concepts/programs.mdx` (`git mv`)
- Modify: `docs.json`, `docs/index.mdx`, `docs/concepts/devices-and-features.mdx`, `docs/concepts/entity-ids.mdx`, `docs/getting-started/install.mdx`, `docs/reference/configuration.mdx`, `docs/reference/troubleshooting.mdx`, `docs/develop/architecture.mdx`, `docs/develop/writing-a-feature.mdx`, `CLAUDE.md`, `custom_components/pururu/manifest.json`

- [ ] **Step 1: Move and rewrite the programs page**

`git mv docs/concepts/programs.mdx docs/concepts/programs.mdx`, then write it as:

````mdx
---
title: Programs
description: Sequences of actions on a device's own entities, each one a Home Assistant script.
---

`programs` gives a device things it knows how to do, such as a greenhouse's cleaning: turn the sprinkler on, wait two hours, turn it off. pururu writes each program as a Home Assistant **script**, and Home Assistant runs it. Its steps act on that device's own entities only.

```yaml
pururu:
  devices:
    greenhouse:
      name: Estufa
      switches:
        sprinkler: {entity: switch.greenhouse_sprinkler, name: Irrigador}
      programs:
        clean:
          name: Limpar
          sequence:
            - turn_on: switch_sprinkler
            - delay: {hours: 2}
            - turn_off: switch_sprinkler
```

This writes `script.pururu_greenhouse_program_clean`, shown as **Estufa Limpar**, to `pururu/scripts/programs.yaml`.

## The include

Home Assistant reads scripts only from its configuration. Add this line to `configuration.yaml`, once, then restart Home Assistant:

```yaml
script pururu: !include_dir_merge_named pururu/scripts
```

Until it's there, **Settings → Repairs** says so. pururu rewrites the file on every reload: don't edit it.

## Settings

`programs` is a map of **program key → program**, with at least one program. The key is a slug, and it ends the script's ID after the namespace `program`: `clean` → `script.pururu_greenhouse_program_clean`. `programs` isn't a feature: a device with programs still needs a feature, such as the switches they act on.

<Property name="name" type="string" required>
  The name shown after the device's name. It can't be empty, and it's the same in every language.
</Property>

---

<Property name="sequence" type="list of steps" required>
  The steps, run in order. At least one.
</Property>

## Steps

Each step has exactly one key:

| Step | What it does |
|---|---|
| `turn_on: <entity key>` | Turns that entity of the device on |
| `turn_off: <entity key>` | Turns it off |
| `toggle: <entity key>` | Turns it on if it's off, off if it's on |
| `delay: <time period>` | Waits, such as `{hours: 2}`, `"00:30:00"` or `90` (seconds) |

An entity key names an entity of **this device**, written as its entity ID ends after the device key: `switch_sprinkler` for `switch.pururu_greenhouse_switch_sprinkler`. It must be an entity of a feature of the device that takes the action. Today that's a [switch](/features/switches) or a [light](/features/lights). The same entity can appear in several steps.

Anything else is a configuration error: an entity ID (`switch.greenhouse_sprinkler`), another program, a sensor (`turn_on: appliance_power` gives `programs: appliance_power does not take turn_on`), or a Home Assistant action such as `action: switch.turn_on`.

## Only its own device

A program is a method of its device. It acts only on its device's entities, and it never starts by itself:

- **No other device, no real entity.** To act on a real switch or light, add it to the device under [`switches`](/features/switches) or [`lights`](/features/lights).
- **No templates, no events, no other actions.** Its steps are the four above.
- **No triggers.** Something outside starts it: you, an automation, a voice assistant.

## The script

`script.pururu_<key>_program_<program key>`, in the device's area. Home Assistant keeps a script from YAML out of any device, so it isn't on the device's page.

- **Starting it:** `script.turn_on`, or **Run** in the UI. It returns at once: an automation starting it doesn't wait for it to end.
- **While it runs**, its state is `on`, and `script.turn_off` stops it. What it already did stays: if the sprinkler was on, it stays on.
- **Started while it runs**, it's ignored, and the log says `Estufa Limpar: Already running`.
- **Its traces**, in the script's menu, show each step it ran.
- **A step that fails**, such as a real switch reporting an error, stops it, and the log and the trace say why. A switch that's `unavailable` doesn't stop it: that step does nothing and the program goes on.
- **A reload** of pururu stops a running program only if you changed that program: Home Assistant then loads its new script.
- **A restart** of Home Assistant loses a running program, as any script.
- **Renaming it** in the UI is kept.
- **An entity it acts on that you disable** in the UI removes the program until you enable it again, and the log says why. Meanwhile an automation starting it fails.
- If an entity it acts on isn't created, the program isn't either, and the log says so. See [Troubleshooting](/reference/troubleshooting).
- **Renaming an entity it acts on** in the UI is followed: the file is rewritten with the new ID.

## From 0.1.11 and before

Programs were buttons, `button.pururu_<key>_program_<program key>`, pressed with `button.press`. The first start of 0.1.12 removes them. Change what pressed one to `script.turn_on` on its script, and add the include above.
````

- [ ] **Step 2: Links and sidebar**

- `docs.json`: remove `{ "title": "programs", "href": "/concepts/programs" }` from Features (and the comma before it); in Concepts, after Reactions add `{ "title": "Programs", "href": "/concepts/programs" },`.
- Replace every `/concepts/programs` with `/concepts/programs` under `docs/`: `grep -rl "/concepts/programs" docs | xargs sed -i 's#/concepts/programs#/concepts/programs#g'`.

- [ ] **Step 3: The pages that describe programs or the include**

- `docs/index.mdx:66`: "A [program](/concepts/programs) starts only when one of them presses it;" → "A [program](/concepts/programs) is a script that starts only when one of them runs it;".
- `docs/concepts/devices-and-features.mdx`: line 37, delete ", or, for [`programs`](/concepts/programs), runs steps on the device's own entities"; delete the `programs` rows at lines 47 and 82; after the table at line 47 add "A device can also have [`reactions`](/concepts/reactions) and [`programs`](/concepts/programs). They aren't features: they write Home Assistant automations and scripts, and a device still needs a feature."
- `docs/concepts/entity-ids.mdx`: line 14, "`switch`, `light` or `button`" → "`switch` or `light`"; line 26, the `programs` row → `| [`programs`](/concepts/programs) | `program` | `script.pururu_greenhouse_program_clean` (a Home Assistant script) |`; line 42, "an [alert](/features/alerts)'s or a [program](/concepts/programs)'s" → "or an [alert](/features/alerts)'s", and add after that paragraph "A [program](/concepts/programs)'s script is named `<device name> <name:>` too."
- `docs/getting-started/install.mdx:63`: after the reactions sentence add "Using [programs](/concepts/programs)? Also add `script pururu: !include_dir_merge_named pururu/scripts`: pururu writes the programs' scripts to that folder."
- `docs/reference/configuration.mdx:70`: add a line after it: `script pururu: !include_dir_merge_named pururu/scripts`; line 167: "[`programs`](/concepts/programs#settings): sequences of actions on the device's own entities, as Home Assistant scripts."
- `docs/reference/troubleshooting.mdx`: line 106, "was pressed while it was still running, for example during its `delay`. The press is ignored" → "was started while it was still running, for example during its `delay`. The start is ignored". After the `## Reactions` section's last entry, add a `## Programs` section:

````mdx
## Programs

### The programs' scripts aren't loaded

**Settings → Repairs** shows it, and the log says:

```
The scripts of pururu's programs are not loaded: add "script pururu: !include_dir_merge_named pururu/scripts" to configuration.yaml
```

**Fix:** add that line to `configuration.yaml`, then reload scripts in **Developer tools → YAML → Scripts**. See [The include](/concepts/programs#the-include).

### `script.… follows …, which is not created; not generating it`

```
script.pururu_greenhouse_program_clean follows switch.pururu_greenhouse_switch_sprinkler, which is not created; not generating it
```

An entity the program acts on isn't created, usually because its ID is taken. Fix that entity, then reload pururu.

### `script.… acts on …, which is disabled; not generating it`

```
script.pururu_greenhouse_program_clean acts on switch.pururu_greenhouse_switch_sprinkler, which is disabled; not generating it
```

You disabled an entity the program acts on. Enable it again and the program comes back.

### `script.… is already taken by …; not generating it`

```
script.pururu_greenhouse_program_clean is already taken by script.mine, a script with the same ID; not generating it
```

A script of your own, or of another integration, has the program's ID. pururu never takes it over: rename or remove the other script, or give the program another key.
````

- [ ] **Step 4: Develop pages**

- `docs/develop/architecture.mdx`: lines 20 and 39, drop `button.py` from the platform lists; replace step 6 (line 42) with: "6. **Generate the reactions' automations and the programs' scripts** (`generated.py`, with a `Kind` per domain from `reactions.py` and `programs.py`): each is written to its file (`pururu/automations/reactions.yaml`, `pururu/scripts/programs.yaml`) when it changed, and `configuration.yaml` includes the folder (`!include_dir_merge_list`, `!include_dir_merge_named`, so a missing one loads as nothing). Entity IDs are registered first so they get the pururu pattern, a script is put in its device's area, HA reloads the domain once HA has started when the file changed or HA doesn't run what it holds (so a reload that didn't take is retried), in a task the entry's unload waits for, and a Repairs issue says when the include is missing, checked again on every state change of the domain. An ID the entry doesn't manage is the user's own and is never taken over; a dropped item keeps its registry entry until HA no longer runs it (a restored placeholder doesn't count). `reactions` and `programs` are device keys, not `Feature`s: they create no pururu entity."; line 73, replace the paragraph with: "A program's step acts on a feature's entity: `_programs_on_this_device` checks that the feature owning each key has the action in its `actions` (`programs: appliance_power does not take turn_on` otherwise). `programs.py` translates the steps to Home Assistant's script syntax on the keys' current entity IDs, and HA runs the script."
- `docs/develop/writing-a-feature.mdx:167`: replace the paragraph with: "**Being acted on:** a feature whose entities a [program](/concepts/programs) can act on declares `actions`, the services of its platform they take: `SWITCHES` and `LIGHTS` have `(\"turn_on\", \"turn_off\", \"toggle\")`."

- [ ] **Step 5: CLAUDE.md**

- Step 3 of the architecture list: platforms `(sensor.py, binary_sensor.py, switch.py, light.py)`.
- Step 6: "Generate the reactions' automations and the programs' scripts (`generated.py`, a `Kind` per domain): `pururu/automations/reactions.yaml` and `pururu/scripts/programs.yaml`, whose folders `configuration.yaml` includes (`automation pururu: !include_dir_merge_list pururu/automations`, `script pururu: !include_dir_merge_named pururu/scripts`, as a missing folder loads as nothing while a missing file stops HA's configuration), entity IDs pre-registered (an ID the entry doesn't manage is the user's, never taken over), a script in its device's area, the domain reloaded when the file changed or HA doesn't run it (retried at the next reload), in an entry task, a Repairs issue while it isn't included (checked again on the domain's state changes, the warning logged once). A dropped item's registry entry goes once HA no longer runs it: a restored placeholder state doesn't count. `reactions` and `programs` are device keys, not `Feature`s; a program isn't generated while an entity it acts on is not created or disabled."
- The `entry.data` bullet: `{"floors": [...], "areas": [...], "automations": [...], "scripts": [...]}`, the last two the IDs of the reactions' automations and the programs' scripts.
- Features: delete the bullet "A feature can act on those entities (a program's `turn_on: switch_sprinkler`)…"; in the `configured` bullet, `(switches, lights, alerts)`; add under Features: "A feature's `actions` (switches and lights: `turn_on`, `turn_off`, `toggle`) are what a program's step can do to its entities; `_programs_on_this_device` checks them."

- [ ] **Step 6: Version**

`custom_components/pururu/manifest.json`: `"version": "0.1.12"`.

- [ ] **Step 7: Check**

Run: `grep -rn "features/programs\|button.press\|button.py\|Feature.acts\|\bacts\b" docs CLAUDE.md --include=*.mdx --include=*.md --include=*.json | grep -v superpowers`
Expected: only the "From 0.1.11 and before" section's `button.press`.

Run: `pnpm install && pnpm docs:check`
Expected: no broken links.

Run: `python3 release.py check && uv run pytest`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add -A docs docs.json CLAUDE.md custom_components/pururu/manifest.json
git commit -m "pururu: programs as scripts, docs and release (0.1.12)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
