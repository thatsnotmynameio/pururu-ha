# Refactor A2a: lifecycle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Leave only HA's entry points in `__init__.py`, run the outputs as a tuple of guarded steps over a frozen `Built`, follow renames with one rule for every generated kind, and share the "not included" Repairs policy and the ID-holder check.

**Architecture:** `lifecycle.py` does what the entry points do; `listener.py` owns the registry listener. After the prelude (places, building, forwarding the platforms), `async_setup_entry` walks `STEPS`, each `async def (hass, entry, built) -> frozenset[str]` owned by its output module, each in `try/except` with a logged exception. Everything is behaviour-preserving except three deliberate changes, each pinned by a test written first: a failing step no longer fails the setup, renaming a ready-made notification's automation reloads the entry, and Alert2's "not included" warning is logged once while its issue is open.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3, pytest (+ pytest-homeassistant-custom-component, pytest-cov), ruff, mypy strict, uv.

**Spec:** `docs/superpowers/specs/2026-09-29-yaml-contract-coherence-design.md` — PR A2a (Part 3: `__init__.py`, lifecycle, flow step 5 and 6, D17, D23).

## Global Constraints

- Every existing test passes unchanged; no test is deleted, edited or loosened. The three deliberate behaviour changes each get a new test.
- Coverage kept per function: no function has more missing lines or branches after than before (Task 7 compares).
- Every entity ID, unique ID and generated ID identical: `tests/test_ids.py` passes unchanged.
- `uv run pytest` green at every commit (ruff, format, mypy strict, hassfest, quality scale).
- The version stays `0.2.0`; this PR releases nothing.
- `__init__.py` ends with only `CONFIG_SCHEMA` and HA's four entry points, each a few lines, no logic.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM`.

## Review Focus

1. **Step order.** Today: events, place, remove stale, scripts, reactions' automations, notifications' automations, Alert2, alert lights, dashboard. `STEPS` must keep it; the listener is registered after the last step, as today.
2. **A guard that hides bugs.** A step's exception is logged, not raised. The autouse fixture of Task 3 fails any test that logs it unexpectedly.
3. **What the prelude still raises.** Building and forwarding stay outside the guard: a feature whose `build` raises still fails the setup (`test_reload_sets_up_a_failed_entry_again` keeps passing).
4. **The rename rule and the user's own items.** A script or automation with a pururu-like ID that the entry doesn't track (`test_renaming_ones_own_script_reloads_nothing`) must still reload nothing.
5. **Targets from steps that ran.** When a step fails, the listener still gets the targets of the steps before and after it.

---

## File structure

