---
title: Button Statistics - Plan
type: feat
date: 2026-10-01
topic: button-statistics
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# Button Statistics - Plan

## Goal Capsule

- **Objective:** The author can see how often each button of a device is used: an all-time count per button that survives restarts, and, when asked in the YAML, how many times it was used today, this week, this month or this year.
- **Means:** the reactions pattern repeated on `buttons`: a per-button `triggered_total` sensor fed by the button's own press, metered by the statistics aspect (KTD1–KTD3).
- **Product authority:** the author's decisions in the 2026-10-01 brainstorm, recorded as Key Decisions; the R-IDs govern behaviour, the KTDs govern mechanism. Counters for `switches` and `lights`, and a rule that every feature must count, are not active scope.
- **Stop conditions:** stop and ask if counting a press would require changing what a press is (the press guards of `docs/plans/2026-09-30-2015-feat-buttons-plan.md`, its R6 and R8), or if the role-model rewrite in KTD3 would let a block-level aspect key into a `Configured` block.
- **Execution profile:** one branch and one PR titled `pururu: buttons, …`; the manifest stays at 0.2.0 (KTD6).
- **Open blockers:** none.

---

## Product Contract

Product Contract preservation: Product Contract unchanged, except Outstanding Questions, whose two items are resolved in place by KTD1 and KTD3.

### Summary

Each button in `buttons:` gets an all-time `triggered` total, like each reaction's. A `statistics:` block inside a button asks for that total's meters per period, with the same periods and validation as every other `statistics:`.

### Problem Frame

A button's state is the time of its last press, so the history shows when it was last pressed but not how often. Every other pururu piece that happens again and again already counts: an appliance's cycles, a door's openings, a program's runs, a reaction's triggers. Buttons shipped without counting. The buttons plan deferred it as the next step (`docs/plans/2026-09-30-2015-feat-buttons-plan.md`, Scope Boundaries).

### Key Decisions

