"""The rules over the whole house that no one block owns: references, real entities, IDs, areas, messages.

Each is a Check (schema.CHECKS). The rules a block owns live in its module:
reactions.check, programs.check, alerts.check, alert_lights.check,
places.floors_exist.
"""

from collections.abc import Hashable, Iterator, Mapping
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_NAME

from ..aspects import notifications, programs
from ..const import (
    CONF_AREA,
    CONF_AREAS,
    CONF_CONFIG,
    CONF_DEVICES,
    CONF_EXECUTABLE,
    CONF_MESSAGE,
    CONF_NOTIFICATIONS,
    CONF_NOTIFY,
    CONF_PROGRAMS,
    CONF_REACTIONS,
)
from ..core import generated
from ..core.feature import Device, Feature
from ..core.resolve import HOME_ASSISTANT, Index, Owner, Ref, Target, resolve
from ..core.roles import Configured, Generates, Refers
from ..device_keys import reactions
from . import catalogue


def references(
    house: Mapping[str, Any], index: Index, builders: Mapping[str, Feature]
) -> Iterator[vol.Invalid]:
    """Refuse a reference that isn't another block's entity, within its reach, at its field (an alert watching an alert: alerts.check).

    An executable program is followed by a reaction's when only: it is no
    entity pururu creates, so an alert can't follow it. Another device's
    entities are another block's.
    """
    devices = house[CONF_DEVICES]
    for key, device in devices.items():
        for name, feature in builders.items():
            if name in device and (refers := feature.role(Refers)) is not None:
                yield from _refused_refs(index, devices, key, name, refers)


def _refused_refs(
    index: Index, devices: Mapping[str, Any], key: str, name: str, refers: Refers
) -> Iterator[vol.Invalid]:
    """Builder `name`'s references on device `key` that it can't have: one refusal each, at its field."""
    for where, ref in refers.of(devices[key][name]):
        path: list[Hashable] = [CONF_DEVICES, key, name, *where]
        found = _reached(index, devices, key, ref, refers)
        if isinstance(found, str):
            yield vol.Invalid(f"{name}: {found}", path=path)
        elif found.builder == name and found.device.key == key:
            yield vol.Invalid(
                f"{name}: {ref.text} is not another block's entity", path=path
            )


def _reached(
    index: Index, devices: Mapping[str, Any], key: str, ref: Ref, refers: Refers
) -> Target | str:
    """What `ref`, written in device `key`, names within the builder's reach; else why it can't, after the field's place.

    Another device's path is within it with Refers.other_devices only; an
    executable program never is.
    """
    if not refers.other_devices or ref.owner is not Owner.DEVICE:
        return programs.reach(index, devices, key, ref)
    if programs.running(devices, key, ref):
        return f"{ref.text} {programs.RUNNING}"
    return resolve(index, key, ref)


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
                # Quoted as written: the schema took homeassistant. off
                yield vol.Invalid(
                    f"{name}: {HOME_ASSISTANT}.{entity} is already in {owners[entity]}",
                    path=[CONF_DEVICES, key, name],
                )


def pururus_own_as_home_assistants(
    house: Mapping[str, Any], index: Index, builders: Mapping[str, Feature]
) -> Iterator[vol.Invalid]:
    """Refuse a reaction's when naming as Home Assistant's what pururu creates or generates, with what to write.

    One way to write each thing: its path follows a rename in the UI, and a
    reaction (reactions.<key>) is refused for what counts it. Matched against
    the IDs as pururu creates them; any other pururu_ ID, a helper of the
    user's, is Home Assistant's.
    """
    # (device, reaction, its when) of each when naming Home Assistant's
    watching = [
        (key, reaction_key, ref)
        for key, device in house[CONF_DEVICES].items()
        for reaction_key, reaction in device.get(CONF_REACTIONS, {}).items()
        if "when" in reaction
        and (ref := Ref.parse(reaction["when"])).owner is Owner.HOME_ASSISTANT
    ]
    if not watching:
        return
    pururus = _pururus(house, index, builders)
    for key, reaction_key, ref in watching:
        if ref.path not in pururus:
            continue
        owner = pururus[ref.path]
        if owner is None:
            why = "is a ready-made notification: a reaction can't watch it"
        else:
            written = Ref(Owner.DEVICE, *owner)
            if written.device == key:
                written = Ref(Owner.HERE, None, written.path)
            why = f"is pururu's: write {written.text}"
        yield vol.Invalid(
            f"reactions: {reaction_key}: {ref.text} {why}",
            path=[CONF_DEVICES, key, CONF_REACTIONS, reaction_key, "when"],
        )


def _pururus(
    house: Mapping[str, Any], index: Index, builders: Mapping[str, Feature]
) -> dict[str, tuple[str, str] | None]:
    """Entity ID as created -> (device, the path to write), of all pururu creates and generates; None: nothing to write.

    A program's script is followed by its path (programs.executable.<key>),
    a reaction's automation by what counts it; a ready-made notification's
    automation by nothing.
    """
    pururus: dict[str, tuple[str, str] | None] = {
        target.entity_id(): (key, path)
        for key, targets in index.items()
        for path, target in targets.items()
    }
    for key, device in house[CONF_DEVICES].items():
        for program in programs.executable(device):
            pururus[
                f"{generated.SCRIPTS.domain}.{programs.script_id(key, program)}"
            ] = (
                key,
                f"{CONF_PROGRAMS}.{CONF_EXECUTABLE}.{program}",
            )
        for reaction in device.get(CONF_REACTIONS, {}):
            automation = reactions.automation_id(key, reaction)
            pururus[f"{generated.AUTOMATIONS.domain}.{automation}"] = (
                key,
                f"{CONF_REACTIONS}.{reaction}.triggered_total",
            )
        for _, feature, notification, _ in notifications.enabled(device, builders):
            automation = notifications.automation_id(
                key, feature.namespace, notification
            )
            pururus[f"{generated.AUTOMATIONS.domain}.{automation}"] = None
    return pururus


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
