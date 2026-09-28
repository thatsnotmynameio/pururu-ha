"""Ready-made alerts: the settings that enable them, and the alerts they build.

A feature offers them (Feature.alerts); its block's `alerts` enables each one
with one key, its defaults and texts ready.
"""

from collections.abc import Callable, Mapping
from typing import Any

import voluptuous as vol

from homeassistant.helpers import config_validation as cv

from ..feature import ALERTS_KEY, Feature, Preset
from .alerts import NOTIFY, PRIORITIES


def _settings(preset: Preset) -> vol.Schema:
    """What one alert takes: for (or lasts), priority, notify."""
    timing: dict[Any, Any]
    if preset.lasts is not None:
        timing = {vol.Optional("lasts", default=preset.lasts): cv.positive_time_period}
    elif preset.hold is None:
        timing = {vol.Required("for"): cv.positive_time_period}
    else:
        timing = {vol.Optional("for", default=preset.hold): cv.positive_time_period}
    return vol.Schema(
        {
            **timing,
            vol.Optional("priority", default=preset.priority): vol.In(PRIORITIES),
            vol.Optional("notify"): NOTIFY,
        }
    )


def settings_schema(
    presets: Mapping[str, Preset],
) -> Callable[[Any], dict[str, dict[str, Any]]]:
    """The block's `alerts`: ready-made alert -> its settings; null is every default."""
    known = ", ".join(presets)
    each = {name: _settings(preset) for name, preset in presets.items()}

    def validate(value: Any) -> dict[str, dict[str, Any]]:
        alerts = vol.All(vol.Schema({cv.slug: vol.Any(None, dict)}), vol.Length(min=1))(
            value
        )
        enabled: dict[str, dict[str, Any]] = {}
        for name, settings in alerts.items():
            if name not in each:
                raise vol.Invalid(
                    f"{name} is not a ready-made alert: {known}", path=[name]
                )
            enabled[name] = vol.Schema({name: each[name]})({name: settings or {}})[name]
        return enabled

    return validate


def validate(feature: Feature, value: Any) -> Any:
    """A feature's block: its schema, and `alerts` when it offers ready-made alerts."""
    if not feature.alerts or not isinstance(value, dict) or ALERTS_KEY not in value:
        return feature.schema(value)
    block = {key: each for key, each in value.items() if key != ALERTS_KEY}
    enabled = vol.Schema({ALERTS_KEY: settings_schema(feature.alerts)})(
        {ALERTS_KEY: value[ALERTS_KEY]}
    )
    return {**feature.schema(block), **enabled}
