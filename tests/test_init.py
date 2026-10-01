"""pururu: the configuration, devices, references, taken IDs, reloads and the entry.

Three made-up features stand in for real ones: `gauge` creates a sensor and a
binary sensor, and can create a `spare` sensor it never builds; `tags` is
configured: a sensor per key of its block, named by the block; `watch` refers
to one entity (`of`, a path, of this device or another) and shows its current
entity ID.
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

LEVEL = "sensor.pururu_dummy_gizmo_gauge_level"
ACTIVE = "binary_sensor.pururu_dummy_gizmo_gauge_active"
SEEN = "sensor.pururu_dummy_gizmo_watch_seen"
GAUGE = {"source": "sensor.dummy_source"}
GIZMO = {"name": "Gizmo", "gauge": GAUGE}
PANEL = {"name": "Panel", "gauge": GAUGE}
FIRST = "sensor.pururu_dummy_gizmo_tags_first"
SECOND = "sensor.pururu_dummy_gizmo_tags_second"
TAGS = {"first": {"name": "First"}, "second": {"name": "Second"}}


@pytest.fixture(autouse=True)
def dummy(ha: HomeAssistant) -> Iterator[None]:
    """Put `gauge`, `tags` and `watch` in FEATURES for the test."""
    feature = module("core.feature")
    roles = module("core.roles")
    entity = module("core.entity")
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

    class Tag(entity.PururuEntity, SensorEntity):
        def __init__(self, device: Any, entity_key: str, name: str) -> None:
            self._identify(device, Platform.SENSOR, entity_key, name)
            self._attr_native_value = entity_key

    class Seen(entity.PururuEntity, SensorEntity):
        def __init__(self, device: Any, of: str, watched: str, *, here: bool) -> None:
            self._identify(device, Platform.SENSOR, "seen")
            self.follows = (of,) if here else ()
            self._attr_native_value = watched

    resolve = module("core.resolve")

    added = {
        "gauge": feature.Feature(
            schema=vol.Schema({vol.Required("source"): cv.entity_id}),
            namespace="gauge",
            entity_keys={"level": Platform.SENSOR, "active": Platform.BINARY_SENSOR,
                         "spare": Platform.SENSOR},
            build=lambda hass, device, config, inputs: [Level(device, config["source"]),
                                                        Active(device)],
            example=GAUGE,
        ),
        "tags": feature.Feature(
            schema=vol.All(vol.Schema({cv.slug: vol.Schema({vol.Required("name"): cv.string})}),
                           vol.Length(min=1)),
            namespace="tags",
            entity_keys={},
            build=lambda hass, device, config, inputs: [Tag(device, key, tag["name"])
                                                        for key, tag in config.items()],
            example={"first": {"name": "First"}},
            roles=(roles.Configured(Platform.SENSOR),),
        ),
        "watch": feature.Feature(
            schema=vol.Schema({vol.Required("of"): resolve.path}),
            namespace="watch",
            entity_keys={"seen": Platform.SENSOR},
            build=lambda hass, device, config, inputs: [
                Seen(device, config["of"], inputs[config["of"]],
                     here=resolve.Ref.parse(config["of"]).owner == "here")],
            example={"of": "gauge.level"},
            roles=(roles.Refers(lambda config: [(("of",), resolve.Ref.parse(config["of"]))], others=True),),
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
    assert await setup(ha, {"dummy_gizmo": GIZMO})
    device = device_of(ha, "dummy_gizmo")
    assert device is not None
    assert device.name == "Gizmo"
    assert held(ha, "dummy_gizmo") == {LEVEL, ACTIVE}
    entry = er.async_get(ha).async_get(LEVEL)
    assert entry is not None
    assert entry.platform == DOMAIN
    assert entry.unique_id == "pururu_dummy_gizmo_gauge_level"
    assert entry.translation_key == "gauge_level"
    assert ha.states.get(LEVEL).attributes["source"] == "sensor.dummy_source"


@pytest.mark.parametrize("device", [
    pytest.param({"gauge": GAUGE}, id="no name"),
    pytest.param({"name": "Gizmo"}, id="no feature"),
    pytest.param({**GIZMO, "colour": "red"}, id="unknown key"),
    pytest.param({**GIZMO, "area": ["despensa"]}, id="area a list"),
    pytest.param({**GIZMO, "area": True}, id="area a boolean"),
    pytest.param({**GIZMO, "area": 123}, id="area a number not in areas"),
    pytest.param({"name": "Gizmo", "gauge": {"source": "not an entity"}}, id="bad feature block"),
])
async def test_invalid_device_is_refused(ha: HomeAssistant, device: dict[str, Any]) -> None:
    assert not await setup(ha, {"dummy_gizmo": device})
    assert device_of(ha, "dummy_gizmo") is None


async def test_a_blank_device_name_is_refused_at_its_path(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    device = {**GIZMO, "name": " "}
    assert not await setup(ha, {"dummy_gizmo": device})
    assert "length of value must be at least 1 for dictionary value 'pururu->devices->dummy_gizmo->name'" in caplog.text


async def test_a_configured_feature_creates_an_entity_per_key(ha: HomeAssistant) -> None:
    assert await setup(ha, {"dummy_gizmo": {**GIZMO, "tags": TAGS}})
    assert held(ha, "dummy_gizmo") == {LEVEL, ACTIVE, FIRST, SECOND}
    assert ha.states.get(FIRST).attributes["friendly_name"] == "Gizmo First"
    entry = er.async_get(ha).async_get(FIRST)
    assert entry is not None
    assert entry.unique_id == "pururu_dummy_gizmo_tags_first"
    assert entry.translation_key is None


async def test_a_configured_name_is_the_same_in_portuguese(ha: HomeAssistant) -> None:
    ha.config.language = "pt-BR"
    assert await setup(ha, {"dummy_gizmo": {**GIZMO, "tags": TAGS}})
    assert ha.states.get(SECOND).attributes["friendly_name"] == "Gizmo Second"


async def test_a_configured_key_may_be_another_features_entity_key(ha: HomeAssistant) -> None:
    """Each feature has its own namespace: tags' level is not gauge's."""
    assert await setup(ha, {"dummy_gizmo": {**GIZMO, "tags": {"level": {"name": "Level"},
                                                               "active": {"name": "Active"}}}})
    assert held(ha, "dummy_gizmo") == {LEVEL, ACTIVE, "sensor.pururu_dummy_gizmo_tags_level",
                                       "sensor.pururu_dummy_gizmo_tags_active"}


async def test_a_feature_gets_the_entity_key_it_refers_to(ha: HomeAssistant) -> None:
    assert await setup(ha, {"dummy_gizmo": {**GIZMO, "watch": {"of": "gauge.active"}}})
    assert ha.states.get(SEEN).state == ACTIVE
    assert held(ha, "dummy_gizmo") == {LEVEL, ACTIVE, SEEN}


async def test_a_reference_to_another_device_gets_that_devices_entity(ha: HomeAssistant) -> None:
    """A Ref with a device resolves on that device, not on the referrer's own."""
    gizmo = {**GIZMO, "watch": {"of": "device.dummy_panel.gauge.active"}}
    assert await setup(ha, {"dummy_gizmo": gizmo, "dummy_panel": PANEL})
    assert ha.states.get(SEEN).state == "binary_sensor.pururu_dummy_panel_gauge_active"


