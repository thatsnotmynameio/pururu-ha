"""Feature `programs`: a made-up pool's cleaning, turning its pump on for two hours."""

import asyncio
from typing import Any
from unittest.mock import patch

from homeassistant.core import Context, Event, HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.script import DATA_SCRIPTS
import pytest

from helpers import capture, fake, held, reload, restart, settle, setup, tick

KEY = "pool"
REAL_PUMP = "switch.pool_pump"
PUMP = "switch.pururu_pool_switch_pump"
CLEAN = "button.pururu_pool_program_clean"
SWITCHES: dict[str, Any] = {"pump": {"entity": REAL_PUMP, "name": "Bomba"}}
TWO_HOURS = 2 * 60 * 60
CLEANING: dict[str, Any] = {"name": "Limpar", "sequence": [
    {"turn_on": "switch_pump"}, {"delay": {"hours": 2}}, {"turn_off": "switch_pump"}]}
APPLIANCE = {"power": "sensor.pool_pump_power",
             "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}}}


def devices(**programs: Any) -> dict[str, Any]:
    return {KEY: {"name": "Piscina", "switches": SWITCHES, "programs": programs or {"clean": CLEANING}}}


def scripts(hass: HomeAssistant, name: str = "Piscina Limpar") -> list[Any]:
    """HA's scripts named `name`: HA keeps each one until it is unloaded."""
    return [data["instance"] for data in hass.data.get(DATA_SCRIPTS, {}).values()
            if data["instance"].name == name]


def reached(calls: list[Event], entity_id: str = REAL_PUMP) -> list[str]:
    """The services called on `entity_id`, in order."""
    found = []
    for event in calls:
        ids = event.data["service_data"].get("entity_id")
        if ids == entity_id or (isinstance(ids, list) and entity_id in ids):
            found.append(event.data["service"])
    return found


async def press(hass: HomeAssistant, entity_id: str = CLEAN, context: Context | None = None) -> None:
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True,
                                   context=context)
    await settle()


@pytest.fixture
async def pool(ha: HomeAssistant) -> HomeAssistant:
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, devices())
    return ha


# --- schema and the device ---------------------------------------------------------


@pytest.mark.parametrize("program", [
    pytest.param({"name": "Limpar"}, id="no sequence"),
    pytest.param({"name": "Limpar", "sequence": []}, id="empty sequence"),
    pytest.param({"sequence": [{"turn_on": "switch_pump"}]}, id="no name"),
    pytest.param({"name": " ", "sequence": [{"turn_on": "switch_pump"}]}, id="blank name"),
    pytest.param({"name": "Limpar", "sequence": [{"action": "switch.turn_on"}]}, id="an HA action"),
    pytest.param({"name": "Limpar", "sequence": [{"turn_on": "switch_pump", "delay": 5}]},
                 id="two keys in a step"),
    pytest.param({"name": "Limpar", "sequence": [{}]}, id="an empty step"),
    pytest.param({"name": "Limpar", "sequence": ["turn_on"]}, id="a step that isn't a mapping"),
    pytest.param({"name": "Limpar", "sequence": [{"delay": -5}]}, id="a negative delay"),
    pytest.param({"name": "Limpar", "sequence": [{"turn_on": REAL_PUMP}]}, id="a real entity ID"),
    pytest.param({"name": "Limpar", "sequence": [{"turn_on": "switch_pump"}], "icon": "mdi:pool"},
                 id="unknown key"),
])
async def test_invalid_program_is_refused(ha: HomeAssistant, program: dict[str, Any]) -> None:
    assert not await setup(ha, devices(clean=program))


@pytest.mark.parametrize("target", [
    pytest.param("switch_pool_pump", id="not an entity key of the device"),
    pytest.param("switch_heater", id="a switch the device doesn't have"),
    pytest.param("program_clean", id="a program"),
])
async def test_a_target_not_of_another_feature_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, target: str) -> None:
    assert not await setup(ha, devices(clean={"name": "Limpar", "sequence": [{"turn_on": target}]}))
    assert f"programs: {target} is not an entity key of another feature of this device" in caplog.text


