"""Feature `switches`: a made-up greenhouse's sprinkler and heater, standing for real switches."""

from typing import Any

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest

from helpers import capture, fake, held, reload, restart, settle, setup

KEY = "greenhouse"
REAL_SPRINKLER = "switch.greenhouse_sprinkler"
REAL_HEATER = "switch.greenhouse_heater"
SPRINKLER = "switch.pururu_greenhouse_switch_sprinkler"
HEATER = "switch.pururu_greenhouse_switch_heater"
SWITCHES: dict[str, Any] = {"sprinkler": {"entity": f"homeassistant.{REAL_SPRINKLER}", "name": "Irrigador"},
                            "heater": {"entity": f"homeassistant.{REAL_HEATER}", "name": "Aquecedor"}}
DEVICES = {KEY: {"name": "Estufa", "switches": SWITCHES}}
APPLIANCE = {"power": "homeassistant.sensor.greenhouse_sprinkler_power",
             "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}}}


def state(hass: HomeAssistant, entity_id: str) -> str:
    return hass.states.get(entity_id).state


@pytest.fixture
async def greenhouse(ha: HomeAssistant) -> HomeAssistant:
    await fake(ha, REAL_SPRINKLER, "off")
    await fake(ha, REAL_HEATER, "off")
    assert await setup(ha, DEVICES)
    return ha


async def forwarded(hass: HomeAssistant, service: str, context: Context) -> list[tuple[str, str]]:
    """Call `service` on the pururu sprinkler; the calls it passed on to the real one."""
    calls = capture(hass, "call_service")
    await hass.services.async_call("switch", service, {"entity_id": SPRINKLER}, blocking=True,
                                   context=context)
    await settle()
    return [(event.data["service"], event.context.id) for event in calls
            if event.data["service_data"].get("entity_id") == [REAL_SPRINKLER]]


# --- schema ------------------------------------------------------------------


@pytest.mark.parametrize("block", [
    pytest.param({"sprinkler": {"entity": "homeassistant.light.greenhouse_light", "name": "Irrigador"}}, id="another domain"),
    pytest.param({"sprinkler": {"entity": f"homeassistant.{REAL_SPRINKLER}"}}, id="no name"),
    pytest.param({"sprinkler": {"entity": f"homeassistant.{REAL_SPRINKLER}", "name": ""}}, id="empty name"),
    pytest.param({"sprinkler": {"entity": f"homeassistant.{REAL_SPRINKLER}", "name": "  "}}, id="blank name"),
    pytest.param({"sprinkler": REAL_SPRINKLER}, id="just the entity"),
    pytest.param({"sprinkler": {"entity": f"homeassistant.{REAL_SPRINKLER}", "name": "Irrigador", "icon": "mdi:sprinkler"}}, id="unknown key"),
    pytest.param({}, id="no switch"),
    pytest.param({"Sprinkler": {"entity": f"homeassistant.{REAL_SPRINKLER}", "name": "Irrigador"}}, id="key not a slug"),
    pytest.param({"sprinkler": {"entity": f"homeassistant.{SPRINKLER}", "name": "Irrigador"}}, id="a pururu switch"),
    pytest.param({"sprinkler": {"entity": "homeassistant.switch.pururu_orchard_valve", "name": "Irrigador"}},
                 id="another device's pururu switch"),
])
async def test_invalid_block_is_refused(ha: HomeAssistant, block: dict[str, Any]) -> None:
    assert not await setup(ha, {KEY: {"name": "Estufa", "switches": block}})


@pytest.mark.parametrize(("entity", "message"), [
    pytest.param("homeassistant.light.greenhouse_light", "homeassistant.light.greenhouse_light is not a switch",
                 id="another domain"),
    pytest.param(f"homeassistant.{SPRINKLER}", f"homeassistant.{SPRINKLER} is a pururu switch: name the real one",
                 id="a pururu switch"),
    pytest.param(REAL_SPRINKLER, f"{REAL_SPRINKLER} is not a Home Assistant entity: "
                 "homeassistant.<domain>.<object_id> for dictionary value "
                 f"'pururu->devices->{KEY}->switches->sprinkler->entity'",
                 id="without homeassistant, as before 0.2.2"),
])
async def test_the_error_names_what_is_wrong(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, entity: str, message: str) -> None:
    """The messages the docs quote (troubleshooting)."""
    assert not await setup(ha, {KEY: {"name": "Estufa", "switches": {
        "sprinkler": {"entity": entity, "name": "Irrigador"}}}})
    assert message in caplog.text


@pytest.mark.parametrize("entity_key", ["power", "running", "runtime_month"])
async def test_a_key_of_another_feature_is_accepted(ha: HomeAssistant, entity_key: str) -> None:
    """The switch is in the switch namespace, the appliance's entities in theirs."""
    await fake(ha, REAL_SPRINKLER, "on")
    switches = {entity_key: {"entity": f"homeassistant.{REAL_SPRINKLER}", "name": "Irrigador"}}
    assert await setup(ha, {KEY: {"name": "Estufa", "appliance": APPLIANCE,
                                  "switches": switches}})
    assert state(ha, f"switch.pururu_greenhouse_switch_{entity_key}") == "on"
    assert "binary_sensor.pururu_greenhouse_appliance_running" in held(ha, KEY)


async def test_a_switch_keyed_switch_repeats_it(ha: HomeAssistant) -> None:
    """No exception to the pattern: the namespace, then the key, even when they are alike."""
    await fake(ha, REAL_SPRINKLER, "on")
    assert await setup(ha, {KEY: {"name": "Estufa", "switches": {"switch": SWITCHES["sprinkler"]}}})
    assert held(ha, KEY) == {"switch.pururu_greenhouse_switch_switch"}


@pytest.mark.parametrize(("entity_key", "other"), [
    pytest.param("switch_sprinkler", {"switches": {"sprinkler": SWITCHES["sprinkler"]}}, id="the same platform"),
    pytest.param("appliance_power", {"appliance": APPLIANCE}, id="another platform"),
])
async def test_two_devices_giving_one_entity_id_are_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, entity_key: str,
        other: dict[str, Any]) -> None:
    """greenhouse + switch_sprinkler and greenhouse_switch + sprinkler are both pururu_greenhouse_switch_switch_sprinkler."""
    assert not await setup(ha, {
        KEY: {"name": "Estufa", "switches": {entity_key: SWITCHES["sprinkler"]}},
        "greenhouse_switch": {"name": "Irrigador", **other},
    })
    assert (f"device greenhouse_switch: pururu_greenhouse_switch_{entity_key} is already an entity of device greenhouse"
            in caplog.text)


