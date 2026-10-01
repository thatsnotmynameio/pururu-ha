"""Every builder of a device, the aspects mounted in its blocks, and the entity keys they can create."""

from collections.abc import Iterator
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_NAME, Platform

from ..aspects import ASPECTS
from ..core.feature import (
    EACH,
    Aspect,
    Device,
    Feature,
    Path,
    Place,
    at,
    item_key,
    walk,
)
from ..core.resolve import Index, Target
from ..core.roles import Actions, Configured, Derived, Items, Nodes
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


# An aspect's value by where it sat (its container's path, EACH made each
# key) and the aspect's key, with the place it sat at
type Taken = dict[tuple[Path, str], tuple[Place, Any]]


def _taken(value: Any, aspect: Aspect, place: Place, taken: Taken, where: Path) -> Any:
    """`value` without the aspect's key, what the key held put in `taken` at `where`.

    Absent, or `value` not a map (left whole): `{}`, or nothing put when the
    aspect doesn't mount an absent key (Aspect.mount_absent).
    """
    if isinstance(value, dict) and aspect.key in value:
        taken[where, aspect.key] = (place, value[aspect.key])
        return {each: kept for each, kept in value.items() if each != aspect.key}
    if aspect.mount_absent:
        taken[where, aspect.key] = (place, {})
    return value


def _take(
    value: Any,
    path: Path,
    aspect: Aspect,
    place: Place,
    taken: Taken,
    where: Path = (),
) -> Any:
    """`value` without the aspect's key in each container `path` names (feature.walk's rule), rebuilt along the path."""
    if not path:
        return _taken(value, aspect, place, taken, where)
    if not isinstance(value, dict):
        return value
    head, *rest = path
    present = [head] if head in value else []
    keys = list(value) if head == EACH else present
    return {
        **value,
        **{
            key: _take(
                value[key], tuple(rest), aspect, place, taken, (*where, str(key))
            )
            for key in keys
        },
    }


def _split(
    builder: Feature, name: str, aspects: tuple[Aspect, ...], value: Any
) -> tuple[Any, Taken]:
    """The block without the aspects' keys, and their values by where each sat (Aspect.places).

    The deepest places first: an aspect's key inside another aspect's value
    (statistics in a detected program, in `programs:`) leaves it before that
    value is taken whole. Places at one depth keep ASPECTS' order.
    """
    rest = value
    taken: Taken = {}
    placed = [
        (aspect, place) for aspect in aspects for place in aspect.places(builder, name)
    ]
    for aspect, place in sorted(placed, key=lambda pair: -len(pair[1].path)):
        rest = _take(rest, place.path, aspect, place, taken)
    return rest, taken


def mount(builder: Feature, name: str, value: Any) -> Any:
    """Builder `name`'s block, validated, each offered aspect's value in it where it was.

    Each aspect's key is taken out of each container its places name (the
    block, each item, a running program, each phase: Aspect.places), and
    validated by that place's schema: absent, as `{}`, or left out
    (Aspect.mount_absent). The rest goes to the builder's own schema.
    This is the first stage: the builder's own schema refusal and each
    aspect's schema refusal are raised together, before either runs a check.
    Once every value is validated and back where it sat, the second stage
    runs: each place's check on each container (Place.check), and those
    refusals are raised together too, separately from the first stage's.
    """
    if not (aspects := aspects_of(builder)):
        return builder.schema(value)
    rest, taken = _split(builder, name, aspects, value)
    errors: list[vol.Invalid] = []
    block: Any = None
    try:
        block = builder.schema(rest)
    except vol.Invalid as error:
        errors.append(error)
    mounted: Taken = {}
    for (path, key), (place, each) in taken.items():
        try:
            mounted[path, key] = (place, place.schema(each))
        except vol.Invalid as error:
            error.prepend([*path, key])
            errors.append(error)
    if errors:
        raise vol.MultipleInvalid(_flat(errors))
    # The shallowest first: `programs:` is back before its programs' `statistics:`
    for (path, key), (_, each) in sorted(
        mounted.items(), key=lambda row: len(row[0][0])
    ):
        block = _put(block, path, key, each)
    if errors := _checked(block, mounted):
        raise vol.MultipleInvalid(_flat(errors))
    return block


def _checked(block: dict[str, Any], mounted: Taken) -> list[vol.Invalid]:
    """Each place's check (Place.check) on each container it sat in; the refusals, with their path."""
    errors: list[vol.Invalid] = []
    for (path, _), (place, _) in mounted.items():
        if place.check is None:
            continue
        try:
            place.check(block, at(block, path))
        except vol.Invalid as error:
            error.prepend(list(path))
            errors.append(error)
    return errors


