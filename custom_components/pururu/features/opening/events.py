"""Events that describe a door's openings, in pururu's own words: what each means, and its fields.

pururu knows no integration: the configuration maps each event_type of an
event entity to a meaning, and each field to the attribute holding it. An
event entity's state is the time of its last event: that time, not when
pururu sees it, is the event's.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from functools import partial
from typing import Any, Self, override

import voluptuous as vol

from homeassistant.components.sensor import RestoreSensor, SensorDeviceClass
from homeassistant.const import Platform
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util.signal_type import SignalType

from ...core.entity import PururuEntity, as_time
from ...core.feature import TEXT, Device

OPENING = "opening"
DENIED = "denied"
RING = "ring"
MEANINGS = (OPENING, DENIED, RING)

# A field -> the entity key of the last opening's value
FIELDS: dict[str, str] = {
    "who": "last_opened_by",
    "how": "last_opened_via",
    "direction": "last_direction",
}
# A meaning recorded on its own -> the entity key of its last time
LAST: dict[str, str] = {DENIED: "last_denied", RING: "last_ring"}

ENTITY_KEYS: dict[str, Platform] = {
    **dict.fromkeys(FIELDS.values(), Platform.SENSOR),
    **dict.fromkeys(LAST.values(), Platform.SENSOR),
}

# One event entity; schemas of their own, so unknown keys are refused
SCHEMA = vol.Schema(
    {
        vol.Required("entity"): cv.entity_domain("event"),
        vol.Required("types"): vol.All(
            vol.Schema({cv.string: vol.In(MEANINGS)}), vol.Length(min=1)
        ),
        vol.Optional("fields", default={}): vol.Schema({vol.In(FIELDS): TEXT}),
    }
)


def _text(value: Any) -> str | None:
    """An attribute as text (`42` → "42"); None when it isn't there."""
    return None if value is None else str(value)


def _time(state: str) -> datetime | None:
    """An event entity's state as its event's time; None unless a time with its zone.

    A time without a zone can't be compared with an opening's, and a string
    shaped as a time can still be out of range.
    """
    time = as_time(state)
    return None if time is None or time.tzinfo is None else time


def described_signal(device: Device) -> SignalType[Mapping[str, str | None]]:
    """The fields of the last opening, sent when it starts ({}) and when an event describes it."""
    return SignalType(device.object_id("described"))


@dataclass(frozen=True, kw_only=True)
class Fired:
    """An event: its time and its fields (None: the attribute isn't there)."""

    time: datetime
    fields: dict[str, str | None]


@dataclass(frozen=True, kw_only=True)
class Source:
    """An event entity of the configuration: its types' meanings, its fields' attributes."""

    entity: str
    types: Mapping[str, str]
    fields: Mapping[str, str]

    @classmethod
    def of(cls, config: Mapping[str, Any]) -> Self:
        """From a validated item of `events`."""
        return cls(
            entity=config["entity"], types=config["types"], fields=config["fields"]
        )

    def means(self, meaning: str) -> bool:
        """Whether some type of this entity means `meaning`."""
        return meaning in self.types.values()

    def fired(self, event: Event[EventStateChangedData], meaning: str) -> Fired | None:
        """The event of `meaning` a change of the entity says, or None.

        The same state again (attributes only), unknown, unavailable, or
        anything not a time with its zone is no new event.
        """
        old, new = event.data["old_state"], event.data["new_state"]
        if new is None or (old is not None and old.state == new.state):
            return None
        time = _time(new.state)
        event_type = str(new.attributes.get("event_type"))
        if time is None or self.types.get(event_type) != meaning:
            return None
        return Fired(
            time=time,
            fields={
                field: _text(new.attributes.get(attribute))
                for field, attribute in self.fields.items()
            },
        )


class LastOpeningField(PururuEntity, RestoreSensor):
    """One field of the last opening (who made it, how, which way); unknown when no event says."""

    def __init__(self, device: Device, field: str) -> None:
        """The value of `field` of the last opening of `device`."""
        self.sources = ("open",)
        self._identify(device, Platform.SENSOR, FIELDS[field])
        self._field = field
        self._signal = described_signal(device)

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the value, then wait for the next opening."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and isinstance(last.native_value, str):
            self._attr_native_value = last.native_value
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._signal, self._record)
        )

    @callback
    def _record(self, fields: Mapping[str, str | None]) -> None:
        self._attr_native_value = fields.get(self._field)
        self.async_write_ha_state()


class LastEvent(PururuEntity, RestoreSensor):
    """When the last event of a meaning came (a denied attempt, a ring), its fields as attributes."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, device: Device, meaning: str, sources: Sequence[Source]) -> None:
        """The last event meaning `meaning` among `sources`."""
        self._identify(device, Platform.SENSOR, LAST[meaning])
        self._meaning = meaning
        self._sources = sources
        self._attr_extra_state_attributes = {}

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the time and fields, then watch every source."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last.native_value
        if (state := await self.async_get_last_state()) is not None:
            self._attr_extra_state_attributes = {
                field: state.attributes[field]
                for field in FIELDS
                if field in state.attributes
            }
        for source in self._sources:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, source.entity, partial(self._changed, source)
                )
            )

    @callback
    def _changed(self, source: Source, event: Event[EventStateChangedData]) -> None:
        """A later event of the meaning replaces the last; an older one, replayed, doesn't."""
        if (fired := source.fired(event, self._meaning)) is None:
            return
        last = self._attr_native_value
        if isinstance(last, datetime) and fired.time <= last:
            return
        self._attr_native_value = fired.time
        self._attr_extra_state_attributes = dict(fired.fields)
        self.async_write_ha_state()


def entities(device: Device, sources: Sequence[Source]) -> list[PururuEntity]:
    """What the events give: each field an opening event maps, and the last denied and ring.

    A ring's attributes would say nothing about the door: it has none.
    """
    mapped = {
        field for source in sources if source.means(OPENING) for field in source.fields
    }
    built: list[PururuEntity] = [
        LastOpeningField(device, field) for field in FIELDS if field in mapped
    ]
    if denied := [source for source in sources if source.means(DENIED)]:
        built.append(LastEvent(device, DENIED, denied))
    if rings := [
        replace(source, fields={}) for source in sources if source.means(RING)
    ]:
        built.append(LastEvent(device, RING, rings))
    return built
