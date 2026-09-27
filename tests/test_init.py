"""pururu: the configuration, devices, capabilities, taken IDs, reloads and the entry.

Two made-up features stand in for real ones: `gauge` creates a sensor and a
binary sensor and provides `activity` (its binary sensor); `echo` requires
`activity` and shows the entity ID it gets.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import (
    area_registry as ar,
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from helpers import DOMAIN, device_of, held, module, reload, setup

LEVEL = "sensor.pururu_demo_widget_level"
ACTIVE = "binary_sensor.pururu_demo_widget_active"
ECHO = "sensor.pururu_demo_widget_echo"
GAUGE = {"source": "sensor.demo_source"}
WIDGET = {"name": "Widget", "gauge": GAUGE}
PANEL = {"name": "Panel", "gauge": GAUGE}


@pytest.fixture(autouse=True)
def demo(ha: HomeAssistant) -> Iterator[None]:
    """Put `gauge` and `echo` in FEATURES for the test."""
    feature = module("feature")
    entity = module("entity")
    features = module("features").FEATURES

    class Level(entity.PururuEntity, SensorEntity):
        def __init__(self, device: Any, source: str) -> None:
            self._identify(device, Platform.SENSOR, "level")
            self._attr_native_value = 1
            self._attr_extra_state_attributes = {"source": source}

    class Active(entity.PururuEntity, BinarySensorEntity):
        def __init__(self, device: Any) -> None:
            self._identify(device, Platform.BINARY_SENSOR, "active")
            self._attr_is_on = True

    class Echo(entity.PururuEntity, SensorEntity):
        def __init__(self, device: Any, activity: str) -> None:
            self._identify(device, Platform.SENSOR, "echo")
            self._attr_native_value = activity

    added = {
        "gauge": feature.Feature(
            schema=vol.Schema({vol.Required("source"): cv.entity_id}),
            metrics={"level": Platform.SENSOR, "active": Platform.BINARY_SENSOR},
            build=lambda hass, device, config, inputs: [Level(device, config["source"]),
                                                        Active(device)],
            example=GAUGE,
            provides={"activity": "active"},
        ),
        "echo": feature.Feature(
            schema=vol.Schema({vol.Required("activity_from"): cv.slug}),
            metrics={"echo": Platform.SENSOR},
            build=lambda hass, device, config, inputs: [Echo(device, inputs["activity"])],
            example={"activity_from": "gauge"},
            requires=("activity",),
        ),
    }
    features.update(added)
    yield
    for name in added:
        features.pop(name)


def entry_entities(hass: HomeAssistant) -> set[str]:
    """Entity IDs the entry holds in the entity registry."""
    [entry] = hass.config_entries.async_entries(DOMAIN)
    return {e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}


# --- configuration and devices ----------------------------------------------


async def test_device_holds_what_its_features_create(ha: HomeAssistant) -> None:
    assert await setup(ha, {"demo_widget": WIDGET})
    device = device_of(ha, "demo_widget")
    assert device is not None
    assert device.name == "Widget"
    assert held(ha, "demo_widget") == {LEVEL, ACTIVE}
    entry = er.async_get(ha).async_get(LEVEL)
    assert entry is not None
    assert entry.platform == DOMAIN
    assert entry.unique_id == "pururu_demo_widget_level"
    assert ha.states.get(LEVEL).attributes["source"] == "sensor.demo_source"


async def test_a_capability_reaches_the_feature_that_requires_it(ha: HomeAssistant) -> None:
    assert await setup(ha, {"demo_widget": {**WIDGET, "echo": {"activity_from": "gauge"}}})
    assert ha.states.get(ECHO).state == ACTIVE
    assert held(ha, "demo_widget") == {LEVEL, ACTIVE, ECHO}


@pytest.mark.parametrize("device", [
    pytest.param({"gauge": GAUGE}, id="no name"),
    pytest.param({"name": "Widget"}, id="no feature"),
    pytest.param({**WIDGET, "colour": "red"}, id="unknown key"),
    pytest.param({**WIDGET, "area": ["lavanderia"]}, id="area a list"),
    pytest.param({**WIDGET, "area": True}, id="area a boolean"),
    pytest.param({**WIDGET, "area": 123}, id="area a number not in areas"),
    pytest.param({"name": "Widget", "gauge": {"source": "not an entity"}}, id="bad feature block"),
    pytest.param({"name": "Widget", "echo": {"activity_from": "gauge"}}, id="from a missing feature"),
    pytest.param({**WIDGET, "echo": {"activity_from": "echo"}}, id="from one that doesn't provide it"),
])
async def test_invalid_device_is_refused(ha: HomeAssistant, device: dict[str, Any]) -> None:
    assert not await setup(ha, {"demo_widget": device})
    assert device_of(ha, "demo_widget") is None


async def test_no_devices_creates_no_entry(ha: HomeAssistant) -> None:
    assert await setup(ha, {})
    assert not ha.config_entries.async_entries(DOMAIN)


# --- areas --------------------------------------------------------------------


def area_of(hass: HomeAssistant, key: str) -> str | None:
    """The area ID of device `key`."""
    device = device_of(hass, key)
    assert device is not None, f"no device {key}"
    return device.area_id


LAVANDERIA = {"lavanderia": {"name": "Lavanderia"}}


async def test_a_device_goes_to_its_area(ha: HomeAssistant) -> None:
    assert await setup(ha, {"demo_widget": {**WIDGET, "area": "lavanderia"}}, areas=LAVANDERIA)
    assert area_of(ha, "demo_widget") == "lavanderia"


async def test_a_reload_takes_the_device_back_to_its_area(ha: HomeAssistant) -> None:
    """The configuration wins over an area the user picked in the UI."""
    devices = {"demo_widget": {**WIDGET, "area": "lavanderia"}}
    assert await setup(ha, devices, areas=LAVANDERIA)
    kitchen = ar.async_get(ha).async_create("Kitchen")
    device = device_of(ha, "demo_widget")
    assert device is not None
    dr.async_get(ha).async_update_device(device.id, area_id=kitchen.id)
    await reload(ha, devices, areas=LAVANDERIA)
    assert area_of(ha, "demo_widget") == "lavanderia"


async def test_an_area_left_out_is_an_error_and_the_device_still_created(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """HA refuses the area (its name is another area's): the device stays where it was."""
    ar.async_get(ha).async_create("Lavanderia")  # ID lavanderia, not configured
    areas = {"laundry": {"name": "Lavanderia"}}
    assert await setup(ha, {"demo_widget": {**WIDGET, "area": "laundry"}}, areas=areas)
    assert area_of(ha, "demo_widget") is None
    assert held(ha, "demo_widget") == {LEVEL, ACTIVE}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any("demo_widget" in message and "laundry" in message for message in errors), errors


async def test_without_an_area_the_device_keeps_the_one_it_has(ha: HomeAssistant) -> None:
    assert await setup(ha, {"demo_widget": {**WIDGET, "area": "lavanderia"}}, areas=LAVANDERIA)
    await reload(ha, {"demo_widget": WIDGET}, areas=LAVANDERIA)
    assert area_of(ha, "demo_widget") == "lavanderia"


async def test_a_device_with_nothing_created_has_no_area_to_go_to(ha: HomeAssistant) -> None:
    registry = er.async_get(ha)
    registry.async_get_or_create(
        "sensor", "template", "someone_else", suggested_object_id="pururu_demo_widget_level")
    registry.async_get_or_create(
        "binary_sensor", "template", "someone_else", suggested_object_id="pururu_demo_widget_active")
    assert await setup(ha, {"demo_widget": {**WIDGET, "area": "lavanderia"}}, areas=LAVANDERIA)
    assert device_of(ha, "demo_widget") is None


async def test_an_area_not_in_areas_is_refused(ha: HomeAssistant) -> None:
    """Even one made in the UI: the device's area is one of pururu's."""
    kitchen = ar.async_get(ha).async_create("Kitchen")
    assert not await setup(ha, {"demo_widget": {**WIDGET, "area": kitchen.id}}, areas=LAVANDERIA)
    assert device_of(ha, "demo_widget") is None


# --- IDs already taken ---------------------------------------------------------


async def test_id_of_another_integration_is_an_error_not_a_suffix(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    other = er.async_get(ha).async_get_or_create(
        "sensor", "template", "someone_else", suggested_object_id="pururu_demo_widget_level")
    assert other.entity_id == LEVEL
    assert await setup(ha, {"demo_widget": WIDGET})
    assert ha.states.get(f"{LEVEL}_2") is None
    assert held(ha, "demo_widget") == {ACTIVE}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(LEVEL in message and "template" in message for message in errors), errors


async def test_a_renamed_entity_is_still_ours(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """A user rename must not free our old ID for someone else to be seen as its holder."""
    assert await setup(ha, {"demo_widget": WIDGET})
    registry = er.async_get(ha)
    renamed = registry.async_update_entity(LEVEL, new_entity_id="sensor.kitchen_level")
    other = registry.async_get_or_create(
        "sensor", "template", "someone_else", suggested_object_id="pururu_demo_widget_level")
    assert other.entity_id == LEVEL

    caplog.clear()
    await reload(ha, {"demo_widget": WIDGET})

    assert ha.states.get("sensor.kitchen_level").state == "1"
    assert held(ha, "demo_widget") == {renamed.entity_id, ACTIVE}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert not any("kitchen_level" in message for message in errors), errors


async def test_what_follows_an_entity_not_created_is_not_created_either(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Echo would follow the other integration's entity: it isn't created, and the log says why."""
    other = er.async_get(ha).async_get_or_create(
        "binary_sensor", "template", "someone_else", suggested_object_id="pururu_demo_widget_active")
    assert other.entity_id == ACTIVE
    assert await setup(ha, {"demo_widget": {**WIDGET, "echo": {"activity_from": "gauge"}}})
    assert ha.states.get(ECHO) is None
    assert held(ha, "demo_widget") == {LEVEL}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(ECHO in message and ACTIVE in message for message in errors), errors


async def test_a_renamed_capability_reaches_the_feature_that_requires_it(ha: HomeAssistant) -> None:
    """Renamed in the UI: the entry reloads, and echo gets the new ID."""
    assert await setup(ha, {"demo_widget": {**WIDGET, "echo": {"activity_from": "gauge"}}})
    er.async_get(ha).async_update_entity(ACTIVE, new_entity_id="binary_sensor.kitchen_active")
    await ha.async_block_till_done()
    assert ha.states.get(ECHO).state == "binary_sensor.kitchen_active"
    assert held(ha, "demo_widget") == {LEVEL, "binary_sensor.kitchen_active", ECHO}


async def test_renaming_another_integrations_entity_does_not_reload(ha: HomeAssistant) -> None:
    assert await setup(ha, {"demo_widget": WIDGET})
    registry = er.async_get(ha)
    registry.async_get_or_create("sensor", "template", "someone_else",
                                 suggested_object_id="demo_other")
    [entry] = ha.config_entries.async_entries(DOMAIN)
    with patch.object(ha.config_entries, "async_schedule_reload") as reloads:
        registry.async_update_entity("sensor.demo_other", new_entity_id="sensor.demo_renamed")
        registry.async_update_entity(LEVEL, name="Kitchen level")
        await ha.async_block_till_done()
    reloads.assert_not_called()
    assert entry.state is ConfigEntryState.LOADED


async def test_id_of_an_entity_without_unique_id_is_an_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    ha.states.async_set(LEVEL, "5")
    assert await setup(ha, {"demo_widget": WIDGET})
    assert ha.states.get(LEVEL).state == "5"
    assert ha.states.get(f"{LEVEL}_2") is None
    assert any(LEVEL in r.getMessage() for r in caplog.records if r.levelname == "ERROR")


# --- reloads and the entry -----------------------------------------------------


async def test_reload_with_the_same_devices_keeps_them(ha: HomeAssistant) -> None:
    assert await setup(ha, {"demo_widget": WIDGET})
    device = device_of(ha, "demo_widget")
    await reload(ha, {"demo_widget": WIDGET})
    assert device_of(ha, "demo_widget") == device
    assert held(ha, "demo_widget") == {LEVEL, ACTIVE}


async def test_reload_that_drops_a_feature_removes_its_entities(ha: HomeAssistant) -> None:
    assert await setup(ha, {"demo_widget": {**WIDGET, "echo": {"activity_from": "gauge"}}})
    await reload(ha, {"demo_widget": WIDGET})
    assert er.async_get(ha).async_get(ECHO) is None
    assert ha.states.get(ECHO) is None
    assert held(ha, "demo_widget") == {LEVEL, ACTIVE}


async def test_reload_that_drops_a_device_removes_it(ha: HomeAssistant) -> None:
    assert await setup(ha, {"demo_widget": WIDGET, "demo_panel": PANEL})
    await reload(ha, {"demo_widget": WIDGET})
    assert device_of(ha, "demo_panel") is None
    assert er.async_get(ha).async_get("sensor.pururu_demo_panel_level") is None
    assert held(ha, "demo_widget") == {LEVEL, ACTIVE}


async def test_reload_without_devices_removes_them_all(ha: HomeAssistant) -> None:
    assert await setup(ha, {"demo_widget": WIDGET})
    await reload(ha, {})
    assert device_of(ha, "demo_widget") is None
    assert entry_entities(ha) == set()


async def test_invalid_reload_keeps_the_devices(ha: HomeAssistant) -> None:
    assert await setup(ha, {"demo_widget": WIDGET})
    await reload(ha, {"demo_widget": {"name": "Widget"}})
    assert held(ha, "demo_widget") == {LEVEL, ACTIVE}


async def test_first_device_on_reload_creates_the_entry(ha: HomeAssistant) -> None:
    assert await setup(ha, {})
    await reload(ha, {"demo_widget": WIDGET})
    assert held(ha, "demo_widget") == {LEVEL, ACTIVE}


async def test_a_second_import_aborts(ha: HomeAssistant) -> None:
    """One entry owns every device (single_config_entry)."""
    assert await setup(ha, {"demo_widget": WIDGET})
    result = await ha.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data={})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
    assert len(ha.config_entries.async_entries(DOMAIN)) == 1


async def test_reload_sets_up_a_failed_entry_again(ha: HomeAssistant) -> None:
    """A reload must not skip an entry that isn't LOADED (e.g. after a SETUP_ERROR)."""
    feature = module("feature")
    features = module("features").FEATURES
    original = features["gauge"]
    calls = {"n": 0}

    def flaky_build(hass: Any, device: Any, config: Any, inputs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return original.build(hass, device, config, inputs)

    features["gauge"] = feature.Feature(
        schema=original.schema, metrics=original.metrics, build=flaky_build,
        example=original.example, provides=original.provides,
    )
    assert await setup(ha, {"demo_widget": WIDGET})
    [entry] = ha.config_entries.async_entries(DOMAIN)
    assert entry.state is ConfigEntryState.SETUP_ERROR

    await reload(ha, {"demo_widget": WIDGET})
    assert entry.state is ConfigEntryState.LOADED
    assert held(ha, "demo_widget") == {LEVEL, ACTIVE}


async def test_deleting_the_entry_removes_devices_and_entities(ha: HomeAssistant) -> None:
    assert await setup(ha, {"demo_widget": WIDGET})
    [entry] = ha.config_entries.async_entries(DOMAIN)
    await ha.config_entries.async_remove(entry.entry_id)
    await ha.async_block_till_done()
    assert device_of(ha, "demo_widget") is None
    assert er.async_get(ha).async_get(LEVEL) is None


async def test_a_device_no_longer_configured_goes_at_set_up(ha: HomeAssistant) -> None:
    """A device the entry had before a restart, gone from the configuration since."""
    entry = MockConfigEntry(domain=DOMAIN, title="Pururu")
    entry.add_to_hass(ha)
    dr.async_get(ha).async_get_or_create(config_entry_id=entry.entry_id,
                                         identifiers={(DOMAIN, "demo_gone")}, name="Gone")
    assert await setup(ha, {"demo_widget": WIDGET})
    assert device_of(ha, "demo_gone") is None
    assert held(ha, "demo_widget") == {LEVEL, ACTIVE}
