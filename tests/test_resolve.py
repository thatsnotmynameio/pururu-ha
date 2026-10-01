"""The index of every entity key a device can create, and finding a reference in it."""

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
            "power": "sensor.washer_power",
            "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
            "alerts": {"offline": None},
        },
        "switches": {"plug": {"entity": "switch.washer_plug", "name": "Plug"}},
        "programs": {"executable": {"clean": {"name": "Clean", "sequence": [{"turn_on": "switch_plug"}]}}},
    },
    "lights": {"name": "Lights", "lights": {"teto": {"entity": "light.teto", "name": "Teto"}}},
}


@pytest.fixture
def index(ha: HomeAssistant) -> Any:
    devices = module("setup.schema").CONFIG_SCHEMA({DOMAIN: {"devices": HOUSE}})[DOMAIN]["devices"]
    return module("setup.catalogue").index(devices)


def ref(device: str | None, key: str) -> Any:
    return module("core.resolve").Ref(device, key)


def find(index: Any, here: str, device: str | None, key: str) -> Any:
    return module("core.resolve").find(index, here, ref(device, key))


def test_a_features_own_key(index: Any) -> None:
    target = find(index, "washer", None, "appliance_running")
    assert (target.builder, target.by, target.item, target.actions) == ("appliance", None, None, ())
    assert target.platform is Platform.BINARY_SENSOR
    assert target.local == "running"
    assert target.unique_id == "pururu_washer_appliance_running"
    assert target.entity_id() == "binary_sensor.pururu_washer_appliance_running"


def test_a_ready_made_alert_is_by_alerts(index: Any) -> None:
    target = find(index, "washer", None, "appliance_alert_offline")
    assert (target.builder, target.by) == ("appliance", "alerts")


def test_a_configured_key_takes_its_builders_actions(index: Any) -> None:
    target = find(index, "washer", None, "switch_plug")
    assert (target.builder, target.platform, target.actions) == ("switches", Platform.SWITCH, SWITCH_ACTIONS)


def test_an_items_key_knows_its_item(index: Any) -> None:
    target = find(index, "washer", None, "program_executable_clean_cycles_total")
    assert (target.builder, target.item) == ("programs", "executable_clean")


def test_a_meter_is_by_statistics(index: Any) -> None:
    """The statistics aspect's keys are in the index whatever the settings, as the builder's own."""
    target = find(index, "washer", None, "appliance_runtime_today")
    assert (target.builder, target.by, target.item) == ("appliance", "statistics", None)
    assert target.platform is Platform.SENSOR
    assert target.unique_id == "pururu_washer_appliance_runtime_today"


def test_an_items_meter_knows_its_item(index: Any) -> None:
    target = find(index, "washer", None, "program_executable_clean_cycles_year")
    assert (target.builder, target.by, target.item) == ("programs", "statistics", "executable_clean")


def test_another_devices_key(index: Any) -> None:
    target = find(index, "washer", "lights", "light_teto")
    assert (target.device.key, target.builder, target.actions) == ("lights", "lights", SWITCH_ACTIONS)
    assert target.unique_id == "pururu_lights_light_teto"


@pytest.mark.parametrize(("device", "key"), [
    pytest.param(None, "appliance_nothing", id="unknown key"),
    pytest.param("dryer", "appliance_running", id="unknown device"),
    pytest.param("lights", "appliance_running", id="a key the other device can't create"),
])
def test_what_isnt_there_is_none(index: Any, device: str | None, key: str) -> None:
    assert find(index, "washer", device, key) is None


def test_the_current_entity_id_follows_a_rename(ha: HomeAssistant, index: Any) -> None:
    registry = er.async_get(ha)
    registry.async_get_or_create("binary_sensor", DOMAIN, "pururu_washer_appliance_running",
                                 suggested_object_id="lavadora_ligada")
    target = find(index, "washer", None, "appliance_running")
    assert target.current_entity_id(ha) == "binary_sensor.lavadora_ligada"


def test_a_reference_reads_as_written() -> None:
    assert ref(None, "appliance_running").text == "appliance_running"
    assert ref("washer", "appliance_running").text == "washer.appliance_running"


# --- the one reference form ---------------------------------------------------------------


@pytest.mark.parametrize(("text", "device", "key"), [
    pytest.param("appliance_running", None, "appliance_running", id="this device"),
    pytest.param("washer.appliance_running", "washer", "appliance_running", id="another device"),
])
def test_a_reference_parses_as_written(ha: HomeAssistant, text: str, device: str | None, key: str) -> None:
    parsed = module("core.resolve").Ref.parse(text)
    assert (parsed.device, parsed.key) == (device, key)
    assert parsed.text == text


@pytest.mark.parametrize("text", [
    pytest.param(".appliance_running", id="no device"),
    pytest.param("washer.", id="no key"),
    pytest.param("a.b.c", id="two dots"),
    pytest.param("", id="empty"),
])
def test_a_reference_not_validated_is_a_programming_error(ha: HomeAssistant, text: str) -> None:
    """Ref.parse reads what reference validated: other text wouldn't read back as written."""
    parse = module("core.resolve").Ref.parse
    with pytest.raises(ValueError, match="is not a validated reference"):
        parse(text)


@pytest.mark.parametrize(("validator", "value"), [
    pytest.param("reference", "appliance_running", id="a reference, local"),
    pytest.param("reference", "washer.appliance_running", id="a reference, of another device"),
    pytest.param("local_key", "switch_plug", id="a local key"),
    pytest.param("device_reference", "lights.light_teto", id="a device's key"),
])
def test_a_reference_is_accepted(ha: HomeAssistant, validator: str, value: str) -> None:
    assert getattr(module("core.resolve"), validator)(value) == value


@pytest.mark.parametrize(("validator", "value", "message"), [
    pytest.param("reference", "washer.", "washer. is neither an entity key nor <device>.<key>",
                 id="no key"),
    pytest.param("reference", ".appliance_running",
                 ".appliance_running is neither an entity key nor <device>.<key>", id="no device"),
    pytest.param("reference", "a.b.c", "a.b.c is neither an entity key nor <device>.<key>",
                 id="two dots"),
    pytest.param("reference", "Washer.appliance_running", "invalid slug Washer", id="not a slug"),
    pytest.param("local_key", "washer.switch_plug",
                 "washer.switch_plug must be of this device: its entity key, without <device>. or <domain>.",
                 id="a local key with a device"),
    pytest.param("local_key", "Switch", "invalid slug Switch", id="a local key not a slug"),
    pytest.param("device_reference", "light_teto", "light_teto needs its device: <device>.light_teto",
                 id="a light group's member without its device"),
    pytest.param("reference", "", "an entity key can't be empty", id="an empty reference"),
    pytest.param("local_key", "", "an entity key can't be empty", id="an empty local key"),
    pytest.param("device_reference", "", "an entity key can't be empty", id="an empty device's key"),
])
def test_a_reference_is_refused(ha: HomeAssistant, validator: str, value: str, message: str) -> None:
    validate = getattr(module("core.resolve"), validator)
    with pytest.raises(vol.Invalid, match=re.escape(message)):
        validate(value)
