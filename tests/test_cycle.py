"""features/cycle: CycleSource, the base every cycle's source (Running, Open, Runs, Current) shares."""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
import pytest

from helpers import fake, module, setup, tick

KEY = "demo_washer"
POWER = "sensor.demo_plug_power"
RUNNING = "binary_sensor.pururu_demo_washer_appliance_running"
APPLIANCE: dict[str, Any] = {
    "power": POWER,
    "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}
DEVICES = {KEY: {"name": "Demo washer", "appliance": APPLIANCE}}


async def watts(hass: HomeAssistant, value: float | str) -> None:
    await fake(hass, POWER, str(value))


async def test_a_cycle_is_sent_after_its_state_cycle_first_end_last(
    ha: HomeAssistant, freezer: Any
) -> None:
    """Characterizes today's order: the state is off already when each signal fires, the cycle signal first."""
    cycle = module("features.cycle")
    device = module("core.feature").Device(
        key=KEY, name="Demo washer", namespace="appliance"
    )
    assert await setup(ha, DEVICES)
    await watts(ha, 120)
    await tick(ha, freezer, 65)
    assert ha.states.get(RUNNING).state == "on"
    await watts(ha, 7)

    seen: list[tuple[str, str]] = []

    def listen(name: str, signal: Any) -> None:
        def record(_cycle: Any) -> None:
            seen.append((name, ha.states.get(RUNNING).state))

        async_dispatcher_connect(ha, signal, record)

    listen("cycle", cycle.cycle_signal(device))
    listen("end", cycle.end_signal(device))

    await watts(ha, 1.4)
    await tick(ha, freezer, 125)
    assert ha.states.get(RUNNING).state == "off"
    assert seen == [("cycle", "off"), ("end", "off")]