async def test_a_device_key_without_generates_builds(ha: HomeAssistant) -> None:
    """A device key is a builder like any other: its inputs don't assume Generates."""
    device_keys = module("device_keys").DEVICE_KEYS
    device_keys["extra"] = module("features").FEATURES["tags"]
    try:
        build = module("setup.build")
        config = {"name": "Gizmo", "extra": TAGS}
        index = module("setup.catalogue").index({"dummy_gizmo": config})
        built, _ = build.build(ha, "dummy_gizmo", config, index, {}, {})
        assert {entity.entity_id for entity, _ in built} == {
            "sensor.pururu_dummy_gizmo_tags_first", "sensor.pururu_dummy_gizmo_tags_second"}
    finally:
        del device_keys["extra"]


async def test_it_can_refer_to_a_configured_entity_key(ha: HomeAssistant) -> None:
    assert await setup(ha, {"dummy_gizmo": {**GIZMO, "tags": TAGS, "watch": {"of": "tags.first"}}})
    assert ha.states.get(SEEN).state == FIRST


@pytest.mark.parametrize(("of", "why"), [
    pytest.param("gauge.nothing", "gauge.nothing is not an entity of this device", id="unknown key"),
    pytest.param("watch.seen", "watch.seen is not another block's entity", id="its own key"),
    pytest.param("tags.first", "tags.first: tags is not a block of this device",
                 id="a configured key the device doesn't have"),
])
async def test_a_reference_to_no_entity_of_another_feature_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, of: str, why: str) -> None:
    assert not await setup(ha, {"dummy_gizmo": {**GIZMO, "watch": {"of": of}}})
    assert f"watch: {why}" in caplog.text


