"""pururu: floors and areas from the configuration, with the IDs their keys give them."""

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, floor_registry as fr
import pytest

from helpers import DOMAIN, device_of, module, reload, setup

TERREO = {"name": "Térreo", "level": 0, "icon": "mdi:home-floor-0", "aliases": ["embaixo"]}
COZINHA = {"name": "Cozinha", "floor": "terreo", "icon": "mdi:stove", "aliases": ["copa"]}


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
    managed = sync(ha, {"terreo": TERREO}, {"cozinha": COZINHA})
    assert managed == {"floors": ["terreo"], "areas": ["cozinha"]}
    created = floor(ha, "terreo")
    assert created is not None
    assert (created.name, created.level, created.icon, created.aliases) == (
        "Térreo", 0, "mdi:home-floor-0", {"embaixo"})
    kitchen = area(ha, "cozinha")
    assert kitchen is not None
    assert (kitchen.name, kitchen.floor_id, kitchen.icon, kitchen.aliases) == (
        "Cozinha", "terreo", "mdi:stove", {"copa"})


async def test_an_area_without_a_floor(ha: HomeAssistant) -> None:
    assert sync(ha, {}, {"quintal": {"name": "Quintal"}}) == {"floors": [], "areas": ["quintal"]}
    garden = area(ha, "quintal")
    assert garden is not None
    assert garden.floor_id is None


async def test_what_has_the_id_is_adopted_and_follows_the_configuration(ha: HomeAssistant) -> None:
    floors = fr.async_get(ha)
    areas = ar.async_get(ha)
    assert floors.async_create("Terreo", level=3, icon="mdi:home", aliases={"velho"}).floor_id == "terreo"
    basement = floors.async_create("Porão")
    assert areas.async_create("Cozinha", floor_id=basement.floor_id, icon="mdi:home",
                              aliases={"velha"}).id == "cozinha"

    managed = sync(ha, {"terreo": {"name": "Térreo"}},
                   {"cozinha": {"name": "Cozinha nova", "floor": "terreo"}})

    assert managed == {"floors": ["terreo"], "areas": ["cozinha"]}
    adopted = floor(ha, "terreo")
    assert adopted is not None
    assert (adopted.name, adopted.level, adopted.icon, adopted.aliases) == ("Térreo", None, None, set())
    kitchen = area(ha, "cozinha")
    assert kitchen is not None
    assert (kitchen.name, kitchen.floor_id, kitchen.icon, kitchen.aliases) == (
        "Cozinha nova", "terreo", None, set())
    assert floor(ha, basement.floor_id) == basement  # not configured: untouched


async def test_what_the_configuration_drops_is_deleted_and_the_rest_kept(ha: HomeAssistant) -> None:
    theirs = fr.async_get(ha).async_create("Sótão")
    managed = sync(ha, {"terreo": TERREO, "primeiro": {"name": "Primeiro andar"}},
                   {"cozinha": COZINHA, "quarto": {"name": "Quarto", "floor": "primeiro"}})
    renamed = {**COZINHA, "name": "Cozinha grande"}

    managed = sync(ha, {"terreo": TERREO}, {"cozinha": renamed}, managed)

    assert managed == {"floors": ["terreo"], "areas": ["cozinha"]}
    assert floor(ha, "primeiro") is None
    assert area(ha, "quarto") is None
    kitchen = area(ha, "cozinha")
    assert kitchen is not None
    assert (kitchen.name, kitchen.floor_id) == ("Cozinha grande", "terreo")
    assert floor(ha, theirs.floor_id) == theirs  # never managed: kept


async def test_a_new_id_for_the_same_name(ha: HomeAssistant) -> None:
    managed = sync(ha, {"terreo": {"name": "Térreo"}}, {"cozinha": {"name": "Cozinha", "floor": "terreo"}})

    managed = sync(ha, {"ground": {"name": "Térreo"}},
                   {"kitchen": {"name": "Cozinha", "floor": "ground"}}, managed)

    assert managed == {"floors": ["ground"], "areas": ["kitchen"]}
    assert floor(ha, "terreo") is None
    assert area(ha, "cozinha") is None
    ground = floor(ha, "ground")
    assert ground is not None
    assert ground.name == "Térreo"
    kitchen = area(ha, "kitchen")
    assert kitchen is not None
    assert kitchen.floor_id == "ground"


