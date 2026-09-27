"""The contract, over every feature in FEATURES: a new feature is covered here unchanged."""

import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
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


@pytest.fixture
def features(ha: HomeAssistant) -> dict[str, Any]:
    return module("features").FEATURES


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
        assert feature.namespace not in feature.entity_keys, name


def test_every_entity_key_is_named_and_has_an_icon(features: dict[str, Any]) -> None:
    qualified = module("feature").qualified
    en, pt, icons = load("translations/en.json"), load("translations/pt-BR.json"), load("icons.json")
    for feature in features.values():
        for entity_key, platform in feature.entity_keys.items():
            key = qualified(feature.namespace, entity_key)
            for translations in (en, pt):
                assert translations["entity"][platform][key]["name"], key
            assert icons["entity"][platform][key]["default"].startswith("mdi:"), key


def test_every_translated_entity_key_is_created(features: dict[str, Any]) -> None:
    """A name or an icon under a key no feature creates is left over, as from before namespaces."""
    qualified = module("feature").qualified
    created = {(str(platform), qualified(feature.namespace, entity_key))
               for feature in features.values()
               for entity_key, platform in feature.entity_keys.items()}
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
        for entity_key, platform in feature.entity_keys.items():
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
