# Refactor B: the aspects — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Part 1 of the spec.
- **Aspects:** statistics, a feature's ready-made alerts and its ready-made notifications become aspects. Each is written once, in `aspects/`, and mounted wherever a builder offers it through its roles.
- **`alerts` becomes a device key.**
- **One automations kind.**
- **`CycleSource`:** the cycle signal code, copied four times today, is written once.
- **The whole layer table,** enforced by the import test.

**Architecture:**
- **`Aspect`** (`core/feature.py`) is a small frozen dataclass: `key`, `offered`, `schema`, `keys`, `example`, `build`, `generates`. `aspects/__init__.py` lists `ASPECTS`.
- **`catalogue.mount`** takes the key of every aspect a builder offers out of its block, validates it with the aspect's schema, and leaves the rest to the builder's schema. That replaces `presets.validate` and `schema._feature_block`.
- **Building:** each builder builds its own entities first. Then each offered aspect builds its own: the statistics aspect builds the meters, the alerts aspect the ready-made alerts. The notifications aspect builds no entity; it writes automations (`generates`, `plan()`).
- **The roles:** `Counters` (new) tells the statistics aspect what to meter. `Presets` and `Happenings` tell the other two aspects what they offer.

The YAML users write doesn't change, and neither do entity IDs, unique IDs or the names shown. The generated automations move to one file (the manual step below).

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3, voluptuous, pytest, ruff, mypy strict, uv.

**Spec:** `docs/superpowers/specs/2026-09-29-yaml-contract-coherence-design.md`:
- Part 1 (the whole of it);
- Part 3: "Package", "Layers", "A builder is composed of roles" (`Counters`), "Other types" (`Aspect`, `CycleSource`, `vocabulary.trigger`), "Generated files" (one automations kind);
- PRs → B.

**Base:** `main` after A2b merges.

