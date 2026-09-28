"""Totals over all time of the cycles a source sends: their count, their hours, their energy."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import override

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import Platform, UnitOfEnergy, UnitOfTime
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from ...entity import PururuEntity
from ...feature import Device, Item
from . import Cycle, cycle_signal

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
        self._signal = cycle_signal(device, item)
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
    """Hours `watched` has been in `state`, all time; the runtime meters (statistics.py) measure it."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        device: Device,
        watched: str,
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
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._watched, self._watched_changed
            )
        )
        self.async_on_remove(
            async_track_time_interval(self.hass, self._update, UPDATE_EVERY)
        )
        if self.hass.states.is_state(self._watched, self._state):
            self._counted_until = dt_util.utcnow()

    def _add_until(self, now: datetime) -> None:
        if self._counted_until is not None:
            self._hours += (now - self._counted_until).total_seconds() / 3600
            self._counted_until = now

    @callback
    def _watched_changed(self, event: Event[EventStateChangedData]) -> None:
        now = dt_util.utcnow()
        self._add_until(now)
        new = event.data["new_state"]
        self._counted_until = (
            now if new is not None and new.state == self._state else None
        )
        self.async_write_ha_state()

    @callback
    def _update(self, now: datetime) -> None:
        if self._counted_until is not None:
            self._add_until(now)
            self.async_write_ha_state()
