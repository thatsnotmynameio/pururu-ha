"""The pururu: block's schema: each device, then the rules over the whole house."""

from collections.abc import Callable, Iterable, Mapping
from functools import partial
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_NAME
from homeassistant.helpers import config_validation as cv

from ..aspects import alerts
from ..const import (
    CONF_ALERTS,
    CONF_AREA,
    CONF_AREAS,
    CONF_CONFIG,
    CONF_DEVICES,
    CONF_FLOORS,
    CONF_LIGHTS,
    CONF_NOTIFY,
    DOMAIN,
)
from ..core import messages
from ..core.feature import Feature
from ..core.resolve import Index
from ..device_keys import programs, reactions
from ..features import FEATURES
from ..outputs import alert_lights, events, places
from . import catalogue, checks


def _device(value: Any) -> dict[str, Any]:
    """A device: a name, maybe an area, at least one feature.

    Each builder's block goes through catalogue.mount, with the aspects it
    offers. What its blocks refer to is checked over the whole house (CHECKS).
    """
    schema: dict[Any, Any] = {
        vol.Required(CONF_NAME): cv.string,
        vol.Optional(CONF_AREA): cv.slug,
        **{
            vol.Optional(name): partial(catalogue.mount, builder, name)
            for name, builder in catalogue.builders().items()
        },
    }
    device: dict[str, Any] = vol.Schema(schema)(value)
    if not any(name in device for name in FEATURES):
        raise vol.Invalid(
            f"a device needs at least one feature ({', '.join(FEATURES)})"
        )
    return device


# The rules over the whole house, each in its owner's module: each gets the
# validated block, the index of what each device can create and the builders,
# and yields each refusal with a path (vol.Invalid(..., path=[devices, key, ...]))
type Check = Callable[
    [Mapping[str, Any], Index, Mapping[str, Feature]], Iterable[vol.Invalid]
]
CHECKS: tuple[Check, ...] = (
    checks.references,
    alerts.check,
    checks.real_entities_distinct,
    reactions.check,
    programs.check,
    places.floors_exist,
    checks.areas_exist,
    checks.generated_ids_distinct,
    checks.keys_distinct,
    checks.entity_ids_distinct,
    alert_lights.check,
    checks.messages_sent,
)


def _checked(house: dict[str, Any]) -> dict[str, Any]:
    """The house, once every check passes over one index of it; every refusal told at once."""
    builders = catalogue.builders()
    index = catalogue.index(house[CONF_DEVICES])
    if refused := [
        error for check in CHECKS for error in check(house, index, builders)
    ]:
        raise vol.MultipleInvalid(refused)
    return house


# The features are read when a configuration is validated, not at import
CONFIG_SCHEMA = vol.Schema(
    {
        # A schema of its own: ALLOW_EXTRA would let a typo (`floor:`) through,
        # and so delete every floor the entry manages
        DOMAIN: vol.All(
            vol.Schema(
                {
                    # Schemas of their own: ALLOW_EXTRA would skip a key that isn't a slug
                    vol.Optional(CONF_FLOORS, default={}): vol.Schema(
                        {cv.slug: places.FLOOR_SCHEMA}
                    ),
                    vol.Optional(CONF_AREAS, default={}): vol.Schema(
                        {cv.slug: places.AREA_SCHEMA}
                    ),
                    vol.Optional(CONF_DEVICES, default={}): {cv.slug: _device},
                    vol.Optional(events.CONF_EVENTS, default=[]): events.SCHEMA,
                    # Settings of the whole house; schemas of their own, so a typo is refused
                    vol.Optional(CONF_CONFIG, default={}): vol.Schema(
                        {
                            # Where every message goes, unless its own notify says
                            vol.Optional(CONF_NOTIFY): messages.TARGETS,
                            vol.Optional(CONF_ALERTS, default={}): vol.Schema(
                                {
                                    vol.Optional(
                                        CONF_LIGHTS, default={}
                                    ): alert_lights.SCHEMA
                                }
                            ),
                        }
                    ),
                }
            ),
            _checked,
        )
    },
    extra=vol.ALLOW_EXTRA,
)
