"""The detector in HA: the program's carrier, and its phases' entities showing it."""

from collections.abc import Callable, Iterator, Mapping
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
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import STATE_ON, Platform
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.util import dt as dt_util

from ....const import DOMAIN
from ....core.entity import PururuEntity, reading
from ....core.feature import Device, Item
from .. import Cycle, CycleSource, cycle_signal
from ..energy import kwh_now
from ..last import LAST_CYCLE, LastCycleValue
from ..totals import CyclesTotal, EnergyTotal, RuntimeTotal
from .detector import Change, Detector, Ended
from .schema import DETECTED, IDLE, OTHER, PHASE, Phase, Program, program_of

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

    It follows the reading and waits for the detector's next delay, from once
    its entry's setup is over, whatever it gave: every view listens by then
    (`subscribe`, and the phases' cycle entities on their signals), so no
    step's cycle is lost; a setup failing after the platforms unloads them,
    and the removed carrier never starts; if that unload fails too, HA keeps
    the entities and the carrier runs them. It wraps its phases: a step writes its own state, then calls each view with
    the step's changes; a step that ends the program calls the views first,
    then writes its state and sends the program's cycle. A reading's step
    comes after, in its own step, the delays a late timer missed: a program
    ended and started again by one reading shows `off` in between, and the
    same for a phase ending late and starting again on that one reading.
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
        of: Item | None = None,
    ) -> None:
        """`program` read from `reading`, as `key` of `device`; `energy` gives each cycle's kWh.

        `of`: a detected program's item, naming the carrier and its signals;
        None: the builder's running program, named by `key`'s translation.
        """
        self._identify(
            device, Platform.BINARY_SENSOR, key, None if of is None else of.name
        )
        self._cycle_signals(device, of)
        self.detector = Detector(program)
        self._reading = reading
        self._energy = energy
        # Replaced, never changed in place: a step calls the views it started with
        self._views: tuple[View, ...] = ()
        # Whether the detector holds what was restored: until then, a view shows its own
        self.ready = False
        # Whether it follows the reading: once its entry's setup is over
        self._started = False
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
        """Call `view` with each step's changes (after the carrier's state; before it when the program ends); returns the unsubscribe."""
        self._views = (*self._views, view)
        return partial(self._unsubscribe, view)

    @callback
    def _unsubscribe(self, view: View) -> None:
        self._views = tuple(each for each in self._views if each is not view)

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the detector; follow the reading once the entry's setup is over, every view listening.

        A step at add could end a restored phase before its entities listen
        (on this platform, added after the carrier; on another, maybe not
        added yet), and its cycle would be lost. Over whatever it gave: a
        setup failing after its platforms unloads them, and removing the
        carrier unsubscribes the wait; if that unload fails too, HA keeps the
        entities of the SETUP_ERROR entry, and the carrier runs them.
        """
        await super().async_added_to_hass()
        if (extra := await self.async_get_last_extra_data()) is not None:
            self._restore(extra.as_dict())
        self.ready = True
        self.async_on_remove(self._cancel_timer)
        entry = self.platform.config_entry
        if entry is None or entry.state is not ConfigEntryState.SETUP_IN_PROGRESS:
            self._start()
        else:
            self.async_on_remove(
                entry.async_on_state_change(partial(self._entry_changed, entry))
            )

    def _restore(self, data: Any) -> None:
        """Take back the snapshot; one that isn't a map (a hand-edited .storage) is none.

        The detector drops what it can't read in a map: a time without a zone,
        an impossible date, a key no longer configured.
        """
        if isinstance(data, Mapping):
            self.detector.restore(data)

    @callback
    def _entry_changed(self, entry: ConfigEntry[Any]) -> None:
        # Not unsubscribed here: HA iterates its callbacks while calling them
        if not self._started and entry.state is not ConfigEntryState.SETUP_IN_PROGRESS:
            self._start()

    @callback
    def _start(self) -> None:
        """Follow the reading from its current state."""
        self._started = True
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._reading, self._reading_changed
            )
        )
        self._read(self.hass.states.get(self._reading))

    @callback
    def _read(self, state: State | None) -> None:
        """Show a reading: first, in its own step, what a late timer missed.

        One reading can end the program (its off_delay passed, the timer not
        run yet) and start it again (on_delay 0): the end is shown first, `off`
        and its phases' ends, then the reading's step shows the new cycle.
        """
        now = dt_util.utcnow()
        kwh = kwh_now(self.hass, self._energy)
        if missed := self.detector.catch_up(now, kwh):
            self._step(missed)
        self._step(self.detector.read(reading(state), now, kwh))

    @callback
    def _reading_changed(self, event: Event[EventStateChangedData]) -> None:
        self._read(event.data["new_state"])

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
        """Show a step, then wait for the next delay.

        The carrier's state, then each view; when the program ends, each view
        first, then the carrier's state and the program's cycle: its end
        comes with its phases' ended (the events' states agree).
        """
        ended = next(
            (c.cycle for c in changes if isinstance(c, Ended) and c.key is None), None
        )
        if ended is None:
            self.async_write_ha_state()
        for view in self._views:
            view(changes)
        if ended is not None:
            self._send(ended)
        self._cancel_timer()
        if (due := self.detector.due()) is not None:
            self._timer = async_track_point_in_utc_time(
                self.hass, self._delay_passed, due
            )


class PhaseRunning(CycleSource, BinarySensorEntity):
    """On while its phase runs: the source of the phase's cycles.

    Added after the carrier on the same platform, so the detector is restored
    by then: its first state is already the restored one. That holds because
    `build` puts the carrier first, `binary_sensor.py` hands a platform's
    entities to one `async_add_entities`, and HA's `EntityPlatform` adds them
    one by one, each awaited; splitting that call would break it.
    """

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(
        self, device: Device, carrier: Carrier, phase: Phase, *, source: str
    ) -> None:
        """Show `phase` of `carrier`'s detector; `source`: the carrier's entity key."""
        item = phase.item
        if phase.other and phase.of is not None:
            # <of>_phase_other, named with its program's name
            self._identify(
                device,
                Platform.BINARY_SENSOR,
                f"{PHASE}_{OTHER}",
                item=phase.of,
                translation=f"{DETECTED}_{PHASE}_{OTHER}",
            )
        elif phase.other:
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
    """The phase that started last among those running, or idle; its name, and those running and seen, as attributes.

    Its state is the phase's key, translated only for idle and other; its
    `name` attribute is a configured phase's `name`, None for idle and other
    (their state is translated already). Until the carrier restored the
    detector (another platform may add it first), it shows its own restored
    state and attributes, named as that phase is now. A disabled carrier
    never runs the detector: it shows idle, as every phase shows off.
    """

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(
        self, device: Device, carrier: Carrier, *, source: str, of: Item | None = None
    ) -> None:
        """Show `carrier`'s detector; `source`: the carrier's entity key; `of`: a detected program's item."""
        self._identify(
            device,
            Platform.SENSOR,
            f"{PHASE}_current",
            item=of,
            translation=_fixed(f"{PHASE}_current", of),
        )
        self.sources = (source,)
        self._carrier = carrier
        phases = carrier.detector.program.phases
        self._phases = [phase.key for phase in phases]
        # Only a configured phase's: idle's and other's state is translated already
        self._names = {phase.key: phase.name for phase in phases if not phase.other}
        self._options = [IDLE, *self._phases]
        self._attr_options = self._options
        self._restored = IDLE
        self._restored_attributes: dict[str, Any] = {"running": [], "seen": []}

    @property
    @override
    def native_value(self) -> str:
        """The current phase; the restored one until the carrier restored the detector."""
        if not self._carrier.ready:
            return self._restored
        return self._carrier.detector.current

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """The shown phase's name; the running phases, and those the program's current or last cycle saw, in the configuration's order (the restored ones until the carrier restored the detector)."""
        if not self._carrier.ready:
            phases = self._restored_attributes
        else:
            detector = self._carrier.detector
            phases = {"running": detector.running, "seen": detector.seen}
        return {"name": self._names.get(self.native_value), **phases}

    @override
    async def async_added_to_hass(self) -> None:
        """Take the restored phase, unless the carrier is disabled; then show each step of the carrier's."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if (
            last is not None
            and last.state in self._options
            and not self._carrier_disabled()
        ):
            self._restored = last.state
            own = [] if last.state == IDLE else [last.state]
            self._restored_attributes = {
                name: self._known(last.attributes.get(name), own)
                for name in ("running", "seen")
            }
        self.async_on_remove(self._carrier.subscribe(self._changed))

    def _carrier_disabled(self) -> bool:
        """Whether the user disabled the carrier: HA never adds it."""
        registry = er.async_get(self.hass)
        found = registry.async_get_entity_id(
            Platform.BINARY_SENSOR, DOMAIN, str(self._carrier.unique_id)
        )
        entry = None if found is None else registry.async_get(found)
        return entry is not None and entry.disabled

    def _known(self, value: Any, default: list[str]) -> list[str]:
        """A restored list of phases, in the configuration's order; `default` when it isn't one."""
        if not isinstance(value, list) or not all(
            isinstance(key, str) and key in self._phases for key in value
        ):
            return default
        return [key for key in self._phases if key in value]

    @callback
    def _changed(self, _changes: list[Change]) -> None:
        self.async_write_ha_state()


class PhaseLast(PururuEntity, RestoreSensor):
    """The phase of the last phase cycle that ended; it changes only when one ends."""

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(
        self, device: Device, program: Program, *, source: str, of: Item | None = None
    ) -> None:
        """Take the phase of every cycle `program`'s phases send; `source`: the carrier's entity key; `of`: a detected program's item."""
        self._identify(
            device,
            Platform.SENSOR,
            f"{PHASE}_last",
            item=of,
            translation=_fixed(f"{PHASE}_last", of),
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


def _fixed(key: str, of: Item | None) -> str:
    """What the current or last phase is named under: its key, or detected_<key> with {item} in a detected program."""
    return key if of is None else f"{DETECTED}_{key}"


def _translation(phase: Phase, suffix: str) -> str:
    """What a phase's cycle entity is named under: phase_<suffix> with {item}, or other's own (a detected program's, with {item})."""
    if not phase.other:
        return f"{PHASE}_{suffix}"
    return _fixed(f"{PHASE}_{OTHER}_{suffix}", phase.of)


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
    of: Item | None = None,
) -> list[PururuEntity]:
    """The program's carrier as `key`; with phases, the current and last phase and each phase's entities.

    The carrier comes first: its platform adds it, and it restores the
    detector, before the phases' binary sensors. `of`: a detected program's
    item (Carrier), None the builder's running program.
    """
    carrier = Carrier(
        device, key, program=program, reading=reading, energy=energy, of=of
    )
    entities: list[PururuEntity] = [carrier]
    if not program.phases:
        return entities
    entities.append(PhaseCurrent(device, carrier, source=key, of=of))
    entities.append(PhaseLast(device, program, source=key, of=of))
    for phase in program.phases:
        entities.append(PhaseRunning(device, carrier, phase, source=key))
        entities.extend(_cycle_entities(hass, device, phase, energy))
    return entities


