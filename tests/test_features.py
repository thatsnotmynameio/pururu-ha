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


def test_no_metric_in_two_features(features: dict[str, Any]) -> None:
    seen: dict[str, str] = {}
    for name, feature in features.items():
        for metric in feature.metrics:
            assert metric not in seen, f"{metric} in {seen.get(metric)} and {name}"
            seen[metric] = name


def test_every_metric_is_named_and_has_an_icon(features: dict[str, Any]) -> None:
    en, pt, icons = load("translations/en.json"), load("translations/pt-BR.json"), load("icons.json")
    for feature in features.values():
        for metric, platform in feature.metrics.items():
            for translations in (en, pt):
                assert translations["entity"][platform][metric]["name"], metric
            assert icons["entity"][platform][metric]["default"].startswith("mdi:"), metric


def test_example_is_valid_and_unknown_keys_are_refused(features: dict[str, Any]) -> None:
    for feature in features.values():
        feature.schema(dict(feature.example))
        with pytest.raises(vol.Invalid):
            feature.schema({**feature.example, "not_a_key": 1})


def test_every_platform_is_set_up(features: dict[str, Any]) -> None:
    platforms = module("const").PLATFORMS
    for name, feature in features.items():
        for metric, platform in feature.metrics.items():
            assert platform in platforms, f"{name}'s {metric} is on {platform}, not in PLATFORMS"


def test_capabilities_line_up(features: dict[str, Any]) -> None:
    provided = {capability for feature in features.values() for capability in feature.provides}
    for name, feature in features.items():
        for capability, metric in feature.provides.items():
            assert metric in feature.metrics, f"{name} provides {capability} by unknown {metric}"
        for capability in feature.requires:
            assert capability in provided, f"{name} requires {capability}, nobody provides it"
            assert f"{capability}_from" in feature.example, f"{name}'s example lacks {capability}_from"
