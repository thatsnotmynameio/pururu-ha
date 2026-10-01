# Refactor C: the vocabulary, and 0.2.1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Reviewed by the owner on 2026-09-30** (see "Decided by the owner"). Every count and message below was measured on a prototype of Tasks 1–5 in a scratch copy of `main` (51bc43b), then deleted; ruling 20 (the owner's) changes Task 1's number tests, so Task 1's count moves by a test or two.

**Goal:** the spec's Part 2, the vocabulary, on the final shape that D left:
- **#1 One reference form.** `key` names an entity of the same device, `device.key` one of another device, `entity:` a real entity. A reaction's `device:` + `when:` becomes `when: <device>.<key>`. A light group becomes a list of `<device>.light_<key>`. An alert's `when`, a program step and a reaction's `then` refuse a `<device>.` prefix.
- **#2 One condition vocabulary.** A hand-written alert's `is` becomes `state`, compared as text, the same rule as a reaction's `to`. `Condition.state` is text only, `Condition.equals` is code only (`no_power`), and one `trigger()` takes a `Condition`. An alert's `for` has no default.
- **#10 One meaning for `notify`.** `notify` always means where. An alert's texts are flat `message` and `done_message`, both or neither.
- **#3 #4 One time format.** `resolved.for` becomes `resolved.lasts`. `repeat` and `lasts` take any HA time period of at least one second.
- **#6–#9 The small ones.** `lights: true` becomes `lights: default`. A door's or window's `events:` becomes `event_entities:`. The top-level `events:` moves to `config: events:`. A device's, floor's and area's `name` refuses empty text.

C also:
- sets the version to **0.2.1**, the release that carries the whole refactor;
- writes the Guide page **"Updating to 0.2.1"**, which carries B4's, D2's, D3's and C's manual steps in one order;
- removes the "From 0.1.14 and before" section of `docs/concepts/programs.mdx`.

No entity ID, unique ID or generated ID changes in C: `tests/fixtures/house_ids.json` stays as it is (spec D20).

