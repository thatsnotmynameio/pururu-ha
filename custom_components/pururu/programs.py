"""Programs: sequences of actions on a device's own entities, as Home Assistant scripts.

A program is a method of its device: something starts it, and it turns the
device's own switches and lights on and off, with delays between. Its steps are
pururu's, translated to HA's script syntax in pururu/scripts/programs.yaml,
whose folder configuration.yaml includes (generated.py); HA runs it. No step
can reach outside the device.
"""

from collections.abc import Iterator, Mapping
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_NAME
from homeassistant.core import split_entity_id
from homeassistant.helpers import config_validation as cv

from .const import CONF_SCRIPTS, ENTITY_PREFIX
from .feature import qualified
from .generated import Kind, period

# The namespace of every program's script ID
NAMESPACE = "program"
DELAY = "delay"
# What a step can do to an entity; the device schema checks its feature takes it
ACTIONS = ("turn_on", "turn_off", "toggle")
KIND = Kind(
    domain="script",
    folder="pururu/scripts",
    file="pururu/scripts/programs.yaml",
    merge="named",
    issue="scripts_not_included",
    data_key=CONF_SCRIPTS,
    one="a script",
    plural="scripts",
    source="programs",
)

STEP = vol.Schema(
    {
        vol.Optional(DELAY): cv.positive_time_period,
        **{vol.Optional(action): cv.slug for action in ACTIONS},
    }
)


def _step(value: Any) -> dict[str, Any]:
    """One of delay, turn_on, turn_off, toggle, with its value: exactly one key."""
    step: dict[str, Any] = STEP(value)
    if len(step) != 1:
        raise vol.Invalid(f"a step is exactly one of {DELAY}, {', '.join(ACTIONS)}")
    return step


PROGRAM = vol.Schema(
    {
        # A blank name would show the program as its device's name alone
        vol.Required(CONF_NAME): vol.All(cv.string, vol.Strip, vol.Length(min=1)),
        vol.Required("sequence"): vol.All([_step], vol.Length(min=1)),
    }
)
# A schema of its own: ALLOW_EXTRA would let a key that isn't a slug through
SCHEMA = vol.All(vol.Schema({cv.slug: PROGRAM}), vol.Length(min=1))


def targets(program: Mapping[str, Any]) -> Iterator[tuple[str, str]]:
    """(action, entity key) of each step that acts on an entity, in order."""
    for step in program["sequence"]:
        yield from ((action, key) for action, key in step.items() if action != DELAY)


def script_id(device_key: str, program_key: str) -> str:
    """The script's object ID, and its unique ID: the pururu pattern."""
    return f"{ENTITY_PREFIX}_{device_key}_{qualified(NAMESPACE, program_key)}"


def _translated(
    step: Mapping[str, Any], entity_ids: Mapping[str, str]
) -> dict[str, Any]:
    """A step in HA's script syntax."""
    ((action, value),) = step.items()
    if action == DELAY:
        return {DELAY: period(value)}
    entity_id = entity_ids[value]
    return {
        "action": f"{split_entity_id(entity_id)[0]}.{action}",
        "target": {"entity_id": entity_id},
    }


def script(
    device_key: str,
    device_name: str,
    program_key: str,
    program: Mapping[str, Any],
    entity_ids: Mapping[str, str],
) -> dict[str, Any]:
    """The script of a program; `entity_ids` maps each entity key it acts on to its current ID.

    single: a start while it runs is ignored, and HA logs it.
    """
    return {
        "alias": f"{device_name} {program[CONF_NAME]}",
        "description": f"pururu: {device_key}, {program_key}",
        "mode": "single",
        "sequence": [_translated(step, entity_ids) for step in program["sequence"]],
    }
