"""The steps every story uses: set up, the clock, reload, and the generated automations running."""

from datetime import timedelta

from homeassistant.util import dt as dt_util

from steps import Home

REAL_PUMP = "switch.garden_pump"
REAL_DOOR = "binary_sensor.garden_door"
PUMP = "switch.pururu_garden_switch_pump"


def garden(**more: object) -> dict[str, object]:
    return {"devices": {"garden": {
        "name": "Garden",
        "switches": {"pump": {"entity": f"homeassistant.{REAL_PUMP}", "name": "Pump"}},
        **more}}}


async def test_a_switch_follows_its_real_switch(home: Home) -> None:
    await home.play(REAL_PUMP, "off")
    assert await home.setup(garden())
    assert home.state(PUMP) == "off"
    await home.play(REAL_PUMP, "on")
    assert home.state(PUMP) == "on"


async def test_the_clock_moves_by_the_tick(home: Home) -> None:
    start = dt_util.now()
    await home.tick(60)
    assert dt_util.now() - start == timedelta(seconds=60)


async def test_a_reload_adds_a_new_device(home: Home) -> None:
    await home.play(REAL_PUMP, "off")
    await home.play("switch.porch_lamp", "off")
    assert await home.setup(garden())
    house = garden()
    house["devices"]["porch"] = {  # type: ignore[index]
        "name": "Porch",
        "switches": {"lamp": {"entity": "homeassistant.switch.porch_lamp", "name": "Lamp"}}}
    await home.reload(house)
    assert home.state("switch.pururu_porch_switch_lamp") == "off"


async def test_a_reactions_automation_runs(home: Home) -> None:
    await home.play(REAL_PUMP, "off")
    await home.play(REAL_DOOR, "off")
    assert await home.setup(garden(reactions={
        "opened": {"name": "Opened", "when": f"homeassistant.{REAL_DOOR}", "to": "on"}}))
    triggered = home.capture("automation_triggered")
    await home.play(REAL_DOOR, "on")
    assert [event.data["entity_id"] for event in triggered] == [
        "automation.pururu_garden_reaction_opened"]
