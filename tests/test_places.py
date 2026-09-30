"""pururu: floors and areas from the configuration, with the IDs their keys give them."""

from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, floor_registry as fr
import pytest

from helpers import DOMAIN, device_of, module, reload, setup

TERREO = {"name": "Térreo", "level": 0, "icon": "mdi:home-floor-0", "aliases": ["embaixo"]}
ATELIE = {"name": "Ateliê", "floor": "terreo", "icon": "mdi:palette", "aliases": ["copa"]}


def sync(hass: HomeAssistant, floors: dict[str, Any], areas: dict[str, Any],
         managed: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """places.async_sync on validated blocks, as the entry calls it."""
    places = module("outputs.places")
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

    assert managed == {"floors": ["a", "b", "c"], "areas": []}
    assert "Floor a is not synced" in errors(caplog)
    assert "Floor b is not synced" in errors(caplog)


async def test_what_exists_but_is_not_synced_stays_managed(ha: HomeAssistant) -> None:
    managed = sync(ha, {"a": {"name": "Um"}, "b": {"name": "Dois"}},
                   {"x": {"name": "Biblioteca", "floor": "a"}})
    managed = sync(ha, {"a": {"name": "Dois"}, "b": {"name": "Um"}},
                   {"x": {"name": "Biblioteca grande", "floor": "a"}}, managed)
    assert managed == {"floors": ["a", "b"], "areas": ["x"]}
    room = area(ha, "x")
    assert room is not None
    assert (room.name, room.floor_id) == ("Biblioteca grande", "a")  # its floor exists

    assert sync(ha, {}, {}, managed) == {"floors": [], "areas": []}

    assert floor(ha, "a") is None
    assert floor(ha, "b") is None
    assert area(ha, "x") is None


async def test_an_adopted_floor_that_cannot_be_renamed_is_still_managed(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    floors = fr.async_get(ha)
    floors.async_create("Terreo")
    floors.async_create("Térreo velho")

    managed = sync(ha, {"terreo": {"name": "Térreo velho"}}, {})

    assert managed == {"floors": ["terreo"], "areas": []}
    assert "Floor terreo is not synced" in errors(caplog)


async def test_remove_deletes_only_what_is_managed(ha: HomeAssistant) -> None:
    theirs = fr.async_get(ha).async_create("Sótão")
    their_area = ar.async_get(ha).async_create("Garagem")
    managed = sync(ha, {"terreo": TERREO}, {"atelie": ATELIE})

    module("outputs.places").async_remove(ha, managed)

    assert floor(ha, "terreo") is None
    assert area(ha, "atelie") is None
    assert floor(ha, theirs.floor_id) == theirs
    assert area(ha, their_area.id) == their_area


# --- the configuration and the entry ----------------------------------------------


async def test_floors_and_areas_alone_create_the_entry(ha: HomeAssistant) -> None:
    assert await setup(ha, {}, floors={"terreo": TERREO}, areas={"atelie": ATELIE})
    [entry] = ha.config_entries.async_entries(DOMAIN)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data == {"floors": ["terreo"], "areas": ["atelie"], "automations": [], "scripts": []}
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
    assert entry.data == {"floors": ["terreo"], "areas": [], "automations": [], "scripts": []}


async def test_a_reload_without_anything_deletes_them_all(ha: HomeAssistant) -> None:
    assert await setup(ha, {}, floors={"terreo": TERREO}, areas={"atelie": ATELIE})
    await reload(ha, {})
    assert floor(ha, "terreo") is None
    assert area(ha, "atelie") is None


@pytest.mark.parametrize(("floors", "areas"), [
    pytest.param({}, {"atelie": ATELIE}, id="area on a floor not in floors"),
    pytest.param({"terreo": {"level": 0}}, {}, id="floor without a name"),
    pytest.param({"terreo": {**TERREO, "level": "mezzanine"}}, {}, id="level not an integer"),
    pytest.param({"terreo": {**TERREO, "level": True}}, {}, id="level a boolean"),
    pytest.param({"terreo": {**TERREO, "level": 1.5}}, {}, id="level a float"),
    pytest.param({"terreo": {**TERREO, "colour": "red"}}, {}, id="unknown floor key"),
    pytest.param({}, {"patio": {"name": "Pátio", "picture": "x"}}, id="unknown area key"),
    pytest.param({"Térreo": TERREO}, {}, id="key not a slug"),
])
async def test_invalid_floors_and_areas_are_refused(
        ha: HomeAssistant, floors: dict[str, Any], areas: dict[str, Any]) -> None:
    assert not await setup(ha, {}, floors=floors, areas=areas)
    assert not ha.config_entries.async_entries(DOMAIN)
    assert not list(fr.async_get(ha).async_list_floors())


async def test_an_unknown_key_under_pururu_is_refused_and_deletes_nothing(ha: HomeAssistant) -> None:
    assert await setup(ha, {}, floors={"terreo": TERREO})
    config = {DOMAIN: {"floor": {"terreo": TERREO}}}  # singular: a typo
    with patch("homeassistant.config.load_yaml_config_file", return_value=config):
        await ha.services.async_call(DOMAIN, "reload", blocking=True)
        await ha.async_block_till_done()
    assert floor(ha, "terreo") is not None


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
