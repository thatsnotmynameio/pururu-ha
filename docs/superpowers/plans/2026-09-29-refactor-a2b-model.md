# Refactor A2b: the model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the builders one model: roles instead of nine optional fields, one index of every entity key a device can create with one way to find a reference in it, the house's rules as one list of checks with paths, and each generated kind planned by its owner.

**Architecture:**
- **Roles.** `core/roles.py` holds small frozen dataclasses. `Feature` keeps five fields plus `roles`, and code asks for a role by type (`feature.role(Configured)`): the Extension Object pattern.
- **The index.** `core/resolve.py` has `Ref`, `Target`, `Index` and `find`. `setup/catalogue.index(devices)` builds the index once. It replaces `referable` and `entity_keys` and their callers' tuples.
- **The checks.** `setup/schema.CHECKS` holds the rules over the whole house. Each runs as `check(house, index, builders)` and raises `vol.Invalid` with a path, and each rule lives in its owner's module.
- **The plans.** `core/generated.Planned` is what a kind's `plan()` returns (items, held, targets). `plan()` moves into `programs.py`, `reactions.py` and `notifications.py`, so `setup/generate.py` only wires them.

Behaviour identical, apart from the order in which errors surface and the path each error carries. **Error texts are kept verbatim**, so tests and the troubleshooting page stay.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3, voluptuous, pytest, ruff, mypy strict, uv.

**Spec:** `docs/superpowers/specs/2026-09-29-yaml-contract-coherence-design.md`: Part 3 ("A builder is composed of roles", "Other types", "Flow: validate, plan, apply") and PRs → A2b.

