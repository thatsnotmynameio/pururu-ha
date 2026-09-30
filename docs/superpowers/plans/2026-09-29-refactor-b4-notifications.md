# Refactor B4: the notifications aspect, one automations kind, the whole layer table — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close B with three changes:
- **Ready-made notifications become the third aspect.** Today `device_keys/notifications.py` is neither a device key nor an aspect, and it reads the builders itself.
- **Reactions' and notifications' automations share one kind:** one file (`pururu/automations/automations.yaml`), one data key, one Repairs issue. Today there are two kinds on the same domain: two files, two issues with the same include line, two reloads.
- **`tests/test_code.py` enforces the spec's whole layer table**, by folder.

**Architecture:**
- **`aspects/notifications.py`**, moved from `device_keys/notifications.py`:
  - `ASPECT`, with `key="notifications"`, `offered` meaning the builder has at least one `Happening` (`bool(happenings_of(builder))`, as B3's alerts aspect with `presets_of`), its schema today's `schema(name, happenings_of(builder))` (the first aspect to use `name`: its messages name the builder), `placed="block"`, `mount_absent=False` (absent: none enabled, as the ready-made alerts), `check=None` (the `notify` rule stays `checks.messages`, over the whole house);
  - no entity (`keys` empty, `build` returns `[]`);
  - `enabled(device, builders)` stays as the helper `checks` reads (`_generated_ids`, `messages`); `automation_id` as today;
  - `plan(...)` as today.
- **`core/generated.py`** holds the two kinds, next to `Kind` (not `setup/generate.py`: `device_keys/` and `aspects/` name their domains and can't import `setup/`):
  - `SCRIPTS` (today's `programs.KIND`, moved);
  - `AUTOMATIONS` (today's `reactions.KIND`, whose data key `automations` and issue `automations_not_included` it keeps, with the file `pururu/automations/automations.yaml` and `source="reactions and notifications"`);
  - `setup/generate.py`'s generate step syncs `AUTOMATIONS` once, with `reactions.plan(...).items + notifications.plan(...).items` and the reactions' held.
- **`_feature_block` goes.** After B2 (statistics) and B3 (alerts), `notifications` was all it had left; `catalogue.mount` validates every aspect.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3, voluptuous, pytest, ruff, mypy strict, uv.

**Spec:** `docs/superpowers/specs/2026-09-29-yaml-contract-coherence-design.md`: Part 3 ("Generated files": one automations kind; "Layers" and its B row; "Package": `aspects/notifications.py`), D18, PRs → B4.

**Base:** `main` at f773f13 (B3 merged). Branch `refactor/b4-notifications`.

## Global Constraints

- Version stays `0.2.0`.
- `tests/test_ids.py`: every automation's `(domain, ID)` stays. Only the file and the data key they're tracked under change.
- The generated automations' content (their YAML) is identical, reactions' then notifications'.
- `notifications.KIND` goes, with its Repairs issue `notifications_not_included` and that issue's translations (en, pt-BR). `automations_not_included`'s title and description stop saying "reactions' automations" (they cover both).
- `entry.data["notifications"]` stays, unread (D13, no migration code).
- A rename of a notification's automation still reloads the entry (the one rename rule over `entry.data`'s kinds).
- Error texts verbatim (`… is not a ready-made notification of …: …`, `… needs notify, here or in config.notify`).
- The layer table (below) is the spec's, by folder.
- `uv run pytest` green at every commit; per-function coverage not lower than B3's (20 missed lines at f773f13); a moved function is compared under its new name.
- Commits end with the two attribution lines. Never `git stash`; a RED against the old code runs in a `git archive HEAD | tar -x -C <scratchpad dir>` copy (with `.hassfest`, `uv sync --locked`). Every review finding fixed, minors included.
- The PR opens as a **draft** after Task 1 with `claude-review`; each later task is pushed and gets `claude-review` once. After the final review's fixes: the `greptile` label, then `gh pr ready`, then `@greptileai review` once if Greptile answers "does not match any trigger rule". Its text carries the manual step (Task 4).

## Review Focus

1. **One file, one sync.**
   - Reactions' and notifications' automations are written once, in one file, reloaded once.
   - A held reaction stays held; a notification watching an entity not created isn't generated (logged).
   - The Repairs issue appears once, while the include is missing.
2. **Tracked IDs.** `entry.data["automations"]` now holds the notifications' IDs too.
   - A notification whose ID the entry doesn't manage is the user's, never taken over. That's why the manual step exists: the old `notifications` data key isn't read.
   - Dropping a notification removes its registry entry once HA no longer runs it.
3. **The rename rule** over the kinds tracked in `entry.data` reloads the entry for a renamed notification's automation (A2a's test keeps passing unchanged).
4. **The layer table:** every folder's allowed imports; the named allowances only (no per-file exceptions); only `aspects/statistics.py` imports `utility_meter`.
5. **`catalogue.mount` without `_feature_block`:** a configured builder (`switches`, `lights`) may have an item keyed `notifications`, and `mount` must leave it alone.

---

### Task 1: The notifications aspect, and `_feature_block` goes

**Files:** `device_keys/notifications.py` → `aspects/notifications.py` (git mv, then the aspect around today's code); `aspects/__init__.py` (`ASPECTS` gains it); `setup/catalogue.py` (`_feature_block` goes; `mount` handles every aspect); `setup/checks.py` (`_generated_ids` walks the offered aspects' `generates` instead of `notifications.enabled`); `setup/generate.py` and `setup/lifecycle.py` (imports); tests that name `device_keys.notifications`.

- [ ] **Step 1 (tests first):**
  - `test_features.py`: the aspect contract (B2/B3's generic rules) now covers the notifications aspect: `offered` ⇔ at least one `Happening`; its `keys` empty; absent `notifications` mounts nothing (`mount_absent=False`); `notifications: {}`/`null` still refused as today. RED: there's no aspect yet.
  - `test_mount_leaves_an_items_key_alone` (catalogue): a `switches` item keyed `notifications` stays an item.
  - Every existing notifications test keeps passing unchanged.
- [ ] **Step 2:** the move and the aspect. `ASPECT.schema(builder, name)` is today's `schema(name, happenings_of(builder))` (`name`, the builder's key in the device, which `mount` passes). `_feature_block` goes and `_validated` calls `builder.schema(value)` for every builder. The refusal texts and paths stay (`[<feature>, notifications, …]`).
- [ ] **Step 3:** `uv run pytest -q` → all pass. Commit `pururu: ready-made notifications are an aspect (refactor B4)`.

### Task 2: One automations kind

**Files:** `core/generated.py` (`SCRIPTS`, `AUTOMATIONS`), `setup/generate.py` (one automations sync), `device_keys/programs.py` (`KIND` moves out), `device_keys/reactions.py` (`KIND` moves out; `plan` returns its items as today), `aspects/notifications.py` (`KIND` goes), `setup/lifecycle.py` (the listener's kinds `(SCRIPTS, AUTOMATIONS)`; `async_remove_entry` removes both), `setup/checks.py` (the domains from the kinds), `translations/en.json` and `pt-BR.json` (`notifications_not_included` goes; `automations_not_included` covers both), `tests/test_generated.py` (reads both kinds from `core.generated`), and the tests that name a kind, a file or the notifications issue.

- [ ] **Step 1 (tests first):**
  - A device with a reaction and a ready-made notification writes both to `pururu/automations/automations.yaml`, and `entry.data["automations"]` holds both IDs. RED: two files today.
  - With the include missing, one Repairs issue (`automations_not_included`), not two.
- [ ] **Step 2:** the kinds and the one sync:
  - `reactions.plan(...)` and `notifications.plan(...)` are unchanged; the generate step concatenates their items and syncs `AUTOMATIONS` once with the reactions' held;
  - the rename rule's kinds are `(SCRIPTS, AUTOMATIONS)`;
  - `generated.async_remove` runs for each kind.
- [ ] **Step 3:** `uv run pytest -q` → all pass. Commit `pururu: one automations kind for reactions and notifications (refactor B4)`.

### Task 3: The whole layer table

**Files:** `tests/test_code.py`.

| Folder | May import (besides `homeassistant`, the stdlib) |
|---|---|
| `core/` | `core/`, `const` |
| `features/<x>` | `core/`, `const`, its own package, `features/cycle`, `features/standing`. `features/__init__` imports every feature |
| `aspects/` | `core/`, `const`, `features/cycle`, another `aspects/` module |
| `device_keys/` | `core/`, `const`, `features/cycle`, a sibling. `device_keys/__init__` also `aspects/alerts` |
| `outputs/` | `core/`, `const`, `aspects/problem`, `features/lights` |
| `setup/` | everything |
| root | the platforms `core.runtime` only; `__init__` `setup/` and `const`; `config_flow` `const` |

Only `aspects/statistics.py` imports `homeassistant.components.utility_meter`.

- [ ] **Step 1:** replace `NEVER` and B3's `outputs/` import test with the table (`ALLOWED`: folder → allowed prefixes); one test checks every module against its folder's row.
- [ ] **Step 2:** watch it fail once per row, by perturbation (add a forbidden import with `cp` aside and back). Fix any real violation the table finds; the spec's B row names two today: `features/alerts.py` importing `alert2_alerts` (gone in B3) and `notifications` importing `FEATURES` (gone in B2/B4). Commit `tests: the whole layer table (refactor B4)`.

### Task 4: Docs, coverage, final review, PR

- [ ] **Step 1: Docs.**
  - `docs/concepts/notifications.mdx` and `docs/concepts/reactions.mdx` (the one file, `pururu/automations/automations.yaml`).
  - `docs/reference/troubleshooting.mdx` (the file named in "The automations are not written to …"; the notifications issue goes).
  - `docs/concepts/…` wherever a Repairs issue is named.
  - `CLAUDE.md` (the generate step: one automations kind; notifications an aspect; the layer table).
  - `docs/develop/architecture.mdx`, `index.mdx` (the tree), `writing-a-feature.mdx` ("Ready-made notifications": a builder offers them with `Happenings`, and the aspect does the rest; its contract-test rows), `testing.mdx` (the layer table).
  - `core/feature.py`'s `Aspect` comments (`key`: "statistics", "alerts", "notifications"; `schema`'s `name`: used by the notifications aspect) and `aspects/statistics.py`'s `_schema` docstring (they name B4 today).
  - `pnpm docs:check`.
- [ ] **Step 2:** Coverage per function against B3's (f773f13).
- [ ] **Step 3:** The final whole-branch review (opus). Every finding fixed, minors included.
- [ ] **Step 4:** The draft PR `pururu: refactor B4, notifications as an aspect, one automations kind (0.2.0)` goes ready (Global Constraints). Its text carries the manual step (also in the "Updating to 0.2.0" guide, PR C):

  > Before updating, remove every `notifications:` block and reload pururu: their automations and registry entries go. The one kind would otherwise find them registered under the old `notifications` data key and treat them as the user's. Update, delete `pururu/automations/reactions.yaml` and `pururu/automations/notifications.yaml` (HA loads every file in the folder, and they'd repeat `automations.yaml`'s IDs), and restart. Put the `notifications:` blocks back and reload.
