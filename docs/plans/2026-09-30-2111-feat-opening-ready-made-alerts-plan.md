---
title: Door and window ready-made alerts - Plan
type: feat
date: 2026-09-30
topic: opening-ready-made-alerts
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# Door and window ready-made alerts - Plan

## Goal Capsule

- **Objective:** A person can be told that a door or window has not been opened for a long time, which no alert can say today, and can enable "open for too long" with one key instead of writing the alert by hand.
- **Means:** `door` and `window` offer ready-made alerts, `long_opening` and `no_opening`, enabled in their own block as the appliance's are (KTD1, KTD2, KTD4).
- **Product authority:** the owner, in the 2026-09-30 ideation review (`docs/ideation/2026-09-30-open-ideation.html`, idea 3). The Product Contract wins on behavior; the Key Technical Decisions win on mechanism.
- **Stop conditions:** stop and ask if the alerts aspect can't build a preset from `open` or `last_closed` without changing `aspects/`, or if the ID snapshot changes anything beyond the added alerts.
- **Execution profile:** three units in order, on one branch and one PR. No version bump (KTD3).
- **Who finishes and ships:** the implementer opens the PR; it merges on Claude's review at 5/5, green checks, Sonar at 0 and resolved threads.
- **Open blockers:** none.

## Product Contract

### Summary

`door` and `window` gain two ready-made alerts, off until enabled in the feature's `alerts:` block. `no_opening` turns on when the opening has stayed closed for longer than `for`. `long_opening` turns on when it has stayed open for longer than `for`.

### Problem Frame

Door and window count their openings and keep the last one, but offer no ready-made alerts. "Open for too long" can already be written as a hand-written alert (`docs/features/door.mdx:111`). "Not opened for a day" cannot: a hand-written alert only takes a state, a range and a `for`, with no time since a milestone. A mailbox, a pet door or a room nobody airs has no way to say it was left untouched. The appliance already says the same thing about its cycles with `no_cycle`.

### Key Decisions

