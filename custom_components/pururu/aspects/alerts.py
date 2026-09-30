"""`alerts`: the device key for hand-written alerts, and the ready-made alerts' aspect.

The device key `ALERTS` builds one alert per key of a device's `alerts:`
block, watching the entity its `when` names. A feature offers ready-made
alerts (roles.Presets); `ASPECT` mounts its block's `alerts`, which enables
each one with one key, its defaults and texts ready. Both build on
aspects.problem's ProblemAlert.
"""

from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any, Literal

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from ..core.entity import PururuEntity
from ..core.feature import (
    ALERTS_KEY,
    PRIORITIES,
    Aspect,
    Device,
    Feature,
    Preset,
    presets_of,
    qualified,
)
from ..core.resolve import Ref
from ..core.roles import Configured, Presets, Refers
from ..core.texts import Texts
from ..core.vocabulary import Condition
from .elapsed import ElapsedAlert
from .problem import NOTIFY, SCHEMA, Alert, lights_group


def _build(
    hass: HomeAssistant,
    device: Device,
    config: dict[str, Any],
    inputs: Mapping[str, str],
) -> list[PururuEntity]:
    """An alert per key of the block, watching the entity its `when` names."""
    return [
        Alert(
            device,
            entity_key,
            name=alert["name"],
            watched=inputs[alert["when"]],
            condition=Condition(
                state=alert.get("is"),
                above=alert.get("above"),
                below=alert.get("below"),
            ),
            hold=alert["for"],
            priority=alert["priority"],
            notify=alert.get("notify"),
            lights=alert.get("lights"),
            follows=(alert["when"],),
        )
        for entity_key, alert in config.items()
    ]


def _refers(config: dict[str, Any]) -> set[Ref]:
    """The entity keys the alerts watch, on this device."""
    return {Ref(None, alert["when"]) for alert in config.values()}


ALERTS = Feature(
    schema=SCHEMA,
    entity_keys={},
    build=_build,
    example={"too_long": {"name": "Too long", "when": "appliance_running", "is": "on"}},
    namespace="alert",
    roles=(Configured(Platform.BINARY_SENSOR), Refers(_refers)),
)


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


def _presets(builder: Feature) -> Mapping[str, Preset]:
    """The builder's ready-made alerts: it offers the aspect only with them."""
    presets = presets_of(builder)
    assert presets  # ASPECT.offered checked it
    return presets


def _schema(builder: Feature, _name: str) -> Callable[[Any], dict[str, dict[str, Any]]]:
    """The block's `alerts`, for this builder's ready-made alerts.

    Its refusals name the alert, not the builder's key in the device (`_name`).
    """
    return settings_schema(_presets(builder))


def _keys(builder: Feature) -> dict[str, Platform]:
    """Every ready-made alert it can enable: alert_<name>, a binary sensor."""
    return {f"alert_{name}": Platform.BINARY_SENSOR for name in _presets(builder)}


def _named(builder: Feature, key: str) -> str:
    """The translation key `key` (`alert_<name>`) is named under: in the builder's namespace."""
    return qualified(builder.namespace, key)


def _example(builder: Feature) -> dict[str, dict[str, Any] | None]:
    """The first ready-made alert, with a `for` when it has no default one."""
    name, preset = next(iter(_presets(builder).items()))
    return {name: None if preset.hold is not None else {"for": {"hours": 1}}}


def _placed(_builder: Feature) -> Literal["block"]:
    """`alerts:` sits in the block, for every builder offering it."""
    return "block"


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


def _build_ready_made(
    hass: HomeAssistant,
    device: Device,
    feature: Feature,
    block: Mapping[str, Any],
    texts: Texts,
) -> list[PururuEntity]:
    """The block's enabled ready-made alerts, in the feature's namespace; none without `alerts`."""
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


ASPECT = Aspect(
    key=ALERTS_KEY,
    offered=lambda builder: builder.role(Presets) is not None,
    schema=_schema,
    keys=_keys,
    named=_named,
    example=_example,
    placed=_placed,
    build=_build_ready_made,
    # Absent: no alert enabled; an explicit empty `alerts` is still refused
    mount_absent=False,
)