- **The counter is named `triggered`, not `presses`.** It is the name reactions already use for "it happened once", so switches and lights can take the same word later without a new vocabulary. (session-settled: user-directed — chosen over `presses`, `count`, `uses` and `activations`: a generic name shared across features.) Governs R1, R3.
- **One total per button, no device-wide total.** What the counts show is which button gets used. (session-settled: user-approved — chosen over a total across a device's buttons: what matters is which button is used.) Governs R1.
- **A press is a press, wherever it comes from.** The buttons plan settled that a press on the remote and a press in Home Assistant are the same press, so both count. (session-settled: user-approved — chosen over counting only physical presses: the buttons plan made both the same press.) Governs R2.

### Requirements

**Counting**

- R1. Each button of a device's `buttons:` has its own all-time `triggered` total sensor, created with no YAML beyond the button itself (for example `sensor.pururu_<device>_button_<key>_triggered_total`).
- R2. The total grows by one on every press of its button: a press from the sensor taking its value, or a press in Home Assistant, whether or not the press starts the button's program.
- R3. The total keeps its value across restarts and reloads, and never goes down.
- R4. While the button entity is disabled, its total does not grow, since a disabled button follows no sensor.

**Statistics per period**

- R5. A button takes an optional `statistics:` block, `{triggered: [today, week, month, year]}`, with any subset of the periods, each at most once, exactly as a reaction's.
- R6. Each period asked creates one meter of that button's total, named with the button's name, and it resets when the period turns over.
- R7. An unknown counter or period in a button's `statistics:` is refused at setup, as anywhere else `statistics:` sits.

**Documentation**

- R8. `docs/features/buttons.mdx` documents the total and the `statistics:` block. `docs/concepts/statistics.mdx` and `docs/concepts/entity-ids.mdx` list buttons with their entity IDs.

### Acceptance Examples

- AE1. **Covers R1, R2.** **Given** a device `sala` with a button `luz` and no `statistics:`, **when** the remote's sensor changes into the button's value twice and the button is pressed once in Home Assistant, **then** `sensor.pururu_sala_button_luz_triggered_total` reads 3.
- AE2. **Covers R2.** **Given** a button whose program's script is already running, **when** it is pressed, **then** the program is not started again and the total still grows by one.
- AE3. **Covers R3.** **Given** a total of 7, **when** Home Assistant restarts and nobody presses, **then** the total reads 7.
- AE4. **Covers R5, R6.** **Given** `statistics: {triggered: [today, month]}` in button `luz`, **when** it is pressed once, **then** the `today` and `month` meters both read 1, and no `week` or `year` meter exists.
- AE5. **Covers R7.** **Given** `statistics: {presses: [today]}` in a button, **then** setup refuses the configuration and names the path.

### Scope Boundaries

**Deferred for later**

- Counters for `switches` and `lights` (times turned on, time on). They would reuse `triggered` where it fits.
- A rule, checked by the contract test, that every feature must declare counters.
- A ready-made alert for a button that hasn't been used in a while.
- A total across all buttons of a device.

**Considered and not built**

- Counting only presses a person made (excluding automations and scripts calling `button.press`). R2 counts every press; evidence that would change it: the author wanting the remote's use apart from automated presses.
- Lifting reactions' `TriggersTotal` into a shared base. Buttons reuse `CyclesTotal` instead (KTD2); merging the two count totals is a refactor nobody asked for.

### Dependencies / Assumptions

- The author did not say what the counts are for. Assumed: seeing each button's use in the history and on the dashboard. Nothing in the requirements depends on a particular use.

### Sources / Research

- `custom_components/pururu/device_keys/reactions.py`: `PER_REACTION`, `_item_at`, `COUNTERS` and `TriggersTotal`, the per-item pattern to repeat.
- `custom_components/pururu/aspects/statistics.py`: the statistics aspect, mounted at every `Counted` place of a builder with `Counters`; `_named` gives an item's meters the shared `item_<counter>_<period>` translations.
- `custom_components/pururu/features/cycle/totals.py`: `CyclesTotal`, the restored TOTAL_INCREASING count whose `_watch` a self-counting subclass overrides.
- `custom_components/pururu/aspects/programs.py`: `Runs`, the precedent for a `CyclesTotal` subclass that counts itself.
- `custom_components/pururu/features/buttons.py`: `Button.async_press`, which every press reaches; HA's `ButtonEntity._async_press_action` is `@final` and calls it after recording the press's time.
- `docs/plans/2026-09-30-2015-feat-buttons-plan.md`: the buttons plan, which deferred "Statistics of the buttons: press counts and period meters (the next step)".

---

## Planning Contract

### Key Technical Decisions

- KTD1. **The press is counted at the top of `Button.async_press`, before its early returns, and reaches the total through a dispatcher signal.** HA's `_async_press_action` is `@final` and calls `async_press` on every press, from the UI and from the sensor alike, so the top of `async_press` sees each one (R2, AE2). A signal per button (`device.object_id` of the button's item key plus a suffix, a `SignalType[None]`) decouples the two entities: a disabled button never presses and a disabled total has no listener (R4). Watching the button's state was ruled out: its state is the press time, so two presses at one instant are one change, and a restore is a change that is no press.
- KTD2. **The total is a `CyclesTotal` subclass in `features/buttons.py` that listens to the press signal.** `CyclesTotal` already restores as an int, is TOTAL_INCREASING and never decreases (R3); `Runs` shows the override of `_watch`. `features/` cannot import reactions' `TriggersTotal` (layer table in `tests/test_code.py`), and lifting it into a shared base is out of scope (Scope Boundaries). Its entity key is `triggered_total` as an item key of the button, so the ID is `sensor.pururu_<device>_button_<key>_triggered_total` (R1, session-settled `triggered`: governs R1, R3).
- KTD3. **`buttons` takes `Items({"triggered_total": SENSOR}, one item per button)` and `Counters(Counted(needs={"triggered": None}, at=(EACH,), item=…))`, and the role model narrows two contract rules instead of forbidding them.** The runtime (`catalogue.keys`, `mount`, `checks.keys_distinct`, build) already copes with a builder that is both `Configured` and `Items` and offers statistics at `(EACH,)`. The two rules become:
  - `test_configured_and_items_never_together` → a `Configured` builder with `Items` yields exactly one item per block key, its slug the key.
  - `test_a_configured_builder_offers_no_block_aspect` → no aspect place of a `Configured` builder sits at the block's own level (`path == ()`); a switch keyed `statistics` stays a switch.

  `Configured`'s docstring changes from "all on this platform" to "its block's keys are entity keys on this platform; per-item keys (Items) may add others". `statistics` stays out of the button's own item schema, so the builder's schema still refuses it and the aspect takes it (R5, R7).
