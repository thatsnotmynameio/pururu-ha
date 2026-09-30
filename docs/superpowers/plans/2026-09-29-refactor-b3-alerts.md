# Refactor B3: the alerts aspect, and `alerts` as a device key — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ready-made alerts (`offline`, `no_power`, `long_cycle`, `no_cycle`) become an aspect, and hand-written `alerts` becomes a device key, next to `programs` and `reactions`. Both share one entity class (`ProblemAlert`) and one settings schema, in `aspects/`.

Today:
- `features/alerts.py` holds the hand-written alerts' feature and the shared alert classes;
- `features/elapsed.py` holds `ElapsedAlert`;
- `features/presets.py` holds the ready-made alerts' validation and build;
- `outputs/alert2_alerts.py` and `outputs/alert_lights.py` import `features.alerts` (L3 importing L1);
- `alerts` counts as a feature, so a device with only `alerts` and `programs` passes with no feature.

**Architecture** (the spec's Part 1 "`alerts` in two places is one aspect with two mounting points", and Part 3 "Package"):
- `aspects/problem.py`: `ProblemAlert`, `Alert`, `NOTIFY`, `lights_group` and the alert schema shared by the ready-made and the hand-written.
- `aspects/elapsed.py`: `ElapsedAlert`.
- `aspects/alerts.py`:
  - `ASPECT`, the ready-made alerts: offered by a builder with `Presets`, its value the block's `alerts`, its keys `alert_<name>`, its build today's `presets.build`;
  - the device key `ALERTS`, today's `features.alerts.ALERTS`, moved into `DEVICE_KEYS`.

`features/alerts.py`, `features/elapsed.py` and `features/presets.py` go. The YAML users write doesn't change, and neither do entity IDs, names, the Alert2 file or the alert lights.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3, voluptuous, pytest, ruff, mypy strict, uv.

**Spec:** `docs/superpowers/specs/2026-09-29-yaml-contract-coherence-design.md`: Part 1 ("Why hand-written `alerts` becomes a device key", "`alerts` in two places…"), Part 3 ("Package", "Layers", "Other types": `Aspect`), D4, D13, PRs → B3.

**Base:** `main` after B2 merges (it brings `Aspect`, `ASPECTS`, `catalogue.mount`, `aspects/`), stacked on `refactor/b2-statistics` until then. Branch `refactor/b3-alerts`. Opened as a draft once Task 1 is done; each task pushed with `claude-review`; `greptile` only when ready.

## Global Constraints

- Version stays `0.2.0`. `tests/test_ids.py` unchanged and passing: every alert's `(platform, unique_id)`, hand-written (`binary_sensor.pururu_<key>_alert_<name>`) and ready-made (`binary_sensor.pururu_<key>_appliance_alert_<name>`).
- Names, texts and the Alert2 file (`pururu/alert2/alerts.yaml`) unchanged. The alert lights still find every `ProblemAlert`.
- Error texts verbatim, except the two the spec changes:
  - D13: `presets.validate`'s redirect "{name} is now a notification: …" goes. `alerts: {finished: …}` is then refused with the ordinary unknown-alert message.
  - D4: a device with `alerts` and only `programs`/`reactions` is refused with the existing "a device needs at least one feature (…)", listing only real features (`alerts` no longer among them).
- Layers (`tests/test_code.py`):
  - `aspects/` imports only `core/`, `const`, `features/cycle`, another `aspects/` module;
  - `outputs/` may import `aspects/problem` and `features/lights`, nothing else of L1/L2;
  - `device_keys/__init__` may import `aspects/alerts`;
  - `features/` imports no `aspects/`.
- The alert checks keep their texts and paths: an alert watching an alert (`by == "alerts"` from the aspect, `builder == "alerts"` from the device key); a reference that isn't another builder's key; a missing light group.
- `uv run pytest` green at every commit; per-function coverage not lower than B2's; a moved function is compared under its new name.
- Commits end with the two attribution lines. Never `git stash`. Every review finding fixed, minors included. The PR opens after the final review's fixes, with the `greptile` label.

## Review Focus

1. **The shared schema.**
   - A ready-made alert's settings are `for` (its preset's default, or required), `priority`, `notify`, `lights`.
   - A hand-written alert's are `name`, `when`, a condition, an optional `for`, `priority`, `notify`, `lights`.
   - One schema for what they share; nothing a user could write before is refused now, except D13's redirect.
2. **`alerts` as a device key.**
   - It is validated through `catalogue.mount` like `programs`.
   - It no longer counts toward "at least one feature".
   - `checks.references` still refuses an alert on an alert and on its own block, now that `builder == "alerts"` is a device key.
3. **The ready-made alerts' keys.**
   - They leave the builder's `entity_keys` and come from the aspect.
   - `catalogue.keys` gives them `by="alerts"`. Its current way, `preset_keys` in `entity_keys` marked by name, goes.
   - A reaction may still watch them (`when: appliance_alert_offline`).
4. **Who imports `ProblemAlert`:** `outputs/alert2_alerts.py` and `outputs/alert_lights.py` from `aspects.problem`, and every `isinstance` check still sees both kinds.
5. **Translations and icons:** the ready-made alerts' entity names and icons stay under their builder's namespace (`appliance_alert_offline`), and so do their default texts (`common`); only the code that reads them moves.

---

### Task 1: Move the alert modules into `aspects/`

A pure move, like A2-layout: `git mv`, imports rewritten, no body changed.

