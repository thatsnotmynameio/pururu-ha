"""The rules a configuration must follow beyond each block's own schema."""

from collections.abc import Iterator
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_NAME

from . import alert_lights, notifications, programs, reactions
from .catalogue import builders, entity_keys, referable
from .const import (
    CONF_ALERTS,
    CONF_AREA,
    CONF_AREAS,
    CONF_CONFIG,
    CONF_DEVICES,
    CONF_LIGHTS,
    CONF_MESSAGE,
    CONF_NOTIFY,
    CONF_PROGRAMS,
    CONF_REACTIONS,
    DEFAULT_ALERT_LIGHTS,
)
from .feature import ALERTS_KEY, Device, preset_keys, qualified
from .features import FEATURES


def capabilities_provided(device: dict[str, Any], names: list[str]) -> None:
    """Refuse a <capability>_from that names no feature of the device providing it."""
    for name in names:
        for capability in FEATURES[name].requires:
            source = device[name][f"{capability}_from"]
            if source not in names or capability not in FEATURES[source].provides:
                raise vol.Invalid(
                    f"{name}: {capability}_from must name a feature of this device "
                    f"that provides {capability}"
                )


def real_entities_distinct(device: dict[str, Any], names: list[str]) -> None:
    """Refuse a real entity in two configured features: a relay is a switch or a light."""
    owners: dict[str, str] = {}  # real entity -> the configured feature that has it
    for name in names:
        if FEATURES[name].configured is None:
            continue
        for item in device[name].values():
            # A configured key need not stand for a real entity (an alert)
            if (entity := item.get("entity")) is None:
                continue
            if owners.setdefault(entity, name) != name:
                raise vol.Invalid(f"{name}: {entity} is already in {owners[entity]}")


def references_resolved(device: dict[str, Any], names: list[str]) -> None:
    """Refuse a reference that isn't another feature's entity key."""
    # Every entity key the device can create, in its namespace -> its feature
    owners = {
        qualified(builders()[name].namespace, entity_key): name
        for name, entity_key, _ in entity_keys(device)
    }
    for name in names:
        feature = FEATURES[name]
        if feature.refers is None:
            continue
        for key in feature.refers(device[name]):
            if owners.get(key, name) == name:
                raise vol.Invalid(
                    f"{name}: {key} is not an entity key of another feature "
                    "of this device"
                )


def no_alert_watches_an_alert(device: dict[str, Any], names: list[str]) -> None:
    """Refuse a hand-written alert whose `when` is another feature's ready-made alert."""
    alerts_feature = FEATURES[CONF_ALERTS]
    if CONF_ALERTS not in names or alerts_feature.refers is None:
        return
    ready_made = {
        qualified(FEATURES[name].namespace, alert)
        for name in names
        for alert in preset_keys(FEATURES[name].alerts)
    }
    for key in alerts_feature.refers(device[CONF_ALERTS]):
        if key in ready_made:
            raise vol.Invalid(
                f"{CONF_ALERTS}: {key} is an alert: an alert can't watch another"
            )


def _own_statistics(reaction_key: str) -> set[str]:
    """The entity keys of a reaction's own statistics: watching them, it would feed itself."""
    return {
        qualified(reactions.NAMESPACE, f"{reaction_key}_{suffix}")
        for suffix in reactions.PER_REACTION
    }


def reactions_on_this_device(device: dict[str, Any]) -> None:
    """Refuse a reaction's `when` or `then` that isn't the device's own.

    `when` without `device` names an entity key of the device, and `then` one of
    its programs.
    """
    keys = {
        qualified(builders()[name].namespace, entity_key)
        for name, entity_key, _ in entity_keys(device)
    }
    for key, reaction in device.get(CONF_REACTIONS, {}).items():
        if "device" not in reaction and reaction.get("when") in _own_statistics(key):
            raise vol.Invalid(
                f"reactions: {key}: {reaction['when']} is its own statistic"
            )
        then = reaction.get("then")
        if then is not None and then not in device.get(CONF_PROGRAMS, {}):
            raise vol.Invalid(
                f"reactions: {key}: {then} is not a program of this device"
            )
        if "device" in reaction or (when := reaction.get("when")) is None:
            continue
        if when not in keys:
            raise vol.Invalid(
                f"reactions: {key}: {when} is not an entity key of this device"
            )


def programs_on_this_device(device: dict[str, Any]) -> None:
    """Refuse a step on what isn't a feature's entity key of the device taking its action."""
    owners = {
        qualified(builders()[name].namespace, entity_key): name
        for name, entity_key, _ in entity_keys(device)
    }
    for program in device.get(CONF_PROGRAMS, {}).values():
        for action, key in programs.targets(program):
            if key not in owners:
                raise vol.Invalid(
                    f"programs: {key} is not an entity key of another feature "
                    "of this device"
                )
            if action not in builders()[owners[key]].actions:
                raise vol.Invalid(f"programs: {key} does not take {action}")