- KTD4. **Names reuse reactions' wording.** The total is translated as `button_triggered_total`, "{button} triggers" / "Disparos de {button}", unit "triggers"/"disparos", icon `mdi:gesture-tap`. The meters use the shared `item_triggered_<period>` translations, so no `Counted.named`. This follows the settled `triggered` word (governs R1); a button-specific wording would be a new decision nobody asked for.
- KTD5. **A button that isn't built doesn't build its total.** The total declares the button as its source (`build.creatable`). Two cases:
  - A button on a pururu sensor is skipped by the build, and its total in the same branch. Its meters, built by the aspect, are dropped by creatable's "watches …, which this device's settings don't create" line.
  - A button whose ID another integration holds is built, then marked missing; its total and meters are dropped by the "follows …, which is not created" line.
- KTD6. **The manifest stays at 0.2.0.** `v0.2.0` is tagged and the unreleased 0.2.0 work ships with the 0.2.1 release the refactor spec reserves for its last PR (`docs/superpowers/specs/2026-09-29-yaml-contract-coherence-design.md`); a bump here would collide with it.

### Implementation Constraints

- Keep the press guards of the buttons plan untouched: counting starts where a press already happened, it adds no path that presses.
- A button keyed so that one of its keys equals another button's total or meter (`luz_triggered_total`, or `luz_triggered_today` beside a button `luz`, whether or not `luz` asks for `today`) is now refused by `checks.keys_distinct`; that is the existing rule, documented, not a new check.

### Assumptions

