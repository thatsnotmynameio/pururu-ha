"""Whether the door is open: its contact, held while the contact has no state; the source of its openings.

It also matches opening events to openings, by time: an event `match` apart
from an opening's start at most describes it, whichever comes first.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from functools import partial
from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import STATE_OFF, STATE_ON, Platform
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from ...entity import PururuEntity
from ...feature import Device
from ..cycle import Cycle, CycleStart, cycle_signal, end_signal
from .events import OPENING, Fired, Source, described_signal


class Open(PururuEntity, BinarySensorEntity, RestoreEntity):
    """On while the contact is open; holds while it has no state. Each opening is a cycle."""

    def __init__(
        self,
        device: Device,
        device_class: BinarySensorDeviceClass,
        *,
        contact: str | None,
        events: Sequence[Source] = (),
        match: timedelta = timedelta(0),
    ) -> None:
        """Follow `contact` (None: stand for nothing, unavailable); `events` describe openings."""
        self._identify(device, Platform.BINARY_SENSOR, "open")
        self._attr_device_class = device_class
        self._attr_available = contact is not None
        self._attr_is_on = False
        self._contact = contact
        self._events = events
        self._match = match
        self._signals = (cycle_signal(device), end_signal(device))
        self._described_signal = described_signal(device)
        self._data = CycleStart()
        # False until HA has started: every entity of the door listens by then
        self._following = False
        # The last opening's start, whether an event described it, an event waiting
        self._opened: datetime | None = None
        self._described = False
        self._pending: Fired | None = None

    @property
    @override
    def extra_restore_state_data(self) -> CycleStart:
        """The current opening's start."""
        return self._data

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the state and the opening; follow the contact once HA has started.

        Nothing opens or closes before: the door's other entities may not listen
        yet. Once HA has started, a restored opening whose contact is closed ends.
        """
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == STATE_ON
        if (extra := await self.async_get_last_extra_data()) is not None:
            self._data = CycleStart.from_dict(extra.as_dict())
        self._opened = self._data.since
        if self._contact is None:
            return
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._contact, self._contact_changed
            )
        )
        for source in self._events:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, source.entity, partial(self._event, source)
                )
            )
        self.async_on_remove(async_at_started(self.hass, self._started))

    @callback
    def _started(self, _hass: HomeAssistant) -> None:
        """Every entity of the door listens now: follow the contact as it is."""
        self._following = True
        if self._contact is not None:
            self._follow(self.hass.states.get(self._contact))

    @callback
    def _contact_changed(self, event: Event[EventStateChangedData]) -> None:
        if self._following:
            self._follow(event.data["new_state"])

    @callback
    def _follow(self, state: State | None) -> None:
        """Open or close as the contact says; hold while it says neither."""
        if state is None or state.state not in (STATE_ON, STATE_OFF):
            return
        is_open = state.state == STATE_ON
        if is_open == self._attr_is_on:
            return
        now = dt_util.utcnow()
        self._attr_is_on = is_open
        if is_open:
            self._data = CycleStart(since=now)
            self.async_write_ha_state()
            self._opening_starts(now)
            return
        cycle = Cycle(start=self._data.since, end=now, energy_kwh=None)
        self._data = CycleStart()
        self.async_write_ha_state()
        for signal in self._signals:  # the end's own signal last
            async_dispatcher_send(self.hass, signal, cycle)

    @callback
    def _opening_starts(self, now: datetime) -> None:
        """A new opening: an event waiting close enough describes it; else nothing does yet."""
        self._opened = now
        self._described = False
        pending, self._pending = self._pending, None
        if pending is not None and abs(now - pending.time) <= self._match:
            self._describe(pending.fields)
        else:
            async_dispatcher_send(self.hass, self._described_signal, {})

    @callback
    def _event(self, source: Source, event: Event[EventStateChangedData]) -> None:
        """An opening event describes the last opening near its start; else it waits for the next."""
        if not self._following or (fired := source.fired(event, OPENING)) is None:
            return
        if (
            self._opened is not None
            and not self._described
            and abs(fired.time - self._opened) <= self._match
        ):
            self._describe(fired.fields)
        else:
            self._pending = fired

    @callback
    def _describe(self, fields: Mapping[str, str | None]) -> None:
        """The first event near the opening wins: later ones don't describe it."""
        self._described = True
        async_dispatcher_send(self.hass, self._described_signal, fields)
