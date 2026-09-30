"""The contract, over every Feature in FEATURES and DEVICE_KEYS: a new one is covered here unchanged."""

import dataclasses
import json
from pathlib import Path
import re
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.setup import async_setup_component
import pytest
import voluptuous as vol

from helpers import DOMAIN, module

# A configured feature's block, valid on its own: for devices that need a feature besides
# the one under test (a non-map programs/appliance block still needs at least one feature)
SWITCHES = {"sprinkler": {"entity": "switch.greenhouse_sprinkler", "name": "Irrigador"}}

INTEGRATION = Path(__file__).resolve().parents[1] / "custom_components/pururu"


def load(name: str) -> dict[str, Any]:
    return json.loads((INTEGRATION / name).read_text())


def paths(tree: Any, prefix: str = "") -> set[str]:
    """Every key path of a translation tree."""
    if not isinstance(tree, dict):
        return {prefix}
    return {path for key, value in tree.items() for path in paths(value, f"{prefix}/{key}")}


def role(feature: Any, name: str) -> Any:
    """The feature's role of that class (roles.py), or None."""
    return feature.role(getattr(module("core.roles"), name))


def per_item(feature: Any) -> dict[str, Any]:
    """The entity keys it repeats per item, by suffix; none without Items."""
    items = role(feature, "Items")
    return dict(items.keys) if items else {}


def named_keys(feature: Any) -> dict[str, Any]:
    """Every key a feature's translations name in its namespace: its entity keys and its per-item suffixes.

    Not an aspect's keys: each aspect names its own (Place.named, aspect_groups).
    """
    return {**feature.entity_keys, **per_item(feature)}


def offered(features: dict[str, Any]) -> list[tuple[Any, str, Any]]:
    """(aspect, builder's key, builder) for every aspect a builder offers."""
    return [(aspect, name, feature) for aspect in module("aspects").ASPECTS
            for name, feature in features.items() if aspect.offered(feature)]


def aspect_keys(aspect: Any, name: str, feature: Any) -> dict[str, Any]:
    """Every local key the aspect can add for this builder, at any of its places (an item's suffixes)."""
    return {key: platform for place in aspect.places(feature, name)
            for key, platform in place.keys.items()}


def aspect_groups(aspect: Any, name: str, feature: Any) -> dict[str, Any]:
    """Where the aspect's keys for this builder are named, as each of its places says (Place.named)."""
    return {place.named(key): platform for place in aspect.places(feature, name)
            for key, platform in place.keys.items()}


def put(block: Any, path: tuple[str, ...], key: str, value: Any) -> Any:
    """`block` with `value` under `key` in each container `path` names (feature.walk's rule)."""
    if not path:
        return {**block, key: value}
    head, *rest = path
    each = module("core.feature").EACH
    keys = list(block) if head == each else [head] if head in block else []
    return {**block, **{k: put(block[k], tuple(rest), key, value) for k in keys}}


def with_examples(aspect: Any, name: str, feature: Any, block: Any) -> Any:
    """`block` with each place's example at every container the place names."""
    for place in aspect.places(feature, name):
        block = put(block, place.path, aspect.key, place.example)
    return block


def with_value(aspect: Any, name: str, feature: Any, block: Any, value: Any) -> Any:
    """`block` with `value` under the aspect's key at every container of every place."""
    for place in aspect.places(feature, name):
        block = put(block, place.path, aspect.key, value)
    return block


@pytest.fixture
def features(ha: HomeAssistant) -> dict[str, Any]:
    """Every Feature: a device's features, and the device keys creating entities (programs, reactions)."""
    return {**module("features").FEATURES, **module("device_keys").DEVICE_KEYS}


def test_translation_files_match() -> None:
    """pt-BR.json has exactly en.json's keys: nothing untranslated, nothing stale."""
    assert paths(load("translations/pt-BR.json")) == paths(load("translations/en.json"))


