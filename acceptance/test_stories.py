"""The stories: the reference house's devices leaning on each other, through a restart, a rename or a disable.

Each starts from the calm house, names the alerts and notifications it causes,
and reads only what a pururu user sees: states, attributes, the notifications
sent, the calls the real devices get.
"""

from typing import Any

from homeassistant.core import Event
from homeassistant.helpers import entity_registry as er

from steps import Home

# The washer
POWER = "sensor.washer_plug_power"
RUNNING = "binary_sensor.pururu_washer_appliance_running"
CYCLES = "sensor.pururu_washer_appliance_cycles_total"
OVERLOAD = "binary_sensor.pururu_washer_alert_overload"
LONG_CYCLE = "binary_sensor.pururu_washer_appliance_alert_long_cycle"
WASHER = "Washer"  # the title of its notifications: the device's name
# The living room
LAUNDRY_DONE = "automation.pururu_living_room_reaction_laundry_done"
LAUNDRY_DONE_TOTAL = "sensor.pururu_living_room_reaction_laundry_done_triggered_total"
REAL_CEILING = "light.living_room_ceiling"
CEILING = "light.pururu_living_room_light_ceiling"
# What the bulb gets for each priority's default turn_on (docs/concepts/alert-lights.mdx),
# as Home Assistant's light.turn_on hands it on: the colour's name as hs, the percent as 0-255
RED = {"hs_color": (0.0, 100.0), "brightness": 255, "effect": "breathe"}
ORANGE = {"hs_color": (38.824, 100.0), "brightness": 255, "effect": "breathe"}
GREEN = {"hs_color": (120.0, 100.0), "brightness": 128}
# The garden
REMOTE = "sensor.garden_remote_action"
WATER_PRESS = "1_single"
REAL_PUMP = "switch.garden_pump"
PUMP = "switch.pururu_garden_switch_pump"
WATER = "script.pururu_garden_program_executable_water"
PRESSES = "sensor.pururu_garden_button_water_triggered_total"
WATER_CYCLES = "sensor.pururu_garden_program_executable_water_cycles_total"
# The water program's delay, between turning the pump on and off
WATERING = 10 * 60


def calls(events: list[Event], entity_id: str) -> list[tuple[str, dict[str, Any]]]:
    """The services called on the real `entity_id`, in order, with their data without it."""
    return [(event.data["service"],
             {key: value for key, value in event.data["service_data"].items() if key != "entity_id"})
            for event in events
            if event.data["service_data"].get("entity_id") in (entity_id, [entity_id])]


def services(events: list[Event], entity_id: str) -> list[str]:
    """The services called on the real `entity_id`, in order."""
    return [service for service, _data in calls(events, entity_id)]


def triggered(events: list[Event], automation: str) -> int:
    """How many times `automation` was triggered."""
    return sum(event.data["entity_id"] == automation for event in events)


def runs(changes: list[Event]) -> int:
    """How many times the water program's script started: turned on from anything else."""
    return sum(event.data["entity_id"] == WATER
               and event.data["new_state"] is not None and event.data["new_state"].state == "on"
               and (event.data["old_state"] is None or event.data["old_state"].state != "on")
               for event in changes)


def total(home: Home, entity_id: str) -> int:
    """A counter's value."""
    return int(float(home.state(entity_id)))


async def start_cycle(home: Home, running: str = RUNNING) -> None:
    """The washer draws power, past its running program's on_delay."""
    await home.play(POWER, "900")
    await home.tick(60)
    assert home.state(running) == "on"


async def end_cycle(home: Home, running: str = RUNNING) -> None:
    """The washer stops drawing, past its running program's off_delay."""
    await home.play(POWER, "0")
    await home.tick(120)
    assert home.state(running) == "off"


async def press(home: Home) -> None:
    """The remote's water key: its sensor changes into the button's value, then back, a few seconds later.

    Two presses at one frozen instant would be one change; the time and the value between keep them apart.
    """
    await home.play(REMOTE, WATER_PRESS)
    await home.tick(1)
    await home.play(REMOTE, "idle")
    await home.tick(5)


