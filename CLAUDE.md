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
  - Where the code lives: `__init__.py` keeps HA's entry points; the schema and the checks over the whole house are in `schema.py` and `checks.py`, the builders and their entity keys in `catalogue.py` (`builders()`), building and `creatable` in `build.py`, placing devices and removing stale ones in `devices.py`, planning the scripts and automations in `generate.py`; `PururuConfigEntry` is in `runtime.py`, `Condition` in `vocabulary.py`, the common texts in `texts.py`.
  - `async_setup_entry` does all the work, in order:
    1. Sync floors and areas (`places.py`).
    2. Build every device's entities.
    3. Hand them to the platforms through `entry.runtime_data`. The platforms (`sensor.py`, `binary_sensor.py`, `switch.py`, `light.py`) only call `async_add_entities`. Right after, `events.async_setup` tracks the created entities, by device, when `events` enables a class (`events.py`).
    4. Put each device in its `area:` (a key of `areas:`).
    5. Remove stale entities and devices.
    6. Generate the programs' scripts, then the reactions' automations (`generated.py`, a `Kind` per domain; a reaction's `then` starts its device's program, `script.turn_on` unless it runs, and follows it: not generated → not generated, held → held; a reaction on `at` or `sun` can `retry`: more triggers `retry_<k>`, each skipped by a template condition on `last_triggered`, the program's script with `then`, the automation's own `this` without, once the occurrence ran; its `message` is told after it, to its `notify` or `config: notify`, through `messages.py`: notify actions in one `parallel`, text escaped, title the device's name, once per occurrence with retry): `pururu/automations/reactions.yaml` and `pururu/scripts/programs.yaml`, then the ready-made notifications' automations (`notifications.py`, a second automation `Kind`: `pururu/automations/notifications.yaml`, same include, `entry.data["notifications"]`; a kind whose file changed reloads only when it holds items or drops some), whose folders `configuration.yaml` includes (`automation pururu: !include_dir_merge_list pururu/automations`, `script pururu: !include_dir_merge_named pururu/scripts`, as a missing folder loads as nothing while a missing file stops HA's configuration), entity IDs pre-registered (an ID the entry doesn't manage is the user's, never taken over), a script in its device's area, the domain reloaded when the file changed or HA doesn't run it (retried at the next reload), in an entry task, a Repairs issue while it isn't included (checked again on the domain's state changes, the warning logged once). A dropped item's registry entry goes once HA no longer runs it: a restored placeholder state doesn't count. A program whose target is disabled is held, not dropped (`async_sync(..., held)`): out of the file, its registry entry and tracked ID stay, and it comes back as the user set it. `reactions` and `programs` are device keys, not features of a device; a program isn't generated while an entity it acts on is not created (dropped) or disabled (held).
    7. Write Alert2's alerts (`alert2_alerts.py`): `pururu/alert2/alerts.yaml`, one condition alert per created alert with `notify`, which the user's `alert2:` block includes as its `alerts` (`!include_dir_merge_list pururu/alert2`); Alert2 reloaded when it changed or doesn't run an alert of it, in an entry task, a Repairs issue while it isn't included. The writer (header, rewrite only on change, logged failure) is shared with `generated.py` (`files.py`).
    8. Lend lights to the alerts (`alert_lights.py`): an alert's `lights` (`true` is the group `default`) borrows a group of `config: alerts: lights: groups` (device key → its `lights` keys); a light shows the highest priority's `turn_on` among its alerts on (`repeat` for one-shot effects), `resolved` for its `for` once the last ends, then `turn_off` and `pururu_alert_lights_released`. Only `light.turn_on`/`turn_off` on the pururu light, which uses what it has (`Borrowable`: `alert`/`alerts` attributes, `alert` restored, an unknown effect dropped); a change without one of the manager's recent contexts is put back (during `resolved`, one by a person or automation releases it, not turned off); a light without a reading is never called; disabling a followed light or alert reloads the entry; a light restored with `alert` and none of its alerts on goes through `resolved`.
    9. Show the dashboard (`dashboard.py`).
- **Features** (`feature.py`, `features/`):
  - A device is a name plus one or more features. `FEATURES` in `features/__init__.py` maps each config key to a `Feature`. A `Feature` has a `schema`, a `namespace`, the `entity_keys` it can create (entity key → platform), `build()`, an `example` block, and the capabilities it `provides` and `requires`.
  - A feature consumes another feature's capability through `<capability>_from: <feature>`. `build.build` passes it the current entity ID of the providing entity key.
  - A feature can watch a particular entity of another feature named in its block (an alert's `when: appliance_power`): `Feature.refers` returns those qualified keys, `schema._device` checks they are another feature's, `build.build` passes their current entity IDs in `inputs` by key, and `PururuEntity.follows` drops the entity when the watched one isn't created (or isn't built by the settings).
  - A `configured` feature (`switches`, `lights`, `alerts`) takes its entity keys from its block's keys, named by the block's `name` (no translation). A feature standing for real entities of one domain is that domain's HA group entity with one member (`SwitchGroup`, `LightGroup`, as `Mirror` is a `SensorGroup`), one feature per domain. `lights` also takes a `switch.*`, as a `SwitchLight` (on/off). What they share (`{key: {entity, name}}`, `is_pururu`) is in `features/standing.py`. `schema._device` refuses a real entity in two configured features of one device.
  - A feature can offer ready-made alerts (`Feature.alerts`: name → `Preset`), off until its block's `alerts` enables them: entity key `alert_<name>` (in `entity_keys` through `preset_keys`), validated and built by `features/presets.py` as an `Alert` (a `Condition`) or an `ElapsedAlert` (time since a milestone, kept across restarts), default texts in the translations' `common`. The Alert2 file is built from the created alerts (`ProblemAlert`), hand-written or ready-made.
  - A feature can repeat entity keys per item of its block (`per_item`, `items`): `modes`' `<slug>_<suffix>`, named by `<namespace>_<suffix>` with `{<namespace>}` as the item's name (`_identify(..., item=item)`). The cycle code `appliance`, `modes`, `door` and `window` share (last cycle, totals, meters, energy) is in `features/cycle/`. `door` and `window` are one package, `features/opening/`, built by one function per namespace: a contact makes the openings (cycles), and user-mapped `event.*` entities describe them (who, how, direction), matched by the event's time (its state).
  - A feature's `actions` (switches and lights: `turn_on`, `turn_off`, `toggle`) are what a program's step can do to its entities; `checks.programs_on_this_device` checks them.
  - `programs` and `reactions` aren't features, but their statistics are sensors built by a `Feature` each in `DEVICE_KEYS` (`device_keys.py`): each program's run is a cycle its `cycles_total` (`Runs`) sends from its script's state, each reaction's `triggered_total` counts `automation_triggered`. `catalogue.builders()` (`FEATURES`, then `DEVICE_KEYS`, read at every call) is what lists, resolves and builds entity keys; `FEATURES` alone makes a device's features.
  - A feature can offer ready-made notifications (`Feature.notifications`: name → `Happening`, the entity key it watches and its `to`/`from_`), enabled in its block's `notifications` (`<feature>: notifications: {<name>: settings}`, as `alerts` for ready-made alerts; `schema._device` takes it out before the feature's schema): no entity, an automation each (`notifications.py`), default texts in the translations' `common`. An alert is what's critical and lasts; a notification is news told once.
  - `tests/test_features.py` is a contract test over every entry in `FEATURES` and `DEVICE_KEYS`. It checks translations and icons for each entity key, that the example is valid, and more. A new feature gets checked there without changes to the test.
- **Entity IDs are the identity:**
  - Every entity is `<platform>.pururu_<device key>_<namespace>_<entity key>` (a ready-made notification's automation `automation.pururu_<device key>_<namespace>_notification_<name>`) (no exception, even for a key alike its namespace: a switch keyed `switch` is `switch.pururu_pool_switch_switch`; so a feature's fixed entity keys never repeat its namespace, as phases' `current`), and its unique ID is the part after the platform (`Device.object_id`). `build.build` hands each feature a `Device` in its namespace, so features write local entity keys; the translation key is the key in its namespace (`appliance_running`).
  - An ID already held by another integration is logged as an error and not created. Anything that follows it (`sources`) is dropped too (`build.creatable`); IDs are never suffixed with `_2`.
  - A user rename in the UI is followed: `current_entity_id`, plus a registry listener that reloads the entry (also on the rename of any script or automation it generates).
- **Floors and areas** (`places.py`):
  - HA's registries accept no ID, so a new floor or area is created named after its YAML key (the ID becomes the key), then renamed.
  - Anything with a configured ID is adopted and synced.
  - The IDs the entry manages live in `entry.data` (`{"floors": [...], "areas": [...], "automations": [...], "scripts": [...]}`, the last two the IDs of the reactions' automations and the programs' scripts). What the YAML drops is deleted, and `async_remove_entry` deletes everything the entry manages.
  - Names HA refuses are logged errors and never fail the setup.
- **Dashboard** (`dashboard.py`):
  - HA has no public API for an integration's dashboard. A `LovelaceConfig` subclass goes in `hass.data[LOVELACE_DATA].dashboards["pururu"]`, and a `lovelace` panel in `yaml` mode (read-only in the UI) shows it. This is private lovelace API: keep every use of it in this module.
  - The config is built at every fetch from `entry.data` and the registries. A registry change fires `lovelace_updated` twice, because the frontend ignores the first one after a yaml fetch.
  - Anything that prevents it (`/pururu` taken, lovelace changed) is a logged error, never a failed setup.
- **Events** (`events.py`): `pururu: events:` lists `state_changed` and `reading`, none by default. Each state change of an entity the entry created is fired on HA's bus as `pururu_state_changed` (no `state_class`) or `pururu_reading` (one), with `event_id` (ULID), `event_name` (`<device>.<key>`), `event_class`, the change, and `states` (the device's states when fired). Not fired: an entity appearing or going, HA's restored placeholder either way (a reload writes one), attributes alone. The key comes from the device that built the entity, never from parsing its ID. pururu speaks no HTTP: a user's automation with a `rest_command` posts them (docs: `concepts/events`).
- **Voluptuous gotcha:** `CONFIG_SCHEMA` uses `extra=vol.ALLOW_EXTRA` at the top level. It propagates into plain nested dicts, so a nested mapping that must refuse unknown or non-slug keys needs its own `vol.Schema(...)`.

## Tests

- **`ha` fixture** (`tests/conftest.py`): it freezes time at a fixed Wednesday 10:00 and puts the repo's `custom_components` on HA's loader path.
- **Loading integration modules:** use `helpers.module("<name>")` after the fixture, not a top-level import.
- **Helpers in `tests/helpers.py`:**
  - `setup` and `reload` take devices, plus `floors=`, `areas=`, `events=` (`pururu: events:`) and `config=` (`pururu: config:`).
  - `restart` restores saved state (a `(State, extra data)` per entity), plus `config=`.
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