# --- the device ----------------------------------------------------------------


async def test_a_device_with_only_switches(greenhouse: HomeAssistant) -> None:
    assert held(greenhouse, KEY) == {SPRINKLER, HEATER}


async def test_switches_next_to_another_feature(ha: HomeAssistant) -> None:
    assert await setup(ha, {KEY: {"name": "Estufa", "appliance": APPLIANCE,
                                  "switches": {"sprinkler": SWITCHES["sprinkler"]}}})
    assert {SPRINKLER, "binary_sensor.pururu_greenhouse_appliance_running"} <= held(ha, KEY)


async def test_two_devices_can_stand_for_one_real_switch(ha: HomeAssistant) -> None:
    await fake(ha, REAL_SPRINKLER, "on")
    assert await setup(ha, {KEY: {"name": "Estufa", "switches": {"sprinkler": SWITCHES["sprinkler"]}},
                            "orchard": {"name": "Pomar", "switches": {"sprinkler": SWITCHES["sprinkler"]}}})
    assert state(ha, SPRINKLER) == "on"
    assert state(ha, "switch.pururu_orchard_switch_sprinkler") == "on"


async def test_names_come_from_the_configuration(greenhouse: HomeAssistant) -> None:
    assert greenhouse.states.get(SPRINKLER).attributes["friendly_name"] == "Estufa Irrigador"
    entry = er.async_get(greenhouse).async_get(SPRINKLER)
    assert entry is not None
    assert entry.unique_id == "pururu_greenhouse_switch_sprinkler"
    assert entry.translation_key is None


