# Refactor B2: the statistics aspect — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Statistics become one aspect. Today the meters per period are written five times: appliance, door/window, modes, programs, reactions. Each copy has its own `statistics` schema, its meter keys in its entity keys and its `Meter` loop. After B2 they are written once in `aspects/statistics.py`, mounted in every builder that has the new `Counters` role.

**Architecture:**
- **`Aspect`** (`core/feature.py`) is a small frozen dataclass: `key`, `offered`, `schema`, `keys`, `example`, `build`. `aspects/__init__.py` lists `ASPECTS = (statistics.ASPECT,)`.
- **Validation.** `setup/catalogue.mount(builder, name, value)` validates a builder's block for `_device`. It takes each offered aspect's key out of the block, or out of each item for `Counters(mount="item")`, and validates it with the aspect. The rest goes where it goes today:
  - a feature's block → `_feature_block`, moved from `setup/schema.py` into `catalogue` (it handles the ready-made alerts and notifications until B3 and B4);
  - a device key's block → its schema.
- **Building.** `catalogue.keys` adds the aspect's keys, per item for an `Items` builder, with `by="statistics"`. `build.build` runs each offered aspect's `build` after the builder's own.
- **What stays with the builder.** It still builds its totals (`<counter>_total`), which its inner state feeds. The aspect builds only the meters.

YAML, entity IDs, unique IDs, names and icons don't change.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3, voluptuous, pytest, ruff, mypy strict, uv.

**Spec:** `docs/superpowers/specs/2026-09-29-yaml-contract-coherence-design.md`:
- Part 1 ("A device is an object", "Placement rule": `statistics` mounted in the block or each item);
- Part 3 ("A builder is composed of roles": `Counters`; "Other types": `Aspect`; "Layers");
- PRs → B2.

**Base:** `main` after B1 merges (stacked on `refactor/b1-cycle-source` until then). Branch `refactor/b2-statistics`.

## Global Constraints

- Version stays `0.2.0`. `tests/test_ids.py` unchanged and passing.
- Names and icons shown don't change, in `en` and `pt-BR`. Verified before this plan: the meters fall into 36 groups (9 counters × 4 periods). Inside each group the text (with `{mode}`/`{program}`/`{reaction}` read as `{item}`) and the icon are the same for every builder, so one translation key per group keeps them:
  - block level: `<counter>_<period>` for `runtime`, `cycles`, `idle_energy`, `openings`, `open_time`;
  - per item: `item_<counter>_<period>` for `runtime`, `cycles`, `energy`, `triggered`, with the placeholder `{item}`.
- Error texts verbatim: `statistics.idle_energy needs energy`, `statistics.energy needs energy`, `a period is repeated: …`, voluptuous' own for an unknown period or counter. The paths may get longer, not shorter.
- Layers (`tests/test_code.py`):
  - `aspects/` imports only `core/`, `const`, `features/cycle` and other `aspects/` modules;
  - `features/` imports no `aspects/`;
  - only `aspects/statistics.py` imports `homeassistant.components.utility_meter`.
- Simple on purpose: `Aspect` exists because it deletes the five copies. Nothing for ready-made alerts or notifications yet: those are B3 and B4.
- `uv run pytest` green at every commit; per-function coverage not lower than B1's (`.superpowers/sdd/2026-09-29-refactor-b-aspects/coverage-after.json`), a moved function compared under its new name.
- Commits end with the two attribution lines. Never `git stash` (shared with other sessions). Every review finding gets fixed, minors included. The PR opens after the final review's fixes, with the `greptile` label.

## Review Focus