async def test_no_devices_creates_no_entry(ha: HomeAssistant) -> None:
    assert await setup(ha, {})
    assert not ha.config_entries.async_entries(DOMAIN)


# --- areas --------------------------------------------------------------------


def area_of(hass: HomeAssistant, key: str) -> str | None:
    """The area ID of device `key`."""
    device = device_of(hass, key)
    assert device is not None, f"no device {key}"
    return device.area_id


DESPENSA = {"despensa": {"name": "Despensa"}}


async def test_a_device_goes_to_its_area(ha: HomeAssistant) -> None:
    assert await setup(ha, {"dummy_gizmo": {**GIZMO, "area": "despensa"}}, areas=DESPENSA)
    assert area_of(ha, "dummy_gizmo") == "despensa"


async def test_a_reload_takes_the_device_back_to_its_area(ha: HomeAssistant) -> None:
    """The configuration wins over an area the user picked in the UI."""
    devices = {"dummy_gizmo": {**GIZMO, "area": "despensa"}}
    assert await setup(ha, devices, areas=DESPENSA)
    atelier = ar.async_get(ha).async_create("Atelier")
    device = device_of(ha, "dummy_gizmo")
    assert device is not None
    dr.async_get(ha).async_update_device(device.id, area_id=atelier.id)
    await reload(ha, devices, areas=DESPENSA)
    assert area_of(ha, "dummy_gizmo") == "despensa"