async def test_names_are_the_same_in_portuguese(ha: HomeAssistant) -> None:
    ha.config.language = "pt-BR"
    assert await setup(ha, DEVICES)
    assert ha.states.get(HEATER).attributes["friendly_name"] == "Estufa Aquecedor"


async def test_it_names_the_real_switch(greenhouse: HomeAssistant) -> None:
    assert greenhouse.states.get(SPRINKLER).attributes["entity_id"] == [REAL_SPRINKLER]


# --- state -------------------------------------------------------------------------


@pytest.mark.parametrize(("real", "expected"), [
    ("on", "on"), ("off", "off"), ("unknown", "unknown"), ("unavailable", "unavailable"),
])
async def test_follows_the_real_switch(greenhouse: HomeAssistant, real: str, expected: str) -> None:
    await fake(greenhouse, REAL_SPRINKLER, real)
    assert state(greenhouse, SPRINKLER) == expected
    assert state(greenhouse, HEATER) == "off"


async def test_without_the_real_switch_it_is_unavailable(ha: HomeAssistant) -> None:
    assert await setup(ha, DEVICES)
    assert state(ha, SPRINKLER) == "unavailable"


async def test_follows_the_real_switch_going_and_coming_back(greenhouse: HomeAssistant) -> None:
    greenhouse.states.async_remove(REAL_SPRINKLER)
    await settle()
    assert state(greenhouse, SPRINKLER) == "unavailable"
    await fake(greenhouse, REAL_SPRINKLER, "on")
    assert state(greenhouse, SPRINKLER) == "on"


async def test_assumed_state_follows_the_real_switch(greenhouse: HomeAssistant) -> None:
    await fake(greenhouse, REAL_SPRINKLER, "on", {"assumed_state": True})
    assert greenhouse.states.get(SPRINKLER).attributes.get("assumed_state") is True


# --- commands ------------------------------------------------------------------------


async def test_turning_it_on_and_off_switches_the_real_one(greenhouse: HomeAssistant) -> None:
    """With the caller's context, so the logbook names who did it."""
    context = Context()
    assert await forwarded(greenhouse, "turn_on", context) == [("turn_on", context.id)]
    assert await forwarded(greenhouse, "turn_off", context) == [("turn_off", context.id)]


async def test_turning_on_without_the_real_switch_does_nothing(ha: HomeAssistant) -> None:
    assert await setup(ha, DEVICES)
    assert await forwarded(ha, "turn_on", Context()) == []
    assert state(ha, SPRINKLER) == "unavailable"


# --- IDs, renames, reloads and restarts --------------------------------------------------


async def test_an_id_already_taken_is_an_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    other = er.async_get(ha).async_get_or_create(
        "switch", "template", "someone_else", suggested_object_id="pururu_greenhouse_switch_sprinkler")
    assert other.entity_id == SPRINKLER
    assert await setup(ha, DEVICES)
    assert held(ha, KEY) == {HEATER}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(SPRINKLER in message and "template" in message for message in errors), errors


async def test_follows_its_own_rename(greenhouse: HomeAssistant) -> None:
    er.async_get(greenhouse).async_update_entity(SPRINKLER, new_entity_id="switch.estufa_irrigador")
    await greenhouse.async_block_till_done()
    await fake(greenhouse, REAL_SPRINKLER, "on")
    assert state(greenhouse, "switch.estufa_irrigador") == "on"
    assert held(greenhouse, KEY) == {"switch.estufa_irrigador", HEATER}


