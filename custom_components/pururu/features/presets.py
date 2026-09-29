"""Ready-made alerts: the settings that enable them, and the alerts they build.

A feature offers them (roles.Presets); its block's `alerts` enables each one
with one key, its defaults and texts ready.
"""

from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from ..core.entity import PururuEntity
from ..core.feature import (
    ALERTS_KEY,
    PRIORITIES,
    Device,
    Feature,
    Preset,
    happenings_of,
    presets_of,
)
from ..core.texts import Texts
from ..core.vocabulary import Condition
from .alerts import NOTIFY, Alert, lights_group
from .elapsed import ElapsedAlert


def _settings(preset: Preset) -> vol.Schema:
    """What one alert takes: for, priority, notify, lights."""
    timing: dict[Any, Any] = (
        {vol.Required("for"): cv.positive_time_period}
        if preset.hold is None
        else {vol.Optional("for", default=preset.hold): cv.positive_time_period}
    )
    return vol.Schema(
        {
            **timing,
            vol.Optional("priority", default=preset.priority): vol.In(PRIORITIES),
            vol.Optional("notify"): NOTIFY,
            vol.Optional("lights"): lights_group,
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


def validate(feature: Feature, value: Any, key: str = "") -> Any:
    """A feature's block: its schema, and `alerts` when it offers ready-made alerts.

    `key` is the feature's in the device: a ready-made alert that became a
    notification says where it went.
    """
    presets = presets_of(feature)
    if not presets or not isinstance(value, dict) or ALERTS_KEY not in value:
        return feature.schema(value)
    if isinstance(given := value[ALERTS_KEY], dict):
        for name in given:
            if name in happenings_of(feature) and name not in presets:
                raise vol.Invalid(
                    f"{name} is now a notification: "
                    f"{key or feature.namespace}: notifications: {name}",
                    path=[ALERTS_KEY, name],
                )
    block = {each: setting for each, setting in value.items() if each != ALERTS_KEY}
    enabled = vol.Schema({ALERTS_KEY: settings_schema(presets)})(
        {ALERTS_KEY: value[ALERTS_KEY]}
    )
    return {**feature.schema(block), **enabled}


def _notify(
    device: Device, entity_key: str, settings: Mapping[str, Any], texts: Texts
) -> dict[str, str]:
    """The user's notify, or the default texts of this alert."""
    if "notify" in settings:
        return dict(settings["notify"])
    key = device.qualified(entity_key)
    return {
        "message": texts[f"{key}_message"],
        "done_message": texts[f"{key}_done_message"],
    }


def build(
    hass: HomeAssistant,
    device: Device,
    feature: Feature,
    block: Mapping[str, Any],
    texts: Texts,
) -> list[PururuEntity]:
    """The block's enabled ready-made alerts, in the feature's namespace."""
    entities: list[PururuEntity] = []
    for name, settings in block.get(ALERTS_KEY, {}).items():
        preset = presets_of(feature)[name]
        entity_key = f"alert_{name}"
        watched = device.current_entity_id(
            hass, feature.entity_keys[preset.watches], preset.watches
        )
        notify = _notify(device, entity_key, settings, texts)
        if isinstance(preset.kind, Condition):
            entities.append(
                Alert(
                    device,
                    entity_key,
                    name=None,
                    watched=watched,
                    condition=preset.kind,
                    hold=settings["for"],
                    priority=settings["priority"],
                    notify=notify,
                    sources=(preset.watches,),
                    asks_alert2="notify" in settings,
                    lights=settings.get("lights"),
                )
            )
            continue
        kind = preset.kind
        milestone = (
            None
            if kind.since_key is None
            else device.current_entity_id(
                hass, feature.entity_keys[kind.since_key], kind.since_key
            )
        )
        entities.append(
            ElapsedAlert(
                device,
                entity_key,
                watched=watched,
                milestone=milestone,
                elapsed=kind,
                hold=settings.get("for", preset.hold or timedelta(0)),
                priority=settings["priority"],
                notify=notify,
                sources=(
                    preset.watches,
                    *((kind.since_key,) if kind.since_key else ()),
                ),
                asks_alert2="notify" in settings,
                lights=settings.get("lights"),
            )
        )
    return entities
