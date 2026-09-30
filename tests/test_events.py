"""pururu's events: each state change of an entity it created, fired on HA's bus."""

import json
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
import pytest

from helpers import capture, fake, held, reload, settle, setup, tick

KEY = "demo_washer"
POWER = "sensor.demo_plug_power"
ENERGY = "sensor.demo_plug_energy"
RUNNING = "binary_sensor.pururu_demo_washer_appliance_running"
MIRROR = "sensor.pururu_demo_washer_appliance_power"
ENERGY_TOTAL = "sensor.pururu_demo_washer_appliance_energy_total"
APPLIANCE: dict[str, Any] = {
    "power": POWER,
    "energy": ENERGY,
    "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}
DEVICES = {KEY: {"name": "Demo washer", "appliance": APPLIANCE}}
BOTH = ["state_changed", "reading"]
TYPES = ("pururu_state_changed", "pururu_reading")
ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
W = {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}
KWH = {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}


def sensor(entity_key: str) -> str:
    return f"sensor.pururu_{KEY}_appliance_{entity_key}"


async def watts(hass: HomeAssistant, value: float | str) -> None:
    await fake(hass, POWER, str(value), W)


async def kwh(hass: HomeAssistant, value: float) -> None:
    await fake(hass, ENERGY, str(value), KWH)


async def washer(hass: HomeAssistant, freezer: Any, events: Any) -> HomeAssistant:
    """The washer with these classes enabled, idle long enough to count as not running."""
    assert await setup(hass, DEVICES, events=events)
    await kwh(hass, 100.0)
    await watts(hass, 1.4)
    await tick(hass, freezer, 125)
    assert hass.states.get(RUNNING).state == "off"
    return hass


async def start_cycle(hass: HomeAssistant, freezer: Any) -> None:
    await watts(hass, 120)
    await tick(hass, freezer, 65)
    assert hass.states.get(RUNNING).state == "on"


async def end_cycle(hass: HomeAssistant, freezer: Any) -> None:
    await watts(hass, 1.4)
    await tick(hass, freezer, 125)
    assert hass.states.get(RUNNING).state == "off"


def of(captured: list, key: str) -> list:
    """The captured events of one entity key."""
    return [event for event in captured if event.data["key"] == key]


def keys(hass: HomeAssistant, device: str) -> set[str]:
    """The keys of the device's entities that have a state."""
    registry = er.async_get(hass)
    return {registry.async_get(entity_id).unique_id.removeprefix(f"pururu_{device}_")
            for entity_id in held(hass, device) if hass.states.get(entity_id) is not None}


@pytest.fixture
async def both(ha: HomeAssistant, freezer: Any) -> HomeAssistant:
    return await washer(ha, freezer, BOTH)


# --- off, on, each class ---------------------------------------------------------


async def test_off_by_default(ha: HomeAssistant, freezer: Any) -> None:
    await washer(ha, freezer, None)
    captured = capture(ha, *TYPES)
    await start_cycle(ha, freezer)
    await end_cycle(ha, freezer)
    assert captured == []


async def test_a_change(both: HomeAssistant, freezer: Any) -> None:
    captured = capture(both, *TYPES)
    await start_cycle(both, freezer)
    [event] = of(captured, "appliance_running")
    state = both.states.get(RUNNING)
    assert event.event_type == "pururu_state_changed"
    assert event.context.id == state.context.id
    data = dict(event.data)
    assert ULID.match(data.pop("event_id"))
    states = data.pop("states")
    assert data == {
        "event_name": f"{KEY}.appliance_running",
        "event_class": "state_changed",
        "entity_id": RUNNING,
        "device": KEY,
        "device_name": "Demo washer",
        "key": "appliance_running",
        "old": "off",
        "new": "on",
        "time": state.last_changed.isoformat(),
        # JSON's own: plain keys, the datetime as ISO text
        "attributes": {
            "cycle_start": state.attributes["cycle_start"].isoformat(),
            "device_class": "running",
            "friendly_name": "Demo washer Running",
        },
    }
    assert set(states) == keys(both, KEY)
    assert states["appliance_running"] == "on"


async def test_a_reading(both: HomeAssistant) -> None:
    captured = capture(both, *TYPES)
    await watts(both, 250)
    [event] = of(captured, "appliance_power")
    assert event.event_type == "pururu_reading"
    assert event.data["event_class"] == "reading"
    assert event.data["entity_id"] == MIRROR
    assert float(event.data["old"]) == 1.4
    assert float(event.data["new"]) == 250
    assert event.data["attributes"]["state_class"] == "measurement"


async def test_a_cycle_end_carries_the_cycle(both: HomeAssistant, freezer: Any) -> None:
    """last_cycle_end is written last: its snapshot holds that cycle's values."""
    await start_cycle(both, freezer)
    await tick(both, freezer, 30 * 60)
    await kwh(both, 100.62)
    captured = capture(both, *TYPES)
    await end_cycle(both, freezer)
    [event] = of(captured, "appliance_last_cycle_end")
    assert event.event_type == "pururu_state_changed"
    states = event.data["states"]
    assert states["appliance_last_cycle_end"] == event.data["new"]
    assert float(states["appliance_last_cycle_energy"]) == pytest.approx(0.62)
    assert states["appliance_last_cycle_duration"] == both.states.get(
        sensor("last_cycle_duration")).state
    assert states["appliance_cycles_total"] == "1"


@pytest.mark.parametrize("enabled", ["state_changed", "reading"])
async def test_each_class_alone(ha: HomeAssistant, freezer: Any, enabled: str) -> None:
    await washer(ha, freezer, [enabled])
    captured = capture(ha, *TYPES)
    await start_cycle(ha, freezer)
    await end_cycle(ha, freezer)
    assert captured
    assert {event.event_type for event in captured} == {f"pururu_{enabled}"}
    assert {event.data["event_class"] for event in captured} == {enabled}


async def test_every_event_has_its_own_id(both: HomeAssistant) -> None:
    captured = capture(both, *TYPES)
    for value in (200, 300, 400):
        await watts(both, value)
    ids = [event.data["event_id"] for event in captured]
    assert len(ids) >= 3
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("events", [
    pytest.param(["bogus"], id="unknown class"),
    pytest.param(["reading", "reading"], id="repeated class"),
    pytest.param({"reading": True}, id="not a list"),
])
async def test_the_schema_refuses(ha: HomeAssistant, events: Any) -> None:
    assert not await setup(ha, DEVICES, events=events)


async def test_the_documented_recipe_posts_json(
        both: HomeAssistant, freezer: Any, aioclient_mock: Any) -> None:
    """docs/concepts/events.mdx's rest_command and automation post each event as a JSON object.

    HA's attributes have enum keys, and running's cycle_start is a datetime:
    unless the data is JSON's own, the template renders it as Python's repr.
    """
    url = "http://n8n.local/webhook/pururu"
    aioclient_mock.post(url, text="ok")
    assert await async_setup_component(both, "rest_command", {"rest_command": {"n8n_pururu": {
        "url": url, "method": "post", "content_type": "application/json",
        "payload": "{{ event | tojson }}"}}})
    assert await async_setup_component(both, "automation", {"automation": [{
        "alias": "pururu → n8n", "mode": "queued", "max": 1000,
        "triggers": [{"trigger": "event", "event_type": list(TYPES)}],
        "actions": [{"action": "rest_command.n8n_pururu",
                     "data": {"event": "{{ trigger.event.data }}"}}],
    }]})
    captured = capture(both, *TYPES)
    await start_cycle(both, freezer)
    await both.async_block_till_done()
    [event] = of(captured, "appliance_running")
    assert "cycle_start" in event.data["attributes"]
    posted = [json.loads(body) for _method, _url, body, *_ in aioclient_mock.mock_calls]
    assert len(posted) == len(captured)
    assert all(isinstance(body, dict) for body in posted), posted
    assert [body["event_id"] for body in posted] == [event.data["event_id"] for event in captured]
    [running] = [body for body in posted if body["key"] == "appliance_running"]
    assert running == json.loads(json.dumps(dict(event.data)))


# --- what isn't fired ----------------------------------------------------------------


async def test_a_reload_is_silent(both: HomeAssistant) -> None:
    """Unloading writes HA's restored placeholder, loading the real state: neither is a change."""
    captured = capture(both, *TYPES)
    await reload(both, DEVICES, events=BOTH)
    assert captured == []


async def test_attributes_alone_are_not_fired(both: HomeAssistant) -> None:
    captured = capture(both, *TYPES)
    state = both.states.get(RUNNING)
    both.states.async_set(RUNNING, state.state, {**state.attributes, "extra": 1})
    await settle()
    assert captured == []


async def test_unavailable_is_fired(both: HomeAssistant) -> None:
    captured = capture(both, *TYPES)
    await fake(both, POWER, "unavailable")
    assert [event.data["new"] for event in of(captured, "appliance_power")] == ["unavailable"]


async def test_an_entity_not_created_is_not_fired(ha: HomeAssistant, freezer: Any) -> None:
    er.async_get(ha).async_get_or_create(
        "sensor", "template", "someone_else", suggested_object_id=ENERGY_TOTAL.split(".")[1])
    await washer(ha, freezer, BOTH)
    captured = capture(ha, *TYPES)
    ha.states.async_set(ENERGY_TOTAL, "5", KWH)
    ha.states.async_set(ENERGY_TOTAL, "6", KWH)
    await settle()
    assert [event for event in captured if event.data["entity_id"] == ENERGY_TOTAL] == []


# --- identity ------------------------------------------------------------------------


async def test_a_rename_is_followed(both: HomeAssistant, freezer: Any) -> None:
    """Renamed in the UI: the entry reloads, silently; the key and name stay."""
    captured = capture(both, *TYPES)
    er.async_get(both).async_update_entity(RUNNING, new_entity_id="binary_sensor.washer_running")
    await both.async_block_till_done()
    await settle()
    assert of(captured, "appliance_running") == []
    await start_cycle_renamed(both, freezer)
    [event] = of(captured, "appliance_running")
    assert event.data["entity_id"] == "binary_sensor.washer_running"
    assert event.data["event_name"] == f"{KEY}.appliance_running"


async def start_cycle_renamed(hass: HomeAssistant, freezer: Any) -> None:
    await watts(hass, 120)
    await tick(hass, freezer, 65)
    assert hass.states.get("binary_sensor.washer_running").state == "on"


async def test_devices_sharing_a_prefix(ha: HomeAssistant) -> None:
    """`pool` and `pool_pump`: each entity's key comes from the device that built it."""
    devices = {
        "pool": {"name": "Pool", "switches": {"pump": {"entity": "switch.a", "name": "A"}}},
        "pool_pump": {"name": "Pool pump", "switches": {"main": {"entity": "switch.b", "name": "B"}}},
    }
    ha.states.async_set("switch.a", "off")
    ha.states.async_set("switch.b", "off")
    assert await setup(ha, devices, events=BOTH)
    captured = capture(ha, *TYPES)
    await fake(ha, "switch.b", "on")
    [event] = [event for event in captured if event.data["entity_id"].startswith("switch.pururu_")]
    assert (event.data["device"], event.data["key"]) == ("pool_pump", "switch_main")
    assert event.data["event_name"] == "pool_pump.switch_main"


async def test_a_reload_turns_classes_on_and_off(ha: HomeAssistant, freezer: Any) -> None:
    await washer(ha, freezer, [])
    captured = capture(ha, *TYPES)
    await watts(ha, 200)
    assert captured == []
    await reload(ha, DEVICES, events=["reading"])
    await watts(ha, 300)
    assert [event.event_type for event in of(captured, "appliance_power")] == ["pururu_reading"]
    await reload(ha, DEVICES, events=[])
    captured.clear()
    await watts(ha, 400)
    assert captured == []