def test_namespaces_are_distinct_slugs(features: dict[str, Any]) -> None:
    """Every feature's entity keys are in its own namespace: no two features' entity IDs meet."""
    for name, feature in features.items():
        assert cv.slug(feature.namespace) == feature.namespace, name
        for other, theirs in features.items():
            if other != name:
                assert feature.namespace != theirs.namespace, f"{name} and {other}"
                assert not theirs.namespace.startswith(f"{feature.namespace}_"), f"{name} and {other}"


def test_no_entity_key_repeats_its_namespace(features: dict[str, Any]) -> None:
    """An appliance's `appliance` would be sensor.pururu_<key>_appliance_appliance: a fixed key never repeats its namespace."""
    for name, feature in features.items():
        assert feature.namespace not in named_keys(feature), name


def test_refers_names_entity_keys_as_in_an_entity_id(features: dict[str, Any]) -> None:
    """What a feature refers to is a qualified entity key, such as appliance_running: a slug."""
    for name, feature in features.items():
        if (refers := role(feature, "Refers")) is not None:
            for ref in refers.of(feature.schema(dict(feature.example))):
                assert cv.slug(ref.key) == ref.key, name


def test_every_entity_key_is_named_and_has_an_icon(features: dict[str, Any]) -> None:
    qualified = module("core.feature").qualified
    en, pt, icons = load("translations/en.json"), load("translations/pt-BR.json"), load("icons.json")
    for feature in features.values():
        for entity_key, platform in named_keys(feature).items():
            key = qualified(feature.namespace, entity_key)
            for translations in (en, pt):
                assert translations["entity"][platform][key]["name"], key
            assert icons["entity"][platform][key]["default"].startswith("mdi:"), key


def test_every_translated_entity_key_is_created(features: dict[str, Any]) -> None:
    """A name or an icon under a key no feature creates is left over, as from before namespaces."""
    qualified = module("core.feature").qualified
    created = {(str(platform), qualified(feature.namespace, entity_key))
               for feature in features.values()
               for entity_key, platform in named_keys(feature).items()}
    created |= {(str(platform), group) for aspect, name, feature in offered(features)
                for group, platform in aspect_groups(aspect, name, feature).items()}
    # The detector's (features/cycle/program): named once for every builder using it
    created |= {(str(platform), key)
                for key, platform in module("features.cycle.program").NAMED.items()}
    for name in ("translations/en.json", "icons.json"):
        listed = {(platform, key) for platform, keys in load(name)["entity"].items() for key in keys}
        assert listed <= created, f"{name}: {sorted(listed - created)}"


def test_the_detectors_keys_are_named(ha: HomeAssistant) -> None:
    """Each key the detector names, in both languages and with an icon: a phase's own with {item}, other's and its own two without.

    The states it shows by itself are named too: idle (the current phase only) and other.
    """
    program = module("features.cycle.program")
    en, pt, icons = load("translations/en.json"), load("translations/pt-BR.json"), load("icons.json")
    per_phase = {f"{program.PHASE}_{suffix}" for suffix in program.SUFFIXES}
    for key, platform in program.NAMED.items():
        for translations in (en, pt):
            text = translations["entity"][platform][key]["name"]
            assert text, key
            assert ("{item}" in text) == (key in per_phase), key
        assert icons["entity"][platform][key]["default"].startswith("mdi:"), key
    for translations in (en, pt):
        sensors = translations["entity"]["sensor"]
        assert {program.IDLE, program.OTHER} <= set(sensors["phase_current"]["state"])
        assert program.OTHER in sensors["phase_last"]["state"]
        assert program.IDLE not in sensors["phase_last"]["state"]


def test_example_is_valid_and_unknown_keys_are_refused(features: dict[str, Any]) -> None:
    for feature in features.values():
        feature.schema(dict(feature.example))
        with pytest.raises(vol.Invalid):
            feature.schema({**feature.example, "not_a_key": 1})