- **Each feature declares its own presets.** A preset is the definition of a ready-made alert in its feature's code. The opening's `open` carries no `cycle_start`, so the appliance's presets can't be reused as they are. Governs R1. (session-settled: user-directed — chosen over one set of cycle alerts shared by every cycle source: it breaks the per-feature preset contract, and the opening lacks the attributes the appliance's presets read)
- **Names follow the appliance's `long_cycle`/`no_cycle`, in the openings' vocabulary.** A door's or window's cycle is an opening (`openings_total`, its last opening). Governs R1, R2. (session-settled: user-directed — chosen over `left_open`: it tells a story about who left it, measures nothing more, and breaks the symmetry with the appliance)
- **`for` is required on both.** How long is too long differs too much between a front door, a window and a mailbox for one default to fit. This mirrors `long_cycle` and `no_cycle`. Governs R3.

### Requirements

**Both alerts**

- R1. `door` and `window` offer `long_opening` and `no_opening`, each off until enabled in the feature's own `alerts:` block, as the appliance's ready-made alerts are.
- R2. Each alert's entity ID carries the feature's namespace, `binary_sensor.pururu_<device>_<door|window>_alert_<name>`, like the appliance's `appliance_alert_<name>`.
- R3. Each takes the same settings as the appliance's ready-made alerts: `for` (required), `priority` (default `medium`), `notify` and `lights`. Anything else is a configuration error.
- R4. Each has default texts in English and Brazilian Portuguese, a name and an icon, so it is delivered through Alert2 like the appliance's.

**`long_opening`**

- R5. `long_opening` is on while the opening has been open for longer than `for`, and off once it closes.

**`no_opening`**

- R6. `no_opening` is on while the opening has been closed for longer than `for`, counted from its last closing, and off once it opens.
- R7. Before the first closing pururu has seen, `no_opening` counts from when the alert was created.
- R8. A restart or a reload doesn't restart the count.

### Acceptance Examples

- AE1. **Covers R6.** A mailbox door with `no_opening: {for: {hours: 24}}` closes at 08:00 on Monday and stays closed. The alert turns on at 08:00 on Tuesday and stays on until the door opens.
- AE2. **Covers R7.** A pet door is added to the YAML on Monday at 10:00 with `no_opening: {for: {hours: 24}}` and is never opened. The alert turns on at 10:00 on Tuesday.
- AE3. **Covers R8.** In AE1, Home Assistant restarts at 20:00 on Monday. The alert still turns on at 08:00 on Tuesday, not 20:00.
- AE4. **Covers R5.** A window with `long_opening: {for: {minutes: 30}}` opens at 14:00. The alert turns on at 14:30 and off when the window closes.
- AE5. **Covers R3.** `long_opening:` with no `for` is refused at the configuration, like `long_cycle:` with no `for`.

### Scope Boundaries

- Ready-made notifications for openings (`opened`, `closed`) are out of this work.
- A shared definition of these alerts for every cycle source waits for a third case; two features repeating one declaration is accepted.
- The vocabulary change of the next refactor PR (`is` to `state`, flat alert texts) is not waited for; these alerts carry no condition the user writes.

### Sources / Research

- `custom_components/pururu/features/appliance/alerts.py`: the appliance's presets, the shape to mirror; `no_cycle` counts from `last_cycle_end` with `or_since_created`.
- `custom_components/pururu/features/opening/__init__.py`: door and window, one code; `roles=(Counters((COUNTED,)),)` and the `last_closed` sensor.
- `custom_components/pururu/core/feature.py`: `Preset` and `Elapsed`.
- `docs/features/appliance.mdx`, "Ready-made alerts": the table and settings the door and window pages should match.
- `docs/superpowers/specs/2026-09-29-yaml-contract-coherence-design.md`: the glossary's "preset", and "`Open` gets none" (`cycle_start`/`cycle_end`).

## Planning Contract

Product Contract preservation: Product Contract unchanged. Its first Key Decision and its Sources describe `Open` as it is before this work, without `cycle_start`; KTD4 adds the attribute, and the decision to keep presets per feature stands.

### Key Technical Decisions

- KTD1. One `PRESETS` map in a new `custom_components/pururu/features/opening/alerts.py`, given by `_opening` to both namespaces through the `Presets` role. Door and window share their code already, and the alerts aspect turns each preset into `<namespace>_alert_<name>`, so one map yields both features' keys. Governs R1, R2.
- KTD2. `long_opening` is an `Elapsed(state=on, since_attribute="cycle_start")` preset watching `open`, as `long_cycle` is on the appliance's `running`. `no_opening` is an `Elapsed(state=off, since_key="last_closed", or_since_created=True)` preset watching `open`. Both have `hold=None` and `priority="medium"`. A held `Condition` would start its `for` when it first sees the door open (`aspects/problem.py`, `Alert._evaluate`), so a restart or reload in the middle of an opening would push the alert later than R5 allows. `last_closed` is the same milestone for an opening that `last_cycle_end` is for the appliance. Governs R3, R5, R6, R7.
- KTD4. `Open` exposes the start of the current opening as a `cycle_start` attribute while open. It already keeps that start across restarts and reloads (`features/opening/open.py`, `OpeningStart`); the attribute only makes it readable, as the appliance's carrier does. Governs R5.
- KTD3. No version bump. `main` holds the unreleased 0.2.0 refactor; this change lands on it like A2 to D3 did, and ships whenever the owner next releases.

### Assumptions

- The alerts aspect needs no change. It reads `watches` and `since_key` from the feature's own entity keys, and both `open` and `last_closed` are door and window entity keys (`features/opening/__init__.py`, `ENTITY_KEYS`).
- `ElapsedAlert` already guards the end of a cycle: it notes when the watched entity enters its state, so `open` going off before `last_closed` is written can't turn `no_opening` on from the previous closing (`aspects/elapsed.py`, `_entered`). R8 comes from `ElapsedAlert` keeping its creation time and reading the milestone from a restored sensor.
- `RuntimeTotal` (`open_time_total`) is unaffected by the new attribute: it reads `cycle_start` only when `open` enters `on` from another state, and at that moment the attribute equals the time it entered (`features/cycle/totals.py`, `_watched_changed`).

## Implementation Units

### U1. Door and window offer the two presets

**Goal:** `door` and `window` accept `long_opening` and `no_opening` in their `alerts:` block and build them as alerts with names, icons and default texts in both languages.

**Requirements:** R1, R2, R3, R4, R5, R6, R7, R8. Covers AE1 to AE5.

**Dependencies:** none.

**Files:**
- `custom_components/pururu/features/opening/alerts.py` (new)
- `custom_components/pururu/features/opening/__init__.py`
- `custom_components/pururu/features/opening/open.py`
- `custom_components/pururu/translations/en.json`
- `custom_components/pururu/translations/pt-BR.json`
- `custom_components/pururu/icons.json`
- `tests/test_opening.py`

**Approach:**
1. Give `Open` its `cycle_start` attribute per KTD4: set while open, absent while closed, restored with the opening.
2. Declare the two presets per KTD2 in `features/opening/alerts.py`, with the same comment style as `features/appliance/alerts.py`.
3. Add `Presets(PRESETS)` to `_opening`'s roles, next to `Counters`.
4. Add, for each of the `door` and `window` namespaces: the binary sensor names `<ns>_alert_long_opening` and `<ns>_alert_no_opening`, the `common` texts `<ns>_alert_<name>_message` and `_done_message`, and an icon. The texts mirror the appliance's tone, for example "It has been open for too long." / "It's closed." and "It hasn't been opened in a while." / "It was opened." Door and window may share wording.
5. Let the contract test (`tests/test_features.py`) find any missing translation, icon or example; it covers new presets without changes.

**Patterns to follow:** `features/appliance/alerts.py` and `features/appliance/__init__.py` (`Presets(PRESETS)`); the `cycle_start` attribute in `features/cycle/program/entities.py`; the `appliance_alert_no_cycle` entries in the translations and `icons.json`; `tests/test_presets.py` for alert tests driven by `tick` and `freezer`.

**Test scenarios:**
- Covers AE1. A door with `no_opening: {for: {hours: 24}}` closes and stays closed: off one second before 24 h, on at 24 h, off when the contact opens.
- Covers AE2. A door with `no_opening` that never opened since setup turns on `for` after the alert was created.
- Covers AE3. `no_opening` counting from a closing 50 minutes ago, with `for` of one hour, turns on 10 minutes after a restart, not an hour after it.
- A door that opens and closes again with `no_opening` on doesn't flicker on at the closing: no `on` state change while `last_closed` catches up.
- Covers AE4. A window with `long_opening: {for: {minutes: 30}}` that opens: off at 29:59, on at 30:00, off when it closes.
- A door with `long_opening: {for: {minutes: 30}}` open for 20 minutes when Home Assistant restarts turns on 10 minutes after the restart, not 30.
- `open` carries `cycle_start` while open, equal to when it opened, and none while closed; after a restart during an opening it is the restored start.
- `open_time_total` counts the same hours with the new attribute as before.
- Covers AE5. `long_opening:` or `no_opening:` with no `for` is refused at the configuration.
- An unknown name in a door's `alerts:` is refused, and the message lists `long_opening, no_opening`.
- Without `alerts:` a door creates no alert entity.
- The entity IDs are `binary_sensor.pururu_<device>_door_alert_long_opening` and `binary_sensor.pururu_<device>_window_alert_no_opening`, named in the HA language, with `priority` `medium`.
- With Alert2 set up, an enabled door alert is written to the Alert2 file with its default texts.

**Verification:** the new tests and `tests/test_features.py` pass; `uv run pytest tests/test_code.py` passes ruff, format, mypy and hassfest.

### U2. The ID snapshot covers the new alerts

**Goal:** the ID snapshot pins the four new entity IDs and nothing else changes.

**Requirements:** R2.

**Dependencies:** U1.

**Files:**
- `tests/fixtures/house.yaml`
- `tests/fixtures/house_ids.json`

**Approach:** enable `long_opening` and `no_opening` on the fixture's `porta_frente` door and `janela_quarto` window, then update the snapshot. Only additions may change in it, per the ID snapshot rule in `docs/superpowers/specs/2026-09-29-yaml-contract-coherence-design.md` (Tests, item 1).

**Patterns to follow:** how the fixture's appliance enables every ready-made alert.

**Test scenarios:** Test expectation: none beyond `tests/test_ids.py` itself; the review checks that the snapshot diff is four added IDs.

**Verification:** `tests/test_ids.py` passes, and the snapshot diff adds exactly the door's and the window's two alerts.

### U3. The docs say what door and window offer

**Goal:** the door, window and alert pages document the two alerts the way the appliance page documents its own.

**Requirements:** R1, R3, R5, R6.

**Dependencies:** U1.

**Files:**
- `docs/features/door.mdx`
- `docs/features/window.mdx`
- `docs/concepts/alerts.mdx`
- `docs/reference/troubleshooting.mdx`
- `tests/test_opening.py`

**Approach:**
1. Add a "Ready-made alerts" section to `door.mdx`, with an example block and a table shaped like `appliance.mdx`'s (alert, on when, off when, defaults).
2. In `door.mdx`'s "Alerts and reactions", point a door left open to `long_opening` and keep the hand-written alert as the general form.
3. In `window.mdx`, add the alerts to what a window shares with a door.
4. In `door.mdx`'s entity table, note `open`'s `cycle_start` attribute while open.
5. In `alerts.mdx`'s "Ready-made alerts", name a door's alerts next to the appliance's as examples.
6. In `troubleshooting.mdx`, show that the unknown-alert message lists the feature's own alerts and that `long_opening`/`no_opening` without `for` is refused.

**Patterns to follow:** `docs/features/appliance.mdx`, "Ready-made alerts"; `test_the_appliance_page_lists_every_ready_made_alert` in `tests/test_presets.py`.

**Test scenarios:**
- The door page's "Ready-made alerts" section names every preset `door` offers.

**Verification:** `pnpm docs:check` reports no issues, and the page test passes.

## Verification Contract

- `uv run pytest`: the whole suite, which includes ruff, ruff format, mypy, hassfest and the quality scale (`tests/test_code.py`).
- During work, one file at a time: `uv run pytest tests/test_opening.py -n 0 -q`.
- `pnpm docs:check`: no issues.
- `python3 release.py check` passes with the version unchanged (KTD3).
- Sonar reports no new issues on the PR.

## Definition of Done

- U1 to U3 are done, and every R1 to R8 has a test or a page that shows it.
- The ID snapshot diff is the four added alerts only.
- The suite and the docs check pass; Sonar is at 0.
- No abandoned attempt is left in the diff.
