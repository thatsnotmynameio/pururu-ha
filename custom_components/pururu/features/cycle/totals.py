"""Totals over all time of the cycles a source sends: their count, their hours, their energy, and between them."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import override

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
    UnitOfEnergy,
    UnitOfTime,
)
from homeassistant.core import Event, EventStateChangedData, State, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from ...core.entity import PururuEntity
from ...core.feature import Device, Item
from . import Cycle, cycle_signal
from .energy import kwh_now, kwh_used

# How often the hours of a running cycle are brought up to date
UPDATE_EVERY = timedelta(minutes=1)


class CyclesTotal(PururuEntity, RestoreSensor):
    """Finished cycles, all time; the cycle meters (statistics.py) measure it."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self,
        device: Device,
        *,
        source: str,
        item: Item | None = None,
        entity_key: str = "cycles_total",
    ) -> None:
        """Count the cycles (of `item`) that `source` sends, as `entity_key` (a door's openings)."""
        self.sources = (source,)
        self._identify(device, Platform.SENSOR, entity_key, item=item)
        self._signal = cycle_signal(device, item)  # only _watch reads it
        self._cycles = 0

    @property
    @override
    def native_value(self) -> int:
        """The count."""
        return self._cycles

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the count, then count."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and isinstance(last.native_value, int | float | Decimal):
            self._cycles = int(last.native_value)
        self._watch()

    def _watch(self) -> None:
        """Count each cycle `self._signal` sends; a subclass that counts itself overrides it."""
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._signal, self._count)
        )

    @callback
    def _count(self, cycle: Cycle) -> None:
        self._cycles += 1
        self.async_write_ha_state()


class EnergyTotal(PururuEntity, RestoreSensor):
    """kWh the cycles used, all time; a cycle whose energy is unknown adds nothing."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3

    def __init__(
        self, device: Device, *, source: str, item: Item | None = None
    ) -> None:
        """Add up the energy of the cycles (of `item`) that `source` sends."""
        self.sources = (source,)
        self._identify(device, Platform.SENSOR, "energy_total", item=item)
        self._signal = cycle_signal(device, item)
        self._kwh = 0.0

    @property
    @override
    def native_value(self) -> float:
        """The kWh, to the mWh: shown to the Wh, but a sip's share still counts."""
        return round(self._kwh, 6)

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the kWh, then add."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and isinstance(last.native_value, int | float | Decimal):
            self._kwh = float(last.native_value)
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._signal, self._add)
        )

    @callback
    def _add(self, cycle: Cycle) -> None:
        if cycle.energy_kwh is None:
            return
        self._kwh += cycle.energy_kwh
        self.async_write_ha_state()


