"""Feature `switches`: a made-up pool's pump and heater, standing for real switches."""

from typing import Any

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest

from helpers import capture, fake, held, reload, restart, settle, setup

KEY = "pool"
REAL_PUMP = "switch.pool_pump"
REAL_HEATER = "switch.pool_heater"
PUMP = "switch.pururu_pool_switch_pump"
HEATER = "switch.pururu_pool_switch_heater"
SWITCHES: dict[str, Any] = {"pump": {"entity": REAL_PUMP, "name": "Bomba"},
                            "heater": {"entity": REAL_HEATER, "name": "Aquecedor"}}
DEVICES = {KEY: {"name": "Piscina", "switches": SWITCHES}}
APPLIANCE = {"power": "sensor.pool_pump_power",
             "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}}}


def state(hass: HomeAssistant, entity_id: str) -> str:
    return hass.states.get(entity_id).state


@pytest.fixture
async def pool(ha: HomeAssistant) -> HomeAssistant:
    await fake(ha, REAL_PUMP, "off")
    await fake(ha, REAL_HEATER, "off")
    assert await setup(ha, DEVICES)
    return ha


async def forwarded(hass: HomeAssistant, service: str, context: Context) -> list[tuple[str, str]]:
    """Call `service` on the pururu pump; the calls it passed on to the real one."""
    calls = capture(hass, "call_service")
    await hass.services.async_call("switch", service, {"entity_id": PUMP}, blocking=True,
                                   context=context)
    await settle()
    return [(event.data["service"], event.context.id) for event in calls
            if event.data["service_data"].get("entity_id") == [REAL_PUMP]]


# --- schema ------------------------------------------------------------------


@pytest.mark.parametrize("block", [
    pytest.param({"pump": {"entity": "light.pool_light", "name": "Bomba"}}, id="another domain"),
    pytest.param({"pump": {"entity": REAL_PUMP}}, id="no name"),
    pytest.param({"pump": {"entity": REAL_PUMP, "name": ""}}, id="empty name"),
    pytest.param({"pump": {"entity": REAL_PUMP, "name": "  "}}, id="blank name"),
    pytest.param({"pump": REAL_PUMP}, id="just the entity"),
    pytest.param({"pump": {"entity": REAL_PUMP, "name": "Bomba", "icon": "mdi:pump"}}, id="unknown key"),
    pytest.param({}, id="no switch"),
    pytest.param({"Pump": {"entity": REAL_PUMP, "name": "Bomba"}}, id="key not a slug"),
    pytest.param({"pump": {"entity": PUMP, "name": "Bomba"}}, id="a pururu switch"),
    pytest.param({"pump": {"entity": "switch.pururu_garden_valve", "name": "Bomba"}},
                 id="another device's pururu switch"),
])
async def test_invalid_block_is_refused(ha: HomeAssistant, block: dict[str, Any]) -> None:
    assert not await setup(ha, {KEY: {"name": "Piscina", "switches": block}})


@pytest.mark.parametrize("entity_key", ["power", "running", "runtime_month"])
async def test_a_key_of_another_feature_is_accepted(ha: HomeAssistant, entity_key: str) -> None:
    """The switch is in the switch namespace, the appliance's entities in theirs."""
    await fake(ha, REAL_PUMP, "on")
    switches = {entity_key: {"entity": REAL_PUMP, "name": "Bomba"}}
    assert await setup(ha, {KEY: {"name": "Piscina", "appliance": APPLIANCE,
                                  "switches": switches}})
    assert state(ha, f"switch.pururu_pool_switch_{entity_key}") == "on"
    assert "binary_sensor.pururu_pool_appliance_running" in held(ha, KEY)


async def test_a_switch_keyed_switch_repeats_it(ha: HomeAssistant) -> None:
    """No exception to the pattern: the namespace, then the key, even when they are alike."""
    await fake(ha, REAL_PUMP, "on")
    assert await setup(ha, {KEY: {"name": "Piscina", "switches": {"switch": SWITCHES["pump"]}}})
    assert held(ha, KEY) == {"switch.pururu_pool_switch_switch"}


@pytest.mark.parametrize(("entity_key", "other"), [
    pytest.param("switch_pump", {"switches": {"pump": SWITCHES["pump"]}}, id="the same platform"),
    pytest.param("appliance_power", {"appliance": APPLIANCE}, id="another platform"),
])
async def test_two_devices_giving_one_entity_id_are_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, entity_key: str,
        other: dict[str, Any]) -> None:
    """pool + switch_pump and pool_switch + pump are both pururu_pool_switch_switch_pump."""
    assert not await setup(ha, {
        KEY: {"name": "Piscina", "switches": {entity_key: SWITCHES["pump"]}},
        "pool_switch": {"name": "Bomba", **other},
    })
    assert (f"device pool_switch: pururu_pool_switch_{entity_key} is already an entity of device pool"
            in caplog.text)


# --- the device ----------------------------------------------------------------


async def test_a_device_with_only_switches(pool: HomeAssistant) -> None:
    assert held(pool, KEY) == {PUMP, HEATER}


async def test_switches_next_to_another_feature(ha: HomeAssistant) -> None:
    assert await setup(ha, {KEY: {"name": "Piscina", "appliance": APPLIANCE,
                                  "switches": {"pump": SWITCHES["pump"]}}})
    assert {PUMP, "binary_sensor.pururu_pool_appliance_running"} <= held(ha, KEY)


async def test_two_devices_can_stand_for_one_real_switch(ha: HomeAssistant) -> None:
    await fake(ha, REAL_PUMP, "on")
    assert await setup(ha, {KEY: {"name": "Piscina", "switches": {"pump": SWITCHES["pump"]}},
                            "garden": {"name": "Jardim", "switches": {"pump": SWITCHES["pump"]}}})
    assert state(ha, PUMP) == "on"
    assert state(ha, "switch.pururu_garden_switch_pump") == "on"