async def test_a_name_another_floor_has_is_an_error_and_the_rest_is_created(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    theirs = fr.async_get(ha).async_create("Térreo")  # ID terreo, not configured

    managed = sync(ha, {"ground": {"name": "Térreo"}, "first": {"name": "Primeiro"}},
                   {"kitchen": {"name": "Cozinha", "floor": "ground"},
                    "bedroom": {"name": "Quarto", "floor": "first"}})

    assert managed == {"floors": ["first"], "areas": ["bedroom"]}
    assert floor(ha, "ground") is None
    assert area(ha, "kitchen") is None
    assert floor(ha, theirs.floor_id) == theirs
    bedroom = area(ha, "bedroom")
    assert bedroom is not None
    assert bedroom.floor_id == "first"
    assert "ground" in errors(caplog)
    assert "kitchen" in errors(caplog)


async def test_a_name_another_area_has_is_an_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    theirs = ar.async_get(ha).async_create("Cozinha")  # ID cozinha, not configured

    assert sync(ha, {}, {"kitchen": {"name": "Cozinha"}}) == {"floors": [], "areas": []}

    assert area(ha, "kitchen") is None
    assert area(ha, theirs.id) == theirs
    assert "kitchen" in errors(caplog)


async def test_a_key_that_is_another_floors_name_leaves_nothing_behind(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    floors = fr.async_get(ha)
    theirs = floors.async_update(floors.async_create("Ground").floor_id, name="Terreo")
    assert theirs.floor_id == "ground"

    assert sync(ha, {"terreo": {"name": "Térreo"}}, {}) == {"floors": [], "areas": []}

    assert [f.floor_id for f in floors.async_list_floors()] == ["ground"]
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
    managed = sync(ha, {"terreo": TERREO}, {"cozinha": COZINHA})

    module("places").async_remove(ha, managed)

    assert floor(ha, "terreo") is None
    assert area(ha, "cozinha") is None
    assert floor(ha, theirs.floor_id) == theirs
    assert area(ha, their_area.id) == their_area


# --- the configuration and the entry ----------------------------------------------


async def test_floors_and_areas_alone_create_the_entry(ha: HomeAssistant) -> None:
    assert await setup(ha, {}, floors={"terreo": TERREO}, areas={"cozinha": COZINHA})
    [entry] = ha.config_entries.async_entries(DOMAIN)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data == {"floors": ["terreo"], "areas": ["cozinha"]}
    kitchen = area(ha, "cozinha")
    assert kitchen is not None
    assert kitchen.floor_id == "terreo"


async def test_floors_and_areas_next_to_devices(ha: HomeAssistant) -> None:
    appliance = module("features").FEATURES["appliance"].example
    assert await setup(ha, {"demo_washer": {"name": "Washer", "appliance": appliance}},
                       floors={"terreo": TERREO}, areas={"cozinha": COZINHA})
    assert len(ha.config_entries.async_entries(DOMAIN)) == 1
    assert device_of(ha, "demo_washer") is not None
    assert floor(ha, "terreo") is not None


async def test_a_reload_that_drops_a_floor_deletes_it(ha: HomeAssistant) -> None:
    assert await setup(ha, {}, floors={"terreo": TERREO, "primeiro": {"name": "Primeiro"}},
                       areas={"cozinha": COZINHA})
    await reload(ha, {}, floors={"terreo": TERREO})
    assert floor(ha, "primeiro") is None
    assert area(ha, "cozinha") is None
    assert floor(ha, "terreo") is not None
    [entry] = ha.config_entries.async_entries(DOMAIN)
    assert entry.data == {"floors": ["terreo"], "areas": []}


async def test_a_reload_without_anything_deletes_them_all(ha: HomeAssistant) -> None:
    assert await setup(ha, {}, floors={"terreo": TERREO}, areas={"cozinha": COZINHA})
    await reload(ha, {})
    assert floor(ha, "terreo") is None
    assert area(ha, "cozinha") is None


@pytest.mark.parametrize(("floors", "areas"), [
    pytest.param({}, {"cozinha": COZINHA}, id="area on a floor not in floors"),
    pytest.param({"terreo": {"level": 0}}, {}, id="floor without a name"),
    pytest.param({"terreo": {**TERREO, "level": "ground"}}, {}, id="level not an integer"),
    pytest.param({"terreo": {**TERREO, "colour": "red"}}, {}, id="unknown floor key"),
    pytest.param({}, {"quintal": {"name": "Quintal", "picture": "x"}}, id="unknown area key"),
    pytest.param({"Térreo": TERREO}, {}, id="key not a slug"),
])
async def test_invalid_floors_and_areas_are_refused(
        ha: HomeAssistant, floors: dict[str, Any], areas: dict[str, Any]) -> None:
    assert not await setup(ha, {}, floors=floors, areas=areas)
    assert not ha.config_entries.async_entries(DOMAIN)
    assert not list(fr.async_get(ha).async_list_floors())


async def test_invalid_reload_keeps_floors_and_areas(ha: HomeAssistant) -> None:
    assert await setup(ha, {}, floors={"terreo": TERREO}, areas={"cozinha": COZINHA})
    await reload(ha, {}, areas={"cozinha": COZINHA})  # its floor is no longer declared
    assert floor(ha, "terreo") is not None
    kitchen = area(ha, "cozinha")
    assert kitchen is not None
    assert kitchen.floor_id == "terreo"


async def test_deleting_the_entry_deletes_only_its_floors_and_areas(ha: HomeAssistant) -> None:
    theirs = fr.async_get(ha).async_create("Sótão")
    their_area = ar.async_get(ha).async_create("Garagem")
    assert await setup(ha, {}, floors={"terreo": TERREO}, areas={"cozinha": COZINHA})
    [entry] = ha.config_entries.async_entries(DOMAIN)
    await ha.config_entries.async_remove(entry.entry_id)
    await ha.async_block_till_done()
    assert floor(ha, "terreo") is None
    assert area(ha, "cozinha") is None
    assert floor(ha, theirs.floor_id) == theirs
    assert area(ha, their_area.id) == their_area