**Four PRs** (decided while Task 1 ran; the spec's PRs table lists B1 to B4). Each PR is its tasks, then its own Task 7: its docs, per-function coverage, the final whole-branch review on opus with every finding fixed, and the PR, opened with the `greptile` label. Each PR is stacked on the previous one and retargeted to `main` once that merges.

| PR | Tasks | Branch |
|---|---|---|
| B1 | 1 (`CycleSource`), 2 (`vocabulary.trigger`) | `refactor/b1-cycle-source` |
| B2 | 3 (the statistics aspect) | `refactor/b2-statistics` |
| B3 | 4 (the alerts aspect, `alerts` a device key) | `refactor/b3-alerts` |
| B4 | 5 (the notifications aspect, one automations kind), 6 (the whole layer table) | `refactor/b4-notifications` |

The manual step (Task 5) goes in B4's PR text, and in the final "Updating to 0.2.0" guide (PR C).

## Global Constraints

- Version stays `0.2.0`.
- `tests/test_ids.py` unchanged and passing: every entity's `(platform, unique_id)` and every generated item's `(domain, ID)` stay. The automations' IDs stay; only their file changes.
- Names shown don't change, in `en` and `pt-BR`: an entity's name comes from a translation key the aspect owns, but reads the same.
- Error texts stay verbatim, except where the spec removes a rule:
  - `presets.validate`'s "{name} is now a notification" goes (D13);
  - a device with only `alerts` and `programs`/`reactions` is now refused with the existing "a device needs at least one feature (…)".
- `uv run pytest` green at every commit. Per-function coverage not lower than A2b's (`.superpowers/sdd/2026-09-29-refactor-a2b-model/coverage-after.json`); a moved function is compared under its new name.
- Simple on purpose: a type exists only if it deletes a duplication that exists today (`Aspect` deletes five copies of statistics; `CycleSource` four copies of the signal plumbing).
- Commits end with the two attribution lines. The PR opens only after the final whole-branch review's fixes, with the `greptile` label; after each push, the `claude-review` label.

## Review Focus

1. **A meter's name.**
   - Each meter's translation key moves from `<namespace>_<counter>_<period>` (`appliance_runtime_today`, `mode_runtime_today`) to the aspect's: `<counter>_<period>`, or `item_<counter>_<period>` with the `{item}` placeholder.
   - The name shown must be the same in both languages for every builder: `door` and `window` share texts; a mode says "Tempo de {item} hoje".
   - The item's placeholder is named `item`, not after the namespace.
2. **`mount` on a configured block.** `switches` and `lights` may have an item keyed `statistics`, `alerts` or `notifications`; `mount` must not take it out: a configured builder offers no block-level aspect. The same holds at item level: a program's own `statistics` is its `Counters(mount="item")`.
3. **The one automations file.** Reactions' and notifications' automations in one `automations.yaml`, one data key, one Repairs issue. A rename of either still reloads the entry. The old `reactions.yaml`/`notifications.yaml` must be deleted by the user (the manual step): until then HA loads duplicate IDs.
4. **`alerts` as a device key.**
   - It stops counting as a feature: a device with `alerts` and only `programs` is now refused.
   - An alert's `when` may still target any feature's key but no alert (`by == "alerts"` or `builder == "alerts"`).
   - The Alert2 file and the alert lights still find every `ProblemAlert`, hand-written or ready-made.
5. **`CycleSource` order.** The state is written, then the cycle signal, then the end signal (the end's own last). A listener that reads the source's state on the cycle signal must see it already written.

---

### Task 1: `CycleSource`

**Files:** Create `features/cycle/source.py` (or add it to `features/cycle/__init__.py`). Modify `features/appliance/running.py` (`Running`), `features/opening/open.py` (`Open`), `device_keys/programs.py` (`Runs`), `features/modes/current.py` (`Current`). Tests: `tests/test_cycle.py` (new, or next to the existing cycle tests).

**Produces:** `class CycleSource(PururuEntity)`, with `_cycle_signals(device, item)` set up in `__init__`, and `_send(cycle: Cycle) -> None`: it writes the state, then sends on the cycle signal, then on the end signal. `cycle_start`/`cycle_end` attributes stay where they are (`Running`, `Current`); `Open` gets none.

- [ ] **Step 1 (test first):** a test that listens on both signals of an appliance's `running` and records, at each call, the entity's state from `hass.states`. When a cycle ends: the cycle signal first, then the end signal, and the state is already `off` at both. Run it against today's code: it passes (a characterization of the order). Then show it RED by perturbing `Running` to send the signals before writing the state. Restore.
- [ ] **Step 2:** `CycleSource`; the four classes inherit it and call `_send`; delete their own `_signals` and loops. `Current` (modes) sends per item: `_send` takes the item from the entity.
- [ ] **Step 3:** the contract test gains `test_a_capability_is_carried_by_a_cycle_source`: for each builder with `Provides`, build its example (the `features` fixture's `ha`) and check the entity at `Provides.key` is a `CycleSource`.
- [ ] **Step 4:** `uv run pytest -q` → all pass. Commit `pururu: CycleSource sends a cycle once, for every source (refactor B)`.

### Task 2: `vocabulary.trigger`

**Files:** `core/vocabulary.py` (gets `trigger`, moved from `device_keys/reactions.triggers` as is), `device_keys/reactions.py`, `device_keys/notifications.py` (stops importing `reactions`), and the tests that call `reactions.triggers`.

- [ ] Point `tests/test_reactions.py`'s helper (line ~260, `reactions.triggers(...)`) at `module("core.vocabulary").trigger`, and watch it fail. Move the function as is, with today's signature, `trigger(reaction: Mapping[str, Any], entity_id: str | None) -> list[dict[str, Any]]`. `reactions.automation` and `notifications.automation` call it. Then `uv run pytest -q`, and commit `pururu: the state trigger is the vocabulary's (refactor B)`.

### Task 3: `Aspect`, `mount`, and the statistics aspect

**Files:**
- Create `aspects/__init__.py` (`ASPECTS`) and `aspects/statistics.py` (`Meter`, `PERIODS`, `PERIOD_LIST` moved from `features/cycle/statistics.py`; `ASPECT`).
- Modify `core/feature.py` (`Aspect`), `core/roles.py` (`Counters`), `setup/catalogue.py` (`mount`, `keys()` adds the offered aspects' keys with `by=<aspect key>`), `setup/schema.py`, `setup/build.py` (the offered aspects' builds after the builder's).
- Every builder with statistics: `features/appliance/__init__.py`, `features/opening/__init__.py`, `features/modes/__init__.py`, `device_keys/programs.py`, `device_keys/reactions.py`. Each loses its `statistics` schema, its meters in `entity_keys` and its `Meter` loop, and gains `Counters`.
- The translations (`en.json`, `pt-BR.json`) and `icons.json`: the meters' keys become the aspect's.
- Tests: `tests/test_statistics.py` (new), `tests/test_features.py` (the aspect rules).

**Produces:**

```python
# core/roles.py
@dataclass(frozen=True)
class Counters:
    needs: Mapping[str, str | None]            # counter -> the setting it needs (None: always)
    mount: Literal["block", "item"] = "block"

# core/feature.py
@dataclass(frozen=True, kw_only=True)
class Aspect:
    key: str                                                  # "statistics"
    offered: Callable[[Feature], bool]
    schema: Callable[[Feature, str], Callable[[Any], Any]]    # (builder, its key in the device)
    keys: Callable[[Feature], Mapping[str, Platform]]         # local keys it can add (suffixes for Items)
    example: Callable[[Feature], Any]
    build: AspectBuild | None = None
    generates: Callable[[str, Feature, Any], Iterable[tuple[str, str]]] | None = None

# setup/catalogue.py
def mount(builder: Feature, key: str, value: Any) -> Any
    # the block validated: each offered aspect's key taken out and validated by it; the rest by the builder's schema
```

Roles:

| Builder | `Counters` |
|---|---|
| `appliance` | `{"runtime": None, "cycles": None, "idle_energy": "energy"}` |
| `door`, `window` | `{"openings": None, "open_time": None}` |
| `modes` | `{"runtime": None, "cycles": None, "energy": "energy"}`, `mount="block"` (the meters repeat per mode) |
| `programs` | `{"runtime": None, "cycles": None}`, `mount="item"` |
| `reactions` | `{"triggered": None}`, `mount="item"` |

The totals stay the builder's (`<counter>_total`: the builder's inner state feeds them). The aspect builds only the meters, `<counter>_<period>` or `<slug>_<counter>_<period>`, each metering the `<counter>_total` entity of its block or item. A counter whose `needs` setting is missing is refused with today's text, `statistics.<counter> needs <setting>`.

- [ ] **Step 1 (tests first):**
  - `tests/test_statistics.py`, one test per builder in the table: a device asking a meter per period has, for every period, the same entity ID and unique ID as today, and the same name as today in `en` and `pt-BR`. Read the names from `hass.states` with the language set: the `ha` fixture has `hass.config.language`; set `pt-BR` in one parametrized case. Run against today's code: they pass (characterization).
  - The contract rules (`test_features.py`), over `builders() × ASPECTS`. They fail until `Aspect` exists:
    - an aspect's keys are named and have an icon, once per aspect;
    - each offered aspect's `example` validates through `mount` and builds;
    - the builder's schema alone refuses each offered aspect's key;
    - a `Configured` builder offers no block-level aspect;
    - `f"{c}_total"` is one of the builder's keys (for an `Items` builder, one of `Items.keys`);
    - a counter without its needed setting is refused.
- [ ] **Step 2:** `Counters`, `Aspect`, `ASPECTS = (statistics.ASPECT,)`.
  - `mount` is used by `schema._device` for every builder in place of `partial(_feature_block, …)`. It takes an offered aspect's key out of the block, or out of each item when `Counters(mount="item")`.
  - `catalogue.keys` adds each offered aspect's keys, expanded per item for an `Items` builder, with `by` set to the aspect's key.
  - `build.build` runs each offered aspect's `build` after the builder's own, with the same device in the builder's namespace.
  - Move the five copies of the meters into `aspects/statistics.py`.
  - The meters' translation keys become `<counter>_<period>` and `item_<counter>_<period>`, with placeholder `{item}`.
  - Today `PururuEntity._identify` (`core/entity.py`) sets `translation_key = device.qualified(entity_key)` and, with an item, the placeholder `{<namespace>: item.name}`. Add a keyword-only `translation: str | None` to `_identify`: when given, it is the translation key, and the item's placeholder is `{"item": item.name}`. `Meter` passes `translation=f"{counter}_{period}"` (or `f"item_{counter}_{period}"`). Every other entity is unchanged.
- [ ] **Step 3:** `uv run pytest -q` → all pass, the characterization tests of Step 1 included. Commit `pururu: statistics is an aspect, written once (refactor B)`.

### Task 4: The alerts aspect, and `alerts` as a device key

**Files:**
- Create `aspects/problem.py` (`ProblemAlert`, `Alert`, the shared alert schema, from `features/alerts.py`), `aspects/elapsed.py` (from `features/elapsed.py`), and `aspects/alerts.py` (`ASPECT`, the ready-made alerts, from `features/presets.py`, plus the device key `ALERTS`, from `features/alerts.py`).
- Delete `features/alerts.py`, `features/elapsed.py`, `features/presets.py`.
- Modify `features/__init__.py` (`alerts` leaves `FEATURES`), `device_keys/__init__.py` (`DEVICE_KEYS = {alerts, programs, reactions}`), `outputs/alert2_alerts.py` and `outputs/alert_lights.py` (import `aspects/problem`), `core/feature.py` (`ALERTS_KEY` stays), `setup/schema.py`.
- Tests: `tests/test_alerts.py` and `tests/test_presets.py` (module paths only), plus the new tests below.

- [ ] **Step 1 (tests first):**
  - A device with `alerts` and only `programs` is refused with "a device needs at least one feature (…)". Today it passes; RED.
  - `test_features.py`: `alerts` is in `DEVICE_KEYS`, not in `FEATURES`, and a device with only `alerts` is refused.
- [ ] **Step 2:**
  - Move the modules as they are (AST identical apart from imports, like A2-layout).
  - `aspects/alerts.ASPECT`: `offered = role(Presets) is not None`; its schema is today's `settings_schema(presets)`; its keys are `preset_keys(presets)`, taken out of the builder's `entity_keys`; its build is today's `presets.build`.
  - The "is now a notification" redirect goes (D13); remove its test and the troubleshooting line.
  - The device key `ALERTS` keeps `Configured(Platform.BINARY_SENSOR)` and `Refers`.
  - `checks.references` keeps refusing an alert on an alert: `by == "alerts"` now comes from the aspect, and `builder == "alerts"` from the device key.
- [ ] **Step 3:** `uv run pytest -q` → all pass. Commit `pururu: ready-made alerts are an aspect; alerts is a device key (refactor B)`.

### Task 5: The notifications aspect and one automations kind

**Files:**
- Create `aspects/notifications.py` (from `device_keys/notifications.py`: `ASPECT` with `generates`, `plan()`).
- Delete `device_keys/notifications.py`.
- `setup/generate.py`:
  - gets `SCRIPTS` (today's `programs.KIND`, moved) and `AUTOMATIONS` (file `pururu/automations/automations.yaml`, data key `automations`, issue `automations_not_included`, `source="reactions and notifications"`);
  - one sync of `reactions.plan(...).items + notifications.plan(...).items`, with the reactions' held.
- `setup/checks.py`: `_generated_ids` walks the offered aspects' `generates`.
- `setup/listener.py` and `setup/lifecycle.py`: the kinds.
- The translations: `notifications_not_included` goes; `automations_not_included`'s title and description stop saying "reactions' automations".
- Tests: `tests/test_generated.py` reads both kinds from `generate`, plus `tests/test_notifications.py` and `tests/test_reactions.py` where they name a kind or a file.

- [ ] **Step 1 (tests first):**
  - A device with a reaction and a ready-made notification writes both to `pururu/automations/automations.yaml`, and `entry.data["automations"]` has both IDs. RED: two files today.
  - `test_features.py`: each `Happening` generates its automation. The kinds' data keys are distinct, and none is `floors` or `areas`.
- [ ] **Step 2:** the moves and the one kind. `entry.data["notifications"]` stays, unread (D13).
- [ ] **Step 3:** `uv run pytest -q` → all pass. Commit `pururu: notifications are an aspect; one automations kind (refactor B)`.

### Task 6: The whole layer table

**Files:** `tests/test_code.py`.

The table, in folders:

| Folder | May import |
|---|---|
| `core/` | `core/`, `const` |
| `features/<x>` | `core/`, `const`, its own package, `features/cycle`, `features/standing`; `features/__init__` imports every feature |
| `aspects/` | `core/`, `const`, `features/cycle`, another `aspects/` module |
| `device_keys/` | `core/`, `const`, `features/cycle`, `aspects/alerts` (in `__init__`), a sibling |
| `outputs/` | `core/`, `const`, `aspects/problem`, `features/lights` |
| `setup/` | everything |
| root | `setup/` and `const`; the platforms only `core.runtime` |

Only `aspects/statistics.py` imports `homeassistant.components.utility_meter`.

- [ ] **Step 1:** replace `NEVER` with the table (`ALLOWED`); each folder's rule is checked. Watch it fail once per row by perturbation, then restore.
- [ ] **Step 2:** commit `tests: the whole layer table (refactor B)`.

### Task 7: Docs, coverage, review, PR

- [ ] **Step 1: Docs.**
  - `docs/features/alerts.mdx` → `docs/concepts/alerts.mdx` (hand-written and ready-made, one page); a new `docs/concepts/statistics.mdx` (the aspect: periods, where it mounts, the names).
  - `docs.json` (sidebar); `docs/reference/configuration.mdx`; `troubleshooting.mdx` (the redirect goes, the "needs at least one feature" case with `alerts`); `docs/concepts/notifications.mdx` (the one file).
  - `CLAUDE.md` Architecture (aspects, `mount`, `ASPECTS`, the one kind); `docs/develop/architecture.mdx`, `writing-a-feature.mdx` (offering an aspect: `Counters`, `Presets`, `Happenings`), `index.mdx` (the tree), `testing.mdx`.
  - `pnpm docs:check`.
- [ ] **Step 2:** Coverage per function against A2b's.
- [ ] **Step 3:** The final whole-branch review (opus); fix **every** finding, minors included, each behaviour fix with a test that failed first (ask the user only if one is absurd).
- [ ] **Step 4:** Open the PR `pururu: refactor B, aspects (0.2.0)` with the `greptile` label. Put the manual step in its text:

  > Before updating, remove every `notifications:` block and reload pururu: their automations and registry entries go. The new kind would otherwise find them registered under the old data key and treat them as the user's. Update, delete `pururu/automations/reactions.yaml` and `pururu/automations/notifications.yaml` (HA loads every file in the folder, and they'd repeat `automations.yaml`'s IDs), and restart. Put the `notifications:` blocks back and reload.
