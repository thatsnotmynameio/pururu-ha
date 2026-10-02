"""A restart carries across only what Home Assistant saves itself, and pururu picks up from it."""

from typing import Any

from homeassistant.core import Event

from steps import Home

POWER = "sensor.washer_power"
RUNNING = "binary_sensor.pururu_washer_appliance_running"
CYCLES = "sensor.pururu_washer_appliance_cycles_total"
WASHER: dict[str, Any] = {"washer": {"name": "Washer", "appliance": {
    "power": f"homeassistant.{POWER}",
    "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}}}}}

REAL_PUMP = "switch.garden_pump"
REAL_DOOR = "binary_sensor.garden_door"
REAL_LANTERN = "light.garden_lantern"
LANTERN = "light.pururu_garden_light_lantern"
GATE_OPEN = "binary_sensor.pururu_garden_alert_gate_open"
WATER = "script.pururu_garden_program_executable_water"


def garden() -> dict[str, Any]:
    """A garden: a pump a program waters with when the door opens, and a lantern the open gate borrows."""
    return {"garden": {
        "name": "Garden",
        "switches": {"pump": {"entity": f"homeassistant.{REAL_PUMP}", "name": "Pump"}},
        "lights": {"lantern": {"entity": f"homeassistant.{REAL_LANTERN}", "name": "Lantern"}},
        "programs": {"executable": {"water": {"name": "Water", "sequence": [
            {"turn_on": "switches.pump"}, {"delay": {"minutes": 1}}, {"turn_off": "switches.pump"}]}}},
        "reactions": {"opened": {"name": "Opened", "when": f"homeassistant.{REAL_DOOR}", "to": "on",
                                 "then": "water"}},
        "alerts": {"gate_open": {"name": "Gate open", "when": "switches.pump", "state": "on",
                                 "priority": "medium", "lights": "default"}}}}


GROUPS = {"alerts": {"lights": {"groups": {"default": ["device.garden.lights.lantern"]}}}}


def services(events: list[Event], entity_id: str) -> list[str]:
    """The services called on `entity_id`, in order."""
    return [event.data["service"] for event in events
            if event.data["service_data"].get("entity_id") in (entity_id, [entity_id])]


async def test_a_cycle_runs_on_across_a_restart(home: Home) -> None:
    await home.play(POWER, "0")
    assert await home.setup({"devices": WASHER})
    await home.play(POWER, "900")
    await home.tick(60)
    started = home.attributes(RUNNING)["cycle_start"]
    await home.tick(40 * 60)
    await home.restart()
    assert home.state(RUNNING) == "on"
    assert home.attributes(RUNNING)["cycle_start"] == started
    await home.play(POWER, "0")
    await home.tick(120)
    assert home.state(RUNNING) == "off"
    assert home.state(CYCLES) == "1"


async def test_a_borrowed_light_is_borrowed_again(home: Home) -> None:
    await home.play(REAL_PUMP, "off")
    await home.play(REAL_DOOR, "off")
    await home.play(REAL_LANTERN, "off")
    assert await home.setup({"devices": garden(), "config": GROUPS})
    home.calm.expect(GATE_OPEN)
    await home.play(REAL_PUMP, "on")
    assert home.state(GATE_OPEN) == "on"
    assert home.attributes(LANTERN)["alert"] == "medium"
    await home.restart()
    assert home.attributes(LANTERN)["alert"] == "medium"


async def test_a_rename_is_kept(home: Home) -> None:
    await home.play(REAL_PUMP, "off")
    await home.play(REAL_DOOR, "off")
    await home.play(REAL_LANTERN, "off")
    assert await home.setup({"devices": garden(), "config": GROUPS})
    await home.rename("switch.pururu_garden_switch_pump", "switch.my_pump")
    await home.restart()
    assert home.state("switch.my_pump") == "off"
    assert home.hass.states.get("switch.pururu_garden_switch_pump") is None


async def test_the_generated_automations_and_scripts_run(home: Home) -> None:
    await home.play(REAL_PUMP, "off")
    await home.play(REAL_DOOR, "off")
    await home.play(REAL_LANTERN, "off")
    assert await home.setup({"devices": garden(), "config": GROUPS})
    home.calm.expect(GATE_OPEN)
    await home.restart()
    calls = home.capture("call_service")
    triggered = home.capture("automation_triggered")
    await home.play(REAL_DOOR, "on")
    assert [event.data["entity_id"] for event in triggered] == [
        "automation.pururu_garden_reaction_opened"]
    assert home.state(WATER) == "on"
    await home.tick(60)
    assert services(calls, REAL_PUMP) == ["turn_on", "turn_off"]
    assert home.state(WATER) == "off"
