"""setup/catalogue: an aspect mounted at its places (feature.walk's paths), and the keys it lists there."""

from typing import Any
from unittest.mock import patch

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
import pytest
import voluptuous as vol

from helpers import DOMAIN, module

# Statistics at each of the appliance's four places: its block, its running
# program, each phase, other
PROGRAM: dict[str, Any] = {
    "above": 4,
    "statistics": {"cycles": ["today"]},
    "phases": {"resfriar": {"name": "Resfriar", "above": 40, "statistics": {"cycles": ["month"]}}},
    "other": {"statistics": {"runtime": ["week"]}},
}
APPLIANCE: dict[str, Any] = {
    "power": "sensor.dummy_plug_power",
    "energy": "sensor.dummy_plug_energy",
    "running_program": PROGRAM,
    "statistics": {"idle_energy": ["year"]},
}


def mount(block: Any) -> Any:
    catalogue = module("setup.catalogue")
    return catalogue.mount(catalogue.builders()["appliance"], "appliance", block)


@pytest.mark.parametrize(("value", "path", "found"), [
    pytest.param({"a": 1}, (), [((), {"a": 1})], id="the block itself"),
    pytest.param({"a": {"b": 2}}, ("a",), [(("a",), {"b": 2})], id="a key"),
    pytest.param({"a": {"b": 2}}, ("x",), [], id="a key missing"),
    pytest.param({"a": 5}, ("a", "b"), [], id="not a map on the way"),
    pytest.param({"a": {"x": {"s": 1}, 1: {"s": 2}}}, ("a", "*"),
                 [(("a", "x"), {"s": 1}), (("a", "1"), {"s": 2})], id="each, a number made text"),
    pytest.param({"a": 5}, ("a",), [(("a",), 5)], id="the last may be anything"),
])
def test_walk_finds_each_container(
        ha: HomeAssistant, value: Any, path: tuple[str, ...], found: list[Any]) -> None:
    assert list(module("core.feature").walk(value, path)) == found


def test_statistics_is_mounted_at_every_place(ha: HomeAssistant) -> None:
    """Taken out before the builder's schema (which refuses it everywhere), validated per place, put back where it sat."""
    block = mount(APPLIANCE)
    program = block["running_program"]
    assert block["statistics"] == {"idle_energy": ["year"]}
    assert program["statistics"] == {"runtime": [], "cycles": ["today"]}
    assert program["phases"]["resfriar"]["statistics"] == {"runtime": [], "cycles": ["month"], "energy": []}
    assert program["other"]["statistics"] == {"runtime": ["week"], "cycles": [], "energy": []}


def test_other_without_its_block_has_no_statistics(ha: HomeAssistant) -> None:
    """other runs anyway; its meters are asked for in `other:`, so without it there is no place to mount."""
    program = {key: value for key, value in PROGRAM.items() if key != "other"}
    block = mount({**APPLIANCE, "running_program": program})
    assert "other" not in block["running_program"]


def test_a_phase_keyed_statistics_is_a_phase(ha: HomeAssistant) -> None:
    """The phases' map isn't a place: only each phase is."""
    phase = {"name": "Estatística", "above": 300, "statistics": {"cycles": ["today"]}}
    program = {**PROGRAM, "phases": {**PROGRAM["phases"], "statistics": phase}}
    block = mount({**APPLIANCE, "running_program": program})
    assert block["running_program"]["phases"]["statistics"]["name"] == "Estatística"
    assert block["running_program"]["phases"]["statistics"]["statistics"]["cycles"] == ["today"]


