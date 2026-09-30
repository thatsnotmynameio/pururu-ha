"""Every builder of a device, the aspects mounted in its blocks, and the entity keys they can create."""

from collections.abc import Iterable, Iterator, Mapping
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_NAME, Platform

from ..aspects import ASPECTS
from ..core.feature import Aspect, Device, Feature, Item
from ..core.resolve import Index, Target
from ..core.roles import Actions, Configured, Derived, Items
from ..device_keys import DEVICE_KEYS
from ..features import FEATURES


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


def _taken(value: Any, aspect: Aspect, places: Places, path: Place) -> Any:
    """`value` without the aspect's key, what the key held put in `places` at `path`.

    Absent, or `value` not a map (left whole): `{}`, or nothing put when the
    aspect doesn't mount an absent key (Aspect.mount_absent).
    """
    if isinstance(value, dict) and aspect.key in value:
        places[path, aspect.key] = value[aspect.key]
        return {each: kept for each, kept in value.items() if each != aspect.key}
    if aspect.mount_absent:
        places[path, aspect.key] = {}
    return value


def _split(
    builder: Feature, aspects: tuple[Aspect, ...], value: Any
) -> tuple[Any, Places]:
    """The block without the aspects' keys, and their values by where each aspect sits (Aspect.placed)."""
    rest = value
    places: Places = {}
    for aspect in aspects:
        if aspect.placed(builder) == "block":
            rest = _taken(rest, aspect, places, ())
        elif isinstance(rest, dict):
            # As the builder's schema returns it: cv.slug makes YAML's 1 "1"
            rest = {
                key: _taken(item, aspect, places, (str(key),))
                for key, item in rest.items()
            }
    return rest, places


def mount(builder: Feature, name: str, value: Any) -> Any:
    """Builder `name`'s block, validated, each offered aspect's value in it where it was.

    Each aspect's key is taken out of the block, or out of each item, where the
    aspect says it sits (Aspect.placed), and validated by the aspect: absent,
    as `{}`, or left out (Aspect.mount_absent). The rest goes to the
    builder's own schema.
    This is the first stage: the builder's own schema refusal and each
    aspect's schema refusal are raised together, before either runs a check.
    Once every value is validated and back where it sat, the second stage
    runs: each aspect checks each container it sits in (Aspect.check), and
    those refusals are raised together too, separately from the first stage's.
    """
    if not (aspects := aspects_of(builder)):
        return builder.schema(value)
    by_key = {aspect.key: aspect for aspect in aspects}
    rest, places = _split(builder, aspects, value)
    errors: list[vol.Invalid] = []
    block: Any = None
    try:
        block = builder.schema(rest)
    except vol.Invalid as error:
        errors.append(error)
    mounted: Places = {}
    for (path, key), taken in places.items():
        try:
            mounted[path, key] = by_key[key].schema(builder, name)(taken)
        except vol.Invalid as error:
            error.prepend([*path, key])
            errors.append(error)
    if errors:
        raise vol.MultipleInvalid(_flat(errors))
    for (path, key), each in mounted.items():
        block = _put(block, path, key, each)
    if errors := _checked(builder, name, by_key, block, mounted.keys()):
        raise vol.MultipleInvalid(_flat(errors))
    return block


def _checked(
    builder: Feature,
    name: str,
    aspects: Mapping[str, Aspect],
    block: dict[str, Any],
    places: Iterable[tuple[Place, str]],
) -> list[vol.Invalid]:
    """Each aspect's check (Aspect.check) on each container it sits in; the refusals, with their path."""
    errors: list[vol.Invalid] = []
    for path, key in places:
        if (check := aspects[key].check) is None:
            continue
        try:
            check(builder, name, block[path[0]] if path else block)
        except vol.Invalid as error:
            error.prepend(list(path))
            errors.append(error)
    return errors


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


def keys(
    device: dict[str, Any],
) -> Iterator[tuple[str, str, Platform, str | None, str | None]]:
    """(builder, local entity key, platform, by, item) of every entity the device's builders can create.

    `by` is the key of the aspect adding it ("alerts" for a ready-made
    alert's, "statistics" for a meter's), None for the builder's own; `item`
    the item owning an Items key.
    """
    for name, feature in builders().items():
        if name not in device:
            continue
        yield from (
            (name, entity_key, platform, None, None)
            for entity_key, platform in feature.entity_keys.items()
        )
        if (configured := feature.role(Configured)) is not None:
            yield from (
                (name, entity_key, configured.platform, None, None)
                for entity_key in device[name]
            )
        if (derived := feature.role(Derived)) is not None:
            yield from (
                (name, entity_key, platform, None, None)
                for entity_key, platform in derived.of(device[name]).items()
            )
        each: list[Item] | None = None
        if (items := feature.role(Items)) is not None:
            each = list(items.of(device[name]))
            yield from _per_item(name, each, items.keys, None)
        yield from _aspects_keys(name, feature, each)


def _aspects_keys(
    name: str, feature: Feature, items: list[Item] | None
) -> Iterator[tuple[str, str, Platform, str | None, str | None]]:
    """keys()' rows for the keys each aspect it offers adds: per item for an Items builder (`items`)."""
    for aspect in aspects_of(feature):
        added = aspect.keys(feature)
        if items is not None:
            yield from _per_item(name, items, added, aspect.key)
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