def _put(block: dict[str, Any], path: Path, key: str, value: Any) -> Any:
    """`block` with `value` under `key` back where it sat, rebuilt along `path`."""
    if not path:
        return {**block, key: value}
    head, *rest = path
    return {**block, head: _put(block[head], tuple(rest), key, value)}


def _flat(errors: list[vol.Invalid]) -> list[vol.Invalid]:
    """Each refusal on its own: a schema's MultipleInvalid opened."""
    return [
        each
        for error in errors
        for each in (
            error.errors if isinstance(error, vol.MultipleInvalid) else [error]
        )
    ]


# A row of keys(): (builder, local entity key, platform, by, item, path)
type Row = tuple[str, str, Platform, str | None, str | None, str]


def _dotted(name: str, *path: str) -> str:
    """A path from the builder's key in the device, as the author reads it: appliance.running_program."""
    return ".".join((name, *path))


def _node(feature: Feature, entity_key: str) -> Path:
    """Where a fixed entity key sits in its builder's block (Nodes); at the block under its own name unless the builder says."""
    nodes = feature.role(Nodes)
    return (entity_key,) if nodes is None else nodes.of.get(entity_key, (entity_key,))


def keys(device: dict[str, Any]) -> Iterator[Row]:
    """(builder, local entity key, platform, by, item, path) of every entity the device's builders can create.

    `by` is the key of the aspect adding it ("alerts" for a ready-made
    alert's, "statistics" for a meter's), None for the builder's own; `item`
    the item owning the key (an Items item, or a container an aspect's place
    makes one: a phase). `path` is its node in the device's YAML, from the
    builder's key, as each key is born: a fixed key's node (Nodes), a block
    key's own, a derived key's (Born), an item's suffix under the item, an
    aspect's under its key in the container.
    """
    for name, feature in builders().items():
        if name not in device:
            continue
        yield from (
            (
                name,
                entity_key,
                platform,
                None,
                None,
                _dotted(name, *_node(feature, entity_key)),
            )
            for entity_key, platform in feature.entity_keys.items()
        )
        if (configured := feature.role(Configured)) is not None:
            yield from (
                (
                    name,
                    entity_key,
                    configured.platform,
                    None,
                    None,
                    _dotted(name, entity_key),
                )
                for entity_key in device[name]
            )
        if (derived := feature.role(Derived)) is not None:
            yield from (
                (name, entity_key, born.platform, None, None, _dotted(name, *born.path))
                for entity_key, born in derived.of(device[name]).items()
            )
        if (items := feature.role(Items)) is not None:
            yield from (
                (
                    name,
                    item.key(suffix),
                    platform,
                    None,
                    item.slug,
                    _dotted(name, *item.path, suffix),
                )
                for item in items.of(device[name])
                for suffix, platform in items.keys.items()
            )
        yield from _aspects_keys(name, feature, device[name])


def _aspects_keys(name: str, feature: Feature, block: Any) -> Iterator[Row]:
    """keys()' rows for the keys each aspect it offers adds, at each container of each of its places.

    Its fixed keys (Place.keys) at every container, as an item's where the
    container is one; then what the aspect's value there adds (Place.derived).
    """
    for aspect in aspects_of(feature):
        for place in aspect.places(feature, name):
            for path, container in walk(block, place.path):
                yield from _place_keys(name, aspect, place, block, path, container)


def _place_keys(
    name: str, aspect: Aspect, place: Place, block: Any, path: Path, container: Any
) -> Iterator[Row]:
    """_aspects_keys' rows for one container at `path`: the place's fixed keys, then what it derives.

    Each under the aspect's key in the container: a fixed key at its leaf
    (Place.leaves), a derived one at its Born path.
    """
    item = None if place.item is None else place.item(block, path)
    yield from (
        (
            name,
            item_key(entity_key, item),
            platform,
            aspect.key,
            None if item is None else item.slug,
            _dotted(name, *path, aspect.key, *place.leaves[entity_key]),
        )
        for entity_key, platform in place.keys.items()
    )
    if place.derived is not None and aspect.key in container:
        yield from (
            (
                name,
                entity_key,
                born.platform,
                aspect.key,
                None,
                _dotted(name, *path, aspect.key, *born.path),
            )
            for entity_key, born in place.derived(container[aspect.key])
        )


def targets(key: str, config: dict[str, Any]) -> dict[str, Target]:
    """Every entity device `key` can create, by its path, and what it is."""
    found: dict[str, Target] = {}
    for name, entity_key, platform, by, item, path in keys(config):
        feature = builders()[name]
        device = Device(key=key, name=config[CONF_NAME], namespace=feature.namespace)
        actions = feature.role(Actions)
        found[path] = Target(
            device=device,
            key=device.qualified(entity_key),
            path=path,
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
