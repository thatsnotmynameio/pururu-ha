# Pururu documentation on docs.page — design

Version: pururu 0.1.3. Branch: `docs/docs-page`.

## Goal

A documentation site at `https://docs.page/thatsnotmynameio/pururu-ha` that documents everything pururu does today. The main reader is a Home Assistant user who has never heard of pururu. After reading, they understand what it does, install it and configure their first device without help. A second tab explains the code to someone who wants to contribute.

The README stays as a short entry point that links to the site.

## Decisions

| Question | Decision |
|---|---|
| Scope | User guide and developer docs, in two tabs: `Guide` (`/`) and `Develop` (`/develop`). |
| Language | English, like the code, the README and HACS. Examples keep Portuguese names (Cozinha, Máquina de lavar), as today. No locales. |
| Structure | Split by what the reader is doing: getting started (install, then a tutorial), concepts (why each rule exists), a reference page per feature, a full configuration reference, and troubleshooting. |
| README | Shrunk to what pururu is, install, the smallest example and a link to the site. The site is the single user-facing reference. |
| `manifest.json` | `documentation` points to the site. The version is not bumped, so this is not a release. |
| Checking examples | A throwaway script in the scratchpad validates every YAML example against `CONFIG_SCHEMA`. It is not a repo test. |
| `docs/superpowers/` | Stays where it is and is not in the sidebar. If the local preview shows docs.page serving or indexing it, stop and ask before moving it. |
| Rejected | One sidebar that splits the README into pages: it stays a reference for people who already know pururu. One long tutorial plus one reference page: hard to look things up in, and it grows badly as features are added. English and Portuguese locales: two trees to keep in sync. |

## Files

```
docs.json                       # at the repo root: name, description, tabs, sidebar
docs/
  index.mdx                     # Guide → What is pururu (the home page)
  getting-started/
    install.mdx
    first-device.mdx
  concepts/
    devices-and-features.mdx
    entity-ids.mdx
    floors-and-areas.mdx
    dashboard.mdx
  features/
    appliance.mdx
    phases.mdx
  reference/
    configuration.mdx
    troubleshooting.mdx
  develop/
    index.mdx
    architecture.mdx
    writing-a-feature.mdx
    places-and-dashboard.mdx
    testing.mdx
    releases.mdx
```

`docs.json` has `name: "Pururu"`, a description, the two tabs, and sidebar groups tagged by tab:

- Guide: `Getting started`, `Concepts`, `Features`, `Reference`.
- Develop: `Develop`.

docs.page components used:

- `Steps` in install and the tutorial.
- `Tabs` for HACS or manual install.
- `Property` for configuration keys.
- `Callout` for traps.
- `Card` on the home page.
- Mermaid for the architecture flow and the cycle timeline.

## Page content

### Guide

- **What is pururu** (`index.mdx`):
  - The problem, in a user's words: a smart plug measures the washer's power, and pururu turns that into a *Máquina de lavar* device. That device shows whether the washer is running, its last cycle, its current phase and its runtime this month.
  - Before and after: the raw plug entities, then the pururu device.
  - What pururu creates: floors, areas, devices, entities and a dashboard.
  - What it does not do: it controls nothing, it is `calculated`, and it only reads real entities.
  - Cards to Install, First device and Features.
- **Install**:
  - HACS (custom repository) or manual copy, in `Tabs` with `Steps`.
  - Restart, then add the `pururu:` block.
  - Reload through Developer tools → YAML → Pururu. A reload with an unknown key changes nothing.
  - `pururu:` can come from packages.
- **First device** (a tutorial): it builds the washer in four steps, showing the full YAML so far and the entities that appear after each one.
  1. `appliance` with `power` and `running`. How to pick `threshold`, `on_delay` and `off_delay` from the plug's history.
  2. `energy` and `statistics`.
  3. `phases` with `cycle_from: appliance`.
  4. A floor and an area, and `area:` on the device.

  It ends with an automation that notifies when the laundry is done. It triggers on `_last_cycle_end`, which is written last.