def test_every_platform_is_set_up(features: dict[str, Any]) -> None:
    platforms = module("const").PLATFORMS
    for name, feature in features.items():
        for entity_key, platform in named_keys(feature).items():
            assert platform in platforms, f"{name}'s {entity_key} is on {platform}, not in PLATFORMS"
        if (configured := role(feature, "Configured")) is not None:
            assert configured.platform in platforms, (
                f"{name}'s configured entities are on {configured.platform}, not in PLATFORMS")


def test_what_a_last_cycle_follows_is_a_cycle_source(
    ha: HomeAssistant, features: dict[str, Any]
) -> None:
    """Each last cycle follows the entity sending its cycles, a CycleSource: the appliance's running and each phase, a door's or a window's open, a program's runs."""
    cycle_source = module("features.cycle").CycleSource
    last_cycle = module("features.cycle.last").LastCycleValue
    device_cls = module("core.feature").Device
    mount = module("setup.catalogue").mount
    following: dict[str, set[str]] = {}
    for name, feature in features.items():
        if role(feature, "Refers") is not None:  # build needs inputs, e.g. alerts
            continue
        device = device_cls(key="dev", name="Dev", namespace=feature.namespace)
        block = mount(feature, name, dict(feature.example))
        built = {entity.key: entity for entity in feature.build(ha, device, block, {})}
        for entity in built.values():
            if isinstance(entity, last_cycle):
                (source,) = entity.sources
                assert isinstance(built[device.qualified(source)], cycle_source), (name, entity.key)
                following.setdefault(name, set()).add(source)
    assert set(following) == {"appliance", "door", "window", "programs"}
    assert following["appliance"] == {"running", "phase_warming", "phase_other"}


def test_a_derived_key_is_in_the_index(ha: HomeAssistant, features: dict[str, Any]) -> None:
    """What a validated block adds (roles.Derived) is listed by catalogue.keys, and the example builds only listed keys."""
    catalogue = module("setup.catalogue")
    device_cls = module("core.feature").Device
    deriving = [name for name, feature in features.items() if role(feature, "Derived")]
    assert deriving == ["appliance"]
    for name in deriving:
        feature = features[name]
        block = catalogue.mount(feature, name, dict(feature.example))
        derived = role(feature, "Derived").of(block)
        assert derived, f"{name}'s example derives no key"
        assert not set(derived) & set(feature.entity_keys), name
        listed = {entity_key for _, entity_key, _, _, _ in catalogue.keys({name: block})}
        assert set(derived) <= listed, name
        device = device_cls(key="dev", name="Dev", namespace=feature.namespace)
        built = {entity.key for entity in feature.build(ha, device, block, {})}
        assert built <= {device.qualified(key) for key in listed}, name


async def test_every_action_is_a_service_of_its_platform(ha: HomeAssistant, features: dict[str, Any]) -> None:
    """A program's step calls <platform>.<action> on the entity: the platform must have that service."""
    for name, feature in features.items():
        if (actions := role(feature, "Actions")) is None:
            continue
        configured = role(feature, "Configured")
        assert configured is not None, f"{name} takes actions: its entities must be on one platform"
        assert await async_setup_component(ha, configured.platform, {})
        for action in actions.services:
            assert ha.services.has_service(configured.platform, action), f"{name}: {configured.platform}.{action}"


@pytest.mark.parametrize("name", ["switches", "lights"])
def test_it_takes_turn_on_turn_off_and_toggle(features: dict[str, Any], name: str) -> None:
    assert role(features[name], "Actions").services == ("turn_on", "turn_off", "toggle")


def test_items_have_suffixes_and_slugs(features: dict[str, Any]) -> None:
    """Items need suffixes to repeat, and each item is a slug."""
    for name, feature in features.items():
        if (items := role(feature, "Items")) is not None:
            assert items.keys, name
            for item in items.of(feature.schema(dict(feature.example))):
                assert cv.slug(item.slug) == item.slug, name


