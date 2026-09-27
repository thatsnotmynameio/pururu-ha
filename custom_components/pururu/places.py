"""Floors and areas configured in YAML, with the IDs their keys give them.

HA's registries take no ID: they make one from the name. A floor or area that
doesn't exist yet is created named after its key, so that the key is its ID,
then renamed. Whatever has a configured ID follows the configuration, whoever
created it; what the entry managed and the configuration dropped is deleted.
"""

from collections.abc import Callable, Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_ICON, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    config_validation as cv,
    floor_registry as fr,
)

from .const import CONF_ALIASES, CONF_AREAS, CONF_FLOOR, CONF_FLOORS, CONF_LEVEL

_LOGGER = logging.getLogger(__name__)

_ALIASES = vol.All(cv.ensure_list, [cv.string])

FLOOR_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        # None clears it, as HA's own floor editor does (its hint says int only)
        vol.Optional(CONF_LEVEL, default=None): vol.Any(int, None),
        vol.Optional(CONF_ICON): cv.icon,
        vol.Optional(CONF_ALIASES, default=[]): _ALIASES,
    }
)
AREA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Optional(CONF_FLOOR): cv.slug,
        vol.Optional(CONF_ICON): cv.icon,
        vol.Optional(CONF_ALIASES, default=[]): _ALIASES,
    }
)


def floors_exist(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse an area on a floor the configuration doesn't declare."""
    for area_id, area in config[CONF_AREAS].items():
        floor_id = area.get(CONF_FLOOR)
        if floor_id is not None and floor_id not in config[CONF_FLOORS]:
            raise vol.Invalid(f"area {area_id}: floor {floor_id} is not in floors")
    return config


@callback
def async_sync(
    hass: HomeAssistant,
    floors: Mapping[str, dict[str, Any]],
    areas: Mapping[str, dict[str, Any]],
    managed: Mapping[str, Any],
) -> dict[str, list[str]]:
    """Make the registries follow the configuration; the IDs managed from now on.

    Deletes first, so that a name a dropped floor or area had is free again. A
    floor or area HA refuses is logged and left out, and so is an area on such
    a floor.
    """
    floor_registry = fr.async_get(hass)
    area_registry = ar.async_get(hass)
    for area_id in managed.get(CONF_AREAS, []):
        if area_id not in areas and area_registry.async_get_area(area_id):
            area_registry.async_delete(area_id)
    for floor_id in managed.get(CONF_FLOORS, []):
        if floor_id not in floors and floor_registry.async_get_floor(floor_id):
            floor_registry.async_delete(floor_id)
    kept_floors = [
        floor_id
        for floor_id, config in floors.items()
        if _floor(floor_registry, floor_id, config)
    ]
    kept_areas: list[str] = []
    for area_id, config in areas.items():
        floor_id = config.get(CONF_FLOOR)
        if floor_id is not None and floor_id not in kept_floors:
            _LOGGER.error(
                "Area %s is left out: its floor %s is not created", area_id, floor_id
            )
        elif _area(area_registry, area_id, config):
            kept_areas.append(area_id)
    return {CONF_FLOORS: kept_floors, CONF_AREAS: kept_areas}


@callback
def async_remove(hass: HomeAssistant, managed: Mapping[str, Any]) -> None:
    """Delete every floor and area `managed` lists that still exists."""
    async_sync(hass, {}, {}, managed)


def _floor(registry: fr.FloorRegistry, floor_id: str, config: dict[str, Any]) -> bool:
    """Whether the floor exists now, as configured."""

    def update() -> None:
        registry.async_update(
            floor_id,
            name=config[CONF_NAME],
            level=config[CONF_LEVEL],
            icon=config.get(CONF_ICON),
            aliases=set(config[CONF_ALIASES]),
        )

    return _follow(
        "Floor",
        floor_id,
        exists=registry.async_get_floor(floor_id) is not None,
        create=lambda name: registry.async_create(name).floor_id,
        delete=registry.async_delete,
        update=update,
    )


def _area(registry: ar.AreaRegistry, area_id: str, config: dict[str, Any]) -> bool:
    """Whether the area exists now, as configured."""

    def update() -> None:
        registry.async_update(
            area_id,
            name=config[CONF_NAME],
            floor_id=config.get(CONF_FLOOR),
            icon=config.get(CONF_ICON),
            aliases=set(config[CONF_ALIASES]),
        )

    return _follow(
        "Area",
        area_id,
        exists=registry.async_get_area(area_id) is not None,
        create=lambda name: registry.async_create(name).id,
        delete=registry.async_delete,
        update=update,
    )


def _follow(
    kind: str,
    place_id: str,
    *,
    exists: bool,
    create: Callable[[str], str],
    delete: Callable[[str], None],
    update: Callable[[], None],
) -> bool:
    """Create `place_id` if missing, then update it; False, logged, if HA refuses.

    HA refuses a name another floor (or area) already has, whitespace and case
    aside: creating one named after the key, or renaming it.
    """
    if not exists:
        try:
            new_id = create(place_id)
        except ValueError as err:
            return _left_out(kind, place_id, err)
        if new_id != place_id:  # can't happen for a free slug; never keep a stray
            delete(new_id)
            return _left_out(kind, place_id, f"HA gave it the ID {new_id}")
    try:
        update()
    except ValueError as err:
        if not exists:
            delete(place_id)
        return _left_out(kind, place_id, err)
    return True


def _left_out(kind: str, place_id: str, reason: object) -> bool:
    """Log why a floor or area is not created; False."""
    _LOGGER.error("%s %s is left out: %s", kind, place_id, reason)
    return False
