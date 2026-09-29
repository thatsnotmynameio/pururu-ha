"""Ready-made notifications: what a device's features offer to tell, as automations pururu generates.

A device's `notifications` enables them, by feature and name: each is a
Happening of the feature (roles.Happenings), told once through HA's notify
actions (messages.py). Each becomes an automation in
pururu/automations/notifications.yaml, next to the reactions' in the folder
configuration.yaml includes (generated.py).
"""

from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
import logging
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from ..const import CONF_MESSAGE, CONF_NOTIFICATIONS, CONF_NOTIFY, ENTITY_PREFIX
from ..core import generated, messages
from ..core.feature import TEXT, Device, Feature, Happening, happenings_of, qualified
from ..features import FEATURES
from . import reactions

_LOGGER = logging.getLogger(__name__)

# The namespace of a notification's automation ID, inside its feature's
NAMESPACE = "notification"
KIND = generated.Kind(
    domain="automation",
    folder="pururu/automations",
    file="pururu/automations/notifications.yaml",
    merge="list",
    issue="notifications_not_included",
    data_key=CONF_NOTIFICATIONS,
    one="an automation",
    plural="automations",
    source="notifications",
)
# What one takes: its text, where it goes; a schema of its own, so unknown keys are refused
SETTINGS = vol.Schema(
    {vol.Optional(CONF_MESSAGE): TEXT, vol.Optional(CONF_NOTIFY): messages.TARGETS}
)


def schema(
    key: str, offered: Mapping[str, Happening]
) -> Callable[[Any], dict[str, dict[str, Any]]]:
    """A feature's `notifications`: name -> settings, null every default; `key` is the feature's in the device.

    Each name validated under itself, so an error's path ends at the setting.
    """
    names = ", ".join(offered)

    def validate(value: Any) -> dict[str, dict[str, Any]]:
        # A schema of its own: ALLOW_EXTRA would let a key that isn't a slug through
        given = vol.All(vol.Schema({cv.slug: vol.Any(None, dict)}), vol.Length(min=1))(
            value
        )
        enabled: dict[str, dict[str, Any]] = {}
        for name, settings in given.items():
            if name not in offered:
                raise vol.Invalid(
                    f"{name} is not a ready-made notification of {key}: {names}",
                    path=[name],
                )
            enabled[name] = vol.Schema({name: SETTINGS})({name: settings or {}})[name]
        return enabled

    return validate


def enabled(
    device: Mapping[str, Any],
) -> Iterator[tuple[str, Feature, str, Mapping[str, Any]]]:
    """(feature key, feature, name, settings) of each ready-made notification the device's blocks enable.

    Only a feature offering them has them: a configured feature (alerts,
    switches) may have an item keyed `notifications`.
    """
    for key, feature in FEATURES.items():
        if not happenings_of(feature) or key not in device:
            continue
        for name, settings in device[key].get(CONF_NOTIFICATIONS, {}).items():
            yield key, feature, name, settings


def automation_id(device_key: str, namespace: str, name: str) -> str:
    """The automation's ID, and the object ID of its entity ID: the pururu pattern."""
    return f"{ENTITY_PREFIX}_{device_key}_{qualified(namespace, qualified(NAMESPACE, name))}"


def automation(
    device: Device,
    name: str,
    happening: Happening,
    entity_id: str,
    *,
    alias: str,
    message: str,
    notify: Sequence[str],
) -> dict[str, Any]:
    """The automation of notification `name` of `device`'s feature; `entity_id` is what it watches."""
    trigger: dict[str, Any] = {"to": happening.to}
    if happening.from_ is not None:
        trigger["from"] = happening.from_
    return {
        "id": automation_id(device.key, device.namespace, name),
        "alias": f"{device.name} {alias}",
        "description": f"pururu: {device.key}, {device.namespace} {NAMESPACE} {name}",
        "triggers": reactions.triggers(trigger, entity_id),
        "actions": messages.actions(notify, device.name, message),
    }


def plan(
    hass: HomeAssistant,
    devices: Mapping[str, Mapping[str, Any]],
    created: Collection[str],
    texts: Mapping[str, str],
    notify: Sequence[str],
) -> generated.Planned:
    """An automation per enabled notification of every device; one on an entity not created is logged.

    `texts` are the common texts in HA's language (its name, its default
    message); `notify` is config's, where one without its own goes.
    """
    found: list[generated.Item] = []
    for key, config in devices.items():
        for _, feature, notification, settings in enabled(config):
            device = Device(
                key=key, name=config[CONF_NAME], namespace=feature.namespace
            )
            happening = happenings_of(feature)[notification]
            platform = feature.entity_keys[happening.watches]
            unique_id = automation_id(key, feature.namespace, notification)
            if device.object_id(happening.watches) not in created:
                _LOGGER.error(
                    "automation.%s follows %s, which is not created; not generating it",
                    unique_id,
                    device.entity_id(platform, happening.watches),
                )
                continue
            text = device.qualified(qualified(NAMESPACE, notification))
            found.append(
                generated.Item(
                    unique_id=unique_id,
                    config=automation(
                        device,
                        notification,
                        happening,
                        device.current_entity_id(hass, platform, happening.watches),
                        alias=texts[f"{text}_name"],
                        message=settings.get(CONF_MESSAGE, texts[f"{text}_message"]),
                        notify=settings.get(CONF_NOTIFY, notify),
                    ),
                )
            )
    return generated.Planned(found)
