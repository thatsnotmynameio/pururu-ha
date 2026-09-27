"""The modes of an appliance: kinds of cycle, each a band of a sensor's value with its own delays.

A cycle is of one mode: leaving the mode's band ends it, another mode starting
ends it too. A mode cycle runs only inside the appliance's (`cycle_from`).
"""

from collections.abc import Mapping
from itertools import pairwise
import math
from typing import Any

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from ...entity import PururuEntity
from ...feature import TEXT, Device, Feature, Item, bounded, finite_float
from ..cycle.statistics import PERIOD_LIST
from .current import IDLE, Current, Mode
from .last import Last


def _not_idle(modes: dict[str, Any]) -> dict[str, Any]:
    if IDLE in modes:
        raise vol.Invalid(f"{IDLE} is the state with no mode: name the mode otherwise")
    return modes


def _apart(modes: dict[str, Any]) -> dict[str, Any]:
    """Refuse two modes whose bands overlap: a reading is in one mode's band at most.

    Sorted by their lower bound, two bands overlap only if two neighbours do.
    """
    spans = sorted(
        (mode.get("above", -math.inf), mode.get("below", math.inf), slug)
        for slug, mode in modes.items()
    )
    for (_, below, first), (above, _, second) in pairwise(spans):
        if above < below:
            raise vol.Invalid(f"the bands of {first} and {second} overlap")
    return modes


def _energy_counted(config: dict[str, Any]) -> dict[str, Any]:
    if config["statistics"]["energy"] and "energy" not in config:
        raise vol.Invalid("statistics.energy needs energy")
    return config


MODE = vol.All(
    vol.Schema(
        {
            vol.Required("name"): TEXT,
            vol.Optional("above"): finite_float,
            vol.Optional("below"): finite_float,
            vol.Required("on_delay"): cv.positive_time_period,
            vol.Required("off_delay"): cv.positive_time_period,
        }
    ),
    bounded("mode"),
)
SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("cycle_from"): cv.slug,
            vol.Required("sensor"): cv.entity_id,
            vol.Optional("energy"): cv.entity_id,
            # A schema of its own: ALLOW_EXTRA would let a key that isn't a slug through
            vol.Required("modes"): vol.All(
                vol.Schema({cv.slug: MODE}), vol.Length(min=1), _not_idle, _apart
            ),
            vol.Optional("statistics", default={}): vol.Schema(
                {
                    vol.Optional("runtime", default=[]): PERIOD_LIST,
                    vol.Optional("cycles", default=[]): PERIOD_LIST,
                    vol.Optional("energy", default=[]): PERIOD_LIST,
                }
            ),
        }
    ),
    _energy_counted,
)


def modes_of(config: dict[str, Any]) -> tuple[Mode, ...]:
    """The modes of a validated block, in its order."""
    return tuple(
        Mode(
            item=Item(slug=slug, name=mode["name"]),
            above=mode.get("above"),
            below=mode.get("below"),
            on_delay=mode["on_delay"],
            off_delay=mode["off_delay"],
        )
        for slug, mode in config["modes"].items()
    )


def build(
    hass: HomeAssistant,
    device: Device,
    config: dict[str, Any],
    inputs: Mapping[str, str],
) -> list[PururuEntity]:
    """The running mode and the last one."""
    modes = modes_of(config)
    return [
        Current(
            device,
            cycle=inputs["cycle"],
            sensor=config["sensor"],
            energy=config.get("energy"),
            modes=modes,
        ),
        Last(device, tuple(mode.item for mode in modes)),
    ]


MODES = Feature(
    schema=SCHEMA,
    entity_keys={"current": Platform.SENSOR, "last": Platform.SENSOR},
    build=build,
    example={
        "cycle_from": "appliance",
        "sensor": "sensor.demo_plug_power",
        "modes": {
            "cooling": {
                "name": "Cooling",
                "above": 40,
                "on_delay": {"seconds": 30},
                "off_delay": {"seconds": 30},
            }
        },
    },
    namespace="mode",
    requires=("cycle",),
)
