"""The pururu: block's schema: each device, then the rules over the whole house."""

from functools import partial
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_NAME
from homeassistant.helpers import config_validation as cv

from ..const import (
    CONF_ALERTS,
    CONF_AREA,
    CONF_AREAS,
    CONF_CONFIG,
    CONF_DEVICES,
    CONF_FLOORS,
    CONF_LIGHTS,
    CONF_NOTIFICATIONS,
    CONF_NOTIFY,
    CONF_PROGRAMS,
    CONF_REACTIONS,
    DOMAIN,
)
from ..core import messages
from ..core.feature import Feature
from ..device_keys import notifications, programs, reactions
from ..features import FEATURES, presets
from ..outputs import alert_lights, events, places
from .checks import (
    alert_lights_resolved,
    areas_exist,
    capabilities_provided,
    entity_ids_distinct,
    generated_ids_distinct,
    messages_sent,
    no_alert_watches_an_alert,
    programs_on_this_device,
    reactions_on_this_device,
    reactions_resolved,
    real_entities_distinct,
    references_resolved,
)


def _device(value: Any) -> dict[str, Any]:
    """A device: a name, maybe an area, at least one feature, every reference resolved.

    Every <capability>_from names a feature of this device that provides it,
    every entity key a feature refers to is another feature's, a program's step
    acts on another feature's entity key that takes the action, and a real
    entity is in one configured feature of the device at most.
    """
    schema: dict[Any, Any] = {
        vol.Required(CONF_NAME): cv.string,
        vol.Optional(CONF_AREA): cv.slug,
        vol.Optional(CONF_REACTIONS): reactions.SCHEMA,
        vol.Optional(CONF_PROGRAMS): programs.SCHEMA,
        **{
            vol.Optional(name): partial(_feature_block, feature, name)
            for name, feature in FEATURES.items()
        },
    }
    device: dict[str, Any] = vol.Schema(schema)(value)
    names = [name for name in FEATURES if name in device]
    if not names:
        raise vol.Invalid(
            f"a device needs at least one feature ({', '.join(FEATURES)})"
        )
    capabilities_provided(device, names)
    references_resolved(device, names)
    no_alert_watches_an_alert(device, names)
    real_entities_distinct(device, names)
    reactions_on_this_device(device)
    programs_on_this_device(device)
    return device


def _feature_block(feature: Feature, key: str, value: Any) -> Any:
    """A feature's block, `key` in the device: its ready-made notifications (notifications.py), the rest as presets.validate says.

    Only a feature offering them has them: a configured feature (alerts,
    switches) may have an item keyed `notifications`.
    """
    if (
        not feature.notifications
        or not isinstance(value, dict)
        or CONF_NOTIFICATIONS not in value
    ):
        return presets.validate(feature, value, key)
    rest = {each: block for each, block in value.items() if each != CONF_NOTIFICATIONS}
    enabled = vol.Schema(
        {CONF_NOTIFICATIONS: notifications.schema(key, feature.notifications)}
    )({CONF_NOTIFICATIONS: value[CONF_NOTIFICATIONS]})
    return {**presets.validate(feature, rest, key), **enabled}


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
            places.floors_exist,
            areas_exist,
            generated_ids_distinct,
            entity_ids_distinct,
            reactions_resolved,
            alert_lights_resolved,
            messages_sent,
        )
    },
    extra=vol.ALLOW_EXTRA,
)