- The two rewritten contract tests protect the same invariants as before (a block's keys are entity keys; no block-level aspect in a `Configured` block). Planning assumes no other code reads "Configured and Items never together" as a rule; research found only the tests and the develop docs.

### Sequencing

U1 (roles and contract) before U2 (total and counting); U3 (docs) last.

---

## Implementation Units

### U1. Buttons count: roles and the contract test

**Goal:** `buttons` declares its per-button total and its statistics place, and the contract test accepts that shape while keeping the invariants it protects.

**Requirements:** R1, R5, R7; KTD3.

**Dependencies:** none.

**Files:**
- `custom_components/pururu/features/buttons.py`
- `custom_components/pururu/core/roles.py`
- `tests/test_features.py`
- `tests/test_statistics.py`

**Approach:**
1. In `features/buttons.py`, add the item helpers (`Item(slug=key, name=button["name"])`, an `ItemOf` for the statistics place) and the roles `Items({"triggered_total": Platform.SENSOR}, …)` and `Counters((Counted(needs={"triggered": None}, at=(EACH,), item=…),))`, beside `Configured(Platform.BUTTON)`.
2. Update `Configured`'s docstring in `core/roles.py` per KTD3.
3. Rewrite `test_configured_and_items_never_together` and `test_a_configured_builder_offers_no_block_aspect` per KTD3; add `buttons` to the pinned sets in `test_a_counter_is_totalled` and `test_the_aspects_each_builder_offers`.

**Patterns to follow:** `device_keys/reactions.py` (`_item`, `_item_at`, `COUNTERS`, `Items(PER_REACTION, _items)`).

**Test scenarios:**
- The rewritten Configured+Items test passes for `buttons` and fails for a builder whose items aren't one per block key.
- The rewritten aspect test passes for `buttons` (place at `(EACH,)`) and fails for a `Configured` builder with a place at `()`.
- `test_mount_leaves_an_items_key_alone` still passes: a button keyed `statistics` is a button.
- Covers AE5. A button with `statistics: {presses: [today]}` is refused and the error names the path.
- A button with `statistics: {triggered: [today, today]}` is refused (a repeated period).

**Verification:** `tests/test_features.py` and `tests/test_statistics.py` pass with `buttons` among the counting builders.

### U2. The total and its counting

**Goal:** every press of a button adds one to its restored total, and its asked meters meter it.

**Requirements:** R1, R2, R3, R4, R5, R6; KTD1, KTD2, KTD4, KTD5.

**Dependencies:** U1.

**Files:**
- `custom_components/pururu/features/buttons.py`
- `custom_components/pururu/translations/en.json`
- `custom_components/pururu/translations/pt-BR.json`
- `custom_components/pururu/icons.json`
- `tests/test_buttons.py`
- `tests/test_statistics.py`
- `tests/fixtures/house_ids.json`

**Approach:**
1. Add the press signal helper and send it at the top of `Button.async_press`, before any return (KTD1).
2. Add the total, a `CyclesTotal` subclass whose `_watch` connects to the button's press signal; `source` is the button's entity key (KTD2, KTD5).
3. In `build`, add each built button's total; skip it in the pururu-sensor branch (KTD5).
4. Add `button_triggered_total` to both translations and to the icons (KTD4).
5. Update the six `held(...)` assertions in `tests/test_buttons.py` that pin a device's entity set, and regenerate the ID snapshot with `PURURU_UPDATE_IDS=1` (additions only).

**Patterns to follow:** `aspects/programs.py` `Runs` (a `CyclesTotal` that counts itself); `tests/test_reactions.py` counting tests; `tests/test_statistics.py` `test_reactions_meters`; `tests/test_appliance.py` restore with `restart(...)`.

**Test scenarios:**
- Covers AE1. Two sensor presses (with a change back between them) and one `button.press` make the total read 3.
- Covers AE2. A press while the program's script runs starts nothing and still adds one.
- A press of a button with no program adds one.
- Covers AE3. Restored at 7, the total reads 7 after a restart with no press, and 8 after one press.
- A reload keeps the total.
- R4. With the button disabled in the registry and the entry reloaded, the sensor taking the value adds nothing.
- Two presses at the same frozen instant add two.
- A sensor write that is no press (rewritten value, restored state, from `unavailable`) adds nothing.
- Covers AE4. `statistics: {triggered: [today, month]}` creates the `today` and `month` meters, both at 1 after a press, and no `week` or `year`.
- The total's friendly name is "<button name> triggers" in English and "Disparos de <button name>" in pt-BR, with its icon; a meter's is the shared `item_triggered_*` name.
- A button on a pururu sensor with `statistics: {triggered: [today]}` builds neither the button, its total nor its meter, and the meter's "watches …, which this device's settings don't create" line is logged.
- A button whose ID another integration holds drops its total, with the "follows …, which is not created" line.
- A button keyed `luz_triggered_total` beside a button `luz` is refused as two entities with one ID.

**Verification:** `tests/test_buttons.py`, `tests/test_statistics.py` and `tests/test_ids.py` pass; the ID snapshot diff only adds button totals.

### U3. Docs

**Goal:** the guide and the develop docs describe the total, the button's `statistics:` and the narrowed role rules.

**Requirements:** R8; KTD3.

**Dependencies:** U2.

**Files:**
- `docs/features/buttons.mdx`
- `docs/concepts/statistics.mdx`
- `docs/concepts/entity-ids.mdx`
- `docs/reference/configuration.mdx`
- `docs/develop/architecture.mdx`
- `docs/develop/writing-a-feature.mdx`
- `docs/develop/testing.mdx`
- `CLAUDE.md`

**Approach:**
1. `buttons.mdx`: the total in "Entity", `statistics:` in "Settings", a "Statistics" section mirroring `docs/concepts/reactions.mdx`, and the key collision rule (Implementation Constraints).
2. `statistics.mdx`: buttons in "Where it sits", the counters table and the entities list; `entity-ids.mdx`: the buttons row gains the total; `configuration.mdx`: where `statistics` sits.
3. Develop docs and `CLAUDE.md`: the narrowed `Configured` rules (KTD3) and the contract-test rows.

**Test expectation:** none -- documentation; `pnpm docs:check` covers links and MDX.

**Verification:** `pnpm docs:check` passes and no page still says `Configured` and `Items` never go together.

---

## Verification Contract

| Gate | Command | Proves |
|---|---|---|
| Feature tests | `uv run pytest tests/test_buttons.py tests/test_statistics.py -n 0 -q` | U2 behaviour |
| Contract | `uv run pytest tests/test_features.py -n 0 -q` | U1 role model |
| IDs | `uv run pytest tests/test_ids.py -n 0` | snapshot only adds totals |
| Whole suite | `uv run pytest` | everything, plus ruff, format, mypy, hassfest, quality scale |
| Release | `python3 release.py check` | 0.2.0 still valid |
| Docs | `pnpm install` then `pnpm docs:check` | no broken links |

## Definition of Done

- Every R-ID is covered by a unit, and every AE by a named test.
- The whole suite, release check and docs check pass, with no unexpected `Step … failed` or `Listener failed` log.
- The two rewritten contract tests still fail for the shapes they used to forbid that remain forbidden (items not one per key; a block-level aspect).
- The manifest is still 0.2.0.
- No dead-end or experimental code from abandoned attempts remains in the diff.
