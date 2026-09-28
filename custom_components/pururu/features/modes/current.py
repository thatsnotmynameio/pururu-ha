"""The running mode, from bands of a sensor's value inside the appliance's cycle: the source of mode cycles."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, override

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import STATE_OFF, STATE_ON, Platform
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from ...entity import PururuEntity, reading
from ...feature import Device, Item
from ..cycle import Cycle, CycleStart, cycle_signal, end_signal
from ..cycle.energy import kwh_now, kwh_used

# The state while no mode runs: no mode is named so
IDLE = "idle"


@dataclass(frozen=True, kw_only=True)
class Mode:
    """A kind of cycle: it starts once the value stays in its band for on_delay, ends once out of it for off_delay."""

    item: Item
    above: float | None
    below: float | None
    on_delay: timedelta
    off_delay: timedelta

    def contains(self, value: float) -> bool:
        """Strictly above `above` and strictly below `below`, as HA's numeric_state."""
        return (self.above is None or value > self.above) and (
            self.below is None or value < self.below
        )


class Current(PururuEntity, SensorEntity, RestoreEntity):
    """The running mode, or idle; each mode cycle that ends is sent on its mode's signals.

    One mode at a time: the bands don't overlap, and a mode whose on_delay
    passed (armed) waits for the running one to end, then starts from when it
    was armed, or from the running one's end if later. A mode starts only while
    the appliance's cycle is on (armed before, it starts when the cycle does);
    the cycle turning off ends it. A mode cycle ends when the value left its
    band, or when the appliance's cycle ended if earlier: off_delay only
    confirms the end.
    """

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(
        self,
        device: Device,
        *,
        cycle: str,
        sensor: str,
        energy: str | None,
        modes: tuple[Mode, ...],
    ) -> None:
        """Follow `sensor` through `modes` while `cycle` is on; `energy` gives each cycle's kWh."""
        self._identify(device, Platform.SENSOR, "current")
        self._device = device
        self._cycle = cycle
        self._sensor = sensor
        self._energy = energy
        self._modes = {mode.item.slug: mode for mode in modes}
        self._attr_options = [IDLE, *self._modes]
        self._running: str | None = None
        self._start = CycleStart()
        # The mode whose band held for its on_delay, waiting for the cycle to be
        # on, and since when
        self._armed: tuple[str, datetime] | None = None
        # (the mode, cancel) while a mode's on_delay runs
        self._starting: tuple[str, CALLBACK_TYPE] | None = None
        # (when the value left the band, cancel) while the running mode's off_delay runs
        self._ending: tuple[datetime, CALLBACK_TYPE] | None = None

    @property
    @override
    def native_value(self) -> str:
        """The running mode, or idle."""
        return self._running or IDLE

    @property
    @override
    def extra_restore_state_data(self) -> CycleStart:
        """The running mode cycle's start."""
        return self._start

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The running mode cycle's start, and its end while off_delay runs."""
        if self._running is None:
            return None
        attributes: dict[str, Any] = {}
        if self._start.since is not None:
            attributes["cycle_start"] = self._start.since
        if self._ending is not None:
            attributes["cycle_end"] = self._ending[0]
        return attributes or None

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the running mode and its start, then follow the sensor and the cycle.

        Nothing ends here, even with the cycle already off: the mode's other
        entities may not listen yet. Once HA has started, a restored mode
        whose cycle is off ends (its sensor may send no reading to end it).
        """
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._modes:
            self._running = last.state
            if (extra := await self.async_get_last_extra_data()) is not None:
                self._start = CycleStart.from_dict(extra.as_dict())
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._sensor, self._sensor_changed
            )
        )
        self.async_on_remove(
            async_track_state_change_event(self.hass, self._cycle, self._cycle_changed)
        )
        self.async_on_remove(self._cancel)
        self._take(self.hass.states.get(self._sensor))
        self.async_on_remove(async_at_started(self.hass, self._started))

    @callback
    def _started(self, _hass: HomeAssistant) -> None:
        """Every entity of the modes listens now: a restored mode whose cycle is off ends."""
        if self._running is not None:
            self._gate(self.hass.states.get(self._cycle))

    @callback
    def _sensor_changed(self, event: Event[EventStateChangedData]) -> None:
        self._take(event.data["new_state"])

    @callback
    def _cycle_changed(self, event: Event[EventStateChangedData]) -> None:
        self._gate(event.data["new_state"], event.data["old_state"])

    @callback
    def _gate(self, state: State | None, old: State | None = None) -> None:
        """The cycle on starts the armed mode; off ends the running one. Unknown does neither.

        Off, the running mode ends when its value left its band, or when the
        cycle ended (`old`'s cycle_end) if earlier, but never before it started.
        """
        if state is None:
            return
        now = dt_util.utcnow()
        if state.state == STATE_ON and self._running is None:
            if self._start_armed(now):
                self.async_write_ha_state()
        elif state.state == STATE_OFF and (running := self._running) is not None:
            end = now if self._ending is None else self._ending[0]
            if old is not None and isinstance(
                cycle_end := old.attributes.get("cycle_end"), datetime
            ):
                end = min(end, cycle_end)
            if self._start.since is not None:
                end = max(end, self._start.since)
            self._end(running, end)
            # Its band may hold still (a sensor other than the gate's plug): no
            # new reading will arm it again, so it's armed for the next cycle
            value = reading(self.hass.states.get(self._sensor))
            if value is not None and self._modes[running].contains(value):
                self._armed = (running, now)

    @callback
    def _take(self, state: State | None) -> None:
        """Schedule the start and the end a reading asks for; cancel those it no longer asks for.

        A reading without a value cancels both, as running's: they count again
        from the next reading. The running mode and the armed one stay.
        """
        if (value := reading(state)) is None:
            self._cancel()
            return
        inside = next(
            (slug for slug, mode in self._modes.items() if mode.contains(value)), None
        )
        armed = None if self._armed is None else self._armed[0]
        if armed != inside:
            self._armed = armed = None
        if self._running is not None:
            ending = self._ending is not None
            if inside == self._running:
                self._cancel_ending()
            elif self._ending is None:
                self._ending = (
                    dt_util.utcnow(),
                    async_call_later(
                        self.hass,
                        self._modes[self._running].off_delay,
                        self._off_delay_passed,
                    ),
                )
            if (self._ending is not None) != ending:
                self.async_write_ha_state()
        if inside is None or inside in (self._running, armed):
            self._cancel_starting()
        elif self._starting is None or self._starting[0] != inside:
            self._cancel_starting()
            self._starting = (
                inside,
                async_call_later(
                    self.hass, self._modes[inside].on_delay, self._on_delay_passed
                ),
            )

    @callback
    def _cancel_starting(self) -> None:
        if self._starting is not None:
            self._starting[1]()
            self._starting = None

    @callback
    def _cancel_ending(self) -> None:
        if self._ending is not None:
            self._ending[1]()
            self._ending = None

    @callback
    def _cancel(self) -> None:
        self._cancel_starting()
        self._cancel_ending()

    @callback
    def _on_delay_passed(self, _now: datetime) -> None:
        if self._starting is None:
            return
        self._armed = (self._starting[0], dt_util.utcnow())
        self._starting = None
        if self._running is None and self._start_armed(dt_util.utcnow()):
            self.async_write_ha_state()

    @callback
    def _off_delay_passed(self, _now: datetime) -> None:
        if self._ending is None or self._running is None:
            return
        left = self._ending[0]
        self._ending = None
        self._end(self._running, left)

    @callback
    def _start_armed(self, now: datetime, after: datetime | None = None) -> bool:
        """The armed mode starts if there is one and the cycle is on; whether it did.

        It starts at `now`, or, handed over, from when it was armed, but not
        before `after` (the previous mode's end). No mode runs; the caller writes
        the state.
        """
        if self._armed is None or not self.hass.states.is_state(self._cycle, STATE_ON):
            return False
        armed, since = self._armed
        self._armed = None
        self._running = armed
        self._start = CycleStart(
            since=now if after is None else max(since, after),
            since_energy=kwh_now(self.hass, self._energy),
        )
        return True

    @callback
    def _end(self, running: str, end: datetime) -> None:
        """`running`'s cycle ends at `end`, and the armed mode starts if it can.

        The state is written once, the next mode or idle, never idle in between
        (an automation on idle would fire at every handover); then the cycle is
        sent, its end's signal last.
        """
        self._cancel_ending()
        cycle = Cycle(
            start=self._start.since,
            end=end,
            energy_kwh=kwh_used(
                self._start.since_energy, kwh_now(self.hass, self._energy)
            ),
        )
        self._running = None
        self._start = CycleStart()
        self._start_armed(dt_util.utcnow(), after=end)
        self.async_write_ha_state()
        item = self._modes[running].item
        for signal in (
            cycle_signal(self._device, item),
            end_signal(self._device, item),
        ):
            async_dispatcher_send(self.hass, signal, cycle)