1. **A meter's name, icon and ID for every builder, both languages**, including a mode's (`{item}` must be the mode's name) and a reaction's.
2. **`mount` on the right blocks.**
   - A configured block (`switches`, `lights`, `alerts`) may have an item keyed `statistics`: `mount` must leave it alone (no `Counters`).
   - A program's or reaction's own `statistics` is taken out of each item, never the block's key.
   - A mode's `statistics` sits at the block and repeats per mode.
3. **`needs`.** `statistics.energy` without `energy` on `modes`, and `statistics.idle_energy` without it on `appliance`, are refused with today's text. Asking no period for that counter still passes without the setting.
4. **References to a meter** (an alert's or a reaction's `when: appliance_runtime_today`) still resolve: the key is in the index, `by="statistics"`, and nothing refuses it.
5. **A meter follows its total:** its source is the total's current entity ID (renamed or not), and it isn't created when the total isn't (`sources`).

---

### Task 1: Pin today's meters

**Files:** Create `tests/test_statistics.py`.

- [ ] **Step 1:** One test per builder, parametrized, with a device asking every counter for every period (`today`, `week`, `month`, `year`). Assert:
  - every meter's entity ID and unique ID, the full list: e.g. `sensor.pururu_<key>_appliance_runtime_today`, `sensor.pururu_<key>_mode_<slug>_cycles_week`, `sensor.pururu_<key>_program_<slug>_runtime_month`, `sensor.pururu_<key>_reaction_<slug>_triggered_year`, `sensor.pururu_<key>_door_openings_today`, `sensor.pururu_<key>_window_open_time_week`;
  - its `friendly_name` in `hass.states` with the language `en` and with `pt-BR` (set `hass.config.language` before `setup`; the device's name comes first in the friendly name);
  - its icon from the entity registry or state (the translated icon: read how tests elsewhere check icons, or assert `entity.icon`/the registry's `translation_key`-based icon through `homeassistant.helpers.icon`, whichever the repo already uses; if none, assert the translation key's icon from `icons.json` by reading `registry.async_get(entity_id).translation_key`).
  - Expected values come from today's `en.json`/`pt-BR.json`/`icons.json`, written as literals in the test (a few per builder, not all 52 per file: one per counter, two periods, both languages).
- [ ] **Step 2:** The refusals: `modes` with `statistics: {energy: [today]}` and no `energy` → `statistics.energy needs energy`. `appliance` with `statistics: {idle_energy: [today]}` and no `energy` → `statistics.idle_energy needs energy`. A repeated period → `a period is repeated`. An unknown period and an unknown counter are refused. Asking no period for `energy` without `energy` passes.
- [ ] **Step 3:** Run. They pass on today's code (they characterize it). Show that one name test and one refusal test would catch a change, by perturbation (copy the file aside with `cp`, edit, run, copy back; no git stash). Commit `tests: today's meters, pinned by name, icon and ID (refactor B2)`.

### Task 2: `Counters`, `Aspect`, `mount`, and the statistics aspect

**Files:**
- Create `aspects/__init__.py` (`ASPECTS`) and `aspects/statistics.py` (`PERIODS`, `PERIOD_LIST`, `Meter` moved from `features/cycle/statistics.py` as is, plus `ASPECT`). Delete `features/cycle/statistics.py`; everything that imported it imports `aspects.statistics` or stops needing it.
- Modify:
  - `core/roles.py` (`Counters`);
  - `core/feature.py` (`Aspect`, `AspectBuild`);
  - `core/entity.py` (`_identify(..., translation=...)`);
  - `setup/catalogue.py` (`mount`, with `_feature_block` moved in; `keys()` with the aspects' keys; `aspects_of(builder)`);
  - `setup/schema.py` (`_device` validates every builder with `partial(catalogue.mount, builder, name)`);
  - `setup/build.py` (the offered aspects' builds);
  - the five builders (appliance, opening, modes, programs, reactions: their `statistics` schema, the meter keys in `ENTITY_KEYS`/`PER_*` and the `Meter` loops go; `Counters` comes);
  - `translations/en.json`, `translations/pt-BR.json`, `icons.json` (the 52 meter keys per file become the 36 group keys, texts and icons unchanged);
  - `tests/test_features.py` (the aspect rules; `named_keys` without the meters).

**Produces:**

```python
# core/roles.py
@dataclass(frozen=True)
class Counters:
    """Totals it builds as <counter>_total; the statistics aspect meters them per period."""
    needs: Mapping[str, str | None]            # counter -> the setting of its block it needs (None: none)
    mount: Literal["block", "item"] = "block"  # where `statistics:` sits; with Items, the meters repeat per item either way

# core/feature.py
type AspectBuild = Callable[[HomeAssistant, Device, Feature, Any, Texts], list[PururuEntity]]
#   hass, the device in the builder's namespace, the builder, its validated block, the common texts

@dataclass(frozen=True, kw_only=True)
class Aspect:
    key: str                                                 # the block key it mounts: "statistics"
    offered: Callable[[Feature], bool]                       # does this builder offer it
    schema: Callable[[Feature], Callable[[Any], Any]]        # the aspect's value, for this builder
    keys: Callable[[Feature], Mapping[str, Platform]]        # local keys it adds (suffixes for an Items builder)
    example: Callable[[Feature], Any]                        # a valid value, for the contract test
    build: AspectBuild

# setup/catalogue.py
def aspects_of(builder: Feature) -> tuple[Aspect, ...]       # the ASPECTS it offers
def mount(builder: Feature, name: str, value: Any) -> Any    # the block validated, aspects' keys included
```

Roles:

| Builder | `Counters` |
|---|---|
| `appliance` | `Counters({"runtime": None, "cycles": None, "idle_energy": "energy"})` |
| `door`, `window` | `Counters({"openings": None, "open_time": None})` |
| `modes` | `Counters({"runtime": None, "cycles": None, "energy": "energy"})` (block; its `Items` repeats the meters per mode) |
| `programs` | `Counters({"runtime": None, "cycles": None}, mount="item")` |
| `reactions` | `Counters({"triggered": None}, mount="item")` |

The aspect:
- **`schema`:** `{vol.Optional(counter, default=[]): PERIOD_LIST for counter in needs}`, its own `vol.Schema`, so unknown counters are refused.
- **`needs`, checked by `mount` after the builder's schema:** a counter with periods whose setting isn't in the validated block raises `vol.Invalid(f"statistics.{counter} needs {setting}")`.
- **`keys`:** `{f"{counter}_{period}": SENSOR}` for every counter and period.
- **`build`:** for each counter and each asked period, a `Meter` of `f"{counter}_{period}"`, metering the current entity ID of `f"{counter}_total"`:
  - per item, for an `Items` builder: the item's own `statistics` with `mount="item"`, the block's with `mount="block"`;
  - its `translation` is `f"{counter}_{period}"`, or `f"item_{counter}_{period}"` for an item.
- **`_identify(..., translation=t)`:** the translation key is `t`, and with an item the placeholder is `{"item": item.name}`. Without `translation`, everything is as today.

- [ ] **Step 1 (tests first):** the contract rules in `tests/test_features.py`, over `catalogue.builders() × ASPECTS`. They fail until `Aspect` exists:
  - `test_an_aspects_keys_are_named_once`: every key an aspect can add is named, with an icon, in both languages, under `<key>` or `item_<key>`, and never under a builder's namespace;
  - `test_an_offered_aspect_validates_and_builds`: the builder's example plus the aspect's example goes through `mount`, and the aspect's `build` returns entities;
  - `test_a_builders_own_schema_refuses_an_aspects_key`: `builder.schema({**example, "statistics": {}})` is refused, and for `mount="item"` inside an item;
  - `test_a_configured_builder_offers_no_block_aspect`;
  - `test_a_counter_is_totalled`: `f"{c}_total"` is in `entity_keys`, or in `Items.keys` for an `Items` builder;
  - `test_a_counter_without_its_setting_is_refused`.

  Then Task 1's tests must still pass unchanged after Step 2.
- [ ] **Step 2:** the implementation above.
  - Move `Meter`, `PERIODS` and `PERIOD_LIST` as they are.
  - `mount` takes the aspect's key out before the rest reaches the builder's schema (which refuses it), and puts the validated value back where it was: in the block, or in each item.
  - `catalogue.keys` expands an aspect's keys per item for an `Items` builder (`item.key(suffix)`, `item=slug`), with `by="statistics"`.
  - `build.build` runs `aspect.build(hass, device, builder, block, texts)` for each offered aspect, with the same `follows`/`sources` handling as the builder's entities.
  - The 52 translation and icon entries per file become 36 group keys, with texts and icons copied from today's.
- [ ] **Step 3:** `uv run pytest -q` → all pass, Task 1's tests unchanged among them. `tests/test_code.py`'s `NEVER` gains `"aspects": {"device_keys", "outputs", "setup"}`, and `features` gains `"aspects"`. The test checking only `aspects/statistics.py` imports `utility_meter` is new; watch it fail by perturbation. Commit `pururu: statistics is an aspect, written once (refactor B2)`.

### Task 3: Docs, coverage, final review, PR

- [ ] **Step 1: Docs.**
  - A new `docs/concepts/statistics.mdx`: what `statistics:` does, the periods, where it sits (a feature's block, each program, each reaction, a `modes` block per mode), the names. Add it to `docs.json`. Point the feature pages' statistics sections at it (appliance, door, window, modes; `concepts/programs.mdx`, `concepts/reactions.mdx`); each page keeps its own counters.
  - `docs/reference/configuration.mdx` where it describes `statistics`.
  - `CLAUDE.md` Architecture: aspects, `ASPECTS`, `mount`, `Counters`.
  - `docs/develop/architecture.mdx`: aspects.
  - `writing-a-feature.mdx`: offering statistics = `Counters`, the totals the builder builds, the translation keys the aspect owns. The contract table gets the new rules.
  - `index.mdx` (the tree: `aspects/`), `testing.mdx` (`test_statistics.py`).
  - `pnpm docs:check`.
- [ ] **Step 2:** Coverage per function against B1's; nothing lost.
- [ ] **Step 3:** The final whole-branch review (opus). Every finding fixed, minors included, each behaviour fix with a test that failed first.
- [ ] **Step 4:** Open the PR `pururu: refactor B2, statistics as an aspect (0.2.0)` with the `greptile` label, based on `main` (or on `refactor/b1-cycle-source` while B1 is open).
