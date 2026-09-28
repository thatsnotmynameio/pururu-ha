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


def named_keys(feature: Any) -> dict[str, Any]:
    """Every key a feature's translations name: its entity keys and its per-item suffixes."""
    return {**feature.entity_keys, **feature.per_item}


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
        if feature.refers is not None:
            for key in feature.refers(feature.schema(dict(feature.example))):
                assert cv.slug(key) == key, name


def test_every_entity_key_is_named_and_has_an_icon(features: dict[str, Any]) -> None:
    qualified = module("feature").qualified
    en, pt, icons = load("translations/en.json"), load("translations/pt-BR.json"), load("icons.json")
    for feature in features.values():
        for entity_key, platform in named_keys(feature).items():
            key = qualified(feature.namespace, entity_key)
            for translations in (en, pt):
                assert translations["entity"][platform][key]["name"], key
            assert icons["entity"][platform][key]["default"].startswith("mdi:"), key


def test_every_translated_entity_key_is_created(features: dict[str, Any]) -> None:
    """A name or an icon under a key no feature creates is left over, as from before namespaces."""
    qualified = module("feature").qualified
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
        if feature.configured is not None:
            assert feature.configured in platforms, (
                f"{name}'s configured entities are on {feature.configured}, not in PLATFORMS")


def test_capabilities_line_up(features: dict[str, Any]) -> None:
    provided = {capability for feature in features.values() for capability in feature.provides}
    for name, feature in features.items():
        for capability, entity_key in feature.provides.items():
            assert entity_key in feature.entity_keys, f"{name} provides {capability} by unknown {entity_key}"
        if feature.configured is not None:
            assert not feature.provides, f"{name} is configured: its entity keys can't carry a capability"
        for capability in feature.requires:
            assert capability in provided, f"{name} requires {capability}, nobody provides it"
            assert f"{capability}_from" in feature.example, f"{name}'s example lacks {capability}_from"


async def test_every_action_is_a_service_of_its_platform(ha: HomeAssistant, features: dict[str, Any]) -> None:
    """A program's step calls <platform>.<action> on the entity: the platform must have that service."""
    for name, feature in features.items():
        if not feature.actions:
            continue
        assert feature.configured is not None, f"{name} takes actions: its entities must be on one platform"
        assert await async_setup_component(ha, feature.configured, {})
        for action in feature.actions:
            assert ha.services.has_service(feature.configured, action), f"{name}: {feature.configured}.{action}"


@pytest.mark.parametrize("name", ["switches", "lights"])
def test_it_takes_turn_on_turn_off_and_toggle(features: dict[str, Any], name: str) -> None:
    assert features[name].actions == ("turn_on", "turn_off", "toggle")


def test_per_item_goes_with_items(features: dict[str, Any]) -> None:
    """Suffixes need items to repeat for, and items need suffixes."""
    for name, feature in features.items():
        assert (feature.items is None) == (not feature.per_item), name
        if feature.items is not None:
            for item in feature.items(feature.schema(dict(feature.example))):
                assert cv.slug(item.slug) == item.slug, name


def test_every_per_item_name_has_its_placeholder(features: dict[str, Any]) -> None:
    """A per-item entity's name is its item's: {<namespace>} in every language."""
    qualified = module("feature").qualified
    for translations in (load("translations/en.json"), load("translations/pt-BR.json")):
        for feature in features.values():
            for suffix, platform in feature.per_item.items():
                key = qualified(feature.namespace, suffix)
                name = translations["entity"][platform][key]["name"]
                assert f"{{{feature.namespace}}}" in name, key


def test_ready_made_alerts_line_up(features: dict[str, Any]) -> None:
    """Every ready-made alert is an entity key, watches its own feature's, has both texts, validates."""
    feature_module = module("feature")
    en, pt = load("translations/en.json"), load("translations/pt-BR.json")
    offering = [name for name, feature in features.items() if feature.alerts]
    assert offering, "no feature offers ready-made alerts"
    for name in offering:
        feature = features[name]
        assert feature_module.preset_keys(feature.alerts).items() <= feature.entity_keys.items(), name
        settings = {}
        for alert, preset in feature.alerts.items():
            assert cv.slug(alert) == alert, name
            assert preset.watches in feature.entity_keys, f"{name}: {alert}"
            if isinstance(preset.kind, feature_module.Elapsed) and preset.kind.since_key:
                assert preset.kind.since_key in feature.entity_keys, f"{name}: {alert}"
            key = feature_module.qualified(feature.namespace, f"alert_{alert}")
            for translations in (en, pt):
                assert translations["common"][f"{key}_message"], key
                assert translations["common"][f"{key}_done_message"], key
            settings[alert] = {} if preset.hold is not None or preset.lasts else {"for": {"hours": 1}}
        validate = module("features.presets").validate
        validate(feature, {**feature.example, "alerts": settings})
        with pytest.raises(vol.Invalid):
            validate(feature, {**feature.example, "alerts": {"not_an_alert": None}})
