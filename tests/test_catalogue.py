"""setup/catalogue: an aspect mounted at its places (feature.walk's paths), and the keys it lists there."""

from typing import Any

from homeassistant.core import HomeAssistant
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