@pytest.mark.parametrize(("program", "path"), [
    pytest.param(5, ["running_program"], id="the program"),
    pytest.param({"above": 4, "phases": 5}, ["running_program", "phases"], id="its phases"),
    pytest.param({"above": 4, "phases": {"resfriar": 5}}, ["running_program", "phases", "resfriar"],
                 id="a phase"),
    pytest.param({"above": 4, "phases": {"resfriar": {"name": "Resfriar", "above": 40}}, "other": 5},
                 ["running_program", "other"], id="other"),
])
def test_a_place_that_isnt_a_map_is_refused_cleanly(
        ha: HomeAssistant, program: Any, path: list[str]) -> None:
    """vol.Invalid at its path, not a KeyError or TypeError from taking the aspect's key out."""
    schema = module("setup.schema").CONFIG_SCHEMA
    house = {"devices": {"washer": {"name": "Washer", "appliance": {
        "power": "sensor.dummy_plug_power", "running_program": program}}}}
    with pytest.raises(vol.Invalid) as refused:
        schema({DOMAIN: house})
    paths = ([error.path for error in refused.value.errors]
             if isinstance(refused.value, vol.MultipleInvalid) else [refused.value.path])
    assert [DOMAIN, "devices", "washer", "appliance", *path] in paths


def test_a_refusal_at_a_place_says_where(ha: HomeAssistant) -> None:
    program = {**PROGRAM, "phases": {"resfriar": {"name": "Resfriar", "above": 40,
                                               "statistics": {"cycles": ["daily"]}}}}
    with pytest.raises(vol.MultipleInvalid) as refused:
        mount({**APPLIANCE, "running_program": program})
    assert [error.path for error in refused.value.errors] == [
        ["running_program", "phases", "resfriar", "statistics", "cycles", 0]]


def test_keys_lists_the_meters_at_every_place(ha: HomeAssistant) -> None:
    """The appliance's own (runtime_today), each phase's as its item's (phase_resfriar_*), other's (phase_other_*)."""
    catalogue = module("setup.catalogue")
    rows = {key: (by, item) for _, key, _, by, item in catalogue.keys({"appliance": mount(APPLIANCE)})}
    assert rows["runtime_today"] == ("statistics", None)
    assert rows["idle_energy_year"] == ("statistics", None)
    assert rows["phase_resfriar_energy_month"] == ("statistics", "phase_resfriar")
    assert rows["phase_other_cycles_week"] == ("statistics", "phase_other")
    assert rows["phase_resfriar_cycles_total"] == (None, None)
    assert "energy_today" not in rows  # the running program counts no energy


# The appliance without statistics: the made-up aspects below replace ASPECTS
PLAIN: dict[str, Any] = {"power": "sensor.dummy_plug_power", "running_program": {"above": 4}}


def made_up(key: str, path: tuple[str, ...], schema: Any, **place: Any) -> Any:
    """An aspect offered by the appliance alone, at one place."""
    feature = module("core.feature")
    appliance = module("setup.catalogue").builders()["appliance"]
    at = feature.Place(path=path, schema=schema, keys={}, named=lambda each: each, example={}, **place)
    return feature.Aspect(key=key, offered=lambda builder: builder is appliance,
                          places=lambda builder, name: (at,), build=lambda *_: [], mount_absent=False)


def test_an_aspect_inside_another_is_taken_first_and_put_back_last(ha: HomeAssistant) -> None:
    """An aspect's key inside another aspect's value (statistics in a detected program).

    The deeper place is taken first, whatever ASPECTS' order, so the outer
    schema never sees it; it is put back once the outer value is.
    """
    catalogue = module("setup.catalogue")
    outer = made_up("outer", (), vol.Schema({"each": {str: {"n": int}}}))
    inner = made_up("inner", ("outer", "each", module("core.feature").EACH), vol.Schema({"m": int}))
    block = {**PLAIN, "outer": {"each": {"a": {"n": 1, "inner": {"m": 2}}, "b": {"n": 3}}}}
    with patch.object(catalogue, "ASPECTS", (outer, inner)):
        mounted = catalogue.mount(catalogue.builders()["appliance"], "appliance", block)
    assert mounted["outer"] == {"each": {"a": {"n": 1, "inner": {"m": 2}}, "b": {"n": 3}}}


def nested(check: Any = None) -> tuple[Any, Any]:
    """`outer` at the block, its items keyed by slugs (YAML's 1 made "1"); `inner` in each of them."""
    outer = made_up("outer", (), vol.Schema({"each": {cv.slug: {"n": int}}}))
    extra = {} if check is None else {"check": check}
    inner = made_up("inner", ("outer", "each", module("core.feature").EACH), vol.Schema({"m": int}), **extra)
    return outer, inner


