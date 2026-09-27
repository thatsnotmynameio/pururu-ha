"""Whether the appliance runs: power above a threshold, with delays; the source of its cycles."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Self, override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_ON,
    Platform,
    UnitOfEnergy,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    State,
    callback,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from ...entity import PururuEntity, reading
from ...feature import Device
from .cycle import Cycle, cycle_signal, end_signal


@dataclass
class RunningData(ExtraStoredData):
    """The running cycle's start, kept across restarts and reloads."""

    since: datetime | None = None
    since_energy: float | None = None

    @override
    def as_dict(self) -> dict[str, Any]:
        """What .storage keeps."""
        return {
            "since": self.since.isoformat() if self.since else None,
            "since_energy": self.since_energy,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Read back what as_dict saved; anything else means no running cycle."""
        since = data.get("since")
        energy = data.get("since_energy")
        return cls(
            since=dt_util.parse_datetime(since) if isinstance(since, str) else None,
            since_energy=float(energy) if isinstance(energy, int | float) else None,
        )


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
        self._data = RunningData()
        # (the state it goes to, cancel) while a delay runs
        self._pending: tuple[bool, CALLBACK_TYPE] | None = None

    @property
    @override
    def extra_restore_state_data(self) -> RunningData:
        """The running cycle's start."""
        return self._data

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the state and the running cycle, then follow the plug."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == STATE_ON
        if (extra := await self.async_get_last_extra_data()) is not None:
            self._data = RunningData.from_dict(extra.as_dict())
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
        """Schedule the change a reading asks for, or cancel one it no longer asks for."""
        if (value := reading(state)) is None:
            self._cancel()
            return
        above = value > self._threshold
        if above == self._attr_is_on:
            self._cancel()
        elif self._pending is None or self._pending[0] != above:
            self._cancel()
            self._pending = (
                above,
                async_call_later(self.hass, self._delays[above], self._turn),
            )

    @callback
    def _cancel(self) -> None:
        if self._pending is not None:
            self._pending[1]()
            self._pending = None

    def _energy_now(self) -> float | None:
        """The counter in kWh (no unit: kWh); None without a reading or an energy unit."""
        if self._energy is None:
            return None
        state = self.hass.states.get(self._energy)
        if state is None or (value := reading(state)) is None:
            return None
        unit = state.attributes.get(
            ATTR_UNIT_OF_MEASUREMENT, UnitOfEnergy.KILO_WATT_HOUR
        )
        if unit not in EnergyConverter.VALID_UNITS:
            return None
        return EnergyConverter.convert(value, unit, UnitOfEnergy.KILO_WATT_HOUR)

    def _energy_used(self) -> float | None:
        start, end = self._data.since_energy, self._energy_now()
        if start is None or end is None:
            return None
        return round(max(end - start, 0.0), 3)

    @callback
    def _turn(self, _now: datetime) -> None:
        """A delay passed: a cycle starts, or ends and is sent to the device's other entities."""
        if self._pending is None:
            return
        on = self._pending[0]
        self._pending = None
        now = dt_util.utcnow()
        if on:
            self._data = RunningData(since=now, since_energy=self._energy_now())
            self._attr_is_on = True
            self.async_write_ha_state()
            return
        cycle = Cycle(start=self._data.since, end=now, energy_kwh=self._energy_used())
        self._data = RunningData()
        self._attr_is_on = False
        self.async_write_ha_state()
        for signal in self._signals:  # the end's own signal last
            async_dispatcher_send(self.hass, signal, cycle)
