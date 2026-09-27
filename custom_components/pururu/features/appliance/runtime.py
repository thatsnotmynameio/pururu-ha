"""Hours the appliance has run, all time."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import override

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import STATE_ON, Platform, UnitOfTime
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from ...entity import PururuEntity
from ...feature import Device

# How often a running appliance's hours are brought up to date
UPDATE_EVERY = timedelta(minutes=1)


class RuntimeTotal(PururuEntity, RestoreSensor):
    """Hours `running` has been on, all time; the runtime meters (statistics.py) measure it."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 2
    sources = ("running",)

    def __init__(self, device: Device, running: str) -> None:
        """Add up the time `running` is on."""
        self._identify(device, Platform.SENSOR, "runtime_total")
        self._running = running
        self._hours = 0.0
        # Up to when the running time is already added; None while not running
        self._counted_until: datetime | None = None

    @property
    @override
    def native_value(self) -> float:
        """The hours, to about a third of a second."""
        return round(self._hours, 4)

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the hours, then count while running is on (not while HA was down)."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and isinstance(last.native_value, int | float | Decimal):
            self._hours = float(last.native_value)
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._running, self._running_changed
            )
        )
        self.async_on_remove(
            async_track_time_interval(self.hass, self._update, UPDATE_EVERY)
        )
        if self.hass.states.is_state(self._running, STATE_ON):
            self._counted_until = dt_util.utcnow()

    def _add_until(self, now: datetime) -> None:
        if self._counted_until is not None:
            self._hours += (now - self._counted_until).total_seconds() / 3600
            self._counted_until = now

    @callback
    def _running_changed(self, event: Event[EventStateChangedData]) -> None:
        now = dt_util.utcnow()
        self._add_until(now)
        new = event.data["new_state"]
        self._counted_until = now if new is not None and new.state == STATE_ON else None
        self.async_write_ha_state()

    @callback
    def _update(self, now: datetime) -> None:
        if self._counted_until is not None:
            self._add_until(now)
            self.async_write_ha_state()
