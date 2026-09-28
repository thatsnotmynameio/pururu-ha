"""Reactions: what a device listens to, as Home Assistant automations pururu generates.

A reaction is one source (an entity of a device, a real entity, a time of day,
the sun) and, for an entity, a condition. Each becomes an automation in
pururu/automations/reactions.yaml, whose folder configuration.yaml includes
(generated.py). It starts one of its device's programs (then), or does nothing:
it fires, and its trace shows when and why.
"""

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_NAME, STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import config_validation as cv

from .const import CONF_AUTOMATIONS, ENTITY_PREFIX
from .feature import TEXT, finite_float, qualified, state_text
from .generated import Kind, period

# The namespace of every reaction's automation ID
NAMESPACE = "reaction"
SOURCES = ("when", "entity", "at", "sun")
# Keys that only a reaction on an entity's state takes
STATE_KEYS = ("to", "from", "above", "below", "for")
KIND = Kind(
    domain="automation",
    folder="pururu/automations",
    file="pururu/automations/reactions.yaml",
    merge="list",
    issue="automations_not_included",
    data_key=CONF_AUTOMATIONS,
    one="an automation",
    plural="automations",
    source="reactions",
)


def _consistent(reaction: dict[str, Any]) -> dict[str, Any]:
    """One source, and the keys that go with it."""
    sources = [key for key in SOURCES if key in reaction]
    if len(sources) != 1:
        raise vol.Invalid("a reaction needs one source: when, entity, at or sun")
    if "device" in reaction and "when" not in reaction:
        raise vol.Invalid("a reaction's device goes with when")
    if "offset" in reaction and "sun" not in reaction:
        raise vol.Invalid("a reaction's offset goes with sun")
    if sources[0] in ("at", "sun"):
        if any(key in reaction for key in STATE_KEYS):
            raise vol.Invalid(
                "a reaction on at or sun takes no to, from, above, below or for"
            )
        return reaction
    if ("to" in reaction) == ("above" in reaction or "below" in reaction):
        raise vol.Invalid(
            "a reaction on a state needs to, or above and/or below, not both"
        )
    if "from" in reaction and "to" not in reaction:
        raise vol.Invalid("a reaction's from goes with to")
    if (
        "above" in reaction
        and "below" in reaction
        and reaction["above"] >= reaction["below"]
    ):
        raise vol.Invalid("a reaction's above must be lower than its below")
    return reaction


REACTION = vol.All(
    vol.Schema(
        {
            # A blank name would show the automation as its device's name alone
            vol.Required(CONF_NAME): TEXT,
            vol.Optional("when"): cv.slug,
            vol.Optional("device"): cv.slug,
            vol.Optional("entity"): cv.entity_id,
            vol.Optional("to"): state_text,
            vol.Optional("from"): state_text,
            vol.Optional("above"): finite_float,
            vol.Optional("below"): finite_float,
            vol.Optional("for"): cv.positive_time_period,
            vol.Optional("at"): cv.time,
            vol.Optional("sun"): vol.In(("sunrise", "sunset")),
            vol.Optional("offset"): cv.time_period,
            # A program of this device, started when the reaction fires
            vol.Optional("then"): cv.slug,
        }
    ),
    _consistent,
)
# A schema of its own: ALLOW_EXTRA would let a key that isn't a slug through
SCHEMA = vol.All(vol.Schema({cv.slug: REACTION}), vol.Length(min=1))


def automation_id(device_key: str, reaction_key: str) -> str:
    """The automation's ID, and the object ID of its entity ID: the pururu pattern."""
    return f"{ENTITY_PREFIX}_{device_key}_{qualified(NAMESPACE, reaction_key)}"


def triggers(
    reaction: Mapping[str, Any], entity_id: str | None
) -> list[dict[str, Any]]:
    """The HA triggers of a validated reaction; `entity_id` is the entity it watches.

    With `to` and no `from`, a state coming back from no reading doesn't fire:
    a plug reconnecting (unavailable → off) is no "turned off".
    """
    if "at" in reaction:
        return [{"trigger": "time", "at": reaction["at"].isoformat()}]
    if "sun" in reaction:
        sun: dict[str, Any] = {"trigger": "sun", "event": reaction["sun"]}
        if "offset" in reaction:
            sun["offset"] = period(reaction["offset"])
        return [sun]
    trigger: dict[str, Any]
    if "to" in reaction:
        trigger = {"trigger": "state", "entity_id": entity_id}
        if "from" in reaction:
            trigger["from"] = reaction["from"]
        else:
            trigger["not_from"] = [STATE_UNAVAILABLE, STATE_UNKNOWN]
        trigger["to"] = reaction["to"]
    else:
        trigger = {"trigger": "numeric_state", "entity_id": entity_id}
        for key in ("above", "below"):
            if key in reaction:
                trigger[key] = reaction[key]
    if "for" in reaction:
        trigger["for"] = period(reaction["for"])
    return [trigger]


def actions(script: str | None) -> list[dict[str, Any]]:
    """Start the program's script unless it runs; nothing without one.

    The check is an action, not a condition: HA counts a trigger only once its
    conditions pass, and a trigger skipped because the program runs still is one.
    """
    if script is None:
        return []
    return [
        {
            "if": [{"condition": "state", "entity_id": script, "state": STATE_OFF}],
            "then": [{"action": "script.turn_on", "target": {"entity_id": script}}],
        }
    ]


def automation(
    device_key: str,
    device_name: str,
    reaction_key: str,
    reaction: Mapping[str, Any],
    entity_id: str | None,
    script: str | None = None,
) -> dict[str, Any]:
    """The automation of a reaction; `script` is the current entity ID of its program's."""
    return {
        "id": automation_id(device_key, reaction_key),
        "alias": f"{device_name} {reaction[CONF_NAME]}",
        "description": f"pururu: {device_key}, {reaction_key}",
        "triggers": triggers(reaction, entity_id),
        "actions": actions(script),
    }
