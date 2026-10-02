"""The reference house: it starts calm, stays calm when nothing happens, and its devices are linked."""

from pathlib import Path

import pytest
import yaml

from steps import AUTOMATIONS, Home

DOOR_NO_OPENING = "binary_sensor.pururu_front_door_door_alert_no_opening"
OVERLOAD = "binary_sensor.pururu_washer_alert_overload"
LONG_CYCLE = "binary_sensor.pururu_washer_appliance_alert_long_cycle"
CEILING = "light.pururu_living_room_light_ceiling"


def alerts_on(home: Home) -> list[str]:
    return [state.entity_id for state in home.hass.states.async_all("binary_sensor")
            if state.entity_id.startswith("binary_sensor.pururu_") and "_alert_" in state.entity_id
            and state.state == "on"]


async def test_it_starts_calm(house: Home) -> None:
    assert alerts_on(house) == []
    assert house.calm.sent() == []


async def test_a_quiet_day_stays_calm(house: Home) -> None:
    for _ in range(24):
        await house.tick(3600)
    assert alerts_on(house) == []
    assert house.calm.unexpected() == []


async def test_the_reaction_follows_the_washer(house: Home) -> None:
    generated = yaml.safe_load(Path(house.hass.config.path(AUTOMATIONS)).read_text(encoding="utf-8"))
    [reaction] = [automation for automation in generated
                  if automation["id"] == "pururu_living_room_reaction_laundry_done"]
    assert [trigger["entity_id"] for trigger in reaction["triggers"]] == [
        "binary_sensor.pururu_washer_appliance_running"]


async def test_the_washers_alerts_share_the_living_room_ceiling(house: Home) -> None:
    assert house.attributes(OVERLOAD)["lights"] == house.attributes(LONG_CYCLE)["lights"] == "living"
    assert house.attributes(OVERLOAD)["priority"] == "high"
    assert house.attributes(LONG_CYCLE)["priority"] == "medium"
    house.calm.expect(OVERLOAD)
    await house.play("sensor.washer_plug_power", "3000")
    await house.tick(60)
    assert house.attributes(CEILING)["alert"] == "high"


async def test_the_water_button_has_its_program(house: Home) -> None:
    assert house.state("button.pururu_garden_button_water") == "unknown"
    assert house.state("script.pururu_garden_program_executable_water") == "off"


async def test_an_alert_nobody_caused_is_named(house: Home) -> None:
    """AE3: three days without opening the door turns its no_opening on, and the calm check names it."""
    for _ in range(3 * 24 + 1):
        await house.tick(3600)
    assert f"alert {DOOR_NO_OPENING}" in house.calm.unexpected()
    house.calm.expect(*alerts_on(house))


@pytest.mark.parametrize("turn", ["first", "second"])
async def test_each_test_starts_from_the_calm_house(house: Home, turn: str) -> None:
    """Whatever ran before, the house is calm; this one leaves the door open long enough to alert."""
    assert alerts_on(house) == []
    house.calm.expect("binary_sensor.pururu_front_door_door_alert_long_opening")
    await house.play("binary_sensor.front_door_contact", "on")
    await house.tick(11 * 60)
    assert alerts_on(house) == ["binary_sensor.pururu_front_door_door_alert_long_opening"]