def test_every_per_item_name_has_its_placeholder(features: dict[str, Any]) -> None:
    """A per-item entity's name is its item's: {<namespace>} in every language."""
    qualified = module("core.feature").qualified
    for translations in (load("translations/en.json"), load("translations/pt-BR.json")):
        for feature in features.values():
            for suffix, platform in per_item(feature).items():
                key = qualified(feature.namespace, suffix)
                name = translations["entity"][platform][key]["name"]
                assert f"{{{feature.namespace}}}" in name, key


def test_ready_made_alerts_line_up(features: dict[str, Any]) -> None:
    """Every ready-made alert is a key of the alerts aspect (not the builder's own), watches its builder's, has both texts, validates."""
    feature_module = module("core.feature")
    catalogue = module("setup.catalogue")
    aspect = module("aspects.alerts").ASPECT
    en, pt = load("translations/en.json"), load("translations/pt-BR.json")
    offering = [name for name, feature in features.items() if role(feature, "Presets")]
    assert offering, "no feature offers ready-made alerts"
    for name in offering:
        feature = features[name]
        presets = role(feature, "Presets").offered
        assert aspect in catalogue.aspects_of(feature), name
        ready_made = {f"alert_{alert}" for alert in presets}
        assert set(aspect_keys(aspect, name, feature)) == ready_made, name
        assert not ready_made & set(feature.entity_keys), name
        by = {entity_key: by for _, entity_key, _, by, _ in catalogue.keys({name: feature.example})}
        assert {key: by[key] for key in ready_made} == dict.fromkeys(ready_made, "alerts"), name
        settings = {}
        for alert, preset in presets.items():
            assert cv.slug(alert) == alert, name
            assert preset.watches in feature.entity_keys, f"{name}: {alert}"
            if isinstance(preset.kind, feature_module.Elapsed) and preset.kind.since_key:
                assert preset.kind.since_key in feature.entity_keys, f"{name}: {alert}"
            key = feature_module.qualified(feature.namespace, f"alert_{alert}")
            for translations in (en, pt):
                assert translations["common"][f"{key}_message"], key
                assert translations["common"][f"{key}_done_message"], key
            settings[alert] = {} if preset.hold is not None else {"for": {"hours": 1}}
        catalogue.mount(feature, name, {**feature.example, "alerts": settings})
        with pytest.raises(vol.Invalid):
            catalogue.mount(feature, name, {**feature.example, "alerts": {"not_an_alert": None}})


@pytest.mark.parametrize(("name", "kind"), [
    pytest.param("alerts", "Presets", id="ready-made alerts"),
    pytest.param("notifications", "Happenings", id="ready-made notifications"),
])
def test_ready_made_are_offered_only_with_one(features: dict[str, Any], name: str, kind: str) -> None:
    """A ready-made aspect is offered for at least one of them: alerts with presets_of (the rule alert_lights reads), notifications with happenings_of.

    An empty role offers nothing: no key to mount, no example to give.
    """
    cls = getattr(module("core.roles"), kind)
    aspect = module(f"aspects.{name}").ASPECT
    appliance = features["appliance"]
    assert aspect.offered(appliance)
    empty = dataclasses.replace(appliance, roles=tuple(
        cls({}) if isinstance(each, cls) else each for each in appliance.roles))
    assert role(empty, kind) is not None
    assert not aspect.offered(empty)
    assert aspect not in module("setup.catalogue").aspects_of(empty)


def schema_keys(schema: Any) -> dict[str, Any]:
    """A voluptuous schema's keys by name, with their markers (Optional, Required)."""
    return {str(key): key for key in schema.schema}


def test_every_alert_takes_the_shared_keys(features: dict[str, Any]) -> None:
    """Hand-written and ready-made alerts take problem.shared's keys, one schema: only the default priority differs."""
    problem, alerts = module("aspects.problem"), module("aspects.alerts")
    shared = schema_keys(vol.Schema(problem.shared("low")))
    assert set(shared) == {"priority", "notify", "lights"}
    hand_written = schema_keys(problem.ALERT.validators[0])
    assert set(shared) <= set(hand_written)
    assert hand_written["priority"].default() == "low"
    for name, feature in features.items():
        for alert, preset in (role(feature, "Presets").offered if role(feature, "Presets") else {}).items():
            ready_made = schema_keys(alerts._settings(preset))
            assert set(shared) <= set(ready_made), f"{name}: {alert}"
            assert set(ready_made) - set(shared) == {"for"}, f"{name}: {alert}"
            assert ready_made["priority"].default() == preset.priority, f"{name}: {alert}"


