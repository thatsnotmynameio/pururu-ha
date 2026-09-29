"""Whether the appliance runs: power above a threshold, with delays; the source of its cycles."""

from datetime import datetime, timedelta
from typing import Any, override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import STATE_ON, Platform
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    State,
    callback,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from ...entity import PururuEntity, reading
from ...feature import Device
from ..cycle import Cycle, CycleStart, cycle_signal, end_signal
from ..cycle.energy import kwh_now, kwh_used


class Running(PururuEntity, BinarySensorEntity, RestoreEntity):
    """On while the power stays above the threshold; holds while the plug has no value."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(
        self,
        device: Device,
        *,
        power: str,
        energy: str | None,
        threshold: float,
        on_delay: timedelta,
        off_delay: timedelta,
    ) -> None:
        """Watch `power` against `threshold`; the delays ignore presses, pauses and tails."""
        self._identify(device, Platform.BINARY_SENSOR, "running")
        self._signals = (cycle_signal(device), end_signal(device))
        self._power = power
        self._energy = energy
        self._threshold = threshold
        self._delays = {True: on_delay, False: off_delay}
        self._attr_is_on = False
        self._data = CycleStart()
        # (the state it goes to, cancel) while a delay runs
        self._pending: tuple[bool, CALLBACK_TYPE] | None = None

    @property
    @override
    def extra_restore_state_data(self) -> CycleStart:
        """The running cycle's start, and its end while off_delay runs."""
        return self._data

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The running cycle's start, and its end while off_delay runs (the power went down then)."""
        if not self._attr_is_on:
            return None
        attributes: dict[str, Any] = {}
        if self._data.since is not None:
            attributes["cycle_start"] = self._data.since
        if self._data.until is not None:
            attributes["cycle_end"] = self._data.until
        return attributes or None

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the state and the running cycle, then follow the plug."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == STATE_ON
        if (extra := await self.async_get_last_extra_data()) is not None:
            self._data = CycleStart.from_dict(extra.as_dict())
        if not self._attr_is_on:
            self._data.until = None
        self.async_on_remove(
            async_track_state_change_event(self.hass, self._power, self._power_changed)
        )
        self.async_on_remove(self._cancel)
        self._evaluate(self.hass.states.get(self._power))

    @callback
    def _power_changed(self, event: Event[EventStateChangedData]) -> None:
        self._evaluate(event.data["new_state"])

    @callback
    def _evaluate(self, state: State | None) -> None:
        """Schedule the change a reading asks for, or cancel one it no longer asks for.

        The end is when the power went down: a reading without a value (or a
        restart, a reload) makes off_delay count again from the next reading,
        and the end stays; only the power back above cancels it.
        """
        ending = self._data.until
        if (value := reading(state)) is None:
            self._cancel()
        else:
            above = value > self._threshold
            if above == self._attr_is_on:
                self._cancel()
                self._data.until = None
            elif self._pending is None or self._pending[0] != above:
                self._cancel()
                if not above and self._data.until is None:
                    self._data.until = dt_util.utcnow()
                self._pending = (
                    above,
                    async_call_later(self.hass, self._delays[above], self._turn),
                )
        if self._data.until != ending:
            self.async_write_ha_state()

    @callback
    def _cancel(self) -> None:
        if self._pending is not None:
            self._pending[1]()
            self._pending = None

    @callback
    def _turn(self, _now: datetime) -> None:
        """A delay passed: a cycle starts, or ends and is sent to the device's other entities.

        It starts now, and ends when the power went down: off_delay only confirms the
        end. The energy is split now, as idle energy reads it when running changes.
        """
        if self._pending is None:
            return
        on = self._pending[0]
        self._pending = None
        if on:
            self._data = CycleStart(
                since=dt_util.utcnow(), since_energy=kwh_now(self.hass, self._energy)
            )
            self._attr_is_on = True
            self.async_write_ha_state()
            return
        cycle = Cycle(
            start=self._data.since,
            end=self._data.until or dt_util.utcnow(),
            energy_kwh=kwh_used(
                self._data.since_energy, kwh_now(self.hass, self._energy)
            ),
        )
        self._data = CycleStart()
        self._attr_is_on = False
        self.async_write_ha_state()
        for signal in self._signals:  # the end's own signal last
            async_dispatcher_send(self.hass, signal, cycle)
