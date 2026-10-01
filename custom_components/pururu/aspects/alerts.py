"""`alerts`: the device key for hand-written alerts, and the ready-made alerts' aspect.

The device key `ALERTS` builds one alert per key of a device's `alerts:`
block, watching the entity its `when` names. A feature offers ready-made
alerts (roles.Presets); `ASPECT` mounts its block's `alerts`, which enables
each one with one key, its defaults and texts ready. Both build on
aspects.problem's ProblemAlert.
"""

from collections.abc import Callable, Iterator, Mapping
from datetime import timedelta
from functools import partial
from typing import Any

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from ..const import CONF_ALERTS, CONF_DEVICES
from ..core import vocabulary
from ..core.entity import PururuEntity
from ..core.feature import (
    ALERTS_KEY,
    Aspect,
    Device,
    Feature,
    Place,
    Preset,
    presets_of,
    qualified,
)
from ..core.resolve import Index, Owner, Ref, find
from ..core.roles import Configured, Refers
from ..core.texts import Texts
from .elapsed import ElapsedAlert
from .problem import SCHEMA, TEXTS, Alert, shared, texts_together


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
            condition=vocabulary.parse(alert),
            hold=alert.get("for"),
            priority=alert["priority"],
            messages=_texts(alert),
            lights=alert.get("lights"),
            # A path of this device (checks.references)
            follows=(alert["when"],),
        )
        for entity_key, alert in config.items()
    ]


def _refers(config: dict[str, Any]) -> list[tuple[tuple[str, ...], Ref]]:
    """What each alert watches, at its when: a path of this device."""
    return [
        ((alert_key, "when"), Ref.parse(alert["when"]))
        for alert_key, alert in config.items()
    ]


def check(house: Mapping[str, Any], index: Index, *_: Any) -> Iterator[vol.Invalid]:
    """Refuse an alert watching a ready-made alert (a schema check): an alert can't watch another.

    What isn't another block's entity of this device is checks.references'
    refusal, so each reference is refused once.
    """
    for key, device in house[CONF_DEVICES].items():
        for where, ref in _refers(device.get(CONF_ALERTS, {})):
            target = find(index, key, ref) if ref.owner is Owner.HERE else None
            if (
                target is not None
                and target.builder != CONF_ALERTS
                and target.by == ASPECT.key
            ):
                yield vol.Invalid(
                    f"{CONF_ALERTS}: {ref.text} is an alert: an alert can't watch another",
                    path=[CONF_DEVICES, key, CONF_ALERTS, *where],
                )


ALERTS = Feature(
    schema=SCHEMA,
    entity_keys={},
    build=_build,
    example={
        "too_long": {
            "name": "Too long",
            "when": "appliance.running_program",
            "state": "on",
        }
    },
    namespace="alert",
    roles=(Configured(Platform.BINARY_SENSOR), Refers(_refers)),
)


def _texts(alert: Mapping[str, Any]) -> dict[str, str] | None:
    """An alert's message and done_message; None without (texts_together: both or neither)."""
    return {text: alert[text] for text in TEXTS} if TEXTS[0] in alert else None


def _settings(preset: Preset) -> Callable[[Any], Any]:
    """What one alert takes: its for, then what every alert takes (problem.shared)."""
    timing: dict[Any, Any] = (
        {vol.Required("for"): cv.positive_time_period}
        if preset.hold is None
        else {vol.Optional("for", default=preset.hold): cv.positive_time_period}
    )
    return vol.All(vol.Schema({**timing, **shared(preset.priority)}), texts_together)


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
    """The builder's ready-made alerts: it offers the aspect only with at least one."""
    presets = presets_of(builder)
    assert presets  # ASPECT.offered checked there is at least one
    return presets


def _example(presets: Mapping[str, Preset]) -> dict[str, dict[str, Any] | None]:
    """The first ready-made alert, with a `for` when it has no default one."""
    name, preset = next(iter(presets.items()))
    return {name: None if preset.hold is not None else {"for": {"hours": 1}}}


def _places(builder: Feature, _name: str) -> tuple[Place, ...]:
    """`alerts:` sits in the block, for every builder offering it: alert_<name> per ready-made alert.

    Each is named in the builder's namespace. Its refusals name the alert, not
    the builder's key in the device (`_name`).
    """
    presets = _presets(builder)
    return (
        Place(
            schema=settings_schema(presets),
            keys={f"alert_{name}": Platform.BINARY_SENSOR for name in presets},
            # Each where it is enabled: alerts.<name>
            leaves={f"alert_{name}": (name,) for name in presets},
            named=partial(qualified, builder.namespace),
            example=_example(presets),
        ),
    )


def _messages(
    device: Device, entity_key: str, settings: Mapping[str, Any], texts: Texts
) -> dict[str, str]:
    """The user's message and done_message, or this alert's default texts."""
    if (own := _texts(settings)) is not None:
        return own
    key = device.qualified(entity_key)
    return {text: texts[f"{key}_{text}"] for text in TEXTS}


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
        messages = _messages(device, entity_key, settings, texts)
        if isinstance(preset.kind, vocabulary.Condition):
            entities.append(
                Alert(
                    device,
                    entity_key,
                    name=None,
                    watched=watched,
                    condition=preset.kind,
                    hold=settings["for"],
                    priority=settings["priority"],
                    messages=messages,
                    sources=(preset.watches,),
                    asks_alert2=TEXTS[0] in settings,
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
                messages=messages,
                sources=(
                    preset.watches,
                    *((kind.since_key,) if kind.since_key else ()),
                ),
                asks_alert2=TEXTS[0] in settings,
                lights=settings.get("lights"),
            )
        )
    return entities


ASPECT = Aspect(
    key=ALERTS_KEY,
    # The rule alert_lights reads too: at least one ready-made alert (presets_of)
    offered=lambda builder: bool(presets_of(builder)),
    places=_places,
    build=_build_ready_made,
    # Absent: no alert enabled; an explicit empty `alerts` is still refused
    mount_absent=False,
)