def test_alerts_is_a_device_key_not_a_feature(ha: HomeAssistant) -> None:
    """`alerts` builds entities as a device key, like programs: it never counts as a device's feature."""
    assert "alerts" in module("device_keys").DEVICE_KEYS
    assert "alerts" not in module("features").FEATURES


def test_ready_made_notifications_line_up(features: dict[str, Any]) -> None:
    """Every ready-made notification watches its own feature's entity key, has both texts, and mounts through its aspect.

    The notifications aspect adds no entity key: each enabled one is an automation.
    """
    feature_module = module("core.feature")
    catalogue = module("setup.catalogue")
    aspect = module("aspects.notifications").ASPECT
    en, pt = load("translations/en.json"), load("translations/pt-BR.json")
    offering = [name for name, feature in features.items() if role(feature, "Happenings")]
    assert offering, "no feature offers ready-made notifications"
    for name in offering:
        feature = features[name]
        happenings = role(feature, "Happenings").offered
        for notification, happening in happenings.items():
            assert cv.slug(notification) == notification, name
            assert happening.watches in feature.entity_keys, f"{name}: {notification}"
            key = feature_module.qualified(feature.namespace, f"notification_{notification}")
            for translations in (en, pt):
                assert translations["common"][f"{key}_name"], key
                assert translations["common"][f"{key}_message"], key
        assert aspect in catalogue.aspects_of(feature), name
        assert not aspect_keys(aspect, name, feature), name
        block = catalogue.mount(feature, name, {**feature.example, "notifications": dict.fromkeys(happenings)})
        assert block["notifications"] == {notification: {} for notification in happenings}
        with pytest.raises(vol.MultipleInvalid) as refused:
            catalogue.mount(feature, name, {**feature.example, "notifications": {"not_a_notification": None}})
        (error,) = refused.value.errors
        assert error.path == ["notifications", "not_a_notification"]
        assert f"is not a ready-made notification of {name}: " in error.msg


def test_each_role_at_most_once(features: dict[str, Any]) -> None:
    for name, feature in features.items():
        assert len({type(each) for each in feature.roles}) == len(feature.roles), name


def test_configured_and_items_never_together(features: dict[str, Any]) -> None:
    """A configured block's keys are its entity keys; an item block's keys are items: not both."""
    for name, feature in features.items():
        assert not (role(feature, "Configured") and role(feature, "Items")), name


def test_a_device_key_neither_acts_nor_derives(ha: HomeAssistant) -> None:
    for name, feature in module("device_keys").DEVICE_KEYS.items():
        for kind in ("Actions", "Derived"):
            assert role(feature, kind) is None, f"{name} has {kind}"


def test_ready_made_watch_the_builders_keys(features: dict[str, Any]) -> None:
    """What a ready-made alert or notification watches, or counts from, is one of its builder's keys."""
    elapsed = module("core.feature").Elapsed
    for name, feature in features.items():
        presets = role(feature, "Presets")
        for alert, preset in (presets.offered if presets else {}).items():
            assert preset.watches in feature.entity_keys, f"{name}: {alert}"
            if isinstance(preset.kind, elapsed) and preset.kind.since_key:
                assert preset.kind.since_key in feature.entity_keys, f"{name}: {alert}"
        happenings = role(feature, "Happenings")
        for notification, happening in (happenings.offered if happenings else {}).items():
            assert happening.watches in feature.entity_keys, f"{name}: {notification}"


