"""Every entity of a device, from its builders, and which of them can be created."""

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, split_entity_id
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity

from ..const import DOMAIN
from ..core.entity import PururuEntity, other_holder
from ..core.feature import Device
from ..core.resolve import Index, Ref, find
from ..core.roles import Generates, Refers
from ..core.texts import Texts
from . import catalogue

_LOGGER = logging.getLogger(__name__)


def build(
    hass: HomeAssistant,
    key: str,
    config: dict[str, Any],
    index: Index,
    texts: Texts,
    owned: Mapping[str, str],
) -> tuple[list[tuple[PururuEntity, set[str]]], dict[str, str]]:
    """Every entity of the device's features, with the unique IDs of the entities it follows.

    A builder's own entities, then those of the aspects it offers (its
    ready-made alerts, the meters of its totals), all in its namespace, each
    stamped with its path from the index, where its key is born.
    Each feature sees the device in its own namespace; what it refers to is
    in the owning feature's. What an entity follows is of this device or of
    another, so whether it is created is the house's to say (`creatable`,
    once over every device). Also the entity ID of each entity some entity
    watches (`follows`), by unique ID: the settings may never build it, and
    then only this names it. `index` is what each device can create; `owned`
    are the entity IDs of the scripts and automations the entry generates, by
    ID.
    """
    paths = {target.key: path for path, target in index[key].items()}
    built: list[tuple[PururuEntity, set[str]]] = []
    watched: dict[str, str] = {}
    for name, feature in catalogue.builders().items():
        if name not in config:
            continue
        device = Device(key=key, name=config[CONF_NAME], namespace=feature.namespace)
        inputs = _inputs(hass, key, config, name, index, owned)
        aspects = (
            entity
            for aspect in catalogue.aspects_of(feature)
            for entity in aspect.build(hass, device, feature, config[name], texts)
        )
        for entity in (*feature.build(hass, device, config[name], inputs), *aspects):
            entity.path = paths[entity.key]
            follows = set()
            for text in entity.follows:
                target = find(index, key, Ref.parse(text))
                assert target is not None  # the schema checked it (checks.references)
                follows.add(target.unique_id)
                watched[target.unique_id] = target.current_entity_id(hass)
            built.append((entity, {*map(device.object_id, entity.sources), *follows}))
    return built, watched


def _inputs(
    hass: HomeAssistant,
    key: str,
    config: dict[str, Any],
    name: str,
    index: Index,
    owned: Mapping[str, str],
) -> dict[str, str]:
    """What builder `name` gets in `inputs`.

    A feature: the current entity IDs of what it refers to. A builder that
    Generates: the entity IDs of its scripts or automations the entry owns,
    by ID: its statistics never watch one the entry doesn't.
    """
    feature = catalogue.builders()[name]
    if (generates := feature.role(Generates)) is not None:
        return {
            unique_id: owned[unique_id]
            for _, unique_id in generates.ids(key, config[name])
            if unique_id in owned
        }
    inputs: dict[str, str] = {}
    refers = feature.role(Refers)
    for _, ref in refers.of(config[name]) if refers else ():
        target = find(index, key, ref)
        assert target is not None  # the schema checked it (checks.references)
        inputs[ref.text] = target.current_entity_id(hass)
    return inputs


def creatable(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    built: list[tuple[PururuEntity, set[str]]],
    watched: dict[str, str],
) -> list[PururuEntity]:
    """The entities whose ID is free and whose sources are created too; the rest logged.

    `built` is every device's: an entity may follow another device's. A
    source the settings don't build (an entity key a feature can create, but
    not with this device's settings) can only be watched: `watched` names it.
    A source the entity says is disabled (`disabled`) isn't created for it
    alone: the source is, and so is everything else that follows it.
    """
    built_ids = {str(entity.unique_id) for entity, _ in built}
    missing: dict[str, str] = {}  # unique ID -> entity ID, of what isn't created
    kept: list[tuple[PururuEntity, set[str]]] = []
    for entity, sources in built:
        if unbuilt := sorted(
            watched.get(source, source) for source in sources if source not in built_ids
        ):
            _LOGGER.error(
                "%s watches %s, which this device's settings don't create "
                "(turn it on, or watch another entity); not creating it",
                entity.entity_id,
                ", ".join(unbuilt),
            )
            missing[str(entity.unique_id)] = entity.entity_id
            continue
        if (holder := _holder(hass, registry, entity)) is None:
            kept.append((entity, sources))
            continue
        _LOGGER.error(
            "%s is already taken by %s; not creating it", entity.entity_id, holder
        )
        missing[str(entity.unique_id)] = entity.entity_id
    lost = True
    while lost:  # until nothing left follows what isn't created
        lost = False
        for entity, sources in list(kept):
            absent = {**missing, **entity.disabled}
            if gone := sorted(absent[source] for source in sources if source in absent):
                _LOGGER.error(
                    "%s follows %s, which is not created; not creating it",
                    entity.entity_id,
                    ", ".join(gone),
                )
                missing[str(entity.unique_id)] = entity.entity_id
                kept.remove((entity, sources))
                lost = True
    return [entity for entity, _ in kept]


def _holder(
    hass: HomeAssistant, registry: er.EntityRegistry, entity: Entity
) -> str | None:
    """Who else has this entity's ID; None when it is free or already this entity's.

    Checked by unique ID first: a renamed entity is still ours wherever the
    user moved it to, even if another integration since took its old ID.
    """
    domain = split_entity_id(entity.entity_id)[0]
    if entity.unique_id is not None:
        if registry.async_get_entity_id(domain, DOMAIN, entity.unique_id) is not None:
            return None
    return other_holder(hass, registry, entity.entity_id)