async def test_names_come_from_the_configuration(pool: HomeAssistant) -> None:
    assert pool.states.get(PUMP).attributes["friendly_name"] == "Piscina Bomba"
    entry = er.async_get(pool).async_get(PUMP)
    assert entry is not None
    assert entry.unique_id == "pururu_pool_switch_pump"
    assert entry.translation_key is None


async def test_names_are_the_same_in_portuguese(ha: HomeAssistant) -> None:
    ha.config.language = "pt-BR"
    assert await setup(ha, DEVICES)
    assert ha.states.get(HEATER).attributes["friendly_name"] == "Piscina Aquecedor"


async def test_it_names_the_real_switch(pool: HomeAssistant) -> None:
    assert pool.states.get(PUMP).attributes["entity_id"] == [REAL_PUMP]


# --- state -------------------------------------------------------------------------


@pytest.mark.parametrize(("real", "expected"), [
    ("on", "on"), ("off", "off"), ("unknown", "unknown"), ("unavailable", "unavailable"),
])
async def test_follows_the_real_switch(pool: HomeAssistant, real: str, expected: str) -> None:
    await fake(pool, REAL_PUMP, real)
    assert state(pool, PUMP) == expected
    assert state(pool, HEATER) == "off"


async def test_without_the_real_switch_it_is_unavailable(ha: HomeAssistant) -> None:
    assert await setup(ha, DEVICES)
    assert state(ha, PUMP) == "unavailable"


async def test_follows_the_real_switch_going_and_coming_back(pool: HomeAssistant) -> None:
    pool.states.async_remove(REAL_PUMP)
    await settle()
    assert state(pool, PUMP) == "unavailable"
    await fake(pool, REAL_PUMP, "on")
    assert state(pool, PUMP) == "on"


async def test_assumed_state_follows_the_real_switch(pool: HomeAssistant) -> None:
    await fake(pool, REAL_PUMP, "on", {"assumed_state": True})
    assert pool.states.get(PUMP).attributes.get("assumed_state") is True


# --- commands ------------------------------------------------------------------------


async def test_turning_it_on_and_off_switches_the_real_one(pool: HomeAssistant) -> None:
    """With the caller's context, so the logbook names who did it."""
    context = Context()
    assert await forwarded(pool, "turn_on", context) == [("turn_on", context.id)]
    assert await forwarded(pool, "turn_off", context) == [("turn_off", context.id)]


async def test_turning_on_without_the_real_switch_does_nothing(ha: HomeAssistant) -> None:
    assert await setup(ha, DEVICES)
    assert await forwarded(ha, "turn_on", Context()) == []
    assert state(ha, PUMP) == "unavailable"


# --- IDs, renames, reloads and restarts --------------------------------------------------


async def test_an_id_already_taken_is_an_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    other = er.async_get(ha).async_get_or_create(
        "switch", "template", "someone_else", suggested_object_id="pururu_pool_switch_pump")
    assert other.entity_id == PUMP
    assert await setup(ha, DEVICES)
    assert held(ha, KEY) == {HEATER}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(PUMP in message and "template" in message for message in errors), errors


async def test_follows_its_own_rename(pool: HomeAssistant) -> None:
    er.async_get(pool).async_update_entity(PUMP, new_entity_id="switch.piscina_bomba")
    await pool.async_block_till_done()
    await fake(pool, REAL_PUMP, "on")
    assert state(pool, "switch.piscina_bomba") == "on"
    assert held(pool, KEY) == {"switch.piscina_bomba", HEATER}


async def test_a_renamed_pururu_switch_is_not_a_real_one(
        pool: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Renamed in the UI, it no longer starts with switch.pururu_: the registry still knows it."""
    er.async_get(pool).async_update_entity(HEATER, new_entity_id="switch.aquecedor")
    await pool.async_block_till_done()
    caplog.clear()
    await reload(pool, {KEY: {"name": "Piscina", "switches": {
        "pump": {"entity": "switch.aquecedor", "name": "Bomba"},
        "heater": SWITCHES["heater"],
    }}})
    assert pool.states.get(PUMP) is None
    assert held(pool, KEY) == {"switch.aquecedor"}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any("switch.aquecedor is a pururu switch" in message and PUMP in message
               for message in errors), errors


async def test_reload_that_drops_a_switch_removes_it(pool: HomeAssistant) -> None:
    await reload(pool, {KEY: {"name": "Piscina", "switches": {"pump": SWITCHES["pump"]}}})
    assert er.async_get(pool).async_get(HEATER) is None
    assert pool.states.get(HEATER) is None
    assert held(pool, KEY) == {PUMP}


async def test_reload_that_swaps_the_appliance_for_a_switch_removes_its_entities(
        ha: HomeAssistant) -> None:
    """A switch keyed like one of the appliance's entities is a new entity; the appliance's go."""
    assert await setup(ha, {KEY: {"name": "Piscina", "appliance": APPLIANCE}})
    assert er.async_get(ha).async_get("sensor.pururu_pool_appliance_power") is not None
    await reload(ha, {KEY: {"name": "Piscina", "switches": {"power": SWITCHES["pump"]}}})
    assert er.async_get(ha).async_get("sensor.pururu_pool_appliance_power") is None
    assert held(ha, KEY) == {"switch.pururu_pool_switch_power"}


async def test_after_a_restart_it_shows_the_real_switch(ha: HomeAssistant) -> None:
    await fake(ha, REAL_PUMP, "on")
    await fake(ha, REAL_HEATER, "off")
    await restart(ha, DEVICES)
    assert state(ha, PUMP) == "on"
    assert state(ha, HEATER) == "off"