def test_a_generating_builder_generates_from_its_example(features: dict[str, Any]) -> None:
    """What a builder writes to a generated kind carries the pururu pattern of its device."""
    generating = [name for name, feature in features.items() if role(feature, "Generates")]
    assert set(generating) == {"programs", "reactions"}
    for name in generating:
        feature = features[name]
        generated = list(role(feature, "Generates").ids("dev", feature.schema(dict(feature.example))))
        assert generated, name
        for domain, unique_id in generated:
            assert domain in ("script", "automation"), name
            assert unique_id.startswith("pururu_dev_"), name


def test_an_aspects_keys_are_named_once(features: dict[str, Any]) -> None:
    """Every key an aspect can add is named and has an icon: each place's own naming (Place.named), whatever it is.

    Generic over how an aspect names its keys (statistics' own, outside every
    namespace; or under the builder's own, as the ready-made alerts' are),
    by reading Place.named itself rather than a naming rule hard-coded here.
    Exhaustive over every place's keys, not just an example: a
    settings-gated counter's meters (idle_energy, a phase's energy) and every
    period (week, month, year) are checked too, not only what the builder's
    minimal example asks for. A place's names carry {item} all or none
    (other's none: it is named on its own), and none without an item.
    """
    en, pt, icons = load("translations/en.json"), load("translations/pt-BR.json"), load("icons.json")
    pairs = offered(features)
    assert pairs, "no builder offers an aspect"
    for aspect, name, feature in pairs:
        for place in aspect.places(feature, name):
            with_item: set[bool] = set()
            for key, platform in place.keys.items():
                translation = place.named(key)
                for translations in (en, pt):
                    text = translations["entity"][platform][translation]["name"]
                    assert text, (name, key)
                    with_item.add("{item}" in text)
                assert icons["entity"][platform][translation]["default"].startswith("mdi:"), (name, key)
            assert len(with_item) <= 1, (name, place.path)
            if place.item is None:
                assert True not in with_item, (name, place.path)


def test_an_offered_aspect_validates_and_builds(
    ha: HomeAssistant, features: dict[str, Any]
) -> None:
    """The builder's example with the aspect's goes through mount, and the aspect builds the keys it lists.

    The builder's example reaches every place: each has a container in it.
    """
    catalogue = module("setup.catalogue")
    feature_module = module("core.feature")
    device_cls = feature_module.Device
    for aspect, name, feature in offered(features):
        for place in aspect.places(feature, name):
            assert list(feature_module.walk(feature.example, place.path)), (name, place.path)
        raw = with_examples(aspect, name, feature, dict(feature.example))
        block = catalogue.mount(feature, name, raw)
        device = device_cls(key="dev", name="Dev", namespace=feature.namespace)
        # The common texts: a ready-made alert's default messages are read from them
        built = aspect.build(ha, device, feature, block, load("translations/en.json")["common"])
        # An aspect adding no entity key (ready-made notifications: automations) builds none
        assert bool(built) == bool(aspect_keys(aspect, name, feature)), name
        listed = {device.qualified(entity_key)
                  for _, entity_key, _, by, _ in catalogue.keys({name: block}) if by == aspect.key}
        assert {entity.key for entity in built} <= listed, name


def test_a_builders_own_schema_refuses_an_aspects_key(features: dict[str, Any]) -> None:
    """Only mount takes an aspect's key: the builder's schema refuses it at each of its places.

    The valid example is refused once a place's valid value is put at that
    place's containers, each place on its own.
    """
    for aspect, name, feature in offered(features):
        valid = dict(feature.example)
        feature.schema(valid)
        for place in aspect.places(feature, name):
            with pytest.raises(vol.Invalid):
                feature.schema(put(valid, place.path, aspect.key, place.example))


def test_mount_leaves_an_items_key_alone(features: dict[str, Any]) -> None:
    """In a block of items, a key alike an aspect's is an item: a program keyed `statistics` is a program, a switch keyed `notifications` a switch."""
    catalogue = module("setup.catalogue")
    for name, feature in features.items():
        each = module("core.feature").EACH
        in_items = any(place.path[:1] == (each,) for aspect in catalogue.aspects_of(feature)
                       for place in aspect.places(feature, name))
        if not (role(feature, "Configured") or in_items):
            continue
        item = next(iter(feature.example.values()))
        for aspect in module("aspects").ASPECTS:
            block = catalogue.mount(feature, name, {aspect.key: item})
            assert set(block) == {aspect.key}, name


