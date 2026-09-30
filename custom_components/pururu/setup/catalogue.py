"""Every builder of a device, the aspects mounted in its blocks, and the entity keys they can create."""

from collections.abc import Hashable, Iterator, Mapping
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_NAME, Platform

from ..aspects import ASPECTS
from ..aspects.statistics import KEY as STATISTICS
from ..const import CONF_NOTIFICATIONS
from ..core.feature import (
    ALERTS_KEY,
    Aspect,
    Device,
    Feature,
    happenings_of,
    preset_keys,
    presets_of,
)
from ..core.resolve import Index, Target
from ..core.roles import Actions, Configured, Counters, Items
from ..device_keys import DEVICE_KEYS, notifications
from ..features import FEATURES, presets


def builders() -> dict[str, Feature]:
    """Everything that builds entities of a device: its features, then the device keys.

    Read at every call, so a feature added to FEATURES is seen. Only FEATURES
    count as a device's features.
    """
    return {**FEATURES, **DEVICE_KEYS}


def aspects_of(builder: Feature) -> tuple[Aspect, ...]:
    """The aspects the builder offers: only their keys are taken out of its block."""
    return tuple(aspect for aspect in ASPECTS if aspect.offered(builder))


def _in_items(builder: Feature) -> bool:
    """Whether its aspects sit in each item of its block (Counters(mount="item")), not in the block."""
    counters = builder.role(Counters)
    return counters is not None and counters.mount == "item"


def _taken(value: Any, aspects: tuple[Aspect, ...]) -> tuple[Any, dict[str, Any]]:
    """`value` without the aspects' keys, and their values; anything but a map is left whole."""
    if not isinstance(value, dict):
        return value, {}
    keys = {aspect.key for aspect in aspects}
    return (
        {key: each for key, each in value.items() if key not in keys},
        {key: each for key, each in value.items() if key in keys},
    )


# Where an aspect's value sat: () the block, (key,) the block's item `key`
type Place = tuple[str, ...]


def _split(
    builder: Feature, aspects: tuple[Aspect, ...], value: Any
) -> tuple[Any, dict[Place, dict[str, Any]]]:
    """The block without the aspects' keys, and their values by where they sat."""
    if not (_in_items(builder) and isinstance(value, dict)):
        rest, taken = _taken(value, aspects)
        return rest, {(): taken}
    split = {key: _taken(item, aspects) for key, item in value.items()}
    return (
        {key: kept for key, (kept, _) in split.items()},
        {(key,): taken for key, (_, taken) in split.items()},
    )


def _validated(builder: Feature, name: str, value: Any) -> Any:
    """What is left of the block: a feature's (_feature_block), or the device key's schema."""
    if name in FEATURES:
        return _feature_block(builder, name, value)
    return builder.schema(value)


def mount(builder: Feature, name: str, value: Any) -> Any:
    """Builder `name`'s block, validated, each offered aspect's value in it where it was.

    An aspect's key is taken out of the block, or out of each item
    (Counters(mount="item")), and validated by the aspect: absent, as `{}`, its
    defaults. The rest goes to _validated. A counter asking for periods without
    the setting it needs is refused after. Every refusal is told at once.
    """
    if not (aspects := aspects_of(builder)):
        return _validated(builder, name, value)
    rest, places = _split(builder, aspects, value)
    errors: list[vol.Invalid] = []
    block: Any = None
    try:
        block = _validated(builder, name, rest)
    except vol.Invalid as error:
        errors.append(error)
    mounted: dict[Place, dict[str, Any]] = {path: {} for path in places}
    for path, taken in places.items():
        for aspect in aspects:
            try:
                mounted[path][aspect.key] = aspect.schema(builder)(
                    taken.get(aspect.key, {})
                )
            except vol.Invalid as error:
                error.prepend([*path, aspect.key])
                errors.append(error)
    if errors:
        raise vol.MultipleInvalid(_flat(errors))
    for path, values in mounted.items():
        block = _placed(block, path, values)
        _needs_met(builder, block[path[0]] if path else block, list(path))
    return block