async def test_a_device_with_only_programs_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    assert not await setup(ha, {KEY: {"name": "Piscina", "programs": {"clean": CLEANING}}})
    assert "programs: switch_pump is not an entity key of another feature of this device" in caplog.text


async def test_an_action_the_target_does_not_take_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    program = {"name": "Ligar", "sequence": [{"turn_on": "appliance_power"}]}
    assert not await setup(ha, {KEY: {"name": "Piscina", "appliance": APPLIANCE,
                                      "programs": {"start": program}}})
    assert "programs: appliance_power does not take turn_on" in caplog.text


async def test_it_is_a_button_named_by_the_configuration(pool: HomeAssistant) -> None:
    assert held(pool, KEY) == {PUMP, CLEAN}
    assert pool.states.get(CLEAN).attributes["friendly_name"] == "Piscina Limpar"
    entry = er.async_get(pool).async_get(CLEAN)
    assert entry is not None
    assert entry.unique_id == "pururu_pool_program_clean"
    assert entry.translation_key is None


# --- running -------------------------------------------------------------------------


async def test_pressing_runs_the_sequence(pool: HomeAssistant, freezer: Any) -> None:
    calls = capture(pool, "call_service")
    await press(pool)
    assert reached(calls) == ["turn_on"]
    await tick(pool, freezer, TWO_HOURS - 1)
    assert reached(calls) == ["turn_on"]
    await tick(pool, freezer, 1)
    assert reached(calls) == ["turn_on", "turn_off"]


async def test_toggle_flips_the_switch(ha: HomeAssistant) -> None:
    await fake(ha, REAL_PUMP, "on")
    assert await setup(ha, devices(flip={"name": "Inverter", "sequence": [{"toggle": "switch_pump"}]}))
    calls = capture(ha, "call_service")
    await press(ha, "button.pururu_pool_program_flip")
    assert reached(calls) == ["turn_off"]


@pytest.mark.parametrize(("real", "attributes"), [
    pytest.param("light.sala_teto", {"supported_color_modes": ["onoff"], "color_mode": "onoff"},
                 id="a real light"),
    pytest.param("switch.sonoff_teto", {}, id="a relay driving a lamp"),
])
async def test_it_turns_a_light_on_and_off(
        ha: HomeAssistant, freezer: Any, real: str, attributes: dict[str, Any]) -> None:
    await fake(ha, real, "off", attributes)
    evening = {"name": "Noite", "sequence": [
        {"turn_on": "light_teto"}, {"delay": {"minutes": 30}}, {"turn_off": "light_teto"}]}
    assert await setup(ha, {"sala": {"name": "Sala",
                                     "lights": {"teto": {"entity": real, "name": "Teto"}},
                                     "programs": {"evening": evening}}})
    calls = capture(ha, "call_service")
    await press(ha, "button.pururu_sala_program_evening")
    await tick(ha, freezer, 30 * 60)
    assert reached(calls, real) == ["turn_on", "turn_off"]


async def test_a_press_returns_before_the_delay_ends(pool: HomeAssistant) -> None:
    """As script.turn_on: an automation pressing it doesn't wait two hours."""
    async with asyncio.timeout(5):
        await pool.services.async_call("button", "press", {"entity_id": CLEAN}, blocking=True)
    assert pool.states.get(CLEAN).state not in ("unknown", "unavailable")


async def test_what_it_does_carries_the_press_context(pool: HomeAssistant) -> None:
    """The logbook names who pressed it."""
    calls = capture(pool, "call_service")
    context = Context()
    await press(pool, context=context)
    real = [event for event in calls if reached([event]) == ["turn_on"]]
    assert real
    assert all(context.id in (event.context.id, event.context.parent_id) for event in real)


