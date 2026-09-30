"""The detector in HA: the program's carrier, and its phases' entities showing it."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any, override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.const import STATE_ON, Platform
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.util import dt as dt_util

from ....core.entity import PururuEntity, reading
from ....core.feature import Device
from .. import Cycle, CycleSource, cycle_signal
from ..energy import kwh_now
from ..last import LAST_CYCLE, LastCycleValue
from ..totals import CyclesTotal, EnergyTotal, RuntimeTotal
from .detector import Change, Detector, Ended
from .schema import IDLE, OTHER, PHASE, Phase, Program

type View = Callable[[list[Change]], None]


@dataclass
class Snapshot(ExtraStoredData):
    """The detector's snapshot, as .storage keeps it."""

    data: dict[str, Any]

    @override
    def as_dict(self) -> dict[str, Any]:
        """What .storage keeps."""
        return self.data


class Carrier(CycleSource, BinarySensorEntity, RestoreEntity):
    """On while the program runs: it owns the detector, and the phases' entities show it.

    It follows the reading and waits for the detector's next delay. Each step
    writes its own state (sending the program's cycle when it ends), then calls
    each view (`subscribe`) with the step's changes.
    """

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(
        self,
        device: Device,
        key: str,
        *,
        program: Program,
        reading: str,
        energy: str | None,
    ) -> None:
        """`program` read from `reading`, as `key` of `device`; `energy` gives each cycle's kWh."""
        self._identify(device, Platform.BINARY_SENSOR, key)
        self._cycle_signals(device)
        self.detector = Detector(program)
        self._reading = reading
        self._energy = energy
        self._views: list[View] = []
        # Whether the detector holds what was restored: until then, a view shows its own
        self.ready = False
        self._timer: CALLBACK_TYPE | None = None

    @property
    @override
    def is_on(self) -> bool:
        """Whether the program runs."""
        return self.detector.on

    @property
    @override
    def extra_restore_state_data(self) -> Snapshot:
        """Every running cycle, and the phases seen."""
        return Snapshot(self.detector.snapshot())

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The running cycle's start, and its end while off_delay runs: the appliance's `running`'s."""
        if (run := self.detector.run(None)) is None:
            return None
        attributes: dict[str, Any] = {}
        if run.since is not None:
            attributes["cycle_start"] = run.since
        if run.until is not None:
            attributes["cycle_end"] = run.until
        return attributes or None

    @callback
    def subscribe(self, view: View) -> CALLBACK_TYPE:
        """Call `view` with each step's changes, after the carrier's own; returns the unsubscribe."""
        self._views.append(view)
        return partial(self._views.remove, view)

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the detector, then follow the reading from its current state."""
        await super().async_added_to_hass()
        if (extra := await self.async_get_last_extra_data()) is not None:
            self.detector.restore(extra.as_dict())
        self.ready = True
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._reading, self._reading_changed
            )
        )
        self.async_on_remove(self._cancel_timer)
        self._step(self._read(self.hass.states.get(self._reading)))

    def _read(self, state: State | None) -> list[Change]:
        return self.detector.read(
            reading(state), dt_util.utcnow(), kwh_now(self.hass, self._energy)
        )

    @callback
    def _reading_changed(self, event: Event[EventStateChangedData]) -> None:
        self._step(self._read(event.data["new_state"]))

    @callback
    def _delay_passed(self, _now: datetime) -> None:
        self._timer = None
        self._step(
            self.detector.advance(dt_util.utcnow(), kwh_now(self.hass, self._energy))
        )

    @callback
    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer()
            self._timer = None

    @callback
    def _step(self, changes: list[Change]) -> None:
        """Show a step: the carrier's state (and the program's cycle), then each view; then wait for the next delay."""
        ended = next(
            (c.cycle for c in changes if isinstance(c, Ended) and c.key is None), None
        )
        if ended is not None:
            self._send(ended)
        else:
            self.async_write_ha_state()
        for view in list(self._views):
            view(changes)
        self._cancel_timer()
        if (due := self.detector.due()) is not None:
            self._timer = async_track_point_in_utc_time(
                self.hass, self._delay_passed, due
            )


class PhaseRunning(CycleSource, BinarySensorEntity):
    """On while its phase runs: the source of the phase's cycles.

    Added after the carrier on the same platform, so the detector is restored
    by then: its first state is already the restored one.
    """

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(
        self, device: Device, carrier: Carrier, phase: Phase, *, source: str
    ) -> None:
        """Show `phase` of `carrier`'s detector; `source`: the carrier's entity key."""
        item = phase.item
        if phase.other:
            self._identify(
                device,
                Platform.BINARY_SENSOR,
                item.slug,
                translation=f"{PHASE}_{OTHER}",
            )
        else:
            self._identify(device, Platform.BINARY_SENSOR, item.slug, name=phase.name)
        self.sources = (source,)
        self._cycle_signals(device, item)
        self._carrier = carrier
        self._key = phase.key

    @property
    @override
    def is_on(self) -> bool:
        """Whether its phase runs."""
        return self._carrier.detector.run(self._key) is not None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The running cycle's start, and its end should it end now."""
        detector = self._carrier.detector
        if (run := detector.run(self._key)) is None:
            return None
        attributes: dict[str, Any] = {}
        if run.since is not None:
            attributes["cycle_start"] = run.since
        if (end := detector.end_so_far(run)) is not None:
            attributes["cycle_end"] = end
        return attributes or None

    @override
    async def async_added_to_hass(self) -> None:
        """Show each step of the carrier's."""
        await super().async_added_to_hass()
        self.async_on_remove(self._carrier.subscribe(self._changed))

    @callback
    def _changed(self, changes: list[Change]) -> None:
        """Its phase's cycle ended: the state, then its signals; else the state."""
        ended = next(
            (c.cycle for c in changes if isinstance(c, Ended) and c.key == self._key),
            None,
        )
        if ended is not None:
            self._send(ended)
        else:
            self.async_write_ha_state()