def _placed(block: dict[str, Any], path: Place, values: dict[str, Any]) -> Any:
    """`block` with `values` back where they sat."""
    if not path:
        return {**block, **values}
    (key,) = path
    return {**block, key: {**block[key], **values}}


def _flat(errors: list[vol.Invalid]) -> list[vol.Invalid]:
    """Each refusal on its own: a schema's MultipleInvalid opened."""
    return [
        each
        for error in errors
        for each in (
            error.errors if isinstance(error, vol.MultipleInvalid) else [error]
        )
    ]


def _needs_met(
    builder: Feature, block: Mapping[str, Any], path: list[Hashable]
) -> None:
    """Refuse a counter with periods whose setting (Counters.needs) isn't in its validated block."""
    if (counters := builder.role(Counters)) is None:
        return
    for counter, setting in counters.needs.items():
        if setting is not None and block[STATISTICS][counter] and setting not in block:
            raise vol.Invalid(f"{STATISTICS}.{counter} needs {setting}", path=path)


def _feature_block(feature: Feature, key: str, value: Any) -> Any:
    """A feature's block, `key` in the device: its ready-made notifications (notifications.py), the rest as presets.validate says.

    Only a feature offering them has them: a configured feature (alerts,
    switches) may have an item keyed `notifications`.
    """
    if (
        not (happenings := happenings_of(feature))
        or not isinstance(value, dict)
        or CONF_NOTIFICATIONS not in value
    ):
        return presets.validate(feature, value, key)
    rest = {each: block for each, block in value.items() if each != CONF_NOTIFICATIONS}
    enabled = vol.Schema({CONF_NOTIFICATIONS: notifications.schema(key, happenings)})(
        {CONF_NOTIFICATIONS: value[CONF_NOTIFICATIONS]}
    )
    return {**presets.validate(feature, rest, key), **enabled}


def keys(
    device: dict[str, Any],
) -> Iterator[tuple[str, str, Platform, str | None, str | None]]:
    """(builder, local entity key, platform, by, item) of every entity the device's builders can create.

    `by` is "alerts" for a ready-made alert's key, an aspect's key for the
    entity keys it adds; `item` the item owning an Items key.
    """
    for name, feature in builders().items():
        if name not in device:
            continue
        ready_made = preset_keys(presets_of(feature))
        yield from (
            (
                name,
                entity_key,
                platform,
                ALERTS_KEY if entity_key in ready_made else None,
                None,
            )
            for entity_key, platform in feature.entity_keys.items()
        )
        if (configured := feature.role(Configured)) is not None:
            yield from (
                (name, entity_key, configured.platform, None, None)
                for entity_key in device[name]
            )
        items = feature.role(Items)
        if items is not None:
            yield from (
                (name, item.key(suffix), platform, None, item.slug)
                for item in items.of(device[name])
                for suffix, platform in items.keys.items()
            )
        for aspect in aspects_of(feature):
            added = aspect.keys(feature)
            if items is None:
                yield from (
                    (name, entity_key, platform, aspect.key, None)
                    for entity_key, platform in added.items()
                )
                continue
            yield from (
                (name, item.key(suffix), platform, aspect.key, item.slug)
                for item in items.of(device[name])
                for suffix, platform in added.items()
            )


def targets(key: str, config: dict[str, Any]) -> dict[str, Target]:
    """Every entity key device `key` can create, qualified, and what it is."""
    found: dict[str, Target] = {}
    for name, entity_key, platform, by, item in keys(config):
        feature = builders()[name]
        device = Device(key=key, name=config[CONF_NAME], namespace=feature.namespace)
        actions = feature.role(Actions)
        found[device.qualified(entity_key)] = Target(
            device=device,
            key=device.qualified(entity_key),
            platform=platform,
            builder=name,
            by=by,
            item=item,
            actions=actions.services if actions else (),
        )
    return found


def index(devices: dict[str, dict[str, Any]]) -> Index:
    """Every device's targets, by device key."""
    return {key: targets(key, config) for key, config in devices.items()}
