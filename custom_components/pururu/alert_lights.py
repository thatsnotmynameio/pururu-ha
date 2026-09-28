"""Alert lights: the lights pururu's alerts borrow while they are on.

An alert with `lights` names a group of `config: alerts: lights: groups`.
While one of a light's alerts is on, the light shows the highest priority's
`turn_on`; once none is, `resolved`'s for its `for`, then it is turned off and
pururu_alert_lights_released says it is free. Only the light's turn_on and
turn_off are called: the light uses what it has.
"""

from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components.light import ATTR_COLOR_NAME, LIGHT_TURN_ON_SCHEMA
from homeassistant.helpers import config_validation as cv
from homeassistant.util.color import color_name_to_rgb

from .features.alerts import PRIORITIES

GROUPS = "groups"
TURN_ON = "turn_on"
REPEAT = "repeat"
FOR = "for"
# What a light shows between its last alert's end and its release
RESOLVED = "resolved"


def _known_colour(params: dict[str, Any]) -> dict[str, Any]:
    """Refuse a colour name HA doesn't know: every call would fail."""
    if (name := params.get(ATTR_COLOR_NAME)) is not None:
        try:
            color_name_to_rgb(name)
        except ValueError as err:
            raise vol.Invalid(
                f"{name} is not a colour name Home Assistant knows"
            ) from err
    return params


# light.turn_on's data under its own names; the light is the group's, never given here
TURN_ON_SCHEMA = vol.All(vol.Schema(LIGHT_TURN_ON_SCHEMA), _known_colour)
# A whole number of seconds, written {seconds: N}
SECONDS = vol.All(
    vol.Schema({vol.Required("seconds"): vol.All(int, vol.Range(min=1))}),
    lambda value: timedelta(seconds=value["seconds"]),
)


def _distinct(lights: list[str]) -> list[str]:
    if len(set(lights)) != len(lights):
        raise vol.Invalid("a light is listed twice")
    return lights


# Device key -> keys of that device's lights; __init__ checks them against the devices
GROUP = vol.All(
    vol.Schema({cv.slug: vol.All([cv.slug], vol.Length(min=1), _distinct)}),
    vol.Length(min=1),
)
PRIORITY = vol.Schema(
    {vol.Required(TURN_ON): TURN_ON_SCHEMA, vol.Optional(REPEAT): SECONDS}
)
RESOLVED_SCHEMA = vol.Schema(
    {vol.Required(TURN_ON): TURN_ON_SCHEMA, vol.Required(FOR): SECONDS}
)


def _breathe(colour: str) -> dict[str, Any]:
    """A priority's default: breathe in `colour`, sent again every 15 s (a one-shot effect)."""
    return {
        TURN_ON: {"color_name": colour, "brightness_pct": 100, "effect": "breathe"},
        REPEAT: {"seconds": 15},
    }


# The defaults as the user would write them: validated like what the user writes
DEFAULTS: dict[str, dict[str, Any]] = {
    "high": _breathe("red"),
    "medium": _breathe("orange"),
    "low": _breathe("blue"),
    RESOLVED: {
        TURN_ON: {"color_name": "green", "brightness_pct": 50},
        FOR: {"seconds": 120},
    },
}

# config: alerts: lights:; a priority written replaces its default whole
SCHEMA = vol.Schema(
    {
        vol.Optional(GROUPS, default=dict): vol.Schema({cv.slug: GROUP}),
        **{
            vol.Optional(priority, default=DEFAULTS[priority]): PRIORITY
            for priority in PRIORITIES
        },
        vol.Optional(RESOLVED, default=DEFAULTS[RESOLVED]): RESOLVED_SCHEMA,
    }
)