**Base:** stacked on `refactor/a2-layout` (PR #46); retargeted to `main` once #46 merges.

## Global Constraints

- Version stays `0.2.0` (`manifest.json`).
- `uv run pytest` green at every commit. `tests/test_ids.py` unchanged and passing. Per-function coverage not lower than A2-layout's (`.superpowers/sdd/2026-09-29-refactor-a2-layout/coverage-after.json`).
- Existing tests change only where they build a `Feature` or read a removed field, or assert on a removed function. No assertion is weakened, and error texts asserted today stay verbatim.
- Layers (`tests/test_code.py`): `core/` imports only `core/` and `const`; `features/` imports no `device_keys`, `outputs` or `setup`; `device_keys/` and `outputs/` import no `setup` and not each other. A check in an owner's module gets the builders and the index as arguments, so it never imports `setup`.
- Simple on purpose: a type exists only if it deletes a duplication that exists today; no role before its reader.
- Commits end with the two attribution lines. The PR opens only after the local final review is done and its findings fixed, with the `greptile` label (Claude reviews by itself on opening; `claude-review` after each push).

## Review Focus

1. **A reference resolved on the wrong device or namespace.** A reaction's `device:` + `when:`, and a light group's `{device: [key]}`, must find the other device's entity, with its current (renamed) entity ID. `Target.current_entity_id` must use the builder's namespace, not the referrer's.
2. **The `by`/`item`/`actions` filters.** An alert may watch neither a ready-made alert (`by == "alerts"`) nor a hand-written one (`builder == "alerts"`). A reaction may not watch its own statistics (same device, `builder == "reactions"`, `item == its key`), while another reaction's statistics are fine. A program's step needs the target's builder to take the action.
3. **A check's path.** A check moved from `_device` to `CHECKS` must still say which device: `path=[CONF_DEVICES, key, …]`. HA shows it as `pururu->devices->washer->…`.
4. **Held versus not generated.** A reaction whose program is held is held. One whose program isn't generated is dropped (logged). The `scripts` mapping plus `held` set must keep the two apart.
5. **`inputs` of a device key.** With `Generates`, `programs` gets only its scripts' IDs and `reactions` only its automations'. Before, both got every owned ID; a lookup by its own ID must still hit.

---

## Types (Task 1 and Task 2 produce them; later tasks consume them)

```python
# core/roles.py
@dataclass(frozen=True)
class Provides:            # until D: a capability others take through <capability>_from
    capability: str
    key: str               # the local entity key carrying it

@dataclass(frozen=True)
class Requires:            # until D
    capability: str

@dataclass(frozen=True)
class Configured:          # entity keys are the block's keys, named by each `name`
    platform: Platform

@dataclass(frozen=True)
class Actions:             # what a program's step may do to its entities
    actions: tuple[str, ...]

@dataclass(frozen=True)
class Items:               # the block is a map of items with entity keys of their own
    keys: Mapping[str, Platform]               # per item: "<slug>_<suffix>"
    items: Callable[[Any], Iterable[Item]]

@dataclass(frozen=True)
class Refers:              # what its validated block refers to; build() gets their current IDs in inputs, by the reference's text
    refers: Callable[[Any], Iterable[Ref]]

@dataclass(frozen=True)
class Presets:             # ready-made alerts
    presets: Mapping[str, Preset]

@dataclass(frozen=True)
class Happenings:          # ready-made notifications
    happenings: Mapping[str, Happening]

@dataclass(frozen=True)
class Generates:           # (domain, object ID) of what it writes to a generated kind, from (device key, block)
    generates: Callable[[str, Any], Iterable[tuple[str, str]]]

type Role = Provides | Requires | Configured | Actions | Items | Refers | Presets | Happenings | Generates

# core/feature.py
@dataclass(frozen=True, kw_only=True)
class Feature:
    schema: Callable[[Any], Any]
    entity_keys: Mapping[str, Platform]
    build: Build
    example: Mapping[str, Any]
    namespace: str
    roles: tuple[Role, ...] = ()

    def role[R: Role](self, kind: type[R]) -> R | None:
        return next((r for r in self.roles if isinstance(r, kind)), None)

# core/resolve.py
@dataclass(frozen=True)
class Ref:
    device: str | None     # None: this device
    key: str               # a qualified entity key: appliance_running

    @property
    def text(self) -> str:  # inputs are keyed by it: "appliance_running", "washer.appliance_running"
        return self.key if self.device is None else f"{self.device}.{self.key}"

@dataclass(frozen=True)
class Target:
    device: Device         # in the builder's namespace
    key: str               # qualified entity key
    platform: Platform
    builder: str           # the builder's key in the device
    by: str | None         # "alerts" for a ready-made alert's key; None: the builder's own
    item: str | None       # the item owning the key (a mode, program, reaction)
    actions: tuple[str, ...]

    @property
    def local(self) -> str: ...                       # the key without the namespace
    @property
    def unique_id(self) -> str: ...                   # device.object_id(local)
    def entity_id(self) -> str: ...                   # as created
    def current_entity_id(self, hass) -> str: ...     # renamed or not

type Index = Mapping[str, Mapping[str, Target]]       # device key -> qualified key -> Target

def find(index: Index, here: str, ref: Ref) -> Target | None
    # the target, or None when that device can't create the key; the caller says why, in its own words

# core/generated.py
@dataclass(frozen=True)
class Planned:
    items: list[Item]
    held: frozenset[str]
    targets: frozenset[str]
```

---

### Task 1: Roles

**Files:**
- Create: `core/roles.py`.
- Modify: `core/feature.py` (the nine fields go, plus `roles` and `role()`). Every builder: `features/appliance/__init__.py`, `features/opening/__init__.py`, `features/modes/__init__.py`, `features/phases.py`, `features/switches.py`, `features/lights.py`, `features/alerts.py`, `device_keys/programs.py`, `device_keys/reactions.py`.
- Modify the readers: `setup/catalogue.py`, `setup/checks.py`, `setup/build.py`, `setup/schema.py`, `features/presets.py`, `device_keys/notifications.py`.
- Tests: `tests/test_features.py` (read roles; the role rules), and every test that builds a `Feature` (`tests/test_init.py`'s `watch` and others: `grep -rn "Feature(" tests`).

Each builder's roles:

| Builder | Roles |
|---|---|
| `appliance` | `Provides("cycle", "running")`, `Presets(PRESETS)`, `Happenings(HAPPENINGS)` |
| `door`, `window` | `Provides("cycle", "open")` |
| `modes` | `Requires("cycle")`, `Items(PER_MODE, …)` |
| `phases` | `Requires("cycle")` |
| `switches` | `Configured(Platform.SWITCH)`, `Actions(("turn_on", "turn_off", "toggle"))` |
| `lights` | `Configured(Platform.LIGHT)`, `Actions(("turn_on", "turn_off", "toggle"))` |
| `alerts` | `Configured(Platform.BINARY_SENSOR)`, `Refers(_refers)` (still returns the qualified keys as `str` until Task 2) |
| `programs` | `Items(PER_PROGRAM, _items)` |
| `reactions` | `Items(PER_REACTION, _items)` |

- [ ] **Step 1: The contract's role rules first** (`tests/test_features.py`). These are new tests that fail until roles exist:
  - `test_each_role_at_most_once`: `len({type(r) for r in f.roles}) == len(f.roles)`.
  - `test_configured_and_items_never_together`.
  - `test_a_device_key_neither_provides_requires_nor_acts`: `DEVICE_KEYS` builders have no `Provides`, `Requires` or `Actions`.
  - `test_ready_made_keys_are_the_builders`: every `Preset.watches`, `Elapsed.since_key` and `Happening.watches` is in `entity_keys`.

  The existing contract tests read roles: `named_keys` is `entity_keys` plus `Items.keys`; `provides` is `Provides`; and so on. Run `uv run pytest tests/test_features.py -n 0 -q`. Expected: fails (`Feature` has no `roles`).
- [ ] **Step 2:** `core/roles.py` and `Feature`. `roles.py` imports `Item`, `Preset` and `Happening` from `.feature` under `TYPE_CHECKING`; `feature.py` imports `Role` the same way. Convert every builder per the table. Convert every reader: `feature.configured` → `(c := feature.role(Configured))` and `c.platform`; `feature.alerts` → `p.presets if (p := feature.role(Presets)) else {}`; and so on. Keep the behaviour identical; `grep -rnE "\.(provides|requires|configured|refers|actions|per_item|items|alerts|notifications)\b" custom_components tests` must show no field use left.
- [ ] **Step 3:** `uv run pytest -q` → all pass.
- [ ] **Step 4:** Commit `pururu: a builder is its roles (refactor A2b)`.

### Task 2: The index and `find`

**Files:**
- Create: `core/resolve.py` and `tests/test_resolve.py`.
- Modify: `setup/catalogue.py` (`keys()` replaces `entity_keys()`; `index()` replaces `referable()`), `features/alerts.py` (`_refers` returns `Ref(None, when)`), `setup/build.py` (`_inputs` and `follows` through the index), `setup/generate.py` (`_acted_on` and `_watched` through the index), `setup/checks.py` (every `referable`/`entity_keys` user).

- [ ] **Step 1: Unit tests of the index and `find`** (`tests/test_resolve.py`, through `helpers.module("core.resolve")` and `module("setup.catalogue")`). Build the index of a two-device house (`washer`: appliance with `alerts: {offline: …}` and a program; `lights`: `lights: {teto: …}` and a reaction). Check each case:
  - `find(index, "washer", Ref(None, "appliance_running"))` is the appliance's `Target`: `builder == "appliance"`, `by is None`, `item is None`, `platform == Platform.BINARY_SENSOR`, `unique_id == "pururu_washer_appliance_running"`.
  - `Ref(None, "appliance_alert_offline")` has `by == "alerts"`.
  - `Ref("lights", "light_teto")` from `washer` is the other device's light with `actions == ("turn_on", "turn_off", "toggle")`.
  - `Ref(None, "program_clean_cycles_total")` has `item == "clean"`, `builder == "programs"`.
  - An unknown key gives `None`. An unknown device gives `None`.
  - `current_entity_id` follows a rename in the registry.
  - `Ref("washer", "appliance_running").text == "washer.appliance_running"`, and the local ref's text is the key.

  Expected: fails (no `core.resolve`).
- [ ] **Step 2:** `core/resolve.py` as in Types. Then `catalogue.keys(config)` (today's `entity_keys`, with `by` and `item` added: `(builder, local key, platform, by, item)`) and `catalogue.index(devices) -> Index`. `by` is `"alerts"` when the local key is in `preset_keys(Presets.presets)`. `item` is the item's slug for the keys `Items` repeats. `actions` is the builder's `Actions`, or `()`.
- [ ] **Step 3:** Switch every caller of `referable`/`entity_keys` to the index, and delete both:
  - `build.build` gets the device's index and resolves `entity.follows` with it: `Target.unique_id` and `Target.current_entity_id`.
  - `_inputs` resolves each `Refers` ref, keyed by `ref.text`.
  - `generate._acted_on` and `_watched` use `find`.
  - `checks.references_resolved`, `reactions_on_this_device`, `programs_on_this_device`, `entity_ids_distinct` and `_reaction_resolved` use the index.
  - The texts don't change.
- [ ] **Step 4:** `uv run pytest -q` → all pass. Commit `pururu: one index of what a device can create, and find (refactor A2b)`.

### Task 3: `Generates`

**Files:** `device_keys/programs.py`, `device_keys/reactions.py`, `setup/checks.py` (`_generated_ids`), `setup/generate.py` (`owned`, `watched_items`), `setup/build.py` (`_inputs` of a device key), `tests/test_features.py`.

- [ ] **Step 1: Test first.** `test_features.py::test_a_generating_builder_generates_from_its_example`: for each builder with `Generates`, `generates("dev", schema(example))` yields `(domain, id)` pairs whose IDs start with `pururu_dev_`. Also a test in `tests/test_programs.py`: a program's `Runs` still counts its script when the device also has a reaction (the device key's `inputs` hold only its own IDs, and the lookup still hits). Run; expected: the first fails (no `Generates`).
- [ ] **Step 2:** `programs.STATISTICS` gets `Generates(lambda key, config: (("script", script_id(key, p)) for p in config))`, and `reactions.STATISTICS` gets its automations the same way.
  - `checks._generated_ids` walks the builders' `Generates` and keeps the notifications' case, which B makes an aspect's.
  - `generate.watched_items` and `owned` walk `Generates`.
  - `build._inputs` of a builder with `Generates` gives it the owned IDs of what it generates, and nothing for a builder without.
- [ ] **Step 3:** `uv run pytest -q` → all pass. Commit `pururu: what a device key generates is its Generates role (refactor A2b)`.

### Task 4: `CHECKS` at the domain level, with paths

**Files:**
- `setup/schema.py`: `_device` keeps the structure, "at least one feature" and `capabilities_provided`.
- `CHECKS` and one validator, `_checked(house)`: it builds the index once and runs each check.
- `setup/checks.py` keeps the generic rules: `references` (the `Refers` builders' refs, and an alert watching an alert), `real_entities_distinct`, `entity_ids_distinct`, `generated_ids_distinct`, `areas_exist` and `messages_sent`.
- The owners' checks:
  - `device_keys/reactions.check`: today's `reactions_on_this_device`, `reactions_resolved` and own statistics.
  - `device_keys/programs.check`: today's `programs_on_this_device`.
  - `outputs/alert_lights.check`: today's `alert_lights_resolved`.
  - `outputs/places.floors_exist`, which takes the same arguments.
- Tests: `tests/test_schema.py` (new) or the owners' test files.

```python
type Check = Callable[[Mapping[str, Any], Index, Mapping[str, Feature]], None]
# raises vol.Invalid(message, path=[CONF_DEVICES, key, ...]); the message is today's, verbatim
CHECKS: tuple[Check, ...] = (
    places.floors_exist, checks.areas_exist, checks.generated_ids_distinct, checks.entity_ids_distinct,
    checks.references, checks.real_entities_distinct, reactions.check, programs.check,
    alert_lights.check, checks.messages_sent,
)
```

- [ ] **Step 1: Tests of the paths first.** For each moved check, a configuration it refuses: `CONFIG_SCHEMA` raises `vol.Invalid` whose `path` is `["pururu", "devices", "<key>", "<block>", …]`.
  - One test per owner: alerts' reference, a reaction's `when`, a program's step, a light group (`["pururu", "config", "alerts", "lights", "groups", "<group>"]`), and two devices' IDs.
  - The message is today's, word for word.
  - Expected: the devices' paths fail for the checks that were in `_device`: their path today stops at the device key, without the block.
- [ ] **Step 2:** Move each rule to its owner with the `Check` signature, and each raise with its path. `schema.CONFIG_SCHEMA` runs `vol.All(<structure>, _checked)`. Delete the per-device calls in `_device` except "at least one feature" and `capabilities_provided`.
- [ ] **Step 3:** `uv run pytest -q` → all pass. The existing tests' substring asserts still match; a test that depended on which of two errors surfaces first gets a ledger ruling. Commit `pururu: the house's rules are CHECKS, each in its owner, with paths (refactor A2b)`.

### Task 5: `Planned`, and each kind's `plan()` in its owner

**Files:**
- `core/generated.py` gets `Planned`.
- `device_keys/programs.plan` (from `generate.scripts` and `_acted_on`), `device_keys/reactions.plan` (from `generate.automations`, `_watched` and `_started`), `device_keys/notifications.plan` (today's `items`).
- `setup/generate.py`: `async_step` wires them.
- `tests/test_generated.py`, where it names moved functions.

```python
# programs.py
def plan(hass: HomeAssistant, devices: Mapping[str, Any], index: Index, created: Collection[str]) -> Planned
# reactions.py; scripts: (device key, program key) -> the script's current entity ID, for the scripts generated;
# held_programs: the (device key, program key) held while a target is disabled
def plan(hass, devices, index, created, scripts: Mapping[tuple[str, str], str],
         held_programs: Collection[tuple[str, str]], notify: Sequence[str]) -> Planned
# notifications.py
def plan(hass, devices, created, texts, notify) -> Planned   # held and targets empty
```

- [ ] **Step 1:** The tests that exercise these paths already exist (held, dropped, renamed script, notifications not created). Point any test that calls `generate.scripts`/`automations` or `notifications.items` at the new `plan()`, and watch it fail on the missing name.
- [ ] **Step 2:** Move the bodies as they are; `Planned` replaces the tuples. `generate.async_step`:
  1. `programs.plan`, then sync, then `targets.update(planned.targets)`;
  2. `scripts`: the generated scripts' current entity IDs, keyed by `(device, program)`;
  3. `held_programs`;
  4. `reactions.plan`, then sync;
  5. `notifications.plan`, then sync.

  `reactions` never imports `programs` beyond what it does today (`script_id`).
- [ ] **Step 3:** `uv run pytest -q` → all pass. Commit `pururu: each generated kind plans itself (refactor A2b)`.

### Task 6: `Built` gains the builders and the index

**Files:** `core/runtime.py`, `setup/lifecycle.py`, `setup/build.py`, `setup/generate.py`, `tests/test_lifecycle.py`.

- [ ] **Step 1: Test first.** `test_lifecycle.py::test_the_steps_read_one_index`: patch `catalogue.index` with `wraps` and set up two devices; it is called once per setup, and not once per device or per step. Expected: fails (called several times).
- [ ] **Step 2:** `Built` gets `builders: Mapping[str, Feature]` and `index: Index`. `lifecycle` builds the index once, before building, and hands it to `build.build` and to the steps. `generate.async_step` uses `built.index`.
- [ ] **Step 3:** `uv run pytest -q` → all pass. Commit `pururu: Built carries the builders and the index (refactor A2b)`.

### Task 7: Docs, coverage, review, PR

- [ ] **Step 1: Docs.**
  - `docs/develop/writing-a-feature.mdx`: a feature's roles, which replace the fields in its example.
  - `docs/develop/architecture.mdx`: roles, the index, `CHECKS`, `plan()`.
  - `docs/develop/testing.mdx`: `test_resolve.py`, the new contract rules.
  - `CLAUDE.md`, the Architecture bullets that name the removed fields (`per_item`, `items`, `refers`, `actions`, `configured`, `Feature.alerts`, `Feature.notifications`) and the checks.
  - `pnpm docs:check`.
- [ ] **Step 2:** Coverage per function against A2-layout's: nothing lost, and the new functions fully covered.
- [ ] **Step 3:** Local final review by a fresh reviewer on opus; fix the Critical and Important findings with tests.
- [ ] **Step 4:** PR against `refactor/a2-layout`, or against `main` if #46 has merged: `pururu: refactor A2b, the model: roles, index, checks, plans (0.2.0)`, with the `greptile` label (Claude reviews by itself on opening).
