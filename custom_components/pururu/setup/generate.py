"""The scripts and automations the entry generates: what each holds, and what it watches."""

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import CONF_CONFIG, CONF_DEVICES, CONF_NOTIFY
from ..core import generated
from ..core.roles import Generates
from ..core.runtime import Built, PururuConfigEntry
from ..device_keys import notifications, programs, reactions
from . import catalogue

_LOGGER = logging.getLogger(__name__)


def owned(
    hass: HomeAssistant, entry: PururuConfigEntry, devices: dict[str, dict[str, Any]]
) -> dict[str, str]:
    """The current entity IDs of the scripts and automations the entry generates, by ID."""
    items = watched_items(devices)
    return {
        unique_id: entity_id
        for kind in (programs.KIND, reactions.KIND)
        for unique_id, entity_id in generated.owned(
            hass,
            entry,
            kind,
            (unique_id for domain, unique_id in items if domain == kind.domain),
        ).items()
    }


def watched_items(devices: dict[str, dict[str, Any]]) -> set[tuple[str, str]]:
    """(domain, ID) of every script and automation the device keys generate.

    Renamed, what watches it follows: a reaction's action, the statistics.
    """
    return {
        generated_item
        for key, config in devices.items()
        for name, feature in catalogue.builders().items()
        if name in config and (generates := feature.role(Generates)) is not None
        for generated_item in generates.ids(key, config[name])
    }


async def async_step(
    hass: HomeAssistant, entry: PururuConfigEntry, built: Built, targets: set[str]
) -> None:
    """The programs' scripts, then the reactions' and the ready-made notifications' automations.

    The scripts come first: a reaction starts one. Adds the entity IDs the
    generated scripts act on to `targets`: disabling one rebuilds the entry.
    """
    devices = built.house.get(CONF_DEVICES, {})
    index = built.index
    scripts = programs.plan(hass, devices, index, built.created)
    targets.update(scripts.targets)
    generated_scripts = await generated.async_sync(
        hass, entry, programs.KIND, scripts.items, scripts.held
    )
    # Where a message goes without a notify of its own
    notify = built.house.get(CONF_CONFIG, {}).get(CONF_NOTIFY, [])
    automations = reactions.plan(
        hass,
        devices,
        index,
        built.created,
        generated_scripts,
        scripts.held,
        notify,
    )
    await generated.async_sync(
        hass, entry, reactions.KIND, automations.items, automations.held
    )
    notified = notifications.plan(
        hass, built.builders, devices, built.created, built.texts, notify
    )
    await generated.async_sync(hass, entry, notifications.KIND, notified.items)