**Files:**
- `features/alerts.py` → `aspects/problem.py` (`ProblemAlert`, `Alert`, `NOTIFY`, `lights_group`, the schema) and `aspects/alerts.py` (the device key `ALERTS`, its `build`, `_refers`). The split is one file into two, with no body changed.
- `features/elapsed.py` → `aspects/elapsed.py`.
- `features/presets.py` → `aspects/alerts.py` (with the device key).
- Imports: `features/__init__.py` (`alerts` leaves `FEATURES`), `device_keys/__init__.py` (`DEVICE_KEYS` gains `alerts`), `features/appliance/__init__.py` and `features/appliance/alerts.py` (their `PRESETS` stay: they're the appliance's), `outputs/alert2_alerts.py`, `outputs/alert_lights.py`, `setup/build.py`, `setup/catalogue.py`, `setup/schema.py`, and the tests' `module("features.alerts"/"features.presets"/"features.elapsed")`.
- Sonar resource keys that name a moved file.

- [ ] **Step 1 (test first):**
  - A device with `alerts` and only `programs` is refused with "a device needs at least one feature (…)". Today it passes, so it's RED.
  - `test_features.py`: `alerts` is in `DEVICE_KEYS`, not in `FEATURES`.
- [ ] **Step 2:**
  - The moves. `alerts` leaves `FEATURES` and enters `DEVICE_KEYS`: its roles stay `Configured(BINARY_SENSOR)` and `Refers`, which the contract test allows for a device key (no `Provides`, `Requires` or `Actions`).
  - `schema._device` validates it through `catalogue.mount`, as B2 does for every builder.
  - "At least one feature" lists `FEATURES` only.
- [ ] **Step 3:** `uv run pytest -q` → all pass. Verify the move as A2-layout did: each moved function's AST is identical apart from imports (compare `ast.dump` with `ImportFrom` stripped, old vs new, per function name). Commit `pururu: the alert modules live in aspects/; alerts is a device key (refactor B3)`.

### Task 2: The ready-made alerts become an aspect

**Files:** `aspects/alerts.py` (`ASPECT`), `aspects/__init__.py` (`ASPECTS` gains it), `setup/catalogue.py` (`_feature_block` no longer handles `alerts`; `keys()` stops reading `preset_keys` from `entity_keys`), `features/appliance/__init__.py` (`entity_keys` without `preset_keys(PRESETS)`), `core/feature.py` (`preset_keys` stays if the aspect uses it, else goes), `setup/build.py` (the ready-made alerts come from the aspect's build like the statistics'; the special case goes), tests.

- **`ASPECT`** (B2's `Aspect` shape: `key`, `offered`, `schema(builder, name)`, `keys`, `named(builder, key)`, `example`, `placed`, `build(hass, device, builder, block, texts)`, `check(builder, name, container)`):
  - `key="alerts"`, `offered = builder.role(Presets) is not None`, `placed = "block"`;
  - `schema(builder, name)`: today's `settings_schema(presets)`; `name` is the builder's key in the device, for its messages;
  - `keys`: `{f"alert_{name}": BINARY_SENSOR}`;
  - `named(builder, key)`: the key under the builder's namespace (`appliance_alert_offline`), where the ready-made alerts' names and icons are today. Unlike the statistics aspect, whose keys sit outside every namespace. The contract test reads `named`, so it holds both.
  - `example`: `{<first preset>: {"for": {"hours": 1}}}` when it has no default `for`, else `None`;
  - `build`: today's `presets.build`, reading the aspect's value in `block["alerts"]` (it gets the builder's whole block) and the texts;
  - `check`: none (`None`).
- **An absent `alerts` key:** B2's `mount` mounts an absent aspect key as `{}` (right for statistics, whose counters default to no period). For ready-made alerts, absent must mean *no alert enabled*: check `mount` doesn't enable anything, or give the aspect a way to say "absent is nothing".
- **D13:** the redirect "is now a notification" goes, with its test and its troubleshooting line.

- [ ] **Step 1 (tests first):**
  - B2's contract rules now also run over the alerts aspect (names and icons once, the example validates and builds, the builder's own schema refuses `alerts`, a configured builder offers none). Watch the ones that don't hold yet fail.
  - `alerts: {finished: …}` on an appliance is refused with the unknown-alert message: RED, since today it gives the redirect.
- [ ] **Step 2:** the aspect; the special cases in `_feature_block`, `build` and `catalogue.keys` go.
- [ ] **Step 3:** `uv run pytest -q` → all pass. Commit `pururu: ready-made alerts are an aspect (refactor B3)`.

### Task 3: Docs, coverage, final review, PR

- [ ] **Step 1: Docs.**
  - `docs/features/alerts.mdx` → `docs/concepts/alerts.mdx`: one page for hand-written and ready-made alerts, since `alerts` is a device key, not a feature. Update `docs.json`, the links to it (`grep -rn "features/alerts" docs`), and `tests/test_alert2.py`'s `ALERTS_PAGE`.
  - `docs/reference/troubleshooting.mdx`: the redirect goes; the "needs at least one feature" case with `alerts`.
  - `docs/reference/configuration.mdx`.
  - `CLAUDE.md` Architecture: `alerts` a device key; ready-made alerts an aspect; `aspects/problem`.
  - `docs/develop/*`: the tree, architecture, `writing-a-feature.mdx` ("Ready-made alerts": a builder offers them with `Presets`, and the aspect does the rest).
  - `pnpm docs:check`.
- [ ] **Step 2:** Coverage per function against B2's.
- [ ] **Step 3:** The final whole-branch review (opus). Every finding fixed, minors included.
- [ ] **Step 4:** Open the PR `pururu: refactor B3, alerts as an aspect and a device key (0.2.0)` with the `greptile` label.
