"""The index of every entity a device can create, the reference forms, and finding a reference in the index."""

import re
from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
import voluptuous as vol

from helpers import DOMAIN, module

SWITCH_ACTIONS = ("turn_on", "turn_off", "toggle")
HOUSE: dict[str, Any] = {
    "washer": {
        "name": "Washer",
        "appliance": {
            "power": "homeassistant.sensor.washer_power",
            "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
            "alerts": {"offline": None},
        },
        "switches": {"plug": {"entity": "homeassistant.switch.washer_plug", "name": "Plug"}},
        "programs": {"executable": {"clean": {"name": "Clean", "sequence": [{"turn_on": "switches.plug"}]}}},
    },
    "lights": {"name": "Lights", "lights": {"teto": {"entity": "homeassistant.light.teto", "name": "Teto"}}},
}


@pytest.fixture
def index(ha: HomeAssistant) -> Any:
    devices = module("setup.schema").CONFIG_SCHEMA({DOMAIN: {"devices": HOUSE}})[DOMAIN]["devices"]
    return module("setup.catalogue").index(devices)


def find(index: Any, here: str, text: str) -> Any:
    resolve = module("core.resolve")
    return resolve.find(index, here, resolve.Ref.parse(text))


def test_a_features_own_key(index: Any) -> None:
    """Found by its path; its key stays qualified, and its IDs are as before."""
    target = find(index, "washer", "appliance.running_program")
    assert (target.builder, target.by, target.item, target.actions) == ("appliance", None, None, ())
    assert (target.key, target.path) == ("appliance_running", "appliance.running_program")
    assert target.platform is Platform.BINARY_SENSOR
    assert target.local == "running"
    assert target.unique_id == "pururu_washer_appliance_running"
    assert target.entity_id() == "binary_sensor.pururu_washer_appliance_running"


def test_a_ready_made_alert_is_by_alerts(index: Any) -> None:
    target = find(index, "washer", "appliance.alerts.offline")
    assert (target.builder, target.by) == ("appliance", "alerts")


def test_a_configured_key_takes_its_builders_actions(index: Any) -> None:
    target = find(index, "washer", "switches.plug")
    assert (target.builder, target.platform, target.actions) == ("switches", Platform.SWITCH, SWITCH_ACTIONS)


def test_an_items_key_knows_its_item(index: Any) -> None:
    target = find(index, "washer", "programs.executable.clean.cycles_total")
    assert (target.builder, target.item) == ("programs", "executable_clean")


def test_a_meter_is_by_statistics(index: Any) -> None:
    """The statistics aspect's keys are in the index whatever the settings, as the builder's own."""
    target = find(index, "washer", "appliance.running_program.statistics.runtime.today")
    assert (target.builder, target.by, target.item) == ("appliance", "statistics", None)
    assert target.platform is Platform.SENSOR
    assert target.unique_id == "pururu_washer_appliance_runtime_today"


def test_an_items_meter_knows_its_item(index: Any) -> None:
    target = find(index, "washer", "programs.executable.clean.statistics.cycles.year")
    assert (target.builder, target.by, target.item) == ("programs", "statistics", "executable_clean")


def test_another_devices_key(index: Any) -> None:
    target = find(index, "washer", "device.lights.lights.teto")
    assert (target.device.key, target.builder, target.actions) == ("lights", "lights", SWITCH_ACTIONS)
    assert target.unique_id == "pururu_lights_light_teto"


@pytest.mark.parametrize("text", [
    pytest.param("appliance.nothing", id="unknown path"),
    pytest.param("device.dryer.appliance.running_program", id="unknown device"),
    pytest.param("device.lights.appliance.running_program", id="a path the other device doesn't have"),
    pytest.param("homeassistant.binary_sensor.door", id="Home Assistant's: not in the index"),
])
def test_what_isnt_there_is_none(index: Any, text: str) -> None:
    assert find(index, "washer", text) is None


def test_the_current_entity_id_follows_a_rename(ha: HomeAssistant, index: Any) -> None:
    registry = er.async_get(ha)
    registry.async_get_or_create("binary_sensor", DOMAIN, "pururu_washer_appliance_running",
                                 suggested_object_id="lavadora_ligada")
    target = find(index, "washer", "appliance.running_program")
    assert target.current_entity_id(ha) == "binary_sensor.lavadora_ligada"


# --- the reference forms -------------------------------------------------------------------


@pytest.mark.parametrize(("text", "owner", "device", "path"), [
    pytest.param("appliance.running_program", "here", None, "appliance.running_program", id="this device"),
    pytest.param("device.washer.appliance.running_program", "device", "washer", "appliance.running_program",
                 id="another device"),
    pytest.param("homeassistant.binary_sensor.door", "homeassistant", None, "binary_sensor.door",
                 id="Home Assistant's"),
])
def test_a_reference_parses_as_written(ha: HomeAssistant, text: str, owner: str, device: str | None,
                                       path: str) -> None:
    parsed = module("core.resolve").Ref.parse(text)
    assert (parsed.owner, parsed.device, parsed.path) == (owner, device, path)
    assert parsed.text == text