def build_detected(
    hass: HomeAssistant,
    device: Device,
    key: str,
    config: Mapping[str, Any],
    *,
    reading: str,
    energy: str | None,
) -> list[PururuEntity]:
    """Detected program `key` of a builder's `programs: detected:`: its carrier and phases, then its own cycle entities.

    Its carrier is `key`, named by the program's name; its last cycle and
    totals are its item's (<key>_<suffix>), named detected_<suffix> with {item}.
    """
    of = Item(slug=key, name=config["name"])
    entities = build(
        hass,
        device,
        program_of(config, of),
        key=key,
        reading=reading,
        energy=energy,
        of=of,
    )
    for description in LAST_CYCLE:
        if energy is not None or description.key != "last_cycle_energy":
            entities.append(
                LastCycleValue(
                    device,
                    description,
                    source=key,
                    item=of,
                    translation=f"{DETECTED}_{description.key}",
                )
            )
    entities.append(
        CyclesTotal(device, source=key, item=of, translation=f"{DETECTED}_cycles_total")
    )
    entities.append(
        RuntimeTotal(
            device,
            device.current_entity_id(hass, Platform.BINARY_SENSOR, key),
            STATE_ON,
            source=key,
            item=of,
            translation=f"{DETECTED}_runtime_total",
        )
    )
    if energy is not None:
        entities.append(
            EnergyTotal(
                device, source=key, item=of, translation=f"{DETECTED}_energy_total"
            )
        )
    return entities