async def test_a_press_while_running_is_ignored(
        pool: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    calls = capture(pool, "call_service")
    await press(pool)
    await tick(pool, freezer, 60)
    await press(pool)
    assert "Piscina Limpar: Already running" in caplog.text
    await tick(pool, freezer, TWO_HOURS)
    assert reached(calls) == ["turn_on", "turn_off"]


async def test_an_unavailable_switch_does_not_stop_it(ha: HomeAssistant, freezer: Any) -> None:
    """No real switch: the pururu switch is unavailable, HA skips it, the program goes on."""
    assert await setup(ha, devices())
    calls = capture(ha, "call_service")
    await press(ha)
    await tick(ha, freezer, TWO_HOURS)
    assert reached(calls, PUMP) == ["turn_on", "turn_off"]


async def test_a_failing_step_stops_it_and_is_logged(
        pool: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    calls = capture(pool, "call_service")
    with patch("homeassistant.components.group.switch.SwitchGroup.async_turn_on",
               side_effect=HomeAssistantError("the relay is stuck")):
        await press(pool)
    await tick(pool, freezer, TWO_HOURS)
    assert reached(calls, PUMP) == ["turn_on"]
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any("Piscina Limpar" in message and "the relay is stuck" in message
               for message in errors), errors


# --- reloads, renames, taken IDs and restarts --------------------------------------------


async def test_a_reload_stops_a_running_program(pool: HomeAssistant, freezer: Any) -> None:
    """What it did stays: the pump stays on."""
    calls = capture(pool, "call_service")
    await press(pool)
    await reload(pool, devices())
    await tick(pool, freezer, TWO_HOURS)
    assert reached(calls) == ["turn_on"]


async def test_after_a_reload_it_runs_again(pool: HomeAssistant, freezer: Any) -> None:
    await reload(pool, devices())
    calls = capture(pool, "call_service")
    await press(pool)
    await tick(pool, freezer, TWO_HOURS)
    assert reached(calls) == ["turn_on", "turn_off"]


async def test_a_reload_that_drops_it_removes_it(pool: HomeAssistant) -> None:
    await reload(pool, {KEY: {"name": "Piscina", "switches": SWITCHES}})
    assert er.async_get(pool).async_get(CLEAN) is None
    assert held(pool, KEY) == {PUMP}
    assert scripts(pool) == []


async def test_a_reload_leaves_one_script_per_program(pool: HomeAssistant) -> None:
    await reload(pool, devices())
    await reload(pool, devices())
    assert len(scripts(pool)) == 1


async def test_it_follows_its_target_renamed(pool: HomeAssistant) -> None:
    er.async_get(pool).async_update_entity(PUMP, new_entity_id="switch.piscina_bomba")
    await pool.async_block_till_done()
    calls = capture(pool, "call_service")
    await press(pool)
    assert reached(calls, "switch.piscina_bomba") == ["turn_on"]
    assert reached(calls) == ["turn_on"]


async def test_renamed_it_still_runs(pool: HomeAssistant) -> None:
    er.async_get(pool).async_update_entity(CLEAN, new_entity_id="button.limpar_piscina")
    await pool.async_block_till_done()
    calls = capture(pool, "call_service")
    await press(pool, "button.limpar_piscina")
    assert reached(calls) == ["turn_on"]


async def test_an_id_already_taken_is_an_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(
        "button", "template", "someone_else", suggested_object_id="pururu_pool_program_clean")
    assert await setup(ha, devices())
    assert held(ha, KEY) == {PUMP}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(CLEAN in message and "template" in message for message in errors), errors


async def test_a_program_whose_target_is_not_created_is_not_created(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(
        "switch", "template", "someone_else", suggested_object_id="pururu_pool_switch_pump")
    assert await setup(ha, devices())
    assert ha.states.get(CLEAN) is None
    assert f"{CLEAN} follows {PUMP}, which is not created; not creating it" in caplog.text
    assert scripts(ha) == []


async def test_after_a_restart_it_shows_its_last_press(ha: HomeAssistant) -> None:
    """A running program is lost, as HA's scripts; the time of the last press stays."""
    pressed = "2026-09-16T09:00:00+00:00"
    await fake(ha, REAL_PUMP, "off")
    await restart(ha, devices(), (State(CLEAN, pressed), {}))
    assert ha.states.get(CLEAN).state == pressed
