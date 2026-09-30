# Refactor D3: programs, detected and executable — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `programs:` gets its two groups (spec Part 4, D11, D22):
- **At the device**, `programs:` is `programs: executable:`: today's flat map of programs moves under `executable:`. The owner decided (2026-09-30) that they take new IDs: `<platform>.pururu_<device>_program_executable_<key>_<suffix>`, script `script.pururu_<device>_program_executable_<key>`.
- **In a feature's block**, a builder with the new role `Programs(reading, energy)` (the appliance only, today) takes `programs: detected:`, a map of detected programs: each a band of the builder's reading, with a `name`, delays, `statistics`, and `phases` with the built-in `other`, built with D1's detector. The owner decided (2026-09-30) their IDs: `binary_sensor.pururu_<device>_appliance_<key>` (on while it runs), `…_appliance_<key>_<suffix>` (its cycle entities and meters), `…_appliance_<key>_phase_<phase>…` (its phases).
- **`aspects/programs.py`** mounts `programs:` in such a block and is the device key `programs`: today's `device_keys/programs.py` moves there whole (the scripts, `plan()`, `check()`, `Runs`).

The ID snapshot changes on purpose: the executable programs' 13 entities and 1 script are renamed, and the fixture's new detected program `cotton` adds 62 entities (20 in Task 3, 42 with its phase and `other` in Task 4). Nothing else in it moves.

**Architecture:**
- **The role** `Programs(reading: str, energy: str | None = None)` (`core/roles.py`): the settings of the builder's block a detected program reads. The appliance has `Programs("power", "energy")`. It makes the programs aspect offered.
- **`aspects/programs.py`** (L2): `ASPECT` (key `programs`, one place at the block, `mount_absent=False`) validates `{detected: {<slug>: <detected program>}}`, lists the detected programs' keys (`Place.derived`) and builds them (`program.build_detected`); `PROGRAMS`, the device key, validates `{executable: {<slug>: <program>}}` and keeps today's scripts, `plan`, `check`, `Runs`. `device_keys/programs.py` goes; `DEVICE_KEYS["programs"]` is `aspects.programs.PROGRAMS`, as `alerts` is `aspects.alerts.ALERTS`.
- **Mounting nested aspects** (`setup/catalogue.py`): statistics sits inside the programs aspect's value (`programs > detected > <key>`, its phases, its `other`). `mount` takes the deepest places first and puts the shallowest first, whatever the order of `ASPECTS`; `ASPECTS` is the build order only: alerts, programs, statistics, notifications (a program's totals exist before their meters, which seed from them).
- **Keys a mounted value adds** (`core/feature.py`): `Place.derived(value)`, the local keys a container's validated aspect value adds beyond `Place.keys` (a detected program's phases vary by block, as `Derived` does for a builder's own). `catalogue.keys` lists them with `by="programs"`, so the index, the checks, `keys_distinct` and the references know them.
- **An item from its path** (`core/roles.py`, `core/feature.py`): `Counted.item` and `Place.item` take the builder's validated block and the container's path, `(block, path)`, not `(key, container)`: a detected program's phase is `<program>_phase_<phase>`, and its `other` is named with its program's name, a level above the container. `feature.at(block, path)` replaces `catalogue._at`.
- **The detector names a detected program's entities** (`features/cycle/program/`): `build(..., of=Item)` prefixes its phases' keys with the program's key (`<key>_phase_<phase>`, `<key>_phase_current`), names its carrier by the program's `name`, sends its cycles on the program's own signals, and names its fixed and `other` entities by the new `detected_*` translations with `{item}`, the program's name. `build_detected` adds the program's own cycle entities (last cycle, `cycles_total`, `runtime_total`, `energy_total`), which the appliance builds itself for `running_program` (D1 ruling 13). `counted_each(where)` gives the statistics places of a map of detected programs.
- **Executable programs** keep the namespace `program`; the group joins the item's slug (`executable_<key>`), so every entity key and the script's ID gain `executable_` and every name stays.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3, voluptuous, pytest (pytest-homeassistant-custom-component), ruff, mypy strict, uv, docs.page (pnpm).

**Spec:** `docs/superpowers/specs/2026-09-29-yaml-contract-coherence-design.md`:
- Part 4: "The model", "In the YAML", "What goes", "In the code", "Decided when D starts" 1–6, "Not in 0.2.0" (now 0.2.2);
- PRs: row D3, "Why this order", A1's ID-snapshot rule;
- "The whole contract, 0.2.0", "Compatibility", "Tests" #2 and #6.

D1's and D2's plans (`docs/superpowers/plans/2026-09-30-refactor-d1-detector.md`, `…-d2-running-program.md`) and their Rulings hold unless a ruling here says otherwise.

