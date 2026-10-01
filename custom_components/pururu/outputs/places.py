"""Floors and areas configured in YAML, with the IDs their keys give them.

HA's registries take no ID: they make one from the name. A floor or area that
doesn't exist yet is created named after its key, so that the key is its ID,
then renamed. Whatever has a configured ID follows the configuration, whoever
created it; what the entry managed and the configuration dropped is deleted.
"""

from collections.abc import Callable, Iterator, Mapping
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

from ..const import CONF_ALIASES, CONF_AREAS, CONF_FLOOR, CONF_FLOORS, CONF_LEVEL
from ..core.feature import TEXT
from ..core.resolve import key_alone

_LOGGER = logging.getLogger(__name__)

_ALIASES = vol.All(cv.ensure_list, [cv.string])


def _level(value: Any) -> int | None:
    """A floor's level: an integer, or None to clear it; not a bool (`level: yes`)."""
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    raise vol.Invalid(f"expected an integer level, got {value!r}")


FLOOR_SCHEMA = vol.Schema(
    {
        # A blank name: HA would refuse it, or show nothing
        vol.Required(CONF_NAME): TEXT,
        # None clears it, as HA's own floor editor does (its hint says int only)
        vol.Optional(CONF_LEVEL, default=None): _level,
        vol.Optional(CONF_ICON): cv.icon,
        vol.Optional(CONF_ALIASES, default=[]): _ALIASES,
    }
)
AREA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): TEXT,
        vol.Optional(CONF_FLOOR): key_alone(CONF_FLOOR, CONF_FLOOR),
        vol.Optional(CONF_ICON): cv.icon,
        vol.Optional(CONF_ALIASES, default=[]): _ALIASES,
    }
)


def floors_exist(house: Mapping[str, Any], *_: Any) -> Iterator[vol.Invalid]:
    """Refuse an area on a floor the configuration doesn't declare (a schema check)."""
    for area_id, area in house[CONF_AREAS].items():
        floor_id = area.get(CONF_FLOOR)
        if floor_id is not None and floor_id not in house[CONF_FLOORS]:
            yield vol.Invalid(
                f"area {area_id}: floor {floor_id} is not in floors",
                path=[CONF_AREAS, area_id, CONF_FLOOR],
            )


@callback
def async_sync(
    hass: HomeAssistant,
    floors: Mapping[str, dict[str, Any]],
    areas: Mapping[str, dict[str, Any]],
    managed: Mapping[str, Any],
) -> dict[str, list[str]]:
    """Make the registries follow the configuration; the IDs managed from now on.

    Deletes first, so that a name a dropped floor or area had is free again. What
    HA refuses is logged: a new floor or area is left out, and so is a new area on
    a floor left out; one that exists stays as it is, and managed.
    """
    floor_registry = fr.async_get(hass)
    area_registry = ar.async_get(hass)
    for area_id in managed.get(CONF_AREAS, []):
        if area_id not in areas and area_registry.async_get_area(area_id):
            area_registry.async_delete(area_id)
    for floor_id in managed.get(CONF_FLOORS, []):
        if floor_id not in floors and floor_registry.async_get_floor(floor_id):
            floor_registry.async_delete(floor_id)
    for floor_id, config in floors.items():
        _floor(floor_registry, floor_id, config)
    for area_id, config in areas.items():
        floor_id = config.get(CONF_FLOOR)
        if floor_id is None or floor_registry.async_get_floor(floor_id):
            _area(area_registry, area_id, config)
        else:
            _LOGGER.error(
                "Area %s is not synced: its floor %s is not created", area_id, floor_id
            )
    return {
        CONF_FLOORS: [f for f in floors if floor_registry.async_get_floor(f)],
        CONF_AREAS: [a for a in areas if area_registry.async_get_area(a)],
    }


@callback
def async_remove(hass: HomeAssistant, managed: Mapping[str, Any]) -> None:
    """Delete every floor and area `managed` lists that still exists."""
    async_sync(hass, {}, {}, managed)


def _floor(registry: fr.FloorRegistry, floor_id: str, config: dict[str, Any]) -> None:
    """Create or update the floor as configured."""

    def update() -> None:
        registry.async_update(
            floor_id,
            name=config[CONF_NAME],
            level=config[CONF_LEVEL],
            icon=config.get(CONF_ICON),
            aliases=set(config[CONF_ALIASES]),
        )

    _follow(
        "Floor",
        floor_id,
        exists=registry.async_get_floor(floor_id) is not None,
        create=lambda name: registry.async_create(name).floor_id,
        delete=registry.async_delete,
        update=update,
    )


def _area(registry: ar.AreaRegistry, area_id: str, config: dict[str, Any]) -> None:
    """Create or update the area as configured."""

    def update() -> None:
        registry.async_update(
            area_id,
            name=config[CONF_NAME],
            floor_id=config.get(CONF_FLOOR),
            icon=config.get(CONF_ICON),
            aliases=set(config[CONF_ALIASES]),
        )

    _follow(
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
) -> None:
    """Create `place_id` if missing, then update it; logged if HA refuses.

    HA refuses a name another floor (or area) already has, whitespace and case
    aside: creating one named after the key, or renaming it. A new one it
    refuses is not kept.
    """
    if not exists:
        try:
            new_id = create(place_id)
        except ValueError as err:
            _LOGGER.error("%s %s is left out: %s", kind, place_id, err)
            return
        if new_id != place_id:  # can't happen for a free slug; never keep a stray
            delete(new_id)
            _LOGGER.error("%s %s is left out: HA gave it %s", kind, place_id, new_id)
            return
    try:
        update()
    except ValueError as err:
        if exists:
            _LOGGER.error("%s %s is not synced: %s", kind, place_id, err)
        else:
            delete(place_id)
            _LOGGER.error("%s %s is left out: %s", kind, place_id, err)