async def test_an_area_left_out_is_an_error_and_the_device_still_created(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """HA refuses the area (its name is another area's): the device stays where it was."""
    ar.async_get(ha).async_create("Despensa")  # ID despensa, not configured
    areas = {"laundry": {"name": "Despensa"}}
    assert await setup(ha, {"dummy_gizmo": {**GIZMO, "area": "laundry"}}, areas=areas)
    assert area_of(ha, "dummy_gizmo") is None
    assert held(ha, "dummy_gizmo") == {LEVEL, ACTIVE}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any("dummy_gizmo" in message and "laundry" in message for message in errors), errors


async def test_without_an_area_the_device_keeps_the_one_it_has(ha: HomeAssistant) -> None:
    assert await setup(ha, {"dummy_gizmo": {**GIZMO, "area": "despensa"}}, areas=DESPENSA)
    await reload(ha, {"dummy_gizmo": GIZMO}, areas=DESPENSA)
    assert area_of(ha, "dummy_gizmo") == "despensa"


async def test_a_device_with_nothing_created_has_no_area_to_go_to(ha: HomeAssistant) -> None:
    registry = er.async_get(ha)
    registry.async_get_or_create(
        "sensor", "template", "someone_else", suggested_object_id="pururu_dummy_gizmo_gauge_level")
    registry.async_get_or_create(
        "binary_sensor", "template", "someone_else", suggested_object_id="pururu_dummy_gizmo_gauge_active")
    assert await setup(ha, {"dummy_gizmo": {**GIZMO, "area": "despensa"}}, areas=DESPENSA)
    assert device_of(ha, "dummy_gizmo") is None


async def test_an_area_not_in_areas_is_refused(ha: HomeAssistant) -> None:
    """Even one made in the UI: the device's area is one of pururu's."""
    atelier = ar.async_get(ha).async_create("Atelier")
    assert not await setup(ha, {"dummy_gizmo": {**GIZMO, "area": atelier.id}}, areas=DESPENSA)
    assert device_of(ha, "dummy_gizmo") is None


# --- IDs already taken ---------------------------------------------------------


async def test_id_of_another_integration_is_an_error_not_a_suffix(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    other = er.async_get(ha).async_get_or_create(
        "sensor", "template", "someone_else", suggested_object_id="pururu_dummy_gizmo_gauge_level")
    assert other.entity_id == LEVEL
    assert await setup(ha, {"dummy_gizmo": GIZMO})
    assert ha.states.get(f"{LEVEL}_2") is None
    assert held(ha, "dummy_gizmo") == {ACTIVE}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(LEVEL in message and "template" in message for message in errors), errors


async def test_a_renamed_entity_is_still_ours(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """A user rename must not free our old ID for someone else to be seen as its holder."""
    assert await setup(ha, {"dummy_gizmo": GIZMO})
    registry = er.async_get(ha)
    renamed = registry.async_update_entity(LEVEL, new_entity_id="sensor.atelier_level")
    other = registry.async_get_or_create(
        "sensor", "template", "someone_else", suggested_object_id="pururu_dummy_gizmo_gauge_level")
    assert other.entity_id == LEVEL

    caplog.clear()
    await reload(ha, {"dummy_gizmo": GIZMO})

    assert ha.states.get("sensor.atelier_level").state == "1"
    assert held(ha, "dummy_gizmo") == {renamed.entity_id, ACTIVE}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert not any("atelier_level" in message for message in errors), errors


async def test_what_refers_to_an_entity_not_created_is_not_created_either(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(
        "sensor", "template", "someone_else", suggested_object_id="pururu_dummy_gizmo_gauge_level")
    assert await setup(ha, {"dummy_gizmo": {**GIZMO, "watch": {"of": "gauge.level"}}})
    assert ha.states.get(SEEN) is None
    assert held(ha, "dummy_gizmo") == {ACTIVE}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(SEEN in message and LEVEL in message for message in errors), errors


async def test_what_refers_to_an_entity_its_settings_dont_build_is_not_created(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """gauge_spare is a key gauge can create, so the reference is valid; it's never built."""
    assert await setup(ha, {"dummy_gizmo": {**GIZMO, "watch": {"of": "gauge.spare"}}})
    assert ha.states.get(SEEN) is None
    assert held(ha, "dummy_gizmo") == {LEVEL, ACTIVE}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert (f"{SEEN} watches sensor.pururu_dummy_gizmo_gauge_spare, which this device's "
            "settings don't create (turn it on, or watch another entity); not creating it"
            in errors), errors


async def test_a_renamed_entity_reaches_what_refers_to_it(ha: HomeAssistant) -> None:
    assert await setup(ha, {"dummy_gizmo": {**GIZMO, "watch": {"of": "gauge.level"}}})
    er.async_get(ha).async_update_entity(LEVEL, new_entity_id="sensor.atelier_level")
    await ha.async_block_till_done()
    assert ha.states.get(SEEN).state == "sensor.atelier_level"


async def test_renaming_another_integrations_entity_does_not_reload(ha: HomeAssistant) -> None:
    assert await setup(ha, {"dummy_gizmo": GIZMO})
    registry = er.async_get(ha)
    registry.async_get_or_create("sensor", "template", "someone_else",
                                 suggested_object_id="dummy_other")
    [entry] = ha.config_entries.async_entries(DOMAIN)
    with patch.object(ha.config_entries, "async_schedule_reload") as reloads:
        registry.async_update_entity("sensor.dummy_other", new_entity_id="sensor.dummy_renamed")
        registry.async_update_entity(LEVEL, name="Atelier level")
        await ha.async_block_till_done()
    reloads.assert_not_called()
    assert entry.state is ConfigEntryState.LOADED


async def test_id_of_an_entity_without_unique_id_is_an_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    ha.states.async_set(LEVEL, "5")
    assert await setup(ha, {"dummy_gizmo": GIZMO})
    assert ha.states.get(LEVEL).state == "5"
    assert ha.states.get(f"{LEVEL}_2") is None
    assert any(LEVEL in r.getMessage() for r in caplog.records if r.levelname == "ERROR")


# --- reloads and the entry -----------------------------------------------------


async def test_reload_with_the_same_devices_keeps_them(ha: HomeAssistant) -> None:
    assert await setup(ha, {"dummy_gizmo": GIZMO})
    device = device_of(ha, "dummy_gizmo")
    await reload(ha, {"dummy_gizmo": GIZMO})
    assert device_of(ha, "dummy_gizmo") == device
    assert held(ha, "dummy_gizmo") == {LEVEL, ACTIVE}


async def test_reload_that_drops_a_feature_removes_its_entities(ha: HomeAssistant) -> None:
    assert await setup(ha, {"dummy_gizmo": {**GIZMO, "watch": {"of": "gauge.level"}}})
    await reload(ha, {"dummy_gizmo": GIZMO})
    assert er.async_get(ha).async_get(SEEN) is None
    assert ha.states.get(SEEN) is None
    assert held(ha, "dummy_gizmo") == {LEVEL, ACTIVE}


async def test_reload_that_drops_a_device_removes_it(ha: HomeAssistant) -> None:
    assert await setup(ha, {"dummy_gizmo": GIZMO, "dummy_panel": PANEL})
    await reload(ha, {"dummy_gizmo": GIZMO})
    assert device_of(ha, "dummy_panel") is None
    assert er.async_get(ha).async_get("sensor.pururu_dummy_panel_gauge_level") is None
    assert held(ha, "dummy_gizmo") == {LEVEL, ACTIVE}


async def test_reload_without_devices_removes_them_all(ha: HomeAssistant) -> None:
    assert await setup(ha, {"dummy_gizmo": GIZMO})
    await reload(ha, {})
    assert device_of(ha, "dummy_gizmo") is None
    assert entry_entities(ha) == set()


async def test_invalid_reload_keeps_the_devices(ha: HomeAssistant) -> None:
    assert await setup(ha, {"dummy_gizmo": GIZMO})
    await reload(ha, {"dummy_gizmo": {"name": "Gizmo"}})
    assert held(ha, "dummy_gizmo") == {LEVEL, ACTIVE}


async def test_first_device_on_reload_creates_the_entry(ha: HomeAssistant) -> None:
    assert await setup(ha, {})
    await reload(ha, {"dummy_gizmo": GIZMO})
    assert held(ha, "dummy_gizmo") == {LEVEL, ACTIVE}


async def test_a_second_import_aborts(ha: HomeAssistant) -> None:
    """One entry owns every device (single_config_entry)."""
    assert await setup(ha, {"dummy_gizmo": GIZMO})
    result = await ha.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data={})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
    assert len(ha.config_entries.async_entries(DOMAIN)) == 1


async def test_reload_sets_up_a_failed_entry_again(ha: HomeAssistant) -> None:
    """A reload must not skip an entry that isn't LOADED (e.g. after a SETUP_ERROR)."""
    feature = module("core.feature")
    features = module("features").FEATURES
    original = features["gauge"]
    calls = {"n": 0}

    def flaky_build(hass: Any, device: Any, config: Any, inputs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return original.build(hass, device, config, inputs)

    features["gauge"] = feature.Feature(
        schema=original.schema, namespace=original.namespace, entity_keys=original.entity_keys,
        build=flaky_build, example=original.example, roles=original.roles,
    )
    assert await setup(ha, {"dummy_gizmo": GIZMO})
    [entry] = ha.config_entries.async_entries(DOMAIN)
    assert entry.state is ConfigEntryState.SETUP_ERROR

    await reload(ha, {"dummy_gizmo": GIZMO})
    assert entry.state is ConfigEntryState.LOADED
    assert held(ha, "dummy_gizmo") == {LEVEL, ACTIVE}


async def test_deleting_the_entry_removes_devices_and_entities(ha: HomeAssistant) -> None:
    assert await setup(ha, {"dummy_gizmo": GIZMO})
    [entry] = ha.config_entries.async_entries(DOMAIN)
    await ha.config_entries.async_remove(entry.entry_id)
    await ha.async_block_till_done()
    assert device_of(ha, "dummy_gizmo") is None
    assert er.async_get(ha).async_get(LEVEL) is None


async def test_a_device_no_longer_configured_goes_at_set_up(ha: HomeAssistant) -> None:
    """A device the entry had before a restart, gone from the configuration since."""
    entry = MockConfigEntry(domain=DOMAIN, title="Pururu")
    entry.add_to_hass(ha)
    dr.async_get(ha).async_get_or_create(config_entry_id=entry.entry_id,
                                         identifiers={(DOMAIN, "dummy_gone")}, name="Gone")
    assert await setup(ha, {"dummy_gizmo": GIZMO})
    assert device_of(ha, "dummy_gone") is None
    assert held(ha, "dummy_gizmo") == {LEVEL, ACTIVE}


async def test_entities_from_before_namespaces_go_at_set_up(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """0.1.4's IDs had no namespace: those entities are stale, and the namespaced ones replace them."""
    entry = MockConfigEntry(domain=DOMAIN, title="Pururu")
    entry.add_to_hass(ha)
    old = er.async_get(ha).async_get_or_create(
        "sensor", DOMAIN, "pururu_dummy_gizmo_level", config_entry=entry,
        suggested_object_id="pururu_dummy_gizmo_level")
    assert await setup(ha, {"dummy_gizmo": GIZMO})
    assert er.async_get(ha).async_get(old.entity_id) is None
    assert held(ha, "dummy_gizmo") == {LEVEL, ACTIVE}
    assert not [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
