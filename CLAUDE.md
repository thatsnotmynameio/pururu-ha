# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

pururu is a Home Assistant custom integration (`custom_components/pururu/`). It reads a `pururu:` YAML block and creates floors, areas and devices from it. It builds each device's entities from real entities and a few settings. The README is the user-facing reference for every configuration key and entity.

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
    3. Hand them to the platforms through `entry.runtime_data`. `sensor.py` and `binary_sensor.py` only call `async_add_entities`.
    4. Put each device in its `area:` (a key of `areas:`).
    5. Remove stale entities and devices.
- **Features** (`feature.py`, `features/`):
  - A device is a name plus one or more features. `FEATURES` in `features/__init__.py` maps each config key to a `Feature`. A `Feature` has a `schema`, the `metrics` it can create (metric → platform), `build()`, an `example` block, and the capabilities it `provides` and `requires`.
  - A feature consumes another feature's capability through `<capability>_from: <feature>`. `_build` passes it the current entity ID of the providing metric.
  - `tests/test_features.py` is a contract test over every entry in `FEATURES`. It checks translations and icons for each metric, that the example is valid, and more. A new feature gets checked there without changes to the test.
- **Entity IDs are the identity:**
  - Every entity is `<platform>.pururu_<device key>_<metric>`, and its unique ID is the part after the platform (`Device.object_id`).
  - An ID already held by another integration is logged as an error and not created. Anything that follows it (`sources`) is dropped too (`_creatable`); IDs are never suffixed with `_2`.
  - A user rename in the UI is followed: `current_entity_id`, plus a registry listener that reloads the entry.
- **Floors and areas** (`places.py`):
  - HA's registries accept no ID, so a new floor or area is created named after its YAML key (the ID becomes the key), then renamed.
  - Anything with a configured ID is adopted and synced.
  - The IDs the entry manages live in `entry.data` (`{"floors": [...], "areas": [...]}`). What the YAML drops is deleted, and `async_remove_entry` deletes everything the entry manages.
  - Names HA refuses are logged errors and never fail the setup.
- **Voluptuous gotcha:** `CONFIG_SCHEMA` uses `extra=vol.ALLOW_EXTRA` at the top level. It propagates into plain nested dicts, so a nested mapping that must refuse unknown or non-slug keys needs its own `vol.Schema(...)`.

## Tests

- **`ha` fixture** (`tests/conftest.py`): it freezes time at a fixed Wednesday 10:00 and puts the repo's `custom_components` on HA's loader path.
- **Loading integration modules:** use `helpers.module("<name>")` after the fixture, not a top-level import.
- **Helpers in `tests/helpers.py`:**
  - `setup` and `reload` take devices, plus `floors=` and `areas=`.
  - `restart` restores saved state.
  - `tick` and `fake` drive time and real-entity states.
  - `device_of` and `held` inspect the registries.

## Releases and CI

- **Releases:** the version is `version` in `custom_components/pururu/manifest.json`. A PR that changes it is a release. After it merges to `main`, the Release workflow tags `vX.Y.Z` and publishes a GitHub release, which HACS offers.
- **CI:** GitHub Actions are pinned by SHA. SonarQube Cloud runs on PRs.
- **Sonar suppressions:** a Sonar finding that conflicts with HA's required signatures or conventions is suppressed in `sonar-project.properties` (`sonar.issue.ignore.multicriteria`), with a comment giving the reason, not in code.