@pytest.mark.parametrize(("house", "path"), [
    pytest.param(
        {"devices": {"washer": {"name": "Washer", "appliance": 5}}},
        ["devices", "washer", "appliance"],
        id="a block-placed aspect's block isn't a map"),
    pytest.param(
        {"devices": {"greenhouse": {"name": "Greenhouse", "switches": SWITCHES, "programs": 5}}},
        ["devices", "greenhouse", "programs"],
        id="an item-placed aspect's block isn't a map"),
    pytest.param(
        {"devices": {"greenhouse": {"name": "Greenhouse", "switches": SWITCHES, "programs": {"clean": 5}}}},
        ["devices", "greenhouse", "programs", "clean"],
        id="an item isn't a map"),
])
def test_mount_refuses_a_block_or_item_that_isnt_a_map(
    ha: HomeAssistant, house: dict[str, Any], path: list[str]
) -> None:
    """A block or item that isn't a map (_taken, _split) is refused cleanly: vol.Invalid, not KeyError/TypeError."""
    schema = module("setup.schema").CONFIG_SCHEMA
    with pytest.raises(vol.Invalid) as refused:
        schema({DOMAIN: house})
    paths = ([error.path for error in refused.value.errors]
              if isinstance(refused.value, vol.MultipleInvalid) else [refused.value.path])
    assert [DOMAIN, *path] in paths


def test_the_aspects_each_builder_offers(features: dict[str, Any]) -> None:
    """Statistics where a builder counts, ready-made alerts and notifications where it offers them: appliance all three."""
    aspects_of = module("setup.catalogue").aspects_of
    offering = {name: {aspect.key for aspect in aspects_of(feature)}
                for name, feature in features.items() if aspects_of(feature)}
    assert offering == {
        "appliance": {"statistics", "alerts", "notifications"},
        "door": {"statistics"},
        "window": {"statistics"},
        "programs": {"statistics"},
        "reactions": {"statistics"},
    }


def test_the_aspects_in_build_order(ha: HomeAssistant) -> None:
    """A builder's ready-made alerts, then its meters, then its ready-made notifications (no entity)."""
    assert [aspect.key for aspect in module("aspects").ASPECTS] == ["alerts", "statistics", "notifications"]


def test_an_absent_aspect_key(features: dict[str, Any]) -> None:
    """Absent, statistics is mounted as `{}` (no counter asks a period); ready-made alerts and notifications are left out (none enabled).

    One left out absent still refuses an explicit empty value, `{}` or null.
    A block that isn't a map is refused by the builder's schema alone: no
    aspect adds a refusal of its own for a key it can't find.
    """
    mount = module("setup.catalogue").mount
    left_out = {aspect.key for aspect in module("aspects").ASPECTS if not aspect.mount_absent}
    assert left_out == {"alerts", "notifications"}
    walk = module("core.feature").walk
    for aspect, name, feature in offered(features):
        block = mount(feature, name, dict(feature.example))
        containers = [container for place in aspect.places(feature, name)
                      for _, container in walk(block, place.path)]
        assert containers, (aspect.key, name)
        assert all((aspect.key in each) == aspect.mount_absent for each in containers), (aspect.key, name)
        if aspect.mount_absent:
            continue
        for empty in ({}, None):
            given = with_value(aspect, name, feature, dict(feature.example), empty)
            with pytest.raises(vol.MultipleInvalid) as refused:
                mount(feature, name, given)
            assert refused.value.errors, (aspect.key, name)
            assert all(error.path[-1] == aspect.key for error in refused.value.errors), (aspect.key, name)
    appliance = features["appliance"]
    block = mount(appliance, "appliance", dict(appliance.example))
    program = block["running_program"]
    assert block["statistics"] == {"idle_energy": []}
    assert program["statistics"] == {"runtime": [], "cycles": []}
    assert program["phases"]["warming"]["statistics"] == {"runtime": [], "cycles": [], "energy": []}
    assert program["other"]["statistics"] == {"runtime": [], "cycles": [], "energy": []}
    with pytest.raises(vol.MultipleInvalid) as refused:
        mount(appliance, "appliance", 5)
    assert [error.path for error in refused.value.errors] == [[]]


