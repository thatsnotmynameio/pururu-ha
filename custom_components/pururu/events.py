"""pururu's events: each state change of an entity the entry created, fired on HA's bus.

pururu speaks no HTTP: whatever consumes HA's events takes them from there (for
a webhook, a rest_command in the user's automation). Two classes, each enabled
on its own in `events`: the change of an entity with a state_class is a reading
(a series: power, totals, meters), any other a change (a fact: running, a mode,
the last cycle's end). Each event carries its device's states when it is fired:
a cycle's end (last_cycle_end, written last) comes with that cycle's values.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, Final

import voluptuous as vol

from homeassistant.components.sensor.const import ATTR_STATE_CLASS
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_RESTORED
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.json import json_bytes
from homeassistant.util.json import json_loads_object
from homeassistant.util.ulid import ulid_now

from .const import DOMAIN

CONF_EVENTS: Final = "events"
STATE_CHANGED: Final = "state_changed"
READING: Final = "reading"
CLASSES: Final = (STATE_CHANGED, READING)


def event_type(event_class: str) -> str:
    """The type a class's events have on HA's bus: pururu_state_changed, pururu_reading."""
    return f"{DOMAIN}_{event_class}"


def _distinct(classes: list[str]) -> list[str]:
    if len(set(classes)) != len(classes):
        raise vol.Invalid(f"a class is repeated: {classes}")
    return classes


# The classes fired, each at most once; none by default
SCHEMA = vol.All(cv.ensure_list, [vol.In(CLASSES)], _distinct)


@dataclass(frozen=True, kw_only=True)
class Watched:
    """A device whose entities' changes are fired: its key, its name, its created entities (entity ID → key)."""

    key: str
    name: str
    entities: Mapping[str, str]


@callback
def async_setup(
    hass: HomeAssistant,
    entry: ConfigEntry,
    classes: Collection[str],
    devices: Collection[Watched],
) -> None:
    """Fire the enabled classes' events for the devices' entities, until the entry unloads."""
    if not classes:
        return
    owners = {entity_id: device for device in devices for entity_id in device.entities}

    @callback
    def changed(event: Event[EventStateChangedData]) -> None:
        """Fire a real change of its class, if enabled.

        No change: an entity appearing or going (None), HA's restored
        placeholder either way (written when an entity unloads, as at a reload,
        and shown at start-up until it loads), attributes alone.
        """
        old, new = event.data["old_state"], event.data["new_state"]
        if old is None or new is None or old.state == new.state:
            return
        if old.attributes.get(ATTR_RESTORED) or new.attributes.get(ATTR_RESTORED):
            return
        event_class = (
            READING
            if new.attributes.get(ATTR_STATE_CLASS) is not None
            else STATE_CHANGED
        )
        if event_class not in classes:
            return
        hass.bus.async_fire(
            event_type(event_class),
            _data(hass, owners[new.entity_id], event_class, old, new),
            context=new.context,
        )

    entry.async_on_unload(async_track_state_change_event(hass, list(owners), changed))


def _data(
    hass: HomeAssistant, device: Watched, event_class: str, old: State, new: State
) -> dict[str, Any]:
    """The event's data, JSON's own: the change, and every state of its device now.

    The attributes as HA's JSON reads them back: their keys may be enums and
    their values datetimes (running's cycle_start), which a template (as a
    rest_command's `{{ event | tojson }}`) renders as Python's repr.
    """
    key = device.entities[new.entity_id]
    return {
        "event_id": ulid_now(),
        "event_name": f"{device.key}.{key}",
        "event_class": event_class,
        "entity_id": new.entity_id,
        "device": device.key,
        "device_name": device.name,
        "key": key,
        "old": old.state,
        "new": new.state,
        "time": new.last_changed.isoformat(),
        "attributes": json_loads_object(json_bytes(new.attributes)),
        "states": {
            entity_key: state.state
            for entity_id, entity_key in device.entities.items()
            if (state := hass.states.get(entity_id)) is not None
        },
    }