| File | After A2a |
|---|---|
| `__init__.py` | `CONFIG_SCHEMA` (re-exported) and `async_setup`, `async_setup_entry`, `async_unload_entry`, `async_remove_entry`, each delegating to `lifecycle` |
| `lifecycle.py` (new) | `async_setup`, `async_apply`, `async_setup_entry` (prelude, `STEPS`, guarded loop, listener), `async_unload_entry`, `async_remove_entry` |
| `listener.py` (new) | `async_listen(hass, entry, targets)`, `rebuild_for(...)`, the one rename rule |
| `runtime.py` | gains `Built` and `Step` |
| `events.py`, `devices.py`, `generate.py`, `alert2_alerts.py`, `alert_lights.py`, `dashboard.py` | each gains `async_step(hass, entry, built) -> frozenset[str]` |
| `entity.py` | `PururuEntity.key`, `PururuEntity.reference`, `other_holder` |
| `generated.py` | `async_issue` (the one "not included" policy) |
| `build.py` | `_holder` uses `other_holder` |
| `tests/test_lifecycle.py` (new) | the guard, the rename rule |
| `tests/conftest.py` | the autouse fixture failing on an unexpected step failure |
| `tests/test_code.py` | the import test (A2's rules) |

---

### Task 1: Entry points out of `__init__`: `lifecycle.py`, `listener.py`

**Files:** Create `custom_components/pururu/lifecycle.py`, `custom_components/pururu/listener.py`; modify `custom_components/pururu/__init__.py`.

**Interfaces:**
- Produces: `lifecycle.async_setup(hass, config) -> bool`, `lifecycle.async_apply(hass, config, *, reloading) -> None`, `lifecycle.async_setup_entry(hass, entry) -> bool`, `lifecycle.async_unload_entry(hass, entry) -> bool`, `lifecycle.async_remove_entry(hass, entry) -> None`; `listener.rebuild_for(entry_id, registered, changes, watched, targets)`, `listener.async_listen(hass, entry, watched, targets) -> None`.

- [ ] **Step 1: Move verbatim** (a pure move; the unchanged suite is its test)

Move `__init__.py`'s bodies to `lifecycle.py`: `async_setup` (with its nested `reload`), `_async_apply` → `async_apply`, `async_setup_entry`, `async_unload_entry`, `async_remove_entry`, with their imports. Move `_rebuild_for` → `listener.rebuild_for`. Take the nested `changed` callback and its registration out of `async_setup_entry` into:

```python
def async_listen(
    hass: HomeAssistant,
    entry: PururuConfigEntry,
    watched: set[tuple[str, str]],
    targets: set[str],
) -> None:
    """Build the entry again when one of its entities or generated items is renamed, or a target disabled."""
    registry = er.async_get(hass)
    # Whether a reload is already scheduled: a burst of disables reloads once
    reloading = False

    @callback
    def changed(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        # today's body, verbatim, with its docstring
        ...

    entry.async_on_unload(hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, changed))
```

`lifecycle.async_setup_entry` ends with `listener.async_listen(hass, entry, watched, targets | lent)` then `return True`.

`__init__.py` becomes:

```python
"""pururu: floors, areas and devices configured in YAML, which the integration creates.

(module docstring as today)
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from . import lifecycle
from .runtime import PururuConfigEntry
from .schema import CONFIG_SCHEMA as CONFIG_SCHEMA


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Keep the configuration for the entry, and apply it again on reload."""
    return await lifecycle.async_setup(hass, config)


async def async_setup_entry(hass: HomeAssistant, entry: PururuConfigEntry) -> bool:
    """Make floors and areas follow the configuration, then build every device."""
    return await lifecycle.async_setup_entry(hass, entry)


async def async_unload_entry(hass: HomeAssistant, entry: PururuConfigEntry) -> bool:
    """Remove the entities; a reload builds them again."""
    return await lifecycle.async_unload_entry(hass, entry)


async def async_remove_entry(hass: HomeAssistant, entry: PururuConfigEntry) -> None:
    """Delete everything the entry managed."""
    await lifecycle.async_remove_entry(hass, entry)
```

Check `sonar-project.properties`: a suppression naming `__init__.py` for `async_remove_entry` (S7503) moves to `lifecycle.py` if the finding moves with the body; keep the one in `__init__.py` if the signature there still triggers it.

- [ ] **Step 2: Run the whole suite**

Run: `uv run pytest -q`. Expected: every test passes unchanged.

- [ ] **Step 3: Commit**

`git add -A custom_components/pururu sonar-project.properties && git commit -m "pururu: HA's entry points only in __init__; lifecycle and listener modules (refactor A2a)"`

---

### Task 2: `Built`, and the outputs as `STEPS`

**Files:** Modify `runtime.py`, `lifecycle.py`, `events.py`, `devices.py`, `generate.py`, `alert2_alerts.py`, `alert_lights.py`, `dashboard.py`.

**Interfaces:**
- Produces:

```python
# runtime.py
@dataclass(frozen=True, kw_only=True)
class Built:
    """What the prelude built: every step reads it, none changes it."""

    house: Mapping[str, Any]                              # the validated pururu: block
    texts: Mapping[str, str]                              # the translations' common texts
    entities: Mapping[Platform, tuple[Entity, ...]]       # what the platforms added
    by_device: Mapping[str, tuple[PururuEntity, ...]]     # each device's created entities
    created: frozenset[str]                               # their unique IDs

type Step = Callable[[HomeAssistant, PururuConfigEntry, Built], Awaitable[frozenset[str]]]
```

Each output module gains `async def async_step(hass, entry, built) -> frozenset[str]`, returning the entity IDs whose disabling reloads the entry (`frozenset()` for most):

| Module | Its step does (today's lines of `async_setup_entry`) | Returns |
|---|---|---|
| `events` | `async_setup(hass, entry, classes, watched(devices, by_device))` | `frozenset()` |
| `devices` | `place`, then `remove_stale` | `frozenset()` |
| `generate` | scripts → `programs.KIND`, reactions' automations → `reactions.KIND`, notifications → `notifications.KIND`, as today | the programs' targets |
| `alert2_alerts` | `async_sync(hass, entry, items(hass, built.entities))` | `frozenset()` |
| `alert_lights` | `settings`, `light_ids`, `async_setup(…)` with the `ProblemAlert`s and `Borrowable`s of `built.entities` | the lent lights and alerts |
| `dashboard` | `async_setup(hass, entry)` | `frozenset()` |

`runtime.py` imports `PururuEntity` from `.entity` (L0). `alert_lights`' step takes `ProblemAlert` and `Borrowable` as today.

- [ ] **Step 1: Write the failing test for what the steps must keep: order**

`tests/test_lifecycle.py`:

```python
"""The entry's life: the steps after the platforms, their guard, the listener."""

from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest

from helpers import DOMAIN, module, setup

SWITCH = {"name": "Estufa", "switches": {"sprinkler": {"entity": "switch.greenhouse_sprinkler", "name": "Irrigador"}}}


async def test_the_steps_run_in_order(ha: HomeAssistant) -> None:
    """Events, devices, the generated files, Alert2, the alert lights, the dashboard: as the spec's flow says."""
    names = [name for name, _ in module("lifecycle").STEPS]
    assert names == ["events", "devices", "generate", "alert2", "alert lights", "dashboard"]
```

Run: `uv run pytest tests/test_lifecycle.py -n 0 -q`. Expected: FAIL (`module 'lifecycle' has no attribute 'STEPS'`).

- [ ] **Step 2: Build `Built` in the prelude and walk `STEPS`**

In `lifecycle.async_setup_entry`, after today's building loop: `built = Built(house=configured, texts=texts, entities={p: tuple(e) for p, e in entities.items()}, by_device={k: tuple(v) for k, v in created_by.items()}, created=frozenset(created))`; `entry.runtime_data` stays the `dict[Platform, list[Entity]]` the platforms read. Then:

```python
STEPS: tuple[tuple[str, Step], ...] = (
    ("events", events.async_step),
    ("devices", devices.async_step),
    ("generate", generate.async_step),
    ("alert2", alert2_alerts.async_step),
    ("alert lights", alert_lights.async_step),
    ("dashboard", dashboard.async_step),
)
```

and, for now without a guard: `targets: set[str] = set()`, `for _, step in STEPS: targets |= await step(hass, entry, built)`, then `listener.async_listen(hass, entry, generate.watched_items(devices), targets)`. Move each block of today's `async_setup_entry` into its module's `async_step`, verbatim apart from reading `built`.

- [ ] **Step 3: Run the test and the suite**

Run: `uv run pytest tests/test_lifecycle.py -n 0 -q` → PASS; `uv run pytest -q` → every test passes.

- [ ] **Step 4: Commit**

`git commit -m "pururu: the outputs as STEPS over a frozen Built (refactor A2a)"`

---

### Task 3: The guard, and the fixture that keeps it honest

**Files:** Modify `lifecycle.py`, `tests/test_lifecycle.py`, `tests/conftest.py`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_lifecycle.py`:

```python
async def test_a_step_that_raises_leaves_the_entry_loaded(
    ha: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """The dashboard raising doesn't fail the setup: logged, the entry loaded, a reload loads it again."""
    with patch.object(module("dashboard"), "async_setup", side_effect=RuntimeError("boom")):
        assert await setup(ha, {"greenhouse": SWITCH})
    [entry] = ha.config_entries.async_entries(DOMAIN)
    assert entry.state is ConfigEntryState.LOADED
    assert ha.states.get("switch.pururu_greenhouse_switch_sprinkler") is not None
    assert "Step dashboard failed" in caplog.text
    await ha.config_entries.async_reload(entry.entry_id)
    await ha.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    caplog.clear()  # expected: the autouse fixture would fail on it
```

Run: `uv run pytest tests/test_lifecycle.py -n 0 -q`. Expected: FAIL (the entry is `SETUP_ERROR`, no "Step dashboard failed").

- [ ] **Step 2: The guard**

```python
for name, step in STEPS:
    try:
        targets |= await step(hass, entry, built)
    except Exception:
        # A step failing after the platforms would leave the entry stuck until a
        # restart: HA unloads a non-loaded entry without async_unload_entry
        _LOGGER.exception("Step %s failed", name)
```

Run: `uv run pytest tests/test_lifecycle.py -n 0 -q` → PASS.

- [ ] **Step 3: The autouse fixture, and proof it bites**

In `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def no_step_failed(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Fail a test in which a step failed without the test expecting it (then it clears caplog)."""
    yield
    failed = [
        record.getMessage()
        for record in caplog.get_records("call")
        if record.name.endswith(".lifecycle") and record.getMessage().startswith("Step ")
    ]
    assert not failed, failed
```

Proof: comment out `caplog.clear()` in the new test, run it, and see it ERROR at teardown with `['Step dashboard failed']`; restore the line and see it PASS.

- [ ] **Step 4: Suite and commit**

Run: `uv run pytest -q` → every test passes (no other test logs a failed step). `git commit -m "pururu: a failing step is logged, not a stuck entry; tests fail on an unexpected one (refactor A2a)"`

---

### Task 4: One rename rule for every generated kind

**Files:** Modify `generated.py` (`KINDS`), `listener.py`, `lifecycle.py`; test in `tests/test_lifecycle.py`.

**Interfaces:** `listener.async_listen(hass, entry, kinds, targets)` takes the kinds, `(programs.KIND, reactions.KIND, notifications.KIND)`, passed by `lifecycle`: `generated.py` is core and can't import the modules that own them.

- [ ] **Step 1: Write the failing test**

```python
async def test_renaming_a_ready_made_notification_reloads(ha: HomeAssistant) -> None:
    """Every generated item the entry tracks follows one rule: renamed, the entry builds again."""
    washer = {
        "name": "Washer",
        "appliance": {
            "power": "sensor.washer_power",
            "running": {"threshold": 4, "on_delay": 1, "off_delay": 1},
            "notifications": {"finished": None},
        },
    }
    assert await setup(ha, {"washer": washer}, config={"notify": "notify.phone"})
    registry = er.async_get(ha)
    with patch.object(ha.config_entries, "async_schedule_reload") as reloading:
        registry.async_update_entity(
            "automation.pururu_washer_appliance_notification_finished",
            new_entity_id="automation.roupa_pronta",
        )
        await ha.async_block_till_done()
    reloading.assert_called_once()
```

Run it. Expected: FAIL (`async_schedule_reload` not called: today's `watched_items` lists programs and reactions only).

- [ ] **Step 2: The rule**

In `listener.py`, `changed` no longer takes `watched`; `rebuild_for` asks whether `(registered.platform, registered.unique_id)` is `(kind.domain, id)` for an `id` in `entry.data.get(kind.data_key, [])`, for any of `kinds`. `lifecycle` passes `(programs.KIND, reactions.KIND, notifications.KIND)` and stops computing `watched_items` for the listener (`generate.owned` keeps using it).

- [ ] **Step 3: Tests**

Run: `uv run pytest tests/test_lifecycle.py -n 0 -q` → PASS; `uv run pytest tests/test_reactions.py tests/test_programs.py -n 0 -q` → PASS (`test_renaming_ones_own_script_reloads_nothing`: the user's script isn't tracked); `uv run pytest -q` → every test passes.

- [ ] **Step 4: Commit**

`git commit -m "pururu: one rename rule for every generated kind, notifications included (refactor A2a)"`

---

### Task 5: `entity.key`/`reference`, `other_holder`, one "not included" policy

**Files:** Modify `entity.py`, `events.py`, `build.py`, `generated.py`, `alert2_alerts.py`; tests `tests/test_entity.py`, `tests/test_alert2.py`.

- [ ] **Step 1: Failing test for the reference**

In `tests/test_entity.py`:

```python
async def test_an_entity_knows_its_reference(ha: HomeAssistant) -> None:
    """`<device>.<entity key>`: the event_name events fire, the reference form C adds to the YAML."""
    assert await setup(ha, {"greenhouse": {"name": "Estufa", "switches": {"sprinkler": {"entity": "switch.greenhouse_sprinkler", "name": "Irrigador"}}}})
    [entry] = ha.config_entries.async_entries(DOMAIN)
    [switch] = entry.runtime_data[Platform.SWITCH]
    assert (switch.key, switch.reference) == ("switch_sprinkler", "greenhouse.switch_sprinkler")
```

Run: FAIL (`no attribute 'key'`).

- [ ] **Step 2: Implement**

In `PururuEntity._identify`: `self.key = device.qualified(key)` and `self.reference = f"{device.key}.{self.key}"` (class annotations `key: str`, `reference: str`). `events.watched` maps `entity.entity_id: entity.key` instead of stripping the prefix off the unique ID. Run the test → PASS; `uv run pytest tests/test_events.py -n 0 -q` → PASS.

- [ ] **Step 3: `other_holder`**

In `entity.py`:

```python
def other_holder(hass: HomeAssistant, registry: er.EntityRegistry, entity_id: str) -> str | None:
    """Who else holds `entity_id` once it isn't ours: another integration, an entity without unique ID, or no one."""
    if (registered := registry.async_get(entity_id)) is not None:
        return f"the {registered.platform} integration"
    if (state := hass.states.get(entity_id)) is not None and not state.attributes.get(ATTR_RESTORED):
        return "an entity without a unique ID"
    return None
```

`build._holder` and `generated._holder` keep their own first step ("is it ours": by unique ID in the registry; for a generated item, managed by the entry) and return `other_holder(hass, registry, entity_id)` for the rest. Run `uv run pytest tests/test_init.py tests/test_generated.py -n 0 -q` → PASS (their taken-ID tests cover both tails).

- [ ] **Step 4: Failing test for one "not included" policy**

In `tests/test_alert2.py`, next to `test_without_the_include_an_issue_says_what_to_add` (a new test; that one stays as it is):

```python
async def test_the_include_warning_is_logged_once_while_its_issue_is_open(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """As the scripts' and automations' issues: an open issue isn't warned about again at each reload."""
    FakeAlert2(ha, included=False)
    assert await setup(ha, devices(**WITH_NOTIFY))
    await reload(ha, devices(**WITH_NOTIFY))
    assert issue(ha) is not None
    assert caplog.text.count(INCLUDE_WARNING) == 1
```

Run: `uv run pytest tests/test_alert2.py -n 0 -q -k once_while`. Expected: FAIL (`2 == 1`: Alert2 warns at every setup today).

- [ ] **Step 5: `generated.async_issue`**

```python
@callback
def async_issue(
    hass: HomeAssistant, issue: str, missing: bool, warning: Callable[[], None], placeholders: dict[str, str]
) -> None:
    """Raise `issue` while something isn't included, else delete it; warn once while it is open.

    An open issue is left as it is. One a restart restored is inactive, and is raised again.
    """
    if not missing:
        ir.async_delete_issue(hass, DOMAIN, issue)
        return
    if (found := ir.async_get(hass).async_get_issue(DOMAIN, issue)) is not None and found.active:
        return
    warning()
    ir.async_create_issue(
        hass, DOMAIN, issue, is_fixable=False, severity=ir.IssueSeverity.WARNING,
        translation_key=issue, translation_placeholders=placeholders,
    )
```

`generated._check_included` and `alert2_alerts._check_included` call it with their own warning. Run the Alert2 test → PASS; `uv run pytest -q` → every test passes.

- [ ] **Step 6: Commit**

`git commit -m "pururu: entity key and reference; one holder tail; one not-included policy (refactor A2a)"`

---

### Task 6: The import test (A2's rules)

**Files:** Modify `tests/test_code.py`.

- [ ] **Step 1: Write it**

```python
L0 = {"const", "runtime", "feature", "vocabulary", "entity", "texts", "messages", "files", "generated"}
PLATFORMS = {"sensor", "binary_sensor", "switch", "light"}


def imports_of(path: Path) -> set[str]:
    """The pururu modules a file imports, as dotted names relative to the package."""
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            base = ".".join(path.relative_to(INTEGRATION).with_suffix("").parts[: -node.level] or [])
            module = ".".join(part for part in (base, node.module or "") if part)
            names = [module] if node.module else [f"{base}.{alias.name}".lstrip(".") for alias in node.names]
            found.update(name for name in names if name)
    return found


def test_the_core_imports_only_the_core() -> None:
    for name in L0:
        assert imports_of(INTEGRATION / f"{name}.py") <= L0, name


def test_the_platforms_import_only_runtime() -> None:
    for name in PLATFORMS:
        assert imports_of(INTEGRATION / f"{name}.py") <= {"runtime"}, name


def test_no_module_is_named_after_a_platform_ha_preloads() -> None:
    from homeassistant.loader import BASE_PRELOAD_PLATFORMS  # noqa: PLC0415
    ours = {path.stem for path in INTEGRATION.glob("*.py")}
    assert not (ours & set(BASE_PRELOAD_PLATFORMS)) - {"config_flow"}
```

(`INTEGRATION` is the package path, as `tests/test_features.py` defines it.)

- [ ] **Step 2: Watch each fail once, then pass**

Add `from .features import FEATURES` to `runtime.py`, run `uv run pytest tests/test_code.py -n 0 -q`, see `test_the_core_imports_only_the_core` FAIL naming `runtime`; remove it, PASS. Same with `from . import events` in `sensor.py` for the platforms test.

- [ ] **Step 3: Commit**

`git commit -m "tests: the core and the platforms import only what the layers allow (refactor A2a)"`

---

### Task 7: Coverage, docs, PR

**Files:** `CLAUDE.md`, `docs/develop/architecture.mdx`, `docs/develop/index.mdx`, `docs/develop/testing.mdx`.

- [ ] **Step 1: Coverage per function** as in A1: record `coverage-before.json` on `main` (before Task 1), `coverage-after.json` now, compare per function (the A1 script, with renames `_async_apply` → `async_apply`, `_rebuild_for` → `rebuild_for`, `changed` counted under `async_listen`). No function with more missing lines or branches.
- [ ] **Step 2: Docs.** CLAUDE.md's Architecture and `architecture.mdx`: `__init__.py` only the entry points; `lifecycle.py` (prelude, `STEPS`, the guard), `listener.py` (one rename rule: any tracked generated item, notifications included); each output's `async_step`; `Built`. `index.mdx` layout: `lifecycle.py`, `listener.py`. `testing.mdx`: `test_lifecycle.py`, the autouse fixture. `pnpm docs:check`.
- [ ] **Step 3: Whole suite, commit, PR** (`pururu: refactor A2a, entry points only in __init__; guarded steps (0.2.0)`), label `claude-review`, watch checks, the review and Sonar.
