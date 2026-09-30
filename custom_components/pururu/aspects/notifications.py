"""Ready-made notifications: what a device's features offer to tell, as automations pururu generates.

A feature offers them (roles.Happenings); `ASPECT` mounts its block's
`notifications`, which enables them by name: each is a Happening of the
feature, told once through HA's notify actions (messages.py). It builds no
entity: each becomes an automation in pururu/automations/automations.yaml,
after the reactions', in the folder configuration.yaml includes
(generated.AUTOMATIONS).
"""

from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
import logging
from typing import Any, Literal

import voluptuous as vol

from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from ..const import CONF_MESSAGE, CONF_NOTIFICATIONS, CONF_NOTIFY, ENTITY_PREFIX
from ..core import generated, messages, vocabulary
from ..core.entity import PururuEntity
from ..core.feature import (
    TEXT,
    Aspect,
    Device,
    Feature,
    Happening,
    happenings_of,
    qualified,
)

_LOGGER = logging.getLogger(__name__)

# The namespace of a notification's automation ID, inside its feature's
NAMESPACE = "notification"
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
    device: Mapping[str, Any], builders: Mapping[str, Feature]
) -> Iterator[tuple[str, Feature, str, Mapping[str, Any]]]:
    """(feature key, feature, name, settings) of each ready-made notification the device's blocks enable.

    Only a feature offering them has them: a configured builder (switches,
    lights, the `alerts` device key) may have an item keyed `notifications`.
    """
    for key, feature in builders.items():
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
        "triggers": [vocabulary.trigger(trigger, entity_id)],
        "actions": messages.actions(notify, device.name, message),
    }


def plan(
    hass: HomeAssistant,
    builders: Mapping[str, Feature],
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
        for _, feature, notification, settings in enabled(config, builders):
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


def _happenings(builder: Feature) -> Mapping[str, Happening]:
    """The builder's ready-made notifications: it offers the aspect only with at least one."""
    happenings = happenings_of(builder)
    assert happenings  # ASPECT.offered checked there is at least one
    return happenings


def _schema(builder: Feature, name: str) -> Callable[[Any], dict[str, dict[str, Any]]]:
    """The block's `notifications`, for this builder's; its refusals name `name`, the builder's key in the device."""
    return schema(name, _happenings(builder))


def _keys(*_: Any) -> dict[str, Platform]:
    """No entity key: each enabled notification is an automation (plan)."""
    return {}


def _example(builder: Feature) -> dict[str, None]:
    """The first ready-made notification, with its default text."""
    return {next(iter(_happenings(builder))): None}


def _placed(*_: Any) -> Literal["block"]:
    """`notifications:` sits in the block, for every builder offering it."""
    return "block"


def _build(*_: Any) -> list[PururuEntity]:
    """No entity: plan generates each enabled notification's automation."""
    return []


ASPECT = Aspect(
    key=CONF_NOTIFICATIONS,
    # At least one ready-made notification (happenings_of), as the alerts aspect's presets_of
    offered=lambda builder: bool(happenings_of(builder)),
    schema=_schema,
    keys=_keys,
    # Never asked, as it adds no key: under the builder's namespace, as a ready-made alert's
    named=lambda builder, key: qualified(builder.namespace, key),
    example=_example,
    placed=_placed,
    build=_build,
    # Absent: none enabled; an explicit empty `notifications` is still refused.
    # No check: `notify` is checks.messages_sent's rule, over the whole house
    mount_absent=False,
)
