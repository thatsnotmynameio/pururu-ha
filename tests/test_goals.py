"""Goals: a made-up pool pump, what it must run each period, and a living room's window that can track one."""

import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
import pytest
import voluptuous as vol

from helpers import DOMAIN, module, setup

POOL = "pool"
LIVING_ROOM = "living_room"
APPLIANCE: dict[str, Any] = {
    "power": "homeassistant.sensor.pool_pump_power",
    "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}
FILTERING: dict[str, Any] = {
    "name": "Filtragem", "target": 6, "period": "today",
    "tracked_by": "appliance.running_program.runtime_total",
}
WINDOW = {"contact": "homeassistant.binary_sensor.living_room_window"}
TARGET = "sensor.pururu_pool_goal_filtering_target"
DONE = "sensor.pururu_pool_goal_filtering_done"
GOAL = ["devices", POOL, "goals", "filtering"]
TRANSLATIONS = Path(__file__).resolve().parents[1] / "custom_components/pururu/translations"


def pool(**goal: Any) -> dict[str, Any]:
    """The pool, its filtering goal with `goal`'s fields over FILTERING's."""
    return {"name": "Piscina", "appliance": APPLIANCE, "goals": {"filtering": {**FILTERING, **goal}}}


def house(*others: tuple[str, dict[str, Any]], **goal: Any) -> dict[str, Any]:
    """A `pururu:` block with the pool, and other devices."""
    return {"devices": {POOL: pool(**goal), **dict(others)}}


def refused(block: dict[str, Any]) -> vol.Invalid:
    """The first refusal of the `pururu:` block."""
    schema = module("setup.schema").CONFIG_SCHEMA
    with pytest.raises(vol.Invalid) as error:
        schema({DOMAIN: block})
    return error.value


# --- configuration ----------------------------------------------------------------


async def test_a_goal_creates_its_target_and_done(ha: HomeAssistant) -> None:
    """Covers R1, R2: each named after the device, then the goal."""
    assert await setup(ha, {POOL: pool()})
    target, done = ha.states.get(TARGET), ha.states.get(DONE)
    assert target.attributes["friendly_name"] == "Piscina Filtragem target"
    assert done.attributes["friendly_name"] == "Piscina Filtragem done"
    assert float(target.state) == 6


def test_its_names_in_portuguese() -> None:
    sensors = json.loads((TRANSLATIONS / "pt-BR.json").read_text())["entity"]["sensor"]
    assert sensors["goal_target"]["name"] == "Meta de {goal}"
    assert sensors["goal_done"]["name"] == "Realizado de {goal}"


async def test_each_carries_its_reference(ha: HomeAssistant) -> None:
    """Covers R9."""
    assert await setup(ha, {POOL: pool()})
    for entity_id, node in ((TARGET, "goals.filtering.target"), (DONE, "goals.filtering.done")):
        assert ha.states.get(entity_id).attributes["reference"] == {
            "inside": node, "outside": f"device.{POOL}.{node}"}


def test_a_device_of_goals_alone_is_refused(ha: HomeAssistant) -> None:
    """Covers R1."""
    block = {"devices": {POOL: {"name": "Piscina", "goals": {"filtering": FILTERING}}}}
    assert refused(block).msg.startswith("a device needs at least one feature")


@pytest.mark.parametrize(("goal", "field"), [
    pytest.param({"target": 0}, "target", id="target 0"),
    pytest.param({"target": -1}, "target", id="target -1"),
    pytest.param({"target": "six"}, "target", id="target six"),
    pytest.param({"period": "fortnight"}, "period", id="period fortnight"),
])
def test_a_wrong_target_or_period_is_refused_at_its_field(
        ha: HomeAssistant, goal: dict[str, Any], field: str) -> None:
    """Covers R3, R4."""
    assert refused(house(**goal)).path == [DOMAIN, *GOAL, field]


def test_a_wrong_period_names_the_four(ha: HomeAssistant) -> None:
    """Covers R4."""
    assert refused(house(period="fortnight")).msg == (
        "a goal's period is one of today, week, month, year")


@pytest.mark.parametrize("tracked_by", [
    pytest.param("appliance.running_program", id="the carrier"),
    pytest.param("appliance.running_program.statistics.runtime.today", id="a meter"),
    pytest.param(f"device.{LIVING_ROOM}.goals.airing.done", id="a goal's sensor"),
])
def test_what_isnt_a_total_is_refused(ha: HomeAssistant, tracked_by: str) -> None:
    """Covers R5: only what accumulates tracks a goal."""
    airing = {"name": "Arejar", "target": 1, "period": "today",
              "tracked_by": "window.open_time_total"}
    living_room = {"name": "Sala", "window": WINDOW, "goals": {"airing": airing}}
    error = refused(house((LIVING_ROOM, living_room), tracked_by=tracked_by))
    assert error.msg == f"goals: filtering: {tracked_by} is not a total"
    assert error.path == [DOMAIN, *GOAL, "tracked_by"]


def test_its_own_goals_sensor_is_refused_once(ha: HomeAssistant) -> None:
    """Covers R5: a goal of this device is its own block's, refused by checks.references alone."""
    block = house(tracked_by="goals.airing.done")
    block["devices"][POOL]["goals"]["airing"] = {**FILTERING, "name": "Arejar"}
    schema = module("setup.schema").CONFIG_SCHEMA
    with pytest.raises(vol.MultipleInvalid) as error:
        schema({DOMAIN: block})
    assert [(each.msg, each.path) for each in error.value.errors] == [
        ("goals: goals.airing.done is not another block's entity",
         [DOMAIN, *GOAL, "tracked_by"])]


def test_another_devices_total_passes(ha: HomeAssistant) -> None:
    """Covers R5: a goal reaches another device, as a reaction's when does."""
    block = house((LIVING_ROOM, {"name": "Sala", "window": WINDOW}),
                  tracked_by=f"device.{LIVING_ROOM}.window.open_time_total")
    module("setup.schema").CONFIG_SCHEMA({DOMAIN: block})


def test_its_own_device_named_is_refused(ha: HomeAssistant) -> None:
    """Covers R5: written from its own device, with the form to write."""
    error = refused(house(tracked_by=f"device.{POOL}.appliance.running_program.runtime_total"))
    assert error.msg == (f"goals: device.{POOL}.appliance.running_program.runtime_total is this "
                         "device's: write appliance.running_program.runtime_total")
    assert error.path == [DOMAIN, *GOAL, "tracked_by"]


def test_the_energy_mirror_passes(ha: HomeAssistant) -> None:
    """Covers R5: its key is appliance_energy_total, a total, though its path isn't."""
    block = house(tracked_by="appliance.energy")
    block["devices"][POOL]["appliance"] = {**APPLIANCE, "energy": "homeassistant.sensor.pool_pump_energy"}
    module("setup.schema").CONFIG_SCHEMA({DOMAIN: block})


def test_a_home_assistant_entity_passes_the_check(ha: HomeAssistant) -> None:
    """Covers R5: checked when the entry sets up, not here."""
    module("setup.schema").CONFIG_SCHEMA({DOMAIN: house(tracked_by="homeassistant.sensor.pool_pump_runtime")})


def test_a_reaction_on_a_goal_names_its_sensors(ha: HomeAssistant) -> None:
    """Covers R9: a goal is no entity; its target and done are."""
    block = house()
    block["devices"][POOL]["reactions"] = {"met": {"name": "Feito", "when": "goals.filtering", "above": 5}}
    error = refused(block)
    assert error.msg == ("reactions: met: goals.filtering is a goal: watch goals.filtering.target "
                         "or goals.filtering.done")
    assert error.path == [DOMAIN, "devices", POOL, "reactions", "met", "when"]


def test_a_reaction_on_a_goals_done_passes(ha: HomeAssistant) -> None:
    """Covers R9."""
    block = house()
    block["devices"][POOL]["reactions"] = {"met": {"name": "Feito", "when": "goals.filtering.done", "above": 5}}
    module("setup.schema").CONFIG_SCHEMA({DOMAIN: block})
