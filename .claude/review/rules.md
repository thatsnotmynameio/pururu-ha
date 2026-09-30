# Review rules for pururu-ha

pururu-ha is a Home Assistant custom integration with one author. `CLAUDE.md` at the repository root
is the architecture and the conventions; these rules say what a review flags and how hard.

## Severity

- **P0**: breaks every user or loses data. A setup that fails for any configuration, an entry
  that deletes the user's own areas, automations or scripts, a release that can't install.
- **P1**: a real bug on a normal path. Wrong state after a restart or a reload, an entity that
  vanishes or duplicates, an automation that fires twice or never, a leak of listeners or tasks,
  a configuration the schema accepts and the code then mishandles, a race between two awaits.
- **P2**: real but narrow. An edge the spec or docs promise and the code misses, a docs page or
  translation that now contradicts the code, a contract between modules broken in a way no test
  catches, at most one missing test per review (only for a path that can regress silently).

A finding needs a concrete failure scenario: which configuration or state, what happens, what
should. "Could be" is not a finding.

## Never flag

- What the linters already report: ruff, ruff format, mypy strict, hassfest, docs.page's link
  check, SonarQube Cloud's code smells. A real bug is still a finding when a test would catch it:
  post it, and name the test in the scenario. You can't run the tests, so never skip a finding
  because "CI will catch it".
- Style, naming, wording, formatting, comment density, nits of any kind.
- `docs/superpowers/` (specs and plans): only when the same PR's code contradicts it.
- Lockfiles and generated files: `uv.lock`, `pnpm-lock.yaml`, `.hassfest/`.
- Anything outside the pull request's changes, unless the change breaks it.
- Compatibility with older configurations (the user's YAML): there is one user and no migration
  promise. This never covers what pururu itself left behind (see "State left by the previous
  version" below).

## Worth checking in this repository

These are where bugs have been found here. `CLAUDE.md` explains each; don't repeat it, check it.

- Entity IDs and unique IDs ("Entity IDs are the identity"): the shape
  `<platform>.pururu_<device>_<namespace>_<key>`, renames followed, IDs of other integrations
  never taken.
- The setup order in `async_setup_entry` and what each step may assume ("Architecture").
- Restore and reload: state kept across restarts, HA's restored placeholder states, listeners
  and tasks removed on unload, entry reloads triggered by registry changes.
- Generated files (`generated.py`, `alert2_alerts.py`, `files.py`): rewritten only on change,
  failures logged not raised, the domain reloaded, IDs pre-registered and never taken over.
- State left by the previous version: the one user upgrades an installed pururu. When a PR
  renames or merges a generated file, an `entry.data` key, a Repairs issue, a unique ID or an
  entity ID, check what the old one leaves on the next reload: an old file still in an included
  folder (`!include_dir_merge_*` loads every file there, so its items run twice or never go),
  IDs tracked under the old key (orphaned registry entries), an old issue never cleared. It is
  handled either by code or by a documented manual upgrade step (in the PR description, or the
  spec or an "Updating to …" docs page the PR points at): read `gh pr view` and those before
  flagging. Only when neither covers it, it is a P1 if it duplicates or keeps running something.
  When a step covers it, check the step is complete (every stale file and key it leaves).
- Configuration: the voluptuous `ALLOW_EXTRA` gotcha in nested mappings ("Voluptuous gotcha"),
  error messages in both `translations/en.json` and `translations/pt-BR.json`.
- Docs: a change in behaviour, configuration, entities or log messages updates the matching
  `docs/**/*.mdx` page in the same PR ("Docs"). MDX: `{` and `<` outside code break the page.
- Releases: `manifest.json`'s `version` must be semver and above the latest release.
- CI: GitHub Actions pinned by SHA, pnpm (never npm).

## Confidence

How safe the PR is to merge as it is, after your findings:

- 5: no findings, the change is understood end to end.
- 4: only P2s, or a change too large to be sure of every path.
- 3: a P1, or several P2s in the same flow.
- 2: several P1s, or a P1 in setup, deletion or releases.
- 1: a P0.
- 0: you couldn't review it (say why in the verdict).

Then cap it by the findings still open: any P0 → at most 1; two or more P1 → at most 3; any P1 →
at most 4.

## Risk

How much can go wrong if this change is wrong, whatever the findings: the area it touches,
weighted by how much it changes behaviour there. A move, a rename or a refactor you traced as
equivalent is one level below its area (a pure move of files is low, whatever they are); a
change of behaviour takes its area's level.

- low: docs, tests, a new optional feature nobody configures yet.
- medium: a feature's entities, translations, the dashboard.
- high: setup, reload, restore, generated files, the registries, events.
- critical: deletion of what the user owns (`places.py`, `async_remove_entry`), releases, CI and
  this review itself.