- **Concepts**: prose that explains the reason behind each rule.
  - **Devices and features**: a device is a key, a name, an optional area and one or more features. A feature consumes another's capability through `<capability>_from`.
  - **Entity IDs**:
    - The pattern `<platform>.pururu_<key>_<metric>[_<period>]`.
    - Renames in the UI are followed, and so is what depends on them.
    - An ID already taken is an error and is never suffixed with `_2`.
  - **Floors and areas**:
    - The key becomes the ID.
    - Existing floors and areas are adopted, and UI edits are undone at the next reload.
    - Dropped ones are deleted, and removing the integration deletes all of them.
    - A name another floor or area already has, ignoring case and whitespace, is an error in the log. The floor or area is not created, and neither are the new areas on that floor.
  - **Dashboard**:
    - It lives at `/pururu` and only admins see it.
    - It shows totals and a table, and only what pururu manages.
    - It is rebuilt every time it is opened.
    - Nothing appears when `/pururu` is taken.
- **Features**: one page per entry in `FEATURES`.
  - A table of keys (type, required, example).
  - A table of entities: ID, unit, and when each one exists.
  - The behaviour rules.
  - `appliance` adds a mermaid timeline that shows `on_delay` and `off_delay` against the cycle's start and end.
  - `phases` covers bands, `for`, the first band that holds winning, the `seen` attribute, and translated states.
- **Configuration reference**: every key of `pururu:` on one page, linked to the concept pages.
- **Troubleshooting**: one entry per error pururu logs, with its cause and fix:
  - `<id> is already taken by <holder>; not creating it`
  - `<id> follows <ids>, which is not created; not creating it`
  - `Device <key> is not placed: its area <id> is not created`
  - `Area <id> is not synced: its floor <id> is not created`
  - `<Floor|Area> <id> is left out: …` and `… is not synced: …`
  - `The dashboard is not created: /pururu is already taken` and `… lovelace is not set up`

  It also covers "I changed it in the UI and it came back" and "the reload changed nothing".

### Develop

The content comes from `CLAUDE.md`, rewritten for someone new to the code.

- **index**:
  - Prerequisites (`uv`) and the commands.
  - The repo layout.
  - Traps: use `-n 0`, never `-p no:xdist`, and never leave the cwd in `homeassistant/helpers/`.
- **architecture**:
  - `async_setup` → import flow → `async_setup_entry` and its six steps → platforms, as a mermaid diagram.
  - `entry.runtime_data`.
  - Entity IDs as identity, and the rename listener.
  - `entry.data`.
  - The `ALLOW_EXTRA` trap in voluptuous.
- **writing-a-feature**:
  - A skeleton `Feature`: `schema`, `metrics`, `build()`, `example`, `provides` and `requires`.
  - Registering it in `FEATURES`, with translations and icons.
  - What `tests/test_features.py` checks on its own.
- **places-and-dashboard**:
  - Create by name, then rename.
  - Adopting existing floors and areas, and the managed IDs in `entry.data`.
  - The private lovelace API kept inside `dashboard.py`.
  - The double `lovelace_updated`.
- **testing**:
  - The `ha` fixture (frozen time, loader path).
  - `helpers.module`, and the helpers `setup`, `reload`, `restart`, `tick`, `fake`, `device_of` and `held`.
  - `test_code.py`.
- **releases**:
  - The semver version in `manifest.json`.
  - A PR that bumps it releases: the workflow tags it and publishes the release, and HACS offers it.
  - `release.py check`.
  - Actions pinned by SHA.
  - Sonar suppressions in `sonar-project.properties`.

## Outside `docs/`

- **README.md**, about 30 lines:
  - What pururu is, in two sentences.
  - Install.
  - The smallest example.
  - A link to the site and to the Develop tab.
- **manifest.json**: `documentation` becomes `https://docs.page/thatsnotmynameio/pururu-ha`.
- **CLAUDE.md**: the user-facing reference is now `docs/` and `docs.json`, not the README. A behaviour change updates the docs.

## Accuracy

Every statement is checked against the code and tests, not only against the README.

## Verification

- Local preview with the docs.page CLI: every page renders, and the sidebar, tabs, components and mermaid work.
- A throwaway script in the scratchpad validates every ```yaml example that has a `pururu:` block against `CONFIG_SCHEMA`.
- `uv run pytest` passes.