class RuntimeTotal(PururuEntity, RestoreSensor):
    """Hours `watched` has been in `state`, all time; the runtime meters (statistics.py) measure it.

    A cycle's source says when its cycle started (`cycle_start`, when it enters
    `state`) and, while its off_delay runs, when it ended (`cycle_end`): the time
    between that end and leaving `state` isn't counted, unless the end is cancelled.
    Without `watched` (a program whose script isn't pururu's), it counts nothing.
    """

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        device: Device,
        watched: str | None,
        state: str,
        *,
        source: str,
        item: Item | None = None,
        entity_key: str = "runtime_total",
    ) -> None:
        """Add up the time `watched`, the entity of `source`, is in `state`, as `entity_key`."""
        self.sources = (source,)
        self._identify(device, Platform.SENSOR, entity_key, item=item)
        self._watched = watched
        self._state = state
        self._hours = 0.0
        # Up to when the time in the state is already added; None while not in it
        self._counted_until: datetime | None = None
        # The watched cycle's end while its off_delay runs: counted up to it, no further
        self._ends: datetime | None = None

    @property
    @override
    def native_value(self) -> float:
        """The hours, to about a third of a second."""
        return round(self._hours, 4)

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the hours, then count while in the state (not while HA was down)."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and isinstance(last.native_value, int | float | Decimal):
            self._hours = float(last.native_value)
        if self._watched is None:
            return
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._watched, self._watched_changed
            )
        )
        self.async_on_remove(
            async_track_time_interval(self.hass, self._update, UPDATE_EVERY)
        )
        if (state := self.hass.states.get(self._watched)) is not None and (
            state.state == self._state
        ):
            self._counted_until = dt_util.utcnow()
            self._ends = _attribute_time(state, "cycle_end")

    def _add_until(self, now: datetime) -> None:
        if self._ends is not None:
            now = min(now, self._ends)
        if self._counted_until is not None and now > self._counted_until:
            self._hours += (now - self._counted_until).total_seconds() / 3600
            self._counted_until = now

    @callback
    def _watched_changed(self, event: Event[EventStateChangedData]) -> None:
        now = dt_util.utcnow()
        self._add_until(now)
        old, new = event.data["old_state"], event.data["new_state"]
        if new is None or new.state != self._state:
            self._counted_until = self._ends = None
        else:
            if self._counted_until is None:
                # Entered from another state, not from none (a restart, a reload)
                entered = old is not None and old.state not in (
                    STATE_UNAVAILABLE,
                    STATE_UNKNOWN,
                )
                start = _attribute_time(new, "cycle_start") if entered else None
                self._counted_until = min(start, now) if start is not None else now
            self._ends = _attribute_time(new, "cycle_end")
            self._add_until(now)
        self.async_write_ha_state()

    @callback
    def _update(self, now: datetime) -> None:
        if self._counted_until is not None:
            self._add_until(now)
            self.async_write_ha_state()


def _attribute_time(state: State, attribute: str) -> datetime | None:
    """A datetime attribute of `state` (a restored state has strings), or None."""
    value = state.attributes.get(attribute)
    if isinstance(value, str):
        value = dt_util.parse_datetime(value)
    return value if isinstance(value, datetime) else None


class IdleEnergyTotal(PururuEntity, RestoreSensor):
    """kWh the counter grew while `watched` is `state` (between cycles), all time.

    The cycles' energy and this add up to the counter's growth: both read the counter
    at the instant `watched` leaves or enters `state`. Added (a restart, a reload) or
    `watched` coming back from no state, it counts from the counter's next reading: the
    reading already there may be from before HA was down, and a cycle that ran meanwhile
    would count as idle.
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3

    def __init__(
        self, device: Device, watched: str, state: str, counter: str, *, source: str
    ) -> None:
        """Add up what `counter` grows while `watched`, the entity of `source`, is `state`."""
        self.sources = (source,)
        self._identify(device, Platform.SENSOR, "idle_energy_total")
        self._watched = watched
        self._state = state
        self._counter = counter
        self._kwh = 0.0
        # The counter's last reading while idle, in kWh; None while not idle or unread
        self._counted_from: float | None = None

    @property
    @override
    def native_value(self) -> float:
        """The kWh, to the mWh, as EnergyTotal."""
        return round(self._kwh, 6)

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the kWh, then add while idle, from the counter's next reading."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and isinstance(last.native_value, int | float | Decimal):
            self._kwh = float(last.native_value)
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._watched, self._watched_changed
            )
        )
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._counter, self._counter_changed
            )
        )

    def _add_until(self, now: float | None) -> None:
        if (used := kwh_used(self._counted_from, now)) is not None:
            self._kwh += used
            self.async_write_ha_state()

    @callback
    def _watched_changed(self, event: Event[EventStateChangedData]) -> None:
        now = kwh_now(self.hass, self._counter)
        self._add_until(now)
        old, new = event.data["old_state"], event.data["new_state"]
        # A cycle's end reads the counter live; from no state, wait for its next reading
        ended = old is not None and old.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)
        idle = new is not None and new.state == self._state
        self._counted_from = now if idle and ended else None

    @callback
    def _counter_changed(self, event: Event[EventStateChangedData]) -> None:
        if not self.hass.states.is_state(self._watched, self._state):
            return
        if (now := kwh_now(self.hass, self._counter)) is None:
            return  # no reading: count on from the last one
        self._add_until(now)
        self._counted_from = now  # after a restart, the first reading only starts it