@pytest.mark.parametrize("text", [
    pytest.param("appliance_running", id="one segment"),
    pytest.param("device.washer.appliance", id="another device without its path"),
    pytest.param("homeassistant.binary_sensor", id="Home Assistant's without its object ID"),
    pytest.param("", id="empty"),
])
def test_a_reference_not_validated_is_a_programming_error(ha: HomeAssistant, text: str) -> None:
    """Ref.parse reads what path validated: other text wouldn't read back as written."""
    parse = module("core.resolve").Ref.parse
    with pytest.raises(ValueError, match="is not a validated reference"):
        parse(text)


@pytest.mark.parametrize("value", [
    pytest.param("appliance.running_program", id="a path of this device"),
    pytest.param("appliance.programs.detected.cotton.other.statistics.energy.month", id="a deep path"),
    pytest.param("device.washer.appliance.running_program", id="another device's path"),
    pytest.param("homeassistant.binary_sensor.door", id="a Home Assistant entity"),
    pytest.param("reactions.morning", id="a path the checks refuse"),
    pytest.param("binary_sensor.door", id="a bare entity ID reads as a path: the checks refuse its first word"),
])
def test_a_path_is_accepted(ha: HomeAssistant, value: str) -> None:
    assert module("core.resolve").path(value) == value


NOT_A_PATH = "{} is not a path: write it from its block, <block>.<key>"


@pytest.mark.parametrize(("value", "message"), [
    pytest.param("appliance_running", NOT_A_PATH.format("appliance_running"), id="a 0.2.1 key"),
    pytest.param("appliance.", NOT_A_PATH.format("appliance."), id="an empty last segment"),
    pytest.param(".running", NOT_A_PATH.format(".running"), id="an empty first segment"),
    pytest.param("appliance..running", NOT_A_PATH.format("appliance..running"), id="two dots"),
    pytest.param("Appliance.running_program", "invalid slug Appliance", id="a segment not a slug"),
    pytest.param("device.washer.appliance",
                 "device.washer.appliance is not a path of another device: device.<device>.<block>.<key>",
                 id="another device without a path"),
    pytest.param("homeassistant.binary_sensor",
                 "homeassistant.binary_sensor is not a Home Assistant entity: homeassistant.<domain>.<object_id>",
                 id="Home Assistant's without its object ID"),
    pytest.param("homeassistant.binary_sensor.door.x",
                 "homeassistant.binary_sensor.door.x is not a Home Assistant entity: "
                 "homeassistant.<domain>.<object_id>",
                 id="Home Assistant's with a path"),
    pytest.param("", "a path can't be empty", id="empty"),
])
def test_a_path_is_refused(ha: HomeAssistant, value: str, message: str) -> None:
    with pytest.raises(vol.Invalid, match=re.escape(message)):
        module("core.resolve").path(value)


@pytest.mark.parametrize(("field", "of", "value"), [
    pytest.param("then", "program", "blink", id="a program's key"),
    pytest.param("area", "area", "despensa", id="an area's key"),
])
def test_a_key_alone_is_accepted(ha: HomeAssistant, field: str, of: str, value: str) -> None:
    assert module("core.resolve").key_alone(field, of)(value) == value


@pytest.mark.parametrize(("field", "of", "value", "message"), [
    pytest.param("then", "program", "programs.executable.blink", "then is its program's key alone: blink",
                 id="a program's path"),
    pytest.param("then", "program", "device.greenhouse.programs.executable.blink",
                 "then is its program's key alone, never another device's", id="another device's program"),
    pytest.param("area", "area", "areas.despensa", "area is its area's key alone: despensa", id="an area's path"),
    pytest.param("floor", "floor", "floors.terreo", "floor is its floor's key alone: terreo", id="a floor's path"),
    pytest.param("then", "program", "Blink", "invalid slug Blink", id="not a slug"),
    pytest.param("then", "program", "", "then can't be empty", id="empty"),
])
def test_a_key_alone_refuses_a_path(ha: HomeAssistant, field: str, of: str, value: str, message: str) -> None:
    with pytest.raises(vol.Invalid, match=re.escape(message)):
        module("core.resolve").key_alone(field, of)(value)


@pytest.mark.parametrize(("value", "domains", "entity_id"), [
    pytest.param("homeassistant.sensor.washer_power", ("sensor",), "sensor.washer_power", id="its domain's"),
    pytest.param("homeassistant.light.teto", (), "light.teto", id="any domain"),
    pytest.param("homeassistant.sensor.Washer_Power", ("sensor",), "sensor.washer_power",
                 id="lowered, as Home Assistant's cv.entity_id"),
])
def test_a_home_assistant_entity_is_accepted(ha: HomeAssistant, value: str, domains: tuple[str, ...],
                                             entity_id: str) -> None:
    assert module("core.resolve").homeassistant_entity(*domains)(value) == entity_id


@pytest.mark.parametrize(("value", "domains", "message"), [
    pytest.param("sensor.washer_power", ("sensor",),
                 "sensor.washer_power is not a Home Assistant entity: homeassistant.<domain>.<object_id>",
                 id="without homeassistant."),
    pytest.param("homeassistant.light.teto", ("sensor",), "homeassistant.light.teto is not a sensor",
                 id="another domain"),
])
def test_a_home_assistant_entity_is_refused(ha: HomeAssistant, value: str, domains: tuple[str, ...],
                                            message: str) -> None:
    with pytest.raises(vol.Invalid, match=re.escape(message)):
        module("core.resolve").homeassistant_entity(*domains)(value)