**Architecture:**
- **`core/vocabulary.py`** gains `band(value, above, below)` (strict, as HA's `numeric_state`, now shared with the detector's `Band.holds`), `parse(block, word="state")` (an alert's `state` or a reaction's `to`, plus `above`/`below`, into one `Condition`) and `Condition.equals`. `trigger(entity_id, when, *, from_, hold)` takes a `Condition` and refuses `equals`.
- **`core/resolve.py`** gains `Ref.parse(text)` and three validators: `reference` (`key` or `device.key`), `local_key` (refuses a dot: `<x> must be of this device…`) and `device_reference` (`device.key`, the dot required). The resolvers stay; only the parsing changes (A2b already built `Ref` from 0.1.23's syntax).
- **`aspects/problem.py`** owns the alert's vocabulary: `state`, `for` without a default, `TEXTS` (`message`, `done_message`) with `texts_together`, and `lights_group`, which takes a group's name only. `ProblemAlert.notify` becomes `ProblemAlert.messages`.
- **`outputs/alert_lights.py`**: `GROUP` is a list of `device_reference`; `light_ids` reads the index; `PERIOD` replaces `SECONDS`; `FOR` becomes `LASTS`.
- **`setup/schema.py`**: `events` moves under `config`; a device's `name` is `TEXT`. **`outputs/places.py`**: a floor's and an area's `name` is `TEXT`. **`features/opening/`**: `EVENT_ENTITIES`.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3, voluptuous, pytest (pytest-homeassistant-custom-component), ruff, mypy strict, uv, docs.page (pnpm).

**Spec:** `docs/superpowers/specs/2026-09-29-yaml-contract-coherence-design.md`:
- Part 2, whole: #1, #2, #10, #3 #4, #6–#9 (#5 was solved by D);
- "The whole contract, 0.2.0": every line marked `(C)`;
- "Compatibility", "PRs" (row C and the paragraph "C, the vocabulary"), "Tests" #4;
- D19 (C sets 0.2.1), D20 (no ID changes), D13 (no compatibility code).

The plans of D1–D3 (`docs/superpowers/plans/2026-09-30-refactor-d{1,2,3}-*.md`) and their Rulings hold, unless a ruling here says otherwise.

**Base:** `main` at 51bc43b (D3 merged, #60). Branch `refactor/c-vocabulary`, cut from it, in a worktree. At the base, `uv run pytest -q` gives **1379 passed**. The names this plan consumes, as merged:
- `core.vocabulary`: `Condition(state, above, below)`, `NO_READING`, `_number`, `period`, `trigger(block, entity_id)`;
- `core.resolve`: `Ref(device, key)`, `Ref.text`, `Target`, `Index`, `find`;
- `core.feature`: `TEXT`, `state_text`, `finite_float`;
- `aspects.problem`: `ALERT`, `SCHEMA`, `NOTIFY`, `shared`, `lights_group`, `ProblemAlert`, `Alert`;
- `aspects.alerts`: `_build`, `_settings`, `_notify`, `ALERTS`;
- `outputs.alert_lights`: `SECONDS`, `GROUP`, `FOR`, `light_ids(settings, devices)`, `_group_refused`, `check`;
- `device_keys.reactions`: `REACTION`, `_consistent`, `_refused`, `_watched`, `triggers`;
- `features.opening`: `SCHEMA`.

## Global Constraints

- Version: `custom_components/pururu/manifest.json` stays `0.2.0` until Task 6, which sets **`0.2.1`**. `python3 release.py check` passes at every commit. Before merging, check `main` and the releases: no other PR may set 0.2.1 (two PRs bumping to one version: the second never ships).
- `uv run pytest` green at every commit: ruff, ruff format, mypy strict, hassfest, the layer table, the quality scale (`tests/test_code.py`).
- **No ID changes.** `tests/fixtures/house_ids.json` is never touched. `tests/fixtures/house.yaml` is rewritten in each task's syntax, and `tests/test_ids.py` must pass unchanged against the same snapshot after every task. `PURURU_UPDATE_IDS` is never set.
- **No compatibility code** (D13): no alias, no deprecation issue, no migration. An old key is refused by voluptuous with its path, or, where the plan says so, with a message that names the new form. Each old form gets one test, its id ending in `as before 0.2.1`.
- Layers (`tests/test_code.py`): `core/resolve.py` and `core/vocabulary.py` import only `core/`, `const` and Home Assistant; `outputs/places.py` imports `core.feature` (`TEXT`), as the L3 row allows. No new allowance.
- Per-function coverage not lower than `main`'s (51bc43b: 10 lines missed in all; the prototype of Tasks 1–5 missed 9, `Condition._is`' line now covered). Measured the same way on both: `uv run pytest --cov=custom_components/pururu --cov-report=json:<file>`, `main`'s in a `git archive 51bc43b` scratch copy. Every new function is fully covered.
- Commits end with exactly:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM
  ```
- Never any `git stash` (shared with other sessions), and never checkout, restore or reset the worktree's files. A RED against the old code runs in a scratch copy:
  - `git archive HEAD | tar -x -C <scratchpad>/<dir>`;
  - copy `.hassfest` and the new tests in, then `uv sync --locked` there;
  - run them there, then delete the dir (`/tmp` is a small shared tmpfs).
- **Rewrites by script, then by hand.** Where a step says "a short Python script", it is written in the scratchpad (never committed), does exact or regex replacements, and prints each rule's count; a rule that matches nothing fails the script.
- **Docs in the same task** (CLAUDE.md, "Keep it true"): each task updates the Guide pages its change touches, and the page tests that read a page's YAML (`test_alert_lights.py`, `test_alert2.py`, `test_notifications.py`, `test_presets.py`, `test_events.py`) must pass. `{` and `<` outside code are JSX in MDX: keep them in backticks. `pnpm docs:check` passes at the end of Tasks 5, 6 and 7.
- Every review finding fixed, minors included; ask when in doubt.
- pururu is public: made-up names only, the ones the tests and the spec use now (`clothes_washer`/Tanquinho, `water_station`/Purificador, `greenhouse`/Estufa, `biblioteca`/Biblioteca, `porta_frente`, `janela_quarto`, `cotton`/Algodão, `warming`/Aquecendo…); nothing from any private setup, in the plan, code, tests, docs, commits or PR text.
- The PR flow (no Greptile; a PR merges on Claude's review at 5/5, green checks, Sonar at 0 issues and every review thread resolved):
  1. After Task 1: push, open a **draft** PR `pururu: refactor C, the vocabulary (0.2.1)`.
  2. Each later task: push. No review label per task.
  3. Task 7's final review: once its fixes are pushed, wait until `gh pr view <n> --json headRefOid -q .headRefOid` equals `git rev-parse HEAD`, then add `claude-review`, **once**. Fix every finding; after the fixes are pushed (and `headRefOid` matches), remove the label and add it again once to confirm. No other label.
  4. If `gh pr edit --add-label` fails with a GraphQL error: `gh api -X POST repos/thatsnotmynameio/pururu-ha/issues/<n>/labels -f 'labels[]=claude-review'`.
  5. Once Claude's review is 5/5, the checks green, Sonar at 0 issues and every thread resolved: `gh pr ready`, then merge (squash). The Release workflow then tags v0.2.1.

## Review Focus

The places most likely to bite a person updating, each with the test that pins it:

1. **A number in `state`.** An alert's `state: 1` (or `1.0`) and a reaction's `to: 1` are refused at the configuration, at their paths (ruling 20): today's `is: 1` matched the power mirror's `1.0`, and a text `1` never would, so a silent never-firing alert becomes an error. A quoted `"1.0"` compares as text; YAML's booleans still read `on`/`off`. Pinned: `test_a_number_in_state_is_refused`, `test_a_quoted_number_in_state_compares_as_text`, the reaction's `to: 1` refusal, `test_holds` (Task 1).
2. **Every old form refused, at its path.** `is:`, an alert's `notify: {message, done_message}`, `device:` + `when:`, a light group as a map, `lights: true`/`false`, `resolved.for`, a door's `events:`, a top-level `events:`: each is refused, none silently ignored. Pinned: one test each, ids `… as before 0.2.1` (Tasks 1–5).
3. **References across devices.** `when: <device>.<key>` resolves on the named device, its own device written out included (accepted, as `device: <own>` was), and the reaction's own statistic is still refused either way. A light group's member must be a `lights` entity: a switch of the same name, a key without its `light_` namespace, or a member without its device is refused. Pinned: `test_valid_reaction_is_accepted[own device named]`, `test_a_reaction_on_its_own_counter_is_refused[named]`, `test_invalid_alert_lights_are_refused` (the six member cases), `test_a_reference_is_refused` (Task 2).
4. **Texts both or neither.** A hand-written or ready-made alert with `message` alone, or `done_message` alone, is refused (`an alert needs message and done_message, or neither`); a ready-made alert's own texts still replace both defaults; only the user's own texts ask for Alert2 (`… has a message, but Alert2 isn't set up to deliver it`). Pinned: `test_invalid_texts_are_refused`, `test_presets.py`'s `a message without done_message` and `a done_message without message`, `test_texts_replace_the_default_texts`, `test_ones_own_texts_without_alert2_are_an_error` (a condition and an elapsed time; Task 3, renamed in fix round 1).
5. **Time periods and their floor.** `repeat` and `lasts` take `{minutes: 1}`, `"00:02:00"` or `1.5`, and refuse `0`, `{seconds: 0}` and anything under a second (a `repeat` of 0 would be a busy loop). Pinned: `test_valid_alert_lights_are_accepted[periods as HA writes them]`, `[a second and a half]`, `test_invalid_alert_lights_are_refused[repeat zero]`, `[repeat 0 seconds]`, `[repeat under a second]`, `[lasts zero]` (Task 4).

## Rulings

Where the spec is silent, or the owner decided, decided here:

1. **`Ref.parse(text)`** is a classmethod of `Ref` (`text.rpartition(".")`): `"washer.appliance_running"` → `Ref("washer", "appliance_running")`, `"appliance_running"` → `Ref(None, "appliance_running")`, and `Ref.parse(r.text) == r`. The validated block keeps the text as written; every reader parses it.
2. **The three validators** (`core/resolve.py`), each `cv.slug` on each part:
   - `reference`: `key` or `device.key`; anything else (`washer.`, `.key`, `a.b.c`) is `<x> is neither an entity key nor <device>.<key>`. Used by a reaction's `when`.
   - `local_key`: refuses any dot with `<x> must be of this device: its entity key, without <device>. or <domain>.` (the spec's wording, with a hint that also covers an entity ID written by mistake, as `switch.greenhouse_sprinkler`). Used by an alert's `when`, a program step's action and a reaction's `then`.
   - `device_reference`: a `reference` with the dot required, else `<x> needs its device: <device>.<x>`. Used by a light group's members.
3. **A reaction's `when: <its own device>.<key>` is accepted** (Open #2): it resolves to the same target as `<key>`, as 0.1.23's `device: <own>` did, and the own-statistic rule applies to both forms (`reactions: <r>: <key> is its own statistic`, the key without the device, so the two forms give one text).
4. **The refusals keep their texts**, only their source changes: `device <d>: reactions: <r>: device <x> is not in devices`, `… <key> is not an entity key of device <x>`, `reactions: <r>: <key> is not an entity key of this device`. `a reaction's device goes with when` goes with `device`.
5. **A light group** is a list of `device_reference`, at least one, no duplicate (`a light is listed twice`). `check` refuses a member whose device isn't in `devices` (`config.alerts.lights.groups: <g>: device <d> is not in devices`) or that isn't a `lights` entity (`config.alerts.lights.groups: <g>: <d>.<key> is not a light`; `find`'s target must have `builder == "lights"`). `light_ids(settings, index)` reads each member's unique ID from the index; `check` already found it there.
6. **`Condition.state` is `str | None`**; `equals: float | None` compares a reading as a number, for `no_power` only (`Condition(equals=0.0)`). `holds` checks `state`, then the number (`equals`, then `band`). Its rules for no reading and restored states don't change.
7. **`parse(block, word="state")`** reads `block[word]` (an alert's `state`, a reaction's `to`) and `above`/`below`; a reaction's `from` and `for` are `trigger()`'s `from_` and `hold`. The validators stay where they are: `_one_condition` in `aspects/problem.py`, `_state_consistent` in `device_keys/reactions.py`.
8. **`trigger(entity_id, when, *, from_=None, hold=None) -> dict[str, Any]`**: one trigger, a dict, as today (the spec's sketch says a list; a dict keeps both callers' lists as they are). `equals` raises `ValueError("a trigger takes a state or a band, not equals")`: a programming error, never a configuration one.
9. **An alert's `state` uses `state_text`**, as a reaction's `to`: `on`/`off` and YAML's booleans read as `on`/`off`, any other value as its text (`1` → `"1"`, `1.0` → `"1.0"`). An alert refuses `to` and a reaction refuses `state` as unknown keys (`'to' is an invalid option…`), at their paths: no message of their own (Open #9).
10. **An alert's `for` has no default** (#9): absent, `Alert(hold=None)` turns on at once, as `timedelta(0)` did. A ready-made alert's `for` stays its preset's.
11. **Texts** (`aspects/problem.py`): `TEXTS = ("message", "done_message")`, two optional `TEXT` keys in `shared()`, and `texts_together` after each alert schema (the hand-written `ALERT`'s `vol.All`, and `alerts._settings`' `vol.All`). `ProblemAlert.messages` (was `notify`) is `{message, done_message}` or `None`; Alert2's file reads it. The log becomes `<entity> has a message, but Alert2 isn't set up to deliver it`; the Repairs issue `alert2_not_included`'s description says "each alert with `message` and `done_message`" (en, pt-BR).
12. **`lights`** takes a group's name only. `true`/`false` are refused with `lights names a group of config.alerts.lights.groups, such as default; absent, the alert borrows none` (Open #5). `DEFAULT_ALERT_LIGHTS` stays: the check's "there is no default group" names it.
13. **`PERIOD = vol.All(cv.positive_time_period, vol.Range(min=timedelta(seconds=1)))`** for `repeat` and `lasts` (spec #4). The defaults are written `repeat: {seconds: 15}` (unchanged) and `lasts: {minutes: 2}` (same 120 s).
14. **`config: events:`**: `events.CONF_EVENTS` moves into `config`'s schema, with its default `[]`; `events.async_step` reads `built.house[config][events]`. The tests' helpers keep their `events=` keyword, which now writes `config: events:` (merged with `config=`).
15. **`event_entities`** is `features/opening/EVENT_ENTITIES`; `features/opening/events.py` keeps its name (it is the module of the event entities, not of pururu's bus events).
16. **Names**: `schema._device`, `places.FLOOR_SCHEMA`, `places.AREA_SCHEMA` take `TEXT` (`cv.string`, `vol.Strip`, at least one character). A name with spaces around it is stored without them (Open #11).
17. **The Guide page "Updating to 0.2.1"** is `docs/getting-started/updating-to-0.2.1.mdx`, in the sidebar's "Getting started" after "Install" (Open #7), linked from `install.mdx`. It carries every manual step of the refactor in one order (Task 6), and says which history restarts.
18. **Old version notes go** (Open #6; spec "Compatibility"): "From 0.1.14 and before" (`concepts/programs.mdx`), "Before pururu 0.1.5" (`concepts/entity-ids.mdx`), "pururu 0.1.11 and earlier" (`concepts/alerts.mdx`), "pururu 0.1.21 and earlier" (`concepts/notifications.mdx`). The troubleshooting page keeps its refusals of old forms, worded "as before 0.2.1".
19. **The fixture** (`tests/fixtures/house.yaml`) follows each task's syntax; its IDs never change. After Task 5 it is the spec's "whole contract" in shape: `state:`, `message`/`done_message`, `lights: default`, groups as lists, `when: clothes_washer.appliance_running`, `event_entities:`, `config: events:`.
20. **A number in `state` (an alert's) or `to` (a reaction's) is refused** (owner, 2026-09-30; replaces Open #4's recommendation). pururu can't tell, at the configuration, which entity shows `1` as `1.0`, so any YAML number there is refused, at its path, with `<word>: YAML reads it as the number <value>: compare a reading with above or below, or quote the state as the entity shows it ("1.0")` (`<word>` is `state` or `to`, `<value>` as YAML reads it, not as written: `state: YAML reads it as the number 1: …`; YAML reads `12:30` as 750 and `1.50` as 1.5, and the loader keeps no text, so the message says it's YAML's reading (fix round 1)). YAML's booleans still read as `on`/`off` (check `bool` before numbers: `bool` is an `int` in Python). A quoted number (`state: "1.0"`) is text and compares as text. The validator sits next to `state_text` in `core/feature.py` (or in `core/vocabulary.py`, where the implementer finds it cleaner), used by an alert's `state` and a reaction's `to`/`from`. Task 1 owns it: its number tests become `test_a_number_in_state_is_refused` (an int and a float, the message, the path) and `test_a_quoted_number_in_state_compares_as_text` (`"1.0"` on with the power at `1`), and a reaction's `to: 1` gets the same refusal test. The Guide's alerts and reactions pages, troubleshooting and the "Updating to 0.2.1" page quote the message; the guide's `is → state` step says to quote a number or use `above`/`below`, and that YAML reads some unquoted values as numbers (`12:30` is 750, `1.50` is 1.5): quote them.
21. **A light group's member that isn't a `lights` entity is refused** (owner, 2026-09-30, ruling 5's check kept): 0.1.23 never checked it, so the "Updating to 0.2.1" page says so in the light groups' step, quoting `config.alerts.lights.groups: <g>: <d>.<key> is not a light`.

## Decided by the owner (2026-09-30)

The owner chose: **1, one PR**; **4, refuse a number in `state`** (ruling 20, not the recommendation below); **the light-group member check (ruling 5): refuse, and say it in the guide**; **6, remove all four notes**. The controller ruled the rest as recommended (2, 3, 5, 7–11). The recommendations, as written before the owner's review:

1. **One PR or two.** C is ~1060 changed lines of code and tests (37 files) plus ~20 Guide pages and the new guide: smaller than D3. **Recommend one PR, seven tasks**: the guide's text quotes every task's final messages, and the version bump belongs with the guide. If the owner prefers two: C1 = Tasks 1–5 (stays 0.2.0, each task with its pages), C2 = Tasks 6–7 (the guide, 0.2.1, the Develop pages).
2. **`when: <own device>.<key>` in a reaction.** **Recommend accept** (ruling 3): 0.1.23 accepted `device: <own>`, the tests pin it, and refusing it adds a rule for no gain. Alternative: refuse it with "write `<key>`" for one form per meaning.
3. **`local_key`'s message.** The spec says `<x> must be of this device`. **Recommend** `<x> must be of this device: its entity key, without <device>. or <domain>.`: with the bare text, `turn_on: switch.greenhouse_sprinkler` (an entity ID written by mistake) would read as if `switch` were a device.
4. **`state: <number>` on the power mirror.** The spec decides text (`state: 1` matches `1`, not `1.0`), and the mirror shows `1.0`, so an old `is: 0`/`is: 1` on `appliance_power` would never hold once renamed. **Recommend keep the spec's rule** and say it in three places: the alerts page, the guide's `is → state` step ("a number: `above`/`below`, or the state as the entity shows it, `"0.0"`"), and the troubleshooting page. No code catches it (pururu can't know what a state looks like). **Owner: refuse instead (ruling 20).**
5. **`lights: true`/`false`.** **Recommend a message of its own** (ruling 12) over `cv.slug`'s `invalid slug True (try true)`, which would suggest `true` is a group's name.
6. **Old version notes.** The spec removes only "From 0.1.14 and before"; its Compatibility section says no "From 0.1.x" sections. **Recommend removing all four** (ruling 18): the guide starts from 0.1.23, past every one of them.
7. **Where the guide lives.** **Recommend `docs/getting-started/updating-to-0.2.1.mdx`**, after "Install" in the sidebar, linked from Install's step 1 (HACS offers the update there). Alternative: the "Reference" group.
8. **D3's note: executable programs' history.** **Recommend the guide only** (its step "What starts over" and the restart step say that the scripts, sensors, totals and meters of executable programs restart under `program_executable_<key>`), and no sentence in `concepts/programs.mdx`: such a sentence is a version note, which ruling 18 removes everywhere else.
9. **An alert's `to` and a reaction's `state`.** The spec says each refuses the other's word. **Recommend voluptuous' own refusal** (`'to' is an invalid option for 'pururu', check: …->to`), which names the key and its path, over a message of their own.
10. **The spec's status.** **Recommend** Task 7 sets the spec's status line to "done (0.2.1)" and marks "Not in 0.2.0" as 0.2.2's; nothing else in the spec changes.
11. **Names stripped of spaces.** `TEXT` strips: a floor named `" Térreo"` becomes `Térreo`, and pururu renames it in HA once. **Recommend accept**: every other `name` already does this.

## Tasks

1. Conditions: `band`, `parse`, `Condition.equals`, `trigger(Condition)`; an alert's `is` → `state`; `no_power` → `equals`; an alert's `for` without default. Draft PR.
2. References: `Ref.parse`, `reference`, `local_key`, `device_reference`; a reaction's `when: <device>.<key>`; light groups as lists; `local_key` on an alert's `when`, program steps and `then`.
3. `notify` means where: an alert's flat `message`/`done_message`; `ProblemAlert.messages`; Alert2's texts.
4. Time and `lights`: `resolved.lasts`; `repeat` and `lasts` as periods of at least a second; `lights: default`.
5. The small ones: `event_entities`, `config: events:`, names that refuse empty text.
6. The Guide page "Updating to 0.2.1"; the old version notes go; version 0.2.1.
7. The Develop pages, CLAUDE.md, the spec's status, coverage, the final review, ready.

Expected test counts (measured on the prototype, from 1379 at the base): Task 1 **1403**, Task 2 **1425**, Task 3 **1427**, Task 4 **1433**, Task 5 **1439**, Task 6 **1442** (the guide's test); Task 7 adds none but what its review finds.

---
### Task 1: One condition vocabulary: `state`, `equals`, `parse`, `band`, `trigger(Condition)`

An alert's `is` becomes `state`, compared as text, by the same rule as a reaction's `to`. `Condition` is the one parsed form, `band` the one numeric rule, `trigger` the one HA trigger builder. An alert's `for` loses its default.

**Files:**
- Modify `custom_components/pururu/core/vocabulary.py` (`band`, `Condition`, `parse`, `trigger`).
- Modify `custom_components/pururu/features/cycle/program/schema.py` (`Band.holds` calls `band`).
- Modify `custom_components/pururu/features/appliance/alerts.py` (`no_power`: `Condition(equals=0.0)`).
- Modify `custom_components/pururu/aspects/problem.py` (`state`, `for`), `aspects/alerts.py` (`_build`, the example), `aspects/notifications.py` and `device_keys/reactions.py` (`trigger`).
- Modify `tests/test_vocabulary.py` (rewritten), `tests/test_alerts.py`, `tests/test_reactions.py`, and every test's alert block (`"is":` → `"state":`, by script): `test_alerts.py`, `test_alert_lights.py`, `test_checks.py`, `test_presets.py`, `test_detected_programs.py`, `test_program_entities.py`; `tests/fixtures/house.yaml`.
- Modify `docs/concepts/alerts.mdx`, `docs/features/door.mdx`, `docs/reference/configuration.mdx`, `docs/reference/troubleshooting.mdx`, `docs/develop/writing-a-feature.mdx` (the `is` lines).

**Interfaces** (produced):

```python
# core/vocabulary.py
def band(value: float, above: float | None, below: float | None) -> bool
@dataclass(frozen=True, kw_only=True)
class Condition:
    state: str | None = None
    above: float | None = None
    below: float | None = None
    equals: float | None = None          # code only: no_power
    def holds(self, state: State | None) -> bool | None
def parse(block: Mapping[str, Any], word: str = "state") -> Condition
def trigger(entity_id: str | None, when: Condition, *, from_: str | None = None,
            hold: timedelta | None = None) -> dict[str, Any]   # ValueError on equals
```

- [ ] **Step 0: Branch.** In a new worktree cut from `main` at 51bc43b, on branch `refactor/c-vocabulary`: `git log -1 --format=%h` shows `51bc43b`, then `uv sync --locked`, then `uv run pytest -q`. Expected: `1379 passed`.

- [ ] **Step 1: The failing tests.**
  - `tests/test_vocabulary.py`, rewritten whole:

    ```python
    """The vocabulary: a Condition, the band it reads, its trigger, and a period as HA reads it."""

    from datetime import timedelta
    from typing import Any

    from homeassistant.core import HomeAssistant, State
    import pytest

    from helpers import module

    ENTITY = "binary_sensor.door"


    def vocabulary(ha: HomeAssistant) -> Any:
        return module("core.vocabulary")


    def condition(ha: HomeAssistant, **fields: Any) -> Any:
        return vocabulary(ha).Condition(**fields)


    def trigger(ha: HomeAssistant, when: Any, **kwargs: Any) -> dict[str, Any]:
        return vocabulary(ha).trigger(ENTITY, when, **kwargs)


    # --- band ---------------------------------------------------------------------


    @pytest.mark.parametrize(("value", "above", "below", "expected"), [
        pytest.param(5, 4, None, True, id="above"),
        pytest.param(4, 4, None, False, id="above is strict"),
        pytest.param(5, None, 6, True, id="below"),
        pytest.param(6, None, 6, False, id="below is strict"),
        pytest.param(5, 4, 6, True, id="between"),
        pytest.param(7, 4, 6, False, id="out of the band"),
        pytest.param(-1e9, None, None, True, id="no bound"),
    ])
    def test_band_is_strict_as_numeric_state(ha: HomeAssistant, value: float, above: float | None,
                                             below: float | None, expected: bool) -> None:
        assert vocabulary(ha).band(value, above, below) is expected


    # --- holds --------------------------------------------------------------------


    @pytest.mark.parametrize(("fields", "reading", "expected"), [
        pytest.param({"state": "1"}, "1", True, id="state is text"),
        pytest.param({"state": "1"}, "1.0", False, id="1 is not 1.0"),
        pytest.param({"state": "on"}, "unavailable", None, id="no reading"),
        pytest.param({"state": "unavailable"}, "unknown", True, id="about no reading"),
        pytest.param({"above": 50}, "51", True, id="above"),
        pytest.param({"above": 50}, "on", None, id="above on no number"),
        pytest.param({"equals": 0.0}, "0.0", True, id="equals is a number"),
        pytest.param({"equals": 0.0}, "0", True, id="equals 0 is 0.0"),
        pytest.param({"equals": 0.0}, "0.5", False, id="equals only that number"),
    ])
    def test_holds(ha: HomeAssistant, fields: dict[str, Any], reading: str,
                   expected: bool | None) -> None:
        assert condition(ha, **fields).holds(State("sensor.x", reading)) is expected


    def test_a_missing_state_is_unavailable(ha: HomeAssistant) -> None:
        assert condition(ha, state="unavailable").holds(None) is True
        assert condition(ha, above=1).holds(None) is None


    def test_a_restored_state_is_no_reading(ha: HomeAssistant) -> None:
        restored = State("sensor.x", "unavailable", {"restored": True})
        assert condition(ha, state="unavailable").holds(restored) is None


    # --- parse --------------------------------------------------------------------


    def test_an_alerts_state_and_a_reactions_to_are_one_condition(ha: HomeAssistant) -> None:
        """state: 1 in an alert and to: 1 in a reaction hold for the same states."""
        parse = vocabulary(ha).parse
        assert parse({"state": "1"}) == parse({"to": "1", "from": "0"}, "to") == condition(ha, state="1")
        assert parse({"above": 5, "below": 9}) == condition(ha, above=5, below=9)


    # --- trigger ------------------------------------------------------------------


    def test_a_state_without_from_adds_not_from_unavailable_unknown(ha: HomeAssistant) -> None:
        assert trigger(ha, condition(ha, state="on")) == {
            "trigger": "state", "entity_id": ENTITY,
            "not_from": ["unavailable", "unknown"], "to": "on",
        }


    def test_from_replaces_not_from(ha: HomeAssistant) -> None:
        assert trigger(ha, condition(ha, state="on"), from_="off") == {
            "trigger": "state", "entity_id": ENTITY, "from": "off", "to": "on",
        }


    @pytest.mark.parametrize(("fields", "expected"), [
        pytest.param({"above": 10}, {"trigger": "numeric_state", "entity_id": ENTITY, "above": 10},
                     id="above only"),
        pytest.param({"below": 20}, {"trigger": "numeric_state", "entity_id": ENTITY, "below": 20},
                     id="below only"),
        pytest.param({"above": 10, "below": 20},
                     {"trigger": "numeric_state", "entity_id": ENTITY, "above": 10, "below": 20},
                     id="above and below"),
    ])
    def test_above_or_below_gives_numeric_state(
            ha: HomeAssistant, fields: dict[str, Any], expected: dict[str, Any]) -> None:
        assert trigger(ha, condition(ha, **fields)) == expected


    def test_hold_becomes_for_as_a_period(ha: HomeAssistant) -> None:
        assert trigger(ha, condition(ha, state="on"), hold=timedelta(minutes=5)) == {
            "trigger": "state", "entity_id": ENTITY,
            "not_from": ["unavailable", "unknown"], "to": "on", "for": "00:05:00",
        }


    def test_equals_is_refused_by_a_trigger(ha: HomeAssistant) -> None:
        """equals is code's only (no_power): no YAML writes it, no automation compares with it."""
        with pytest.raises(ValueError, match="a trigger takes a state or a band, not equals"):
            trigger(ha, condition(ha, equals=0.0))


    # --- period -------------------------------------------------------------------


    def test_period_of_whole_seconds(ha: HomeAssistant) -> None:
        assert vocabulary(ha).period(timedelta(hours=1, minutes=2, seconds=3)) == "01:02:03"


    def test_period_of_a_fraction_of_a_second(ha: HomeAssistant) -> None:
        assert vocabulary(ha).period(timedelta(seconds=1, microseconds=500000)) == "00:00:01.500000"


    def test_period_of_a_negative_value(ha: HomeAssistant) -> None:
        assert vocabulary(ha).period(timedelta(seconds=-5)) == "-00:00:05"
    ```

  - Every test's alert block, by a short Python script over `tests/*.py`: `"is":` → `"state":` and `**{"is": ` → `**{"state": ` (counts: `test_alerts.py` 10, `test_checks.py` 6, `test_program_entities.py` 3, `test_detected_programs.py` 2, `test_presets.py` 1, `test_alert_lights.py` 1). In `tests/fixtures/house.yaml`, `stuck`'s `is: wringing` → `state: wringing`.
  - `tests/test_alerts.py`, by hand:
    - `from helpers import …` gains `module`;
    - in `test_invalid_alert_is_refused`, the two `an alert needs is, …` reasons become `an alert needs state, or above and/or below, not both`, the id `is and above` becomes `state and above`, and before the `above not lower than below` param:

      ```python
          pytest.param({"name": "X", "when": "switch_sprinkler", "to": "on"},
                       "'to' is an invalid option for 'pururu', check: "
                       "pururu->devices->dummy_washer->alerts->overload->to", id="a reaction's to"),
          pytest.param({"name": "X", "when": "switch_sprinkler", "is": "on"},
                       "'is' is an invalid option for 'pururu', check: "
                       "pururu->devices->dummy_washer->alerts->overload->is", id="is, as before 0.2.1"),
      ```

    - `test_a_number_in_is_compares_as_a_number` and `test_a_number_in_is_holds_its_state_without_a_reading` are replaced by:

      ```python
      @pytest.mark.parametrize(("written", "expected"), [
          pytest.param(1, "off", id="1 is not the mirror's 1.0"),
          pytest.param("1.0", "on", id="as the mirror shows it"),
          pytest.param(1.0, "on", id="a float reads as its text"),
      ])
      async def test_a_number_in_state_compares_as_text(ha: HomeAssistant, written: Any, expected: str) -> None:
          """state is text, as HA's condition: state: the power's mirror shows 1 W as 1.0."""
          assert await setup(ha, devices(one={"name": "One", "when": "appliance_power", "state": written}))
          await fake(ha, POWER, "1")
          assert state(ha, alert("one")) == expected


      async def test_a_state_holds_its_state_without_a_reading(ha: HomeAssistant) -> None:
          assert await setup(ha, devices(one={"name": "One", "when": "appliance_power", "state": "1.0"}))
          await fake(ha, POWER, "1")
          await fake(ha, POWER, "unavailable")
          assert state(ha, alert("one")) == "on"
          await fake(ha, POWER, "2")
          assert state(ha, alert("one")) == "off"
      ```

    - before `test_without_for_it_turns_on_at_once`:

      ```python
      def test_for_has_no_default(ha: HomeAssistant) -> None:
          """Absent means at once, as a reaction's: the validated alert has no for."""
          validated = module("aspects.problem").ALERT({"name": "X", "when": "switch_sprinkler", "state": "on"})
          assert "for" not in validated
      ```

  - `tests/test_reactions.py`, in `test_invalid_reaction_is_refused`, before the `from without to` param:

    ```python
        pytest.param({"name": "X", "entity": DOOR, "state": "on"},
                     f"'state' is an invalid option for 'pururu', check: {PATH[1:]}->state",
                     id="an alert's state"),
    ```

  ```sh
  uv run pytest tests/test_vocabulary.py tests/test_alerts.py tests/test_reactions.py -n 4 -q
  ```

  Expected: `test_vocabulary.py` fails throughout (`band`, `parse`, `equals` don't exist; `trigger` takes a block); every alert set up with `state` is refused (`'state' is an invalid option`); `test_for_has_no_default` fails (`for` is `timedelta(0)`); the `an alert's state` param passes already (`state` is unknown to a reaction today). That param is a guard, not a RED.

- [ ] **Step 2: `core/vocabulary.py`.** Replace `Condition` and `trigger` (keep `NO_READING`, `period`, `_number`, the imports):

  ```python
  def band(value: float, above: float | None, below: float | None) -> bool:
      """Whether `value` is strictly above `above` and strictly below `below`, as HA's numeric_state; None is no bound."""
      return (above is None or value > above) and (below is None or value < below)


  @dataclass(frozen=True, kw_only=True)
  class Condition:
      """What makes the watched entity's state hold: a state, a band, or (code only) a number.

      `state` is text, compared as HA's condition: state compares: `1` matches
      `1`, not `1.0`. `equals` compares a reading as a number: only a ready-made
      alert's (no_power), never the YAML's, and no trigger takes it.
      """

      state: str | None = None
      above: float | None = None
      below: float | None = None
      equals: float | None = None

      def holds(self, state: State | None) -> bool | None:
          """Whether `state` holds; None when it is no reading.

          A condition on unavailable or unknown holds while the entity has no
          reading, either state or missing: a plug reconnecting passes from one to
          the other. A state HA restored for an entity not loaded yet (at start,
          during a reload) is no reading, for every condition.
          """
          if state is not None and state.attributes.get(ATTR_RESTORED):
              return None
          if self.state is not None:
              return self._is(STATE_UNAVAILABLE if state is None else state.state)
          if state is None or (value := _number(state)) is None:
              return None
          if self.equals is not None:
              return value == self.equals
          return band(value, self.above, self.below)

      def _is(self, current: str) -> bool | None:
          """`state`: no reading for other states, unless it is about no reading."""
          if self.state in NO_READING:
              return current in NO_READING
          if current in NO_READING:
              return None
          return current == self.state


  def parse(block: Mapping[str, Any], word: str = "state") -> Condition:
      """The Condition of a validated block: an alert's `state` (`word`), a reaction's `to`, or above/below."""
      return Condition(
          state=block.get(word), above=block.get("above"), below=block.get("below")
      )


  def trigger(
      entity_id: str | None,
      when: Condition,
      *,
      from_: str | None = None,
      hold: timedelta | None = None,
  ) -> dict[str, Any]:
      """The HA state or numeric_state trigger of `when` on `entity_id`: `from_` the state it leaves, `hold` its for.

      With a state and no `from_`, a state coming back from no reading doesn't
      fire: a plug reconnecting (unavailable → off) is no "turned off". A
      Condition with `equals` is code's only: no trigger takes it.
      """
      if when.equals is not None:
          raise ValueError("a trigger takes a state or a band, not equals")
      result: dict[str, Any]
      if when.state is not None:
          result = {"trigger": "state", "entity_id": entity_id}
          if from_ is not None:
              result["from"] = from_
          else:
              result["not_from"] = [STATE_UNAVAILABLE, STATE_UNKNOWN]
          result["to"] = when.state
      else:
          result = {"trigger": "numeric_state", "entity_id": entity_id}
          if when.above is not None:
              result["above"] = when.above
          if when.below is not None:
              result["below"] = when.below
      if hold is not None:
          result["for"] = period(hold)
      return result
  ```

- [ ] **Step 3: The callers.**
  - `features/cycle/program/schema.py`: import `from ....core.vocabulary import band`; `Band.holds` returns `band(value, self.above, self.below)`.
  - `features/appliance/alerts.py`: `no_power`'s `kind=Condition(equals=0.0)`.
  - `aspects/problem.py`: `_state` goes (and `finite_float` stays imported for `above`/`below`); `_one_condition` tests `"state" in alert` and says `an alert needs state, or above and/or below, not both`; in `ALERT`:

    ```python
                # Text, as a reaction's to: a number is above/below
                vol.Optional("state"): state_text,
                vol.Optional("above"): finite_float,
                vol.Optional("below"): finite_float,
                # Absent: at once
                vol.Optional("for"): cv.positive_time_period,
    ```

    `Alert.__init__`'s `hold` is `timedelta | None`, its docstring "Watch `watched` for `condition` held for `hold` (None: at once); `name` None: translated." (`_evaluate`'s `if self._hold:` already reads None as at once).
  - `aspects/alerts.py`: import `vocabulary` (`from ..core import vocabulary`); `_build` passes `condition=vocabulary.parse(alert)` and `hold=alert.get("for")`; `ALERTS`' example `"state": "on"`.
  - `aspects/notifications.py`: import `Condition` from `..core.vocabulary`; `automation`'s local `trigger` dict goes, and its triggers are

    ```python
            "triggers": [
                vocabulary.trigger(
                    entity_id, Condition(state=happening.to), from_=happening.from_
                )
            ],
    ```

  - `device_keys/reactions.py`, `triggers`' last line:

    ```python
        return [
            vocabulary.trigger(
                entity_id,
                vocabulary.parse(reaction, "to"),
                from_=reaction.get("from"),
                hold=reaction.get("for"),
            )
        ]
    ```

- [ ] **Step 4: GREEN.** `uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu && uv run pytest -q`. Expected: `1403 passed`, `test_ids.py` included (no ID moved).

- [ ] **Step 5: The pages.** Each `is` becomes `state`, and the number rule changes:
  - `docs/concepts/alerts.mdx`: the example's `is: "on"` and `is: unavailable` → `state:`. The property `is` becomes:

    ```mdx
    <Property name="state" type="state" optional>
      The state that is a problem, as text: `"on"`, `"off"`, a phase such as `wringing`, `unavailable`.

      - `on` and `off` work with or without quotes. Without quotes, YAML also reads `yes`/`true` as `on` and `no`/`false` as `off`.
      - A number is compared as text, as Home Assistant's `state` condition does: `state: 1` matches a state of `1`, not `1.0`. The appliance's power shows `1.0`. For a number, write `above`/`below`, or the state as the entity shows it (`"0.0"`).
    </Property>
    ```

    "An alert needs **either** `is` **or** `above`/`below`" and the "When an alert is on" bullets say `state`; "`is: unavailable` or `is: unknown`" → "`state: unavailable` or `state: unknown`". The `for` property says "Without it, the alert turns on at once." (unchanged).
  - `docs/features/door.mdx` (the `door_open` sentence): `` `state: "on"` ``.
  - `docs/reference/configuration.mdx`: `long_cycle`'s `is: "on"` → `state: "on"`.
  - `docs/reference/troubleshooting.mdx`: "An alert with both `state` and `above`/`below`, with neither, …"; add "An alert's `is`, as before 0.2.1: `'is' is an invalid option`. Write `state`.".
  - `docs/develop/writing-a-feature.mdx` (the `kind` bullet): "a `Condition`, as a hand-written alert's `state`/`above`/`below` (`equals`, a number, only in code: `no_power`)".

  `git grep -n -E '\bis: ["a-z0-9]|`is`' -- docs/concepts docs/features docs/reference/configuration.mdx docs/develop/writing-a-feature.mdx` returns nothing (troubleshooting and, in Task 6, the guide name the old form on purpose).

- [ ] **Step 6: Commit, push, open the draft PR.**

  ```bash
  git add -A
  git commit -m "pururu: one condition vocabulary: an alert's state, Condition.equals, trigger takes a Condition (refactor C)

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM"
  git push -u origin refactor/c-vocabulary
  gh pr create --draft --title "pururu: refactor C, the vocabulary (0.2.1)" --body-file <scratchpad>/body-c.md
  ```

  The PR text: what C is (the Goal), "This is a draft, updated at the end of each task", a Progress list of the seven tasks (Task 1 checked, with its count), and an "Updating (manual step)" section that says "Task 6's guide carries every step; the vocabulary's changes are listed there". It ends with the two attribution lines of the PR footer.

---

### Task 2: One reference form

A reaction names another device's entity as `when: <device>.<key>`. A light group is a list of `<device>.light_<key>`. An alert's `when`, a program step and a reaction's `then` refuse a `<device>.` prefix. The resolution (A2b's `find`, `Target`) doesn't change.

**Files:**
- Modify `custom_components/pururu/core/resolve.py` (`Ref.parse`, `reference`, `local_key`, `device_reference`).
- Modify `custom_components/pururu/device_keys/reactions.py` (`when`, `then`, `device` goes, `_refused`, `_watched`, `check`'s docstring).
- Modify `custom_components/pururu/aspects/problem.py` (`when`), `aspects/programs.py` (`STEP`).
- Modify `custom_components/pururu/outputs/alert_lights.py` (`GROUP`, `light_ids`, `_group_refused`, `async_step`).
- Modify `tests/test_resolve.py`, `tests/test_reactions.py`, `tests/test_checks.py`, `tests/test_alert_lights.py`, `tests/test_alerts.py`, `tests/test_programs.py`, `tests/fixtures/house.yaml`.
- Modify `docs/concepts/reactions.mdx`, `docs/concepts/alert-lights.mdx`, `docs/concepts/alerts.mdx`, `docs/concepts/programs.mdx`, `docs/reference/configuration.mdx`, `docs/reference/troubleshooting.mdx`.

**Interfaces** (produced):

```python
# core/resolve.py
class Ref:
    @classmethod
    def parse(cls, text: str) -> "Ref"        # "washer.appliance_running" -> Ref("washer", "appliance_running")
def reference(value: Any) -> str              # key or device.key
def local_key(value: Any) -> str              # key only
def device_reference(value: Any) -> str       # device.key only
# outputs/alert_lights.py
def light_ids(settings: Mapping[str, Any], index: Index) -> dict[str, list[str]]
```

- [ ] **Step 1: The failing tests.**
  - `tests/test_resolve.py`: imports `import re` and `import voluptuous as vol`; after `test_a_reference_reads_as_written`:

    ```python
    # --- the one reference form ---------------------------------------------------------------


    @pytest.mark.parametrize(("text", "device", "key"), [
        pytest.param("appliance_running", None, "appliance_running", id="this device"),
        pytest.param("washer.appliance_running", "washer", "appliance_running", id="another device"),
    ])
    def test_a_reference_parses_as_written(ha: HomeAssistant, text: str, device: str | None, key: str) -> None:
        parsed = module("core.resolve").Ref.parse(text)
        assert (parsed.device, parsed.key) == (device, key)
        assert parsed.text == text


    @pytest.mark.parametrize(("validator", "value"), [
        pytest.param("reference", "appliance_running", id="a reference, local"),
        pytest.param("reference", "washer.appliance_running", id="a reference, of another device"),
        pytest.param("local_key", "switch_plug", id="a local key"),
        pytest.param("device_reference", "lights.light_teto", id="a device's key"),
    ])
    def test_a_reference_is_accepted(ha: HomeAssistant, validator: str, value: str) -> None:
        assert getattr(module("core.resolve"), validator)(value) == value


    @pytest.mark.parametrize(("validator", "value", "message"), [
        pytest.param("reference", "washer.", "washer. is neither an entity key nor <device>.<key>",
                     id="no key"),
        pytest.param("reference", ".appliance_running",
                     ".appliance_running is neither an entity key nor <device>.<key>", id="no device"),
        pytest.param("reference", "a.b.c", "a.b.c is neither an entity key nor <device>.<key>",
                     id="two dots"),
        pytest.param("reference", "Washer.appliance_running", "invalid slug Washer", id="not a slug"),
        pytest.param("local_key", "washer.switch_plug",
                     "washer.switch_plug must be of this device: its entity key, without <device>. or <domain>.",
                     id="a local key with a device"),
        pytest.param("local_key", "Switch", "invalid slug Switch", id="a local key not a slug"),
        pytest.param("device_reference", "light_teto", "light_teto needs its device: <device>.light_teto",
                     id="a light group's member without its device"),
    ])
    def test_a_reference_is_refused(ha: HomeAssistant, validator: str, value: str, message: str) -> None:
        with pytest.raises(vol.Invalid, match=re.escape(message)):
            getattr(module("core.resolve"), validator)(value)
    ```

  - `tests/test_reactions.py`:
    - `OVERLOAD = {"name": "Sobrecarga", "when": f"{WASHER}.appliance_power", "above": 2500}`;
    - in `test_valid_reaction_is_accepted`: `own device named` is `{"name": "Teto", "when": f"{LIGHTS}.light_teto", "to": "on"}`, and `an entity the settings don't build` is `{"name": "Mês", "when": f"{WASHER}.appliance_runtime_month", "to": "1"}`;
    - in `test_invalid_reaction_is_refused`, the `device without when` param is replaced by:

      ```python
          pytest.param({"name": "X", "device": WASHER, "when": "appliance_power", "to": "on"},
                       f"'device' is an invalid option for 'pururu', check: {PATH[1:]}->device",
                       id="device and when, as before 0.2.1"),
          pytest.param({"name": "X", "when": f"{WASHER}.", "to": "on"},
                       "washer. is neither an entity key nor <device>.<key>", id="a device without a key"),
          pytest.param({"name": "X", "when": f"{WASHER}.appliance.power", "to": "on"},
                       "washer.appliance.power is neither an entity key nor <device>.<key>", id="two dots"),
          pytest.param({"name": "X", "when": "Washer.appliance_power", "to": "on"},
                       "invalid slug Washer", id="a device not a slug"),
          pytest.param({"name": "X", "at": "22:00", "then": "greenhouse.clean"},
                       "greenhouse.clean must be of this device", id="then of another device"),
      ```

      and `device not in devices` is `{"name": "X", "when": "dryer.appliance_power", "to": "on"}`, `when not of that device` is `{"name": "X", "when": f"{WASHER}.light_teto", "to": "on"}` (their messages unchanged);
    - `test_a_reaction_on_an_entity_not_created_is_not_generated`'s `month` and `test_a_reaction_on_another_device_starts_its_own_program`'s `power`: `"when": f"{WASHER}.appliance_…"`, no `"device"`;
    - `test_a_reaction_on_its_own_counter_is_refused`'s parametrize: `[{}, {"when": f"{LIGHTS}.reaction_it_triggered_total"}]`, `ids=["its device implied", "named"]` (the message stays `reactions: it: reaction_it_triggered_total is its own statistic`).
  - `tests/test_checks.py`: `a reaction's device` becomes `{"name": "X", "when": "dryer.appliance_running", "to": "on"}`, id `a reaction's other device` (same path and message); `a light group`'s config is `{"groups": {"porch": ["garagem.light_x"]}}` (same message).
  - `tests/test_alert_lights.py`:
    - `GROUPS = {"default": ["greenhouse.light_lantern"], "porch": ["varanda.light_rele"], "both": ["greenhouse.light_lantern", "varanda.light_rele"]}`;
    - the group params of `test_invalid_alert_lights_are_refused`, from `group not a slug` to `a switch, not a light`, become:

      ```python
          pytest.param(lights_block(groups={"Porch": ["varanda.light_rele"]}), "invalid slug Porch",
                       id="group not a slug"),
          pytest.param(lights_block(groups={"porch": []}), "length of value must be at least 1",
                       id="empty group"),
          pytest.param(lights_block(groups={"porch": ["varanda.light_rele", "varanda.light_rele"]}),
                       "a light is listed twice", id="a light twice"),
          pytest.param(lights_block(groups={"porch": "varanda.light_rele"}), "expected a list",
                       id="not a list"),
          pytest.param(lights_block(groups={"porch": {"varanda": ["rele"]}}), "expected a list",
                       id="a map of devices, as before 0.2.1"),
          pytest.param(lights_block(groups={"porch": ["light_rele"]}),
                       "light_rele needs its device: <device>.light_rele", id="no device"),
          pytest.param(lights_block(groups={"porch": ["garagem.light_rele"]}),
                       "config.alerts.lights.groups: porch: device garagem is not in devices",
                       id="unknown device"),
          pytest.param(lights_block(groups={"porch": ["varanda.light_teto"]}),
                       "config.alerts.lights.groups: porch: varanda.light_teto is not a light",
                       id="unknown light"),
          pytest.param(lights_block(groups={"porch": ["varanda.rele"]}),
                       "config.alerts.lights.groups: porch: varanda.rele is not a light",
                       id="a light without its namespace"),
          pytest.param(lights_block(groups={"porch": ["casa.switch_gate"]}),
                       "config.alerts.lights.groups: porch: casa.switch_gate is not a light",
                       id="a switch, not a light"),
      ```

    - `test_an_alerts_lights_must_name_a_group`'s `no default group` config and the `porch`-only config near the end of the file: `{"porch": ["varanda.light_rele"]}`.
  - `tests/test_alerts.py`, in `test_invalid_alert_is_refused`, before `when without its namespace`:

    ```python
        pytest.param({**OVERLOAD, "when": "dummy_washer.appliance_power"},
                     "dummy_washer.appliance_power must be of this device", id="when with a device"),
        pytest.param({**OVERLOAD, "when": POWER},
                     "sensor.dummy_plug_power must be of this device: its entity key, without "
                     "<device>. or <domain>.", id="when an entity ID"),
    ```

  - `tests/test_programs.py`, in `test_invalid_program_is_refused`, after `a real entity ID`:

    ```python
        pytest.param({"name": "Limpar", "sequence": [{"turn_on": "greenhouse.switch_sprinkler"}]},
                     id="a step with a device"),
    ```

  - `tests/fixtures/house.yaml`: the groups `default: [biblioteca.light_teto]`, `externas: [biblioteca.light_teto, biblioteca.light_abajur]`; `washer_done`'s `device: clothes_washer` + `when: appliance_running` → `when: clothes_washer.appliance_running`.

  ```sh
  uv run pytest tests/test_resolve.py tests/test_reactions.py tests/test_alert_lights.py tests/test_checks.py tests/test_alerts.py tests/test_programs.py tests/test_ids.py -n 4 -q
  ```

  Expected: `Ref.parse`, `reference`, `local_key`, `device_reference` don't exist; every reaction with `<device>.<key>` is refused (`invalid slug`); every list group is refused (`expected a dictionary`); `test_ids.py` fails at setup (the fixture is refused). The `a step with a device` param passes already (`cv.slug` refuses the dot): a guard.

- [ ] **Step 2: `core/resolve.py`.** Imports `from typing import Any`, `import voluptuous as vol`, `from homeassistant.helpers import config_validation as cv`. In `Ref`, before `text`:

  ```python
      @classmethod
      def parse(cls, text: str) -> "Ref":
          """The reference `text` writes: appliance_running, or washer.appliance_running."""
          device, _, key = text.rpartition(".")
          return cls(device or None, key)
  ```

  At the end of the module:

  ```python
  def reference(value: Any) -> str:
      """An entity key, of this device (appliance_running) or of another (washer.appliance_running)."""
      text = cv.string(value)
      parts = text.split(".")
      if len(parts) > 2 or not all(parts):
          raise vol.Invalid(f"{text} is neither an entity key nor <device>.<key>")
      return ".".join(str(cv.slug(part)) for part in parts)


  def local_key(value: Any) -> str:
      """An entity key of this device: an alert's when, a program's step, a reaction's then."""
      text = cv.string(value)
      if "." in text:
          raise vol.Invalid(
              f"{text} must be of this device: its entity key, without <device>. or <domain>."
          )
      return str(cv.slug(text))


  def device_reference(value: Any) -> str:
      """An entity key of a named device, as a light group's: always washer.appliance_running."""
      text = reference(value)
      if "." not in text:
          raise vol.Invalid(f"{text} needs its device: <device>.{text}")
      return text
  ```

- [ ] **Step 3: The readers.**
  - `aspects/problem.py`: `from ..core.resolve import local_key`; `ALERT`'s `vol.Required("when"): local_key`.
  - `aspects/programs.py`: `local_key` joins the `..core.resolve` import; `STEP`'s `**{vol.Optional(action): local_key for action in ACTIONS}`.
  - `device_keys/reactions.py`:
    - import `local_key, reference` from `..core.resolve`;
    - `REACTION`: `vol.Optional("device")` goes; `# An entity key: of this device, or of another (<device>.<key>)` above `vol.Optional("when"): reference`; `vol.Optional("then"): local_key`;
    - `_consistent`: the `device goes with when` rule goes;
    - `check`'s docstring: "Refuse a reaction's `when` or `then` it can't have (a schema check). `when` names an entity key of the device, or of another device (<device>.<key>), never one of the reaction's own statistics; `then` one of the device's executable programs.";
    - `_refused`, from `path` to the end:

      ```python
          path: list[Hashable] = [CONF_DEVICES, key, CONF_REACTIONS, reaction_key]
          ref = Ref.parse(reaction["when"]) if "when" in reaction else None
          target = None if ref is None else find(index, key, ref)
          if ref is not None and _own_statistic(target, key, reaction_key):
              return vol.Invalid(
                  f"reactions: {reaction_key}: {ref.key} is its own statistic", path=path
              )
          then = reaction.get("then")
          if then is not None and then not in programs.executable(devices[key]):
              return vol.Invalid(
                  f"reactions: {reaction_key}: {then} is not an executable program of "
                  "this device",
                  path=path,
              )
          if ref is None or target is not None:
              return None
          if ref.device is None:
              return vol.Invalid(
                  f"reactions: {reaction_key}: {ref.key} is not an entity key of this device",
                  path=path,
              )
          where = f"device {key}: reactions: {reaction_key}"
          if ref.device not in devices:
              return vol.Invalid(f"{where}: device {ref.device} is not in devices", path=path)
          return vol.Invalid(
              f"{where}: {ref.key} is not an entity key of device {ref.device}", path=path
          )
      ```

    - `_watched`: `target = find(index, key, Ref.parse(when))`.
  - `outputs/alert_lights.py`: import `device_reference` from `..core.resolve`; then

    ```python
    # Its lights, each <device>.light_<key>; check() checks them against the devices
    GROUP = vol.All([device_reference], vol.Length(min=1), _distinct)
    ```

    ```python
    def light_ids(settings: Mapping[str, Any], index: Index) -> dict[str, list[str]]:
        """Each group's lights, by unique ID (pururu_<device>_light_<key>): check() found each in `index`."""
        return {
            group: [
                index[ref.device][ref.key].unique_id
                for ref in map(Ref.parse, members)
                if ref.device is not None
            ]
            for group, members in settings[GROUPS].items()
        }
    ```

    ```python
    def _group_refused(
        devices: Mapping[str, Any], index: Index, group: str, members: list[str]
    ) -> vol.Invalid | None:
        """Why this group can't be: a member that isn't a device's light; None when it can."""
        where = f"config.alerts.lights.groups: {group}"
        path: list[Hashable] = [CONF_CONFIG, CONF_ALERTS, CONF_LIGHTS, GROUPS, group]
        for ref in map(Ref.parse, members):
            assert ref.device is not None  # device_reference
            if ref.device not in devices:
                return vol.Invalid(
                    f"{where}: device {ref.device} is not in devices", path=path
                )
            target = find(index, ref.device, ref)
            if target is None or target.builder != CONF_LIGHTS:
                return vol.Invalid(f"{where}: {ref.text} is not a light", path=path)
        return None
    ```

    `async_step` passes `light_ids(lights_settings, built.index)`. `ruff check --fix` drops the imports left unused (`Device`, `qualified`, `LIGHTS`, `CONF_NAME`); `Borrowable` stays.

- [ ] **Step 4: GREEN.** Expected: `1425 passed`; `test_ids.py` passes against the unchanged snapshot.

- [ ] **Step 5: The pages.**
  - `docs/concepts/reactions.mdx`: the example's `washer_done: {…, device: clothes_washer, when: appliance_running, …}` → `when: clothes_washer.appliance_running`. "An entity of another device" becomes:

    ```mdx
    ### An entity of another device

    <Property name="when" type="device.entity key">
      An entity of **another device**: its device key, a dot, and its entity key, as above: `when: clothes_washer.appliance_running`. Its own device written out (`laundry_lights.light_teto`) is the same as `light_teto`.
    </Property>
    ```

    The line "even when it listens to another device (`device: clothes_washer`)" says `(when: clothes_washer.appliance_running)`.
  - `docs/concepts/alert-lights.mdx`: the example's groups as lists (`default: [greenhouse.light_lantern]`, `externas: [greenhouse.light_lantern, varanda.light_teto]`); `groups`' property: "A map of **group name → list of lights**, each written `<device>.light_<key>`, as its entity ID ends after `light.pururu_`: `externas: [greenhouse.light_lantern, varanda.light_teto]`. A group holds at least one light, a light may be in several groups, and a group may hold lights of several devices. Relays (`switch.*` in `lights`) are welcome: they are `light_<key>` too, and only turn on and off."
  - `docs/concepts/alerts.mdx`, `when`'s property: "…It must be an entity of another feature of the device… A `<device>.` before it is refused (`<x> must be of this device…`): an alert watches its own device."
  - `docs/concepts/programs.mdx`, "Steps": "A step names an entity key of its own device (`switch_sprinkler`); a `<device>.` before it is refused."
  - `docs/reference/configuration.mdx`: the example's groups `default: [biblioteca.light_teto]`; `washer_done`'s `when: clothes_washer.appliance_running`; a general rule: "A reference to an entity is its entity key on the same device (`appliance_running`), `<device>.<key>` on another (`clothes_washer.appliance_running`: a reaction's `when`, a light group's member), or `entity:` for a real entity (a reaction's source). An alert's `when`, a program's steps and a reaction's `then` are always of their own device."
  - `docs/reference/troubleshooting.mdx`: the reaction bullet loses "`device` without `when`", and its `when` bullet reads: "A reaction whose `when` isn't an entity of its device (`reactions: door: appliance_power is not an entity key of this device`: write `<device>.appliance_power` for another device's), or of the device it names (`device laundry_lights: reactions: washer_done: light_teto is not an entity key of device clothes_washer`), or whose device isn't a device (`… device dryer is not in devices`). `device:` with `when:`, as before 0.2.1, is refused (`'device' is an invalid option`)." Add: "A light group's member that isn't `<device>.light_<key>` of a device's `lights`: `config.alerts.lights.groups: porch: varanda.rele is not a light`; a member without its device: `light_rele needs its device: <device>.light_rele`; a group written as a map of devices, as before 0.2.1: `expected a list`." and "An alert's `when`, a program step or a reaction's `then` with a dot: `<x> must be of this device: its entity key, without <device>. or <domain>.`"

  `git grep -n -E 'device: [a-z_]+, when' -- docs ':!docs/superpowers' ':!docs/ideation'` and `git grep -n -E '\{[a-z_]+: \[[a-z_, ]+\]\}' -- docs/concepts/alert-lights.mdx docs/reference` return nothing.

- [ ] **Step 6: Commit, push.**

  ```bash
  git add -A
  git commit -m "pururu: one reference form: <device>.<key>, light groups as lists, local keys refuse a device (refactor C)

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM"
  git push
  ```

  The PR text: Task 2 checked, with its count.

---
### Task 3: `notify` means where: an alert's flat `message` and `done_message`

`notify` is always **where** (a `notify.*` action or a list: `config`, a reaction, a ready-made notification). An alert's texts move out of its `notify: {message, done_message}` onto the alert itself, both or neither. An alert with texts, its own or a ready-made alert's defaults, goes to Alert2's file as today.

**Files:**
- Modify `custom_components/pururu/aspects/problem.py` (`NOTIFY` goes; `TEXTS`, `texts_together`, `shared`, `ProblemAlert.messages`, the log), `aspects/alerts.py` (`_texts`, `_settings`, `_messages`, both builds), `aspects/elapsed.py` (`messages`), `outputs/alert2_alerts.py` (`messages`).
- Modify `custom_components/pururu/translations/en.json`, `translations/pt-BR.json` (`alert2_not_included`'s description).
- Modify `tests/test_alerts.py`, `tests/test_alert2.py`, `tests/test_presets.py`, `tests/test_features.py`, `tests/fixtures/house.yaml`.
- Modify `docs/concepts/alerts.mdx`, `docs/features/appliance.mdx`, `docs/reference/configuration.mdx`, `docs/reference/troubleshooting.mdx`.

**Interfaces** (produced):

```python
# aspects/problem.py
TEXTS = ("message", "done_message")
def texts_together(alert: dict[str, Any]) -> dict[str, Any]   # both or neither
class ProblemAlert:
    messages: Mapping[str, str] | None                         # was notify
    def __init__(self, *, watched: str, priority: str, messages: Mapping[str, str] | None,
                 asks_alert2: bool = True, lights: str | None = None) -> None
# Alert(..., messages=...), ElapsedAlert(..., messages=...): the keyword renamed
# outputs/alert2_alerts.py
def alert(object_id: str, entity_id: str, friendly_name: str, priority: str,
          messages: Mapping[str, str]) -> dict[str, Any]
```

- [ ] **Step 1: The failing tests.**
  - A short Python script over `tests/test_alerts.py`, `test_alert2.py`, `test_presets.py`, with these regex rules in order (counts on the prototype):

    | Rule | Replacement | Counts |
    |---|---|---|
    | `"notify": \{\*\*NOTIFY, ("message": "[^"]*")\}` | `**TEXTS, \1` | test_alert2 1 |
    | `"notify": NOTIFY\b` | `**TEXTS` | test_alerts 5, test_alert2 8 |
    | `"notify": notify\b` | `**texts` | test_alerts 1, test_alert2 2, test_presets 2 |
    | `\bnotify = \{"message"` | `texts = {"message"` | test_alert2 2, test_presets 2 |
    | `\bWITH_NOTIFY\b` | `WITH_TEXTS` | test_alert2 22 |
    | `^NOTIFY = \{"message"` (multiline) | `TEXTS = {"message"` | test_alerts 1, test_alert2 1 |

  - `tests/test_alerts.py`, by hand: `NOTIFY_PATH` and `test_invalid_notify_is_refused` become

    ```python
    ALERT_PATH = "pururu->devices->dummy_washer->alerts->overload"
    BOTH_OR_NEITHER = "an alert needs message and done_message, or neither"


    @pytest.mark.parametrize(("texts", "reason"), [
        pytest.param({"done_message": "OK"}, BOTH_OR_NEITHER, id="no message"),
        pytest.param({"message": "X"}, BOTH_OR_NEITHER, id="no done_message"),
        pytest.param({**TEXTS, "message": " "},
                     f"length of value must be at least 1 for dictionary value '{ALERT_PATH}->message'",
                     id="empty message"),
        pytest.param({"notify": TEXTS},
                     f"'notify' is an invalid option for 'pururu', check: {ALERT_PATH}->notify",
                     id="notify: {message, done_message}, as before 0.2.1"),
        pytest.param({**TEXTS, "notify": "notify.mobile_app_phone"},
                     f"'notify' is an invalid option for 'pururu', check: {ALERT_PATH}->notify",
                     id="notify: where, which Alert2's notifier says"),
    ])
    async def test_invalid_texts_are_refused(ha: HomeAssistant, caplog: pytest.LogCaptureFixture,
                                             texts: dict[str, Any], reason: str) -> None:
        assert not await setup(ha, devices(overload={**OVERLOAD, **texts}))
        errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
        assert any(reason in message for message in errors), errors
    ```

    and the renames: `test_notify_texts_are_attributes` → `test_the_texts_are_attributes`; `test_without_notify_there_are_no_texts` → `test_without_texts_there_are_none` (docstring "Only an alert with message and done_message carries what to tell."); `NOTIFY_ERROR = "has a message, but Alert2 isn't set up to deliver it"`.
  - `tests/test_presets.py`: `all set`'s block is `{"offline": {"for": {"minutes": 1}, "priority": "high", "message": "m", "done_message": "d"}}` (as today, the texts flat); `incomplete notify` is replaced by

    ```python
        pytest.param({"offline": {"message": "m"}}, "an alert needs message and done_message, or neither",
                     id="a message without done_message"),
        pytest.param({"offline": {"notify": {"message": "m", "done_message": "d"}}},
                     "'notify' is an invalid option", id="notify: {message, done_message}, as before 0.2.1"),
    ```

    `test_notify_replaces_the_default_texts` → `test_texts_replace_the_default_texts`; `NOTIFY_ERROR` as in `test_alerts.py`; `test_a_notify_of_ones_own_without_alert2_is_an_error` → `test_texts_of_ones_own_without_alert2_is_an_error`.
  - `tests/test_alert2.py`: the module docstring "…one per alert with texts…"; `test_an_alert_with_notify_is_an_alert2_alert` → `test_an_alert_with_texts_is_an_alert2_alert`; the param id `without notify` → `without texts`; `test_the_file_is_an_empty_list_without_notify` → `…_without_texts`; `test_without_alerts_with_notify_there_is_no_issue` → `test_without_alerts_with_texts_there_is_no_issue`.
  - `tests/test_features.py`, `test_every_alert_takes_the_shared_keys`: `assert set(shared) == {"priority", "message", "done_message", "lights"}`, and the ready-made settings are read through the `vol.All`:

    ```python
                # vol.All(schema, problem.texts_together)
                ready_made = schema_keys(alerts._settings(preset).validators[0])
    ```

  - `tests/fixtures/house.yaml`, `stuck`: `notify: {message: Travada!, done_message: Destravou.}` → `message: Travada!` and `done_message: Destravou.` on two lines.

  Expected RED: every alert with flat texts is refused (`'message' is an invalid option`), `test_every_alert_takes_the_shared_keys` (`notify` in the keys), `test_ids.py` (the fixture refused).

- [ ] **Step 2: `aspects/problem.py`.**
  - The module docstring: "…With `message` and `done_message`, it also says what to tell; Alert2 does the telling, reading its attributes. pururu sends nothing."
  - `NOTIFY` is replaced by

    ```python
    # What an alert tells, for Alert2 to deliver: both or neither
    TEXTS = ("message", "done_message")


    def texts_together(alert: dict[str, Any]) -> dict[str, Any]:
        """An alert's message and done_message: both, or neither."""
        if ("message" in alert) != ("done_message" in alert):
            raise vol.Invalid("an alert needs message and done_message, or neither")
        return alert
    ```

  - `shared`:

    ```python
    def shared(priority: str) -> dict[Any, Any]:
        """What every alert takes, hand-written or ready-made: priority, its texts, lights.

        Only the default priority differs: low for a hand-written alert, the
        ready-made alert's own for one. Its texts go together (texts_together).
        """
        return {
            vol.Optional("priority", default=priority): vol.In(PRIORITIES),
            **{vol.Optional(text): TEXT for text in TEXTS},
            vol.Optional("lights"): lights_group,
        }
    ```

  - `ALERT`'s `vol.All(…, _one_condition, texts_together)`.
  - `ProblemAlert.__init__`: the keyword `notify` → `messages`; its docstring "Watch `watched`; `messages` is what Alert2 tells (message, done_message), `lights` the group it borrows. `asks_alert2` False: its messages are a ready-made alert's default texts, not a request of the user's, so no error without Alert2."; `self._asks_alert2 = asks_alert2 and messages is not None`; `self.messages = messages`; `**(messages or {})` in the attributes.
  - `_start`'s docstring "…whether Alert2, which delivers its messages, is set up."; the log `"%s has a message, but Alert2 isn't set up to deliver it"`.
  - `Alert.__init__`: `messages: Mapping[str, str] | None`, passed on as `messages=messages`.
- [ ] **Step 3: The other readers.**
  - `aspects/elapsed.py`: `ElapsedAlert.__init__`'s `notify` → `messages`, passed on.
  - `aspects/alerts.py`: import `TEXTS`, `texts_together` from `.problem`; `_build` passes `messages=_texts(alert)`; before `_settings`:

    ```python
    def _texts(alert: Mapping[str, Any]) -> dict[str, str] | None:
        """An alert's message and done_message; None without (texts_together: both or neither)."""
        return {text: alert[text] for text in TEXTS} if TEXTS[0] in alert else None
    ```

    `_settings` returns `Callable[[Any], Any]`: `vol.All(vol.Schema({**timing, **shared(preset.priority)}), texts_together)`. `_notify` becomes

    ```python
    def _messages(
        device: Device, entity_key: str, settings: Mapping[str, Any], texts: Texts
    ) -> dict[str, str]:
        """The user's message and done_message, or this alert's default texts."""
        if (own := _texts(settings)) is not None:
            return own
        key = device.qualified(entity_key)
        return {text: texts[f"{key}_{text}"] for text in TEXTS}
    ```

    and `_build_ready_made` calls it (`messages = _messages(…)`), passes `messages=messages` to both alerts and `asks_alert2=TEXTS[0] in settings`.
  - `outputs/alert2_alerts.py`: `alert(…, messages: Mapping[str, str])` with `escaped(messages["message"])`, `escaped(messages["done_message"])`; `items` reads `entity.messages`; the docstrings say "with messages" for "with notify" (module, `_finish`: "each alert with a message logs so", `items`, `async_step`).
  - `translations/en.json`, `alert2_not_included.description`: "pururu writes an Alert2 alert for each alert with `message` and `done_message` to `{file}`, …"; `pt-BR.json`: "O pururu escreve um alerta do Alert2 para cada alerta com `message` e `done_message` em `{file}`, …".
- [ ] **Step 4: GREEN.** Expected: `1427 passed`.
- [ ] **Step 5: The pages.**
  - `docs/concepts/alerts.mdx`:
    - the intro: "pururu **detects** the problem and, with `message` and `done_message`, says what to tell.";
    - the example's `long_cycle`: `message: A máquina passou de 3 horas ligada!` and `done_message: A máquina terminou.`, flat;
    - the property `notify` is replaced by

      ```mdx
      <Property name="message, done_message" type="string" optional>
        What to tell, for Alert2 to deliver: `message` when the alert fires and `done_message` when it's resolved. Give both or neither, and neither can be empty. Without them, Alert2 leaves the alert alone. Where it's told is Alert2's, in its `defaults`: an alert has no `notify`. See [Getting notified](#getting-notified).
      </Property>
      ```

    - "Ready-made alerts": "Each one takes `for`, `priority`, `message` and `done_message`, and `lights`…"; "…texts of its own in Home Assistant's language, which `message` and `done_message` replace.";
    - "Entity": "…with `message` and `done_message`, **`message`** and **`done_message`**, which a ready-made alert always has, its own texts without them…";
    - "Getting notified": every "with `notify`" → "with `message` and `done_message`" (four places: the alerts written, the reload trigger "adding or removing them", "Only the alerts with texts are written", the log line `… has a message, but Alert2 isn't set up to deliver it`), and "**Without them**, the alert is yours to use…".
  - `docs/features/appliance.mdx` (ready-made alerts): "Each one takes `for`, `priority`, [`message` and `done_message`](/concepts/alerts#settings), which replace its texts, and [`lights`]…".
  - `docs/reference/configuration.mdx`: `long_cycle`'s two texts flat; the comment `alert2:                          # alerts with texts: see alerts`.
  - `docs/reference/troubleshooting.mdx`: "An alert's `message` without `done_message`, or the reverse (`an alert needs message and done_message, or neither`), or an empty one. An alert's `notify`, as before 0.2.1 (`'notify' is an invalid option`): write `message` and `done_message` on the alert itself." The section `### … has notify, but Alert2 isn't set up to deliver it` becomes `### … has a message, but Alert2 isn't set up to deliver it`, its log line and text with "texts" for "`notify`" ("only texts you wrote do"; "or remove `message` and `done_message` from the alert"). Every link to its anchor follows (`git grep -n 'has-notify' -- docs`).

  `git grep -n -E 'notify: \{|with `notify`|has notify' -- docs ':!docs/superpowers' ':!docs/ideation'` returns nothing outside troubleshooting's "as before 0.2.1".

- [ ] **Step 6: Commit, push.** Message: `pururu: notify means where: an alert's flat message and done_message (refactor C)`, the two attribution lines. The PR text: Task 3 checked.

---

### Task 4: One time format, and `lights: default`

`resolved.for` becomes `resolved.lasts`. `repeat` and `lasts` take any HA time period of at least one second. An alert's `lights` names a group, `default` included; `true` and `false` go.

**Files:**
- Modify `custom_components/pururu/outputs/alert_lights.py` (`PERIOD`, `LASTS`, `DEFAULTS`, the docstrings), `aspects/problem.py` (`lights_group`), `const.py` (`DEFAULT_ALERT_LIGHTS`' comment).
- Modify `tests/test_alert_lights.py`, `tests/test_checks.py`, `tests/fixtures/house.yaml`.
- Modify `docs/concepts/alert-lights.mdx`, `docs/concepts/alerts.mdx`, `docs/reference/configuration.mdx`, `docs/reference/troubleshooting.mdx`.

**Interfaces** (produced):

```python
# outputs/alert_lights.py
LASTS = "lasts"                       # was FOR = "for"
PERIOD = vol.All(cv.positive_time_period, vol.Range(min=timedelta(seconds=1)))   # was SECONDS
# aspects/problem.py
def lights_group(value: Any) -> str   # a group's name; a bool refused
```

- [ ] **Step 1: The failing tests.** `tests/test_alert_lights.py`:
  - `raised(name, priority, lights: Any = "default")`;
  - `test_without_config_every_default_applies`: `"resolved": {"turn_on": GREEN, "lasts": timedelta(minutes=2)}`;
  - `test_valid_alert_lights_are_accepted`: `resolved`'s block `{"turn_on": {"color_name": "dark green"}, "lasts": {"seconds": 5}}`, and after it

    ```python
        pytest.param({"high": {"turn_on": {}, "repeat": {"minutes": 1}},
                      "resolved": {"turn_on": {}, "lasts": "00:02:00"}}, id="periods as HA writes them"),
        pytest.param({"high": {"turn_on": {}, "repeat": 1.5}}, id="a second and a half"),
    ```

  - `test_invalid_alert_lights_are_refused`: `repeat in minutes`, `repeat zero` and `repeat not whole` are replaced by

    ```python
        pytest.param(lights_block(high={"turn_on": {}, "repeat": {"seconds": 0}}),
                     "value must be at least 0:00:01", id="repeat zero"),
        pytest.param(lights_block(high={"turn_on": {}, "repeat": 0}),
                     "value must be at least 0:00:01", id="repeat 0 seconds"),
        pytest.param(lights_block(high={"turn_on": {}, "repeat": {"seconds": 0.5}}),
                     "value must be at least 0:00:01", id="repeat under a second"),
        pytest.param(lights_block(high={"turn_on": {}, "repeat": "soon"}),
                     "offset soon should be format 'HH:MM', 'HH:MM:SS' or 'HH:MM:SS.F'",
                     id="repeat not a period"),
        pytest.param(lights_block(resolved={"turn_on": {}, "lasts": {"seconds": 0}}),
                     "value must be at least 0:00:01", id="lasts zero"),
    ```

    and `resolved without for` and `repeat on resolved` by

    ```python
        pytest.param(lights_block(resolved={"turn_on": {}}),
                     "required key 'lasts' not provided", id="resolved without lasts"),
        pytest.param(lights_block(resolved={"turn_on": {}, "for": {"seconds": 120}}),
                     "'for' is an invalid option", id="resolved's for, as before 0.2.1"),
        pytest.param(lights_block(resolved={"turn_on": {}, "lasts": {"seconds": 5},
                                            "repeat": {"seconds": 5}}),
                     "'repeat' is an invalid option", id="repeat on resolved"),
    ```

  - `test_an_alerts_group_is_an_attribute`'s `true` param: `pytest.param("default", "default", id="default")`;
  - `test_an_alert_without_lights_has_no_group` loses its parametrize (only `None`), and a new test follows it:

    ```python
    async def test_an_alert_without_lights_has_no_group(house: HomeAssistant) -> None:
        assert await setup(house, devices(gate=raised("gate", "medium", None)), config=CONFIG)
        assert "lights" not in attributes(house, alert("gate"))


    @pytest.mark.parametrize("lights", [pytest.param(True, id="true, as before 0.2.1"),
                                        pytest.param(False, id="false, as before 0.2.1")])
    async def test_an_alerts_lights_is_a_groups_name(
            house: HomeAssistant, caplog: pytest.LogCaptureFixture, lights: bool) -> None:
        assert not await setup(house, devices(gate=raised("gate", "medium", lights)), config=CONFIG)
        assert ("lights names a group of config.alerts.lights.groups, such as default; "
                "absent, the alert borrows none") in caplog.text
    ```

  - `test_an_alerts_lights_must_name_a_group`: `True` → `"default"` in `no default group` and `no config`;
  - the two ready-made `{"lights": True}` blocks (`test_a_ready_made_alerts_group_is_an_attribute`'s washer, and the offline alert with `for: {seconds: 0}`): `"lights": "default"`.

  `tests/test_checks.py`, `a ready-made alert's missing default group`: `{"offline": {"lights": "default"}}`. `tests/fixtures/house.yaml`: `long_cycle: {for: {hours: 3}, lights: default}`.

  Expected RED: `lights: "default"` is accepted already (a slug), so the RED is `lasts` (refused, `required key 'for'`), the periods (`'minutes' is an invalid option`…), and `true`/`false` (accepted today).

- [ ] **Step 2: The code.**
  - `outputs/alert_lights.py`: the module docstring "…`resolved`'s for its `lasts`…"; `FOR = "for"` → `LASTS = "lasts"`; `SECONDS` → 

    ```python
    # Any HA time period, at least a second: 0 would make repeat a busy loop
    PERIOD = vol.All(cv.positive_time_period, vol.Range(min=timedelta(seconds=1)))
    ```

    `PRIORITY`'s `vol.Optional(REPEAT): PERIOD`; `RESOLVED_SCHEMA`'s `vol.Required(LASTS): PERIOD`; `DEFAULTS[RESOLVED]`'s `LASTS: {"minutes": 2}`; the `resolving` timer reads `self._settings[RESOLVED][LASTS]`; the docstrings and comments that say resolved's `for` say `lasts` (`_Light.overdue`'s comment, "Stop counting resolved's `lasts`", "its `lasts` running on", "Show resolved for its `lasts`").
  - `aspects/problem.py`:

    ```python
    def lights_group(value: Any) -> str:
        """An alert's alert lights group (alert_lights.py), by its name: default is the group default."""
        if isinstance(value, bool):
            raise vol.Invalid(
                f"lights names a group of config.alerts.lights.groups, such as "
                f"{DEFAULT_ALERT_LIGHTS}; absent, the alert borrows none"
            )
        return str(cv.slug(value))
    ```

  - `const.py`: `# The alert lights group an alert's \`lights: default\` names, and the first to write`.
- [ ] **Step 3: GREEN.** Expected: `1433 passed`.
- [ ] **Step 4: The pages.**
  - `docs/concepts/alert-lights.mdx`: the example's `lights: true` → `lights: default`; `lights`' property `type="group"`: "In an alert you write, or in a feature's ready-made one: the name of a group of `config: alerts: lights: groups`, such as `default`. Without it, the alert borrows nothing."; `repeat`: "optional, a [time period](/features/appliance#settings) of at least a second (`{seconds: 15}`): the same `turn_on` again that often while the priority lasts…"; `resolved`: "`turn_on`, as above, and `lasts`, a time period of at least a second: how long before it's turned off and handed back. Both are required."; the defaults block's `resolved: {…, lasts: {minutes: 2}}`; the table's "for its `lasts`" and "`resolved`'s `lasts` ends"; "If `resolved`'s `lasts` ended meanwhile".
  - `docs/concepts/alerts.mdx`, `lights`' property: `type="group"`, "Lights that show the alert while it's on: a group's name from `config: alerts: lights: groups`, such as `default`. See [Alert lights](/concepts/alert-lights)."
  - `docs/reference/configuration.mdx`: `long_cycle`'s `lights: default`.
  - `docs/reference/troubleshooting.mdx`: "An alert's `lights: true` or `false`, as before 0.2.1: `lights names a group of config.alerts.lights.groups, such as default; absent, the alert borrows none`." and "`resolved`'s `for`, as before 0.2.1 (`'for' is an invalid option`): write `lasts`. A `repeat` or `lasts` under a second: `value must be at least 0:00:01`."

  `git grep -n -E 'lights: true|for: \{seconds|\{seconds: N\}|`true` (for|borrows)' -- docs ':!docs/superpowers' ':!docs/ideation' ':!docs/reference/troubleshooting.mdx'` returns nothing.
- [ ] **Step 5: Commit, push.** Message: `pururu: one time format: resolved.lasts, periods of a second or more, lights: default (refactor C)`. The PR text: Task 4 checked.

---

### Task 5: The small ones: `event_entities`, `config: events:`, names

**Files:**
- Modify `custom_components/pururu/features/opening/__init__.py` (`EVENT_ENTITIES`), `setup/schema.py` (`events` under `config`, the device's `name`), `outputs/events.py` (reads `config`), `outputs/places.py` (`name`).
- Modify `tests/helpers.py` (`_config`), `tests/test_ids.py`, `tests/test_opening.py`, `tests/test_events.py`, `tests/test_places.py`, `tests/test_init.py`, `tests/fixtures/house.yaml`.
- Modify `docs/features/door.mdx`, `docs/features/window.mdx`, `docs/concepts/events.mdx`, `docs/concepts/floors-and-areas.mdx`, `docs/concepts/devices-and-features.mdx`, `docs/reference/configuration.mdx`, `docs/reference/troubleshooting.mdx`.

**Interfaces** (produced): `features.opening.EVENT_ENTITIES = "event_entities"`; `pururu: config: events:` (the validated `house[config][events]`, default `[]`); the helpers' `events=` writes `config: events:`.

- [ ] **Step 1: The failing tests.**
  - `tests/helpers.py`, `_config`:

    ```python
    def _config(devices: dict[str, Any], floors: dict[str, Any] | None,
                areas: dict[str, Any] | None, events: Any = None,
                config: dict[str, Any] | None = None) -> dict[str, Any]:
        """A configuration.yaml with this `pururu:` block; `events` is config's (both left out when None)."""
        block: dict[str, Any] = {"devices": devices, "floors": floors or {}, "areas": areas or {}}
        if events is not None:
            config = {**(config or {}), "events": events}
        if config is not None:
            block["config"] = config
        return {DOMAIN: block}
    ```

  - `tests/test_ids.py`: `events=HOUSE["events"],` goes (the fixture's `config` holds them).
  - `tests/fixtures/house.yaml`: `events: [state_changed, reading]` moves from the top level into `config:` after `notify`; `porta_frente`'s `events:` → `event_entities:`.
  - `tests/test_opening.py`, by a short Python script: `\bevents=(EVENTS|\[EVENTS)` → `event_entities=\1` (9), `\{"events": \[` → `{"event_entities": [` (8); then by hand, after `match not a period` in `test_invalid_events_are_refused`:

    ```python
        pytest.param({"events": [{"entity": ACCESS, "types": ACCESS_TYPES}]},
                     id="events, as before 0.2.1"),
    ```

  - `tests/test_events.py`, after `test_the_schema_refuses`:

    ```python
    async def test_events_are_configs(ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
        """config: is the one place for the whole house's settings: a top-level events, as before 0.2.1, is refused."""
        assert not await async_setup_component(ha, "pururu", {"pururu": {"devices": DEVICES, "events": BOTH}})
        assert "'events' is an invalid option for 'pururu', check: pururu->events" in caplog.text
    ```

  - `tests/test_places.py`, `test_invalid_floors_and_areas_are_refused`, after `floor without a name`:

    ```python
        pytest.param({"terreo": {**TERREO, "name": " "}}, {}, id="floor with a blank name"),
        pytest.param({}, {"patio": {"name": ""}}, id="area with an empty name"),
    ```

  - `tests/test_init.py`, `test_invalid_device_is_refused`, after `no name`: `pytest.param({**GIZMO, "name": " "}, id="a blank name"),`.

  Expected RED: every test with `events=` is refused (`'events' is an invalid option` under `config`), the door's `event_entities` too; the blank names are accepted today; `test_events_are_configs` fails (the top level accepts `events`).

- [ ] **Step 2: The code.**
  - `features/opening/__init__.py`: the docstring "…The contact is required; event_entities (events.py), optional, describe the openings."; after `_LOGGER`:

    ```python
    # The block's key for its event.* entities
    EVENT_ENTITIES = "event_entities"
    ```

    `SCHEMA`'s `# The event.* entities that describe the openings (not pururu's bus events)` above `vol.Optional(EVENT_ENTITIES): vol.All([events.SCHEMA], vol.Length(min=1))`; `build` reads `config.get(EVENT_ENTITIES, [])`.
  - `setup/schema.py`: import `TEXT` from `..core.feature`; `_device`'s `# A blank name would show its entities by their own names alone` above `vol.Required(CONF_NAME): TEXT`; the top-level `vol.Optional(events.CONF_EVENTS, default=[])` goes, and in `config`'s schema, after `notify`:

    ```python
                                # pururu's events fired on HA's bus
                                vol.Optional(events.CONF_EVENTS, default=[]): events.SCHEMA,
    ```

  - `outputs/events.py`: import `CONF_CONFIG`; the module docstring gains "Enabled by class in `config: events:`."; `async_step` reads `built.house.get(CONF_CONFIG, {}).get(CONF_EVENTS, [])`.
  - `outputs/places.py`: import `TEXT` from `..core.feature`; `FLOOR_SCHEMA`'s and `AREA_SCHEMA`'s `vol.Required(CONF_NAME): TEXT` (`# A blank name: HA would refuse it, or show nothing` above the floor's).
- [ ] **Step 3: GREEN.** Expected: `1439 passed`; `test_ids.py` against the unchanged snapshot.
- [ ] **Step 4: The pages.**
  - `docs/features/door.mdx`: the example's and the property's `events` → `event_entities` (`<Property name="event_entities" type="list" optional>`), and "With `event_entities`, only what they give"; prose "events" for the `event.*` entities stays as a word where it means the events themselves.
  - `docs/features/window.mdx`: "…it takes `event_entities` as a door does…".
  - `docs/concepts/events.mdx`: the example's `events:` moves under `config:`; "`config: events:` lists the classes to fire…".
  - `docs/reference/configuration.mdx`: the example's `events:` moves under `config:` (after `notify`); "`pururu:` has four optional keys: `config`, `floors`, `areas` and `devices`."; `config`'s properties gain `events` ("The classes of [events](/concepts/events) pururu fires on Home Assistant's bus: `state_changed`, `reading`. None by default."); floors', areas' and devices' `name`: "It can't be empty."
  - `docs/concepts/floors-and-areas.mdx` and `docs/concepts/devices-and-features.mdx`: where `name` is described, "It can't be empty."
  - `docs/reference/troubleshooting.mdx`: "A door's or window's `events`, as before 0.2.1: `'events' is an invalid option`; write `event_entities`." "A top-level `events:`, as before 0.2.1: `'events' is an invalid option for 'pururu', check: pururu->events`; move it under `config:`." "A device's, floor's or area's empty `name`: `length of value must be at least 1`." The door bullet says "an event entity whose `entity` isn't an `event.*` entity…".
  - Run `pnpm docs:check`.

  `git grep -n -E '^  events:|^\s+events:$' -- docs ':!docs/superpowers' ':!docs/ideation'` returns nothing (`config:`'s `events:` is indented four spaces in every example).
- [ ] **Step 5: Commit, push.** Message: `pururu: event_entities, config: events:, names that refuse empty text (refactor C)`. The PR text: Task 5 checked.

---
### Task 6: The Guide page "Updating to 0.2.1", and version 0.2.1

One page carries every manual step of the refactor, in the one order that works: B4's (the notifications, before the update; the old automation files), D2's (`running_program`, modes and phases), D3's (final text, from #60: `executable:`, `when: program_executable_…`, phases keyed `other_…`, references outside pururu) and C's (Tasks 1–5). A test keeps its examples true. The old version notes go, and the version becomes 0.2.1.

**Files:**
- Create `docs/getting-started/updating-to-0.2.1.mdx`, `tests/test_updating.py`.
- Modify `docs.json` (the sidebar), `docs/getting-started/install.mdx` (the link).
- Modify `docs/concepts/programs.mdx`, `docs/concepts/alerts.mdx`, `docs/concepts/notifications.mdx`, `docs/concepts/entity-ids.mdx`, `docs/reference/troubleshooting.mdx` (the old version notes, ruling 18).
- Modify `custom_components/pururu/manifest.json` (`0.2.1`).

**Interfaces:** none in code. The page's YAML blocks are titled `0.1.23` or `0.2.1` (each step shows both), and the last one `0.2.1: configuration.yaml` (the whole example); the test reads them by title.

- [ ] **Step 1: The failing test.** `tests/test_updating.py`:

  ```python
  """The Guide's "Updating to 0.2.1": each 0.1.23 example is refused, each 0.2.1 one is valid, and the whole example sets up."""

  from pathlib import Path
  import re
  from typing import Any

  from homeassistant.core import HomeAssistant
  import pytest
  import voluptuous as vol
  import yaml

  from helpers import module, setup

  PAGE = Path(__file__).resolve().parents[1] / "docs/getting-started/updating-to-0.2.1.mdx"


  class _Loader(yaml.SafeLoader):
      """configuration.yaml's own tags (!include_dir_…) read as nothing: only pururu: is checked."""


  _Loader.add_multi_constructor("!", lambda *_: None)


  def blocks(version: str) -> list[Any]:
      """The page's YAML blocks titled `version`, in order."""
      found = re.findall(rf'```yaml title="{re.escape(version)}[^"]*"\n(.*?)```', PAGE.read_text(), re.DOTALL)
      return [yaml.load(block, Loader=_Loader) for block in found]


  def test_each_step_shows_both_versions() -> None:
      assert len(blocks("0.1.23")) == len(blocks("0.2.1")) - 1  # the whole example has no "before"


  async def test_the_whole_example_sets_up(ha: HomeAssistant) -> None:
      """Every 0.2.1 key of the steps, in one block: valid, and pururu sets it up."""
      [whole] = blocks("0.2.1: configuration.yaml")
      house = whole["pururu"]
      assert await setup(ha, house["devices"], config=house["config"])


  def test_the_whole_example_is_refused_with_any_old_key(ha: HomeAssistant) -> None:
      """Each 0.1.23 key the steps rename, put back in the whole example, is refused."""
      schema = module("setup.schema").CONFIG_SCHEMA
      [whole] = blocks("0.2.1: configuration.yaml")
      olds: list[tuple[list[str], str, Any]] = [
          (["devices", "clothes_washer", "alerts", "stuck"], "is", "wringing"),
          (["devices", "clothes_washer", "alerts", "stuck"], "notify", {"message": "m", "done_message": "d"}),
          (["devices", "biblioteca", "reactions", "washer_done"], "device", "clothes_washer"),
          (["devices", "porta_frente", "door"], "events", [{"entity": "event.x", "types": {"ring": "ring"}}]),
          (["devices", "clothes_washer", "appliance"], "running", {"threshold": 4}),
          ([], "events", ["reading"]),
          (["config", "alerts", "lights", "resolved"], "for", {"seconds": 120}),
      ]
      for path, key, value in olds:
          house = yaml.load(yaml.dump(whole["pururu"]), Loader=_Loader)
          at = house
          for step in path:
              at = at[step]
          at[key] = value
          with pytest.raises(vol.Invalid):
              schema({"pururu": house})
  ```

  `uv run pytest tests/test_updating.py -n 0 -q`. Expected: `FileNotFoundError` (no page yet).

- [ ] **Step 2: The page.** `docs/getting-started/updating-to-0.2.1.mdx`, whole (it supersedes the planner's earlier draft in the scratchpad, written before D and C had plans):

````mdx
---
title: Updating to 0.2.1
description: Move a 0.1.23 configuration to 0.2.1 by hand, once, in this order. There is no automatic migration.
---

0.2.1 is the release that carries pururu's 0.2.0 refactor. pururu still does what it did for you; the YAML you write for it changes, made consistent: one way to name an entity, one condition vocabulary, one meaning for `notify`, one time format, and programs in place of `modes`, `phases` and the appliance's `running`.

**There is no automatic migration.** pururu ships no aliases, no deprecation warnings and no migration code: an old key is refused, with its place (`'is' is an invalid option for 'pururu', check: pururu->devices->clothes_washer->alerts->stuck->is`). You rewrite the `pururu:` block once, from 0.1.23, following this page in order.

<Warning>
  **Some history starts over.** Two kinds of entities get new IDs:

  - **Modes and phases** (`mode_*`, `phase_current`): a phase of `running_program` is `<platform>.pururu_<key>_appliance_phase_<phase>…`.
  - **Executable programs**: each script is `script.pururu_<key>_program_executable_<program>`, and its sensors `sensor.pururu_<key>_program_executable_<program>_…`.

  Their old entities are removed at the first start. Their history stays in the recorder under the old IDs; the new totals and meters start from zero. Every other entity keeps its ID, its history and its statistics. See [What starts over](#what-starts-over).
</Warning>

## Before you update

Still on 0.1.23:

<Steps>
  <Step title="Wait until every appliance is stopped">
    A cycle running during the update is lost, and so are its phases'.
  </Step>
  <Step title="Back up">
    Copy `configuration.yaml`, the `pururu/` folder next to it, and `.storage/`: your way back to a running 0.1.23.
  </Step>
  <Step title="Remove every ready-made notifications block, then reload pururu">
    Delete each feature's `notifications:` (such as the appliance's `finished`), then reload pururu (**Developer tools → YAML → Pururu**, or the `pururu.reload` action). Their automations and registry entries go. 0.2.1 writes reactions' and notifications' automations to one file under one list of IDs: left in place, the old ones would be taken for yours and not generated again. You put the blocks back at the end.
  </Step>
</Steps>

## Update

<Steps>
  <Step title="Download 0.2.1, but don't restart yet">
    In HACS, open **Pururu** and download 0.2.1 (or copy the new `custom_components/pururu/` by hand). Don't restart and don't reload pururu until the `pururu:` block below is rewritten: the old version refuses the new keys, and the new one the old keys.
  </Step>
  <Step title="Delete the old automation files">
    ```sh
    rm pururu/automations/reactions.yaml pururu/automations/notifications.yaml
    ```

    0.2.1 writes both kinds to `pururu/automations/automations.yaml`. Home Assistant loads every file in the folder, so the old two would repeat its IDs.
  </Step>
</Steps>

## Rewrite the `pururu:` block

Home Assistant validates the whole block at once: make every change below before you restart. Each step shows 0.1.23, then 0.2.1.

<Steps>
  <Step title="The appliance's running becomes running_program">
    `running:` becomes `running_program:`, its `threshold:` becomes `above:`, and its delays stay (absent, they are 0). The appliance's `runtime` and `cycles` statistics move into it; `idle_energy` stays on the appliance.

    ```yaml title="0.1.23"
    appliance:
      power: sensor.washer_plug_power
      energy: sensor.washer_plug_energy
      running: {threshold: 4, on_delay: {minutes: 1}, off_delay: {minutes: 2}}
      statistics:
        runtime: [today, month]
        cycles: [today, month]
        idle_energy: [month]
    ```

    ```yaml title="0.2.1"
    appliance:
      power: sensor.washer_plug_power
      energy: sensor.washer_plug_energy
      running_program:
        above: 4
        on_delay: {minutes: 1}
        off_delay: {minutes: 2}
        statistics:
          runtime: [today, month]
          cycles: [today, month]
      statistics:
        idle_energy: [month]
    ```
  </Step>

  <Step title="modes and phases become the running program's phases">
    Each `modes:` and `phases:` feature goes. Its bands become `running_program: phases:`, each with a `name`, `above`/`below` and `on_delay`/`off_delay`.

    - A mode keeps its `name`, band and delays. `cycle_from`, `sensor` and `energy` go: a phase reads the appliance's power and energy.
    - A phase band's `for:` becomes `on_delay:`, and it needs a `name` now. `defaults:` goes: a stopped appliance's phase is `idle`, and one running outside every band is `other`.
    - `idle`, `other`, `other_…`, `current` and `last` are reserved: rename a phase keyed so.
    - Bands may overlap: both phases then run.
    - `statistics:` goes in each phase that should have meters. They are new meters, starting from zero.

    ```yaml title="0.1.23"
    water_station:
      name: Purificador
      appliance:
        power: sensor.station_plug_power
        energy: sensor.station_plug_energy
        running: {threshold: 2.9, on_delay: {seconds: 1}, off_delay: {minutes: 1}}
      modes:
        cycle_from: appliance
        sensor: sensor.station_plug_power
        energy: sensor.station_plug_energy
        modes:
          resfriar: {name: Resfriar, above: 4, below: 150, on_delay: {seconds: 10}, off_delay: {minutes: 3}}
          quente: {name: Água quente, above: 150, below: 400, on_delay: {seconds: 30}, off_delay: {seconds: 30}}
        statistics:
          runtime: [today, month]
    ```

    ```yaml title="0.2.1"
    water_station:
      name: Purificador
      appliance:
        power: sensor.station_plug_power
        energy: sensor.station_plug_energy
        running_program:
          above: 2.9
          on_delay: {seconds: 1}
          off_delay: {minutes: 1}
          phases:
            resfriar:
              name: Resfriar
              above: 4
              below: 150
              on_delay: {seconds: 10}
              off_delay: {minutes: 3}
              statistics: {runtime: [today, month]}
            quente:
              name: Água quente
              above: 150
              below: 400
              on_delay: {seconds: 30}
              off_delay: {seconds: 30}
              statistics: {runtime: [today, month]}
    ```

    A `modes:` block's `statistics:` metered every mode: write it in each phase.

    ```yaml title="0.1.23"
    phases:
      cycle_from: appliance
      sensor: sensor.washer_plug_power
      defaults: {stopped: idle, running: washing}
      bands:
        warming: {above: 1000}
        wringing: {above: 50, below: 1000, for: {minutes: 3}}
    ```

    ```yaml title="0.2.1"
    running_program:
      above: 4
      phases:
        warming: {name: Aquecendo, above: 1000}
        wringing: {name: Centrifugando, above: 50, below: 1000, on_delay: {minutes: 3}}
    ```
  </Step>

  <Step title="A device's programs go under executable">
    Indent each device's programs under `executable:`.

    ```yaml title="0.1.23"
    programs:
      clean:
        name: Limpar
        sequence: [{turn_on: switch_sprinkler}, {delay: {hours: 2}}, {turn_off: switch_sprinkler}]
    ```

    ```yaml title="0.2.1"
    programs:
      executable:
        clean:
          name: Limpar
          sequence: [{turn_on: switch_sprinkler}, {delay: {hours: 2}}, {turn_off: switch_sprinkler}]
    ```

    A program an appliance's power alone tells apart can become a [detected program](/concepts/programs#more-detected-programs) later, in its `appliance:` block, under `programs: detected:`.
  </Step>

  <Step title="Rename what pururu's own YAML says about renamed entities">
    In your alerts' and reactions' `when:`:

    - `mode_current`, `mode_last`, `mode_<key>_…` and `phase_current` become `appliance_phase_current`, `appliance_phase_last` and `appliance_phase_<key>_…`.
    - `program_<key>_…` becomes `program_executable_<key>_…`.
    - A state that named the old `defaults: running:` word names `other` now.

    A missed one is refused: `alerts: program_clean_cycles_total is not an entity key of another feature of this device`. A reaction's `then:` needs nothing: it still names the program's key.
  </Step>

  <Step title="Another device's entity is device.key">
    A reaction's `device:` and `when:` become one `when: <device>.<key>`. An entity of the same device is still its key alone.

    ```yaml title="0.1.23"
    washer_done: {name: Lavadora terminou, device: clothes_washer, when: appliance_running, from: "on", to: "off"}
    ```

    ```yaml title="0.2.1"
    washer_done: {name: Lavadora terminou, when: clothes_washer.appliance_running, from: "on", to: "off"}
    ```

    An alert light group becomes a list of its lights, each `<device>.light_<key>`:

    ```yaml title="0.1.23"
    groups:
      default: {biblioteca: [teto]}
      externas: {biblioteca: [teto, abajur]}
    ```

    ```yaml title="0.2.1"
    groups:
      default: [biblioteca.light_teto]
      externas: [biblioteca.light_teto, biblioteca.light_abajur]
    ```
  </Step>

  <Step title="An alert's is, notify and lights">
    - `is:` becomes `state:`, compared as text, as a reaction's `to:`. `"on"` and `"off"` read as before. **A number is text now:** `state: 1` matches a state of `1`, not `1.0`, and the appliance's power shows `1.0`. For a number, write `above`/`below`, or the state as the entity shows it (`state: "0.0"`); for a plug drawing nothing, the appliance's ready-made [`no_power`](/features/appliance#ready-made-alerts).
    - `notify: {message, done_message}` becomes `message:` and `done_message:` on the alert, both or neither. This applies to the ready-made alerts too. `notify` always means where a message goes now; an alert's is Alert2's.
    - `lights: true` becomes `lights: default`. `lights: false` goes: absent, an alert borrows no light.

    ```yaml title="0.1.23"
    stuck:
      name: Travada
      when: phase_current
      is: wringing
      for: {hours: 1}
      lights: true
      notify: {message: Travada!, done_message: Destravou.}
    ```

    ```yaml title="0.2.1"
    stuck:
      name: Travada
      when: appliance_phase_current
      state: wringing
      for: {hours: 1}
      lights: default
      message: Travada!
      done_message: Destravou.
    ```
  </Step>

  <Step title="The alert lights' resolved lasts">
    `resolved`'s `for` becomes `lasts`. It and `repeat` take any time period of at least a second: `{seconds: 120}`, `{minutes: 2}`, `"00:02:00"`.

    ```yaml title="0.1.23"
    resolved: {turn_on: {color_name: green}, for: {seconds: 120}}
    ```

    ```yaml title="0.2.1"
    resolved: {turn_on: {color_name: green}, lasts: {minutes: 2}}
    ```
  </Step>

  <Step title="event_entities, config: events, names">
    - A door's or window's `events:` (its `event.*` entities) becomes `event_entities:`.
    - The top-level `events:` (pururu's events on the bus) moves into `config:`.
    - A device's, floor's or area's `name` can't be empty.

    ```yaml title="0.1.23"
    pururu:
      config:
        notify: notify.mobile_app_phone
      events: [state_changed, reading]
    ```

    ```yaml title="0.2.1"
    pururu:
      config:
        notify: notify.mobile_app_phone
        events: [state_changed, reading]
    ```
  </Step>

  <Step title="Check the configuration">
    **Developer tools → YAML → Check configuration** validates the whole file, `pururu:` included. A refused key names its place: `'events' is an invalid option for 'pururu', check: pururu->events`. [Troubleshooting](/reference/troubleshooting#the-reload-changed-nothing) lists each refusal, the old forms' too.
  </Step>

  <Step title="Restart Home Assistant">
    pururu sets up with 0.2.1. The old modes', phases' and executable programs' entities and scripts are removed; see [What starts over](#what-starts-over).
  </Step>
</Steps>

## After the restart

<Steps>
  <Step title="Put the notifications back, then reload pururu">
    Their syntax didn't change (`message`, `notify`): only the file they're written to did.
  </Step>
  <Step title="Rename what refers to a renamed entity outside pururu">
    Dashboards, your automations and scripts, and whatever consumes [pururu's events](/concepts/events) still name the old IDs:

    - `…_mode_…` and `…_phase_current` → `…_appliance_phase_…`; an event's `event_name` too (`<device>.mode_…` → `<device>.appliance_phase_…`).
    - `script.pururu_<key>_program_<program>` (as a `script.turn_on` target) and its sensors → `…_program_executable_<program>…`.
  </Step>
  <Step title="Optional: tidy up">
    Once you no longer need them, delete the old entities' long-term statistics in **Developer tools → Statistics**.
  </Step>
</Steps>

### If you didn't remove the notifications first

Their automations show as **no longer provided**, and pururu logs each new one as already taken. In **Settings → Entities**, delete each `automation.pururu_…_notification_…`, then reload pururu: their IDs are free again, and pururu generates them.

## What starts over

| What | Before | After | Its history |
|---|---|---|---|
| A mode's or phase's entities | `sensor.pururu_<key>_mode_<mode>_…`, `…_mode_current`, `…_phase_current` | `sensor.pururu_<key>_appliance_phase_<phase>_…`, `…_appliance_phase_current` | Kept under the old IDs; the new ones start from zero |
| An executable program's script | `script.pururu_<key>_program_<program>` | `script.pururu_<key>_program_executable_<program>` | Its runs restart under the new ID |
| An executable program's sensors | `sensor.pururu_<key>_program_<program>_…` | `sensor.pururu_<key>_program_executable_<program>_…` | Kept under the old IDs; totals and meters start from zero |

Everything else keeps its ID, history and statistics: floors and areas, the appliance's own entities (`appliance_running`, its last cycle, totals and meters), switches, lights, doors, windows, alerts (and their Alert2 names and acknowledgements), reactions' and notifications' automations, and the `/pururu` dashboard.

## The whole example, after

```yaml title="0.2.1: configuration.yaml"
pururu:
  config:
    notify: notify.mobile_app_phone
    events: [state_changed, reading]
    alerts:
      lights:
        groups:
          default: [biblioteca.light_teto]
          externas: [biblioteca.light_teto, biblioteca.light_abajur]
        resolved: {turn_on: {color_name: green}, lasts: {minutes: 2}}
  devices:
    clothes_washer:
      name: Tanquinho
      appliance:
        power: sensor.washer_plug_power
        energy: sensor.washer_plug_energy
        running_program:
          above: 4
          on_delay: {minutes: 1}
          off_delay: {minutes: 2}
          statistics:
            runtime: [today, month]
            cycles: [today, month]
          phases:
            warming: {name: Aquecendo, above: 1000}
            wringing: {name: Centrifugando, above: 50, below: 1000, on_delay: {minutes: 3}}
        statistics:
          idle_energy: [month]
        alerts:
          long_cycle: {for: {hours: 3}, lights: default}
        notifications:
          finished:
      alerts:
        stuck:
          name: Travada
          when: appliance_phase_current
          state: wringing
          for: {hours: 1}
          lights: externas
          message: Travada!
          done_message: Destravou.
    porta_frente:
      name: Porta da frente
      door:
        contact: binary_sensor.porta_frente
        event_entities:
          - entity: event.porta_frente_doorbell
            types: {ring: ring}
    greenhouse:
      name: Estufa
      switches:
        sprinkler: {entity: switch.greenhouse_sprinkler, name: Irrigador}
      programs:
        executable:
          clean:
            name: Limpar
            sequence: [{turn_on: switch_sprinkler}, {delay: {hours: 2}}, {turn_off: switch_sprinkler}]
    biblioteca:
      name: Biblioteca
      lights:
        teto: {entity: light.biblioteca_teto, name: Teto}
        abajur: {entity: switch.sonoff_abajur, name: Abajur}
      reactions:
        washer_done: {name: Lavadora terminou, when: clothes_washer.appliance_running, from: "on", to: "off"}

automation pururu: !include_dir_merge_list pururu/automations
script pururu: !include_dir_merge_named pururu/scripts
alert2:
  alerts: !include_dir_merge_list pururu/alert2
```
````

  Its sources, step by step, so a reviewer can check nothing was dropped:

  | Step of the page | From |
  |---|---|
  | Wait until every appliance is stopped | D2 #57, step 1 |
  | Back up | the earlier draft |
  | Remove every ready-made notifications block, reload | B4 #54, step 1 |
  | Download 0.2.1, don't restart | B4 step 2, D2 step 2, D3 #60 step 1 |
  | Delete the old automation files | B4 step 3 |
  | `running` → `running_program` | D2 step 3 |
  | modes and phases → phases (reserved keys `idle`, `other`, `other_…`) | D2 steps 4–5, D3 step 1's third bullet |
  | programs under `executable:` | D3 step 1's first bullet, step 4 (optional) |
  | Rename pururu's own `when:` | D2 step 6 (inside pururu), D3 step 1's second bullet |
  | `device.key`, light groups | C Task 2 |
  | `is`, `notify`, `lights` | C Tasks 1, 3, 4 |
  | `resolved.lasts` | C Task 4 |
  | `event_entities`, `config: events`, names | C Task 5 |
  | Restart | B4 step 4, D2 step 7, D3 step 2 |
  | Put the notifications back | B4 step 5 |
  | Rename outside pururu (cards, automations, `script.turn_on`, `event_name`) | D2 step 6, D3 step 3 |
  | Tidy up the old statistics | D2 step 7 (optional) |
  | If you didn't remove the notifications | B4's recovery |
  | What starts over | D2 and D3 (history), D3's Claude review note (executable programs restart under `program_executable_<key>`) |

- [ ] **Step 3: The sidebar and the link.**
  - `docs.json`, "Getting started", after `Install`: `{ "title": "Updating to 0.2.1", "href": "/getting-started/updating-to-0.2.1" },`.
  - `docs/getting-started/install.mdx`, before `## 2. Add a \`pururu:\` block`:

    ```mdx
    <Info>
      Updating from 0.1.23? Follow [Updating to 0.2.1](/getting-started/updating-to-0.2.1): its `pururu:` block is rewritten before the restart.
    </Info>
    ```

- [ ] **Step 4: The old version notes go** (ruling 18):
  - `docs/concepts/programs.mdx`: the section `### From 0.1.14 and before`, whole;
  - `docs/concepts/alerts.mdx`: the section `### Coming from the generator`, whole;
  - `docs/concepts/notifications.mdx`: the section `## Coming from the \`finished\` alert`, whole;
  - `docs/concepts/entity-ids.mdx`: the `<Info>` "Before pururu 0.1.5…", whole;
  - `docs/reference/troubleshooting.mdx`: the `Duplicate declaration of alert for domain=pururu` entry stays (it's a log line), its link becomes `See [Getting notified](/concepts/alerts#getting-notified).`

  `git grep -n -E '0\.1\.(1?[0-9]|2[0-2])\b' -- docs README.md ':!docs/superpowers' ':!docs/ideation'` returns nothing.
- [ ] **Step 5: The version.** `custom_components/pururu/manifest.json`: `"version": "0.2.1"`. `python3 release.py check` prints `release: v0.2.1 will be published`. Before merging (Task 7), `gh release list --limit 3` and `git log origin/main -1 -- custom_components/pururu/manifest.json` show that no other PR set 0.2.1.
- [ ] **Step 6: GREEN and the checks.** `uv run pytest -q`: `1442 passed`. `pnpm docs:check`: `No documentation issues found.` Then, against the old forms, outside the guide and troubleshooting (which name them on purpose):

  ```sh
  git grep -n -E '\bis: ["a-z0-9]|notify: \{|device: [a-z_]+, when|lights: true|for: \{seconds: 120|^  events:' -- docs README.md ':!docs/superpowers' ':!docs/ideation' ':!docs/getting-started/updating-to-0.2.1.mdx' ':!docs/reference/troubleshooting.mdx'
  ```

  returns nothing.
- [ ] **Step 7: Commit, push.** Message: `docs: Updating to 0.2.1, one guide for every manual step of the refactor; the old version notes go; 0.2.1 (refactor C)`. The PR text: Task 6 checked, and its "Updating (manual step)" section links the page and lists its steps' titles.

---

### Task 7: The Develop pages, CLAUDE.md, the spec's status, coverage, the final review, ready

- [ ] **Step 1: CLAUDE.md.**
  - Architecture, the `aspects/` line: `shared(priority)`, "the keys every alert takes: `priority`, `message` and `done_message` (both or neither, `texts_together`), `lights`".
  - Step 6: "its `message` is told after it, to its `notify` or `config: notify`" stays (a reaction's `notify` is where).
  - Step 7: "one condition alert per created alert with `message` and `done_message`".
  - Step 8: "an alert's `lights` (a group's name, `default` included) borrows a group of `config: alerts: lights: groups` (a list of `<device>.light_<key>`)…`resolved` for its `lasts` once the last ends…".
  - "Features": a sentence after the `Refers` bullet: "A reference is `key` (this device), `<device>.<key>` (another device: a reaction's `when`, a light group's member) or `entity:` (a real entity); `core/resolve.py`'s `reference`, `local_key` and `device_reference` validate them, `Ref.parse` reads them."
  - "Events": "`pururu: config: events:` lists `state_changed` and `reading`…".
  - "Tests", the helpers: "`events=` (`pururu: config: events:`)".
  - A line for `core/vocabulary.py` where the Architecture names it: "`Condition` (`state` as text, `above`/`below`, `equals` in code only), `parse`, `band`, `trigger`".
- [ ] **Step 2: The Develop pages.**
  - `docs/develop/architecture.mdx`: step 3's "when `pururu: config: events:` enables a class"; step 7's "each created alert with `message` and `done_message`"; step 8's light groups as `<device>.light_<key>` and `resolved`'s `lasts`; the paragraph on `problem.shared` (`priority`, `message`, `done_message`, `lights`); a short "References" paragraph (the three forms, the three validators, `Ref.parse`, and that `find` is unchanged).
  - `docs/develop/writing-a-feature.mdx`: the `kind` bullet (Task 1); the contract table's `test_every_alert_takes_the_shared_keys` row (`priority`, `message`, `done_message`, `lights`).
  - `docs/develop/testing.mdx`: the helpers' `events=` (`config: events:`); `test_updating.py`'s row ("The Guide's update page: its examples, old and new").
- [ ] **Step 3: The spec's status** (Open #10): `docs/superpowers/specs/2026-09-29-yaml-contract-coherence-design.md`'s status line becomes "**Status:** done, released as 0.2.1."; nothing else changes.
- [ ] **Step 4: Coverage per function, against `main`.** `uv run pytest --cov=custom_components/pururu --cov-report=json:<scratchpad>/cov-c.json`, and the same in a `git archive 51bc43b` scratch copy (`UV_PROJECT_ENVIRONMENT` may point at the worktree's `.venv`, with `uv run --frozen`). Compare missed lines per function by name. Expected (the prototype's): 10 → 9 in all; `Condition._is` covered now; no function worse; every new function (`band`, `parse`, `reference`, `local_key`, `device_reference`, `Ref.parse`, `texts_together`, `_texts`, `_messages`) fully covered. The table goes in the PR text.
- [ ] **Step 5: The final whole-branch review** (opus): `git diff 51bc43b...HEAD` against this plan, the spec's Part 2 and its whole contract, the rulings and the Review Focus. It checks:
  - `tests/fixtures/house_ids.json` untouched (`git diff 51bc43b...HEAD --stat -- tests/fixtures/house_ids.json` is empty);
  - every line of the spec's "whole contract" marked `(C)` has its form in `tests/fixtures/house.yaml` or the guide's whole example;
  - each old form has its `as before 0.2.1` test;
  - no private setup anywhere (only the spec's and the tests' made-up names).

  Fix every finding, minors included, each behaviour fix with a test that failed first. Commit the fixes as `pururu: C final review: <what> (refactor C)` and the docs as `docs: the vocabulary in the Develop pages and CLAUDE.md; the spec done (refactor C)`; each commit ends with the two attribution lines. Push, wait until `headRefOid` equals `git rev-parse HEAD`, then add `claude-review` (the only label of the PR).
- [ ] **Step 6: The review's findings, ready.** Fix every finding of Claude's review, minors included; push; wait for `headRefOid`; remove `claude-review` and add it once more to confirm. Once Claude's review is 5/5, the checks green, Sonar at 0 issues and every thread resolved, and `main` and the releases show no other 0.2.1: `gh pr ready`, then merge (squash). The Release workflow tags v0.2.1 and publishes it. The PR text holds, by then: what C is, the rulings in short, the open decisions as the owner settled them, a link to the "Updating to 0.2.1" page, and the coverage table.

---

## Self-review

- **Spec coverage.** Part 2: #1 (Task 2), #2 (Task 1), #10 (Task 3), #3 #4 (Task 4), #6 (Task 4), #7 #8 #9 (Task 5; #9's `for` in Task 1). "The whole contract": every `(C)` line (Tasks 1–5; the fixture and the guide's whole example hold them). "PRs", row C: 0.2.1 (Task 6); the "From 0.1.14 and before" section (Task 6); tests' helpers (Task 5), every feature page, `configuration.mdx`, `troubleshooting.mdx` (Tasks 1–5), the fixture (each task). "Tests" #4: `resolve` every row of the reference table (`test_a_reference_is_accepted`/`_refused`, the reactions', alerts', programs' and light groups' params), `vocabulary` (`holds`, `band`, `trigger`, `equals` refused), `repeat: 0` refused, `to: 1` and `state: 1` alike (`test_an_alerts_state_and_a_reactions_to_are_one_condition`). Compatibility: B4's, D2's, D3's steps in the guide (Task 6).
- **Not in C** (unchanged): Part 2's #5 (D did it); the spec's "Open decisions" (the `STEPS` guard, a list of triggers, an alert's `notify` as Alert2's per-alert notifier); "Not in 0.2.0", now 0.2.2's.
- **Placeholders:** none; each "by script" step names its rules and counts.
- **Types:** `Condition(state: str | None, above, below, equals)`, `parse(block, word)`, `trigger(entity_id, when, *, from_, hold)`, `Ref.parse`, `reference`/`local_key`/`device_reference`, `light_ids(settings, index)`, `ProblemAlert.messages`, `TEXTS`, `texts_together`, `LASTS`, `PERIOD`, `EVENT_ENTITIES`: the same names in every task.
