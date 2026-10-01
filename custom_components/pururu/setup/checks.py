"""The rules over the whole house that no one block owns: references, real entities, IDs, areas, messages.

Each is a Check (schema.CHECKS). The rules a block owns live in its module:
reactions.check, programs.check, alerts.check, alert_lights.check,
places.floors_exist.
"""

from collections.abc import Hashable, Iterator, Mapping
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_NAME

from ..aspects import notifications
from ..const import (
    CONF_AREA,
    CONF_AREAS,
    CONF_CONFIG,
    CONF_DEVICES,
    CONF_MESSAGE,
    CONF_NOTIFICATIONS,
    CONF_NOTIFY,
    CONF_REACTIONS,
)
from ..core import generated
from ..core.feature import Device, Feature
from ..core.resolve import Index, Owner, resolve
from ..core.roles import Configured, Generates, Refers
from . import catalogue


def references(
    house: Mapping[str, Any], index: Index, builders: Mapping[str, Feature]
) -> Iterator[vol.Invalid]:
    """Refuse a reference that isn't another block's entity, within its reach, at its field (an alert watching an alert: alerts.check)."""
    for key, device in house[CONF_DEVICES].items():
        for name, feature in builders.items():
            if name in device and (refers := feature.role(Refers)) is not None:
                yield from _refused_refs(index, key, name, refers, device[name])


def _refused_refs(
    index: Index, key: str, name: str, refers: Refers, block: Any
) -> Iterator[vol.Invalid]:
    """Builder `name`'s references on device `key` that it can't have: one refusal each, at its field."""
    for where, ref in refers.of(block):
        path: list[Hashable] = [CONF_DEVICES, key, name, *where]
        if ref.owner is Owner.HOME_ASSISTANT or (
            ref.owner is Owner.DEVICE and ref.device != key and not refers.others
        ):
            yield vol.Invalid(f"{name}: {ref.text} is not of this device", path=path)
            continue
        found = resolve(index, key, ref)
        if isinstance(found, str):
            yield vol.Invalid(f"{name}: {found}", path=path)
        elif found.builder == name:
            yield vol.Invalid(
                f"{name}: {ref.text} is not another block's entity", path=path
            )


def real_entities_distinct(
    house: Mapping[str, Any], index: Index, builders: Mapping[str, Feature]
) -> Iterator[vol.Invalid]:
    """Refuse a real entity in two configured features of a device: a relay is a switch or a light."""
    for key, device in house[CONF_DEVICES].items():
        yield from _shared_real_entities(key, device, builders)


def _shared_real_entities(
    key: str, device: Mapping[str, Any], builders: Mapping[str, Feature]
) -> Iterator[vol.Invalid]:
    """Device `key`'s real entities already in another of its configured features."""
    owners: dict[str, str] = {}  # real entity -> the configured feature that has it
    for name, feature in builders.items():
        if name not in device or feature.role(Configured) is None:
            continue
        # A configured key need not stand for a real entity (an alert)
        for entity in filter(
            None, (item.get("entity") for item in device[name].values())
        ):
            if owners.setdefault(entity, name) != name:
                yield vol.Invalid(
                    f"{name}: {entity} is already in {owners[entity]}",
                    path=[CONF_DEVICES, key, name],
                )


def areas_exist(
    house: Mapping[str, Any], index: Index, builders: Mapping[str, Feature]
) -> Iterator[vol.Invalid]:
    """Refuse a device in an area the configuration doesn't declare."""
    for key, device in house[CONF_DEVICES].items():
        area_id = device.get(CONF_AREA)
        if area_id is not None and area_id not in house[CONF_AREAS]:
            yield vol.Invalid(
                f"device {key}: area {area_id} is not in areas",
                path=[CONF_DEVICES, key, CONF_AREA],
            )


