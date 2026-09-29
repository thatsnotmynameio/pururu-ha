"""The contract, over every Feature in FEATURES and DEVICE_KEYS: a new one is covered here unchanged."""

import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.setup import async_setup_component
import pytest
import voluptuous as vol

from helpers import module

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
    """Every key a feature's translations name: its entity keys and its per-item suffixes."""
    return {**feature.entity_keys, **per_item(feature)}


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
    """phases' `phase` would be sensor.pururu_<key>_phase_phase: its key is `current`."""
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
    for name in ("translations/en.json", "icons.json"):
        listed = {(platform, key) for platform, keys in load(name)["entity"].items() for key in keys}
        assert listed <= created, f"{name}: {sorted(listed - created)}"


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


def test_capabilities_line_up(features: dict[str, Any]) -> None:
    provided = {p.capability for feature in features.values() if (p := role(feature, "Provides"))}
    for name, feature in features.items():
        if (provides := role(feature, "Provides")) is not None:
            assert provides.key in feature.entity_keys, f"{name} provides {provides.capability} by unknown {provides.key}"
            assert role(feature, "Configured") is None, f"{name} is configured: its entity keys can't carry a capability"
        if (requires := role(feature, "Requires")) is not None:
            capability = requires.capability
            assert capability in provided, f"{name} requires {capability}, nobody provides it"
            assert f"{capability}_from" in feature.example, f"{name}'s example lacks {capability}_from"


def test_a_capability_is_carried_by_a_cycle_source(
    ha: HomeAssistant, features: dict[str, Any]
) -> None:
    """What a builder provides (appliance's running, door/window's open) sends its cycles as a CycleSource."""
    cycle_source = module("features.cycle").CycleSource
    device_cls = module("core.feature").Device
    for name, feature in features.items():
        if (provides := role(feature, "Provides")) is None:
            continue
        device = device_cls(key="dev", name="Dev", namespace=feature.namespace)
        config = feature.schema(dict(feature.example))
        built = {entity.key: entity for entity in feature.build(ha, device, config, {})}
        carrier = built[device.qualified(provides.key)]
        assert isinstance(carrier, cycle_source), name


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
    """Every ready-made alert is an entity key, watches its own feature's, has both texts, validates."""
    feature_module = module("core.feature")
    en, pt = load("translations/en.json"), load("translations/pt-BR.json")
    offering = [name for name, feature in features.items() if role(feature, "Presets")]
    assert offering, "no feature offers ready-made alerts"
    for name in offering:
        feature = features[name]
        presets = role(feature, "Presets").offered
        assert feature_module.preset_keys(presets).items() <= feature.entity_keys.items(), name
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
        validate = module("features.presets").validate
        validate(feature, {**feature.example, "alerts": settings})
        with pytest.raises(vol.Invalid):
            validate(feature, {**feature.example, "alerts": {"not_an_alert": None}})


def test_ready_made_notifications_line_up(features: dict[str, Any]) -> None:
    """Every ready-made notification watches its own feature's entity key and has both texts."""
    feature_module = module("core.feature")
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
        validate = module("device_keys.notifications").schema(name, happenings)
        assert validate(dict.fromkeys(happenings)) == {notification: {} for notification in happenings}
        with pytest.raises(vol.Invalid):
            validate({"not_a_notification": None})


def test_each_role_at_most_once(features: dict[str, Any]) -> None:
    for name, feature in features.items():
        assert len({type(each) for each in feature.roles}) == len(feature.roles), name


def test_configured_and_items_never_together(features: dict[str, Any]) -> None:
    """A configured block's keys are its entity keys; an item block's keys are items: not both."""
    for name, feature in features.items():
        assert not (role(feature, "Configured") and role(feature, "Items")), name


def test_a_device_key_neither_provides_requires_nor_acts(ha: HomeAssistant) -> None:
    for name, feature in module("device_keys").DEVICE_KEYS.items():
        for kind in ("Provides", "Requires", "Actions"):
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