def areas_exist(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse a device in an area the configuration doesn't declare."""
    for key, device in config[CONF_DEVICES].items():
        area_id = device.get(CONF_AREA)
        if area_id is not None and area_id not in config[CONF_AREAS]:
            raise vol.Invalid(f"device {key}: area {area_id} is not in areas")
    return config


def entity_ids_distinct(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse two devices whose entities would share an ID.

    Device `pool` with the switch `switch_pump` and device `pool_switch` with
    the switch `pump` would both have pururu_pool_switch_switch_pump.
    """
    owners: dict[str, str] = {}  # object ID -> the device that has it
    for key, device in config[CONF_DEVICES].items():
        for name, entity_key, _ in entity_keys(device):
            identity = Device(
                key=key, name=device[CONF_NAME], namespace=builders()[name].namespace
            )
            object_id = identity.object_id(entity_key)
            if object_id in owners:
                raise vol.Invalid(
                    f"device {key}: {object_id} is already an entity of device "
                    f"{owners[object_id]}"
                )
            owners[object_id] = key
    return config


def _generated_ids(key: str, device: dict[str, Any]) -> Iterator[tuple[str, str, str]]:
    """(domain, ID, what) of every automation and script the device generates."""
    for reaction_key in device.get(CONF_REACTIONS, {}):
        yield (
            reactions.KIND.domain,
            reactions.automation_id(key, reaction_key),
            "reaction",
        )
    for _, feature, notification, _ in notifications.enabled(device):
        yield (
            notifications.KIND.domain,
            notifications.automation_id(key, feature.namespace, notification),
            "notification",
        )
    for program in device.get(CONF_PROGRAMS, {}):
        yield programs.KIND.domain, programs.script_id(key, program), "program"


def generated_ids_distinct(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse two automations, or two scripts, that would share an ID.

    Device `lights` with the reaction `b_reaction_c` and device `lights_reaction_b`
    with the reaction `c` would both have pururu_lights_reaction_b_reaction_c; a
    reaction's and a notification's may meet the same way.
    """
    owners: dict[
        tuple[str, str], tuple[str, str]
    ] = {}  # (domain, ID) -> (device, what)
    for key, device in config[CONF_DEVICES].items():
        for domain, unique_id, what in _generated_ids(key, device):
            if (owner := owners.get((domain, unique_id))) is not None:
                raise vol.Invalid(
                    f"device {key}: {domain}.{unique_id} is already a {owner[1]} "
                    f"of device {owner[0]}"
                )
            owners[domain, unique_id] = (key, what)
    return config


def reactions_resolved(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse a reaction's `device` that isn't a device, or its `when` that isn't that device's."""
    devices = config[CONF_DEVICES]
    for key, device in devices.items():
        for reaction_key, reaction in device.get(CONF_REACTIONS, {}).items():
            if "device" in reaction:
                _reaction_resolved(devices, key, reaction_key, reaction)
    return config


def _reaction_resolved(
    devices: dict[str, Any], key: str, reaction_key: str, reaction: dict[str, Any]
) -> None:
    """Refuse this reaction's `device` that isn't a device, or `when` it can't watch there.

    Naming its own device, it can't watch its own statistics either.
    """
    other = reaction["device"]
    where = f"device {key}: reactions: {reaction_key}"
    if other not in devices:
        raise vol.Invalid(f"{where}: device {other} is not in devices")
    if other == key and reaction["when"] in _own_statistics(reaction_key):
        raise vol.Invalid(f"{where}: {reaction['when']} is its own statistic")
    if reaction["when"] not in referable(other, devices[other]):
        raise vol.Invalid(
            f"{where}: {reaction['when']} is not an entity key of device {other}"
        )


def messages_sent(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse a message that goes nowhere, a reaction's or a notification's.

    Neither a notify of its own nor one in config.notify.
    """
    if config[CONF_CONFIG].get(CONF_NOTIFY):
        return config
    for key, device in config[CONF_DEVICES].items():
        for reaction_key, reaction in device.get(CONF_REACTIONS, {}).items():
            if CONF_MESSAGE in reaction and CONF_NOTIFY not in reaction:
                raise vol.Invalid(
                    f"device {key}: reactions: {reaction_key}: message needs notify, "
                    "here or in config.notify"
                )
        for name, _, notification, settings in notifications.enabled(device):
            if CONF_NOTIFY not in settings:
                raise vol.Invalid(
                    f"device {key}: {name}: notifications: {notification} needs "
                    "notify, here or in config.notify"
                )
    return config


def alert_lights_resolved(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse a group's light that isn't a device's, or an alert's group that isn't one."""
    devices = config[CONF_DEVICES]
    groups = config[CONF_CONFIG][CONF_ALERTS][CONF_LIGHTS][alert_lights.GROUPS]
    for group, members in groups.items():
        _alert_light_group_resolved(devices, group, members)
    for key, device in devices.items():
        for where, group in _alert_light_groups(device):
            if group in groups:
                continue
            if group == DEFAULT_ALERT_LIGHTS:
                raise vol.Invalid(
                    f"device {key}: {where}: there is no default group in "
                    "config.alerts.lights.groups"
                )
            raise vol.Invalid(
                f"device {key}: {where}: {group} is not a group of "
                "config.alerts.lights.groups"
            )
    return config


def _alert_light_group_resolved(
    devices: dict[str, Any], group: str, members: dict[str, list[str]]
) -> None:
    """Refuse a light of this group that isn't a device's."""
    where = f"config.alerts.lights.groups: {group}"
    for key, lights in members.items():
        if key not in devices:
            raise vol.Invalid(f"{where}: device {key} is not in devices")
        for light in lights:
            if light not in devices[key].get(CONF_LIGHTS, {}):
                raise vol.Invalid(f"{where}: device {key} has no light {light}")


def _alert_light_groups(device: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """(where, group) of each of the device's alerts with lights, hand-written or ready-made."""
    for alert_key, alert in device.get(CONF_ALERTS, {}).items():
        if (group := alert.get(CONF_LIGHTS)) is not None:
            yield f"{CONF_ALERTS}: {alert_key}", group
    for name, feature in FEATURES.items():
        if not feature.alerts or name not in device:
            continue
        for preset, settings in device[name].get(ALERTS_KEY, {}).items():
            if (group := settings.get(CONF_LIGHTS)) is not None:
                yield f"{name}: {ALERTS_KEY}: {preset}", group
