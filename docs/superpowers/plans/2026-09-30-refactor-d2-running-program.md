# Refactor D2: the running program replaces running, modes and phases — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The appliance builds its required `running_program` with D1's detector (`features/cycle/program`). A detected program is a band of the power (`above`/`below`, `on_delay`/`off_delay`), and its `phases` are bands too, with the built-in `other`. It replaces four things:
- the appliance's `running:` block and its `threshold`;
- the `modes` and `phases` features (`features/modes/`, `features/phases.py`);
- `cycle_from`;
- the roles `Provides`/`Requires` and the capability check.

The appliance's own entities keep their IDs: `appliance_running` (now the carrier), its last cycle, its totals and its meters. Phases get the IDs D1 built: `appliance_phase_<key>`, `appliance_phase_<key>_<suffix>`, `appliance_phase_current`, `appliance_phase_last`. `statistics:` moves into `running_program` (the appliance's `runtime`, `cycles`) and into each phase (and `other`), mounted by B's statistics aspect, which learns to sit at a path in a block. `idle_energy` stays in the appliance's block. The ID snapshot changes on purpose, for today's modes and phases only.

D2 stops before D3: no `programs: {detected, executable}`, no `Programs` role, no `aspects/programs.py`, and `programs:` at the device stays a flat map of executable programs.

**Architecture:**
- **The appliance** (`features/appliance/`): `running_program` is validated by `program.SCHEMA` (a name refused), and `build` calls `program.build(..., key="running", reading=power, energy=energy)`, so the carrier is `binary_sensor.pururu_<device>_appliance_running`. The appliance still builds the program's own cycle entities (last cycle, `cycles_total`, `runtime_total`, idle energy) from `running`, as D1 ruling 13 says. `features/appliance/running.py` goes.
- **A new role, `Derived(of)`** (`core/roles.py`): entity keys a validated block adds beyond `entity_keys`. The appliance's are its phases' (`program.keys_of`): `phase_current`, `phase_last`, and each phase's (`other` too) `phase_<key>` and `phase_<key>_<suffix>`. `catalogue.keys()` lists them, so the index knows them: an alert, a reaction or `when:` can name `appliance_phase_current`.
- **Aspects at places** (`core/feature.py`): an aspect no longer sits in "the block or each item". It sits at **places**: a `Place` is a path from the block (`()`, `("running_program",)`, `("running_program", "phases", EACH)`), with the schema, keys, names, example, item and check the aspect has there. `Aspect.places(builder, name)` replaces `schema`, `keys`, `named`, `example`, `placed` and `check`. `walk(block, path)` finds the containers a path names. `catalogue.mount`, `_split`, `_put`, `_checked` and `keys` walk paths. The alerts and notifications aspects sit at `()`, as today.
- **`Counters` becomes a tuple of `Counted` places** (`core/roles.py`): each place has its counters (`needs`), its path, the item a container there is (a program, a phase) and, for the phase `other`, its own translation prefix. The appliance's are its block (`idle_energy`), `running_program` (`runtime`, `cycles`: the appliance's totals, IDs unchanged), each phase and `other` (`runtime`, `cycles`, `energy`). `program.counted(at)` gives a detected program's three places, so D3 reuses it for `programs: detected:`.
- **What goes:** `features/modes/`, `features/phases.py`, `features/appliance/running.py`, `Provides`, `Requires`, `checks.capabilities_provided`, `build._inputs`' capability branch, and the translations and icons of `mode_*`. Door and window lose `Provides("cycle", "open")`: nothing takes their cycle any more (a door's opening as a detected program is "Not in 0.2.0").
- **A new check, `checks.keys_distinct`:** two entities of one device with one unique ID are refused. A phase's binary sensor is `phase_<key>` alone, so phase `gelar_cycles_today`'s would be phase `gelar`'s meter `phase_gelar_cycles_today`.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3, voluptuous, pytest (pytest-homeassistant-custom-component), ruff, mypy strict, uv, docs.page (pnpm).

**Spec:** `docs/superpowers/specs/2026-09-29-yaml-contract-coherence-design.md`:
- Part 4: "The model", "In the YAML", "What goes", "In the code", "Decided when D starts" 1–6;
- PRs: rows D1–D3, "Why this order", A1's ID-snapshot rule (D updates `tests/test_ids.py` on purpose for modes and phases only);
- "The whole contract, 0.2.0", "Compatibility", "Tests" #2 and #6.

D1's plan, `docs/superpowers/plans/2026-09-30-refactor-d1-detector.md`, and its Rulings 1–22 hold unless a ruling here says otherwise.