async def test_f1_the_washer_ends_and_the_living_room_hears_it_across_a_restart(house: Home) -> None:
    house.calm.expect(WASHER)
    cycles = total(house, CYCLES)
    reacted = total(house, LAUNDRY_DONE_TOTAL)
    events = house.capture("automation_triggered")
    await start_cycle(house)
    await house.tick(40 * 60)
    await house.restart()
    assert house.state(RUNNING) == "on"
    assert triggered(events, LAUNDRY_DONE) == 0
    assert house.calm.sent() == []
    await end_cycle(house)
    assert triggered(events, LAUNDRY_DONE) == 1
    assert total(house, LAUNDRY_DONE_TOTAL) == reacted + 1
    assert [(call.data["title"], call.data["message"]) for call in house.calm.sent()] == [
        (WASHER, "The cycle finished.")]
    assert total(house, CYCLES) == cycles + 1


async def test_f2_two_alerts_borrow_the_ceiling_and_give_it_back(house: Home) -> None:
    house.calm.expect(LONG_CYCLE, OVERLOAD, WASHER)
    events = house.capture("call_service")
    released = house.capture("pururu_alert_lights_released")
    await start_cycle(house)
    await house.tick(3 * 3600)
    assert house.state(LONG_CYCLE) == "on"
    assert house.attributes(CEILING)["alert"] == "medium"
    await house.play(POWER, "3000")
    await house.tick(60)
    assert house.state(OVERLOAD) == "on"
    assert house.attributes(CEILING)["alert"] == "high"
    assert house.attributes(CEILING)["alerts"] == [LONG_CYCLE, OVERLOAD]
    assert calls(events, REAL_CEILING)[-1] == ("turn_on", RED)

    across = house.capture("call_service")
    await house.restart()
    assert house.attributes(CEILING)["alert"] == "high"
    assert calls(across, REAL_CEILING) == [("turn_on", RED)]

    await house.play(POWER, "900")
    assert house.state(OVERLOAD) == "off"
    assert house.attributes(CEILING)["alert"] == "medium"
    assert calls(events, REAL_CEILING)[-1] == ("turn_on", ORANGE)

    await end_cycle(house)
    assert house.state(LONG_CYCLE) == "off"
    assert house.attributes(CEILING)["alert"] == "resolved"
    assert calls(events, REAL_CEILING)[-1] == ("turn_on", GREEN)
    assert released == []
    await house.tick(120)
    assert calls(events, REAL_CEILING)[-1] == ("turn_off", {})
    assert "alert" not in house.attributes(CEILING)
    assert [event.data for event in released] == [{"entity_id": CEILING}]
    assert ("turn_off", {}) not in calls(events, REAL_CEILING)[:-1]


async def test_f3_a_press_runs_the_water_program_once(house: Home) -> None:
    presses = total(house, PRESSES)
    cycles = total(house, WATER_CYCLES)
    events = house.capture("call_service")
    changes = house.capture("state_changed")
    await press(house)
    assert house.state(WATER) == "on"
    assert services(events, REAL_PUMP) == ["turn_on"]
    await house.tick(60)
    await press(house)
    assert house.state(WATER) == "on"
    assert services(events, REAL_PUMP) == ["turn_on"]
    await house.tick(WATERING)
    assert house.state(WATER) == "off"
    assert services(events, REAL_PUMP) == ["turn_on", "turn_off"]
    assert runs(changes) == 1
    assert total(house, PRESSES) == presses + 2
    assert total(house, WATER_CYCLES) == cycles + 1


async def test_f4_a_rename_and_a_disable_midway(house: Home) -> None:
    house.calm.expect(WASHER)
    registry = er.async_get(house.hass)
    renamed = "binary_sensor.washer_running"
    await house.rename(RUNNING, renamed)
    assert house.state(renamed) == "off"

    reactions = house.capture("automation_triggered")
    await start_cycle(house, renamed)
    await end_cycle(house, renamed)
    assert triggered(reactions, LAUNDRY_DONE) == 1

    script = registry.async_get(WATER)
    assert script is not None
    await house.disable(PUMP)
    await house.tick(31)
    await house.hass.async_block_till_done()
    held = registry.async_get(WATER)
    assert held is not None
    assert held.id == script.id
    assert house.state(WATER) == "unavailable"
    assert house.attributes(WATER).get("restored") is True
    events = house.capture("call_service")
    await press(house)
    assert house.state(WATER) == "unavailable"
    assert services(events, REAL_PUMP) == []

    await house.enable(PUMP)
    await house.tick(31)
    await house.hass.async_block_till_done()
    back = registry.async_get(WATER)
    assert back is not None
    assert back.id == script.id
    assert house.state(WATER) == "off"
    await press(house)
    assert house.state(WATER) == "on"
    assert services(events, REAL_PUMP) == ["turn_on"]
    await house.tick(WATERING)
    assert services(events, REAL_PUMP) == ["turn_on", "turn_off"]
