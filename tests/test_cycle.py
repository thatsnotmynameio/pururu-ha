"""features/cycle: CycleSource, the base every cycle's source (Running, Open, Runs, Current) shares."""

from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
import pytest

from helpers import fake, module, setup, tick

KEY = "demo_washer"
POWER = "sensor.demo_plug_power"
RUNNING = "binary_sensor.pururu_demo_washer_appliance_running"
APPLIANCE: dict[str, Any] = {
    "power": POWER,
    "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}
DEVICES = {KEY: {"name": "Demo washer", "appliance": APPLIANCE}}

CONTACT = "binary_sensor.demo_contact"
DOOR_KEY = "demo_door"

MODE_KEY = "demo_filter"
MODE_APPLIANCE: dict[str, Any] = {
    "power": POWER,
    "running_program": {"above": 4, "on_delay": {"seconds": 20}, "off_delay": {"minutes": 2}},
}
# gelar and quente, so watts(1000) hands gelar straight over to quente: no idle in between
MODES: dict[str, Any] = {
    "cycle_from": "appliance",
    "sensor": POWER,
    "modes": {
        "gelar": {
            "name": "Gelar",
            "above": 40,
            "below": 300,
            "on_delay": {"seconds": 30},
            "off_delay": {"seconds": 30},
        },
        "quente": {
            "name": "Água quente",
            "above": 300,
            "on_delay": {"seconds": 10},
            "off_delay": {"seconds": 30},
        },
    },
}
MODE_DEVICES = {
    MODE_KEY: {"name": "Demo filter", "appliance": MODE_APPLIANCE, "modes": MODES}
}
CURRENT = "sensor.pururu_demo_filter_mode_current"


async def watts(hass: HomeAssistant, value: float | str) -> None:
    await fake(hass, POWER, str(value))


def _order(
    hass: HomeAssistant, entity_id: str
) -> tuple[list[tuple[str, str]], Callable[[str, Any], None]]:
    """`seen`, and a `listen(name, signal)` that records `(name, entity_id's state)` on each dispatch."""
    seen: list[tuple[str, str]] = []

    def listen(name: str, signal: Any) -> None:
        # A callback runs during the send, so it sees the state as the signal finds it
        @callback
        def record(_cycle: Any) -> None:
            seen.append((name, ha_state(hass, entity_id)))

        async_dispatcher_connect(hass, signal, record)

    return seen, listen


def ha_state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


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
    assert ha_state(ha, RUNNING) == "on"
    await watts(ha, 7)

    seen, listen = _order(ha, RUNNING)
    listen("cycle", cycle.cycle_signal(device))
    listen("end", cycle.end_signal(device))

    await watts(ha, 1.4)
    await tick(ha, freezer, 125)
    assert ha_state(ha, RUNNING) == "off"
    assert seen == [("cycle", "off"), ("end", "off")]


@pytest.mark.parametrize("kind", ["door", "window"])
async def test_a_cycle_is_sent_after_its_state_door_or_window(
    ha: HomeAssistant, freezer: Any, kind: str
) -> None:
    """Same order for Open: closed already when each signal fires, the cycle signal first."""
    cycle = module("features.cycle")
    device = module("core.feature").Device(
        key=DOOR_KEY, name="Demo door", namespace=kind
    )
    open_entity = f"binary_sensor.pururu_{DOOR_KEY}_{kind}_open"
    await fake(ha, CONTACT, "off", {"device_class": "door"})
    assert await setup(ha, {DOOR_KEY: {"name": "Demo door", kind: {"contact": CONTACT}}})
    await fake(ha, CONTACT, "on", {"device_class": "door"})
    assert ha_state(ha, open_entity) == "on"

    seen, listen = _order(ha, open_entity)
    listen("cycle", cycle.cycle_signal(device))
    listen("end", cycle.end_signal(device))

    await fake(ha, CONTACT, "off", {"device_class": "door"})
    assert ha_state(ha, open_entity) == "off"
    assert seen == [("cycle", "off"), ("end", "off")]


async def test_a_cycle_is_sent_after_its_state_a_mode_ending_into_the_next(
    ha: HomeAssistant, freezer: Any
) -> None:
    """Same order for a mode's own cycle: gelar already handed over to quente when its signals fire."""
    cycle = module("features.cycle")
    device = module("core.feature").Device(
        key=MODE_KEY, name="Demo filter", namespace="mode"
    )
    item = module("core.feature").Item(slug="gelar", name="Gelar")
    assert await setup(ha, MODE_DEVICES)
    await watts(ha, 120)
    await tick(ha, freezer, 35)
    assert ha_state(ha, CURRENT) == "gelar"

    seen, listen = _order(ha, CURRENT)
    listen("cycle", cycle.cycle_signal(device, item))
    listen("end", cycle.end_signal(device, item))

    await watts(ha, 1000)
    await tick(ha, freezer, 30)
    assert ha_state(ha, CURRENT) == "quente"
    assert seen == [("cycle", "quente"), ("end", "quente")]


def test_a_cycle_entity_takes_a_translation(ha: HomeAssistant) -> None:
    """The detector names a phase's cycle entities with its own keys ({item}); without one, the builder's namespace as today."""
    feature = module("core.feature")
    last, totals = module("features.cycle.last"), module("features.cycle.totals")
    device = feature.Device(key="dev", name="Dev", namespace="appliance")
    item = feature.Item(slug="phase_gelar", name="Gelar")
    named = [
        last.LastCycleValue(device, last.LAST_CYCLE[0], source="phase_gelar", item=item,
                            translation="phase_last_cycle_start"),
        totals.CyclesTotal(device, source="phase_gelar", item=item,
                           translation="phase_cycles_total"),
        totals.RuntimeTotal(device, None, "on", source="phase_gelar", item=item,
                            translation="phase_runtime_total"),
        totals.EnergyTotal(device, source="phase_gelar", item=item,
                           translation="phase_energy_total"),
    ]
    assert [(e.entity_id, e.translation_key, e.translation_placeholders) for e in named] == [
        (f"sensor.pururu_dev_appliance_phase_gelar_{suffix}", f"phase_{suffix}", {"item": "Gelar"})
        for suffix in ("last_cycle_start", "cycles_total", "runtime_total", "energy_total")
    ]
    plain = totals.CyclesTotal(device, source="running")
    assert (plain.entity_id, plain.translation_key) == (
        "sensor.pururu_dev_appliance_cycles_total", "appliance_cycles_total")
