"""reading(): a sensor's number, or None while it has none; as_time(): a time read back; an entity's key, path and reference."""

from typing import Any
from unittest.mock import patch

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from helpers import DOMAIN, fake, module, setup


def value(state: str | None) -> float | None:
    entity = module("core.entity")
    return entity.reading(None if state is None else State("sensor.dummy", state))


def test_a_number_is_read(ha: HomeAssistant) -> None:
    assert value("5") == 5.0
    assert value("5.5") == 5.5


def test_unknown_and_unavailable_have_no_reading(ha: HomeAssistant) -> None:
    assert value("unknown") is None
    assert value("unavailable") is None


def test_not_a_number_has_no_reading(ha: HomeAssistant) -> None:
    assert value("abc") is None


def test_no_state_has_no_reading(ha: HomeAssistant) -> None:
    assert value(None) is None


def test_non_finite_numbers_have_no_reading(ha: HomeAssistant) -> None:
    assert value("nan") is None
    assert value("inf") is None
    assert value("-inf") is None



def test_a_time_is_read_back(ha: HomeAssistant) -> None:
    """A datetime as it is, a time's string parsed; an impossible date and anything else, none."""
    as_time = module("core.entity").as_time
    moment = dt_util.utcnow()
    assert as_time(moment) is moment
    assert as_time(moment.isoformat()) == moment
    assert as_time("2026-02-30T10:00:00+00:00") is None
    assert as_time("not a time") is None
    assert as_time(None) is None
    assert as_time(5) is None


GREENHOUSE = {"name": "Estufa", "switches": {"sprinkler": {"entity": "homeassistant.switch.greenhouse_sprinkler", "name": "Irrigador"}}}
SPRINKLER = "switch.pururu_greenhouse_switch_sprinkler"
WASHER = {"name": "Tanquinho", "appliance": {
    "power": "homeassistant.sensor.washer_plug_power",
    "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}}
POWER = "sensor.pururu_clothes_washer_appliance_power"


def reference(hass: HomeAssistant, entity_id: str) -> Any:
    return hass.states.get(entity_id).attributes.get("reference")


async def test_an_entity_knows_its_key_and_path(ha: HomeAssistant) -> None:
    """Its key in its namespace, and its path in its device's YAML, stamped from the index."""
    assert await setup(ha, {"greenhouse": GREENHOUSE})
    [entry] = ha.config_entries.async_entries(DOMAIN)
    [switch] = entry.runtime_data[Platform.SWITCH]
    assert (switch.key, switch.path) == ("switch_sprinkler", "switches.sprinkler")
    assert not hasattr(switch, "reference")


async def test_an_entity_shows_its_reference(ha: HomeAssistant) -> None:
    """Both forms: from inside its device, and from another device."""
    assert await setup(ha, {"greenhouse": GREENHOUSE})
    assert reference(ha, SPRINKLER) == {
        "inside": "switches.sprinkler", "outside": "device.greenhouse.switches.sprinkler"}


async def test_devices_sharing_a_prefix_show_their_own_reference(ha: HomeAssistant) -> None:
    """`greenhouse` and `greenhouse_sprinkler`: each entity names the device that built it."""
    devices = {
        "greenhouse": GREENHOUSE,
        "greenhouse_sprinkler": {"name": "Irrigador", "switches": {
            "main": {"entity": "homeassistant.switch.b", "name": "B"}}},
    }
    assert await setup(ha, devices)
    assert reference(ha, SPRINKLER) == {
        "inside": "switches.sprinkler", "outside": "device.greenhouse.switches.sprinkler"}
    assert reference(ha, "switch.pururu_greenhouse_sprinkler_switch_main") == {
        "inside": "switches.main", "outside": "device.greenhouse_sprinkler.switches.main"}


async def test_an_unavailable_entity_still_shows_its_reference(ha: HomeAssistant) -> None:
    """A capability attribute: HA writes it while the entity is unavailable, when it is most needed (an alert on an offline plug); a sensor keeps its state_class."""
    await fake(ha, "sensor.washer_plug_power", "unavailable")
    assert await setup(ha, {"clothes_washer": WASHER})
    state = ha.states.get(POWER)
    assert state.state == "unavailable"
    assert state.attributes["reference"] == {
        "inside": "appliance.power", "outside": "device.clothes_washer.appliance.power"}
    await fake(ha, "sensor.washer_plug_power", "5", {"unit_of_measurement": "W", "state_class": "measurement"})
    state = ha.states.get(POWER)
    assert state.attributes["state_class"] == "measurement"
    assert state.attributes["reference"]["inside"] == "appliance.power"


async def test_a_light_keeps_its_color_modes(ha: HomeAssistant) -> None:
    await fake(ha, "light.room_ceiling", "on", {"supported_color_modes": ["hs"], "color_mode": "hs",
                                                "hs_color": [30.0, 50.0], "brightness": 128})
    assert await setup(ha, {"room": {"name": "Room", "lights": {
        "ceiling": {"entity": "homeassistant.light.room_ceiling", "name": "Ceiling"}}}})
    attributes = ha.states.get("light.pururu_room_light_ceiling").attributes
    assert attributes["supported_color_modes"] == ["hs"]
    assert attributes["reference"] == {"inside": "lights.ceiling", "outside": "device.room.lights.ceiling"}


async def test_the_reference_is_in_the_registry_and_its_change_reloads_nothing(ha: HomeAssistant) -> None:
    """HA keeps capability attributes in the registry entry: a change there alone isn't a rename or a disable."""
    assert await setup(ha, {"greenhouse": GREENHOUSE})
    registry = er.async_get(ha)
    assert registry.async_get(SPRINKLER).capabilities["reference"]["inside"] == "switches.sprinkler"
    with patch.object(ha.config_entries, "async_schedule_reload") as reload:
        registry.async_update_entity(SPRINKLER, capabilities={
            "reference": {"inside": "switches.other", "outside": "device.greenhouse.switches.other"}})
        await ha.async_block_till_done()
        assert not reload.called
        # What does reload it, seen by the same patch: a rename
        registry.async_update_entity(SPRINKLER, new_entity_id="switch.renamed_sprinkler")
        await ha.async_block_till_done()
        assert reload.called