def test_an_aspect_inside_another_keeps_a_whole_number_key(ha: HomeAssistant) -> None:
    """An item keyed 1 at depth: its inner value is put back under "1", where the outer schema made it."""
    catalogue = module("setup.catalogue")
    block = {**PLAIN, "outer": {"each": {1: {"n": 1, "inner": {"m": 2}}}}}
    with patch.object(catalogue, "ASPECTS", nested()):
        mounted = catalogue.mount(catalogue.builders()["appliance"], "appliance", block)
    assert mounted["outer"] == {"each": {"1": {"n": 1, "inner": {"m": 2}}}}


def test_a_refusal_inside_another_aspect_says_where(ha: HomeAssistant) -> None:
    catalogue = module("setup.catalogue")
    block = {**PLAIN, "outer": {"each": {1: {"n": 1, "inner": {"m": "two"}}}}}
    appliance, aspects = catalogue.builders()["appliance"], nested()
    with patch.object(catalogue, "ASPECTS", aspects), pytest.raises(vol.MultipleInvalid) as refused:
        catalogue.mount(appliance, "appliance", block)
    assert [error.path for error in refused.value.errors] == [["outer", "each", "1", "inner", "m"]]


def test_a_check_inside_another_aspect_gets_its_container_put_back(ha: HomeAssistant) -> None:
    """A nested place's check sees its container with its value back in it; its refusal says where."""
    catalogue = module("setup.catalogue")
    seen: list[Any] = []

    def check(_block: Any, container: Any) -> None:
        seen.append(container)
        if container["inner"]["m"] > 1:
            raise vol.Invalid("too many", path=["inner"])

    block = {**PLAIN, "outer": {"each": {"a": {"n": 1, "inner": {"m": 2}}, "b": {"n": 3, "inner": {"m": 1}}}}}
    appliance, aspects = catalogue.builders()["appliance"], nested(check)
    with patch.object(catalogue, "ASPECTS", aspects), pytest.raises(vol.MultipleInvalid) as refused:
        catalogue.mount(appliance, "appliance", block)
    assert seen == [{"n": 1, "inner": {"m": 2}}, {"n": 3, "inner": {"m": 1}}]
    assert [error.path for error in refused.value.errors] == [["outer", "each", "a", "inner"]]


def test_keys_lists_what_a_place_derives(ha: HomeAssistant) -> None:
    """Place.derived: the keys an aspect's validated value adds, by the aspect and no item's; none while it's absent."""
    catalogue = module("setup.catalogue")
    derives = made_up("made", (), vol.Schema({str: int}),
                      derived=lambda value: [(f"{key}_seen", Platform.SENSOR) for key in value])
    appliance = catalogue.builders()["appliance"]
    with patch.object(catalogue, "ASPECTS", (derives,)):
        rows = {key: (by, item) for _, key, _, by, item in catalogue.keys(
            {"appliance": catalogue.mount(appliance, "appliance", {**PLAIN, "made": {"cotton": 1}})})}
        absent = {key for _, key, *_ in catalogue.keys(
            {"appliance": catalogue.mount(appliance, "appliance", PLAIN)})}
    assert rows["cotton_seen"] == ("made", None)
    assert not {key for key in absent if key.endswith("_seen")}


def test_keys_lists_a_key_derived_twice_twice(ha: HomeAssistant) -> None:
    """Place.derived gives pairs, not a map: a key two items derive comes twice, for checks.keys_distinct."""
    catalogue = module("setup.catalogue")
    derives = made_up("made", (), vol.Schema({str: int}),
                      derived=lambda value: [("same", Platform.SENSOR) for _ in value])
    appliance = catalogue.builders()["appliance"]
    with patch.object(catalogue, "ASPECTS", (derives,)):
        block = catalogue.mount(appliance, "appliance", {**PLAIN, "made": {"cotton": 1, "linen": 2}})
        listed = [key for _, key, *_ in catalogue.keys({"appliance": block})]
    assert listed.count("same") == 2
