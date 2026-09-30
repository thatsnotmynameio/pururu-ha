# Floors and Areas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** pururu creates Home Assistant floors and areas from `pururu: floors:` / `pururu: areas:` in YAML, each with the ID its key gives it, keeps them following the configuration, and deletes the ones the configuration drops.

**Architecture:** A new module `places.py` owns floors and areas: the blocks' schemas and one `async_sync` that deletes what the configuration dropped, then creates (named after the key, then renamed) or adopts and updates every configured floor, then every area. The config entry calls it at the start of `async_setup_entry`, before the devices, and keeps the IDs it manages in `entry.data`; `async_remove_entry` deletes them.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3 (`homeassistant.helpers.floor_registry`, `area_registry`), voluptuous, pytest with `pytest-homeassistant-custom-component`, uv.

**Spec:** `docs/superpowers/specs/2026-09-26-floors-areas-design.md`

## Global Constraints

- Version: `custom_components/pururu/manifest.json` `version` → `0.1.1`.
- Public registry API only: `async_create`, `async_update`, `async_delete`, `async_get_floor`, `async_get_area`. Never write to `registry.floors[...]` / `registry.areas[...]`.
- A floor's or area's ID is its YAML key (`cv.slug`); a new one is created with `name=<key>` and then renamed.
- Whatever has a configured ID is adopted: every configured field is written on each setup; an omitted optional field is cleared (`None`, or an empty set for aliases).
- Nothing about floors and areas fails the entry's setup: every problem is a logged error, and the rest is still created.
- `entry.data` is exactly `{"floors": [<ids>], "areas": [<ids>]}` after a setup.
- `uv run pytest` must pass: it also runs ruff check, ruff format, mypy (strict, core's settings), hassfest and the quality-scale check on `custom_components/pururu`.
- Code style: follow the surrounding code (short docstrings, `_LOGGER.error` with `%s`, imports `area_registry as ar`, `floor_registry as fr`, `config_validation as cv`).

## Review Focus

1. A managed floor the user deleted in the UI → recreated with the same ID at the next start/reload (Task 1: `test_a_managed_floor_deleted_in_the_ui_comes_back`).
2. Two configured floors whose names differ only in case or spaces ("Térreo", "térreo") → the first is created, the second is a logged error (Task 1: `test_two_configured_floors_with_the_same_name`).
3. Two managed floors swapping names on a reload → logged errors, nothing raises, the rest is still set up (Task 1: `test_swapping_names_is_logged_not_raised`).
4. An invalid reload (an area on a floor not in `floors:`) → the running floors and areas are kept (Task 2: `test_invalid_reload_keeps_floors_and_areas`).
5. Floors and areas next to devices → the devices are created as before, one entry owns everything (Task 2: `test_floors_and_areas_next_to_devices`).

---

## File Structure

- Create `custom_components/pururu/places.py` — floors and areas only: `FLOOR_SCHEMA`, `AREA_SCHEMA`, `floors_exist`, `async_sync`, `async_remove`.
- Modify `custom_components/pururu/const.py` — `CONF_FLOORS`, `CONF_AREAS`, `CONF_FLOOR`, `CONF_LEVEL`, `CONF_ALIASES`; `DATA_DEVICES` → `DATA_CONFIG`.
- Modify `custom_components/pururu/__init__.py` — schema, `_async_apply`, `async_setup_entry`, new `async_remove_entry`.
- Modify `custom_components/pururu/manifest.json` — version.
- Modify `custom_components/pururu/translations/en.json`, `pt-BR.json` — the reload service's description.
- Modify `README.md` — a **Floors and areas** section.
- Modify `tests/helpers.py` — `setup` / `reload` take `floors=` and `areas=`.
- Create `tests/test_places.py` — every floor/area test.

---

### Task 1: `places.py` — sync floors and areas with the registries

**Files:**
- Modify: `custom_components/pururu/const.py`
- Create: `custom_components/pururu/places.py`
- Test: `tests/test_places.py` (create)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces (used by Task 2):
  - `const.CONF_FLOORS = "floors"`, `CONF_AREAS = "areas"`, `CONF_FLOOR = "floor"`, `CONF_LEVEL = "level"`, `CONF_ALIASES = "aliases"`.
  - `places.FLOOR_SCHEMA`, `places.AREA_SCHEMA`: `vol.Schema` for one floor's / area's block.
  - `places.floors_exist(config: dict[str, Any]) -> dict[str, Any]`: raises `vol.Invalid` when an area's `floor` is not a key of `config["floors"]`.
  - `places.async_sync(hass, floors: Mapping[str, dict[str, Any]], areas: Mapping[str, dict[str, Any]], managed: Mapping[str, Any]) -> dict[str, list[str]]` (`@callback`): returns `{"floors": [...], "areas": [...]}`.
  - `places.async_remove(hass, managed: Mapping[str, Any]) -> None` (`@callback`).

- [ ] **Step 1: Add the constants**

In `custom_components/pururu/const.py`, after `CONF_DEVICES: Final = "devices"`, add:

```python
CONF_FLOORS: Final = "floors"
CONF_AREAS: Final = "areas"
# Keys of a floor's or an area's block (name and icon are HA's CONF_NAME, CONF_ICON)
CONF_FLOOR: Final = "floor"
CONF_LEVEL: Final = "level"
CONF_ALIASES: Final = "aliases"
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_places.py`:

```python
"""pururu: floors and areas from the configuration, with the IDs their keys give them."""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, floor_registry as fr
import pytest

from helpers import module

TERREO = {"name": "Térreo", "level": 0, "icon": "mdi:home-floor-0", "aliases": ["embaixo"]}
ATELIE = {"name": "Ateliê", "floor": "terreo", "icon": "mdi:palette", "aliases": ["copa"]}


def sync(hass: HomeAssistant, floors: dict[str, Any], areas: dict[str, Any],
         managed: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """places.async_sync on validated blocks, as the entry calls it."""
    places = module("places")
    return places.async_sync(
        hass,
        {key: places.FLOOR_SCHEMA(block) for key, block in floors.items()},
        {key: places.AREA_SCHEMA(block) for key, block in areas.items()},
        managed or {},
    )


def floor(hass: HomeAssistant, floor_id: str) -> fr.FloorEntry | None:
    return fr.async_get(hass).async_get_floor(floor_id)


def area(hass: HomeAssistant, area_id: str) -> ar.AreaEntry | None:
    return ar.async_get(hass).async_get_area(area_id)


def errors(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(r.getMessage() for r in caplog.records if r.levelname == "ERROR")


# --- sync ------------------------------------------------------------------------


async def test_floor_and_area_get_the_ids_of_their_keys(ha: HomeAssistant) -> None:
    managed = sync(ha, {"terreo": TERREO}, {"atelie": ATELIE})
    assert managed == {"floors": ["terreo"], "areas": ["atelie"]}
    created = floor(ha, "terreo")
    assert created is not None
    assert (created.name, created.level, created.icon, created.aliases) == (
        "Térreo", 0, "mdi:home-floor-0", {"embaixo"})
    atelier = area(ha, "atelie")
    assert atelier is not None
    assert (atelier.name, atelier.floor_id, atelier.icon, atelier.aliases) == (
        "Ateliê", "terreo", "mdi:palette", {"copa"})


async def test_an_area_without_a_floor(ha: HomeAssistant) -> None:
    assert sync(ha, {}, {"patio": {"name": "Pátio"}}) == {"floors": [], "areas": ["patio"]}
    orchard = area(ha, "patio")
    assert orchard is not None
    assert orchard.floor_id is None


async def test_what_has_the_id_is_adopted_and_follows_the_configuration(ha: HomeAssistant) -> None:
    floors = fr.async_get(ha)
    areas = ar.async_get(ha)
    assert floors.async_create("Terreo", level=3, icon="mdi:home", aliases={"velho"}).floor_id == "terreo"
    basement = floors.async_create("Porão")
    assert areas.async_create("Ateliê", floor_id=basement.floor_id, icon="mdi:home",
                              aliases={"velha"}).id == "atelie"

    managed = sync(ha, {"terreo": {"name": "Térreo"}},
                   {"atelie": {"name": "Ateliê nova", "floor": "terreo"}})

    assert managed == {"floors": ["terreo"], "areas": ["atelie"]}
    adopted = floor(ha, "terreo")
    assert adopted is not None
    assert (adopted.name, adopted.level, adopted.icon, adopted.aliases) == ("Térreo", None, None, set())
    atelier = area(ha, "atelie")
    assert atelier is not None
    assert (atelier.name, atelier.floor_id, atelier.icon, atelier.aliases) == (
        "Ateliê nova", "terreo", None, set())
    assert floor(ha, basement.floor_id) == basement  # not configured: untouched


async def test_what_the_configuration_drops_is_deleted_and_the_rest_kept(ha: HomeAssistant) -> None:
    theirs = fr.async_get(ha).async_create("Sótão")
    managed = sync(ha, {"terreo": TERREO, "primeiro": {"name": "Primeiro andar"}},
                   {"atelie": ATELIE, "quarto": {"name": "Quarto", "floor": "primeiro"}})
    renamed = {**ATELIE, "name": "Ateliê grande"}

    managed = sync(ha, {"terreo": TERREO}, {"atelie": renamed}, managed)

    assert managed == {"floors": ["terreo"], "areas": ["atelie"]}
    assert floor(ha, "primeiro") is None
    assert area(ha, "quarto") is None
    atelier = area(ha, "atelie")
    assert atelier is not None
    assert (atelier.name, atelier.floor_id) == ("Ateliê grande", "terreo")
    assert floor(ha, theirs.floor_id) == theirs  # never managed: kept


async def test_a_new_id_for_the_same_name(ha: HomeAssistant) -> None:
    managed = sync(ha, {"terreo": {"name": "Térreo"}}, {"atelie": {"name": "Ateliê", "floor": "terreo"}})

    managed = sync(ha, {"mezzanine": {"name": "Térreo"}},
                   {"atelier": {"name": "Ateliê", "floor": "mezzanine"}}, managed)

    assert managed == {"floors": ["mezzanine"], "areas": ["atelier"]}
    assert floor(ha, "terreo") is None
    assert area(ha, "atelie") is None
    mezzanine = floor(ha, "mezzanine")
    assert mezzanine is not None
    assert mezzanine.name == "Térreo"
    atelier = area(ha, "atelier")
    assert atelier is not None
    assert atelier.floor_id == "mezzanine"


async def test_a_name_another_floor_has_is_an_error_and_the_rest_is_created(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    theirs = fr.async_get(ha).async_create("Térreo")  # ID terreo, not configured

    managed = sync(ha, {"mezzanine": {"name": "Térreo"}, "first": {"name": "Primeiro"}},
                   {"atelier": {"name": "Ateliê", "floor": "mezzanine"},
                    "bedroom": {"name": "Quarto", "floor": "first"}})

    assert managed == {"floors": ["first"], "areas": ["bedroom"]}
    assert floor(ha, "mezzanine") is None
    assert area(ha, "atelier") is None
    assert floor(ha, theirs.floor_id) == theirs
    bedroom = area(ha, "bedroom")
    assert bedroom is not None
    assert bedroom.floor_id == "first"
    assert "mezzanine" in errors(caplog)
    assert "atelier" in errors(caplog)


async def test_a_name_another_area_has_is_an_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    theirs = ar.async_get(ha).async_create("Ateliê")  # ID atelie, not configured

    assert sync(ha, {}, {"atelier": {"name": "Ateliê"}}) == {"floors": [], "areas": []}

    assert area(ha, "atelier") is None
    assert area(ha, theirs.id) == theirs
    assert "atelier" in errors(caplog)


async def test_a_key_that_is_another_floors_name_leaves_nothing_behind(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    floors = fr.async_get(ha)
    theirs = floors.async_update(floors.async_create("Mezzanine").floor_id, name="Terreo")
    assert theirs.floor_id == "mezzanine"

    assert sync(ha, {"terreo": {"name": "Térreo"}}, {}) == {"floors": [], "areas": []}

    assert [f.floor_id for f in floors.async_list_floors()] == ["mezzanine"]
    assert "terreo" in errors(caplog)


async def test_a_managed_floor_deleted_in_the_ui_comes_back(ha: HomeAssistant) -> None:
    managed = sync(ha, {"terreo": TERREO}, {})
    fr.async_get(ha).async_delete("terreo")

    assert sync(ha, {"terreo": TERREO}, {}, managed) == {"floors": ["terreo"], "areas": []}

    back = floor(ha, "terreo")
    assert back is not None
    assert back.name == "Térreo"


async def test_two_configured_floors_with_the_same_name(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    managed = sync(ha, {"terreo": {"name": "Térreo"}, "terreo_bis": {"name": "térreo"}}, {})

    assert managed == {"floors": ["terreo"], "areas": []}
    assert floor(ha, "terreo_bis") is None
    assert "terreo_bis" in errors(caplog)


async def test_swapping_names_is_logged_not_raised(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    managed = sync(ha, {"a": {"name": "Um"}, "b": {"name": "Dois"}, "c": {"name": "Três"}}, {})

    managed = sync(ha, {"a": {"name": "Dois"}, "b": {"name": "Um"}, "c": {"name": "Três"}}, {}, managed)

    assert managed == {"floors": ["c"], "areas": []}
    assert "Floor a is left out" in errors(caplog)
    assert "Floor b is left out" in errors(caplog)


async def test_remove_deletes_only_what_is_managed(ha: HomeAssistant) -> None:
    theirs = fr.async_get(ha).async_create("Sótão")
    their_area = ar.async_get(ha).async_create("Garagem")
    managed = sync(ha, {"terreo": TERREO}, {"atelie": ATELIE})

    module("places").async_remove(ha, managed)

    assert floor(ha, "terreo") is None
    assert area(ha, "atelie") is None
    assert floor(ha, theirs.floor_id) == theirs
    assert area(ha, their_area.id) == their_area
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_places.py -p no:xdist -v`
Expected: every test FAILS with `ModuleNotFoundError: No module named 'custom_components.pururu.places'`.

- [ ] **Step 4: Write `places.py`**

Create `custom_components/pururu/places.py`:

```python
"""Floors and areas configured in YAML, with the IDs their keys give them.

HA's registries take no ID: they make one from the name. A floor or area that
doesn't exist yet is created named after its key, so that the key is its ID,
then renamed. Whatever has a configured ID follows the configuration, whoever
created it; what the entry managed and the configuration dropped is deleted.
"""

from collections.abc import Callable, Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_ICON, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    config_validation as cv,
    floor_registry as fr,
)

from .const import CONF_ALIASES, CONF_AREAS, CONF_FLOOR, CONF_FLOORS, CONF_LEVEL

_LOGGER = logging.getLogger(__name__)

_ALIASES = vol.All(cv.ensure_list, [cv.string])

FLOOR_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Optional(CONF_LEVEL): int,
        vol.Optional(CONF_ICON): cv.icon,
        vol.Optional(CONF_ALIASES, default=[]): _ALIASES,
    }
)
AREA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Optional(CONF_FLOOR): cv.slug,
        vol.Optional(CONF_ICON): cv.icon,
        vol.Optional(CONF_ALIASES, default=[]): _ALIASES,
    }
)


def floors_exist(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse an area on a floor the configuration doesn't declare."""
    for area_id, area in config[CONF_AREAS].items():
        floor_id = area.get(CONF_FLOOR)
        if floor_id is not None and floor_id not in config[CONF_FLOORS]:
            raise vol.Invalid(f"area {area_id}: floor {floor_id} is not in floors")
    return config


@callback
def async_sync(
    hass: HomeAssistant,
    floors: Mapping[str, dict[str, Any]],
    areas: Mapping[str, dict[str, Any]],
    managed: Mapping[str, Any],
) -> dict[str, list[str]]:
    """Make the registries follow the configuration; the IDs managed from now on.

    Deletes first, so that a name a dropped floor or area had is free again. A
    floor or area HA refuses is logged and left out, and so is an area on such
    a floor.
    """
    floor_registry = fr.async_get(hass)
    area_registry = ar.async_get(hass)
    for area_id in managed.get(CONF_AREAS, []):
        if area_id not in areas and area_registry.async_get_area(area_id):
            area_registry.async_delete(area_id)
    for floor_id in managed.get(CONF_FLOORS, []):
        if floor_id not in floors and floor_registry.async_get_floor(floor_id):
            floor_registry.async_delete(floor_id)
    kept_floors = [
        floor_id
        for floor_id, config in floors.items()
        if _floor(floor_registry, floor_id, config)
    ]
    kept_areas: list[str] = []
    for area_id, config in areas.items():
        floor_id = config.get(CONF_FLOOR)
        if floor_id is not None and floor_id not in kept_floors:
            _LOGGER.error(
                "Area %s is left out: its floor %s is not created", area_id, floor_id
            )
        elif _area(area_registry, area_id, config):
            kept_areas.append(area_id)
    return {CONF_FLOORS: kept_floors, CONF_AREAS: kept_areas}


@callback
def async_remove(hass: HomeAssistant, managed: Mapping[str, Any]) -> None:
    """Delete every floor and area `managed` lists that still exists."""
    async_sync(hass, {}, {}, managed)


def _floor(registry: fr.FloorRegistry, floor_id: str, config: dict[str, Any]) -> bool:
    """Whether the floor exists now, as configured."""

    def update() -> None:
        registry.async_update(
            floor_id,
            name=config[CONF_NAME],
            level=config.get(CONF_LEVEL),
            icon=config.get(CONF_ICON),
            aliases=set(config[CONF_ALIASES]),
        )

    return _follow(
        "Floor",
        floor_id,
        exists=registry.async_get_floor(floor_id) is not None,
        create=lambda name: registry.async_create(name).floor_id,
        delete=registry.async_delete,
        update=update,
    )


def _area(registry: ar.AreaRegistry, area_id: str, config: dict[str, Any]) -> bool:
    """Whether the area exists now, as configured."""

    def update() -> None:
        registry.async_update(
            area_id,
            name=config[CONF_NAME],
            floor_id=config.get(CONF_FLOOR),
            icon=config.get(CONF_ICON),
            aliases=set(config[CONF_ALIASES]),
        )

    return _follow(
        "Area",
        area_id,
        exists=registry.async_get_area(area_id) is not None,
        create=lambda name: registry.async_create(name).id,
        delete=registry.async_delete,
        update=update,
    )


def _follow(
    kind: str,
    place_id: str,
    *,
    exists: bool,
    create: Callable[[str], str],
    delete: Callable[[str], None],
    update: Callable[[], None],
) -> bool:
    """Create `place_id` if missing, then update it; False, logged, if HA refuses.

    HA refuses a name another floor (or area) already has, whitespace and case
    aside: creating one named after the key, or renaming it.
    """
    if not exists:
        try:
            new_id = create(place_id)
        except ValueError as err:
            return _left_out(kind, place_id, err)
        if new_id != place_id:  # can't happen for a free slug; never keep a stray
            delete(new_id)
            return _left_out(kind, place_id, f"HA gave it the ID {new_id}")
    try:
        update()
    except ValueError as err:
        if not exists:
            delete(place_id)
        return _left_out(kind, place_id, err)
    return True


def _left_out(kind: str, place_id: str, reason: object) -> bool:
    """Log why a floor or area is not created; False."""
    _LOGGER.error("%s %s is left out: %s", kind, place_id, reason)
    return False
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_places.py -p no:xdist -v`
Expected: all 12 tests PASS.

If `test_swapping_names_is_logged_not_raised` fails on `managed`, check the order: renaming `a` to "Dois" fails because `b` is still "Dois"; renaming `b` to "Um" fails because `a` is still "Um". Both are left out; `c` is kept.

- [ ] **Step 6: Lint, format, type-check**

Run: `uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu && uv run pytest tests/test_code.py -p no:xdist -v`
Expected: PASS. Fix whatever ruff or mypy reports in `places.py` without changing behaviour (e.g. if ruff's PERF401 flags the areas loop, keep the loop and restructure only as ruff suggests).

- [ ] **Step 7: Commit**

```bash
git add custom_components/pururu/const.py custom_components/pururu/places.py tests/test_places.py
git commit -m "places: floors and areas that follow the configuration, with the IDs of their keys"
```

---

### Task 2: The configuration and the entry own floors and areas; version 0.1.1

**Files:**
- Modify: `custom_components/pururu/const.py` (the `DATA_DEVICES` line)
- Modify: `custom_components/pururu/__init__.py`
- Modify: `custom_components/pururu/manifest.json`
- Modify: `custom_components/pururu/translations/en.json`, `custom_components/pururu/translations/pt-BR.json`
- Modify: `README.md`
- Modify: `tests/helpers.py`
- Test: `tests/test_places.py` (append)

**Interfaces:**
- Consumes (Task 1): `const.CONF_FLOORS`, `CONF_AREAS`; `places.FLOOR_SCHEMA`, `places.AREA_SCHEMA`, `places.floors_exist`, `places.async_sync(hass, floors, areas, managed) -> dict[str, list[str]]`, `places.async_remove(hass, managed) -> None`.
- Produces:
  - `const.DATA_CONFIG: HassKey[dict[str, Any]]` — the validated `pururu:` block (replaces `DATA_DEVICES`).
  - `helpers.setup(hass, devices, *, floors=None, areas=None) -> bool`, `helpers.reload(hass, devices, *, floors=None, areas=None) -> None`.
  - `entry.data == {"floors": [...], "areas": [...]}` after every setup.

- [ ] **Step 1: Let the test helpers take floors and areas**

In `tests/helpers.py`, replace `setup` and `reload` with:

```python
def _config(devices: dict[str, Any], floors: dict[str, Any] | None,
            areas: dict[str, Any] | None) -> dict[str, Any]:
    """A configuration.yaml with this `pururu:` block."""
    return {DOMAIN: {"devices": devices, "floors": floors or {}, "areas": areas or {}}}


async def setup(hass: HomeAssistant, devices: dict[str, Any], *,
                floors: dict[str, Any] | None = None,
                areas: dict[str, Any] | None = None) -> bool:
    """Set pururu up from `pururu:`; False when HA refuses the configuration."""
    ok = await async_setup_component(hass, DOMAIN, _config(devices, floors, areas))
    await hass.async_block_till_done()
    return ok


async def reload(hass: HomeAssistant, devices: dict[str, Any], *,
                 floors: dict[str, Any] | None = None,
                 areas: dict[str, Any] | None = None) -> None:
    """pururu.reload, with a configuration.yaml holding this `pururu:` block."""
    config = _config(devices, floors, areas)
    with patch("homeassistant.config.load_yaml_config_file", return_value=config):
        await hass.services.async_call(DOMAIN, "reload", blocking=True)
        await hass.async_block_till_done()
```

- [ ] **Step 2: Write the failing tests**

In `tests/test_places.py`, change the helpers import to:

```python
from homeassistant.config_entries import ConfigEntryState

from helpers import DOMAIN, device_of, module, reload, setup
```

(keep `ConfigEntryState` with the other `homeassistant` imports, above `import pytest`), and append:

```python
# --- the configuration and the entry ----------------------------------------------


async def test_floors_and_areas_alone_create_the_entry(ha: HomeAssistant) -> None:
    assert await setup(ha, {}, floors={"terreo": TERREO}, areas={"atelie": ATELIE})
    [entry] = ha.config_entries.async_entries(DOMAIN)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data == {"floors": ["terreo"], "areas": ["atelie"]}
    atelier = area(ha, "atelie")
    assert atelier is not None
    assert atelier.floor_id == "terreo"


async def test_floors_and_areas_next_to_devices(ha: HomeAssistant) -> None:
    appliance = module("features").FEATURES["appliance"].example
    assert await setup(ha, {"dummy_washer": {"name": "Washer", "appliance": appliance}},
                       floors={"terreo": TERREO}, areas={"atelie": ATELIE})
    assert len(ha.config_entries.async_entries(DOMAIN)) == 1
    assert device_of(ha, "dummy_washer") is not None
    assert floor(ha, "terreo") is not None


async def test_a_reload_that_drops_a_floor_deletes_it(ha: HomeAssistant) -> None:
    assert await setup(ha, {}, floors={"terreo": TERREO, "primeiro": {"name": "Primeiro"}},
                       areas={"atelie": ATELIE})
    await reload(ha, {}, floors={"terreo": TERREO})
    assert floor(ha, "primeiro") is None
    assert area(ha, "atelie") is None
    assert floor(ha, "terreo") is not None
    [entry] = ha.config_entries.async_entries(DOMAIN)
    assert entry.data == {"floors": ["terreo"], "areas": []}


async def test_a_reload_without_anything_deletes_them_all(ha: HomeAssistant) -> None:
    assert await setup(ha, {}, floors={"terreo": TERREO}, areas={"atelie": ATELIE})
    await reload(ha, {})
    assert floor(ha, "terreo") is None
    assert area(ha, "atelie") is None


@pytest.mark.parametrize(("floors", "areas"), [
    pytest.param({}, {"atelie": ATELIE}, id="area on a floor not in floors"),
    pytest.param({"terreo": {"level": 0}}, {}, id="floor without a name"),
    pytest.param({"terreo": {**TERREO, "level": "mezzanine"}}, {}, id="level not an integer"),
    pytest.param({"terreo": {**TERREO, "colour": "red"}}, {}, id="unknown floor key"),
    pytest.param({}, {"patio": {"name": "Pátio", "picture": "x"}}, id="unknown area key"),
    pytest.param({"Térreo": TERREO}, {}, id="key not a slug"),
])
async def test_invalid_floors_and_areas_are_refused(
        ha: HomeAssistant, floors: dict[str, Any], areas: dict[str, Any]) -> None:
    assert not await setup(ha, {}, floors=floors, areas=areas)
    assert not ha.config_entries.async_entries(DOMAIN)
    assert not list(fr.async_get(ha).async_list_floors())


async def test_invalid_reload_keeps_floors_and_areas(ha: HomeAssistant) -> None:
    assert await setup(ha, {}, floors={"terreo": TERREO}, areas={"atelie": ATELIE})
    await reload(ha, {}, areas={"atelie": ATELIE})  # its floor is no longer declared
    assert floor(ha, "terreo") is not None
    atelier = area(ha, "atelie")
    assert atelier is not None
    assert atelier.floor_id == "terreo"


async def test_deleting_the_entry_deletes_only_its_floors_and_areas(ha: HomeAssistant) -> None:
    theirs = fr.async_get(ha).async_create("Sótão")
    their_area = ar.async_get(ha).async_create("Garagem")
    assert await setup(ha, {}, floors={"terreo": TERREO}, areas={"atelie": ATELIE})
    [entry] = ha.config_entries.async_entries(DOMAIN)
    await ha.config_entries.async_remove(entry.entry_id)
    await ha.async_block_till_done()
    assert floor(ha, "terreo") is None
    assert area(ha, "atelie") is None
    assert floor(ha, theirs.floor_id) == theirs
    assert area(ha, their_area.id) == their_area
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_places.py -p no:xdist -v`
Expected: the 12 Task 1 tests PASS. The new ones FAIL: `setup` returns False, because `floors` and `areas` are unknown keys under `pururu:` (`extra keys not allowed`). `test_invalid_floors_and_areas_are_refused` may pass for the wrong reason, which is fine.

- [ ] **Step 4: Replace `DATA_DEVICES` with `DATA_CONFIG`**

In `custom_components/pururu/const.py`, replace:

```python
# The configured devices, from async_setup (and each reload) to the entry
DATA_DEVICES: HassKey[dict[str, dict[str, Any]]] = HassKey(DOMAIN)
```

with:

```python
# The validated `pururu:` block, from async_setup (and each reload) to the entry
DATA_CONFIG: HassKey[dict[str, Any]] = HassKey(DOMAIN)
```

- [ ] **Step 5: Wire `places` into `__init__.py`**

In `custom_components/pururu/__init__.py`:

5a. Replace the module docstring with:

```python
"""pururu: floors, areas and devices configured in YAML, which the integration creates.

`pururu: floors:` and `areas:` map an ID to a floor or an area (places.py).
`pururu: devices:` maps a device key to its name and features (features/).
From the real entities and settings in a feature's block, the feature creates
the device's entities. One config entry owns every floor, area, device and entity.
"""
```

5b. Replace the `.const` import and add `places` (keep the existing `.entity`, `.feature`, `.features` imports):

```python
from . import places
from .const import (
    CONF_AREAS,
    CONF_DEVICES,
    CONF_FLOORS,
    DATA_CONFIG,
    DOMAIN,
    PLATFORMS,
)
```

5c. Replace `CONFIG_SCHEMA` (keep its comment line above it) with:

```python
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(
            {
                vol.Optional(CONF_FLOORS, default={}): {
                    cv.slug: places.FLOOR_SCHEMA
                },
                vol.Optional(CONF_AREAS, default={}): {cv.slug: places.AREA_SCHEMA},
                vol.Optional(CONF_DEVICES, default={}): {cv.slug: _device},
            },
            places.floors_exist,
        )
    },
    extra=vol.ALLOW_EXTRA,
)
```

5d. In `async_setup`, change the docstring to `"""Keep the configuration for the entry, and apply it again on reload."""`.

5e. In `_async_apply`, change the first docstring line to `"""Keep the configuration; set the entry up again, or create it the first time.`, and replace

```python
    hass.data[DATA_DEVICES] = config.get(DOMAIN, {}).get(CONF_DEVICES, {})
```

with

```python
    hass.data[DATA_CONFIG] = config.get(DOMAIN, {})
```

and

```python
    elif hass.data[DATA_DEVICES]:
```

with

```python
    elif any(
        hass.data[DATA_CONFIG].get(key)
        for key in (CONF_FLOORS, CONF_AREAS, CONF_DEVICES)
    ):
```

5f. Replace the start of `async_setup_entry`, from its docstring to `devices = hass.data.get(DATA_DEVICES, {})`, with:

```python
async def async_setup_entry(hass: HomeAssistant, entry: PururuConfigEntry) -> bool:
    """Make floors and areas follow the configuration, then build every device.

    Floors and areas come first: devices will be placed in them.
    """
    config = hass.data.get(DATA_CONFIG, {})
    managed = places.async_sync(
        hass, config.get(CONF_FLOORS, {}), config.get(CONF_AREAS, {}), entry.data
    )
    hass.config_entries.async_update_entry(entry, data=managed)
    registry = er.async_get(hass)
    devices = config.get(CONF_DEVICES, {})
```

(The rest of `async_setup_entry` is unchanged.)

5g. After `async_unload_entry`, add:

```python
async def async_remove_entry(hass: HomeAssistant, entry: PururuConfigEntry) -> None:
    """Delete the floors and areas the entry managed."""
    places.async_remove(hass, entry.data)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_places.py tests/test_init.py tests/test_appliance.py tests/test_phases.py -p no:xdist -v`
Expected: all PASS; the existing device tests are unchanged in behaviour.

- [ ] **Step 7: Version, service description, README**

7a. `custom_components/pururu/manifest.json`: `"version": "0.1.0"` → `"version": "0.1.1"`.

7b. `custom_components/pururu/translations/en.json`: the reload description becomes `"Reloads the floors, areas and devices from the YAML configuration."`.
`custom_components/pururu/translations/pt-BR.json`: `"Recarrega os andares, as áreas e os dispositivos da configuração YAML."`.

7c. `README.md`:
- First paragraph: replace `A Home Assistant integration that creates devices, and their entities, from real entities and a few settings.` with `A Home Assistant integration that creates floors, areas and devices, and the devices' entities, from real entities and a few settings.`
- Insert this section right before `## Features`:

````markdown
### Floors and areas

```yaml
pururu:
  floors:
    terreo:                  # the floor's ID in HA
      name: Térreo
      level: 0
      icon: mdi:home-floor-0
      aliases: [embaixo]
  areas:
    atelie:                 # the area's ID in HA
      name: Ateliê
      floor: terreo          # a key of floors:
      icon: mdi:palette
    patio:
      name: Pátio          # no floor
```

| Key | | |
|---|---|---|
| `name` | required | The name HA shows. |
| `level` | optional, floors | The floor's level: 0 the ground floor, negative below it. |
| `floor` | optional, areas | The area's floor: a key of `floors:`. |
| `icon`, `aliases` | optional | The icon (`mdi:…`) and other names, e.g. for voice assistants. |

- The key is the floor's or area's ID. HA makes IDs from names, so pururu creates a new one named after its key, then renames it.
- A floor or area with that ID follows the configuration at every start and reload, even one made in the UI: a key left out is cleared, and changes made in the UI are undone.
- A floor or area the configuration drops is deleted at the next reload, and deleting the integration deletes them all. HA then takes a deleted floor off its areas, and a deleted area off its devices and entities.
- A name that a floor or area not in the configuration already has (whitespace and case aside), or a key that is already such a name, is an error in the log: that floor or area is not created, nor the areas on that floor.
````

- [ ] **Step 8: The whole suite**

Run: `uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu && uv run pytest`
Expected: everything PASSES, including `tests/test_code.py` (ruff, format, mypy, hassfest, quality scale) and `tests/test_release.py` (0.1.1 is above the latest release).

- [ ] **Step 9: Commit**

```bash
git add custom_components/pururu/ README.md tests/helpers.py tests/test_places.py
git commit -m "pururu: floors and areas from YAML, owned by the entry; 0.1.1"
```
