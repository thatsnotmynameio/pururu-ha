# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

pururu is a Home Assistant custom integration (`custom_components/pururu/`). It reads a `pururu:` YAML block and creates floors, areas and devices from it. It builds each device's entities from real entities and a few settings. The docs site is the user-facing reference for every configuration key and entity (see Docs below); the README is a short entry point that links to it.

## Commands

Run all commands from the repo root with `uv`. Home Assistant is pinned through `pytest-homeassistant-custom-component` in `pyproject.toml`, which pins `homeassistant==2026.9.3`.

```sh
uv run pytest                                   # all tests plus ruff, ruff format, mypy, hassfest, quality scale (tests/test_code.py)
uv run pytest tests/test_places.py -n 0 -q      # one file, single process
uv run pytest "tests/test_places.py::test_name[param id]" -n 0
uv run ruff check --fix custom_components/pururu
uv run ruff format custom_components/pururu
uv run mypy custom_components/pururu
python3 release.py check                        # the manifest version must be semver and not below the latest release
```

- **Running single-process:** `pyproject.toml` addopts already pass `-n 4 --dist loadfile`, so use `-n 0` to run in one process. `-p no:xdist` breaks the run.
- **Lint and type scope:** ruff and mypy run only on `custom_components/pururu`, with core's settings (`ruff.toml`, `mypy.ini`, strict). Tests are not linted.
- **hassfest:** it is downloaded once into `.hassfest/` (`fetch_hassfest.py`).
- **Current working directory:** never leave the shell's cwd inside `.venv/.../homeassistant/helpers/`. That folder contains an `importlib.py` that shadows the stdlib, so any Python started there (hooks included) crashes.

## Architecture

- **One config entry owns everything.**
  - `async_setup` validates `CONFIG_SCHEMA` and stores the validated `pururu:` block in `hass.data[DATA_CONFIG]`. It then creates the single entry through an import flow (`config_flow.py`, `single_config_entry`) when the block declares floors, areas or devices.
  - The `pururu.reload` service re-reads YAML and reloads the entry.
  - `async_setup_entry` does all the work, in order:
    1. Sync floors and areas (`places.py`).
    2. Build every device's entities.
    3. Hand them to the platforms through `entry.runtime_data`. The platforms (`sensor.py`, `binary_sensor.py`, `switch.py`, `light.py`, `button.py`) only call `async_add_entities`.
    4. Put each device in its `area:` (a key of `areas:`).
    5. Remove stale entities and devices.
    6. Generate the reactions' automations (`reactions.py`): `pururu/automations/reactions.yaml`, whose folder `configuration.yaml` includes (`automation pururu: !include_dir_merge_list pururu/automations`, as a missing folder loads as `[]` while a missing file stops HA's configuration), entity IDs pre-registered (an ID the entry doesn't manage is the user's, never taken over), automations reloaded when it changed or HA doesn't run it (retried at the next reload), in an entry task, a Repairs issue while it isn't included. A dropped automation's registry entry goes once HA no longer runs it: a restored placeholder state still carries the `id` attribute, so it doesn't count as running. `reactions` is a device key, not a `Feature`.
    7. Write Alert2's alerts (`alert2_alerts.py`): `pururu/alert2/alerts.yaml`, one condition alert per created alert with `notify`, which the user's `alert2:` block includes as its `alerts` (`!include_dir_merge_list pururu/alert2`); Alert2 reloaded when it changed or doesn't run an alert of it, in an entry task, a Repairs issue while it isn't included. The writer is shared with reactions (`files.py`).
    8. Show the dashboard (`dashboard.py`).