def test_mount_skips_a_place_without_a_check(features: dict[str, Any]) -> None:
    """A place offering no check (Place.check is None) still mounts: _checked skips it (continue)."""
    catalogue = module("setup.catalogue")
    feature_module = module("core.feature")
    feature = features["appliance"]
    place = feature_module.Place(schema=lambda value: value, keys={}, named=lambda key: key, example={})
    aspect = feature_module.Aspect(
        key="uninspected",
        offered=lambda builder: builder is feature,
        places=lambda builder, name: (place,),
        build=lambda hass, device, builder, block, texts: [],
    )
    with patch.object(catalogue, "ASPECTS", (aspect,)):
        block = catalogue.mount(feature, "appliance", {**feature.example, "uninspected": {"x": 1}})
    assert block["uninspected"] == {"x": 1}


def test_a_configured_builder_offers_no_block_aspect(features: dict[str, Any]) -> None:
    """A configured block's keys are its entity keys: one keyed as an aspect is an entity."""
    aspects_of = module("setup.catalogue").aspects_of
    for name, feature in features.items():
        if role(feature, "Configured") is not None:
            assert not aspects_of(feature), name


def test_a_counter_is_totalled(features: dict[str, Any]) -> None:
    """Each counter's total, <counter>_total, is one of the builder's own keys at each place: its meters meter it.

    The item's (a program's, a phase's, other's) at a container that is one,
    the builder's own elsewhere; the mounted example reaches every place.
    """
    catalogue = module("setup.catalogue")
    feature_module = module("core.feature")
    counting = [name for name, feature in features.items() if role(feature, "Counters")]
    assert set(counting) == {"appliance", "door", "window", "programs", "reactions"}
    for name in counting:
        feature = features[name]
        block = catalogue.mount(feature, name, dict(feature.example))
        own = {entity_key for _, entity_key, _, by, _ in catalogue.keys({name: block}) if by is None}
        for counted in role(feature, "Counters").places:
            containers = list(feature_module.walk(block, counted.at))
            assert containers, (name, counted.at)
            for path, container in containers:
                item = None if counted.item is None else counted.item(path[-1], container)
                for counter in counted.needs:
                    total = feature_module.item_key(f"{counter}_total", item)
                    assert total in own, f"{name}: {total}"


def test_a_counter_without_its_setting_is_refused(features: dict[str, Any]) -> None:
    """A counter needing a setting (energy) takes no period without it, at every place it counts; asking none passes.

    The setting is looked up in the builder's whole block: a phase's energy needs the appliance's.
    """
    mount = module("setup.catalogue").mount
    needing = [(name, feature, counted, counter, setting) for name, feature in features.items()
               if (counters := role(feature, "Counters")) is not None
               for counted in counters.places
               for counter, setting in counted.needs.items() if setting is not None]
    assert needing, "no counter needs a setting"
    assert {(name, counted.at) for name, _, counted, _, _ in needing} == {
        ("appliance", ()),
        ("appliance", ("running_program", "phases", "*")),
        ("appliance", ("running_program", "other")),
    }
    for name, feature, counted, counter, setting in needing:
        example = {key: value for key, value in feature.example.items() if key != setting}
        asked = put(example, counted.at, "statistics", {counter: ["today"]})
        with pytest.raises(vol.Invalid, match=re.escape(f"statistics.{counter} needs {setting}")):
            mount(feature, name, asked)
        mount(feature, name, put(example, counted.at, "statistics", {counter: []}))