async def test_a_renamed_pururu_switch_is_not_a_real_one(
        greenhouse: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Renamed in the UI, it no longer starts with switch.pururu_: the registry still knows it."""
    er.async_get(greenhouse).async_update_entity(HEATER, new_entity_id="switch.aquecedor")
    await greenhouse.async_block_till_done()
    caplog.clear()
    await reload(greenhouse, {KEY: {"name": "Estufa", "switches": {
        "sprinkler": {"entity": "homeassistant.switch.aquecedor", "name": "Irrigador"},
        "heater": SWITCHES["heater"],
    }}})
    assert greenhouse.states.get(SPRINKLER) is None
    assert held(greenhouse, KEY) == {"switch.aquecedor"}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any("switch.aquecedor is a pururu switch" in message and SPRINKLER in message
               for message in errors), errors


async def test_a_switch_renamed_to_what_it_stands_for_stays_as_it_is(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Renamed in the UI to its own entity: kept with its rename, unavailable, at every reload."""
    await fake(ha, REAL_SPRINKLER, "on")
    devices = {KEY: {"name": "Estufa", "switches": {
        "sprinkler": SWITCHES["sprinkler"], "heater": {"entity": "homeassistant.switch.aquecedor", "name": "Aquecedor"}}}}
    assert await setup(ha, devices)
    er.async_get(ha).async_update_entity(HEATER, new_entity_id="switch.aquecedor")
    await ha.async_block_till_done()
    for _ in range(3):
        entry = er.async_get(ha).async_get("switch.aquecedor")
        assert entry is not None
        assert entry.unique_id == "pururu_greenhouse_switch_heater"
        assert state(ha, "switch.aquecedor") == "unavailable"
        assert held(ha, KEY) == {SPRINKLER, "switch.aquecedor"}
        assert "switch.aquecedor is this switch itself: name the real one" in caplog.text
        caplog.clear()
        await reload(ha, devices)


async def test_a_switch_standing_for_itself_passes_nothing_on(ha: HomeAssistant) -> None:
    """Its state set by hand (developer tools) makes it neither available nor calling itself."""
    devices = {KEY: {"name": "Estufa", "switches": {
        "heater": {"entity": "homeassistant.switch.aquecedor", "name": "Aquecedor"}}}}
    assert await setup(ha, devices)
    er.async_get(ha).async_update_entity(HEATER, new_entity_id="switch.aquecedor")
    await ha.async_block_till_done()
    await fake(ha, "switch.aquecedor", "on")
    calls = capture(ha, "call_service")
    await ha.services.async_call("switch", "turn_on", {"entity_id": "switch.aquecedor"},
                                 blocking=True)
    await settle()
    assert [event.data["service_data"] for event in calls] == [
        {"entity_id": "switch.aquecedor"}]


async def test_reload_that_drops_a_switch_removes_it(greenhouse: HomeAssistant) -> None:
    await reload(greenhouse, {KEY: {"name": "Estufa", "switches": {"sprinkler": SWITCHES["sprinkler"]}}})
    assert er.async_get(greenhouse).async_get(HEATER) is None
    assert greenhouse.states.get(HEATER) is None
    assert held(greenhouse, KEY) == {SPRINKLER}


async def test_reload_that_swaps_the_appliance_for_a_switch_removes_its_entities(
        ha: HomeAssistant) -> None:
    """A switch keyed like one of the appliance's entities is a new entity; the appliance's go."""
    assert await setup(ha, {KEY: {"name": "Estufa", "appliance": APPLIANCE}})
    assert er.async_get(ha).async_get("sensor.pururu_greenhouse_appliance_power") is not None
    await reload(ha, {KEY: {"name": "Estufa", "switches": {"power": SWITCHES["sprinkler"]}}})
    assert er.async_get(ha).async_get("sensor.pururu_greenhouse_appliance_power") is None
    assert held(ha, KEY) == {"switch.pururu_greenhouse_switch_power"}


async def test_after_a_restart_it_shows_the_real_switch(ha: HomeAssistant) -> None:
    await fake(ha, REAL_SPRINKLER, "on")
    await fake(ha, REAL_HEATER, "off")
    await restart(ha, DEVICES)
    assert state(ha, SPRINKLER) == "on"
    assert state(ha, HEATER) == "off"
