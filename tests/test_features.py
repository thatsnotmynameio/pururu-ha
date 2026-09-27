"""The contract, over every feature in FEATURES: a new feature is covered here unchanged."""

import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
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


def test_no_entity_key_in_two_features(features: dict[str, Any]) -> None:
    seen: dict[str, str] = {}
    for name, feature in features.items():
        for entity_key in feature.entity_keys:
            assert entity_key not in seen, f"{entity_key} in {seen.get(entity_key)} and {name}"
            seen[entity_key] = name


def test_every_entity_key_is_named_and_has_an_icon(features: dict[str, Any]) -> None:
    en, pt, icons = load("translations/en.json"), load("translations/pt-BR.json"), load("icons.json")
    for feature in features.values():
        for entity_key, platform in feature.entity_keys.items():
            for translations in (en, pt):
                assert translations["entity"][platform][entity_key]["name"], entity_key
            assert icons["entity"][platform][entity_key]["default"].startswith("mdi:"), entity_key


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