**Base:** `main` at 9fd851e (D1 merged, #56). `refactor/d2-running-program` is cut from it. The plan names D1's code as merged. D1's final review changed four things this plan relies on, none of them a name it uses:
- a setup failing after the forward, or cancelled (`except BaseException`), unloads its platforms, then raises (D1 ruling 22);
- every parser of a time read back drops an impossible date through `core/entity.as_time` (D1 ruling 15): the detector's snapshot, `CycleStart.from_dict`, the runtime totals' `cycle_start`/`cycle_end`, the elapsed alerts, the openings' events;
- the carrier follows the reading once its entry's setup is over, whatever state follows (`SETUP_IN_PROGRESS` left: `LOADED`, or `SETUP_ERROR` with its platforms kept), and a carrier removed while it waits never starts (D1 ruling 15);
- the entry listener is set up as a guarded step, logged `Listener failed` (D1 ruling 22).

The names Task 1 consumes are unchanged at 9fd851e: `program.SCHEMA`, `program_of`, `build(hass, device, program, *, key, reading, energy)`, `phase_keys`, `FIXED`, `NAMED`, `COUNTERS`, `Phase.item`. `program.keys_of` is new (Task 2).

## Global Constraints

- Version stays `0.2.0` in `custom_components/pururu/manifest.json`. Only the last PR of the refactor, C, sets `0.2.1`. `python3 release.py check` passes at every commit.
- `uv run pytest` green at every commit: ruff, ruff format, mypy strict, hassfest, the layer table, the quality scale (`tests/test_code.py`).
- Layers (`tests/test_code.py`, unchanged): `features/cycle/program/` imports only `core/`, `const` and `features/cycle`; `features/appliance` imports `features/cycle/program`; `aspects/statistics.py` imports only `core/` and `const`. Nothing in `core/` names a concrete builder.
- `tests/fixtures/house_ids.json` changes only as Task 2 and Task 3 say: exactly the modes' and phases' IDs go and the new phases' come. Nothing else in the snapshot moves.
- Per-function coverage not lower than D1's. `main` (9fd851e) misses 15 lines in all; 5 of them are in modules D2 deletes (`features/appliance/running.py` 1, `features/modes/current.py` 3, `features/phases.py` 1), so D2 misses at most 10: `aspects/problem.py` 1, `core/vocabulary.py` 1, `outputs/alert_lights.py` 1, `outputs/dashboard.py` 2, `outputs/places.py` 3, `setup/lifecycle.py` 1, `setup/listener.py` 1. Measured the same way on both: `uv run pytest --cov=custom_components/pururu --cov-report=json:<file>`, `main`'s in a `git archive 9fd851e` scratch copy; each function compared by name (a moved function under its new name). Every new function is fully covered.
- Commits end with exactly:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM
  ```
- Never `git stash` (shared with other sessions), and never checkout, restore or reset the worktree's files. A RED against the old code runs in a scratch copy:
  - `git archive HEAD | tar -x -C <scratchpad>/<dir>`;
  - copy `.hassfest` and the new test in, then `uv sync --locked` there;
  - run it there, then delete the dir (`/tmp` is a small tmpfs).
- Every review finding fixed, minors included; ask when in doubt.
- pururu is public: no private setup anywhere (plan, code, tests, docs, commits, PR text). Real data only anonymised, as D1's `purifier_day.csv`. The owner's configuration appears only as the generic shapes of "The whole contract, 0.2.0".
- The PR flow (Greptile is out of it: the owner, 2026-09-30, its trial credits ran out; a PR merges on Claude's review at 5/5, green checks, Sonar at 0 issues and every review thread resolved):
  1. After Task 1: push, open a **draft** PR `pururu: refactor D2, the running program replaces running, modes and phases (0.2.0)`. Wait until `gh pr view <n> --json headRefOid -q .headRefOid` equals `git rev-parse HEAD`, then add `claude-review`.
  2. Each later task: push, wait for `headRefOid` again, add `claude-review` (remove it first if it's still there). Fix what the review finds before the next label.
  3. After the final review's fixes, once Claude's review is 5/5, the checks are green, Sonar shows 0 issues and every thread is resolved: `gh pr ready`.
  4. If `gh pr edit --add-label` fails with a GraphQL error: `gh api -X POST repos/thatsnotmynameio/pururu-ha/issues/<n>/labels -f 'labels[]=claude-review'`.

## Review Focus

The five places most likely to bite, each with the tests that pin it:

1. **The carrier replacing `Running` keeps every behaviour of the appliance's `running`.** Same IDs, the `cycle_start`/`cycle_end` attributes the ready-made `long_cycle` alert reads, `idle_energy` split at the same instants, the off_delay dated from when the power went down, a plug without a value holding the state. What changes: the restored extra data is the detector's snapshot, not a `CycleStart`, and the carrier follows the power only once its entry's setup is over (D1 ruling 15). Pinned: every test of `tests/test_appliance.py` and `tests/test_presets.py`, ported to `running_program` with their assertions unchanged (Task 1), and `test_an_old_running_restore_is_no_cycle` (Task 1).
2. **Mounting at a path.** `statistics:` is taken out of the block, of `running_program`, of each phase and of `other` before the builders' schemas see them, validated per place, put back at the same path, and checked against the builder's whole block (`energy`). A block, a program or a phase that isn't a map is refused cleanly; a phase keyed `statistics` is a phase. Pinned (Task 3): `tests/test_catalogue.py` (new), the contract test's place rules, `test_a_phases_energy_needs_the_appliances_energy`.
3. **IDs.** The appliance's own entities and meters keep their unique IDs, and a user's customisations of them survive (not removed as stale). Only the listed modes and phases IDs go. Pinned: `tests/test_ids.py` with the exact diff checked by a script (Tasks 2 and 3), `test_the_appliances_meters_keep_their_ids` (Task 3).
4. **What refers to a phase.** An alert on `appliance_phase_current`, on `appliance_phase_gelar` or on a phase's total; a reaction on a phase; a reference to a phase that isn't configured, or to `appliance_phase_current` on an appliance without phases, is refused at the configuration. Pinned (Task 2): `test_an_alert_can_watch_the_current_phase`, `test_an_alert_can_watch_a_phases_total`, `test_a_reaction_can_watch_a_phase`, `test_a_reference_to_a_phase_not_configured_is_refused`, `test_no_phase_keys_without_phases`, `test_a_derived_key_is_in_the_index`; a phase key that would be two entities (Task 3): `test_a_check_says_where[two entities of one device]`.
5. **Names.** Phase meters carry the phase's name (`{item}`); `other`'s are named by their own translations; the appliance's meters keep their names. A `mode_*` translation left over, or a meter without a name or an icon, fails the contract. Pinned: `test_statistics.py`'s name tests in en and pt-BR (Task 3), the contract's `test_an_aspects_keys_are_named_once` and `test_every_translated_entity_key_is_created`.

## Rulings

Where the spec is silent, decided here:

1. **Three code tasks, in this order:** the appliance's `running_program` first (Task 1), then `modes`/`phases`/`cycle_from`/`Provides`/`Requires` go (Task 2), then statistics at places (Task 3). Places can't express today's `modes` (one `statistics:` in the block, repeated per mode), and generalising for a feature Task 2 deletes would be waste; so modes go before places come. Between Tasks 2 and 3, phases have no meters and the `item_energy_*` translations have no user: Task 2 removes them, Task 3 puts them back unchanged. The snapshot changes twice: Task 2 removes the 41 modes and phases IDs and adds the phases' 52 entities; Task 3 adds their 72 meters (only additions).
2. **`running_program`'s delays are optional, 0 when absent** ("absent meaning at once, as every program"; D1 ruling 11 left it to D2). Today's `running` required both. `above` or `below` is required (D1's `bounded`); `running_program` may be a band with both.
3. **`running_program` takes no `name`**, refused with `running_program takes no name: it is the appliance running`. Its carrier is `appliance_running`, named by that key's translation ("Running"), as today. D1 ruling 10 allowed a program's name for D3's `detected:` items.
4. **The carrier keeps the entity key `running`** (`build(..., key="running")`): `appliance_running`'s entity ID, unique ID, translation and icon don't change. The program's own cycle entities stay the appliance's (D1 ruling 13), following `running`.
5. **What the carrier does differently from `Running`** (D1's rulings, now the appliance's), each encoded by a ported test:
   - a cycle starts at the moment its `on_delay` passed, however late the timer ran (D1 ruling 3); `Running` dated it when its timer ran. In the tests, `start_cycle` now ticks exactly the 60 s `on_delay` instead of 65 s, and every assertion stays;
   - a restored run needs a start: a snapshot whose start is an impossible date restores no cycle (D1 ruling 15), where `Running` stayed `on` without a start. `test_restart_with_an_impossible_start_restores_running` becomes `test_restart_with_an_impossible_start_is_no_cycle`;
   - the restored extra data is the detector's snapshot. `Running`'s (a `CycleStart`, as 0.1.23 saved it) isn't one: after the update, a cycle running during it is lost and the next reading starts a new one (D13: no migration code). The update step says to update while every appliance is stopped. Pinned by `test_an_old_running_restore_is_no_cycle`;
   - it follows the power only once its entry's setup is over (D1 ruling 15); a test that fakes `running`'s own state is meaningless now, since the carrier writes its state at every step (`test_modes.py`'s `test_no_mode_starts_while_the_cycle_is_unknown` goes in Task 1; Task 2 deletes the file).
6. **A new role, `Derived(of)`, lists the phases' keys**, not `Items` and not D3's `Programs`:
   - `Items` means "the block is a map of items" and names each suffix `<namespace>_<suffix>` with `{<namespace>}`. The appliance's block isn't one, a phase's binary sensor is its slug alone (`phase_<key>`), and D1 names phase entities `phase_<suffix>` with `{item}`, because `appliance_last_cycle_start` is already the appliance's own.
   - `Programs(reading, energy)` is D3's (spec "In the code"; the task's scope). `Derived` is a generic role (entity keys a validated block adds beyond `entity_keys`) that D3 may keep for `running_program` or fold.
   - The keys are listed only when `running_program` has phases: an alert on `appliance_phase_current` of an appliance without phases is refused at the configuration (`… is not an entity key of another feature of this device`), where today's `phases` entity keys were static.
7. **Aspects sit at places.** `Aspect.places(builder, name)` returns `Place`s; a `Place` bundles what an aspect has at one path (schema, keys, names, example, item, check). This replaces six callables of `Aspect` (`schema`, `keys`, `named`, `example`, `placed`, `check`). The alternative, a path argument added to each of them plus an `item` callable, changes as many signatures and reads worse. `walk(block, path)` finds the containers a path names; `EACH` stands for every key of a map. The alerts and notifications aspects have one place, `()`: nothing they do changes.
8. **`Counters` becomes a tuple of `Counted` places**, each with its counters, path, item and (for `other`) own names. `Counted.needs`' setting is looked up in the builder's **whole block**, not the container: a phase's `energy` counter needs the appliance's `energy`. Nothing changes for today's builders: their places are the block itself, or items whose counters need no setting.
9. **What each place of the appliance counts:**
   - the block: `idle_energy` (the plug's energy while no program runs, outside any program);
   - `running_program`: `runtime`, `cycles`, the appliance's own totals, so the meters keep their IDs (`appliance_runtime_today`) and names ("Runtime today"). No `energy` counter: `appliance_energy_total` is the plug's mirror, not a program total;
   - each phase and `other`: `runtime`, `cycles`, `energy` (needs the appliance's `energy`), the totals D1 built (`COUNTERS`).
10. **`other` takes `statistics`** (spec item 4: "the full set of phase entities and statistics"), in `running_program.other.statistics`; D1's `other:` took only delays. Its meters are named by their own translations, `phase_other_<counter>_<period>` (12 keys, en and pt-BR, with icons), as D1 ruling 6 names other's entities; `Counted(named="phase_other")` says so. To ask for them, `other:` is written.
11. **The appliance's example has one phase and `other: {}`** (Tasks 2 and 3), so the contract test reaches every place and every derived key. `other: {}` is valid and changes nothing but gives `other`'s place a container.
12. **A new check, `checks.keys_distinct`:** two entities of one device may not share a unique ID. The index is a map by qualified key and would silently keep one of them. Only phases can meet so today: a phase keyed `gelar_cycles_today` has the binary sensor `phase_gelar_cycles_today`, phase `gelar`'s meter's unique ID (on another platform). D1's `_apart` can't see meters (L1 doesn't know the periods). Refused with `device <key>: <unique ID> would be two entities`.
13. **D1's test-only builder retires in Task 1.** `tests/test_program_entities.py` runs on the real appliance and keeps its name: its tests are the detector's entities, whoever builds them. D1's `snapshot()` helper moves to `tests/helpers.py`, which every restart of `running` now needs.
14. **The modes' and phases' tests:** each scenario D1 replayed in `tests/test_program.py` (pure) or covered in `tests/test_program_entities.py` goes with its file; the rest is ported to the appliance's phases (Task 2 lists each test and where it went).
15. **Door and window drop `Provides("cycle", "open")`**: nothing takes their cycle any more. `test_opening.py`'s `test_the_openings_are_a_cycle_for_phases` goes (a door's opening as a detected program is "Not in 0.2.0"). The contract's cycle-source rule, which found carriers through `Provides`, becomes: what every last-cycle entity follows is a `CycleSource`.
16. **The Guide's concept page is `docs/concepts/detected-programs.mdx`** ("Detected programs and phases"), in the sidebar before "Programs". `concepts/programs.mdx` stays the executable programs' page until D3, which merges both into one programs page (spec PR D's docs).
17. **Events and the dashboard.** The events' `event_name` is `<device>.<qualified key>`: the phases' are `water_filter.appliance_phase_current`, `water_filter.appliance_phase_gelar_cycles_total`…, and the old `water_filter.mode_*` and `laundry_washer.phase_current` go with their IDs (D20). The dashboard lists floors, areas, devices and generated items, not entities: nothing changes. The listener's rename rule covers every entity of the entry, the phases' too: a renamed phase binary sensor reloads the entry, and its runtime total follows the new ID (`test_a_renamed_phase_is_followed`, Task 2).
18. **Translations:** `mode_*` (names, states, icons) go; `phase_current` stays (D1 owns it, with its states). No `phases` feature translation is left: `phase_current` is the detector's key since D1.
19. **`test_init.py`'s made-up `echo` goes with `Requires`** (Task 2). Its tests pin the mechanism D2 deletes: a capability reaching its feature, a renamed capability, what follows a provider not created, and two refusal params (`from a missing feature`, `from one that doesn't provide it`). The made-up `watch` (`Refers`) already pins the same three behaviours for references: `test_a_feature_gets_the_entity_key_it_refers_to`, `test_a_renamed_entity_reaches_what_refers_to_it`, `test_what_refers_to_an_entity_not_created_is_not_created_either`. `test_reload_that_drops_a_feature_removes_its_entities` drops `watch` instead of `echo`; `gauge` loses `Provides`.
20. **Two contract rules replace the capability rules** (Task 2, `tests/test_features.py`):
    - `test_what_a_last_cycle_follows_is_a_cycle_source` (ruling 15's rule): for each builder with `Counters`, built from its mounted example, each `LastCycleValue`'s source is a `CycleSource`. It reaches the appliance's `running`, `phase_heating` and `phase_other` (the example's phase and other, ruling 11), a door's and a window's `open`, and a program's `<key>_cycles_total` (`Runs`). It replaces `test_capabilities_line_up`, `test_a_capability_is_carried_by_a_cycle_source` and `test_the_other_cycle_sources_are_pinned_too` (whose `Runs` half it covers).
    - `test_a_derived_key_is_in_the_index`: a `Derived` builder's example derives keys, none of them in `entity_keys`, all listed by `catalogue.keys`, and its build creates only listed keys. The derived keys are named by the detector (`NAMED`, checked by `test_the_detectors_keys_are_named`), not in the builder's namespace, so `named_keys` leaves them out.
21. **The manual update step goes in the PR text** (the owner, 2026-09-30), and PR C's "Updating to 0.2.1" guide carries it next to B4's; D2 adds no page for it. Its text, final once Task 3 lands (Task 1's first version has steps 1, 2's first sentence and 6):
    1. Before updating, wait until every appliance is stopped: a cycle running during the update is lost, its phases' too (ruling 5).
    2. In each `appliance:` block, `running:` becomes `running_program:` and its `threshold:` becomes `above:` (the delays stay; absent, they are 0). The appliance's `statistics:` `runtime` and `cycles` move into `running_program: statistics:`; `idle_energy` stays in the appliance's `statistics:`.
    3. Each `modes:` block goes: its modes become the phases of the same device's `running_program: phases:`, each with its `name`, `above`/`below` and `on_delay`/`off_delay`. Its `statistics:` goes into each phase that should keep its meters. `cycle_from`, `sensor` and `energy` go: a phase reads the appliance's power and energy.
    4. Each `phases:` block goes: each band becomes a phase of `running_program: phases:`, now with a `name`; `for:` becomes `on_delay:`; `defaults:` goes (a stopped appliance's phase is `idle`, one running outside every band `other`). Bands may overlap now: both phases run.
    5. Every `when:` (alerts, reactions), card or automation naming `mode_current`, `mode_last`, `mode_<key>_…` or `phase_current` names `appliance_phase_current`, `appliance_phase_last`, `appliance_phase_<key>_…` instead (entity IDs `<platform>.pururu_<device>_appliance_phase_…`).
    6. Update and restart. The old modes' and phases' entities are removed as stale; their history stays in the recorder under the old IDs, and the phases' totals and meters start from zero.
22. **`EACH` is the string `"*"`, and a `Path` a `tuple[str, ...]`** (Task 3). No slug is `*`, so `Counted.at` (L0 `roles.py`, which imports `feature.py` only for typing) and `Place.path` share one plain type. `walk` yields each container with its concrete path, a key made text as the builder's schema makes it (`cv.slug`: YAML's `1` is `"1"`), so a value is put back where the validated block has it.
23. **`program_of` builds other's band from its delays alone** (Task 3). The block `build` gets is the mounted one, with `statistics` at each place; D1's `Band(**other)` raised `TypeError` on it. The prototype found it through the dashboard and places tests, which set up the appliance's example (`other: {}`, ruling 11). A phase's band was already read field by field (`_band`).
24. **The contract's `{item}` rule is per place** (Task 3): a place's names carry `{item}` all or none, and none without `Place.item`. Other has an item (its keys are `phase_other_*`, as D1's `_cycle_entities` makes them) but is named on its own (ruling 10), so "every key of an item's place has `{item}`" would be false; before D2 the rule was per `Items` builder.
25. **A place's check gets the builder's whole block and its container** (`Place.check(block, container)`, ruling 8): a phase's `energy` counter needs the appliance's `energy`. The refusal's path is the container's (`running_program > phases > gelar`), its text as today (`statistics.energy needs energy`). The alerts and notifications aspects have no check, as today.
26. **The appliance's counters move, and the old places refuse them** (Task 3): `runtime`/`cycles` in the appliance's `statistics:` are unknown counters now, `idle_energy` in `running_program`'s too (`test_the_appliances_counters_sit_where_they_count`). The tests asking for them move them; `test_appliance.py`'s and `test_statistics.py`'s `repeated period`/`unknown period` move too, lest they pass as unknown counters.
27. **What `Counters` replaces** (Task 3): `catalogue._per_item` goes for aspects (their keys come per container of each place; `Items`' own keys stay in `keys()`); D1's `program.COUNTERS` becomes `PHASE_COUNTERS` (the needs) and `counted(at)`; the opening and the programs keep a module-level `COUNTED`, which their `ENTITY_KEYS` read. `Counted.item` for programs and reactions is their `Items` item, so a program's meter keeps its key and name.

## Tasks

1. The appliance's `running_program`: the carrier replaces `Running`, `threshold` → `above`; every test's appliance ported; D1's test-only builder retired. Draft PR.
2. `modes`, `phases`, `cycle_from`, `Provides`/`Requires` go; `Derived` puts the phases in the index; the fixture in the new syntax; the snapshot's first update.
3. Aspects at places: `Place`, `walk`, `Counted`; statistics in `running_program`, each phase and `other`; `checks.keys_distinct`; the snapshot's second update.
4. The Guide: the detected programs concept page, `appliance.mdx`, `modes.mdx`/`phases.mdx` removed, every example, `configuration.mdx`, `troubleshooting.mdx`; the update step in the PR text (ruling 21).
5. The Develop pages, CLAUDE.md, coverage, the final review, ready.

The counts below were measured on a prototype of Tasks 1–3 in a `git archive` scratch copy of 9fd851e (1340 passed there).

---

### Task 1: The appliance's `running_program`

The appliance builds its carrier with D1's `build`; `running:` and `threshold` go. Nothing else changes yet: `modes` and `phases` still take the cycle from the appliance (`Provides("cycle", "running")` stays until Task 2), and statistics stay in the appliance's block. The IDs don't change, so the snapshot doesn't either.

**Files:**
- Modify `custom_components/pururu/features/appliance/__init__.py`, `custom_components/pururu/features/cycle/__init__.py` (`CycleSource`'s docstring).
- Delete `custom_components/pururu/features/appliance/running.py`.
- Modify `tests/helpers.py` (`snapshot`), `tests/test_appliance.py`, `tests/test_presets.py`, `tests/test_program_entities.py`, `tests/test_modes.py`, `tests/test_phases.py`.
- Modify mechanically (one line each, Step 3): `tests/test_alert2.py`, `test_alert_lights.py`, `test_alerts.py`, `test_checks.py`, `test_cycle.py` (two), `test_events.py`, `test_lifecycle.py`, `test_notifications.py`, `test_opening.py`, `test_programs.py`, `test_reactions.py`, `test_resolve.py`, `test_statistics.py` (three), `test_switches.py`, `tests/fixtures/house.yaml`.
- Modify the docs examples a test validates, and every other `running: {threshold: …}` example (Step 3): `README.md`, `docs/index.mdx`, `docs/getting-started/{install,first-device}.mdx`, `docs/concepts/{alert-lights,alerts,events,floors-and-areas,notifications,reactions,statistics,devices-and-features}.mdx`, `docs/features/{appliance,modes,phases}.mdx`, `docs/reference/configuration.mdx`, `docs/develop/testing.mdx`. Task 4 rewrites the pages' prose; here only the examples' syntax changes.

**Interfaces:**

Consumes (D1): `features.cycle.program`: `SCHEMA`, `program_of`, `build(hass, device, program, *, key, reading, energy)`.

Produces:

```python
# features/appliance/__init__.py
RUNNING_PROGRAM = "running_program"
CARRIER = "running"
SCHEMA  # power, energy, running_program (program.SCHEMA, no name)

# tests/helpers.py
def snapshot(since: str | None, *, since_energy: float | None = None,
             until: str | None = None, **phases: dict[str, Any]) -> dict[str, Any]
```

- [ ] **Step 0: Branch.** The branch exists, cut from `main` at 9fd851e (D1 merged). In its worktree: `git log -1 --format=%h` shows `9fd851e`, then `uv sync --locked`, then `uv run pytest -q`. Expected: `1340 passed`.

- [ ] **Step 1: The failing tests.** In `tests/test_appliance.py`:
  - `APPLIANCE`'s `"running": {"threshold": 4, …}` → `"running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}}`;
  - `test_invalid_block_is_refused`'s params: `no off_delay` becomes `pytest.param({**APPLIANCE, "running_program": {"on_delay": {"minutes": 1}}}, id="no bound")`; `no power` takes `{"running_program": APPLIANCE["running_program"]}`; `threshold not a number`/`threshold infinite` become `above not a number`/`above infinite` on `{**APPLIANCE["running_program"], "above": "nan"}` (`"inf"`); add
    ```python
    pytest.param({"power": POWER, "running": {"on_delay": 60, "off_delay": 120, "threshold": 4}},
                 id="running is now running_program"),
    pytest.param({**APPLIANCE, "running_program": {**APPLIANCE["running_program"], "name": "X"}},
                 id="running_program takes no name"),
    ```
    (`threshold` last in the old block: Step 3's `sed` rewrites `"running": {"threshold": ` and would make this param a valid block.)
  - `start_cycle`: `await tick(hass, freezer, 65)` → `await tick(hass, freezer, 60)`, docstring "Exactly on_delay above, so the cycle starts now (the carrier dates it when on_delay passed), then the drum's pause (~7 W)."; `test_cycle_start_is_shown_while_running`: `timedelta(seconds=65)` → `timedelta(seconds=60)`. `wash` keeps its 65 s (its durations only count whole minutes of runtime);
  - every restart of `RUNNING` passes `snapshot(...)` instead of a `CycleStart` dict: `{"since": since, "since_energy": 100.0}` → `snapshot(since, since_energy=100.0)`; `{"since": since.isoformat(), "since_energy": 100.0}` → `snapshot(since.isoformat(), since_energy=100.0)`; `{"since": since.isoformat(), "since_energy": None, "until": dropped.isoformat()}` → `snapshot(since.isoformat(), until=dropped.isoformat())`; `{"since": None, "since_energy": None}` → `snapshot(None)`; import `snapshot` from `helpers`;
  - replace `test_restart_with_an_impossible_start_restores_running` with the two tests below.

  ```python
  async def test_restart_with_an_impossible_start_is_no_cycle(
          ha: HomeAssistant, freezer: Any) -> None:
      """A hand-edited .storage: a well-formed but impossible start is none, and a program without a start doesn't run (D1 ruling 15); the power starts the next cycle."""
      await restart(ha, DEVICES, (State(RUNNING, "on"),
                                  snapshot("2020-02-30T10:00:00+00:00", since_energy=100.0)))
      assert running(ha) == "off"
      await watts(ha, IDLE_W)
      await tick(ha, freezer, 125)
      await start_cycle(ha, freezer)
      await end_cycle(ha, freezer)
      assert ha.states.get(sensor("cycles_total")).state == "1"


  async def test_an_old_running_restore_is_no_cycle(ha: HomeAssistant, freezer: Any) -> None:
      """What 0.1.23's running saved (its CycleStart) is no snapshot: no cycle is restored, and the next one counts from its own start (the update step: update while stopped)."""
      since = (dt_util.utcnow() - timedelta(minutes=20)).isoformat()
      await restart(ha, DEVICES, (State(RUNNING, "on"), {"since": since, "since_energy": 100.0}))
      assert running(ha) == "off"
      assert "cycle_start" not in ha.states.get(RUNNING).attributes
      await watts(ha, IDLE_W)
      await tick(ha, freezer, 125)
      started = dt_util.utcnow() + timedelta(seconds=60)
      await start_cycle(ha, freezer)
      assert ha.states.get(RUNNING).attributes["cycle_start"] == started
  ```

  In `tests/helpers.py`, append (D1's helper from `test_program_entities.py`, `since` now optional):

  ```python
  def snapshot(since: str | None, *, since_energy: float | None = None,
               until: str | None = None, **phases: dict[str, Any]) -> dict[str, Any]:
      """A running program's carrier's restored extra data: its cycle from `since` (None: not running), and `phases`' runs by key."""
      program = None if since is None else {
          "since": since, "since_energy": since_energy, "until": until, "gap": False}
      return {"program": program,
              "phases": {key: {"since_energy": None, "until": None, "gap": False, **run}
                         for key, run in phases.items()},
              "order": list(phases), "seen": list(phases)}
  ```

  ```sh
  uv run pytest tests/test_appliance.py -n 0 -q
  ```

  Expected: every test fails at setup or collection: `'running_program' is an invalid option` (the appliance's schema is today's).

- [ ] **Step 2: The appliance.** Replace `custom_components/pururu/features/appliance/__init__.py`'s schema, keys and build (the imports lose `finite_float`, `Running`; gain `CONF_NAME` and `..cycle.program`):

  ```python
  """An appliance on a power-measuring plug: when it runs, its cycles, their statistics and the energy between them.

  Its required `running_program` is a detected program (features/cycle/program)
  read from the plug's power: the appliance running at all, and its phases.
  """

  # (imports)
  from ..cycle import program

  # The appliance running at all: a detected program with a fixed key
  RUNNING_PROGRAM = "running_program"
  # Its carrier's entity key: appliance_running, as before running_program
  CARRIER = "running"


  def _unnamed(block: Any) -> Any:
      """Refuse a name: running_program is the appliance running, named by the appliance."""
      if isinstance(block, dict) and CONF_NAME in block:
          raise vol.Invalid(
              f"{RUNNING_PROGRAM} takes no name: it is the appliance running"
          )
      return block


  SCHEMA = vol.Schema(
      {
          vol.Required("power"): cv.entity_id,
          vol.Optional("energy"): cv.entity_id,
          vol.Required(RUNNING_PROGRAM): vol.All(_unnamed, program.SCHEMA),
      }
  )

  # ENTITY_KEYS: as today, "running" written CARRIER


  def build(
      hass: HomeAssistant,
      device: Device,
      config: dict[str, Any],
      inputs: Mapping[str, str],
  ) -> list[PururuEntity]:
      """The plug's mirrors, the running program (its carrier first, then its phases'), and its cycles.

      The program's own cycle entities are the appliance's (D1 ruling 13): they
      follow the carrier, `running`.
      """
      energy: str | None = config.get("energy")
      running = device.current_entity_id(hass, Platform.BINARY_SENSOR, CARRIER)
      entities: list[PururuEntity] = [
          Mirror(hass, device, "power", config["power"]),
          *program.build(
              hass,
              device,
              program.program_of(config[RUNNING_PROGRAM]),
              key=CARRIER,
              reading=config["power"],
              energy=energy,
          ),
          *(
              LastCycleValue(device, description, source=CARRIER)
              for description in LAST_CYCLE
              if energy is not None or description.key != "last_cycle_energy"
          ),
          CyclesTotal(device, source=CARRIER),
          RuntimeTotal(device, running, STATE_ON, source=CARRIER),
      ]
      if energy is not None:
          entities.append(Mirror(hass, device, "energy_total", energy))
          entities.append(
              IdleEnergyTotal(device, running, STATE_OFF, energy, source=CARRIER)
          )
      return entities
  ```

  `APPLIANCE`: `example` becomes `{"power": "sensor.demo_plug_power", RUNNING_PROGRAM: {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}}}`; `Provides("cycle", CARRIER)`; the other roles as today. Delete `features/appliance/running.py`: nothing imports it.

  The carrier comes first in `program.build`'s list, and the platforms keep `build`'s order, so it restores the detector before any phase's binary sensor is added (D1 ruling 15).

  In `features/cycle/__init__.py`, `CycleSource`'s docstring drops `Running` from the classes it names (`` `Open`, `Runs`, and the detector's `Carrier` and `PhaseRunning` set the signals up once, in `__init__`; `Current` (modes) … ``); Task 2 drops `Current` and the module docstring's `modes`.

- [ ] **Step 3: Every other test, the fixture and the examples.**

  ```sh
  sed -i 's/"running": {"threshold": /"running_program": {"above": /' tests/*.py
  sed -i 's/running: {threshold: /running_program: {above: /' tests/fixtures/house.yaml README.md docs/index.mdx docs/getting-started/*.mdx docs/concepts/*.mdx docs/features/*.mdx
  git grep -n 'threshold' -- tests docs README.md
  ```

  Expected: `git grep` lists only `test_appliance.py`'s docstrings and ids already handled in Step 1, and the prose and multi-line examples Task 4 rewrites (`docs/features/appliance.mdx`, `docs/getting-started/first-device.mdx`, `docs/reference/*.mdx`, `docs/develop/testing.mdx`). Rewrite the multi-line `running:` examples of `first-device.mdx`, `appliance.mdx`, `configuration.mdx` and `testing.mdx` to `running_program:` with `above:` now, so no page shows a refused block between tasks.

  Then:
  - `tests/test_presets.py`: its three restarts of `RUNNING` pass `snapshot(since.isoformat())` (one) and `snapshot(None)` (two); import `snapshot`.
  - `tests/test_modes.py` (5 restarts) and `tests/test_phases.py` (1): `{"since": since, "since_energy": None}` → `snapshot(since)`, `{"since": None, "since_energy": None}` → `snapshot(None)`; import `snapshot`. Delete `test_modes.py`'s `test_no_mode_starts_while_the_cycle_is_unknown` (ruling 5: it fakes `running`'s own state, which the carrier rewrites at every step; the file goes in Task 2).
  - `tests/test_program_entities.py` runs on the real appliance (ruling 13):
    - delete `builder()` and the `detecting` fixture, and rename every `detecting` to `ha` (`sed -i 's/\bdetecting\b/ha/g'`);
    - the module docstring: "features/cycle/program's entities, in HA, through the appliance's running_program. The carrier is the appliance's `running`; the phases' entity IDs are <platform>.pururu_<device>_appliance_phase_<key>_<suffix>.";
    - delete its `snapshot` (now `helpers.snapshot`, same calls) and import it from `helpers`; drop the imports left unused (`Platform`, `cv`, `vol`);
    - after `SUFFIXES`, add `OWN`, the appliance's own entities, and use it:
      ```python
      # The appliance's own, beside its running program's phases
      OWN = {RUNNING, *(sensor(key) for key in (
          "power", "energy_total", *LAST_CYCLE, "cycles_total", "runtime_total", "idle_energy_total"))}
      ```
      (move `def sensor` above it). `test_its_entities_and_their_ids` asserts `held(ha, KEY) == {*OWN, CURRENT, LAST, …}`; `test_without_phases_only_the_carrier` becomes `test_without_phases_no_phase_entity`, asserting `held(ha, KEY) == {RUNNING, *(sensor(key) for key in ("power", *LAST_CYCLE[:3], "cycles_total", "runtime_total"))}` (no energy there).

- [ ] **Step 4: GREEN, and the whole suite.**

  ```sh
  uv run pytest tests/test_appliance.py tests/test_program_entities.py tests/test_presets.py -n 0 -q
  uv run pytest -q
  ```

  Expected: all pass; then `1342 passed`: 1340, plus two refusal params and one restart test, minus one modes test. `test_code.py` passes: ruff, mypy, the layer table (the appliance imports `features/cycle/program`, L1 to L1). `test_ids.py` passes unchanged: no ID moved. `test_alert_lights.py::test_the_pages_example_is_valid` passes on the rewritten example.

- [ ] **Step 5: Commit, push, open the draft PR.**

  ```sh
  git add -A custom_components tests docs README.md
  git commit -m "pururu: the appliance's running_program replaces running and its threshold (refactor D2)

  The appliance builds its required running_program with the detector
  (features/cycle/program): the carrier is appliance_running, IDs unchanged.
  threshold becomes above; the delays default to 0; a name is refused. A
  cycle starts when its on_delay passed; a restore needs the detector's
  snapshot. D1's test-only builder retires: the entity tests run on the
  appliance.

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM"
  git push -u origin refactor/d2-running-program
  gh pr create --draft --base main --title "pururu: refactor D2, the running program replaces running, modes and phases (0.2.0)" --body-file <scratchpad>/pr.md
  ```

  The PR body says what D2 is, where it stops (D3), the rulings in short, and the manual update step (ruling 21): its first version now, with the `running_program`/`above` part only; Tasks 2 and 3 complete it (`gh pr edit <n> --body-file`). It ends with:

  ```
  🤖 Generated with [Claude Code](https://claude.com/claude-code)

  https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM
  ```

  Then wait for `gh pr view <n> --json headRefOid -q .headRefOid` to equal `git rev-parse HEAD`, and add `claude-review`.

---

### Task 2: `modes`, `phases`, `cycle_from`, `Provides`/`Requires` go; the phases in the index

The appliance's phases replace both features. `Derived` puts their keys in the index, so an alert, a reaction or `when:` can name them. The capability machinery goes with its only users. Phases have no meters yet (Task 3): the `item_energy_*` translations go with `modes`, and Task 3 puts them back unchanged. The snapshot changes for the first time: the 41 IDs of today's modes and phases go, the 52 of the new phases come.

**Files:**
- Modify `custom_components/pururu/core/roles.py` (`Provides`, `Requires` go; `Derived` comes), `features/cycle/program/{schema,__init__}.py` (`keys_of`), `features/appliance/__init__.py` (roles, example), `features/opening/__init__.py` (roles), `features/__init__.py` (`FEATURES`), `setup/{catalogue,checks,schema,build}.py`, `translations/{en,pt-BR}.json`, `icons.json`.
- Modify docstrings naming modes: `features/cycle/__init__.py`, `core/{feature,roles,entity,resolve}.py`, `outputs/events.py`.
- Delete `custom_components/pururu/features/modes/` (`__init__.py`, `current.py`, `last.py`), `features/phases.py`, `tests/test_modes.py`, `tests/test_phases.py`.
- Modify `tests/test_program_entities.py`, `tests/test_features.py`, `tests/test_init.py`, `tests/test_cycle.py`, `tests/test_opening.py`, `tests/test_statistics.py`, `tests/test_alerts.py`, `tests/fixtures/house.yaml`, `tests/fixtures/house_ids.json`.
- Modify `docs/develop/writing-a-feature.mdx` (its `features/__init__.py` example imports `.phases`: `test_code.py` checks it). Task 5 rewrites the page's prose.

**Interfaces:**

Consumes (D1): `features.cycle.program`: `phase_keys(key)`, `FIXED`, `OTHER`.

Produces:

```python
# core/roles.py
@dataclass(frozen=True)
class Derived:
    of: Callable[[Any], Mapping[str, Platform]]
type Role = Configured | Derived | Actions | Items | Counters | Refers | Presets | Happenings | Generates

# features/cycle/program/schema.py (re-exported by the package)
def keys_of(config: Mapping[str, Any]) -> dict[str, Platform]

# setup/build.py
def _inputs(hass, key, config, name, index, owned) -> dict[str, str]   # no `required` set any more
```

- [ ] **Step 1: The failing tests.** Append to `tests/test_program_entities.py` (import `generated` from `helpers`):

  ```python
  # --- what refers to a phase ------------------------------------------------------------

  HOT = "binary_sensor.pururu_demo_filter_alert_hot"


  def with_alert(**alert: Any) -> dict[str, Any]:
      return {KEY: {**DEVICES[KEY], "alerts": {"hot": {"name": "Esquentando", **alert}}}}


  async def test_an_alert_can_watch_the_current_phase(ha: HomeAssistant, freezer: Any) -> None:
      assert await setup(ha, with_alert(when="appliance_phase_current", **{"is": "quente"}))
      await watts(ha, IDLE_W)
      await tick(ha, freezer, 125)
      assert state(ha, HOT) == "off"
      await watts(ha, 1000)
      await tick(ha, freezer, 25)
      assert state(ha, HOT) == "on"


  async def test_an_alert_can_watch_a_phases_total(ha: HomeAssistant) -> None:
      assert await setup(ha, with_alert(when="appliance_phase_quente_cycles_total", above=10))
      assert state(ha, HOT) == "off"


  async def test_a_reaction_can_watch_a_phase(ha: HomeAssistant) -> None:
      devices = {KEY: {**DEVICES[KEY], "reactions": {
          "hot": {"name": "Quente", "when": "appliance_phase_quente", "to": "on"}}}}
      assert await setup(ha, devices)
      assert generated(ha)[0]["triggers"][0]["entity_id"] == QUENTE


  @pytest.mark.parametrize("when", [
      pytest.param("appliance_phase_morno_cycles_total", id="a phase not configured"),
      pytest.param("appliance_phase_morno", id="its binary sensor"),
  ])
  async def test_a_reference_to_a_phase_not_configured_is_refused(
          ha: HomeAssistant, caplog: pytest.LogCaptureFixture, when: str) -> None:
      assert not await setup(ha, with_alert(when=when, above=10))
      assert f"alerts: {when} is not an entity key of another feature of this device" in caplog.text


  async def test_no_phase_keys_without_phases(
          ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
      """Without phases the appliance creates no phase entity, so none can be named."""
      devices = {KEY: {"name": "Demo filter",
                       "appliance": {"power": POWER, "running_program": {"above": 4}},
                       "alerts": {"hot": {"name": "Esquentando", "when": "appliance_phase_current",
                                          "is": "quente"}}}}
      assert not await setup(ha, devices)
      assert ("alerts: appliance_phase_current is not an entity key of another feature "
              "of this device") in caplog.text


  async def test_a_renamed_phase_is_followed(purifier: HomeAssistant, freezer: Any) -> None:
      """Renamed in the UI: the entry reloads, and the phase's runtime follows the new ID."""
      renamed = "binary_sensor.demo_filter_gelar"
      er.async_get(purifier).async_update_entity(GELAR, new_entity_id=renamed)
      await purifier.async_block_till_done()
      await cool(purifier, freezer)
      assert state(purifier, renamed) == "on"
      await tick(purifier, freezer, 600)
      await watts(purifier, IDLE_W)
      await tick(purifier, freezer, 35)
      assert float(state(purifier, sensor("phase_gelar_runtime_total"))) == pytest.approx(
          605 / 3600, abs=0.0005)
  ```

  In `tests/test_features.py`, replace `test_capabilities_line_up`, `test_a_capability_is_carried_by_a_cycle_source` and `test_the_other_cycle_sources_are_pinned_too` with the two rules of ruling 20:

  ```python
  def test_what_a_last_cycle_follows_is_a_cycle_source(
      ha: HomeAssistant, features: dict[str, Any]
  ) -> None:
      """Each last cycle follows the entity sending its cycles, a CycleSource: the appliance's running and each phase, a door's or a window's open, a program's runs."""
      cycle_source = module("features.cycle").CycleSource
      last_cycle = module("features.cycle.last").LastCycleValue
      device_cls = module("core.feature").Device
      mount = module("setup.catalogue").mount
      following: dict[str, set[str]] = {}
      for name, feature in features.items():
          if role(feature, "Counters") is None:  # counts no cycle
              continue
          device = device_cls(key="dev", name="Dev", namespace=feature.namespace)
          block = mount(feature, name, dict(feature.example))
          built = {entity.key: entity for entity in feature.build(ha, device, block, {})}
          for entity in built.values():
              if isinstance(entity, last_cycle):
                  (source,) = entity.sources
                  assert isinstance(built[device.qualified(source)], cycle_source), (name, entity.key)
                  following.setdefault(name, set()).add(source)
      assert set(following) == {"appliance", "door", "window", "programs"}
      assert following["appliance"] == {"running", "phase_heating", "phase_other"}


  def test_a_derived_key_is_in_the_index(ha: HomeAssistant, features: dict[str, Any]) -> None:
      """What a validated block adds (roles.Derived) is listed by catalogue.keys, and the example builds only listed keys."""
      catalogue = module("setup.catalogue")
      device_cls = module("core.feature").Device
      deriving = [name for name, feature in features.items() if role(feature, "Derived")]
      assert deriving == ["appliance"]
      for name in deriving:
          feature = features[name]
          block = catalogue.mount(feature, name, dict(feature.example))
          derived = role(feature, "Derived").of(block)
          assert derived, f"{name}'s example derives no key"
          assert not set(derived) & set(feature.entity_keys), name
          listed = {entity_key for _, entity_key, _, _, _ in catalogue.keys({name: block})}
          assert set(derived) <= listed, name
          device = device_cls(key="dev", name="Dev", namespace=feature.namespace)
          built = {entity.key for entity in feature.build(ha, device, block, {})}
          assert built <= {device.qualified(key) for key in listed}, name
  ```

  The Counters filter keeps out the `alerts` device key, whose build needs its references in `inputs`.

  ```sh
  uv run pytest tests/test_program_entities.py tests/test_features.py -n 0 -q
  ```

  Expected: FAIL, 5 tests. `test_an_alert_can_watch_the_current_phase`, `test_an_alert_can_watch_a_phases_total` and `test_a_reaction_can_watch_a_phase` fail at setup (`Invalid config`: the index doesn't know derived keys); `test_a_derived_key_is_in_the_index` fails (`AttributeError`: no `Derived`); `test_what_a_last_cycle_follows_is_a_cycle_source` fails (`modes`' build wants `inputs["cycle"]`). Already passing, as they must stay: both refusal tests (nothing names a phase key yet) and `test_a_renamed_phase_is_followed` (the listener's one rename rule covers every entity of the entry since A2a).

- [ ] **Step 2: `Derived`, `keys_of`, and the appliance's roles.**

  `core/roles.py`: delete `Provides` and `Requires`; add, before `Actions`:

  ```python
  @dataclass(frozen=True)
  class Derived:
      """Entity keys its validated block adds beyond entity_keys: the appliance's phases'.

      `of` takes the validated block. catalogue.keys lists them, so the index
      knows them: an alert, a reaction or a `when:` can name one.
      """

      of: Callable[[Any], Mapping[str, Platform]]
  ```

  and `Role` becomes `Configured | Derived | Actions | Items | Counters | Refers | Presets | Happenings | Generates`.

  `features/cycle/program/schema.py`, before `_reserved` (and `keys_of` added to the package's imports and `__all__`):

  ```python
  def keys_of(config: Mapping[str, Any]) -> dict[str, Platform]:
      """Every entity key a program block's phases create, other's too: none without phases."""
      if "phases" not in config:
          return {}
      return {
          **FIXED,
          **{
              entity_key: platform
              for key in (*config["phases"], OTHER)
              for entity_key, platform in phase_keys(key).items()
          },
      }
  ```

  It reads only the phases' keys, so it works on the validated block and on the builder's raw example alike. `phase_<key>_energy_total` is listed without `energy` too: a key the builder *can* create, as `appliance_energy_total` is.

  `features/appliance/__init__.py`: the roles import `Counters, Derived, Happenings, Presets` (no `Provides`); `APPLIANCE`'s `Provides("cycle", CARRIER)` becomes

  ```python
          # Its running program's phases' keys (none without phases)
          Derived(lambda config: program.keys_of(config[RUNNING_PROGRAM])),
  ```

  and its example gains one phase and `other` (ruling 11):

  ```python
          # One phase and other: the contract test reaches every derived key
          RUNNING_PROGRAM: {
              "above": 4,
              "on_delay": {"minutes": 1},
              "off_delay": {"minutes": 2},
              "phases": {"heating": {"name": "Heating", "above": 1000}},
              "other": {},
          },
  ```

  `features/opening/__init__.py`: `roles=(COUNTERS,)`, and the import loses `Provides` (ruling 15).

  `setup/catalogue.py`'s `keys()` lists the derived keys after the configured ones (import `Derived`):

  ```python
          if (derived := feature.role(Derived)) is not None:
              yield from (
                  (name, entity_key, platform, None, None)
                  for entity_key, platform in derived.of(device[name]).items()
              )
  ```

  `by` and `item` are None: a phase's keys are the builder's own, and `Target.item` names an `Items` item (a program, a reaction), which a phase isn't.

- [ ] **Step 3: What goes.**
  - `features/__init__.py`: drop `MODES`, `PHASES` and their imports. `FEATURES` is `appliance`, `door`, `window`, `lights`, `switches`. Delete `features/modes/` and `features/phases.py`.
  - `setup/checks.py`: delete `capabilities_provided` and `_provides`; the imports lose `Provides`, `Requires` and `FEATURES`.
  - `setup/schema.py`'s `_device`: drop the docstring's `<capability>_from` sentence and the check's call; the feature test becomes `if not any(name in device for name in FEATURES):`.
  - `setup/build.py`: `_inputs` returns only `inputs` (the `required` set and the `Requires` branch go; its docstring: "A feature: the current entity IDs of what it refers to. A builder that Generates: …"); `build` calls `inputs = _inputs(...)` and appends `(entity, {*map(device.object_id, entity.sources), *follows})`; its docstring: "what it refers to is in the owning feature's". The imports lose `Provides`, `Requires` and `FEATURES`. Run `uv run ruff format custom_components/pururu` (the append fits one line).
  - `translations/en.json`, `translations/pt-BR.json`, `icons.json`: delete the nine `mode_*` entries (`mode_current`, `mode_last` with their states, `mode_last_cycle_{start,end,duration,energy}`, `mode_{cycles,runtime,energy}_total`) and the four `item_energy_{today,week,month,year}` (ruling 1). `phase_current` and `phase_last` keep every state.
  - Docstrings: `features/cycle/__init__.py`'s module docstring becomes "The detector (`program/`) has one for its program (the appliance's `running`) and one per phase; a door's or a window's `open` one; an executable program's `Runs` one per program, an Item of its block." and `CycleSource`'s "`Open`, `Runs`, and the detector's `Carrier` and `PhaseRunning` set the signals up once, in `__init__`."; `core/roles.py` `Items` and `core/entity.py` `_identify`: `({mode})` → `({program})`; `core/feature.py`: `bounded`'s "(`what`: program, phase)", `Item`'s "(roles.Items): a program, a reaction."; `core/resolve.py`: "(a program, a reaction)"; `outputs/events.py`: "a fact: running, a phase,".

  ```sh
  git grep -n 'Provides\|Requires\|capabilit\|cycle_from\|features\.modes\|features\.phases\|mode_' -- custom_components
  ```

  Expected: nothing.

- [ ] **Step 4: The tests of what went.** Delete `tests/test_modes.py` and `tests/test_phases.py`. Each of their tests went where the table says (ruling 14): "D1" is a test of D1's already on `main`, pure (`test_program.py`) or on the entities (`test_program_entities.py`); "ported" is added here to `test_program_entities.py`; "goes" pins what D2 removes.

  | `test_modes.py` | Where |
  |---|---|
  | `test_invalid_block_is_refused` (16 params) | D1 `test_invalid_program_is_refused`; `overlapping bands` and `a band inside another` are valid now (spec item 1), so is `no on_delay` (0 when absent), `no cycle_from` goes, the statistics params go to Task 3 |
  | `test_bands_that_only_touch_are_accepted` | D1 `test_after_an_idle_gap_the_next_phase_does_not_wait` (40 W between `below: 40` and `above: 40`) |
  | `test_the_cycle_must_come_from_this_device` | goes: no `cycle_from`; `running_program` is required (Task 1's `no power`/`no bound`) |
  | `test_idle_until_a_mode_starts` | D1 `test_idle_until_a_phase_starts` |
  | `test_a_mode_starts_after_its_on_delay`, `test_a_mode_ends_after_its_off_delay`, `test_a_reading_back_in_the_band_cancels_the_end` | D1 `test_a_phase_starts_after_its_on_delay`, `test_a_phase_ends_after_its_off_delay_at_when_it_left`, `test_back_in_its_band_cancels_the_end`; D1 `test_a_phase_runs_and_ends` |
  | `test_another_mode_waits_for_the_running_one`, `test_the_next_mode_starts_when_the_running_one_ends` | D1 `test_after_a_dip_another_phase_waits_for_the_running_one` |
  | `test_a_dip_into_another_band_does_not_split_the_cycle`, `test_a_short_visit_to_another_band_is_nothing` | D1, same names |
  | `test_a_mode_armed_before_the_cycle_starts_with_it` | D1 `test_a_phase_armed_before_the_program_starts_with_it` |
  | `test_the_cycle_ending_ends_the_mode`, `…_at_its_end`, `test_a_mode_ending_during_the_appliances_off_delay_ends_when_the_power_went_down` | D1 `test_the_program_ending_ends_the_phase_at_its_end` (a phase reads the program's reading: no second sensor) |
  | `test_restart_during_a_modes_off_delay_keeps_when_it_left` | D1 `test_a_snapshot_restores_the_running_cycles` (a phase's `until`) |
  | `test_a_reading_without_a_value_cancels_pending_and_keeps_the_mode` | D1 `test_no_value_keeps_the_phase_and_counts_its_delays_again`, `test_a_reading_without_a_value_holds_the_phase` |
  | `test_restart_keeps_the_running_mode`, `test_restart_mid_cycle_keeps_its_start` | D1 `test_a_restart_keeps_the_running_phase` |
  | `test_restart_with_an_impossible_start_keeps_the_mode` | D1 `test_a_phases_impossible_date_is_no_start` |
  | `test_last_restores`, `test_reload_keeps_the_running_mode`, `test_reload_mid_cycle_counts_one` | D1 `test_last_restores`, `test_a_reload_mid_phase_counts_one_cycle` |
  | `test_follows_a_renamed_cycle` | D1 `test_a_carrier_renamed_mid_phase_follows_the_reading` |
  | `test_no_modes_when_its_cycle_is_not_created` | D1 `test_nothing_…_when_the_carrier_is_not_created`, renamed below |
  | `test_an_alert_can_watch_the_mode`, `test_an_alert_can_watch_a_mode_entity`, `test_an_alert_on_a_mode_that_does_not_exist_is_refused` | Step 1: `test_an_alert_can_watch_the_current_phase`, `test_an_alert_can_watch_a_phases_total`, `test_a_reference_to_a_phase_not_configured_is_refused` |
  | `test_names`, `test_names_in_portuguese`, `test_per_mode_names_carry_the_mode_name`, `test_per_mode_names_in_portuguese` | D1 `test_names` (en, pt-BR) |
  | `test_a_mode_cycle_is_recorded`, `test_end_is_written_last_and_last_before_it` | D1 `test_a_phase_runs_and_ends`, `test_a_phases_cycle_is_sent_after_its_state_its_end_last` |
  | `test_energy_total_adds_the_cycles_and_skips_the_unknown` | ported: `test_a_phases_energy_adds_its_cycles_and_skips_the_unknown` |
  | `test_short_cycles_add_up_their_energy` | ported: `test_short_phases_add_up_their_energy` |
  | `test_runtime_per_mode` | ported: `test_each_phases_runtime_counts_from_its_start` |
  | `test_totals_restore` | ported: `test_a_phases_totals_restore` |
  | `test_meters_per_mode` | Task 3: `test_meters_per_phase` |
  | `test_without_energy_no_energy_per_mode` | D1 `test_without_energy_no_energy_per_phase` |
  | `test_a_mode_ended_by_the_cycle_starts_again_when_it_reopens` | D1 `test_after_the_program_a_band_still_holding_starts_with_the_next` |
  | `test_a_handover_never_shows_idle` | D1, same name (pure and entity) |
  | `test_a_restored_mode_ends_when_the_cycle_is_already_off` | goes: one snapshot holds the program and its phases, so a phase is never restored running without its program (D1 `test_a_snapshot_it_cannot_use_is_ignored`) |

  | `test_phases.py` | Where |
  |---|---|
  | `test_invalid_block_is_refused` (9 params) | D1 `test_invalid_program_is_refused`; `defaults alike`, `band named like a default` and `no cycle_from` go with `defaults` and `cycle_from` |
  | `test_the_cycle_must_come_from_this_device` | goes, as the modes' |
  | `test_stopped_until_a_cycle_starts` | D1 `test_idle_until_a_phase_starts` |
  | `test_a_cycle_starts_in_the_running_default` | goes with `defaults`: outside every band the phase is `other` after its on_delay (D1 `test_other_runs_outside_every_band_after_its_on_delay`) |
  | `test_a_band_without_for_holds_at_once`, `test_a_band_with_for_holds_after_it`, `test_leaving_before_for_is_not_the_band` | D1 `test_a_band_without_on_delay_holds_at_once_and_ends_at_once`, `test_a_band_with_on_delay_holds_after_it`, `test_leaving_before_its_on_delay_is_not_the_phase` |
  | `test_the_first_band_in_order_wins` | goes: no band wins (spec item 1; D1 `test_overlapping_bands_run_at_once_and_none_wins`) |
  | `test_end_is_stopped_and_keeps_seen`, `test_a_new_cycle_clears_seen` | D1 `test_seen_stays_after_the_program_and_clears_with_the_next` |
  | `test_readings_while_stopped_change_nothing`, `test_a_band_before_the_cycle_counts_when_it_starts` | D1 `test_readings_while_stopped_start_nothing`, `test_a_band_before_the_program_counts_when_it_starts` |
  | `test_holds_while_the_sensor_has_no_value`, `test_a_band_pending_its_for_starts_over_after_no_value` | D1 `test_no_value_keeps_a_phase_whose_band_held`, `test_a_band_pending_its_on_delay_starts_over_after_no_value` |
  | `test_restart_holds_the_phase_until_the_first_reading` | D1 `test_a_restart_keeps_the_running_phase`, `test_seen_holds_after_the_program_over_a_restart` |
  | `test_reload_while_a_band_is_pending` | ported: `test_a_reload_while_a_phase_is_pending` |
  | `test_follows_a_renamed_cycle` | D1 `test_a_carrier_renamed_mid_phase_follows_the_reading` |
  | `test_no_phase_when_its_cycle_is_not_created` | D1's test, renamed below and given its appliance asserts |
  | `test_names_its_states_in_portuguese` | D1 `test_names` (pt-BR "Demo filter Fase") |

  The ports, in `tests/test_program_entities.py`: before `# --- restarts and reloads ---`,

  ```python
  async def test_a_phases_energy_adds_its_cycles_and_skips_the_unknown(
          purifier: HomeAssistant, freezer: Any) -> None:
      """A cycle whose counter had no reading at its start adds nothing; the others add theirs."""
      for start, end in ((100.0, 100.05), ("unavailable", 100.2), (100.2, 100.23)):
          await kwh(purifier, start)
          await cool(purifier, freezer)
          await kwh(purifier, end)
          await watts(purifier, IDLE_W)
          await tick(purifier, freezer, 125)
      assert state(purifier, sensor("phase_gelar_cycles_total")) == "3"
      assert float(state(purifier, sensor("phase_gelar_energy_total"))) == pytest.approx(0.08)


  async def test_short_phases_add_up_their_energy(purifier: HomeAssistant, freezer: Any) -> None:
      """A sip uses a fraction of a Wh: rounding each cycle to 0.001 kWh would add nothing."""
      for start, end in ((100.0, 100.0004), (100.0004, 100.0008)):
          await kwh(purifier, start)
          await cool(purifier, freezer)
          await kwh(purifier, end)
          await watts(purifier, IDLE_W)
          await tick(purifier, freezer, 125)
      assert float(state(purifier, sensor("phase_gelar_energy_total"))) == pytest.approx(0.0008, abs=1e-6)
      assert state(purifier, sensor("phase_gelar_last_cycle_energy")) == "0.0"


  async def test_each_phases_runtime_counts_from_its_start(purifier: HomeAssistant, freezer: Any) -> None:
      """gelar from 30 s to 635 s; quente, armed at 645 s after the dip, starts when gelar ends (665 s), dated 645 s, until 965 s."""
      await cool(purifier, freezer)
      await tick(purifier, freezer, 600)
      await watts(purifier, 1000)
      await tick(purifier, freezer, 10)
      await tick(purifier, freezer, 20)
      await tick(purifier, freezer, 300)
      await watts(purifier, IDLE_W)
      await tick(purifier, freezer, 30)
      await tick(purifier, freezer, 95)
      assert float(state(purifier, sensor("phase_gelar_runtime_total"))) == pytest.approx(605 / 3600, abs=0.0005)
      assert float(state(purifier, sensor("phase_quente_runtime_total"))) == pytest.approx(320 / 3600, abs=0.0005)
      assert float(state(purifier, sensor("phase_other_runtime_total"))) == 0
  ```

  and before `test_last_restores`,

  ```python
  async def test_a_phases_totals_restore(ha: HomeAssistant) -> None:
      await restart(
          ha, DEVICES,
          (State(sensor("phase_gelar_cycles_total"), "7"), {"native_value": 7, "native_unit_of_measurement": None}),
          (State(sensor("phase_gelar_energy_total"), "1.2"), {"native_value": 1.2, "native_unit_of_measurement": "kWh"}),
          (State(sensor("phase_gelar_runtime_total"), "3.5"), {"native_value": 3.5, "native_unit_of_measurement": "h"}),
      )
      assert state(ha, sensor("phase_gelar_cycles_total")) == "7"
      assert float(state(ha, sensor("phase_gelar_energy_total"))) == 1.2
      assert float(state(ha, sensor("phase_gelar_runtime_total"))) == 3.5


  async def test_a_reload_while_a_phase_is_pending(
          purifier: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
      """A delay pending at the reload dies with its carrier: no error, no phase from it; the new carrier counts from its first reading."""
      await watts(purifier, 120)
      await tick(purifier, freezer, 25)
      assert state(purifier, RUNNING) == "on"
      await reload(purifier, DEVICES)
      await tick(purifier, freezer, 10)
      assert [r.getMessage() for r in caplog.records if r.levelname == "ERROR"] == []
      assert state(purifier, CURRENT) == "idle"
      await tick(purifier, freezer, 25)
      assert state(purifier, CURRENT) == "gelar"
  ```

  D1's `test_nothing_of_the_phases_when_the_carrier_is_not_created` becomes `test_nothing_that_follows_the_carrier_when_it_is_not_created`, docstring "The carrier's ID belongs to another integration: no phase entity, nor the appliance's cycle entities, is created; its mirrors are.", and gains (from `test_phases.py`'s)

  ```python
      assert ha.states.get(sensor("runtime_total")) is None
      assert ha.states.get(sensor("power")) is not None
      …
      assert any(sensor("runtime_total") in message and RUNNING in message for message in errors), errors
  ```

  The other files:
  - `tests/test_cycle.py`: delete `MODE_KEY`, `MODE_APPLIANCE`, `MODES`, `MODE_DEVICES`, `CURRENT` and `test_a_cycle_is_sent_after_its_state_a_mode_ending_into_the_next` (D1's `test_a_phases_cycle_is_sent_after_its_state_its_end_last` and `test_a_handover_never_shows_idle`); the module docstring's sources become "(the detector's Carrier and PhaseRunning, Open, Runs)".
  - `tests/test_opening.py`: delete `test_the_openings_are_a_cycle_for_phases` (ruling 15; both params).
  - `tests/test_statistics.py`: delete the `# --- modes ---` section (`MODE_*`, `mode_sensor`, `test_modes_meters`), `MODES_MINIMAL`, `test_mode_energy_without_energy_is_refused` and `test_no_period_for_energy_without_energy_passes`. Task 3 brings each back for phases.
  - `tests/test_init.py` (ruling 19): the module docstring ("Three made-up features stand in for real ones: `gauge` creates a sensor and a binary sensor, and can create a `spare` sensor it never builds; `tags` …; `watch` …"; its first line "the configuration, devices, references, taken IDs, reloads and the entry"); `ECHO`, `Echo`, the `echo` feature and `gauge`'s `roles=(roles.Provides(...),)` go; the fixture's docstring "Put `gauge`, `tags` and `watch` in FEATURES for the test."; delete `test_a_capability_reaches_the_feature_that_requires_it`, `test_what_follows_an_entity_not_created_is_not_created_either`, `test_a_renamed_capability_reaches_the_feature_that_requires_it` and `test_invalid_device_is_refused`'s two `echo` params; `test_reload_that_drops_a_feature_removes_its_entities` sets up `{**WIDGET, "watch": {"of": "gauge_level"}}` and asserts `SEEN` is gone.
  - `tests/test_features.py`: `test_no_entity_key_repeats_its_namespace`'s docstring "An appliance's `appliance` would be sensor.pururu_<key>_appliance_appliance: a fixed key never repeats its namespace."; `test_a_device_key_neither_provides_requires_nor_acts` becomes `test_a_device_key_neither_acts_nor_derives` over `("Actions", "Derived")`; `test_the_aspects_each_builder_offers` and `test_a_counter_is_totalled` lose `modes`.
  - `tests/test_alerts.py`: `test_alerts_alone_are_not_a_feature` expects `"(appliance, door, window, lights, switches)"`.
  - `docs/develop/writing-a-feature.mdx`: its `features/__init__.py` example loses `from .phases import PHASES` and `"phases": PHASES,` (`test_the_develop_docs_examples_import_what_exists` resolves every relative import).

- [ ] **Step 5: The fixture in the new syntax, and the snapshot.** In `tests/fixtures/house.yaml`:
  - `laundry_washer`'s `phases:` block goes; its bands become `running_program`'s phases, `for` → `on_delay`, each named (the spec's washer):
    ```yaml
          running_program:
            above: 4
            on_delay: {minutes: 1}
            off_delay: {minutes: 2}
            phases:
              heating: {name: Aquecendo, above: 1000}
              spinning: {name: Centrifugando, above: 50, below: 1000, on_delay: {minutes: 3}}
    ```
    and its `stuck` alert's `when: phase_current` becomes `when: appliance_phase_current`;
  - `water_filter`'s `modes:` block goes; its modes become `running_program`'s phases:
    ```yaml
          running_program:
            above: 2.9
            on_delay: {seconds: 1}
            off_delay: {minutes: 1}
            phases:
              gelar: {name: Gelar, above: 4, below: 150, on_delay: {seconds: 10}, off_delay: {minutes: 3}}
              quente: {name: Água quente, above: 150, below: 400, on_delay: {seconds: 30}, off_delay: {seconds: 30}}
    ```
    (its `statistics:` comes back per phase in Task 3).

  Then rewrite the snapshot and check the diff is exactly the planned one. The checker, saved as `<scratchpad>/iddiff_d2.py`:

  ```python
  """The ID snapshot's change: what went and what came, by data key."""
  import json
  import sys

  before, after = (json.load(open(path)) for path in sys.argv[1:3])
  for key in before:
      old = {tuple(each) for each in before[key]}
      new = {tuple(each) for each in after[key]}
      print(key, "gone", len(old - new), "new", len(new - old))
      for each in sorted(old - new):
          print("  -", *each)
      for each in sorted(new - old):
          print("  +", *each)
  ```

  ```sh
  git show HEAD:tests/fixtures/house_ids.json > <scratchpad>/ids_before_t2.json
  PURURU_UPDATE_IDS=1 uv run pytest tests/test_ids.py -n 0 -q
  python3 <scratchpad>/iddiff_d2.py <scratchpad>/ids_before_t2.json tests/fixtures/house_ids.json
  ```

  Expected: `entities gone 41 new 52`, `generated gone 0 new 0`. Gone, exactly: `sensor pururu_laundry_washer_phase_current`, `sensor pururu_water_filter_mode_current`, `…_mode_last`, and per mode (`gelar`, `quente`) `…_mode_<mode>_{last_cycle_start,last_cycle_end,last_cycle_duration,last_cycle_energy,cycles_total,runtime_total,energy_total}` and `…_mode_<mode>_{runtime,cycles,energy}_{today,week,month,year}`. New, exactly: for `laundry_washer` (`heating`, `spinning`, `other`) and `water_filter` (`gelar`, `quente`, `other`), `binary_sensor pururu_<device>_appliance_phase_<phase>` and `sensor pururu_<device>_appliance_phase_<phase>_{last_cycle_start,last_cycle_end,last_cycle_duration,last_cycle_energy,cycles_total,runtime_total,energy_total}`, plus `sensor pururu_<device>_appliance_phase_{current,last}` each. Nothing of `appliance_*` moves. Any other line fails the task: find the cause, don't accept it.

- [ ] **Step 6: GREEN, and the whole suite.**

  ```sh
  uv run pytest tests/test_program_entities.py tests/test_features.py tests/test_init.py tests/test_ids.py -n 0 -q
  uv run pytest -q
  ```

  Expected: all pass; then `1256 passed`: 1342, minus `test_modes.py` (58) and `test_phases.py` (27), minus `test_cycle.py` 1, `test_opening.py` 2, `test_statistics.py` 4, `test_init.py` 5 and `test_features.py` 1 (three capability rules out, two rules in), plus `test_program_entities.py` 12 (seven reference tests, five ports).

- [ ] **Step 7: Commit, push, review.**

  ```sh
  git add -A custom_components tests docs
  git commit -m "pururu: the appliance's phases replace modes and phases; Derived puts them in the index (refactor D2)

  running_program's phases are the appliance's: appliance_phase_<key>_*,
  appliance_phase_current and appliance_phase_last, listed by the new Derived
  role so alerts, reactions and when: can name them. The modes and phases
  features go, with cycle_from, Provides, Requires and the capability check.
  The ID snapshot changes on purpose: the modes' and phases' 41 IDs go, the
  phases' 52 come.

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM"
  git push
  ```

  The PR body's update step gains ruling 21's steps 3–5 (`gh pr edit <n> --body-file <scratchpad>/pr.md`). Wait for `headRefOid` to equal `git rev-parse HEAD`, then remove and add `claude-review`. Fix what it finds before Task 3.

---

### Task 3: Aspects at places; statistics in `running_program`, each phase and `other`

An aspect sits at `Place`s, paths from the builder's block (ruling 7), and `Counters` becomes a tuple of `Counted` places (ruling 8). The appliance counts at four (ruling 9): its block (`idle_energy`), `running_program` (`runtime`, `cycles`: its own totals, IDs unchanged), each phase and `other` (`runtime`, `cycles`, `energy`). `checks.keys_distinct` refuses two entities of one device with one unique ID (ruling 12). The `item_energy_*` translations come back unchanged, and `other`'s meters get their own (ruling 10). The snapshot changes a second time, only by additions: the phases' 72 meters.

**Files:**
- Modify `custom_components/pururu/core/feature.py` (`Path`, `EACH`, `walk`, `Place`; `Aspect` at places), `core/roles.py` (`Counted`; `Counters(places)`).
- Modify `custom_components/pururu/setup/catalogue.py` (mount and keys at paths), `setup/checks.py` (`keys_distinct`), `setup/schema.py` (`CHECKS`).
- Modify `custom_components/pururu/aspects/{statistics,alerts,notifications}.py`.
- Modify `custom_components/pururu/features/cycle/program/{schema,__init__}.py` (`PHASE_COUNTERS`, `counted`; `program_of` reads only other's delays), `features/appliance/__init__.py`, `features/opening/__init__.py`, `device_keys/{programs,reactions}.py`.
- Modify `custom_components/pururu/translations/{en,pt-BR}.json`, `icons.json`.
- Create `tests/test_catalogue.py`.
- Modify `tests/test_features.py`, `tests/test_statistics.py`, `tests/test_appliance.py`, `tests/test_alerts.py`, `tests/test_checks.py`, `tests/test_program_entities.py`, `tests/test_program.py`, `tests/fixtures/house.yaml`, `tests/fixtures/house_ids.json`.
- Modify the docs examples that ask for the appliance's `runtime`/`cycles` (Step 9): `docs/index.mdx`, `docs/getting-started/first-device.mdx` (three), `docs/concepts/statistics.mdx`, `docs/reference/configuration.mdx`, `docs/features/appliance.mdx`. Task 4 rewrites the prose.

**Interfaces:**

Consumes (Task 2): `roles.Derived`, `program.keys_of`; (D1) `program.PHASE`, `OTHER`.

Produces:

```python
# core/feature.py
type Path = tuple[str, ...]
EACH = "*"
def walk(value: Any, path: Path, at: Path = ()) -> Iterator[tuple[Path, Any]]
@dataclass(frozen=True, kw_only=True)
class Place:
    path: Path = ()
    schema: Callable[[Any], Any]
    keys: Mapping[str, Platform]
    named: Callable[[str], str]
    example: Any
    item: Callable[[str, Any], Item] | None = None
    check: Callable[[Mapping[str, Any], Mapping[str, Any]], None] | None = None
@dataclass(frozen=True, kw_only=True)
class Aspect:
    key: str
    offered: Callable[[Feature], bool]
    places: Callable[[Feature, str], tuple[Place, ...]]
    build: AspectBuild
    mount_absent: bool = True

# core/roles.py
@dataclass(frozen=True, kw_only=True)
class Counted:
    needs: Mapping[str, str | None]
    at: tuple[str, ...] = ()
    item: Callable[[str, Any], Item] | None = None
    named: str | None = None
@dataclass(frozen=True)
class Counters:
    places: tuple[Counted, ...]

# features/cycle/program (re-exported); D1's COUNTERS goes
PHASE_COUNTERS: dict[str, str | None]
def counted(at: Path) -> tuple[Counted, ...]

# setup/checks.py
def keys_distinct(house, index, builders) -> Iterator[vol.Invalid]
```

- [ ] **Step 1: The failing tests.**

  Create `tests/test_catalogue.py`:

  ```python
  """setup/catalogue: an aspect mounted at its places (feature.walk's paths), and the keys it lists there."""

  from typing import Any

  from homeassistant.core import HomeAssistant
  import pytest
  import voluptuous as vol

  from helpers import DOMAIN, module

  # Statistics at each of the appliance's four places: its block, its running
  # program, each phase, other
  PROGRAM: dict[str, Any] = {
      "above": 4,
      "statistics": {"cycles": ["today"]},
      "phases": {"gelar": {"name": "Gelar", "above": 40, "statistics": {"cycles": ["month"]}}},
      "other": {"statistics": {"runtime": ["week"]}},
  }
  APPLIANCE: dict[str, Any] = {
      "power": "sensor.demo_plug_power",
      "energy": "sensor.demo_plug_energy",
      "running_program": PROGRAM,
      "statistics": {"idle_energy": ["year"]},
  }


  def mount(block: Any) -> Any:
      catalogue = module("setup.catalogue")
      return catalogue.mount(catalogue.builders()["appliance"], "appliance", block)


  @pytest.mark.parametrize(("value", "path", "found"), [
      pytest.param({"a": 1}, (), [((), {"a": 1})], id="the block itself"),
      pytest.param({"a": {"b": 2}}, ("a",), [(("a",), {"b": 2})], id="a key"),
      pytest.param({"a": {"b": 2}}, ("x",), [], id="a key missing"),
      pytest.param({"a": 5}, ("a", "b"), [], id="not a map on the way"),
      pytest.param({"a": {"x": {"s": 1}, 1: {"s": 2}}}, ("a", "*"),
                   [(("a", "x"), {"s": 1}), (("a", "1"), {"s": 2})], id="each, a number made text"),
      pytest.param({"a": 5}, ("a",), [(("a",), 5)], id="the last may be anything"),
  ])
  def test_walk_finds_each_container(
          ha: HomeAssistant, value: Any, path: tuple[str, ...], found: list[Any]) -> None:
      assert list(module("core.feature").walk(value, path)) == found


  def test_statistics_is_mounted_at_every_place(ha: HomeAssistant) -> None:
      """Taken out before the builder's schema (which refuses it everywhere), validated per place, put back where it sat."""
      block = mount(APPLIANCE)
      program = block["running_program"]
      assert block["statistics"] == {"idle_energy": ["year"]}
      assert program["statistics"] == {"runtime": [], "cycles": ["today"]}
      assert program["phases"]["gelar"]["statistics"] == {"runtime": [], "cycles": ["month"], "energy": []}
      assert program["other"]["statistics"] == {"runtime": ["week"], "cycles": [], "energy": []}


  def test_other_without_its_block_has_no_statistics(ha: HomeAssistant) -> None:
      """other runs anyway; its meters are asked for in `other:`, so without it there is no place to mount."""
      program = {key: value for key, value in PROGRAM.items() if key != "other"}
      block = mount({**APPLIANCE, "running_program": program})
      assert "other" not in block["running_program"]


  def test_a_phase_keyed_statistics_is_a_phase(ha: HomeAssistant) -> None:
      """The phases' map isn't a place: only each phase is."""
      phase = {"name": "Estatística", "above": 300, "statistics": {"cycles": ["today"]}}
      program = {**PROGRAM, "phases": {**PROGRAM["phases"], "statistics": phase}}
      block = mount({**APPLIANCE, "running_program": program})
      assert block["running_program"]["phases"]["statistics"]["name"] == "Estatística"
      assert block["running_program"]["phases"]["statistics"]["statistics"]["cycles"] == ["today"]


  @pytest.mark.parametrize(("program", "path"), [
      pytest.param(5, ["running_program"], id="the program"),
      pytest.param({"above": 4, "phases": 5}, ["running_program", "phases"], id="its phases"),
      pytest.param({"above": 4, "phases": {"gelar": 5}}, ["running_program", "phases", "gelar"],
                   id="a phase"),
      pytest.param({"above": 4, "phases": {"gelar": {"name": "Gelar", "above": 40}}, "other": 5},
                   ["running_program", "other"], id="other"),
  ])
  def test_a_place_that_isnt_a_map_is_refused_cleanly(
          ha: HomeAssistant, program: Any, path: list[str]) -> None:
      """vol.Invalid at its path, not a KeyError or TypeError from taking the aspect's key out."""
      schema = module("setup.schema").CONFIG_SCHEMA
      house = {"devices": {"washer": {"name": "Washer", "appliance": {
          "power": "sensor.demo_plug_power", "running_program": program}}}}
      with pytest.raises(vol.Invalid) as refused:
          schema({DOMAIN: house})
      paths = ([error.path for error in refused.value.errors]
               if isinstance(refused.value, vol.MultipleInvalid) else [refused.value.path])
      assert [DOMAIN, "devices", "washer", "appliance", *path] in paths


  def test_a_refusal_at_a_place_says_where(ha: HomeAssistant) -> None:
      program = {**PROGRAM, "phases": {"gelar": {"name": "Gelar", "above": 40,
                                                 "statistics": {"cycles": ["daily"]}}}}
      with pytest.raises(vol.MultipleInvalid) as refused:
          mount({**APPLIANCE, "running_program": program})
      assert [error.path for error in refused.value.errors] == [
          ["running_program", "phases", "gelar", "statistics", "cycles", 0]]


  def test_keys_lists_the_meters_at_every_place(ha: HomeAssistant) -> None:
      """The appliance's own (runtime_today), each phase's as its item's (phase_gelar_*), other's (phase_other_*)."""
      catalogue = module("setup.catalogue")
      rows = {key: (by, item) for _, key, _, by, item in catalogue.keys({"appliance": mount(APPLIANCE)})}
      assert rows["runtime_today"] == ("statistics", None)
      assert rows["idle_energy_year"] == ("statistics", None)
      assert rows["phase_gelar_energy_month"] == ("statistics", "phase_gelar")
      assert rows["phase_other_cycles_week"] == ("statistics", "phase_other")
      assert rows["phase_gelar_cycles_total"] == (None, None)
      assert "energy_today" not in rows  # the running program counts no energy
  ```

  In `tests/test_statistics.py`:
  - the module docstring: "Five builders build per-period `Meter` entities through the statistics aspect (aspects/statistics.py): appliance, door, window, programs, reactions. The appliance counts at four places: its block, its running program, each phase and other."
  - `test_appliance_meters`' block asks `runtime` and `cycles` in `running_program` (`"statistics": {counter: list(PERIODS) for counter in ("runtime", "cycles")}` inside it) and `{"idle_energy": list(PERIODS)}` in the block; its assertions stay.
  - after `APPLIANCE_MINIMAL` (two blank lines before the first test, which Task 2's cut left out), a helper, and `test_a_repeated_period_is_refused`/`test_an_unknown_period_is_refused` ask in the running program (`block = counting({"cycles": ["today", "today"]})`, `counting({"cycles": ["daily"]})`):
    ```python
    def counting(statistics: dict[str, Any]) -> dict[str, Any]:
        """APPLIANCE_MINIMAL with `statistics` in its running program."""
        return {**APPLIANCE_MINIMAL, "running_program": {**APPLIANCE_MINIMAL["running_program"],
                                                         "statistics": statistics}}
    ```
  - a `# --- phases ---` section before `# --- door and window ---` (Task 2 removed the modes'):
    ```python
    PHASE_KEY = "demo_filter"
    PHASE_NAME = "Demo filter"
    PHASE_COUNTERS = ("runtime", "cycles", "energy")
    PHASE_STATISTICS = {counter: list(PERIODS) for counter in PHASE_COUNTERS}
    PHASE_ICONS = {
        "gelar_runtime_today": "mdi:timer-sand",
        "gelar_cycles_week": "mdi:counter",
        "gelar_energy_month": "mdi:lightning-bolt",
        "other_runtime_today": "mdi:timer-sand",
        "other_energy_year": "mdi:lightning-bolt",
    }
    PHASE_NAMES = {
        "en": {
            "gelar_runtime_today": "Gelar runtime today",
            "gelar_cycles_week": "Gelar cycles this week",
            "gelar_energy_month": "Gelar energy this month",
            "other_runtime_today": "Other phase runtime today",
            "other_cycles_week": "Other phase cycles this week",
            "other_energy_year": "Other phase energy this year",
        },
        "pt-BR": {
            "gelar_runtime_today": "Tempo de Gelar hoje",
            "gelar_cycles_week": "Ciclos de Gelar na semana",
            "gelar_energy_month": "Energia de Gelar no mês",
            "other_runtime_today": "Tempo de outra fase hoje",
            "other_cycles_week": "Ciclos de outra fase na semana",
            "other_energy_year": "Energia de outra fase no ano",
        },
    }


    def phase_sensor(suffix: str) -> str:
        return f"sensor.pururu_{PHASE_KEY}_appliance_phase_{suffix}"


    def phases(statistics: dict[str, Any], **appliance: Any) -> dict[str, Any]:
        """The demo filter: phase gelar and other, each with `statistics`."""
        return {PHASE_KEY: {"name": PHASE_NAME, "appliance": {
            "power": "sensor.demo_plug_power",
            "running_program": {
                "above": 4,
                "phases": {"gelar": {"name": "Gelar", "above": 40, "statistics": statistics}},
                "other": {"statistics": statistics},
            },
            **appliance,
        }}}


    @pytest.mark.parametrize("language", ["en", "pt-BR"])
    async def test_phases_meters(ha: HomeAssistant, language: str) -> None:
        ha.config.language = language
        assert await setup(ha, phases(PHASE_STATISTICS, energy="sensor.demo_plug_energy"))
        for phase in ("gelar", "other"):
            for counter in PHASE_COUNTERS:
                for period in PERIODS:
                    assert_meter(ha, phase_sensor(f"{phase}_{counter}_{period}"))
        for suffix, icon in PHASE_ICONS.items():
            assert icon_of(ha, phase_sensor(suffix)) == icon
        for suffix, expected in PHASE_NAMES[language].items():
            assert friendly_name(ha, phase_sensor(suffix)) == f"{PHASE_NAME} {expected}"
    ```
  - at the end, the refusals Task 2 removed for modes, now for phases, and the places' own rule:
    ```python
    async def test_the_appliances_counters_sit_where_they_count(ha: HomeAssistant) -> None:
        """runtime and cycles are its running program's, idle energy its block's: each refused at the other place."""
        for block in ({**APPLIANCE_MINIMAL, "statistics": {"cycles": ["today"]}},
                      counting({"idle_energy": ["today"]})):
            assert not await setup(ha, {APPLIANCE_KEY: {"name": APPLIANCE_NAME, "appliance": block}})


    @pytest.mark.parametrize("place", ["gelar", "other"])
    async def test_a_phases_energy_needs_the_appliances_energy(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, place: str
    ) -> None:
        """The setting is the appliance's, looked up in its whole block: the phase has none of its own."""
        devices = phases({})
        program = devices[PHASE_KEY]["appliance"]["running_program"]
        (program["phases"]["gelar"] if place == "gelar" else program["other"])["statistics"] = {
            "energy": ["today"]}
        assert not await setup(ha, devices)
        where = "phases->gelar" if place == "gelar" else "other"
        assert f"appliance->running_program->{where}" in caplog.text
        assert "statistics.energy needs energy" in caplog.text


    async def test_no_period_for_a_phases_energy_without_energy_passes(ha: HomeAssistant) -> None:
        assert await setup(ha, phases({"energy": []}))
    ```

  In `tests/test_appliance.py`:
  - `test_invalid_block_is_refused`'s `repeated period` and `unknown period` ask in the running program (`{**APPLIANCE, "running_program": {**APPLIANCE["running_program"], "statistics": {"cycles": ["today", "today"]}}}`, and `["daily"]`), else they'd pass for the wrong reason (an unknown counter); add `pytest.param({**APPLIANCE, "statistics": {"cycles": ["today"]}}, id="cycles in the block")`;
  - `STATISTICS` asks in the running program:
    ```python
    STATISTICS = {**APPLIANCE, "running_program": {
        **APPLIANCE["running_program"],
        "statistics": {"runtime": ["today", "week"], "cycles": ["today", "month"]}}}
    ```
  - before `test_two_devices_have_their_own_meters` (Review Focus 3):
    ```python
    async def test_the_appliances_meters_keep_their_ids(metered: HomeAssistant) -> None:
        """runtime and cycles count in running_program now: their meters keep the appliance's IDs and names, and a customisation survives a reload."""
        registry = er.async_get(metered)
        for key, name in (("runtime_today", "Runtime today"), ("cycles_month", "Cycles this month")):
            entry = registry.async_get(sensor(key))
            assert entry is not None, key
            assert entry.unique_id == f"pururu_{KEY}_appliance_{key}"
            assert entry.translation_key == key
            assert metered.states.get(sensor(key)).attributes["friendly_name"] == f"Demo washer {name}"
        registry.async_update_entity(sensor("runtime_today"), name="Hoje")
        await reload(metered, {KEY: {"name": "Demo washer", "appliance": STATISTICS}})
        assert registry.async_get(sensor("runtime_today")).name == "Hoje"
    ```

  `tests/test_alerts.py`'s `test_an_alert_may_watch_a_meter`: `metered = {**APPLIANCE, "running_program": {**APPLIANCE["running_program"], "statistics": {"runtime": ["today"]}}}`.

  `tests/test_checks.py`'s `test_a_check_says_where`, after `two devices' IDs`:

  ```python
      pytest.param(
          {"devices": {"washer": washer(appliance={**APPLIANCE, "running_program": {
              **APPLIANCE["running_program"],
              "phases": {"gelar": {"name": "Gelar", "above": 40},
                         "gelar_cycles_today": {"name": "Hoje", "above": 300}}}})}},
          ["devices", "washer"],
          "device washer: pururu_washer_appliance_phase_gelar_cycles_today would be two entities",
          id="two entities of one device"),
  ```

  `tests/test_program_entities.py`, before `# --- restarts and reloads ---` (the port of `test_meters_per_mode`, Task 2's table):

  ```python
  async def test_meters_per_phase(ha: HomeAssistant, freezer: Any) -> None:
      """Each phase's statistics meter its own totals; a period not asked has no meter."""
      periods = {"runtime": ["today"], "cycles": ["today", "month"], "energy": ["today"]}
      program = {**RUNNING_PROGRAM, "phases": {key: {**phase, "statistics": periods}
                                               for key, phase in RUNNING_PROGRAM["phases"].items()}}
      assert await setup(ha, {KEY: {"name": "Demo filter", "appliance": {
          "power": POWER, "energy": ENERGY, "running_program": program}}})
      await watts(ha, IDLE_W)
      await tick(ha, freezer, 125)
      for _ in range(2):
          await kwh(ha, 100.0)
          await cool(ha, freezer)
          await kwh(ha, 100.05)
          await watts(ha, IDLE_W)
          await tick(ha, freezer, 125)
      await tick(ha, freezer, 60)
      assert float(state(ha, sensor("phase_gelar_cycles_today"))) == 2
      assert float(state(ha, sensor("phase_gelar_cycles_month"))) == 2
      assert float(state(ha, sensor("phase_gelar_energy_today"))) == pytest.approx(0.1)
      assert float(state(ha, sensor("phase_gelar_runtime_today"))) == pytest.approx(
          float(state(ha, sensor("phase_gelar_runtime_total"))), abs=0.01)
      assert float(state(ha, sensor("phase_quente_cycles_today"))) == 0
      assert ha.states.get(sensor("phase_gelar_runtime_month")) is None
      assert ha.states.get(sensor("phase_gelar_cycles_today")).attributes["unit_of_measurement"] == "cycles"
  ```

  ```sh
  uv run pytest tests/test_catalogue.py tests/test_statistics.py tests/test_checks.py tests/test_appliance.py tests/test_program_entities.py tests/test_alerts.py -n 4 -q
  ```

  Expected: `29 failed, 9 errors` (measured on the prototype). The 9 errors are the tests of `test_appliance.py`'s `metered` fixture, whose setup is refused (`statistics` in `running_program`), `test_the_appliances_meters_keep_their_ids` among them. Failing: every `test_catalogue.py` test but the four `test_a_place_that_isnt_a_map_is_refused_cleanly` (the builder's schema refuses those already; they pin that the path walk keeps it so); `test_statistics.py`'s `test_appliance_meters`, `test_phases_meters`, the refusals and the phase tests; `cycles in the block` (valid until `cycles` counts in the running program); `two entities of one device`; `test_meters_per_phase`; `test_an_alert_may_watch_a_meter`; and the other `metered`-less appliance meter tests (`test_today_resets_at_local_midnight`, `test_runtime_restores`, `test_a_restored_meter_is_not_seeded_again`, `test_a_meter_is_not_created_without_its_total`, `test_two_devices_have_their_own_meters`).

- [ ] **Step 2: Paths and places, in `core/`.**

  `core/feature.py` (imports gain `Iterator`; `Literal` goes), replacing `AspectBuild`'s comment and `Aspect`:

  ```python
  # From a builder's block to a container of it: the keys to follow, EACH for
  # every key of a map. () is the block itself
  type Path = tuple[str, ...]
  # Every key of a map, in a Path: no slug is "*"
  EACH = "*"


  def walk(value: Any, path: Path, at: Path = ()) -> Iterator[tuple[Path, Any]]:
      """Each container `path` names in `value`, with its own path (EACH made each key).

      A key missing, or a map expected where there's none, names no container:
      nothing is yielded for it. The last container may be anything.
      """
      if not path:
          yield at, value
          return
      if not isinstance(value, Mapping):
          return
      head, *rest = path
      for key in value if head == EACH else (head,) if head in value else ():
          # As the builder's schema returns it: cv.slug makes YAML's 1 "1"
          yield from walk(value[key], tuple(rest), (*at, str(key)))


  @dataclass(frozen=True, kw_only=True)
  class Place:
      """Where an aspect's key sits in a builder's block, and what the aspect has there."""

      # The containers of its key; () the block itself
      path: Path = ()
      # Validates the aspect's value in a container there
      schema: Callable[[Any], Any]
      # The local entity keys it adds per container: suffixes of the container's
      # item, with one; none for the ready-made notifications (automations)
      keys: Mapping[str, Platform]
      # The translation key each of its keys is named under
      named: Callable[[str], str]
      # A valid value, for the contract test
      example: Any
      # The item a container there is, from its key and the container: its
      # keys are the item's (<slug>_<key>); None: the builder's own
      item: Callable[[str, Any], Item] | None = None
      # Refuses (vol.Invalid) what it can't be once validated, given the
      # builder's whole block and the container, its value put back
      check: Callable[[Mapping[str, Any], Mapping[str, Any]], None] | None = None


  # hass, the device in the builder's namespace, the builder, its validated block
  # (the aspect's value put back at each of its places), the common texts
  type AspectBuild = Callable[
      [HomeAssistant, Device, Feature, Any, Texts], list[PururuEntity]
  ]


  @dataclass(frozen=True, kw_only=True)
  class Aspect:
      """A concern written once, mounted at its places in the block of every builder offering it."""

      # The key it mounts: "statistics", "alerts", "notifications"
      key: str
      # Whether this builder offers it: it has what the aspect needs (Counters;
      # at least one ready-made alert; at least one Happening)
      offered: Callable[[Feature], bool]
      # Where its key sits for this builder, given the builder's key in the
      # device (the notifications' refusals name it): the block, a map's items,
      # or deeper (a running program, each of its phases)
      places: Callable[[Feature, str], tuple[Place, ...]]
      # Its entities, from the builder's validated block
      build: AspectBuild
      # (mount_absent: as today)
      mount_absent: bool = True
  ```

  `core/roles.py` (`Literal` goes), replacing `Counters`:

  ```python
  @dataclass(frozen=True, kw_only=True)
  class Counted:
      """Totals it builds at one place of its block, <counter>_total; `statistics:` there asks for their meters."""

      # Counter -> the setting of the builder's whole block it needs (None: none)
      needs: Mapping[str, str | None]
      # Where `statistics:` sits: the path from the block to its containers
      # (feature.Path; EACH for each item of a map)
      at: tuple[str, ...] = ()
      # The item a container there is, from its key and the container: its
      # totals and meters are the item's, named with {item}; None: the builder's own
      item: Callable[[str, Any], Item] | None = None
      # The prefix its meters' translations are named under (<named>_<counter>_<period>,
      # other's own), instead of the statistics aspect's
      named: str | None = None


  @dataclass(frozen=True)
  class Counters:
      """Totals it builds, at each of its places (Counted); the statistics aspect meters them per period."""

      places: tuple[Counted, ...]
  ```

- [ ] **Step 3: Mount and keys at paths** (`setup/catalogue.py`; imports `EACH, Aspect, Device, Feature, Path, Place, item_key, walk` from `core.feature`). `_taken`, `_split`, `mount`, `_checked` and `_put` are replaced, `_at` and `_take` come, `keys`' aspect part walks each place, and `_per_item` goes (the `Items` keys inline in `keys`):

  ```python
  # An aspect's value by where it sat (its container's path, EACH made each
  # key) and the aspect's key, with the place it sat at
  type Taken = dict[tuple[Path, str], tuple[Place, Any]]


  def _taken(value: Any, aspect: Aspect, place: Place, taken: Taken, at: Path) -> Any:
      """`value` without the aspect's key, what the key held put in `taken` at `at`.

      Absent, or `value` not a map (left whole): `{}`, or nothing put when the
      aspect doesn't mount an absent key (Aspect.mount_absent).
      """
      if isinstance(value, dict) and aspect.key in value:
          taken[at, aspect.key] = (place, value[aspect.key])
          return {each: kept for each, kept in value.items() if each != aspect.key}
      if aspect.mount_absent:
          taken[at, aspect.key] = (place, {})
      return value


  def _take(
      value: Any,
      path: Path,
      aspect: Aspect,
      place: Place,
      taken: Taken,
      at: Path = (),
  ) -> Any:
      """`value` without the aspect's key in each container `path` names (feature.walk's rule), rebuilt along the path."""
      if not path:
          return _taken(value, aspect, place, taken, at)
      if not isinstance(value, dict):
          return value
      head, *rest = path
      keys = list(value) if head == EACH else [head] if head in value else []
      return {
          **value,
          **{
              key: _take(value[key], tuple(rest), aspect, place, taken, (*at, str(key)))
              for key in keys
          },
      }


  def _split(
      builder: Feature, name: str, aspects: tuple[Aspect, ...], value: Any
  ) -> tuple[Any, Taken]:
      """The block without the aspects' keys, and their values by where each sat (Aspect.places)."""
      rest = value
      taken: Taken = {}
      for aspect in aspects:
          for place in aspect.places(builder, name):
              rest = _take(rest, place.path, aspect, place, taken)
      return rest, taken


  def mount(builder: Feature, name: str, value: Any) -> Any:
      """Builder `name`'s block, validated, each offered aspect's value in it where it was.

      Each aspect's key is taken out of each container its places name (the
      block, each item, a running program, each phase: Aspect.places), and
      validated by that place's schema: absent, as `{}`, or left out
      (Aspect.mount_absent). The rest goes to the builder's own schema.
      This is the first stage: the builder's own schema refusal and each
      aspect's schema refusal are raised together, before either runs a check.
      Once every value is validated and back where it sat, the second stage
      runs: each place's check on each container (Place.check), and those
      refusals are raised together too, separately from the first stage's.
      """
      if not (aspects := aspects_of(builder)):
          return builder.schema(value)
      rest, taken = _split(builder, name, aspects, value)
      errors: list[vol.Invalid] = []
      block: Any = None
      try:
          block = builder.schema(rest)
      except vol.Invalid as error:
          errors.append(error)
      mounted: Taken = {}
      for (path, key), (place, each) in taken.items():
          try:
              mounted[path, key] = (place, place.schema(each))
          except vol.Invalid as error:
              error.prepend([*path, key])
              errors.append(error)
      if errors:
          raise vol.MultipleInvalid(_flat(errors))
      for (path, key), (_, each) in mounted.items():
          block = _put(block, path, key, each)
      if errors := _checked(block, mounted):
          raise vol.MultipleInvalid(_flat(errors))
      return block


  def _checked(block: dict[str, Any], mounted: Taken) -> list[vol.Invalid]:
      """Each place's check (Place.check) on each container it sat in; the refusals, with their path."""
      errors: list[vol.Invalid] = []
      for (path, _), (place, _) in mounted.items():
          if place.check is None:
              continue
          try:
              place.check(block, _at(block, path))
          except vol.Invalid as error:
              error.prepend(list(path))
              errors.append(error)
      return errors


  def _at(block: Mapping[str, Any], path: Path) -> Any:
      """The container at `path` in the validated block."""
      for key in path:
          block = block[key]
      return block


  def _put(block: dict[str, Any], path: Path, key: str, value: Any) -> Any:
      """`block` with `value` under `key` back where it sat, rebuilt along `path`."""
      if not path:
          return {**block, key: value}
      head, *rest = path
      return {**block, head: _put(block[head], tuple(rest), key, value)}
  ```

  `keys()`' docstring ends "`item` the item owning the key (an Items item, or a container an aspect's place makes one: a phase)"; after the `Derived` rows it yields the `Items` rows inline and then the aspects':

  ```python
          if (items := feature.role(Items)) is not None:
              yield from (
                  (name, item.key(suffix), platform, None, item.slug)
                  for item in items.of(device[name])
                  for suffix, platform in items.keys.items()
              )
          yield from _aspects_keys(name, feature, device[name])


  def _aspects_keys(
      name: str, feature: Feature, block: Any
  ) -> Iterator[tuple[str, str, Platform, str | None, str | None]]:
      """keys()' rows for the keys each aspect it offers adds, at each container of each of its places."""
      for aspect in aspects_of(feature):
          for place in aspect.places(feature, name):
              for path, container in walk(block, place.path):
                  item = None if place.item is None else place.item(path[-1], container)
                  yield from (
                      (
                          name,
                          item_key(entity_key, item),
                          platform,
                          aspect.key,
                          None if item is None else item.slug,
                      )
                      for entity_key, platform in place.keys.items()
                  )
  ```

  A phase's meter's `item` in the index is its item's slug (`phase_gelar`), as a program's is: only the reactions' check reads `item`, for `builder == "reactions"`.

- [ ] **Step 4: The aspects' places.**

  `aspects/statistics.py` (imports: `partial`; `Place`, `walk` from `core.feature`; `Counted, Counters` from `core.roles`; `Literal`, `Items` go). The module docstring's second paragraph: "Every builder with Counters builds its totals (<counter>_total) at each of its places (Counted: its block, each item, a running program, each phase); `statistics:` there asks for their meters by period." `KEY`'s comment: "The key, at each place a builder counts (Counted)". `_counters` stays; the rest after it becomes:

  ```python
  def _schema(counted: Counted) -> vol.Schema:
      """`statistics:` at a place: counter -> its periods; a schema of its own, so an unknown counter is refused."""
      return vol.Schema(
          {vol.Optional(counter, default=[]): PERIOD_LIST for counter in counted.needs}
      )


  def _named(counted: Counted, key: str) -> str:
      """The translation key `key` (`<counter>_<period>`) is named under, once for every builder.

      `key` itself for the builder's own, `item_<key>` (with the `{item}`
      placeholder) for an item's, `<named>_<key>` for a place named on its own
      (other's).
      """
      if counted.named is not None:
          return f"{counted.named}_{key}"
      return key if counted.item is None else f"item_{key}"


  def _example(counted: Counted) -> dict[str, list[str]]:
      """A period for each counter needing no setting: a builder's example has only what it requires."""
      return {
          counter: [next(iter(PERIODS))]
          for counter, setting in counted.needs.items()
          if setting is None
      }


  def _check(
      counted: Counted, block: Mapping[str, Any], container: Mapping[str, Any]
  ) -> None:
      """Refuse a counter with periods whose setting (Counted.needs) isn't in the builder's block.

      The whole block, not the container: a phase's energy needs the appliance's.
      """
      for counter, setting in counted.needs.items():
          if setting is not None and container[KEY][counter] and setting not in block:
              raise vol.Invalid(f"{KEY}.{counter} needs {setting}")


  def _place(counted: Counted) -> Place:
      """Where `statistics:` sits for these counters, and every meter it can add there: <counter>_<period>."""
      return Place(
          path=counted.at,
          schema=_schema(counted),
          keys={
              f"{counter}_{period}": Platform.SENSOR
              for counter in counted.needs
              for period in PERIODS
          },
          named=partial(_named, counted),
          example=_example(counted),
          item=counted.item,
          check=partial(_check, counted),
      )


  def _places(builder: Feature, _name: str) -> tuple[Place, ...]:
      """One place per Counted of the builder.

      Statistics doesn't need the builder's key in the device (`_name`): it names
      nothing to a person, unlike the ready-made notifications' messages.
      """
      return tuple(_place(counted) for counted in _counters(builder).places)


  def _meters(
      hass: HomeAssistant,
      device: Device,
      counted: Counted,
      asked: Mapping[str, list[str]],
      item: Item | None,
  ) -> Iterator[Meter]:
      """The meters `asked` names (counter -> periods), each metering its total's current entity ID."""
      for counter, periods in asked.items():
          total = f"{counter}_total"
          source = device.current_entity_id(hass, Platform.SENSOR, item_key(total, item))
          for period in periods:
              key = f"{counter}_{period}"
              yield Meter(
                  device, key, total, source, period, _named(counted, key), item=item
              )


  def _build(
      hass: HomeAssistant, device: Device, builder: Feature, block: Any, *_: Any
  ) -> list[PururuEntity]:
      """The meters asked for at each place, an item's for a container that is one.

      AspectBuild's `texts` (the common texts a ready-made alert's messages
      need) has nothing to build meters from; `*_` takes it without naming it.
      """
      return [
          meter
          for counted in _counters(builder).places
          for path, container in walk(block, counted.at)
          for meter in _meters(
              hass,
              device,
              counted,
              container[KEY],
              None if counted.item is None else counted.item(path[-1], container),
          )
      ]


  ASPECT = Aspect(
      key=KEY,
      offered=lambda builder: builder.role(Counters) is not None,
      places=_places,
      build=_build,
  )
  ```

  `aspects/alerts.py` (imports `partial`, `Place`; `Literal` goes): `_schema`, `_keys`, `_named` and `_placed` go, `_example` takes the presets, and

  ```python
  def _places(builder: Feature, _name: str) -> tuple[Place, ...]:
      """`alerts:` sits in the block, for every builder offering it: alert_<name> per ready-made alert.

      Each is named in the builder's namespace. Its refusals name the alert, not
      the builder's key in the device (`_name`).
      """
      presets = _presets(builder)
      return (
          Place(
              schema=settings_schema(presets),
              keys={f"alert_{name}": Platform.BINARY_SENSOR for name in presets},
              named=partial(qualified, builder.namespace),
              example=_example(presets),
          ),
      )
  ```

  `ASPECT` takes `places=_places` instead of the five callables.

  `aspects/notifications.py` (imports `partial`, `Place`; `Literal` and `Platform` go): `_schema`, `_keys`, `_example`, `_placed` become

  ```python
  def _places(builder: Feature, name: str) -> tuple[Place, ...]:
      """`notifications:` sits in the block, for every builder offering it; no entity key.

      Each enabled notification is an automation (plan). Its refusals name
      `name`, the builder's key in the device; its example is the first ready-made
      notification, with its default text.
      """
      happenings = _happenings(builder)
      return (
          Place(
              schema=schema(name, happenings),
              keys={},
              # Never asked, as it adds no key: under the builder's namespace, as a ready-made alert's
              named=partial(qualified, builder.namespace),
              example={next(iter(happenings)): None},
          ),
      )
  ```

  and `ASPECT` takes `places=_places`.

- [ ] **Step 5: Each builder's places.**

  `features/cycle/program/schema.py` (imports `EACH`, `Path` from `core.feature`, `Counted` instead of `Counters`); D1's `COUNTERS` becomes `PHASE_COUNTERS` (in the package's imports and `__all__`, with `counted`):

  ```python
  # Each phase's totals, for the statistics aspect to meter; energy needs the builder's `energy`
  PHASE_COUNTERS: dict[str, str | None] = {
      "runtime": None,
      "cycles": None,
      "energy": "energy",
  }


  def _phase_item(key: str, phase: Mapping[str, Any]) -> Item:
      """A configured phase's item: phase_<key>, named by its name."""
      return Item(slug=f"{PHASE}_{key}", name=phase["name"])


  def _other_item(*_: Any) -> Item:
      """Other's item: phase_other; its entities are named by their own translations."""
      return Item(slug=f"{PHASE}_{OTHER}", name=OTHER)


  def counted(at: Path) -> tuple[Counted, ...]:
      """Where a detected program at `at` counts: its own runtime and cycles, each phase's and other's.

      The program's own totals are its builder's (the appliance's runtime_total,
      cycles_total); a phase's and other's are phase_<key>_<counter>_total,
      other's meters named by their own translations (phase_other_*).
      """
      return (
          Counted(needs={"runtime": None, "cycles": None}, at=at),
          Counted(needs=PHASE_COUNTERS, at=(*at, "phases", EACH), item=_phase_item),
          Counted(
              needs=PHASE_COUNTERS,
              at=(*at, OTHER),
              item=_other_item,
              named=f"{PHASE}_{OTHER}",
          ),
      )
  ```

  and `program_of` builds other's band from its delays alone (ruling 23):

  ```python
          # Its name is only its item's: its entities are named by their own translations.
          # Only its delays: the mounted block holds its statistics too
          band = Band(on_delay=other["on_delay"], off_delay=other["off_delay"])
          phases.append(Phase(key=OTHER, name=OTHER, band=band))
  ```

  `tests/test_program.py`'s `test_the_keys_a_phase_creates`: `assert set(program.PHASE_COUNTERS) == {"runtime", "cycles", "energy"}`.

  `features/appliance/__init__.py` (roles import `Counted, Counters, Derived, Happenings, Presets`):

  ```python
          # Metered by the statistics aspect: idle energy in the block (it needs
          # the plug's energy), the rest in running_program, each phase and other
          Counters(
              (
                  Counted(needs={"idle_energy": "energy"}),
                  *program.counted((RUNNING_PROGRAM,)),
              )
          ),
  ```

  `features/opening/__init__.py`: `COUNTED = Counted(needs={"openings": None, "open_time": None})`, `ENTITY_KEYS` reads `COUNTED.needs`, `roles=(Counters((COUNTED,)),)`.

  `device_keys/programs.py` (imports `EACH`, `Counted`):

  ```python
  def _item(key: str, program: Mapping[str, Any]) -> Item:
      return Item(slug=key, name=program[CONF_NAME])


  # The statistics aspect meters them, `statistics:` in each program
  COUNTED = Counted(needs={"runtime": None, "cycles": None}, at=(EACH,), item=_item)
  ```

  `PER_PROGRAM` reads `COUNTED.needs`, `_items` returns `[_item(key, program) for key, program in config.items()]`, and the roles take `Counters((COUNTED,))`.

  `device_keys/reactions.py` (imports `EACH`, `Counted`):

  ```python
  # The statistics aspect meters it, `statistics:` in each reaction
  COUNTERS = Counters(
      (
          Counted(
              needs={"triggered": None},
              at=(EACH,),
              item=lambda key, reaction: Item(slug=key, name=reaction[CONF_NAME]),
          ),
      )
  )
  ```

- [ ] **Step 6: `checks.keys_distinct`** (`setup/checks.py`; imports `CONF_NAME`, `Device`, `from . import catalogue`), before `entity_ids_distinct`, and in `setup/schema.py`'s `CHECKS` right before `checks.entity_ids_distinct`:

  ```python
  def keys_distinct(
      house: Mapping[str, Any], index: Index, builders: Mapping[str, Feature]
  ) -> Iterator[vol.Invalid]:
      """Refuse two entities of one device with one unique ID, whatever their platforms.

      The index keeps one entity per qualified key and would lose the other. A
      phase keyed gelar_cycles_today has the binary sensor
      phase_gelar_cycles_today, phase gelar's meter's key.
      """
      for key, device in house[CONF_DEVICES].items():
          seen: set[str] = set()
          for name, entity_key, *_ in catalogue.keys(device):
              unique_id = Device(
                  key=key, name=device[CONF_NAME], namespace=builders[name].namespace
              ).object_id(entity_key)
              if unique_id in seen:
                  yield vol.Invalid(
                      f"device {key}: {unique_id} would be two entities",
                      path=[CONF_DEVICES, key],
                  )
                  break
              seen.add(unique_id)
  ```

  It reads `catalogue.keys`, not the index, which already lost one of the two. It refuses a key the builder *can* create, as every check over the index does: the phase `gelar_cycles_today` is refused beside `gelar` even with no statistics asked.

- [ ] **Step 7: The translations.** In `translations/en.json`, `translations/pt-BR.json` and `icons.json`, before `item_triggered_today`: the four `item_energy_{today,week,month,year}` Task 2 removed, unchanged (en "`{item} energy today`", "`… this week`", "`… this month`", "`… this year`"; pt-BR "`Energia de {item} hoje`", "`… na semana`", "`… no mês`", "`… no ano`"; icon `mdi:lightning-bolt`), and other's twelve meters, `phase_other_{runtime,cycles,energy}_{today,week,month,year}`:
  - en: "Other phase runtime today", "Other phase cycles this week", "Other phase energy this month"… (the counter as in `phase_other_<counter>_total`'s name, then the period as in `item_*`);
  - pt-BR: "Tempo de outra fase hoje", "Ciclos de outra fase na semana", "Energia de outra fase no mês"…;
  - icons: `mdi:timer-sand` (runtime), `mdi:counter` (cycles), `mdi:lightning-bolt` (energy).

- [ ] **Step 8: The contract test at places** (`tests/test_features.py`). The helpers read places:

  ```python
  def aspect_keys(aspect: Any, name: str, feature: Any) -> dict[str, Any]:
      """Every local key the aspect can add for this builder, at any of its places (an item's suffixes)."""
      return {key: platform for place in aspect.places(feature, name)
              for key, platform in place.keys.items()}


  def aspect_groups(aspect: Any, name: str, feature: Any) -> dict[str, Any]:
      """Where the aspect's keys for this builder are named, as each of its places says (Place.named)."""
      return {place.named(key): platform for place in aspect.places(feature, name)
              for key, platform in place.keys.items()}


  def put(block: Any, path: tuple[str, ...], key: str, value: Any) -> Any:
      """`block` with `value` under `key` in each container `path` names (feature.walk's rule)."""
      if not path:
          return {**block, key: value}
      head, *rest = path
      each = module("core.feature").EACH
      keys = list(block) if head == each else [head] if head in block else []
      return {**block, **{k: put(block[k], tuple(rest), key, value) for k in keys}}


  def with_examples(aspect: Any, name: str, feature: Any, block: Any) -> Any:
      """`block` with each place's example at every container the place names."""
      for place in aspect.places(feature, name):
          block = put(block, place.path, aspect.key, place.example)
      return block


  def with_value(aspect: Any, name: str, feature: Any, block: Any, value: Any) -> Any:
      """`block` with `value` under the aspect's key at every container of every place."""
      for place in aspect.places(feature, name):
          block = put(block, place.path, aspect.key, value)
      return block
  ```

  replacing `aspect_groups(aspect, feature)` and `placed`; `named_keys`' docstring reads "(Place.named, aspect_groups)". The tests, each as in the prototype:
  - `test_every_translated_entity_key_is_created`: `aspect_groups(aspect, name, feature)`.
  - `test_ready_made_alerts_line_up`, `test_ready_made_notifications_line_up`: `aspect_keys(aspect, name, feature)` for `aspect.keys(feature)`.
  - `test_an_aspects_keys_are_named_once`: per place, each key's `place.named(key)` is named (en, pt-BR) and has an icon; a place's names carry `{item}` all or none (other's none, ruling 24), and none without `place.item`:
    ```python
        for aspect, name, feature in pairs:
            for place in aspect.places(feature, name):
                with_item: set[bool] = set()
                for key, platform in place.keys.items():
                    translation = place.named(key)
                    for translations in (en, pt):
                        text = translations["entity"][platform][translation]["name"]
                        assert text, (name, key)
                        with_item.add("{item}" in text)
                    assert icons["entity"][platform][translation]["default"].startswith("mdi:"), (name, key)
                assert len(with_item) <= 1, (name, place.path)
                if place.item is None:
                    assert True not in with_item, (name, place.path)
    ```
  - `test_an_offered_aspect_validates_and_builds`: the example reaches every place (`assert list(walk(feature.example, place.path)), (name, place.path)`, ruling 11); `raw = with_examples(...)`; `bool(built) == bool(aspect_keys(...))`.
  - `test_a_builders_own_schema_refuses_an_aspects_key`: for each place, `feature.schema(put(valid, place.path, aspect.key, place.example))` raises (no more "one item" special case).
  - `test_mount_leaves_an_items_key_alone`: `in_items` is `any(place.path[:1] == (EACH,) …)` over the aspects' places.
  - `test_an_absent_aspect_key`: the containers are `walk(block, place.path)`'s over every place; `given = with_value(...)`; the appliance's example mounts `{"idle_energy": []}` in the block, `{"runtime": [], "cycles": []}` in `running_program`, and `{"runtime": [], "cycles": [], "energy": []}` in `phases.heating` and `other`.
  - `test_mount_skips_an_aspect_without_a_check` becomes `test_mount_skips_a_place_without_a_check`: `place = Place(schema=lambda value: value, keys={}, named=lambda key: key, example={})`, `Aspect(key="uninspected", offered=…, places=lambda builder, name: (place,), build=lambda hass, device, builder, block, texts: [])`.
  - `test_a_counter_is_totalled`: for each `Counted`, the mounted example reaches its place, and at each container the item's (or builder's) `<counter>_total` is one of the builder's own keys in `catalogue.keys` (`by is None`).
  - `test_a_counter_without_its_setting_is_refused`: over every `Counted` of every builder, `put(example, counted.at, "statistics", {counter: ["today"]})` is refused with `statistics.<counter> needs <setting>`, `{counter: []}` passes. It now reaches the appliance's block, each phase and other.

- [ ] **Step 9: The fixture, the snapshot and the docs examples.**

  `tests/fixtures/house.yaml`, every counter × period at every place (spec A1's rule):
  - `laundry_washer`'s appliance: `runtime`/`cycles` move into `running_program: statistics:`; `heating`, `spinning` and a new `other:` each get `statistics: {runtime: [today, week, month, year], cycles: [today, week, month, year], energy: [today, week, month, year]}`; the appliance's own `statistics:` keeps `idle_energy`;
  - `water_filter`'s `gelar`, `quente` and a new `other:` get the same `statistics:` (what `modes: statistics:` asked before Task 2).

  ```sh
  git show HEAD:tests/fixtures/house_ids.json > <scratchpad>/ids_before_t3.json
  PURURU_UPDATE_IDS=1 uv run pytest tests/test_ids.py -n 0 -q
  python3 <scratchpad>/iddiff_d2.py <scratchpad>/ids_before_t3.json tests/fixtures/house_ids.json
  ```

  Expected: `entities gone 0 new 72`, `generated gone 0 new 0`; the 72 are exactly `sensor pururu_<device>_appliance_phase_<phase>_{runtime,cycles,energy}_{today,week,month,year}` for the six phases (`heating`, `spinning`, `other` of the washer; `gelar`, `quente`, `other` of the filter). The appliance's `runtime_*`/`cycles_*` meters don't move.

  The docs examples asking for the appliance's `runtime`/`cycles` move them into `running_program: statistics:` (a flow `running_program: {…}` written as a block), keeping `idle_energy` in the appliance's `statistics:`: `docs/index.mdx`, `docs/getting-started/first-device.mdx` (three), `docs/concepts/statistics.mdx`, `docs/reference/configuration.mdx`, `docs/features/appliance.mdx`. `git grep -n -B6 'runtime: \[\|cycles: \[' -- docs README.md` shows each; only `modes.mdx` keeps its old block (Task 4 deletes the page).

- [ ] **Step 10: GREEN, the whole suite, coverage.**

  ```sh
  uv run pytest tests/test_catalogue.py tests/test_features.py tests/test_statistics.py tests/test_ids.py -n 0 -q
  uv run pytest -q
  uv run pytest -q --cov=custom_components/pururu --cov-report=json:<scratchpad>/cov-t3.json
  ```

  Expected: all pass; `1281 passed`: 1256, plus `test_catalogue.py` 15, `test_statistics.py` 6 (two `test_phases_meters`, `test_the_appliances_counters_sit_where_they_count`, two `test_a_phases_energy_needs_the_appliances_energy`, `test_no_period_for_a_phases_energy_without_energy_passes`), `test_appliance.py` 2 (`cycles in the block`, `test_the_appliances_meters_keep_their_ids`), `test_checks.py` 1, `test_program_entities.py` 1. Coverage: exactly the 10 lines of Global Constraints missed, none in a file this task touched.

- [ ] **Step 11: Commit, push, review.**

  ```sh
  git add -A custom_components tests docs
  git commit -m "pururu: aspects at places; statistics in running_program, each phase and other (refactor D2)

  An aspect sits at places, paths from the builder's block (Place, walk,
  EACH); Counters is a tuple of Counted places. The appliance counts idle
  energy in its block, runtime and cycles in running_program (meters keep
  their IDs), and each phase's and other's runtime, cycles and energy. A new
  check refuses two entities of one device with one unique ID. The ID
  snapshot gains the phases' 72 meters.

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM"
  git push
  ```

  The PR body's update step is now complete (ruling 21: step 2's statistics sentence, step 3's per-phase `statistics:`). Wait for `headRefOid`, then remove and add `claude-review`. Fix what it finds before Task 4.

---

### Task 4: The Guide

The user-facing pages say what D2 changed: the appliance's `running_program` and its phases, one concept page for detected programs (ruling 16), and no `modes`, `phases` or `cycle_from` anywhere. The update step stays in the PR text (ruling 21): no page for it. No code changes; the tests that read pages (`test_presets.py` the appliance page's ready-made alerts, `test_alert_lights.py`, `test_alert2.py`, `test_notifications.py`, `test_events.py`) must keep passing.

**Files:**
- Create `docs/concepts/detected-programs.mdx`.
- Delete `docs/features/modes.mdx`, `docs/features/phases.mdx`.
- Modify `docs.json`, `docs/features/appliance.mdx`, `docs/features/door.mdx`, `docs/index.mdx`, `docs/getting-started/first-device.mdx`, `docs/concepts/{devices-and-features,entity-ids,statistics,alerts,events,programs}.mdx`, `docs/reference/{configuration,troubleshooting}.mdx`, `README.md`.

- [ ] **Step 1: The concept page**, `docs/concepts/detected-programs.mdx`. What it says, in this order (every behaviour is D1's, now the appliance's; the rulings named are D1's unless said):

  ```mdx
  ---
  title: Detected programs and phases
  description: A program pururu tells from a reading, the appliance running at all, and the phases of each run, each a band of the plug's power.
  ---

  A **detected program** is one pururu knows is running from a reading: a band of the plug's power, confirmed by delays. An appliance's `running_program` is one, the appliance running at all. Its **phases** are bands too: a washer heating, then spinning; a water purifier chilling or heating. The programs pururu runs itself are on [Programs](/concepts/programs).
  ```

  then the washer of the spec's contract ("The whole contract, 0.2.0": `running_program` with `above`, both delays, `statistics`, the phases `heating` and `spinning`), and these sections:
  - **A band** (`<Property>` each): `above`, `below` (strict, as Home Assistant's `numeric_state`: with `above: 1000` a reading of exactly 1000 is outside; at least one of them; `above` lower than `below`); `on_delay` (how long the reading stays in the band before the run starts; absent, 0: at once; a [time period](/features/appliance#settings)); `off_delay` (how long it stays out before the run ends; absent, 0).
  - **The running program**: required in `appliance`; a band, then `statistics` (`runtime`, `cycles`: the appliance's own meters, see [Statistics](/concepts/statistics)), `phases`, `other`; no `name` (`running_program takes no name: it is the appliance running`). A cycle **starts** at the moment its `on_delay` passed and **ends** at the moment the reading left the band; `off_delay` only confirms the end. A reading without a value (`unknown`, `unavailable`, not a number) counts every delay again from the next reading; what runs stays, and an end keeps the moment its reading left. A restart or reload keeps the running cycle and its phases (the carrier's snapshot), and Home Assistant's downtime isn't runtime; a restore that can't be read (a hand-edited `.storage`) starts from nothing.
  - **Phases** (`<Property>` each): `name` (required: it names the phase's entities), the band's four, `statistics` (`runtime`, `cycles`, `energy`; `energy` needs the appliance's `energy`). Their keys are slugs; `idle` and `other` are reserved, and a key whose entities would be another's is refused (`current`, `last`; `gelar` beside `gelar_cycles_total`; `gelar_cycles_today` beside `gelar`, whose meter it would be: `device <key>: <unique ID> would be two entities`). How they run:
    - a phase runs while the program runs and its reading has held its band for its `on_delay`; it ends after its `off_delay` out of the band, dated when it left, or when the program ends;
    - **bands may overlap**: two that hold at once run at once, and none wins;
    - a **dip** straight from a running phase's band into another's makes the other wait, once its `on_delay` passed, for the first to end or for a reading back in both bands; it then starts from when its `on_delay` passed. A short visit to another band is nothing (a chill's tail dipping into a sip's band isn't a drink);
    - an **idle gap**, a reading outside every band once a phase left its own (between `below: 40` and `above: 40`, or under the program's band), blocks nothing: the next phase starts after its own `on_delay`, and the first still ends, at the moment it left, unless its reading comes back;
    - a phase whose band holds before the program runs starts with it; after the program ends, a band still holding starts with the next cycle; while the program's reading is out (its `off_delay` counting), no phase starts;
    - at one instant: the program's end first, then the phases' ends in the order they started, then their starts in the configuration's order; a reading at the very instant a delay passes comes before it.
  - **`other`**: the built-in phase, the program's band outside every configured one (a reading under the program's band is the program ending, not `other`); only with at least one phase; it waits for nothing and ends at once when a configured phase starts. `other:` takes `on_delay` and `off_delay` (30 s each by default, so a compressor's 2-s spike isn't one) and `statistics`; write `other: {}` or `other:` with its settings to ask for its meters.
  - **Entities** (`<key>` the device's key, `<phase>` a phase's key or `other`):

    | Entity | What it is |
    |---|---|
    | `binary_sensor.pururu_<key>_appliance_running` | The program: on while the appliance runs (see [`appliance`](/features/appliance#entities)) |
    | `sensor.pururu_<key>_appliance_phase_current` | The running phase that started last, or `idle`. Device class `enum`. Attributes: `running` (the running phases, in the configuration's order) and `seen` (the phases of the current or last cycle, `other` included, cleared when a cycle starts) |
    | `sensor.pururu_<key>_appliance_phase_last` | The phase of the last phase cycle that ended; `enum`, kept across restarts, `unknown` until the first |
    | `binary_sensor.pururu_<key>_appliance_phase_<phase>` | On while the phase runs, named by its `name` (`other`: "Other phase"). Attributes `cycle_start`, and `cycle_end` while its `off_delay` runs |
    | `sensor.pururu_<key>_appliance_phase_<phase>_last_cycle_start`, `_end`, `_duration`, `_energy` | The phase's last cycle, as the appliance's (`_end` written last; `_energy` *with `energy`*) |
    | `sensor.pururu_<key>_appliance_phase_<phase>_cycles_total`, `_runtime_total`, `_energy_total` | Its totals, `total_increasing` (`_energy_total` added exactly, *with `energy`*) |
    | `sensor.pururu_<key>_appliance_phase_<phase>_<counter>_<period>` | One per entry of the phase's (or `other`'s) `statistics` |

    A phase's cycle entities are named after its `name` ("Gelar cycles", "Ciclos de Gelar"), `other`'s by their own ("Other phase cycles", "Ciclos de outra fase"). While `running` is disabled, every phase is off and `phase_current` is `idle`.
  - **State names**: `phase_current` and `phase_last` show a phase's key, translated for `idle`, `washing`, `heating`, `spinning`, `rinsing`, `drying`, `cooling`, `dispensing` and `other` (the table from today's `phases.mdx`, with `phase_last`'s without `idle`); any other key is shown as written.
  - **Referring to a phase**: an alert's or a reaction's `when` names `appliance_phase_current`, `appliance_phase_gelar` or `appliance_phase_gelar_cycles_total` as any entity key of the device; a phase not configured, or any phase key of an appliance without phases, is refused at the configuration (`alerts: appliance_phase_morno is not an entity key of another feature of this device`). Renaming a phase's entity in the UI is followed, as every pururu entity.

  `docs.json`: `{ "title": "Detected programs", "href": "/concepts/detected-programs" }` right before `Programs`; the Features group loses `phases` and `modes`.

- [ ] **Step 2: `docs/features/appliance.mdx`.**
  - The description and intro: "Its required `running_program` tells when it runs, and its phases what it's doing."
  - The example: the spec's washer (`running_program` with `statistics: {runtime: …, cycles: …}` and the two phases), `statistics: {idle_energy: [today, month]}` in the block.
  - Settings: `power` ("compared with `running_program`'s band"); `energy` (as today, plus "each phase's `energy_total` and `last_cycle_energy`"); `running_program` (required: a [detected program](/concepts/detected-programs): `above`/`below`, `on_delay`/`off_delay` (0 when absent), `statistics` for `runtime` and `cycles`, `phases`, `other`; no `name`); `statistics.idle_energy`. The `running.*` and the appliance's `statistics.runtime`/`statistics.cycles` properties go.
  - "When a cycle starts and ends": the diagram with `power > above` / `power ≤ above` (a `below` band reads the same way); the start is "the moment `on_delay` passed" (no more "when `running` turns on"); the rest as today; the restart bullet: "`running` restores the detector's snapshot: the cycle, its phases and when each started".
  - Entities: the phases' rows, pointing to [Detected programs](/concepts/detected-programs#entities); `runtime_<period>`/`cycles_<period>` "one per `running_program.statistics` entry".
  - "Provides" goes; a short "Phases" section instead: "`running_program`'s `phases` split each cycle into what the appliance is doing: see [Detected programs and phases](/concepts/detected-programs)."
  - The ready-made alerts and notifications sections stay (`test_presets.py` reads "## Ready-made alerts").

- [ ] **Step 3: Every other Guide page.**
  - `docs/index.mdx`: the example's `phases:` block goes; its bands become `running_program`'s phases (named, `on_delay` for `for`); the table's `sensor.pururu_laundry_washer_phase_current` row becomes `sensor.pururu_laundry_washer_appliance_phase_current` (`idle`, `heating`, `spinning` or `other`); the features list names `appliance`, `door`, `window`, `switches`, `lights`, and says an appliance's phases are part of it.
  - `docs/getting-started/first-device.mdx`: "Picking the numbers" says `above`, not "threshold"; Step 3, "the phase of the wash", writes the phases in `running_program` (`heating: {name: Aquecendo, above: 1000}`, `spinning: {name: Centrifugando, above: 50, below: 1000, on_delay: {minutes: 3}}`), explains `on_delay` for `for`, overlap (both run), `idle` and `other` instead of the defaults, and shows `sensor.pururu_laundry_washer_appliance_phase_current` and a phase's binary sensor; its later full examples follow.
  - `docs/concepts/devices-and-features.mdx`: the example without `phases:`; the features table loses `phases` and `modes`; "Features that build on each other" (`cycle_from`, provides/requires) goes, replaced by one paragraph: a feature stands alone, and what used to be `phases`/`modes` is the appliance's own `running_program` (link); "a threshold" becomes "a band of its power".
  - `docs/concepts/entity-ids.mdx`: the `phases` row goes; an `appliance` row example gains `sensor.pururu_laundry_washer_appliance_phase_heating_cycles_total`; "`phases` reads `running`" becomes "a phase's runtime reads its binary sensor".
  - `docs/concepts/statistics.mdx`: its example moves `runtime`/`cycles` into `running_program`; "Where it sits": the appliance's block (`idle_energy`), its `running_program` (`runtime`, `cycles`), each phase and `other` (`runtime`, `cycles`, `energy`), each program or reaction; the counters table's `modes` rows become `running_program` phases' (`energy` needs the appliance's `energy`); the naming example uses a phase ("Máquina de lavar Aquecendo cycles today") and `other`'s own.
  - `docs/concepts/alerts.mdx`: `phase_current` in `when`'s examples becomes `appliance_phase_current`.
  - `docs/concepts/events.mdx`: `key`'s example `mode_heating_cycles_total` becomes `appliance_phase_heating_cycles_total` (ruling 17).
  - `docs/concepts/programs.mdx`: one line at the top: these are programs pururu runs; the ones it tells from a reading are [Detected programs](/concepts/detected-programs) (D3 merges both pages).
  - `docs/features/door.mdx`: "Provides" loses `phases`/`modes`/`cycle_from`: each opening is a cycle, recorded in its last opening and totals; alerts and reactions can watch `door_open`.
  - `docs/reference/configuration.mdx`: the example as the appliance page's; "General rules"' `statistics` sentence lists the appliance's block, its `running_program`, each phase and `other`, and each program or reaction; the devices' feature list loses `phases` and `modes`.
  - `docs/reference/troubleshooting.mdx`: "The reload changed nothing": `treshold:` for `threshold:` becomes `running:` for `running_program:` ("an old key is `extra keys not allowed`"); `cycle_from` and the `phases` band causes go; added: a `running_program` with a `name`, or with neither `above` nor `below`; a phase without `name`, keyed `idle`, `other`, `current` or `last`, or whose entities another phase's would be (`phase … would create …`); `other:` without `phases`; two entities of one device with one unique ID (`device <key>: … would be two entities`); `statistics.energy needs energy` at a phase. The `follows` example: `sensor.pururu_laundry_washer_appliance_phase_current follows binary_sensor.pururu_laundry_washer_appliance_running, which is not created; not creating it`. "The cycle ends too early, or never starts": `above`, not the threshold.
  - `README.md`: "which phase it's in" stays true; nothing else names a removed key.

  ```sh
  git grep -n 'cycle_from\|/features/phases\|/features/modes\|mode_current\|threshold\|running\.on_delay\|running\.off_delay' -- docs README.md ':!docs/superpowers'
  ```

  Expected: nothing, but `docs/develop/` (Task 5).

- [ ] **Step 4: Check.**

  ```sh
  pnpm install --frozen-lockfile
  pnpm docs:check
  uv run pytest tests/test_presets.py tests/test_alert_lights.py tests/test_alert2.py tests/test_notifications.py tests/test_events.py -n 4 -q
  ```

  Expected: no broken link (the pages that linked `/features/phases` or `/features/modes` now link `/concepts/detected-programs`); the page tests pass. `uv run pytest -q`: `1281 passed`. Look at the new page with `pnpm docs:preview`: the MDX renders (no `{`/`<` outside code), the tables fit.

- [ ] **Step 5: Commit, push, review.**

  ```sh
  git add -A docs docs.json README.md
  git commit -m "docs: detected programs and phases; the appliance's running_program (refactor D2)

  A concept page for detected programs and their phases replaces the modes
  and phases feature pages. The appliance's page, the examples, the
  configuration reference and troubleshooting speak of running_program,
  above, the phases and other.

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM"
  git push
  ```

  Wait for `headRefOid`, then remove and add `claude-review`. Fix what it finds before Task 5.

---

### Task 5: The Develop pages, CLAUDE.md, coverage, the final review, ready

What contributors read says what D2 built: `Derived`, places, `Counted`, the appliance's `running_program`, no capabilities. Then coverage against `main`, the final review, and the PR ready.

**Files:**
- Modify `CLAUDE.md`, `docs/develop/{architecture,writing-a-feature,index,testing}.mdx`.

- [ ] **Step 1: CLAUDE.md** (Architecture → Features, and Tests):
  - the roles list: `Configured`, `Derived`, `Actions`, `Items`, `Counters`, `Refers`, `Presets`, `Happenings`, `Generates` (no `Provides`, `Requires`);
  - the `<capability>_from` bullet goes; a bullet in its place: "A validated block can add entity keys beyond `entity_keys` (`Derived(of)`): the appliance's phases' (`program.keys_of`), listed by `catalogue.keys` so the index knows them only when the block has phases.";
  - the `Items` bullet's example is a program's (`<slug>_<suffix>`, `{program}`), and the cycle code is what "the appliance (its running program and phases), `door`, `window` and the programs" share;
  - the **Detected programs** bullet: "(`features/cycle/program/`): the appliance's required `running_program` is one, built with `key="running"`, so its carrier is `appliance_running` and the appliance's own cycle entities follow it (D1 ruling 13)"; `schema.py` lists `keys_of`, `PHASE_COUNTERS`, `counted(at)` for `COUNTERS`; `tests/test_program_entities.py` runs on the real appliance (no test-only builder);
  - the **Aspects** bullet: an `Aspect` has `key`, `offered(builder)`, `places(builder, name)` (the `Place`s where its key sits: `path` from the block, `EACH` for each key of a map, with its `schema`, `keys`, `named`, `example`, `item` and optional `check(block, container)`), `build`, `mount_absent`; `statistics.ASPECT` meters a builder with `Counters(places)`, each a `Counted(needs, at, item, named)` (`needs` looked up in the builder's whole block); `catalogue.mount` takes the key out of each container `walk` finds for each place, validates it with the place's schema, puts it back along the path, then runs each place's check; the appliance counts at four places (its block, `running_program`, each phase, `other`);
  - `CHECKS`' generic ones (`setup/checks.py`) include `keys_distinct` (two entities of one device, one unique ID);
  - "Where the code lives": `setup/catalogue.py` holds "the builders, the aspects they mount at their places, and the index of what each device can create" (`builders()`, `aspects_of()`, `mount()`, `keys()`, `index()`, as today).

- [ ] **Step 2: The Develop pages.**
  - `docs/develop/architecture.mdx`: "Features" names `appliance` and `door` as keys, and `appliance`, `door`, `light`, `switch` as namespaces; the roles table loses `Provides`/`Requires`, gains `Derived(of)` ("entity keys its validated block adds beyond `entity_keys`: the appliance's phases"), and `Counters(places)` reads "totals it builds at each place, a `Counted(needs, at, item, named)`: `at` the path to where `statistics:` sits (`EACH` for each item), `item` what a container there is, `named` a translation prefix of its own (other's)"; the rules line says no device key has `Actions` or `Derived`. "Detected programs": the appliance's `running_program` is built on it (`build(..., key="running")`), its phases' keys come through `Derived`, its statistics through the statistics aspect at `running_program`, each phase and `other`. "Aspects": `Aspect.places` and `Place` replace `schema`/`keys`/`named`/`example`/`placed`/`check`; `walk` and `EACH`; `mount`'s two stages at paths; `keys()` per container of each place; statistics applies to `appliance` (four places), `door`, `window`, `programs`, `reactions`. "Restoring state": `running` is the carrier (its snapshot, D1's rulings); the `modes`' `current` and `phase` bullets go.
  - `docs/develop/writing-a-feature.mdx`: section 4's "On another feature" capability part (`Provides`, `Requires`, `cycle_from`, "`phases.py` is the example to copy") goes: a feature reads another's entity only through `Refers` (the next paragraph); a new paragraph, "**Entity keys the block adds.** A feature whose block decides more entity keys than `entity_keys` lists (the appliance's phases) adds `Derived(of)`…". Section 5: the `Items` example is `programs` (`sensor.pururu_<key>_program_clean_cycles_total`, `{program}`); the cycle code line names the appliance's running program and phases, `door`, `window`, the programs' statistics; "Offering statistics" shows `Counters((Counted(needs={...}),))` and a place deeper in the block (`Counted(needs, at=("running_program", "phases", EACH), item=…)`, with `program.counted(at)` as the example); the `CycleSource` paragraph names `Open`, `Runs`, the carrier and `PhaseRunning` and the contract rule "what every last cycle follows". The contract table: `test_capabilities_line_up`, `test_a_capability_is_carried_by_a_cycle_source`, `test_the_other_cycle_sources_are_pinned_too` go; `test_what_a_last_cycle_follows_is_a_cycle_source` and `test_a_derived_key_is_in_the_index` come; `test_a_device_key_neither_acts_nor_derives`, `test_mount_skips_a_place_without_a_check` renamed; the aspect rows say "each place" (`Place.named`; `{item}` all or none per place; the example reaches every place; `put` at each place's containers); `test_no_entity_key_repeats_its_namespace`'s `…_appliance_appliance`. "as `test_appliance.py` and `test_phases.py` do" becomes "`test_appliance.py` and `test_program_entities.py`".
  - `docs/develop/index.mdx`, the tree: `appliance/` is "running_program, mirrors, alerts, notifications"; `phases.py` (and `modes/`, if listed) goes.
  - `docs/develop/testing.mdx`, "Test files": `test_phases.py`'s row goes; `test_catalogue.py` comes ("`mount` and `keys` at places: `walk`, each place mounted, a phase keyed `statistics`, a place that isn't a map, a refusal's path, the keys at each place"); `test_program_entities.py` "through the appliance's `running_program`: IDs, states, the handover, restarts, reloads, names, what refers to a phase, the phases' meters"; `test_features.py` "every last cycle follows a `CycleSource`; derived keys in the index"; `test_statistics.py` names the appliance's four places; `test_appliance.py` "`running_program`, cycles…". "Running tests"' example is `tests/test_appliance.py`.

  ```sh
  git grep -n 'Provides\|Requires\|cycle_from\|phases\.py\|features/modes\|test_phases\|test_modes\|placed(\|Aspect\.named\|Aspect\.placed' -- CLAUDE.md docs ':!docs/superpowers'
  pnpm docs:check
  uv run pytest tests/test_code.py -n 0 -q
  ```

  Expected: `git grep` finds nothing; no broken link; `test_the_develop_docs_examples_import_what_exists` passes (every titled example imports what exists).

- [ ] **Step 3: Coverage per function, against `main`.**

  ```sh
  uv run pytest -q --cov=custom_components/pururu --cov-report=json:<scratchpad>/after.json
  ```

  In a `git archive 9fd851e` scratch copy (with `.hassfest`, `uv sync --locked`), run the same command into `<scratchpad>/before.json`, then delete the copy. Compare each file's `functions` by name (a moved function under its new name: `_per_item` → `_aspects_keys`, `COUNTERS` → `counted`):
  - no function misses more lines than before;
  - every function D2 adds (`keys_of`, `counted`, `_phase_item`, `_other_item`, `walk`, `_take`, `_at`, `_places` ×3, `_place`, `keys_distinct`, the appliance's `_unnamed`) misses none;
  - the total is at most 10 (Global Constraints; the prototype missed exactly those 10).

  Write the table (file, function, before, after) into the PR text.

- [ ] **Step 4: The final whole-branch review** (opus): `git diff 9fd851e...HEAD`, against this plan, the spec's Part 4 and "Decided when D starts", the rulings and the Review Focus. It checks the snapshot's diff against `main` once more (`iddiff_d2.py`: exactly the 41 gone and the 124 new, nothing of `appliance_*` moved), and that no private setup is anywhere (the fixture and examples use the spec's generic shapes). Fix every finding, minors included, each behaviour fix with a test that failed first. Commit the fixes as `pururu: D2 final review: <what> (refactor D2)` and the docs as `docs: running_program, places and Derived in the Develop pages and CLAUDE.md (refactor D2)`. Each commit ends with the two attribution lines. Push, wait for `headRefOid`, then remove and add `claude-review`.

- [ ] **Step 5: Ready.** Once Claude's review is 5/5 and its findings fixed, the checks green, Sonar at 0 issues and every review thread resolved: `gh pr ready`. The PR text holds, by then: what D2 is and where it stops (D3), the rulings in short, the manual update step (ruling 21) for PR C's "Updating to 0.2.1" guide to carry, and the coverage table. The version stays `0.2.0` (`python3 release.py check`).