def keys_distinct(
    house: Mapping[str, Any], index: Index, builders: Mapping[str, Feature]
) -> Iterator[vol.Invalid]:
    """Refuse two entities of one device with one unique ID, whatever their platforms.

    Home Assistant keeps one entity per unique ID and would lose the other. A
    phase keyed resfriar_cycles_today has the binary sensor
    phase_resfriar_cycles_today, phase resfriar's meter's key.
    """
    for key, device in house[CONF_DEVICES].items():
        seen: set[str] = set()
        for name, entity_key, *_ in catalogue.keys(device):
            unique_id = Device(
                key=key, name=device[CONF_NAME], namespace=builders[name].namespace
            ).object_id(entity_key)
            if unique_id in seen:
                yield vol.Invalid(
                    f"device {key}: {unique_id} would be two entities",
                    path=[CONF_DEVICES, key],
                )
                break
            seen.add(unique_id)


def entity_ids_distinct(
    house: Mapping[str, Any], index: Index, builders: Mapping[str, Feature]
) -> Iterator[vol.Invalid]:
    """Refuse two devices whose entities would share an ID.

    Device `greenhouse` with the switch `switch_sprinkler` and device `greenhouse_switch` with
    the switch `sprinkler` would both have pururu_greenhouse_switch_switch_sprinkler.
    """
    owners: dict[str, str] = {}  # object ID -> the device that has it
    for key, targets in index.items():
        for target in targets.values():
            if (owner := owners.setdefault(target.unique_id, key)) != key:
                yield vol.Invalid(
                    f"device {key}: {target.unique_id} is already an entity of "
                    f"device {owner}",
                    path=[CONF_DEVICES, key],
                )
                break


def _generated_ids(
    key: str, device: Mapping[str, Any], builders: Mapping[str, Feature]
) -> Iterator[tuple[str, str, str]]:
    """(domain, ID, what) of every automation and script the device generates."""
    for name, feature in builders.items():
        if name in device and (generates := feature.role(Generates)) is not None:
            for domain, unique_id in generates.ids(key, device[name]):
                yield domain, unique_id, generates.what
    for _, feature, notification, _ in notifications.enabled(device, builders):
        yield (
            generated.AUTOMATIONS.domain,
            notifications.automation_id(key, feature.namespace, notification),
            "notification",
        )


def generated_ids_distinct(
    house: Mapping[str, Any], index: Index, builders: Mapping[str, Feature]
) -> Iterator[vol.Invalid]:
    """Refuse two automations, or two scripts, that would share an ID.

    Device `lights` with the reaction `b_reaction_c` and device `lights_reaction_b`
    with the reaction `c` would both have pururu_lights_reaction_b_reaction_c; a
    reaction's and a notification's may meet the same way.
    """
    owners: dict[
        tuple[str, str], tuple[str, str]
    ] = {}  # (domain, ID) -> (device, what)
    for key, device in house[CONF_DEVICES].items():
        for domain, unique_id, what in _generated_ids(key, device, builders):
            if (owner := owners.get((domain, unique_id))) is not None:
                yield vol.Invalid(
                    f"device {key}: {domain}.{unique_id} is already a {owner[1]} "
                    f"of device {owner[0]}",
                    path=[CONF_DEVICES, key],
                )
                break
            owners[domain, unique_id] = (key, what)


def messages_sent(
    house: Mapping[str, Any], index: Index, builders: Mapping[str, Feature]
) -> Iterator[vol.Invalid]:
    """Refuse a message that goes nowhere, a reaction's or a notification's.

    Neither a notify of its own nor one in config.notify.
    """
    if house[CONF_CONFIG].get(CONF_NOTIFY):
        return
    for key, device in house[CONF_DEVICES].items():
        for reaction_key, reaction in device.get(CONF_REACTIONS, {}).items():
            if CONF_MESSAGE in reaction and CONF_NOTIFY not in reaction:
                yield vol.Invalid(
                    f"device {key}: reactions: {reaction_key}: message needs notify, "
                    "here or in config.notify",
                    path=[CONF_DEVICES, key, CONF_REACTIONS, reaction_key],
                )
        for name, _, notification, settings in notifications.enabled(device, builders):
            if CONF_NOTIFY not in settings:
                yield vol.Invalid(
                    f"device {key}: {name}: notifications: {notification} needs "
                    "notify, here or in config.notify",
                    path=[CONF_DEVICES, key, name, CONF_NOTIFICATIONS, notification],
                )
