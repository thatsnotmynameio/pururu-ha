"""The devices the entry built: each in its area, and nothing stale left."""

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)

from .const import CONF_AREA, CONF_DEVICES, DOMAIN
from .runtime import Built, PururuConfigEntry

_LOGGER = logging.getLogger(__name__)


def place(
    hass: HomeAssistant, entry: PururuConfigEntry, devices: dict[str, dict[str, Any]]
) -> None:
    """Put each created device in its area; an area HA refused is logged.

    The configuration wins over an area picked in the UI; a device without
    `area`, or whose area is not created, keeps the one it has.
    """
    areas = ar.async_get(hass)
    registry = dr.async_get(hass)
    for key, config in devices.items():
        if (area_id := config.get(CONF_AREA)) is None:
            continue
        device = registry.async_get_device_by_identifier((DOMAIN, key), entry.entry_id)
        if device is None:  # none of its entities is created
            continue
        if areas.async_get_area(area_id) is None:
            _LOGGER.error(
                "Device %s is not placed: its area %s is not created", key, area_id
            )
        elif device.area_id != area_id:
            registry.async_update_device(device.id, area_id=area_id)


def remove_stale(hass: HomeAssistant, entry: PururuConfigEntry, keys: set[str]) -> None:
    """Remove what the entry has and the configuration no longer creates."""
    registry = er.async_get(hass)
    # With its platform: an entity key that moved to another platform keeps its unique ID
    wanted = {
        (platform, entity.unique_id)
        for platform, entities in entry.runtime_data.items()
        for entity in entities
    }
    for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (registered.domain, registered.unique_id) not in wanted:
            registry.async_remove(registered.entity_id)
    devices = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        if not any(
            domain == DOMAIN and key in keys for domain, key in device.identifiers
        ):
            devices.async_remove_device(device.id)


async def async_step(
    hass: HomeAssistant, entry: PururuConfigEntry, built: Built
) -> frozenset[str]:
    """Put each device in its area, then remove what the configuration no longer builds."""
    devices = built.house.get(CONF_DEVICES, {})
    place(hass, entry, devices)
    remove_stale(hass, entry, set(devices))
    return frozenset()