- **Features** (`feature.py`, `features/`):
  - A device is a name plus one or more features. `FEATURES` in `features/__init__.py` maps each config key to a `Feature`. A `Feature` has a `schema`, a `namespace`, the `entity_keys` it can create (entity key → platform), `build()`, an `example` block, and the capabilities it `provides` and `requires`.
  - A feature consumes another feature's capability through `<capability>_from: <feature>`. `_build` passes it the current entity ID of the providing entity key.
  - A feature can watch a particular entity of another feature named in its block (an alert's `when: appliance_power`): `Feature.refers` returns those qualified keys, `_device` checks they are another feature's, `_build` passes their current entity IDs in `inputs` by key, and `PururuEntity.follows` drops the entity when the watched one isn't created (or isn't built by the settings).
  - A feature can act on those entities (a program's `turn_on: switch_pump`): `Feature.acts` returns (action, key) pairs, each key in `refers`, and `_device` checks the owner has the action in its `Feature.actions` (switches and lights: `turn_on`, `turn_off`, `toggle`). `programs` runs its translated steps with HA's `Script` helper, one per button, built in `async_added_to_hass` and unloaded on removal.
  - A `configured` feature (`switches`, `lights`, `alerts`, `programs`) takes its entity keys from its block's keys, named by the block's `name` (no translation). A feature standing for real entities of one domain is that domain's HA group entity with one member (`SwitchGroup`, `LightGroup`, as `Mirror` is a `SensorGroup`), one feature per domain. `lights` also takes a `switch.*`, as a `SwitchLight` (on/off). What they share (`{key: {entity, name}}`, `is_pururu`) is in `features/standing.py`. `_device` refuses a real entity in two configured features of one device.
  - A feature can offer ready-made alerts (`Feature.alerts`: name → `Preset`), off until its block's `alerts` enables them: entity key `alert_<name>` (in `entity_keys` through `preset_keys`), validated and built by `features/presets.py` as an `Alert` (a `Condition`) or an `ElapsedAlert` (time since a milestone, kept across restarts), default texts in the translations' `common`. The Alert2 file is built from the created alerts (`ProblemAlert`), hand-written or ready-made.
  - A feature can repeat entity keys per item of its block (`per_item`, `items`): `modes`' `<slug>_<suffix>`, named by `<namespace>_<suffix>` with `{<namespace>}` as the item's name (`_identify(..., item=item)`). The cycle code `appliance`, `modes`, `door` and `window` share (last cycle, totals, meters, energy) is in `features/cycle/`. `door` and `window` are one package, `features/opening/`, built by one function per namespace: a contact makes the openings (cycles), and user-mapped `event.*` entities describe them (who, how, direction), matched by the event's time (its state).
  - `tests/test_features.py` is a contract test over every entry in `FEATURES`. It checks translations and icons for each entity key, that the example is valid, and more. A new feature gets checked there without changes to the test.
- **Entity IDs are the identity:**
  - Every entity is `<platform>.pururu_<device key>_<namespace>_<entity key>` (no exception, even for a key alike its namespace: a switch keyed `switch` is `switch.pururu_pool_switch_switch`; so a feature's fixed entity keys never repeat its namespace, as phases' `current`), and its unique ID is the part after the platform (`Device.object_id`). `_build` hands each feature a `Device` in its namespace, so features write local entity keys; the translation key is the key in its namespace (`appliance_running`).
  - An ID already held by another integration is logged as an error and not created. Anything that follows it (`sources`) is dropped too (`_creatable`); IDs are never suffixed with `_2`.
  - A user rename in the UI is followed: `current_entity_id`, plus a registry listener that reloads the entry.
- **Floors and areas** (`places.py`):
  - HA's registries accept no ID, so a new floor or area is created named after its YAML key (the ID becomes the key), then renamed.
  - Anything with a configured ID is adopted and synced.
  - The IDs the entry manages live in `entry.data` (`{"floors": [...], "areas": [...], "automations": [...]}`, the last the IDs of the reactions' automations). What the YAML drops is deleted, and `async_remove_entry` deletes everything the entry manages.
  - Names HA refuses are logged errors and never fail the setup.
- **Dashboard** (`dashboard.py`):
  - HA has no public API for an integration's dashboard. A `LovelaceConfig` subclass goes in `hass.data[LOVELACE_DATA].dashboards["pururu"]`, and a `lovelace` panel in `yaml` mode (read-only in the UI) shows it. This is private lovelace API: keep every use of it in this module.
  - The config is built at every fetch from `entry.data` and the registries. A registry change fires `lovelace_updated` twice, because the frontend ignores the first one after a yaml fetch.
  - Anything that prevents it (`/pururu` taken, lovelace changed) is a logged error, never a failed setup.
- **Voluptuous gotcha:** `CONFIG_SCHEMA` uses `extra=vol.ALLOW_EXTRA` at the top level. It propagates into plain nested dicts, so a nested mapping that must refuse unknown or non-slug keys needs its own `vol.Schema(...)`.

## Tests

- **`ha` fixture** (`tests/conftest.py`): it freezes time at a fixed Wednesday 10:00 and puts the repo's `custom_components` on HA's loader path.
- **Loading integration modules:** use `helpers.module("<name>")` after the fixture, not a top-level import.
- **Helpers in `tests/helpers.py`:**
  - `setup` and `reload` take devices, plus `floors=` and `areas=`.
  - `restart` restores saved state.
  - `tick` and `fake` drive time and real-entity states.
  - `device_of` and `held` inspect the registries.

## Docs

- **Where:** [docs.page](https://docs.page/thatsnotmynameio/pururu-ha) serves `docs.json` (tabs and sidebar) and `docs/**/*.mdx` from `main`. Only `.mdx` is published, so `docs/superpowers/` (specs and plans) is not.
- **Two tabs:** `Guide` (`/`) for users (getting started, concepts, one page per feature in `FEATURES`, configuration reference, troubleshooting) and `Develop` (`/develop`) for contributors.
- **Keep it true:** a change in behaviour, configuration, entities or log messages updates the matching pages in the same PR. A new feature gets `docs/features/<feature>.mdx` and a sidebar entry.
- **MDX:** `{` and `<` outside code are JSX, so keep them in backticks or code blocks.
- **Check:** `pnpm install` once, then `pnpm docs:check` (broken links; the Docs workflow runs it on every PR) and `pnpm docs:preview` (live preview). Use pnpm, never npm: `package.json` pins the docs.page CLI and pnpm itself (`packageManager`), and `pnpm-lock.yaml` pins them by hash.

## Releases and CI

- **Releases:** the version is `version` in `custom_components/pururu/manifest.json`. A PR that changes it is a release. After it merges to `main`, the Release workflow tags `vX.Y.Z` and publishes a GitHub release, which HACS offers.
- **CI:** GitHub Actions are pinned by SHA, Python packages by hash (`uv.lock`), pnpm packages by hash (`pnpm-lock.yaml`). SonarQube Cloud and the docs.page check run on PRs.
- **Sonar suppressions:** a Sonar finding that conflicts with HA's required signatures or conventions is suppressed in `sonar-project.properties` (`sonar.issue.ignore.multicriteria`), with a comment giving the reason, not in code.