class PhaseCurrent(PururuEntity, SensorEntity, RestoreEntity):
    """The phase that started last among those running, or idle; those running and seen as attributes."""

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, device: Device, carrier: Carrier, *, source: str) -> None:
        """Show `carrier`'s detector; `source`: the carrier's entity key."""
        self._identify(
            device, Platform.SENSOR, f"{PHASE}_current", translation=f"{PHASE}_current"
        )
        self.sources = (source,)
        self._carrier = carrier
        phases = carrier.detector.program.phases
        self._options = [IDLE, *(phase.key for phase in phases)]
        self._attr_options = self._options
        self._restored = IDLE

    @property
    @override
    def native_value(self) -> str:
        """The current phase; the restored one until the carrier restored the detector (another platform may add it first)."""
        if not self._carrier.ready:
            return self._restored
        return self._carrier.detector.current

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """The running phases, and those the program's current or last cycle saw, in the configuration's order."""
        detector = self._carrier.detector
        return {"running": detector.running, "seen": detector.seen}

    @override
    async def async_added_to_hass(self) -> None:
        """Take the restored phase, then show each step of the carrier's."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._options:
            self._restored = last.state
        self.async_on_remove(self._carrier.subscribe(self._changed))

    @callback
    def _changed(self, _changes: list[Change]) -> None:
        self.async_write_ha_state()


class PhaseLast(PururuEntity, RestoreSensor):
    """The phase of the last phase cycle that ended; it changes only when one ends."""

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, device: Device, program: Program, *, source: str) -> None:
        """Take the phase of every cycle `program`'s phases send; `source`: the carrier's entity key."""
        self._identify(
            device, Platform.SENSOR, f"{PHASE}_last", translation=f"{PHASE}_last"
        )
        self.sources = (source,)
        self._device = device
        self._phases = program.phases
        self._options = [phase.key for phase in program.phases]
        self._attr_options = self._options

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the last phase, then wait for the next phase cycle."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and last.native_value in self._options:
            self._attr_native_value = last.native_value
        for phase in self._phases:
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    cycle_signal(self._device, phase.item),
                    partial(self._record, phase.key),
                )
            )

    @callback
    def _record(self, key: str, _cycle: Cycle) -> None:
        self._attr_native_value = key
        self.async_write_ha_state()


def _translation(phase: Phase, suffix: str) -> str:
    """What a phase's cycle entity is named under: phase_<suffix> with {item}, or other's own."""
    return f"{PHASE}_{OTHER}_{suffix}" if phase.other else f"{PHASE}_{suffix}"


def _cycle_entities(
    hass: HomeAssistant, device: Device, phase: Phase, energy: str | None
) -> Iterator[PururuEntity]:
    """A phase's last cycle and totals, its energy with `energy`, all following its binary sensor."""
    item = phase.item
    source = item.slug
    for description in LAST_CYCLE:
        if energy is not None or description.key != "last_cycle_energy":
            yield LastCycleValue(
                device,
                description,
                source=source,
                item=item,
                translation=_translation(phase, description.key),
            )
    yield CyclesTotal(
        device,
        source=source,
        item=item,
        translation=_translation(phase, "cycles_total"),
    )
    yield RuntimeTotal(
        device,
        device.current_entity_id(hass, Platform.BINARY_SENSOR, source),
        STATE_ON,
        source=source,
        item=item,
        translation=_translation(phase, "runtime_total"),
    )
    if energy is not None:
        yield EnergyTotal(
            device,
            source=source,
            item=item,
            translation=_translation(phase, "energy_total"),
        )


def build(
    hass: HomeAssistant,
    device: Device,
    program: Program,
    *,
    key: str,
    reading: str,
    energy: str | None,
) -> list[PururuEntity]:
    """The program's carrier as `key`; with phases, the current and last phase and each phase's entities.

    The carrier comes first: its platform adds it, and it restores the
    detector, before the phases' binary sensors.
    """
    carrier = Carrier(device, key, program=program, reading=reading, energy=energy)
    entities: list[PururuEntity] = [carrier]
    if not program.phases:
        return entities
    entities.append(PhaseCurrent(device, carrier, source=key))
    entities.append(PhaseLast(device, program, source=key))
    for phase in program.phases:
        entities.append(PhaseRunning(device, carrier, phase, source=key))
        entities.extend(_cycle_entities(hass, device, phase, energy))
    return entities
