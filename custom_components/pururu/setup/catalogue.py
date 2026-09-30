"""Every builder of a device, the aspects mounted in its blocks, and the entity keys they can create."""

from collections.abc import Iterable, Iterator, Mapping
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_NAME, Platform

from ..aspects import ASPECTS
from ..const import CONF_NOTIFICATIONS
from ..core.feature import (
    ALERTS_KEY,
    Aspect,
    Device,
    Feature,
    Item,
    happenings_of,
    preset_keys,
    presets_of,
)
from ..core.resolve import Index, Target
from ..core.roles import Actions, Configured, Items
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


# Where an aspect's value sat: () the block, (key,) the block's item `key`
type Place = tuple[str, ...]
# An aspect's value by where it sat and the aspect's key
type Places = dict[tuple[Place, str], Any]


def _taken(value: Any, key: str) -> tuple[Any, Any]:
    """`value` without `key`, and what `key` held (absent: `{}`); anything but a map is left whole."""
    if not isinstance(value, dict):
        return value, {}
    return {each: kept for each, kept in value.items() if each != key}, value.get(
        key, {}
    )


def _split(
    builder: Feature, aspects: tuple[Aspect, ...], value: Any
) -> tuple[Any, Places]:
    """The block without the aspects' keys, and their values by where each aspect sits (Aspect.placed)."""
    rest = value
    places: Places = {}
    for aspect in aspects:
        if aspect.placed(builder) == "block":
            rest, places[(), aspect.key] = _taken(rest, aspect.key)
        elif isinstance(rest, dict):
            items = {}
            for key, item in rest.items():
                # As the builder's schema returns it: cv.slug makes YAML's 1 "1"
                items[key], places[(str(key),), aspect.key] = _taken(item, aspect.key)
            rest = items
    return rest, places


def _validated(builder: Feature, name: str, value: Any) -> Any:
    """What is left of the block: a feature's (_feature_block), or the device key's schema."""
    if name in FEATURES:
        return _feature_block(builder, name, value)
    return builder.schema(value)


def mount(builder: Feature, name: str, value: Any) -> Any:
    """Builder `name`'s block, validated, each offered aspect's value in it where it was.

    Each aspect's key is taken out of the block, or out of each item, where the
    aspect says it sits (Aspect.placed), and validated by the aspect: absent, as
    `{}`. The rest goes to _validated. Once every value is back, each aspect
    checks each container it sits in (Aspect.check). Every refusal is told at
    once, with its path.
    """
    if not (aspects := aspects_of(builder)):
        return _validated(builder, name, value)
    by_key = {aspect.key: aspect for aspect in aspects}
    rest, places = _split(builder, aspects, value)
    errors: list[vol.Invalid] = []
    block: Any = None
    try:
        block = _validated(builder, name, rest)
    except vol.Invalid as error:
        errors.append(error)
    mounted: Places = {}
    for (path, key), taken in places.items():
        try:
            mounted[path, key] = by_key[key].schema(builder)(taken)
        except vol.Invalid as error:
            error.prepend([*path, key])
            errors.append(error)
    if errors:
        raise vol.MultipleInvalid(_flat(errors))
    for (path, key), each in mounted.items():
        block = _put(block, path, key, each)
    for path, key in mounted:
        if (check := by_key[key].check) is None:
            continue
        try:
            check(builder, block[path[0]] if path else block)
        except vol.Invalid as error:
            error.prepend(list(path))
            errors.append(error)
    if errors:
        raise vol.MultipleInvalid(_flat(errors))
    return block


def _put(block: dict[str, Any], path: Place, key: str, value: Any) -> Any:
    """`block` with `value` under `key` back where it sat."""
    if not path:
        return {**block, key: value}
    (item,) = path
    return {**block, item: {**block[item], key: value}}


def _flat(errors: list[vol.Invalid]) -> list[vol.Invalid]:
    """Each refusal on its own: a schema's MultipleInvalid opened."""
    return [
        each
        for error in errors
        for each in (
            error.errors if isinstance(error, vol.MultipleInvalid) else [error]
        )
    ]


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
        each = [] if items is None else list(items.of(device[name]))
        if items is not None:
            yield from _per_item(name, each, items.keys, None)
        for aspect in aspects_of(feature):
            added = aspect.keys(feature)
            if items is not None:
                yield from _per_item(name, each, added, aspect.key)
                continue
            yield from (
                (name, entity_key, platform, aspect.key, None)
                for entity_key, platform in added.items()
            )


def _per_item(
    name: str, items: Iterable[Item], suffixes: Mapping[str, Platform], by: str | None
) -> Iterator[tuple[str, str, Platform, str | None, str | None]]:
    """keys()' rows for `suffixes` repeated per item: <slug>_<suffix>, owned by the item."""
    return (
        (name, item.key(suffix), platform, by, item.slug)
        for item in items
        for suffix, platform in suffixes.items()
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