**Base:** `main` at f0d0aff (D2 merged, #57). `refactor/d3-programs` is cut from it. The names this plan consumes, as merged: `features.cycle.program`'s `SCHEMA`, `program_of`, `build(hass, device, program, *, key, reading, energy)`, `keys_of`, `counted(at)`, `phase_keys`, `phase_slug`, `FIXED`, `NAMED`, `SUFFIXES`, `PHASE_COUNTERS`, `Phase.item`; `core.feature`'s `Place`, `Aspect`, `walk`, `EACH`, `Path`, `Item`, `item_key`; `core.roles`' `Counted`, `Counters`, `Derived`; `setup.catalogue`'s `mount`, `_split`, `_take`, `_put`, `_at`, `_checked`, `keys`, `_aspects_keys`; `checks.keys_distinct`.

## Global Constraints

- Version stays `0.2.0` in `custom_components/pururu/manifest.json`. Only the very last PR of the refactor, C, sets `0.2.1`. `python3 release.py check` passes at every commit.
- `uv run pytest` green at every commit: ruff, ruff format, mypy strict, hassfest, the layer table, the quality scale (`tests/test_code.py`).
- Layers (`tests/test_code.py`): `aspects/programs.py` imports only `core/`, `const`, `features/cycle` and `aspects/` (the L2 row, unchanged); `features/cycle/program/` only `core/`, `const` and `features/cycle`. Two named allowances in `ALSO`: `device_keys/__init__` gains `aspects.programs` (the device key, as it has `aspects.alerts`), and `device_keys/reactions` gets `aspects.programs` (a reaction's `then` starts an executable program: its script ID). Nothing in `core/` names a concrete builder.
- `tests/fixtures/house_ids.json` changes only as the tasks say: Task 1 renames exactly the 13 `program_clean_*` entities and the script `pururu_greenhouse_program_clean` to `program_executable_clean…`; Tasks 3 and 4 only add the detected program's entities. A script checks each diff.
- Per-function coverage not lower than `main`'s (f0d0aff, 10 lines missed in all; the prototype of Tasks 1–4 missed the same 10), measured the same way on both: `uv run pytest --cov=custom_components/pururu --cov-report=json:<file>`, `main`'s in a `git archive f0d0aff` scratch copy; each function compared by name (a moved function under its new name). Every new function is fully covered.
- Commits end with exactly:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM
  ```
- Never any `git stash` (shared with other sessions), and never checkout, restore or reset the worktree's files. A RED against the old code runs in a scratch copy:
  - `git archive HEAD | tar -x -C <scratchpad>/<dir>`;
  - copy `.hassfest` and the new test in, then `uv sync --locked` there;
  - run it there, then delete the dir (`/tmp` is a small shared tmpfs).
- Every review finding fixed, minors included; ask when in doubt.
- pururu is public: made-up example names only, reusing the ones the tests use now (`clothes_washer`/Tanquinho, `water_station`/Purificador, `greenhouse`/Estufa, `cotton`/Algodão from the spec, `warming`/Aquecendo…); nothing from any private setup, in the plan, code, tests, docs, commits or PR text.
- The PR flow (no Greptile: its trial ran out; a PR merges on Claude's review at 5/5, green checks, Sonar at 0 issues and every review thread resolved):
  1. After Task 1: push, open a **draft** PR `pururu: refactor D3, programs detected and executable (0.2.0)`.
  2. Each later task: push. No review label per task.
  3. Task 6's final review: once its fixes are pushed, wait until `gh pr view <n> --json headRefOid -q .headRefOid` equals `git rev-parse HEAD`, then add `claude-review`, **once**. Fix every finding; after the fixes are pushed (and `headRefOid` matches), remove the label and add it again once to confirm. No other label.
  4. If `gh pr edit --add-label` fails with a GraphQL error: `gh api -X POST repos/thatsnotmynameio/pururu-ha/issues/<n>/labels -f 'labels[]=claude-review'`.
  5. Once Claude's review is 5/5, the checks green, Sonar at 0 issues and every thread resolved: `gh pr ready`, then merge (squash).

## Review Focus

The places most likely to bite, each with the tests that pin it:

1. **IDs.** Executable programs' entities and scripts are renamed and nothing else moves; the old ones go (entities as stale, the script as a dropped generated item) and a reaction's `then` starts the new script. Pinned: `tests/test_ids.py` with the exact diff checked by a script (Tasks 1, 3, 4), `test_programs.py` (every test on the new IDs), `test_the_update_leaves_no_old_id` (Task 1), `test_reactions.py`'s `then` tests.
2. **Mounting a nested aspect.** `statistics:` inside `programs > detected > <key>` (and its phases and `other`) is taken out before the programs aspect's schema sees it, validated per place, put back after `programs:` is, and checked against the builder's whole block (`energy`). A `programs:` that is `{}`, `null` or not a map, a detected program without a name, with a `sequence`, or with an unknown period: refused cleanly, at its path. Pinned: `test_an_aspect_inside_another_is_taken_first_and_put_back_last` (Task 2, made-up aspects), `test_where_programs_sit`, `test_its_statistics`, `test_its_energy_needs_the_appliances` (Task 3), the contract's place rules (`full`, the nested case of `test_a_builders_own_schema_refuses_an_aspects_key`).
3. **Collisions.** A detected program whose entities would be the appliance's own, its running program's, a ready-made alert's, a meter's, or another detected program's, is refused at the configuration. `Place.derived` yields pairs, not a map: a map would silently keep one of two programs' equal keys (the prototype found it). Pinned: `test_a_detected_program_may_not_take_a_key_of_the_appliance` (computed from `catalogue.keys` and the detector's suffixes) and `test_detected_programs_may_not_take_each_others_keys` (Task 3; Task 4 gives cotton phases).
4. **The detector for a named program.** Its carrier and phases send on their own signals: the running program's last cycle never counts a detected program's cycle, nor the reverse; restarts restore each carrier's snapshot. The running program's keys, names and signals don't change (`of=None`). Pinned: `test_it_runs_and_counts_apart_from_the_running_program`, `test_a_restart_keeps_a_running_detected_program` (Task 3), `test_a_detected_programs_phases_count_apart`, `test_a_restart_keeps_a_detected_programs_phase` (Task 4), and `tests/test_program_entities.py`, `test_appliance.py` unchanged.
5. **Names.** A detected program's entities carry its name (`{item}`); its phases' their names; its `other`'s and its fixed ones the new `detected_*` translations. Executable programs' names don't change. Pinned: `test_a_detected_programs_keys_are_named` (the contract, Tasks 3, 4), `test_a_detected_program_is_named_after_its_name` (Task 3), `test_a_detected_programs_phases_are_named` (Task 4), `test_statistics.py`'s `test_programs_meters` (executable programs' names, both languages).
6. **Scope.** An executable program in a feature's block, a detected one at the device, `then:` naming a detected program, a step on a detected program's carrier: refused, each with its message. Pinned: `test_the_programs_block_is_executable` (Task 1), `test_where_programs_sit`, `test_an_executable_program_takes_no_band`, `test_then_names_an_executable_program`, `test_a_step_on_a_detected_program_is_refused` (Task 3).

## Rulings

Where the spec is silent, or the owner decided, decided here:

1. **Executable programs' IDs — decided by the owner, 2026-09-30.** Entities `<platform>.pururu_<device>_program_executable_<key>_<suffix>` (today `…_program_<key>_<suffix>`), script `script.pururu_<device>_program_executable_<key>` (today `…_program_<key>`). The spec's D20 ("no ID changes but modes' and phases'") gives way to this decision.
2. **`executable` is part of the item's slug, not of the namespace.** The namespace stays `program`; each program's `Item` is `Item(slug=f"executable_{key}", name=…)`, so `Items`' keys, `Counted`'s meters, `Runs`' signals and `script_id` all gain `executable_` at once, and `Target.item` is `executable_<key>`. Why not a namespace `program_executable`: a namespace is a builder's (one per builder, `test_namespaces_are_distinct_slugs`), the group isn't one; the per-program translations are named `<namespace>_<suffix>` with the `{<namespace>}` placeholder, so a new namespace would rename five translation keys and the placeholder for no visible change. With the slug, every name shown stays (`Estufa Limpar cycles`).
3. **Detected programs' IDs — decided by the owner, 2026-09-30.** In the appliance's namespace, a detected program `<key>` creates:
   - `binary_sensor.pururu_<device>_appliance_<key>`: on while it runs (its carrier), named by its `name`;
   - `sensor.pururu_<device>_appliance_<key>_last_cycle_start`, `_end`, `_duration`, `_energy` (with `energy`), `_cycles_total`, `_runtime_total`, `_energy_total` (with `energy`);
   - `sensor.pururu_<device>_appliance_<key>_<counter>_<period>`: its meters;
   - with phases: `sensor.…_appliance_<key>_phase_current`, `…_phase_last`, and per phase (and `other`) `binary_sensor.…_appliance_<key>_phase_<phase>`, `sensor.…_appliance_<key>_phase_<phase>_<suffix>`, `…_phase_<phase>_<counter>_<period>`.
4. **Detected programs take phases** (spec "The model": `programs:` is a map of key → `Program`, a program has phases, a phase is a program without phases; "Not in 0.2.0" defers only an *executable* program's phases). With phases comes the built-in `other` (D2 ruling 10), as for `running_program`: the detector has one rule.
5. **Where each group sits** (D22, PR2): in a feature's block `programs:` takes only `detected:` (an executable program in a feature is "Not in 0.2.0": `a feature's programs are detected: executable programs are the device's`); at the device only `executable:` (a detected program reads a feature's reading, so it sits in that feature's block: `a device's programs are executable: a detected program sits in the block of the feature whose reading it reads`). Each group needs at least one program; `programs: {}` and `programs:` (null) are refused. Absent, nothing is mounted (`mount_absent=False`).
6. **A detected program needs a `name`** (it names its carrier and its entities' `{item}`); `running_program` still refuses one (D2 ruling 3). Its item schema is `program.SCHEMA` with `name` required: `program.DETECTED_SCHEMA` (`a detected program needs a name: it names its entities`).
7. **A detected program counts `runtime`, `cycles` and `energy`** (`energy` needs the builder's `energy`), and has `last_cycle_energy` and `energy_total` with it, as a phase. The spec's "In the code" lists `energy` for "a phase and `other`" and gives its reason only for `running_program` (the appliance's `energy_total` is the plug's mirror, not a program total, D2 ruling 9); a detected program's `energy_total` is its cycles' energy, a program total like a phase's. Flagged in the report as a reading of the spec.
8. **Collisions are refused by `checks.keys_distinct`, computed**, not by a hand-kept list. It already refuses two entities of one device with one unique ID over every key `catalogue.keys` lists: the builder's own, its derived keys, the ready-made alerts', every meter at every place (all counters × all periods, asked or not), and now the detected programs' (`Place.derived`). A new key in any builder or aspect is covered at once. Today's reserved keys for a detected program `<key>` in an appliance, derived from the code (the appliance with `energy`, its four ready-made alerts, `running_program` with phases `<p>` and `other`):
   - its carrier `<key>` may not be: `power`, `energy_total`, `running`, `last_cycle_start`, `last_cycle_end`, `last_cycle_duration`, `last_cycle_energy`, `cycles_total`, `runtime_total`, `idle_energy_total`; `alert_offline`, `alert_no_power`, `alert_long_cycle`, `alert_no_cycle`; `runtime_<period>`, `cycles_<period>`, `idle_energy_<period>` (each of `today`, `week`, `month`, `year`); with phases, `phase_current`, `phase_last`, `phase_<p>`, `phase_<p>_<suffix>` and `phase_<p>_<counter>_<period>` for each phase and `other`;
   - through its own entities: `idle` (`idle_energy_total`, `idle_energy_<period>`), and `phase_<p>` for each phase and `other` (already its carrier's);
   - between detected programs: `<a>_phase_<p>` beside a program `<a>` with phase `<p>` (and `<a>_phase_current`, `<a>_phase_last`, `<a>_phase_other`, beside `<a>` with phases).

   The refusal is `device <key>: <unique ID> would be two entities`, path `devices > <key>`. The test computes the reserved keys from `catalogue.keys` and `program.SUFFIXES`/`statistics.PERIODS` (Task 3); none is hard-coded in the code.
9. **`Programs(reading, energy)` makes the aspect offered and says what it reads**; `Derived` stays for `running_program`, not folded (spec: "D3 may keep for `running_program` or fold"): the running program's carrier and cycle entities are the appliance's own (`by=None`, D1 ruling 13), a detected program's are the aspect's (`by="programs"`); folding would move the appliance's keys to the aspect. The detected programs' statistics places are declared in the appliance's `Counters` (`*program.counted_each(DETECTED_AT)`), as `running_program`'s are: `Counters` stays the one list the statistics aspect meters.
10. **Nested aspects: deepest taken first, shallowest put first.** `_split` takes each (aspect, place) in order of its path's depth, deepest first, so statistics leaves `programs > detected > <key>` before the programs aspect takes `programs`; `mount` puts the validated values back shallowest first, so `programs` is back before its programs' `statistics`. Places at one depth keep `ASPECTS` order. `ASPECTS` is then only the build order: `(alerts, programs, statistics, notifications)`.
11. **`Place.derived`** (`Callable[[Any], Iterable[tuple[str, Platform]]] | None`): the local keys a container's validated value of the aspect adds, beyond `keys`, listed with `by=<aspect key>` and no item. Pairs, not a map: a key two detected programs create comes twice, so `checks.keys_distinct` sees it (a map would keep one of them silently: the prototype of Task 4 found a program keyed `cotton_cycles_total` beside `cotton` accepted that way). Only the programs aspect has one. Contract rules that read `Place.keys` read `derived` too where they must (Task 3 lists each).
12. **`Counted.item` and `Place.item` take `(block, path)`**: the builder's validated (mounted) block and the container's concrete path. `feature.at(block, path)` gives the container. Every item function changes signature, nothing else; `program.counted`'s parameter becomes `where`, which no longer shadows `at`.
13. **The detector's `of: Item | None`** (`build`, `program_of`, `Phase`): `None` is `running_program` (D2's names, unchanged); an `Item(slug=<key>, name=<name>)` is a detected program: its phases' slugs `<key>_phase_<phase>`, its fixed keys `<key>_phase_current`/`_last`, its carrier named `name` with signals of its own, its cycle entities and its `other`'s named by `detected_*` translations with `{item}`, the program's name. A configured phase's cycle entities keep `phase_<suffix>` with `{item}`, the phase's name.
14. **The new translations** (en, pt-BR, icons): `detected_<suffix>` (7, sensor), `detected_phase_current` and `detected_phase_last` (sensor enums, with `phase_current`'s and `phase_last`'s states), `detected_phase_other` (binary sensor), `detected_phase_other_<suffix>` (7), `detected_phase_other_<counter>_<period>` (12, meters): 29 keys, all with `{item}`. `program.DETECTED_NAMED` lists the 17 the detector names (the contract reads it beside `NAMED`); the 12 meters are the statistics aspect's, named through `Counted(named="detected_phase_other")` as `other`'s are (D2 ruling 10). A detected program's own meters are `item_<counter>_<period>` (B's), a phase's too.
15. **`build_detected`** (`features/cycle/program/entities.py`) builds one detected program: `build(..., of=item)` (carrier, phases), then its own last cycle, `cycles_total`, `runtime_total` and, with `energy`, `energy_total`, following its carrier. The aspect calls it per program, in the configuration's order.
16. **A reaction's `then:` names an executable program**: checked against `programs: executable:`; anything else, a detected program's key included, is `reactions: <reaction>: <key> is not an executable program of this device`.
17. **`aspects/programs.py` names the device key `PROGRAMS`** (today's `STATISTICS`), as `aspects/alerts.py` names `ALERTS`.
18. **The old IDs after the update:** the old entities are stale and removed by `remove_stale` (their history stays in the recorder under the old IDs; totals and meters start from zero); the old script is in `entry.data["scripts"]`, dropped from the file, and its registry entry goes once HA no longer runs it (the existing drop rule): nothing pururu needs to clean by hand. What refers to them (cards, automations, a `script.turn_on`) must be renamed by the user (the manual step, ruling 22).
19. **The Guide's programs page is one page** (D2 ruling 16): `docs/concepts/detected-programs.mdx` merges into `docs/concepts/programs.mdx` ("Programs": detected and executable), and goes; every link to `/concepts/detected-programs` becomes `/concepts/programs#…`.
20. **The fixture** (`tests/fixtures/house.yaml`): `greenhouse`'s `programs:` moves under `executable:` (Task 1); `clothes_washer`'s appliance gains the spec's `programs: detected: cotton: {name: Algodão, above: 1500, on_delay: {minutes: 5}}` with every statistic (Task 3: 20 new IDs), then a phase `warming: {name: Aquecendo, above: 1800}` and `other`, each with every statistic (Task 4: 42 new IDs).
21. **Sonar:** `build_unused_programs`' suppression follows the file to `custom_components/pururu/aspects/programs.py`.
22. **The manual update step goes in the PR text**, and PR C's "Updating to 0.2.1" guide carries it next to B4's and D2's (the text is final once Task 4 lands):
    1. In each device's `programs:` block, indent its programs under `executable:`.
    2. Update and restart (or reload pururu). Each program's script is now `script.pururu_<device>_program_executable_<key>` and its sensors `sensor.pururu_<device>_program_executable_<key>_…`. The old script and sensors are removed; their history stays in the recorder under the old IDs, and the new totals and meters start from zero.
    3. Everything that names an old ID — a dashboard card, an automation or script calling `script.turn_on` on `script.pururu_<device>_program_<key>`, an alert's or a reaction's `when: program_<key>_…` — names the new one (`program_executable_<key>…`). pururu's own reactions follow by themselves.
    4. Optional: a program an appliance's power alone tells apart becomes a detected program in its `appliance:` block, under `programs: detected:`.

## Tasks

1. Executable programs under `programs: executable:`; `device_keys/programs.py` moves to `aspects/programs.py`; the new IDs; reactions' `then:`; the fixture and the snapshot's rename. Draft PR.
2. The mounting machinery: `Place.derived`, `Counted.item`/`Place.item` from `(block, path)`, `feature.at`, nested aspects (deepest taken first, shallowest put first).
3. `programs: detected:` without phases: the `Programs` role, the programs aspect and `ASPECTS`' build order, `build_detected`, `counted_each`, the `detected_*` names of a program's own entities, where each group sits, collisions; the fixture's `cotton`.
4. A detected program's phases and `other`: the detector's `of`, the phases' keys, names and statistics; the fixture's `cotton` phases.
5. The Guide: one programs page, the appliance, statistics, reactions, entity IDs, configuration, troubleshooting, every example; the update step in the PR text.
6. The Develop pages, CLAUDE.md, coverage, the final review, ready.

The counts below were measured on a prototype of Tasks 1–4 in a `git archive f0d0aff` scratch copy (1295 passed there at the base).

---

### Task 1: Executable programs under `programs: executable:`, in `aspects/programs.py`, with new IDs

`device_keys/programs.py` moves to `aspects/programs.py` (a `git mv`, so the history follows), the device key's block becomes `{executable: {<key>: <program>}}`, and every executable program's slug becomes `executable_<key>` (ruling 2). Reactions start the new scripts; the fixture and the snapshot follow. No detected program yet.

**Files:**
- Modify `custom_components/pururu/const.py` (`CONF_EXECUTABLE`, `CONF_DETECTED`).
- Move `custom_components/pururu/device_keys/programs.py` → `custom_components/pururu/aspects/programs.py`, and modify it.
- Modify `custom_components/pururu/device_keys/__init__.py`, `device_keys/reactions.py`, `setup/generate.py`, `setup/schema.py`, `sonar-project.properties`.
- Modify `tests/test_code.py` (`ALSO`), `tests/test_programs.py`, `test_reactions.py`, `test_alerts.py`, `test_checks.py`, `test_lifecycle.py`, `test_resolve.py`, `test_statistics.py`, `test_features.py`, `test_generated.py`, `tests/fixtures/house.yaml`, `tests/fixtures/house_ids.json`.
- Modify the device-level `programs:` examples of `docs/concepts/{programs,reactions}.mdx`, `docs/reference/{configuration,troubleshooting}.mdx` (syntax only; Task 5 rewrites the prose).

**Interfaces** (produced):

```python
# const.py
CONF_EXECUTABLE: Final = "executable"
CONF_DETECTED: Final = "detected"

# aspects/programs.py (was device_keys/programs.py)
def slug(program_key: str) -> str                         # "executable_<key>"
def script_id(device_key: str, program_key: str) -> str   # pururu_<device>_program_executable_<key>
def executable(device: Mapping[str, Any]) -> Mapping[str, Any]   # a validated device's executable programs
PROGRAMS: Feature                                          # the device key (was STATISTICS)
COUNTED = Counted(needs={"runtime": None, "cycles": None}, at=(CONF_EXECUTABLE, EACH), item=_item)
```

- [ ] **Step 0: Branch.** The branch exists, cut from `main` at f0d0aff. In its worktree: `git log -1 --format=%h` shows `f0d0aff`, then `uv sync --locked`, then `uv run pytest -q`. Expected: `1295 passed`.

- [ ] **Step 1: The failing tests.**
  - `tests/test_programs.py`, two new tests, after `test_invalid_program_is_refused` and before `test_the_old_button_is_removed` (imports: `from pathlib import Path`, `import yaml`, and `SCRIPTS` from `helpers`):

    ```python
    @pytest.mark.parametrize(("programs", "message"), [
        pytest.param({"clean": CLEANING}, "'clean' is an invalid option for 'pururu', check: "
                     "pururu->devices->greenhouse->programs->clean", id="a flat map, as before D3"),
        pytest.param({}, "required key 'executable' not provided", id="no group"),
        pytest.param({"executable": {}}, "length of value must be at least 1", id="no program"),
        pytest.param(None, "expected a mapping for dictionary value 'pururu->devices->greenhouse->programs'",
                     id="null"),
        pytest.param({"executable": {"clean": CLEANING}, "detected": {"cotton": {"name": "Algodão", "above": 1500}}},
                     "a device's programs are executable: a detected program sits in the block of the "
                     "feature whose reading it reads", id="detected at the device"),
    ])
    async def test_the_programs_block_is_executable(
            ha: HomeAssistant, caplog: pytest.LogCaptureFixture, programs: Any, message: str) -> None:
        config = devices()
        config[KEY]["programs"] = programs
        assert not await setup(ha, config)
        assert message in caplog.text


    async def test_the_update_leaves_no_old_id(scripts: HomeAssistant) -> None:
        """0.2.0 before D3: script.pururu_<device>_program_<key> and its sensors; after it, only the program_executable_ ones.

        The old script is a generated item the entry managed: dropped from the file,
        its registry entry goes once HA no longer runs it. The old sensors are stale.
        """
        old = "pururu_greenhouse_program_clean"
        path = Path(scripts.config.path(SCRIPTS))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump({old: {"alias": "Estufa Limpar", "sequence": [{"delay": 1}]}}))
        await scripts.services.async_call("script", "reload", blocking=True)
        registry = er.async_get(scripts)
        assert registry.async_get_entity_id("script", "script", old) is not None
        entry = MockConfigEntry(domain=DOMAIN, source="import", data={"scripts": [old]})
        entry.add_to_hass(scripts)
        registry.async_get_or_create("sensor", DOMAIN, f"{old}_cycles_total", config_entry=entry,
                                     suggested_object_id=f"{old}_cycles_total")
        await fake(scripts, REAL_SPRINKLER, "off")
        assert await setup(scripts, devices())
        assert registry.async_get_entity_id("script", "script", old) is None
        assert registry.async_get_entity_id("sensor", DOMAIN, f"{old}_cycles_total") is None
        assert registry.async_get(CLEAN) is not None
        assert registry.async_get(STAT + "cycles_total") is not None
        assert entry.data["scripts"] == ["pururu_greenhouse_program_executable_clean"]
    ```

  - Every program block and ID in the tests, in the new syntax. Two rewrites, each asserted to match at least once per file (a short Python script in the scratchpad, not committed):
    - IDs, in `test_programs.py`, `test_reactions.py`, `test_lifecycle.py`: `re.sub(r"(pururu_(?:greenhouse|biblioteca|lights)_program_)(?!executable_)", r"\1executable_", text)`;
    - entity keys in strings, in `test_reactions.py`, `test_alerts.py`, `test_resolve.py`: `re.sub(r'"program_(?!executable_)', '"program_executable_', text)`.

    Then by hand, each block under `executable:`:
    - `test_programs.py`: `devices()` returns `"programs": {"executable": programs or {"clean": CLEANING}}`; the blocks of `test_programs_alone_are_not_a_feature`, `test_an_action_the_target_does_not_take_is_refused` (`start`), the generated-IDs collision test (`c`), `evening`, `test_a_program_whose_target_is_not_created_is_not_generated` (`clean: program`) and the `1:` statistics test (`device["programs"]["executable"]["1"]["statistics"]`); `test_a_run_counts_itself_before_it_sends_its_cycle`'s `Item(slug="executable_clean", …)`; `test_a_target_not_of_another_feature_is_refused`'s `a program` param `"program_executable_clean"`. The collision test becomes greenhouse's `b_program_executable_c` beside device `greenhouse_program_executable_b`'s `c`, both `script.pururu_greenhouse_program_executable_b_program_executable_c` (docstring and message);
    - `test_reactions.py`: `with_program`, `test_then_another_devices_program_is_refused`, `greenhouse()`; both refusal texts become `… is not an executable program of this device`;
    - `test_alerts.py` (`it`, `clean`), `test_checks.py` (`a program's step`: the block, and the path `["devices", "greenhouse", "programs", "executable", "clean"]`), `test_lifecycle.py` (`clean`), `test_resolve.py` (the house's `clean`; `target.item` is `"executable_clean"` in both item tests), `test_statistics.py` (`test_programs_meters`' block; `program_executable_{PROGRAM_SLUG}` in its entity IDs), `test_features.py` (`an item isn't a map`: `{"executable": {"clean": 5}}` at `[…, "programs", "executable", "clean"]`);
    - `test_generated.py`'s `Case` gains `group: str | None = None` (last field) and `items(self, items)` (`items if self.group is None else {self.group: items}`), used by `devices`, `devices_with` and the two tests that set `case.block` by hand; `SCRIPT` has `namespace="program_executable"` (the ID prefix the case builds) and `group="executable"`.
  - `tests/fixtures/house.yaml`: `greenhouse`'s `clean` indented under `programs: executable:`.

  ```sh
  uv run pytest tests/test_programs.py tests/test_reactions.py tests/test_generated.py -n 4 -q
  ```

  Expected: failures wherever a program is set up (`required key 'executable' not provided`, or the old IDs); `test_the_update_leaves_no_old_id` fails at `registry.async_get_entity_id("script", "script", old) is None` (the old code generates that very ID), and the `detected at the device` param on its message.

- [ ] **Step 2: The move and the code.**

  ```sh
  git mv custom_components/pururu/device_keys/programs.py custom_components/pururu/aspects/programs.py
  ```

  `const.py`, replacing `CONF_PROGRAMS`' comment:

  ```python
  # Programs: a device's (executable, each one a script pururu generates) and a
  # feature's (detected, each a band of its reading)
  CONF_PROGRAMS: Final = "programs"
  # The programs pururu runs: a device's, each one a script
  CONF_EXECUTABLE: Final = "executable"
  # The programs pururu tells from a reading: a feature's
  CONF_DETECTED: Final = "detected"
  ```

  `aspects/programs.py`:
  - the module docstring: "Programs: the executable ones of a device, as Home Assistant scripts. An executable program (`programs: executable:` at the device) is a method of its device: … Each run is a cycle: its statistics are sensors of its device (PROGRAMS, the device key)." (the rest as today; Task 3 adds the detected half);
  - imports `CONF_DETECTED`, `CONF_EXECUTABLE` from `..const`;
  - replace `_item`, `COUNTED` and `SCHEMA`, add `slug`, `executable` and `_executable_only`, and change `script_id`:

    ```python
    def slug(program_key: str) -> str:
        """An executable program's slug, executable_<key>: every entity key of it and its script's ID start with it."""
        return f"{CONF_EXECUTABLE}_{program_key}"


    def _item(key: str, program: Mapping[str, Any]) -> Item:
        return Item(slug=slug(key), name=program[CONF_NAME])


    # The statistics aspect meters them, `statistics:` in each executable program
    COUNTED = Counted(
        needs={"runtime": None, "cycles": None}, at=(CONF_EXECUTABLE, EACH), item=_item
    )

    # (PER_PROGRAM and PROGRAM as today)


    def _executable_only(block: Any) -> Any:
        """Refuse `detected:` at the device: a detected program reads a feature's reading, in its block."""
        if isinstance(block, dict) and CONF_DETECTED in block:
            raise vol.Invalid(
                "a device's programs are executable: a detected program sits in the "
                "block of the feature whose reading it reads",
                path=[CONF_DETECTED],
            )
        return block


    # Schemas of their own: ALLOW_EXTRA would let a key that isn't a slug through
    SCHEMA = vol.All(
        _executable_only,
        vol.Schema(
            {
                vol.Required(CONF_EXECUTABLE): vol.All(
                    vol.Schema({cv.slug: PROGRAM}), vol.Length(min=1)
                )
            }
        ),
    )


    def script_id(device_key: str, program_key: str) -> str:
        """The script's object ID, and its unique ID: pururu_<device>_program_executable_<key>."""
        return f"{ENTITY_PREFIX}_{device_key}_{qualified(NAMESPACE, slug(program_key))}"


    def executable(device: Mapping[str, Any]) -> Mapping[str, Any]:
        """A validated device's executable programs, by key; none without `programs`."""
        found: Mapping[str, Any] = device.get(CONF_PROGRAMS, {}).get(CONF_EXECUTABLE, {})
        return found
    ```
  - `_items(config)` reads `config[CONF_EXECUTABLE]`; `build` loops `for key, program in config[CONF_EXECUTABLE].items()`, with `item = _item(key, program)` and `script = inputs.get(script_id(device.key, key))` (it passed `item.slug`, which now carries `executable_`);
  - the Feature is `PROGRAMS` (ruling 17), its comment "The device key: not a device's feature; its executable programs' statistics, built as a Feature's entities", its example `{CONF_EXECUTABLE: {"clean": {"name": "Clean", "sequence": [{"delay": 1}]}}}`, its `Generates` ids `((SCRIPTS.domain, script_id(key, p)) for p in config[CONF_EXECUTABLE])`;
  - `check` and `plan` loop `executable(device)`/`executable(config)`; `check`'s path is `[CONF_DEVICES, key, CONF_PROGRAMS, CONF_EXECUTABLE, program_key]`.

  `device_keys/__init__.py`: `from ..aspects.programs import PROGRAMS`, `"programs": PROGRAMS`, `from . import reactions`; its docstring: "A device's executable programs (aspects/programs.py) and its reactions (reactions.py) are generated files; …".

  `device_keys/reactions.py`: `from ..aspects import programs` (for `from . import programs`); `CONF_PROGRAMS` leaves its imports; `_refused`'s `then`:

  ```python
      then = reaction.get("then")
      if then is not None and then not in programs.executable(devices[key]):
          return vol.Invalid(
              f"reactions: {reaction_key}: {then} is not an executable program of "
              "this device",
              path=path,
          )
  ```

  and `check`'s docstring: "`then` one of the device's executable programs".

  `setup/generate.py`, `setup/schema.py`: `programs` from `..aspects`, `reactions` from `..device_keys` (`from ..aspects import alerts, programs` in `schema.py`, as ruff orders it).

  `tests/test_code.py`'s `ALSO`:

  ```python
      # the hand-written alerts' and the executable programs' device keys
      "device_keys/__init__": ("aspects.alerts", "aspects.programs"),
      # a reaction's then starts an executable program: its script's ID
      "device_keys/reactions": ("aspects.programs",),
  ```

  `sonar-project.properties`: `build_unused_programs.resourceKey=custom_components/pururu/aspects/programs.py` (ruling 21).

- [ ] **Step 3: GREEN, then the snapshot.**

  ```sh
  uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu
  uv run pytest -q
  ```

  Expected: every test passes but `tests/test_ids.py::test_ids_are_pinned` (the renamed IDs). Then:

  ```sh
  cp tests/fixtures/house_ids.json <scratchpad>/ids_before.json
  PURURU_UPDATE_IDS=1 uv run pytest tests/test_ids.py -n 0 -q
  python3 <scratchpad>/iddiff_d3.py <scratchpad>/ids_before.json tests/fixtures/house_ids.json 1
  uv run pytest -q
  ```

  `<scratchpad>/iddiff_d3.py` (not committed; Tasks 3 and 4 run it too):

  ```python
  """D3's snapshot diff: `python3 iddiff_d3.py <old house_ids.json> <new house_ids.json> <task>`.

  Task 1: exactly the executable program's entities and script renamed, nothing else.
  Task 3: only additions, each an entity of the detected program `cotton` (no phase).
  Task 4: only additions, each a phase entity of `cotton`.
  """
  import json
  import sys

  old, new, task = json.load(open(sys.argv[1])), json.load(open(sys.argv[2])), sys.argv[3]


  def rows(snapshot: dict) -> set[tuple[str, str, str]]:
      return {("entities", *row) for row in snapshot["entities"]} | {
          ("generated", *row) for row in snapshot["generated"]}


  before, after = rows(old), rows(new)
  gone, came = before - after, after - before
  if task == "1":
      renamed = {(kind, a, b.replace("_program_clean", "_program_executable_clean")) for kind, a, b in gone}
      assert all("_program_clean" in b for _, _, b in gone), sorted(gone)
      assert renamed == came, (sorted(renamed - came), sorted(came - renamed))
      print(f"renamed {len(gone)}: {sum(k == 'entities' for k, *_ in gone)} entities, "
            f"{sum(k == 'generated' for k, *_ in gone)} generated")
  else:
      assert not gone, sorted(gone)
      prefix = "pururu_clothes_washer_appliance_cotton"
      assert all(b == prefix or b.startswith(f"{prefix}_") for _, _, b in came), sorted(came)
      phase = [b for _, _, b in came if b.startswith(f"{prefix}_phase_")]
      assert (len(phase) == len(came)) if task == "4" else not phase, sorted(came)
      print(f"added {len(came)}")
  ```

  Expected: `renamed 14: 13 entities, 1 generated`; then `1301 passed` (1295, plus the five params and the update test). `test_code.py` passes: the layer table with the two allowances, ruff, mypy.

- [ ] **Step 4: The examples.** `git grep -n -A2 'programs:' -- README.md docs ':!docs/superpowers'` lists the device-level examples in `docs/concepts/programs.mdx`, `reactions.mdx`, `docs/reference/configuration.mdx`, `troubleshooting.mdx` and the Develop pages: indent each under `executable:` now, and `script.pururu_<key>_program_<program key>`/`sensor.pururu_<key>_program_<program>_…` become `…_program_executable_…` (Task 5 rewrites the prose), so no page shows a refused block or a gone ID between tasks. Expected: `uv run pytest -q` still `1301 passed` (the page tests read their examples).

- [ ] **Step 5: Commit, push, open the draft PR.**

  ```sh
  git add -A custom_components tests docs sonar-project.properties
  git commit -m "pururu: executable programs under programs: executable:, in aspects/programs.py (refactor D3)

  The device key programs moves to aspects/programs.py (PROGRAMS). Its block
  is programs: executable:, and each program's slug is executable_<key>: its
  script is script.pururu_<device>_program_executable_<key> and its sensors
  ..._program_executable_<key>_<suffix> (the owner's decision). A detected
  program at the device is refused. Reactions start the new scripts.

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM"
  git push -u origin refactor/d3-programs
  gh pr create --draft --base main --title "pururu: refactor D3, programs detected and executable (0.2.0)" --body-file <scratchpad>/pr.md
  ```

  The PR body says what D3 is, the rulings in short, and the manual update step (ruling 22): steps 1–3 now; Task 4 adds step 4 (`gh pr edit <n> --body-file`). It ends with:

  ```
  🤖 Generated with [Claude Code](https://claude.com/claude-code)

  https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM
  ```

  No review label yet (Global Constraints).

---

### Task 2: The mounting machinery: nested aspects, derived keys, an item from its path

What Task 3 needs from `core/` and `setup/catalogue.py`, with nothing using it yet but made-up aspects in tests: an aspect's key may sit inside another aspect's value (rulings 10), a place may list keys its value adds (ruling 11), and an item is found from the whole block and a path (ruling 12). No behaviour of today's builders changes; the snapshot doesn't move.

**Files:**
- Modify `custom_components/pururu/core/feature.py` (`at`, `ItemOf`, `Place.item`, `Place.derived`), `core/roles.py` (`Counted.item`), `setup/catalogue.py` (`_split`, `mount`, `_checked`, `_at` goes, `_aspects_keys`), `aspects/statistics.py` (`_build`), `features/cycle/program/schema.py` (`_phase_item`), `aspects/programs.py` and `device_keys/reactions.py` (`_item_at`).
- Modify `tests/test_catalogue.py`, `tests/test_features.py` (`test_a_counter_is_totalled`).

**Interfaces** (produced):

```python
# core/feature.py
def at(block: Any, path: Path) -> Any                     # the container at a concrete path
type ItemOf = Callable[[Any, Path], Item]                  # (the builder's validated block, the container's path)
Place.item: ItemOf | None                                  # was Callable[[str, Any], Item] | None
Place.derived: Callable[[Any], Iterable[tuple[str, Platform]]] | None = None

# core/roles.py
Counted.item: Callable[[Any, tuple[str, ...]], Item] | None   # the same (block, path)
```

- [ ] **Step 1: The failing tests.** Append to `tests/test_catalogue.py` (imports: `from unittest.mock import patch`, `from homeassistant.const import Platform`):

  ```python
  # The appliance without statistics: the made-up aspects below replace ASPECTS
  PLAIN: dict[str, Any] = {"power": "sensor.dummy_plug_power", "running_program": {"above": 4}}


  def made_up(key: str, path: tuple[str, ...], schema: Any, **place: Any) -> Any:
      """An aspect offered by the appliance alone, at one place."""
      feature = module("core.feature")
      appliance = module("setup.catalogue").builders()["appliance"]
      at = feature.Place(path=path, schema=schema, keys={}, named=lambda each: each, example={}, **place)
      return feature.Aspect(key=key, offered=lambda builder: builder is appliance,
                            places=lambda builder, name: (at,), build=lambda *_: [], mount_absent=False)


  def test_an_aspect_inside_another_is_taken_first_and_put_back_last(ha: HomeAssistant) -> None:
      """An aspect's key inside another aspect's value (statistics in a detected program).

      The deeper place is taken first, whatever ASPECTS' order, so the outer
      schema never sees it; it is put back once the outer value is.
      """
      catalogue = module("setup.catalogue")
      outer = made_up("outer", (), vol.Schema({"each": {str: {"n": int}}}))
      inner = made_up("inner", ("outer", "each", module("core.feature").EACH), vol.Schema({"m": int}))
      block = {**PLAIN, "outer": {"each": {"a": {"n": 1, "inner": {"m": 2}}, "b": {"n": 3}}}}
      with patch.object(catalogue, "ASPECTS", (outer, inner)):
          mounted = catalogue.mount(catalogue.builders()["appliance"], "appliance", block)
      assert mounted["outer"] == {"each": {"a": {"n": 1, "inner": {"m": 2}}, "b": {"n": 3}}}


  def test_keys_lists_what_a_place_derives(ha: HomeAssistant) -> None:
      """Place.derived: the keys an aspect's validated value adds, by the aspect and no item's; none while it's absent."""
      catalogue = module("setup.catalogue")
      derives = made_up("made", (), vol.Schema({str: int}),
                        derived=lambda value: [(f"{key}_seen", Platform.SENSOR) for key in value])
      appliance = catalogue.builders()["appliance"]
      with patch.object(catalogue, "ASPECTS", (derives,)):
          rows = {key: (by, item) for _, key, _, by, item in catalogue.keys(
              {"appliance": catalogue.mount(appliance, "appliance", {**PLAIN, "made": {"cotton": 1}})})}
          absent = {key for _, key, *_ in catalogue.keys(
              {"appliance": catalogue.mount(appliance, "appliance", PLAIN)})}
      assert rows["cotton_seen"] == ("made", None)
      assert not {key for key in absent if key.endswith("_seen")}
  ```

  In `tests/test_features.py`'s `test_a_counter_is_totalled`: `for path, _container in containers:` and `item = None if counted.item is None else counted.item(block, path)`.

  ```sh
  uv run pytest tests/test_catalogue.py -n 0 -q
  ```

  Expected: `2 failed, 15 passed`: the outer schema refuses `inner` (`extra keys not allowed @ data['outer']['each']['a']['inner']`: the outer aspect was taken first, with `inner` in it); `Place` takes no `derived` (`TypeError`).

- [ ] **Step 2: `core/feature.py` and `core/roles.py`.** Before `Place`:

  ```python
  def at(block: Any, path: Path) -> Any:
      """The container at `path` in `block`: a concrete path, as walk yields it."""
      for key in path:
          block = block[key]
      return block


  # The item the container at a path of the builder's validated block is (a
  # program, a phase): the block and the container's concrete path
  type ItemOf = Callable[[Any, Path], Item]
  ```

  `Place`'s `item` and a new field after it:

  ```python
      # The item a container there is (ItemOf): its keys are the item's
      # (<slug>_<key>); None: the builder's own
      item: ItemOf | None = None
      # The local keys a container's validated value of the aspect adds beyond
      # `keys`, the builder's own and no item's (a detected program's, its
      # phases'): they vary with the value, as Derived's with a block. Pairs, not
      # a map: a key two of them add comes twice, for checks.keys_distinct
      derived: Callable[[Any], Iterable[tuple[str, Platform]]] | None = None
  ```

  (`Iterable` joins the `collections.abc` import.)

  `Counted.item` in `roles.py` (L0 `roles.py` imports `feature.py` only for typing, so the path is spelled `tuple[str, ...]`, as `Counted.at` is):

  ```python
      # The item the container at a path of the builder's validated block is
      # (feature.ItemOf: the block, the container's path): its totals and meters
      # are the item's, named with {item}; None: the builder's own
      item: Callable[[Any, tuple[str, ...]], Item] | None = None
  ```

- [ ] **Step 3: `setup/catalogue.py`.** Import `at` from `..core.feature` (and drop `Mapping`); `_at` goes, `_checked` calls `at(block, path)`. `_split`:

  ```python
  def _split(
      builder: Feature, name: str, aspects: tuple[Aspect, ...], value: Any
  ) -> tuple[Any, Taken]:
      """The block without the aspects' keys, and their values by where each sat (Aspect.places).

      The deepest places first: an aspect's key inside another aspect's value
      (statistics in a detected program, in `programs:`) leaves it before that
      value is taken whole. Places at one depth keep ASPECTS' order.
      """
      rest = value
      taken: Taken = {}
      placed = [
          (aspect, place) for aspect in aspects for place in aspect.places(builder, name)
      ]
      for aspect, place in sorted(placed, key=lambda pair: -len(pair[1].path)):
          rest = _take(rest, place.path, aspect, place, taken)
      return rest, taken
  ```

  `mount`'s put loop:

  ```python
      # The shallowest first: `programs:` is back before its programs' `statistics:`
      for (path, key), (_, each) in sorted(
          mounted.items(), key=lambda row: len(row[0][0])
      ):
          block = _put(block, path, key, each)
  ```

  `_aspects_keys`: its docstring gains "Its fixed keys (Place.keys) at every container, as an item's where the container is one; then what the aspect's value there adds (Place.derived)."; the item is `place.item(block, path)`; after the fixed keys' `yield from`:

  ```python
                  if place.derived is not None and aspect.key in container:
                      yield from (
                          (name, entity_key, platform, aspect.key, None)
                          for entity_key, platform in place.derived(
                              container[aspect.key]
                          )
                      )
  ```

- [ ] **Step 4: Every item function takes `(block, path)`.**
  - `aspects/statistics.py`'s `_build`: `counted.item(block, path)`.
  - `features/cycle/program/schema.py` (imports `at`):

    ```python
    def _phase_item(block: Any, path: Path) -> Item:
        """A configured phase's item, at `path` of the builder's block: phase_<key>, named by its name."""
        return Item(slug=phase_slug(path[-1]), name=at(block, path)["name"])
    ```

    (`_other_item(*_)` already ignores its arguments.) `counted(at)`'s parameter becomes `where` (`counted(where: Path)`, `at=where`, `(*where, "phases", EACH)`, `(*where, OTHER)`): the module imports the function `at` now, and a parameter of that name would shadow it. Callers pass it positionally.
  - `aspects/programs.py` and `device_keys/reactions.py` (each imports `Path`, `at`) keep their `_item(key, config)` for `Items` and add, for their `Counted`:

    ```python
    def _item_at(block: Any, path: Path) -> Item:
        """The executable program at `path` of the device key's block."""
        return _item(path[-1], at(block, path))
    ```

    (reactions: "The reaction at `path` …"); `COUNTED`/`COUNTERS` take `item=_item_at`.

- [ ] **Step 5: GREEN.**

  ```sh
  uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu
  uv run pytest tests/test_catalogue.py tests/test_features.py tests/test_statistics.py -n 4 -q
  uv run pytest -q
  ```

  Expected: all pass; then `1303 passed` (1301 plus the two). `test_ids.py` unchanged.

- [ ] **Step 6: Commit, push.**

  ```sh
  git add -A custom_components tests
  git commit -m "pururu: nested aspects, derived place keys, an item from its path (refactor D3)

  mount takes the deepest places first and puts the shallowest back first, so
  an aspect's key can sit inside another aspect's value (statistics in a
  detected program). Place.derived lists the keys an aspect's value adds.
  Counted.item and Place.item take the builder's block and the container's
  path, feature.at finds it.

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM"
  git push
  ```

---

### Task 3: `programs: detected:` in the appliance's block (no phases yet)

The `Programs` role, the programs aspect, and a detected program's carrier and cycle entities (rulings 3, 5–11, 13–17). Phases on a detected program come in Task 4: until then `program.DETECTED_SCHEMA` takes them (it is `program.SCHEMA`), but `detected_keys` doesn't list them and the fixture has none; Task 4's first test is that they build under the program's prefix.

**Files:**
- Modify `custom_components/pururu/core/roles.py` (`Programs`), `features/cycle/program/schema.py`, `features/cycle/program/entities.py`, `features/cycle/program/__init__.py`, `aspects/programs.py` (the aspect), `aspects/__init__.py` (`ASPECTS`), `features/appliance/__init__.py`, `translations/en.json`, `translations/pt-BR.json`, `icons.json`.
- Create `tests/test_detected_programs.py`.
- Modify `tests/test_features.py`, `tests/fixtures/house.yaml`, `tests/fixtures/house_ids.json`.

**Interfaces** (produced):

```python
# core/roles.py
@dataclass(frozen=True)
class Programs:
    reading: str
    energy: str | None = None

# features/cycle/program (schema.py, entities.py; exported by __init__)
DETECTED_AT: Path = (CONF_PROGRAMS, CONF_DETECTED, EACH)
DETECTED = "detected"                                     # the translations' prefix
DETECTED_NAMED: dict[str, Platform]                      # detected_<suffix> (Task 4 adds the phases')
DETECTED_SCHEMA                                          # SCHEMA with a name required
def counted_each(where: Path) -> tuple[Counted, ...]
def detected_keys(key: str, config: Mapping[str, Any]) -> dict[str, Platform]
def build_detected(hass, device, key, config, *, reading, energy) -> list[PururuEntity]
build(hass, device, program, *, key, reading, energy, of: Item | None = None)   # of: new
Carrier(device, key, *, program, reading, energy, of: Item | None = None)       # of: new

# aspects/programs.py
DETECTED                                                  # the schema of `programs:` in a feature's block
ASPECT: Aspect                                            # key "programs", mount_absent=False
```

- [ ] **Step 1: The failing tests.** Create `tests/test_detected_programs.py`:

  ```python
  """A feature's detected programs, `programs: detected:` in an appliance's block (aspects/programs.py).

  Each is a band of the appliance's power, as its running program is: a made-up
  washer whose cotton wash draws over 1500 W. Its entity IDs are
  <platform>.pururu_<device>_appliance_<key>[_<suffix>].
  """

  from typing import Any

  from homeassistant.const import Platform
  from homeassistant.core import HomeAssistant, State
  import pytest
  import voluptuous as vol

  from helpers import DOMAIN, fake, held, module, restart, setup, snapshot, tick

  KEY = "clothes_washer"
  POWER = "sensor.washer_plug_power"
  ENERGY = "sensor.washer_plug_energy"
  PREFIX = f"pururu_{KEY}_appliance"
  RUNNING = f"binary_sensor.{PREFIX}_running"
  COTTON = f"binary_sensor.{PREFIX}_cotton"
  RUNNING_PROGRAM: dict[str, Any] = {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}}
  DETECTED: dict[str, Any] = {"cotton": {"name": "Algodão", "above": 1500, "on_delay": {"minutes": 5}}}
  LAST_CYCLE = ("last_cycle_start", "last_cycle_end", "last_cycle_duration", "last_cycle_energy")
  SUFFIXES = (*LAST_CYCLE, "cycles_total", "runtime_total", "energy_total")


  def appliance(**block: Any) -> dict[str, Any]:
      """The washer's appliance block with its detected programs, `block` over it."""
      return {"power": POWER, "energy": ENERGY, "running_program": RUNNING_PROGRAM,
              "programs": {"detected": DETECTED}, **block}


  def devices(**block: Any) -> dict[str, Any]:
      return {KEY: {"name": "Tanquinho", "appliance": appliance(**block)}}


  def sensor(entity_key: str) -> str:
      return f"sensor.{PREFIX}_{entity_key}"


  def state(hass: HomeAssistant, entity_id: str) -> str:
      found = hass.states.get(entity_id)
      assert found is not None, entity_id
      return found.state


  async def watts(hass: HomeAssistant, value: float) -> None:
      await fake(hass, POWER, str(value))


  @pytest.fixture
  async def washer(ha: HomeAssistant, freezer: Any) -> HomeAssistant:
      """Idle at 1 W, long enough to count as not running."""
      await fake(ha, ENERGY, "100")
      assert await setup(ha, devices())
      await watts(ha, 1)
      await tick(ha, freezer, 125)
      return ha


  # --- what it creates ----------------------------------------------------------------


  async def test_its_entities_and_their_ids(washer: HomeAssistant) -> None:
      """Its carrier and cycle entities, in the appliance's namespace, beside the appliance's own."""
      found = held(washer, KEY)
      assert COTTON in found
      assert {sensor(f"cotton_{suffix}") for suffix in SUFFIXES} <= found
      assert not {entity_id for entity_id in found if "_cotton_phase" in entity_id}


  async def test_without_energy_no_energy_entity(ha: HomeAssistant) -> None:
      block = {key: value for key, value in appliance().items() if key != "energy"}
      assert await setup(ha, {KEY: {"name": "Tanquinho", "appliance": block}})
      found = held(ha, KEY)
      assert sensor("cotton_cycles_total") in found
      assert not {sensor("cotton_energy_total"), sensor("cotton_last_cycle_energy")} & found


  async def test_it_runs_and_counts_apart_from_the_running_program(
          washer: HomeAssistant, freezer: Any) -> None:
      """A cotton wash is the appliance running and cotton running; a wash under 1500 W is only the appliance's."""
      await watts(washer, 2000)
      await tick(washer, freezer, 60)
      assert (state(washer, RUNNING), state(washer, COTTON)) == ("on", "off")
      await tick(washer, freezer, 240)
      assert state(washer, COTTON) == "on"
      await tick(washer, freezer, 240)
      await fake(washer, ENERGY, "101.5")
      await watts(washer, 1)
      await tick(washer, freezer, 125)
      assert (state(washer, RUNNING), state(washer, COTTON)) == ("off", "off")
      assert state(washer, sensor("cycles_total")) == "1"
      assert state(washer, sensor("cotton_cycles_total")) == "1"
      assert float(state(washer, sensor("cotton_last_cycle_duration"))) == 4.0
      assert float(state(washer, sensor("cotton_energy_total"))) == pytest.approx(1.5)
      await watts(washer, 500)
      await tick(washer, freezer, 600)
      await watts(washer, 1)
      await tick(washer, freezer, 125)
      assert state(washer, sensor("cycles_total")) == "2"
      assert state(washer, sensor("cotton_cycles_total")) == "1"


  async def test_a_restart_keeps_a_running_detected_program(ha: HomeAssistant, freezer: Any) -> None:
      """Its carrier restores its own snapshot, as the running program's does."""
      since = "2026-09-16T16:50:00+00:00"
      await restart(ha, devices(), (State(RUNNING, "on"), snapshot(since)),
                    (State(COTTON, "on"), snapshot(since)))
      await watts(ha, 2000)
      await tick(ha, freezer, 1)
      assert state(ha, COTTON) == "on"
      assert ha.states.get(COTTON).attributes["cycle_start"].isoformat() == since


  @pytest.mark.parametrize(("language", "names"), [
      pytest.param("en", {COTTON: "Tanquinho Algodão", sensor("cotton_cycles_total"): "Tanquinho Algodão cycles",
                          sensor("cotton_last_cycle_start"): "Tanquinho Algodão last cycle start"}, id="en"),
      pytest.param("pt-BR", {COTTON: "Tanquinho Algodão", sensor("cotton_cycles_total"): "Tanquinho Ciclos de Algodão",
                             sensor("cotton_last_cycle_start"): "Tanquinho Início do último ciclo de Algodão"},
                   id="pt-BR"),
  ])
  async def test_a_detected_program_is_named_after_its_name(
          ha: HomeAssistant, language: str, names: dict[str, str]) -> None:
      ha.config.language = language
      assert await setup(ha, devices())
      for entity_id, name in names.items():
          assert ha.states.get(entity_id).attributes["friendly_name"] == name


  async def test_its_statistics(ha: HomeAssistant) -> None:
      """`statistics:` in the detected program: its runtime, cycles and energy per period."""
      cotton = {**DETECTED["cotton"], "statistics": {"cycles": ["today"], "energy": ["month"]}}
      assert await setup(ha, devices(programs={"detected": {"cotton": cotton}}))
      assert {sensor("cotton_cycles_today"), sensor("cotton_energy_month")} <= held(ha, KEY)


  # --- where it sits, and what it can't be ------------------------------------------


  @pytest.mark.parametrize(("programs", "message"), [
      pytest.param({"executable": {"clean": {"name": "Limpar", "sequence": [{"delay": 1}]}}},
                   "a feature's programs are detected: executable programs are the device's",
                   id="an executable program in a feature"),
      pytest.param({}, "a feature's programs needs detected", id="empty"),
      pytest.param({"detected": {}}, "length of value must be at least 1", id="no program"),
      pytest.param({"detected": {"cotton": {"above": 1500}}},
                   "a detected program needs a name: it names its entities", id="no name"),
      pytest.param({"detected": {"cotton": {"name": "Algodão"}}}, "a program needs above, below or both",
                   id="no band"),
      pytest.param({"detected": {"cotton": {"name": "Algodão", "above": 1500, "sequence": [{"delay": 1}]}}},
                   "'sequence' is an invalid option", id="a sequence"),
      pytest.param({"detected": {"cotton": {"name": "Algodão", "above": 1500, "statistics": {"cycles": ["daily"]}}}},
                   "value must be one of", id="an unknown period"),
  ])
  async def test_where_programs_sit(
          ha: HomeAssistant, caplog: pytest.LogCaptureFixture, programs: Any, message: str) -> None:
      assert not await setup(ha, devices(programs=programs))
      assert message in caplog.text


  async def test_an_executable_program_takes_no_band(ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
      """A device's program is executable: `above` is a detected program's."""
      clean = {"name": "Limpar", "above": 1500, "sequence": [{"delay": 1}]}
      config = devices()
      config[KEY]["programs"] = {"executable": {"clean": clean}}
      assert not await setup(ha, config)
      assert "'above' is an invalid option" in caplog.text


  async def test_its_energy_needs_the_appliances(ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
      cotton = {**DETECTED["cotton"], "statistics": {"energy": ["today"]}}
      block = {key: value for key, value in appliance(programs={"detected": {"cotton": cotton}}).items()
               if key != "energy"}
      assert not await setup(ha, {KEY: {"name": "Tanquinho", "appliance": block}})
      assert "statistics.energy needs energy" in caplog.text


  async def test_then_names_an_executable_program(ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
      """A detected program can't be started: a reaction's then names an executable one."""
      config = devices()
      config[KEY]["reactions"] = {"it": {"name": "X", "at": "08:00", "then": "cotton"}}
      assert not await setup(ha, config)
      assert "reactions: it: cotton is not an executable program of this device" in caplog.text


  async def test_a_step_on_a_detected_program_is_refused(ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
      config = devices()
      config[KEY]["programs"] = {"executable": {"start": {"name": "X", "sequence": [{"turn_on": "appliance_cotton"}]}}}
      assert not await setup(ha, config)
      assert "programs: appliance_cotton does not take turn_on" in caplog.text


  async def test_an_alert_and_a_reaction_can_watch_it(ha: HomeAssistant) -> None:
      config = devices()
      config[KEY]["alerts"] = {"long": {"name": "Longo", "when": "appliance_cotton", "is": "on", "for": {"hours": 3}}}
      config[KEY]["reactions"] = {"done": {"name": "Pronto", "when": "appliance_cotton", "from": "on", "to": "off"}}
      assert await setup(ha, config)
      assert ha.states.get(f"binary_sensor.pururu_{KEY}_alert_long") is not None


  def reserved(block: dict[str, Any]) -> set[str]:
      """Every key a detected program can't take in this appliance's block, computed.

      Each key the block lists (catalogue.keys: the appliance's own, its derived,
      its ready-made alerts', every meter), as the program's carrier; and each
      key that is the program's key plus one of its suffixes (its cycle
      entities', its meters').
      """
      catalogue = module("setup.catalogue")
      statistics = module("aspects.statistics")
      program = module("features.cycle.program")
      appliance_ = catalogue.builders()["appliance"]
      listed = {key for _, key, *_ in catalogue.keys({"appliance": catalogue.mount(appliance_, "appliance", block)})}
      suffixes = [*program.SUFFIXES,
                  *(f"{counter}_{period}" for counter in program.PHASE_COUNTERS for period in statistics.PERIODS)]
      return listed | {key.removesuffix(f"_{suffix}") for key in listed for suffix in suffixes
                       if key.endswith(f"_{suffix}") and key != suffix}


  # The appliance with everything that adds keys: energy, a phase and other
  FULL = {"power": POWER, "energy": ENERGY, "running_program": {
      **RUNNING_PROGRAM, "phases": {"warming": {"name": "Aquecendo", "above": 1000}}, "other": {}}}


  def test_the_reserved_keys(ha: HomeAssistant) -> None:
      """What reserved() computes, for the record: the appliance's own and its running program's keys, and idle."""
      keys = reserved(FULL)
      assert {"power", "running", "cycles_total", "idle_energy_total", "idle", "alert_offline",
              "runtime_today", "phase_current", "phase_warming", "phase_other_cycles_total"} <= keys
      assert "cotton" not in keys


  async def test_a_detected_program_may_not_take_a_key_of_the_appliance(ha: HomeAssistant) -> None:
      """Each reserved key, as a detected program's, is refused at the configuration (checks.keys_distinct); cotton passes."""
      schema = module("setup.schema").CONFIG_SCHEMA
      for key in sorted(reserved(FULL)):
          detected = {key: {"name": "X", "above": 1500}}
          house = {"devices": {KEY: {"name": "Tanquinho", "appliance": {**FULL, "programs": {"detected": detected}}}}}
          with pytest.raises(vol.Invalid, match="would be two entities"):
              schema({DOMAIN: house})
      house = {"devices": {KEY: {"name": "Tanquinho", "appliance": {**FULL, "programs": {"detected": DETECTED}}}}}
      schema({DOMAIN: house})


  async def test_detected_programs_may_not_take_each_others_keys(ha: HomeAssistant) -> None:
      """Each key cotton creates, as another detected program's key, is refused (Place.derived's pairs)."""
      schema = module("setup.schema").CONFIG_SCHEMA
      program = module("features.cycle.program")
      cotton = DETECTED["cotton"]
      for key in sorted(set(program.detected_keys("cotton", cotton)) - {"cotton"}):
          detected = {"cotton": cotton, key: {"name": "X", "above": 1500}}
          house = {"devices": {KEY: {"name": "Tanquinho", "appliance": appliance(programs={"detected": detected})}}}
          with pytest.raises(vol.Invalid, match="would be two entities"):
              schema({DOMAIN: house})


  def test_its_keys_are_in_the_index(ha: HomeAssistant) -> None:
      """By the programs aspect, in the appliance's namespace."""
      catalogue = module("setup.catalogue")
      appliance_ = catalogue.builders()["appliance"]
      rows = {key: (platform, by) for _, key, platform, by, _ in catalogue.keys(
          {"appliance": catalogue.mount(appliance_, "appliance", appliance())})}
      assert rows["cotton"] == (Platform.BINARY_SENSOR, "programs")
      assert rows["cotton_cycles_total"] == (Platform.SENSOR, "programs")
      assert rows["cotton_cycles_today"] == (Platform.SENSOR, "statistics")
  ```

  `reserved(FULL)` is 69 keys today (ruling 8's list); the test names none of them in the code, and a key a builder or aspect adds later is covered by it without a change.

  In `tests/test_features.py` (the contract; rulings 9–11):
  - a helper after `with_examples`:

    ```python
    def full(name: str, feature: Any) -> Any:
        """The builder's example with every offered aspect's example at each of its places.

        The shallowest places first: `programs:` is there before its programs'
        `statistics:`, as mount puts them back. It reaches every place, those
        inside another aspect's value too.
        """
        placed = sorted(((aspect, place) for aspect in module("setup.catalogue").aspects_of(feature)
                         for place in aspect.places(feature, name)), key=lambda pair: len(pair[1].path))
        block = dict(feature.example)
        for aspect, place in placed:
            block = put(block, place.path, aspect.key, place.example)
        return block
    ```
  - `test_every_translated_entity_key_is_created`: `created |= {…for key, platform in {**program.NAMED, **program.DETECTED_NAMED}.items()}`;
  - a new rule after `test_the_detectors_keys_are_named`:

    ```python
    def test_a_detected_programs_keys_are_named(ha: HomeAssistant) -> None:
        """Each key a detected program is named by, in both languages and with an icon, all with {item}: its name."""
        program = module("features.cycle.program")
        en, pt, icons = load("translations/en.json"), load("translations/pt-BR.json"), load("icons.json")
        assert program.DETECTED_NAMED
        for key, platform in program.DETECTED_NAMED.items():
            for translations in (en, pt):
                assert "{item}" in translations["entity"][platform][key]["name"], key
            assert icons["entity"][platform][key]["default"].startswith("mdi:"), key
    ```
  - `test_what_a_last_cycle_follows_is_a_cycle_source` builds the builder **and its aspects** from `mount(feature, name, full(name, feature))` (`aspect.build(ha, device, feature, block, load("translations/en.json")["common"])` for each of `catalogue.aspects_of(feature)`), its docstring names "a detected program", and `following["appliance"] == {"running", "phase_warming", "phase_other", "cotton"}`;
  - `test_an_offered_aspect_validates_and_builds`: every place is reached by `walk(full(name, feature), place.path)`; the block is `catalogue.mount(feature, name, full(name, feature))`; `listed` (the keys `catalogue.keys` gives `by == aspect.key`) comes first, and `assert bool(built) == bool(listed), name` replaces the `aspect_keys` comparison (a derived key is listed, not in `Place.keys`); docstring: "An aspect builds something exactly when it lists a key there, fixed or derived (ready-made notifications: none).";
  - `test_a_builders_own_schema_refuses_an_aspects_key`: a place the builder's own example reaches is checked as today; a place inside another aspect's value is that aspect's to refuse:

    ```python
        walk = module("core.feature").walk
        for aspect, name, feature in offered(features):
            valid = dict(feature.example)
            feature.schema(valid)
            for place in aspect.places(feature, name):
                if list(walk(valid, place.path)):
                    with pytest.raises(vol.Invalid):
                        feature.schema(put(valid, place.path, aspect.key, place.example))
                    continue
                holders = [(other, at) for other, _, each in offered({name: feature}) if each is feature
                           for at in other.places(feature, name)
                           if place.path[:len(at.path) + 1] == (*at.path, other.key)]
                assert holders, (aspect.key, name, place.path)
                for other, at in holders:
                    inner = place.path[len(at.path) + 1:]
                    assert list(walk(at.example, inner)), (aspect.key, name, place.path)
                    with pytest.raises(vol.Invalid):
                        at.schema(put(at.example, inner, aspect.key, place.example))
    ```

    (docstring: "A place inside another aspect's value (statistics in a detected program) is that aspect's to refuse: its schema refuses the key where its own example reaches it.");
  - `test_the_aspects_each_builder_offers`: the appliance's set gains `"programs"`; `test_the_aspects_in_build_order`: `["alerts", "programs", "statistics", "notifications"]`, docstring "…its detected programs, then its meters (after the totals they meter)…"; `test_an_absent_aspect_key`: `left_out == {"alerts", "notifications", "programs"}`;
  - `test_a_counter_is_totalled` mounts `full(name, feature)`, and `own` is every key `by != "statistics"` (the builder's, or an aspect's building it: a detected program's totals are the programs aspect's); docstring says so;
  - `test_a_counter_without_its_setting_is_refused`: `needing` gains `("appliance", ("programs", "detected", "*"))`, and `example` starts from `full(name, feature)`;
  - a new rule after `test_a_counter_is_totalled`:

    ```python
    def test_a_programs_builder_counts_its_detected_programs(features: dict[str, Any]) -> None:
        """A builder taking detected programs (Programs) counts them where they sit, program.counted_each(DETECTED_AT), and reads settings its schema has."""
        program = module("features.cycle.program")
        taking = [name for name, feature in features.items() if role(feature, "Programs")]
        assert taking == ["appliance"]
        for name in taking:
            feature = features[name]
            places = role(feature, "Counters").places
            assert all(each in places for each in program.counted_each(program.DETECTED_AT)), name
            programs = role(feature, "Programs")
            settings = schema_keys(feature.schema)
            assert programs.reading in settings, name
            assert programs.energy is None or programs.energy in settings, name
    ```

  ```sh
  uv run pytest tests/test_detected_programs.py tests/test_features.py -n 4 -q
  ```

  Expected: `test_detected_programs.py` fails (the prototype: 19 failed, 2 errors in the `washer` fixture, 2 passed): every configuration with `programs:` in the appliance is refused (`'programs' is an invalid option for 'pururu', check: pururu->devices->clothes_washer->appliance->programs`), so each message test finds that one instead. Only `test_the_reserved_keys` (it reads what exists) and `test_an_executable_program_takes_no_band` (Task 1's schema) pass already. The contract's new and changed rules fail (`DETECTED_NAMED`, `Programs` missing; the aspects' sets).

- [ ] **Step 2: The role and the detected program's schema, keys and places.** `core/roles.py`, before `Actions`, and in `Role`'s union after `Derived`:

  ```python
  @dataclass(frozen=True)
  class Programs:
      """It takes detected programs, `programs: detected:` in its block: each a band of the setting `reading`.

      `energy` is the setting giving each cycle's kWh, None: none. The programs
      aspect (aspects/programs.py) mounts `programs:`, lists their keys and
      builds them.
      """

      reading: str
      energy: str | None = None
  ```

  `features/cycle/program/schema.py` (imports `CONF_DETECTED`, `CONF_PROGRAMS` from `....const`); after `NAMED`:

  ```python
  # Where a feature's detected programs sit in its block: `programs: detected:`,
  # the programs aspect's key (aspects/programs.py)
  DETECTED_AT: Path = (CONF_PROGRAMS, CONF_DETECTED, EACH)
  # A detected program's translations, once for every builder, all with {item},
  # its name: detected_<suffix> for its cycle entities
  DETECTED = "detected"
  DETECTED_NAMED: dict[str, Platform] = {
      f"{DETECTED}_{suffix}": platform for suffix, platform in SUFFIXES.items()
  }
  ```

  before `phase_keys`:

  ```python
  def _detected_item(block: Any, path: Path) -> Item:
      """The detected program at `path` of the builder's block: its key, named by its name."""
      return Item(slug=path[-1], name=at(block, path)["name"])


  def counted_each(where: Path) -> tuple[Counted, ...]:
      """Where each detected program of the map at `where` counts: its runtime, cycles and energy, as its item's.

      Unlike running_program's (the builder's own totals), a detected program's
      totals are its own: <key>_runtime_total, <key>_cycles_total,
      <key>_energy_total (energy needs the builder's `energy`, ruling 7).
      """
      return (Counted(needs=PHASE_COUNTERS, at=where, item=_detected_item),)


  def detected_keys(key: str, config: Mapping[str, Any]) -> dict[str, Platform]:
      """Every entity key detected program `key` can create: its carrier, then its cycle entities."""
      return {
          key: Platform.BINARY_SENSOR,
          **{f"{key}_{suffix}": platform for suffix, platform in SUFFIXES.items()},
      }
  ```

  before `SCHEMA`, and after it:

  ```python
  def _named(block: Any) -> Any:
      """Refuse a detected program without a name: it names its entities."""
      if isinstance(block, dict) and "name" not in block:
          raise vol.Invalid("a detected program needs a name: it names its entities")
      return block

  # (SCHEMA as today)

  # A detected program of `programs: detected:`: a program with a name
  DETECTED_SCHEMA = vol.All(_named, SCHEMA)
  ```

  `features/cycle/program/__init__.py` exports `DETECTED_AT`, `DETECTED_NAMED`, `DETECTED_SCHEMA`, `build_detected`, `counted_each`, `detected_keys`; its docstring's last sentence: "A builder reading a sensor calls `build` (the appliance's `running_program`), or `build_detected` for a detected program of `programs: detected:` (the programs aspect)."

- [ ] **Step 3: The carrier of a named program, and `build_detected`.** `features/cycle/program/entities.py` (imports `Item`; `DETECTED`, `program_of` from `.schema`). `Carrier.__init__` takes `of: Item | None = None` last:

  ```python
          """`program` read from `reading`, as `key` of `device`; `energy` gives each cycle's kWh.

          `of`: a detected program's item, naming the carrier and its signals;
          None: the builder's running program, named by `key`'s translation.
          """
          self._identify(
              device, Platform.BINARY_SENSOR, key, None if of is None else of.name
          )
          self._cycle_signals(device, of)
  ```

  (A detected program's cycles go on `<key>`'s own signals: the appliance's last cycle and totals, on the builder's signals, never see them, and the reverse.) `build` takes `of: Item | None = None` last and passes it to `Carrier`. After `build`:

  ```python
  def build_detected(
      hass: HomeAssistant,
      device: Device,
      key: str,
      config: Mapping[str, Any],
      *,
      reading: str,
      energy: str | None,
  ) -> list[PururuEntity]:
      """Detected program `key` of a builder's `programs: detected:`: its carrier and phases, then its own cycle entities.

      Its carrier is `key`, named by the program's name; its last cycle and
      totals are its item's (<key>_<suffix>), named detected_<suffix> with {item}.
      """
      of = Item(slug=key, name=config["name"])
      entities = build(
          hass, device, program_of(config), key=key, reading=reading, energy=energy, of=of
      )
      for description in LAST_CYCLE:
          if energy is not None or description.key != "last_cycle_energy":
              entities.append(
                  LastCycleValue(
                      device,
                      description,
                      source=key,
                      item=of,
                      translation=f"{DETECTED}_{description.key}",
                  )
              )
      entities.append(
          CyclesTotal(device, source=key, item=of, translation=f"{DETECTED}_cycles_total")
      )
      entities.append(
          RuntimeTotal(
              device,
              device.current_entity_id(hass, Platform.BINARY_SENSOR, key),
              STATE_ON,
              source=key,
              item=of,
              translation=f"{DETECTED}_runtime_total",
          )
      )
      if energy is not None:
          entities.append(
              EnergyTotal(
                  device, source=key, item=of, translation=f"{DETECTED}_energy_total"
              )
          )
      return entities
  ```

- [ ] **Step 4: The aspect.** `aspects/programs.py`:
  - the module docstring's first lines: "Programs: a feature's detected ones (ASPECT), and a device's executable ones, as Home Assistant scripts. A detected program (`programs: detected:` in the block of a builder with the Programs role) is a band of the builder's reading, built with the detector (features/cycle/program): ASPECT mounts `programs:`, lists each one's keys and builds it. An executable program …";
  - imports: `from functools import partial`; `Aspect`, `Place` from `..core.feature`; `Programs` from `..core.roles`; `from ..features.cycle.program import DETECTED_SCHEMA, build_detected, detected_keys` (named imports: a module-level `program` would be shadowed by the many `program` loop variables of the executable half, F402);
  - at the end:

    ```python
    # --- detected programs: the aspect ---------------------------------------------


    def _detected_only(block: Any) -> Any:
        """Refuse `executable:` in a feature's block: an executable program is its device's."""
        if isinstance(block, dict) and CONF_EXECUTABLE in block:
            raise vol.Invalid(
                "a feature's programs are detected: executable programs are the device's",
                path=[CONF_EXECUTABLE],
            )
        return block


    # `programs:` in a feature's block; schemas of their own, as the device key's.
    # Its only key is `detected`, so an empty block is refused where it is
    DETECTED = vol.All(
        _detected_only,
        vol.Schema(
            {
                vol.Optional(CONF_DETECTED): vol.All(
                    vol.Schema({cv.slug: DETECTED_SCHEMA}), vol.Length(min=1)
                )
            }
        ),
        vol.Length(min=1, msg=f"a feature's {CONF_PROGRAMS} needs {CONF_DETECTED}"),
    )


    def _derived(value: Mapping[str, Any]) -> Iterator[tuple[str, Platform]]:
        """Every entity key the detected programs of a validated `programs:` create.

        A key two of them create comes twice: checks.keys_distinct refuses it
        (cotton's cotton_cycles_total beside a program keyed cotton_cycles_total).
        """
        for key, config in value[CONF_DETECTED].items():
            yield from detected_keys(key, config).items()


    def _places(builder: Feature, _name: str) -> tuple[Place, ...]:
        """`programs:` sits in the block; its keys are the detected programs' (derived).

        It names nothing to a person (`_name`); `named` is never asked, as it adds
        no fixed key.
        """
        return (
            Place(
                schema=DETECTED,
                keys={},
                named=partial(qualified, builder.namespace),
                example={CONF_DETECTED: {"cotton": {"name": "Cotton", "above": 1500}}},
                derived=_derived,
            ),
        )


    def _build(
        hass: HomeAssistant, device: Device, builder: Feature, block: Any, *_: Any
    ) -> list[PururuEntity]:
        """Each detected program, in the configuration's order, reading the builder's settings (Programs)."""
        if CONF_PROGRAMS not in block:
            return []
        role = builder.role(Programs)
        assert role is not None  # ASPECT.offered checked it
        energy = None if role.energy is None else block.get(role.energy)
        return [
            entity
            for key, config in block[CONF_PROGRAMS][CONF_DETECTED].items()
            for entity in build_detected(
                hass, device, key, config, reading=block[role.reading], energy=energy
            )
        ]


    ASPECT = Aspect(
        key=CONF_PROGRAMS,
        offered=lambda builder: builder.role(Programs) is not None,
        places=_places,
        build=_build,
        # Absent: no detected program; an explicit {} or null is refused
        mount_absent=False,
    )
    ```

  `aspects/__init__.py`:

  ```python
  from . import alerts, notifications, programs, statistics

  # In build order: a builder's ready-made alerts, its detected programs, then
  # its meters (after every total they meter, which seeds them), then its
  # ready-made notifications (no entity: automations). Mounting doesn't follow
  # it: catalogue.mount takes the deepest places first
  ASPECTS: tuple[Aspect, ...] = (
      alerts.ASPECT,
      programs.ASPECT,
      statistics.ASPECT,
      notifications.ASPECT,
  )
  ```

  `features/appliance/__init__.py` (imports `Programs`): after `Derived(...)`, `Programs("power", "energy")` with the comment "More detected programs of its power, in `programs: detected:` (the programs aspect)"; `Counters` gains `*program.counted_each(program.DETECTED_AT)` after `*program.counted((RUNNING_PROGRAM,))`, its comment "…each phase and other, and each detected program".

- [ ] **Step 5: The names.** In `translations/en.json`, `translations/pt-BR.json` and `icons.json`, after each file's `"phase_energy_total"` line (hand-formatted: one entry a line), seven entries `detected_<suffix>`, each a copy of `phase_<suffix>`'s (the same `{item}` texts, units and icons): `detected_last_cycle_start`, `_last_cycle_end`, `_last_cycle_duration`, `_last_cycle_energy`, `detected_cycles_total` (with its `unit_of_measurement`), `detected_runtime_total`, `detected_energy_total`. For example, en:

  ```json
        "detected_cycles_total": {"name": "{item} cycles", "unit_of_measurement": "cycles"},
  ```

  pt-BR `"detected_cycles_total": {"name": "Ciclos de {item}", "unit_of_measurement": "ciclos"}`, icons `"detected_cycles_total": {"default": "mdi:counter"}`.

- [ ] **Step 6: GREEN.**

  ```sh
  uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu
  uv run pytest tests/test_detected_programs.py tests/test_features.py tests/test_catalogue.py -n 4 -q
  ```

  Expected: all pass.

- [ ] **Step 7: The fixture and the snapshot.** `tests/fixtures/house.yaml`, in `clothes_washer`'s appliance, before its `statistics:`:

  ```yaml
        programs:
          detected:
            cotton:
              name: Algodão
              above: 1500
              on_delay: {minutes: 5}
              statistics: {runtime: [today, week, month, year], cycles: [today, week, month, year], energy: [today, week, month, year]}
  ```

  ```sh
  cp tests/fixtures/house_ids.json <scratchpad>/ids_before.json
  PURURU_UPDATE_IDS=1 uv run pytest tests/test_ids.py -n 0 -q
  python3 <scratchpad>/iddiff_d3.py <scratchpad>/ids_before.json tests/fixtures/house_ids.json 3
  uv run pytest -q
  ```

  Expected: `added 20` (the carrier, its seven cycle entities, its twelve meters); then `1328 passed` (1303, the 23 of `test_detected_programs.py`, the two new contract rules).

- [ ] **Step 8: Commit, push.**

  ```sh
  git add -A custom_components tests
  git commit -m "pururu: programs: detected: in the appliance's block (refactor D3)

  The Programs role makes a builder take detected programs; the programs
  aspect mounts programs: detected:, lists each one's keys and builds it with
  the detector: binary_sensor.pururu_<device>_appliance_<key>, its last
  cycle, totals and meters, named after its name. An executable program in a
  feature is refused; a key taken by the appliance is two entities.

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM"
  git push
  ```

---

### Task 4: A detected program's phases and `other`

A detected program's phases and its `other` (rulings 4, 13, 14): the detector learns `of`, the program each phase belongs to, and prefixes, signals and names follow it; `counted_each` gains their statistics places; the fixture's `cotton` gains a phase and `other`.

**Files:**
- Modify `custom_components/pururu/features/cycle/program/schema.py` (`_of`, `phase_slug`, `phase_keys`, `keys_of`, `Phase.of`, `Phase.item`, `program_of`, `DETECTED_NAMED`, `counted_each`, `detected_keys`), `features/cycle/program/entities.py` (`PhaseRunning`, `PhaseCurrent`, `PhaseLast`, `_fixed`, `_translation`, `build`, `build_detected`), `aspects/programs.py` (the example), `translations/en.json`, `translations/pt-BR.json`, `icons.json`.
- Modify `tests/test_detected_programs.py`, `tests/test_features.py`, `tests/fixtures/house.yaml`, `tests/fixtures/house_ids.json`.

**Interfaces** (produced; `of` is always last and optional, `None` being the running program, whose keys and names don't change):

```python
def phase_slug(key: str, of: str | None = None) -> str          # <of>_phase_<key>
def phase_keys(key: str, of: str | None = None) -> dict[str, Platform]
def keys_of(config: Mapping[str, Any], of: str | None = None) -> dict[str, Platform]
def program_of(config: Mapping[str, Any], of: Item | None = None) -> Program
Phase.of: Item | None = None
DETECTED_NAMED  # + detected_phase_current, detected_phase_last, detected_phase_other, detected_phase_other_<suffix>
PhaseCurrent(device, carrier, *, source, of=None); PhaseLast(device, program, *, source, of=None)
```

- [ ] **Step 1: The failing tests.** Append to `tests/test_detected_programs.py`:

  ```python
  # --- its phases ---------------------------------------------------------------------

  # Cotton heats its water over 1800 W; the appliance's running program warms over 1000 W
  WARMING: dict[str, Any] = {"name": "Aquecendo", "above": 1800}
  PHASED: dict[str, Any] = {"cotton": {**DETECTED["cotton"], "phases": {"warming": WARMING}, "other": {}}}


  def phased(**block: Any) -> dict[str, Any]:
      """The washer whose running program warms over 1000 W and whose cotton program heats over 1800 W."""
      return devices(**{"running_program": {**RUNNING_PROGRAM, "phases": {"warming": {"name": "Aquecendo", "above": 1000}}},
                        "programs": {"detected": PHASED}, **block})


  async def test_its_phases_entities_and_ids(ha: HomeAssistant) -> None:
      """<key>_phase_<phase>…, <key>_phase_current and _last, beside the running program's phase_… of the same key."""
      assert await setup(ha, phased())
      found = held(ha, KEY)
      for phase in ("warming", "other"):
          assert f"binary_sensor.{PREFIX}_cotton_phase_{phase}" in found
          assert {sensor(f"cotton_phase_{phase}_{suffix}") for suffix in SUFFIXES} <= found
      assert {sensor("cotton_phase_current"), sensor("cotton_phase_last"), sensor("phase_current"),
              f"binary_sensor.{PREFIX}_phase_warming"} <= found


  async def test_a_detected_programs_phases_count_apart(ha: HomeAssistant, freezer: Any) -> None:
      """Cotton's warming and the running program's warming run on their own signals: each counts its own cycles."""
      await fake(ha, ENERGY, "100")
      assert await setup(ha, phased())
      await watts(ha, 1)
      await tick(ha, freezer, 125)
      await watts(ha, 2000)
      await tick(ha, freezer, 600)
      assert state(ha, sensor("cotton_phase_current")) == "warming"
      await watts(ha, 1)
      await tick(ha, freezer, 125)
      assert state(ha, sensor("phase_warming_cycles_total")) == "1"
      assert state(ha, sensor("cotton_phase_warming_cycles_total")) == "1"
      assert state(ha, sensor("cotton_phase_last")) == "warming"
      await watts(ha, 1200)
      await tick(ha, freezer, 600)
      await watts(ha, 1)
      await tick(ha, freezer, 125)
      assert state(ha, sensor("phase_warming_cycles_total")) == "2"
      assert state(ha, sensor("cotton_phase_warming_cycles_total")) == "1"


  async def test_a_restart_keeps_a_detected_programs_phase(ha: HomeAssistant, freezer: Any) -> None:
      since = "2026-09-16T16:50:00+00:00"
      await restart(ha, phased(), (State(COTTON, "on"), snapshot(since, warming={"since": since})))
      await watts(ha, 2000)
      await tick(ha, freezer, 1)
      assert state(ha, f"binary_sensor.{PREFIX}_cotton_phase_warming") == "on"
      assert state(ha, sensor("cotton_phase_current")) == "warming"


  @pytest.mark.parametrize(("language", "names"), [
      pytest.param("en", {
          sensor("cotton_phase_current"): "Tanquinho Algodão phase",
          sensor("cotton_phase_last"): "Tanquinho Algodão last phase",
          f"binary_sensor.{PREFIX}_cotton_phase_warming": "Tanquinho Aquecendo",
          sensor("cotton_phase_warming_cycles_total"): "Tanquinho Aquecendo cycles",
          f"binary_sensor.{PREFIX}_cotton_phase_other": "Tanquinho Algodão other phase",
          sensor("cotton_phase_other_cycles_total"): "Tanquinho Algodão other phase cycles",
          sensor("cotton_phase_other_energy_month"): "Tanquinho Algodão other phase energy this month",
      }, id="en"),
      pytest.param("pt-BR", {
          sensor("cotton_phase_current"): "Tanquinho Fase de Algodão",
          sensor("cotton_phase_last"): "Tanquinho Última fase de Algodão",
          f"binary_sensor.{PREFIX}_cotton_phase_other": "Tanquinho Outra fase de Algodão",
          sensor("cotton_phase_other_cycles_total"): "Tanquinho Ciclos de outra fase de Algodão",
          sensor("cotton_phase_other_energy_month"): "Tanquinho Energia de outra fase de Algodão no mês",
      }, id="pt-BR"),
  ])
  async def test_a_detected_programs_phases_are_named(
          ha: HomeAssistant, language: str, names: dict[str, str]) -> None:
      """A phase by its name, as the running program's; the fixed ones and other's with the program's name."""
      ha.config.language = language
      cotton = {**PHASED["cotton"], "other": {"statistics": {"energy": ["month"]}}}
      assert await setup(ha, phased(programs={"detected": {"cotton": cotton}}))
      for entity_id, name in names.items():
          assert ha.states.get(entity_id).attributes["friendly_name"] == name


  async def test_a_detected_programs_phase_statistics(ha: HomeAssistant) -> None:
      cotton = {**PHASED["cotton"], "phases": {"warming": {**WARMING, "statistics": {"cycles": ["today"]}}},
                "other": {"statistics": {"runtime": ["week"]}}}
      assert await setup(ha, phased(programs={"detected": {"cotton": cotton}}))
      assert {sensor("cotton_phase_warming_cycles_today"), sensor("cotton_phase_other_runtime_week")} <= held(ha, KEY)


  async def test_an_alert_can_watch_a_detected_programs_phase(ha: HomeAssistant) -> None:
      config = phased()
      config[KEY]["alerts"] = {"hot": {"name": "Quente", "when": "appliance_cotton_phase_current", "is": "warming",
                                       "for": {"hours": 1}}}
      assert await setup(ha, config)
      assert ha.states.get(f"binary_sensor.pururu_{KEY}_alert_hot") is not None
  ```

  and in `test_detected_programs_may_not_take_each_others_keys` (Task 3), `cotton = PHASED["cotton"]` and its docstring "Each key cotton creates (with a phase and other), …": its 25 keys now include `cotton_phase_current`, `cotton_phase_warming`, `cotton_phase_other_cycles_total`….

  `tests/test_features.py`:
  - `test_a_detected_programs_keys_are_named` also checks the fixed ones' states:

    ```python
        for translations in (en, pt):
            sensors = translations["entity"]["sensor"]
            for fixed in ("phase_current", "phase_last"):
                assert sensors[f"detected_{fixed}"]["state"] == sensors[fixed]["state"], fixed
    ```
  - `test_what_a_last_cycle_follows_is_a_cycle_source`: `following["appliance"] == {"running", "phase_warming", "phase_other", "cotton", "cotton_phase_rinsing", "cotton_phase_other"}` (the aspect's example, Step 4);
  - `test_a_counter_without_its_setting_is_refused`: `needing` gains `("appliance", ("programs", "detected", "*", "phases", "*"))` and `("appliance", ("programs", "detected", "*", "other"))`.

  ```sh
  uv run pytest tests/test_detected_programs.py tests/test_features.py -n 4 -q
  ```

  Expected: the new tests fail: a detected program's phases are built as `phase_warming` (the running program's IDs: `binary_sensor.pururu_clothes_washer_appliance_phase_warming` is two entities, and `…_cotton_phase_warming` doesn't exist), `detected_phase_current` has no translation (`KeyError`), and the contract's places and `following` don't match.

- [ ] **Step 2: The schema.** `features/cycle/program/schema.py`:

  ```python
  def _of(entity_key: str, of: str | None) -> str:
      """`entity_key` of the running program, or of detected program `of`: <of>_<entity_key>."""
      return entity_key if of is None else f"{of}_{entity_key}"


  def phase_slug(key: str, of: str | None = None) -> str:
      """A phase's entity keys' slug: phase_<key>, or <of>_phase_<key> in detected program `of`; the one rule every phase key uses."""
      return _of(f"{PHASE}_{key}", of)
  ```

  `phase_keys(key, of=None)` uses `phase_slug(key, of)`; `keys_of(config, of=None)` ("`of`: a detected program's key, before each (<of>_phase_current, …)") lists `{_of(key, of): platform for key, platform in FIXED.items()}` and `phase_keys(key, of)`. `_apart` doesn't change: collisions among one program's phases are the same with or without its prefix.

  `DETECTED_NAMED` and its comment:

  ```python
  # A detected program's translations, once for every builder, all with {item},
  # its name: detected_<suffix> for its cycle entities, detected_phase_current and
  # _last for its fixed ones, detected_phase_other* for its other's (a configured
  # phase's are phase_<suffix>, with the phase's name, as the running program's)
  DETECTED = "detected"
  DETECTED_NAMED: dict[str, Platform] = {
      **{f"{DETECTED}_{suffix}": platform for suffix, platform in SUFFIXES.items()},
      **{f"{DETECTED}_{key}": platform for key, platform in FIXED.items()},
      f"{DETECTED}_{PHASE}_{OTHER}": Platform.BINARY_SENSOR,
      **{
          f"{DETECTED}_{PHASE}_{OTHER}_{suffix}": platform
          for suffix, platform in SUFFIXES.items()
      },
  }
  ```

  After `_detected_item`, and `counted_each` and `detected_keys` in full:

  ```python
  def _detected_phase_item(block: Any, path: Path) -> Item:
      """A phase of a detected program, at `path` (…, <program>, phases, <phase>): <program>_phase_<phase>, named by its name."""
      return Item(slug=phase_slug(path[-1], path[-3]), name=at(block, path)["name"])


  def _detected_other_item(block: Any, path: Path) -> Item:
      """A detected program's other, at `path` (…, <program>, other): <program>_phase_other, named with its program's name."""
      return Item(slug=phase_slug(OTHER, path[-2]), name=at(block, path[:-1])["name"])


  def counted_each(where: Path) -> tuple[Counted, ...]:
      """Where each detected program of the map at `where` counts: its runtime, cycles and energy, as its item's; each phase's and other's.

      Unlike running_program's (the builder's own totals), a detected program's
      totals are its own: <key>_runtime_total, <key>_cycles_total,
      <key>_energy_total (energy needs the builder's `energy`). Its phases' are
      <key>_phase_<phase>_<counter>_total; its other's meters are named by
      detected_phase_other_*, with its name.
      """
      return (
          Counted(needs=PHASE_COUNTERS, at=where, item=_detected_item),
          Counted(
              needs=PHASE_COUNTERS,
              at=(*where, "phases", EACH),
              item=_detected_phase_item,
          ),
          Counted(
              needs=PHASE_COUNTERS,
              at=(*where, OTHER),
              item=_detected_other_item,
              named=f"{DETECTED}_{PHASE}_{OTHER}",
          ),
      )


  def detected_keys(key: str, config: Mapping[str, Any]) -> dict[str, Platform]:
      """Every entity key detected program `key` can create: its carrier, its cycle entities, then its phases'."""
      return {
          key: Platform.BINARY_SENSOR,
          **{f"{key}_{suffix}": platform for suffix, platform in SUFFIXES.items()},
          **keys_of(config, of=key),
      }
  ```

  `Phase` and `program_of`:

  ```python
      key: str
      name: str
      band: Band
      # The detected program it is a phase of: None, the builder's running program
      of: Item | None = None

      @property
      def item(self) -> Item:
          """Its entity keys' item: phase_<key>_<suffix>, or <of>_phase_<key>_<suffix>.

          A detected program's other is named with the program's name: its
          translations (detected_phase_other_*) carry {item}.
          """
          if self.of is None:
              return Item(slug=phase_slug(self.key), name=self.name)
          name = self.of.name if self.other else self.name
          return Item(slug=phase_slug(self.key, self.of.slug), name=name)
  ```

  `program_of(config, of: Item | None = None)` ("`of`: a detected program's item, its phases' (Phase.of).") passes `of=of` to every `Phase`, `other`'s too.

- [ ] **Step 3: The entities.** `features/cycle/program/entities.py`:

  ```python
  def _fixed(key: str, of: Item | None) -> str:
      """What the current or last phase is named under: its key, or detected_<key> with {item} in a detected program."""
      return key if of is None else f"{DETECTED}_{key}"


  def _translation(phase: Phase, suffix: str) -> str:
      """What a phase's cycle entity is named under: phase_<suffix> with {item}, or other's own (a detected program's, with {item})."""
      if not phase.other:
          return f"{PHASE}_{suffix}"
      return _fixed(f"{PHASE}_{OTHER}_{suffix}", phase.of)
  ```

  `PhaseRunning.__init__`, a branch before `elif phase.other:` (today's `if phase.other:`):

  ```python
          if phase.other and phase.of is not None:
              # <of>_phase_other, named with its program's name
              self._identify(
                  device,
                  Platform.BINARY_SENSOR,
                  f"{PHASE}_{OTHER}",
                  item=phase.of,
                  translation=f"{DETECTED}_{PHASE}_{OTHER}",
              )
  ```

  (`_identify` makes `item_key("phase_other", of)`, `<of>_phase_other`, and `{item}` the program's name; a configured phase's `item.slug` is prefixed already.) `PhaseCurrent(device, carrier, *, source, of=None)` and `PhaseLast(device, program, *, source, of=None)` identify as `_identify(device, Platform.SENSOR, f"{PHASE}_current", item=of, translation=_fixed(f"{PHASE}_current", of))` (`_last` alike): with `of=None` exactly today's key and translation. `build` passes `of=of` to both; `build_detected` calls `program_of(config, of)`.

- [ ] **Step 4: The names and the example.** In `translations/en.json`, `translations/pt-BR.json` and `icons.json`, after Task 3's `"detected_energy_total"` line, the sensors (each a copy of the running program's key, its name given `{item}`; icons, units and states copied as they are):
  - `detected_phase_current`: en `"{item} phase"`, pt-BR `"Fase de {item}"`, with `phase_current`'s `state`;
  - `detected_phase_last`: en `"{item} last phase"`, pt-BR `"Última fase de {item}"`, with `phase_last`'s `state`;
  - `detected_phase_other_<suffix>` (7) and `detected_phase_other_<counter>_<period>` (12), from `phase_other_…`: en `Other phase` → `{item} other phase` ("{item} other phase energy this month"), pt-BR `outra fase` → `outra fase de {item}` ("Energia de outra fase de {item} no mês", "Ciclos de outra fase de {item}");

  and in `binary_sensor`, after `"phase_other"` (the block's last entry: a comma goes after it), `"detected_phase_other"`: en `"{item} other phase"`, pt-BR `"Outra fase de {item}"`, icon `mdi:progress-question`.

  `aspects/programs.py`'s example reaches every place (the contract), with a module constant before `_places`:

  ```python
  # A detected program with a phase and other: the programs aspect's example
  EXAMPLE: dict[str, Any] = {
      "name": "Cotton",
      "above": 1500,
      "phases": {"rinsing": {"name": "Rinsing", "above": 1800}},
      "other": {},
  }
  ```

  and `example={CONF_DETECTED: {"cotton": EXAMPLE}}` ("One phase and other: the contract test reaches every place").

- [ ] **Step 5: GREEN.**

  ```sh
  uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu
  uv run pytest tests/test_detected_programs.py tests/test_features.py tests/test_program_entities.py tests/test_program.py -n 4 -q
  ```

  Expected: all pass; the running program's tests (`test_program_entities.py`, `test_program.py`, `test_appliance.py`) unchanged.

- [ ] **Step 6: The fixture and the snapshot.** `tests/fixtures/house.yaml`, `cotton` after its `statistics:`:

  ```yaml
              phases:
                warming:
                  name: Aquecendo
                  above: 1800
                  statistics: {runtime: [today, week, month, year], cycles: [today, week, month, year], energy: [today, week, month, year]}
              other:
                statistics: {runtime: [today, week, month, year], cycles: [today, week, month, year], energy: [today, week, month, year]}
  ```

  ```sh
  cp tests/fixtures/house_ids.json <scratchpad>/ids_before.json
  PURURU_UPDATE_IDS=1 uv run pytest tests/test_ids.py -n 0 -q
  python3 <scratchpad>/iddiff_d3.py <scratchpad>/ids_before.json tests/fixtures/house_ids.json 4
  uv run pytest -q
  ```

  Expected: `added 42` (`cotton_phase_current`, `cotton_phase_last`; for `warming` and `other` each, the binary sensor, seven cycle entities and twelve meters); then `1335 passed` (1328 plus the seven).

- [ ] **Step 7: Commit, push, the PR text.**

  ```sh
  git add -A custom_components tests
  git commit -m "pururu: a detected program's phases and other (refactor D3)

  A detected program takes phases, as every program: its phases' entities
  are appliance_<key>_phase_<phase>..., its current and last phase
  appliance_<key>_phase_current and _last, each on its own signals. Its
  fixed and other's entities carry its name.

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM"
  git push
  gh pr edit <n> --body-file <scratchpad>/pr.md
  ```

  The PR text's update step is now final (ruling 22, step 4 added).

---

### Task 5: The Guide

The user-facing pages say what D3 changed: one programs page with both groups (ruling 19), a detected program in the appliance's page, the executable programs' new IDs everywhere, and no flat `programs:` anywhere. The update step stays in the PR text (ruling 22). No code changes; the tests that read pages (`test_presets.py`, `test_alert_lights.py`, `test_alert2.py`, `test_notifications.py`, `test_events.py`) must keep passing.

**Files:**
- Modify `docs/concepts/programs.mdx` (the merged page); delete `docs/concepts/detected-programs.mdx`.
- Modify `docs.json`, `docs/features/appliance.mdx`, `docs/concepts/{reactions,statistics,entity-ids,devices-and-features,alerts,events,notifications}.mdx`, `docs/getting-started/{first-device,install}.mdx`, `docs/index.mdx`, `docs/reference/{configuration,troubleshooting}.mdx`, `README.md` where they name a program.

- [ ] **Step 1: The programs page**, `docs/concepts/programs.mdx`, rewritten from both pages (every sentence of `detected-programs.mdx` kept, moved under "Detected programs"; every sentence of today's `programs.mdx` kept under "Executable programs", with the new IDs). Front matter:

  ```mdx
  ---
  title: Programs
  description: What a device runs, detected from a reading or run by pururu as a Home Assistant script, and the phases of each run.
  ---
  ```

  In this order:
  - **Intro**: a program is a named kind of run. A **detected** program is one pururu knows is running from a reading: a band of the plug's power, confirmed by delays (the appliance running at all, a cotton wash). An **executable** program is one pururu runs itself: its steps, as a Home Assistant script (a greenhouse's cleaning). Then the spec's table (Part 4, "The model"): *pururu knows it runs* (from a reading / because it runs it), *can be started* (no / yes: a reaction's `then`, `script.turn_on`), *where* (in the block of the feature whose reading it reads / at the device).
  - **Where they sit** (D22): a feature's `programs:` takes `detected:` only (`a feature's programs are detected: executable programs are the device's`); a device's `programs:` takes `executable:` only (`a device's programs are executable: a detected program sits in the block of the feature whose reading it reads`); the appliance's own `running_program` is a detected program with a fixed key, required, in its block. Only an executable program can be started. The example: the spec's "In the YAML" washer (with `programs: detected: cotton`) and greenhouse (`programs: executable: clean`).
  - **Detected programs** (`##`), then its subsections from `detected-programs.mdx`: "A band", "The running program", "More detected programs" (new), "Phases", "How phases run", "`other`", "Entities", "State names", "Referring to a program or a phase". New text:
    - *More detected programs*: `programs: detected:` in the appliance's block, a map of **key → program**: `name` (required: it names its entities; `a detected program needs a name: it names its entities`), a band (`above`/`below`, `on_delay`/`off_delay`), `statistics` (`runtime`, `cycles`, `energy`; `energy` needs the appliance's `energy`), `phases` and `other` as the running program's. It reads the appliance's `power`, and `energy` for each cycle's kWh. A cycle of `cotton` is also one of the running program's (both bands hold): each counts its own. Its key is a slug; a key whose entities would be the appliance's is refused (`device clothes_washer: pururu_clothes_washer_appliance_idle_energy_total would be two entities`): its own entity keys (`power`, `running`, `cycles_total`…, `idle` for `idle_energy_total`), its ready-made alerts' (`alert_offline`…), its meters' (`runtime_today`…), its running program's phases' (`phase_current`, `phase_<phase>`…), and another detected program's (`cotton_phase_warming` beside `cotton` with a phase `warming`). Pick a word, not an entity's name.
    - *Entities*: the table grows the detected program's rows (`<program>` its key):

      | Entity | What it is |
      |---|---|
      | `binary_sensor.pururu_<key>_appliance_<program>` | On while it runs, named by its `name`. Attributes `cycle_start`, and `cycle_end` while its `off_delay` runs |
      | `sensor.pururu_<key>_appliance_<program>_last_cycle_start`, `_end`, `_duration`, `_energy` | Its last cycle (`_energy` *with `energy`*) |
      | `sensor.pururu_<key>_appliance_<program>_cycles_total`, `_runtime_total`, `_energy_total` | Its totals, `total_increasing` (`_energy_total` *with `energy`*) |
      | `sensor.pururu_<key>_appliance_<program>_<counter>_<period>` | One per entry of its `statistics` |
      | `sensor.pururu_<key>_appliance_<program>_phase_current`, `_phase_last`, `binary_sensor.…_<program>_phase_<phase>`, `sensor.…_<program>_phase_<phase>_<suffix>` | Its phases, as the running program's, under its key |

      Named: the program's own and its fixed and `other`'s entities after its name ("Tanquinho Algodão cycles", "Tanquinho Algodão phase", "Tanquinho Algodão other phase"; "Ciclos de Algodão", "Fase de Algodão", "Outra fase de Algodão"); a phase's after the phase's name, as the running program's.
    - *Referring*: `when: appliance_cotton`, `appliance_cotton_phase_current`, `appliance_cotton_cycles_total`; a detected program can't be started (`reactions: <reaction>: cotton is not an executable program of this device`) nor acted on by a step (`programs: appliance_cotton does not take turn_on`).
  - **Executable programs** (`##`), then today's "The include", "Settings", "Steps", "Only its own device", "The script", "Statistics", with:
    - the example under `programs: executable:`;
    - `script.pururu_greenhouse_program_executable_clean`, `script.pururu_<key>_program_executable_<program key>`, `sensor.pururu_<key>_program_executable_<program>_…` everywhere; "Settings": "`programs: executable:` is a map of **program key → program** … The key is a slug, and it ends the script's ID after `program_executable_`: `clean` → `script.pururu_greenhouse_program_executable_clean`";
    - `phases` on an executable program is refused (an unknown key: its steps could be its phases, "Not in 0.2.0");
    - the statistics' `when:` example becomes `program_executable_clean_last_cycle_end`;
    - "From 0.1.14 and before" stays as it is (spec: PR C removes it).

  `docs.json`: the "Detected programs" entry goes; "Programs" stays. `pnpm docs:check` finds every link to `/concepts/detected-programs`: each becomes `/concepts/programs#<section>` (`#a-band`, `#the-running-program`, `#phases`, `#other`, `#entities`, as the section it names).

- [ ] **Step 2: `docs/features/appliance.mdx`.** The example gains `programs: detected: cotton: {name: Algodão, above: 1500, on_delay: {minutes: 5}}` (the spec's). Settings: a `<Property name="programs.detected" type="map" optional>`: "More [detected programs](/concepts/programs#more-detected-programs) of the plug's power, each with its `name`, a band, `statistics`, `phases`. Each is `binary_sensor.pururu_<key>_appliance_<program>`." Entities: a row for them, pointing to the programs page. `running_program`'s property links `/concepts/programs#the-running-program`.

- [ ] **Step 3: Every other Guide page.**
  - `docs/concepts/reactions.mdx`: its example's `programs:` is `programs: executable:` (Task 1); `then`'s property: "A key of **this device's** [executable programs](/concepts/programs#executable-programs) … A detected program can't be started: `reactions: <reaction>: <key> is not an executable program of this device`"; "Starting a program"'s YAML and every `script.pururu_…_program_…` become `…_program_executable_…` (`script.pururu_laundry_lights_program_executable_blink`, `script.pururu_orchard_program_executable_water`).
  - `docs/concepts/statistics.mdx`: "Where it sits" lists a detected program (and its phases and `other`) in `programs: detected:`, and each executable program; the counters table: a detected program's `runtime`, `cycles`, `energy` (`energy` needs the appliance's `energy`), its item its key; an executable program's `<item>` is `executable_<key>`; the naming example adds "Tanquinho Algodão cycles today".
  - `docs/concepts/entity-ids.mdx`: the `programs` row: `script.pururu_greenhouse_program_executable_clean`, `sensor.pururu_greenhouse_program_executable_clean_cycles_total`; the `appliance` row adds `binary_sensor.pururu_clothes_washer_appliance_cotton`; a sentence: a detected program's key is an entity key of the appliance's namespace, so it can't be one the appliance already creates (link to the programs page).
  - `docs/concepts/devices-and-features.mdx`: "`programs`" is a device key for executable programs; a feature's block takes its detected ones.
  - `docs/concepts/alerts.mdx`, `events.mdx`, `notifications.mdx`: every `program_…` ID or key follows (`program_executable_…`); `when:`'s examples may add `appliance_cotton`.
  - `docs/getting-started/first-device.mdx`: the link to the detected programs page becomes `/concepts/programs#phases`; one sentence after the phases: a wash kind the power alone tells apart can be a detected program of its own (link). `install.mdx`: "Using [executable programs](/concepts/programs#executable-programs)? …".
  - `docs/index.mdx`: "A [program](/concepts/programs) is a script …" becomes "An [executable program](/concepts/programs#executable-programs) is a script …".
  - `docs/reference/configuration.mdx`: the example's `programs:` under `executable:` (Task 1) and the washer's `programs: detected: cotton`; "General rules"' key list names "a detected or executable program"; `programs`' property: "`executable:`, a map of **program key → program**, each one a Home Assistant script …; a detected program sits in its feature's block (`programs: detected:`)", `then` names an executable program.
  - `docs/reference/troubleshooting.mdx`: "The reload changed nothing" adds: a flat `programs:` (`'clean' is an invalid option for 'pururu', check: pururu->devices->greenhouse->programs->clean`: indent under `executable:`), `detected:` at the device, `executable:` in a feature, `programs: {}` (`a feature's programs needs detected`), a detected program without `name`, `then:` naming a detected program, a detected program keyed as one of the appliance's entities (`… would be two entities`); every `script.pururu_greenhouse_program_clean` becomes `…_program_executable_clean`; "Programs" is "Executable programs".
  - `README.md`: nothing names a flat `programs:` or an old ID (checked below).

  ```sh
  git grep -n 'detected-programs\|_program_clean\|program_<\|_program_blink\|_program_water\|_program_evening' -- docs README.md ':!docs/superpowers' ':!docs/develop'
  git grep -n -B1 -A2 '^ *programs:$' -- docs README.md ':!docs/superpowers'
  ```

  Expected: the first finds nothing (every ID is `program_executable_…`); the second shows only `programs:` followed by `executable:` or `detected:`.

- [ ] **Step 4: Check.**

  ```sh
  pnpm install --frozen-lockfile
  pnpm docs:check
  uv run pytest tests/test_presets.py tests/test_alert_lights.py tests/test_alert2.py tests/test_notifications.py tests/test_events.py -n 4 -q
  uv run pytest -q
  ```

  Expected: no broken link; the page tests pass; `1335 passed`. `pnpm docs:preview`: the merged page renders (no `{`/`<` outside code: `{item}` stays in backticks), the tables fit.

- [ ] **Step 5: Commit, push.**

  ```sh
  git add -A docs docs.json README.md
  git commit -m "docs: one programs page, detected and executable; the new IDs (refactor D3)

  Detected and executable programs share one concept page: where each
  sits, the appliance's running program and its detected ones, phases,
  other, entities; executable programs under programs: executable: with
  their program_executable_ IDs. Every example and ID follows.

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM"
  git push
  ```

---

### Task 6: The Develop pages, CLAUDE.md, coverage, the final review, ready

What contributors read says what D3 built: the `Programs` role, `aspects/programs.py` (the aspect and the device key), nested aspects, `Place.derived`, items from `(block, path)`, the detector's `of`. Then coverage against `main`, the one final review, and the PR ready.

**Files:**
- Modify `CLAUDE.md`, `docs/develop/{architecture,writing-a-feature,index,testing}.mdx`.

- [ ] **Step 1: CLAUDE.md** (Architecture, Features, Tests):
  - "Where the code lives": `aspects/` holds "`ASPECTS` … `statistics.py`, `alerts.py`, `notifications.py`, `programs.py` (the detected programs' aspect and the executable programs' device key)"; `device_keys/` holds "`DEVICE_KEYS`, reactions" (programs moved); `CHECKS`' owners list `programs.check` in `aspects/programs.py`; `setup/catalogue.py`'s line adds that `mount` takes the deepest places first and puts the shallowest first;
  - step 6: "Generate the programs' scripts (`aspects/programs.py`: `programs: executable:`, `script.pururu_<device>_program_executable_<key>`) …"; "`reactions` and `programs` are device keys" becomes "`reactions` and `programs` (its `executable:` group) are device keys; a feature's `programs: detected:` is an aspect";
  - the roles list gains `Programs`; a bullet after the `Derived` one: "A builder with `Programs(reading, energy)` (the appliance: `power`, `energy`) takes `programs: detected:` in its block: the programs aspect (`aspects/programs.py`) mounts it, lists each detected program's keys (`Place.derived`, pairs, so `checks.keys_distinct` sees a key two programs create) and builds each with `program.build_detected` (the detector with `of`, the program's item: `<key>`, `<key>_<suffix>`, `<key>_phase_…`, named `detected_*` with `{item}`); the builder's `Counters` lists `program.counted_each(program.DETECTED_AT)`.";
  - the **Aspects** bullet: `ASPECTS` is the build order (alerts, programs, statistics, notifications); `mount` takes each (aspect, place) deepest first, so an aspect's key can sit inside another aspect's value (statistics in a detected program), and puts values back shallowest first; `Place.item` and `Counted.item` take `(block, path)` (`feature.ItemOf`, `feature.at`); `Place.derived`;
  - the `Items` bullet's example: a program's keys are `executable_<key>_<suffix>` (`program_executable_clean_cycles_total`), named `program_<suffix>` with `{program}`;
  - the entity IDs bullet: the script is `script.pururu_<device>_program_executable_<key>`;
  - Tests: `test_detected_programs.py` (the aspect: IDs, counting apart, restarts, names, statistics, where programs sit, collisions computed).

- [ ] **Step 2: The Develop pages.**
  - `docs/develop/architecture.mdx`: step 6 of the diagram and the list: "programs' scripts (`aspects/programs.py`)"; the roles table gains `Programs(reading, energy)` ("the settings a detected program in its block reads: the programs aspect mounts `programs: detected:`"); "Detected programs": the appliance's `running_program` (the builder's own carrier and cycle entities) and its `programs: detected:` (the aspect's: `build_detected`, `of`, keys by `Place.derived`, statistics at `counted_each`'s places); "Aspects": the four aspects, `ASPECTS` as the build order, `mount`'s depth order (deepest taken first, shallowest put back first), `Place.derived`, `(block, path)` items; "The checks": `keys_distinct` refuses a detected program's key the appliance or another program creates; "The plans": `programs.plan` is `aspects/programs.py`'s.
  - `docs/develop/writing-a-feature.mdx`: a paragraph "**Detected programs.** A feature reading a sensor can take `programs: detected:` by adding `Programs(reading, energy)` and `*program.counted_each(program.DETECTED_AT)` to its `Counters`: the programs aspect does the rest (schema, keys, build)"; the `Items` example is `program_executable_clean_cycles_total`; the contract table: `test_a_detected_programs_keys_are_named`, `test_a_programs_builder_counts_its_detected_programs` come; `test_what_a_last_cycle_follows_is_a_cycle_source` (the aspects' builds too), `test_an_offered_aspect_validates_and_builds` (the full example; builds exactly when it lists, fixed or derived), `test_a_builders_own_schema_refuses_an_aspects_key` (inside another aspect's value, that aspect's schema), `test_a_counter_is_totalled` (from the full example; an aspect's total counts) say so.
  - `docs/develop/index.mdx`, the tree: `aspects/` lists `programs.py` ("detected programs' aspect, executable programs' device key"); `device_keys/` is "reactions.py; alerts is aspects.alerts.ALERTS, programs aspects.programs.PROGRAMS".
  - `docs/develop/testing.mdx`, "Test files": `test_detected_programs.py` comes ("a feature's detected programs: IDs, counting apart from the running program, restarts, names in both languages, statistics, where programs sit, collisions computed from `catalogue.keys`, phases"); `test_catalogue.py` adds "an aspect inside another, a place's derived keys"; `test_programs.py` says "executable programs".

  ```sh
  git grep -n 'device_keys/programs\|device_keys\.programs\|programs\.STATISTICS\|_program_clean\|detected-programs' -- CLAUDE.md docs ':!docs/superpowers'
  pnpm docs:check
  uv run pytest tests/test_code.py -n 0 -q
  ```

  Expected: `git grep` finds nothing; no broken link; `test_the_develop_docs_examples_import_what_exists` passes (every titled example imports what exists).

- [ ] **Step 3: Coverage per function, against `main`.**

  ```sh
  uv run pytest -q --cov=custom_components/pururu --cov-report=json:<scratchpad>/after.json
  ```

  In a `git archive f0d0aff` scratch copy (with `.hassfest`, `uv sync --locked`), the same command into `<scratchpad>/before.json`, then delete the copy. Compare each file's `functions` by name, `device_keys/programs.py`'s under `aspects/programs.py`:
  - no function misses more lines than before;
  - every function D3 adds (`slug`, `executable`, `_executable_only`, `_item_at` ×2, `at`, `_detected_only`, `_derived`, `_places` and `_build` of the programs aspect, `_named`, `_of`, `_detected_item`, `_detected_phase_item`, `_detected_other_item`, `counted_each`, `detected_keys`, `build_detected`, `_fixed`) misses none;
  - the total is 10, as `main`'s: `aspects/problem.py` 1, `core/vocabulary.py` 1, `outputs/alert_lights.py` 1, `outputs/dashboard.py` 2, `outputs/places.py` 3, `setup/lifecycle.py` 1, `setup/listener.py` 1 (the prototype missed exactly those).

  Write the table (file, function, before, after) into the PR text.

- [ ] **Step 4: The final whole-branch review** (opus): `git diff f0d0aff...HEAD` against this plan, the spec's Part 4, the rulings and the Review Focus. It re-runs the three snapshot diffs against `main`'s `house_ids.json` in one go (14 renamed, 62 added, nothing else moved: `iddiff_d3.py` per task, or its checks combined), and checks that no private setup is anywhere (only the spec's and the tests' made-up names). Fix every finding, minors included, each behaviour fix with a test that failed first. Commit the fixes as `pururu: D3 final review: <what> (refactor D3)` and the docs as `docs: programs, the Programs role and nested aspects in the Develop pages and CLAUDE.md (refactor D3)`; each commit ends with the two attribution lines. Push, wait until `headRefOid` equals `git rev-parse HEAD`, then add `claude-review` (the only label of the PR, Global Constraints).

- [ ] **Step 5: The review's findings, ready.** Fix every finding of Claude's review, minors included; push; wait for `headRefOid`; remove `claude-review` and add it once more to confirm. Once Claude's review is 5/5, the checks green, Sonar at 0 issues and every thread resolved: `gh pr ready`, then merge (squash). The PR text holds, by then: what D3 is, the rulings in short (the owner's two decisions marked), the manual update step (ruling 22) for PR C's "Updating to 0.2.1" guide to carry, and the coverage table. The version stays `0.2.0` (`python3 release.py check`).
