"""What the features standing for real entities share: their configuration, and knowing pururu's own.

`switches` and `lights` give each key of their block an entity standing for one
real entity. Their entities differ by domain, each on its HA group entity; what
they share is here, as functions, not a base class.
"""

from collections.abc import Callable
from typing import Any

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, split_entity_id
from homeassistant.helpers import config_validation as cv, entity_registry as er

from ..const import DOMAIN, ENTITY_PREFIX


def real_entity(*domains: Platform) -> Callable[[Any], str]:
    """One entity ID of one of `domains`, not one of pururu's own.

    An entity standing for itself would call itself forever, and one standing
    for another pururu entity would stand for what that one already stands for.
    """

    def validate(value: Any) -> str:
        entity_id: str = cv.entity_id(value)
        domain, object_id = split_entity_id(entity_id)
        if domain not in domains:
            raise vol.Invalid(f"{entity_id} is not a {' or '.join(domains)}")
        if object_id.startswith(f"{ENTITY_PREFIX}_"):
            raise vol.Invalid(f"{entity_id} is a pururu {domain}: name the real one")
        return entity_id

    return validate


def schema(*domains: Platform) -> Callable[[Any], Any]:
    """A block of entity key -> the real entity it stands for and its name; at least one."""
    item = vol.Schema(
        {
            vol.Required("entity"): real_entity(*domains),
            # A blank name would show the entity as its device's name alone
            vol.Required("name"): vol.All(cv.string, vol.Strip, vol.Length(min=1)),
        }
    )
    # A schema of its own: ALLOW_EXTRA would let a key that isn't a slug through
    return vol.All(vol.Schema({cv.slug: item}), vol.Length(min=1))


def is_pururu(hass: HomeAssistant, entity_id: str) -> bool:
    """Whether `entity_id` is pururu's: renamed in the UI, it no longer says so."""
    registered = er.async_get(hass).async_get(entity_id)
    return registered is not None and registered.platform == DOMAIN
