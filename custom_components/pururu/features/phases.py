"""The phase of a cycle, from bands of a sensor's value: the first band that holds, in order."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any, override

import voluptuous as vol

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
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from ..entity import PururuEntity, reading
from ..feature import Device, Feature, finite_float


@dataclass(frozen=True, kw_only=True)
class Band:
    """A range of the sensor's value that is a phase once the value stays in it for `hold`."""

    name: str
    above: float | None
    below: float | None
    hold: timedelta

    def contains(self, value: float) -> bool:
        """Strictly above `above` and strictly below `below`, as HA's numeric_state."""
        return (self.above is None or value > self.above) and (
            self.below is None or value < self.below
        )


def _bounded(band: dict[str, Any]) -> dict[str, Any]:
    if "above" not in band and "below" not in band:
        raise vol.Invalid("a band needs above, below or both")
    if "above" in band and "below" in band and band["above"] >= band["below"]:
        raise vol.Invalid("a band's above must be lower than its below")
    return band


def _distinct(config: dict[str, Any]) -> dict[str, Any]:
    names = [
        config["defaults"]["stopped"],
        config["defaults"]["running"],
        *config["bands"],
    ]
    if len(set(names)) != len(names):
        raise vol.Invalid(f"phase names must differ: {names}")
    return config


BAND = vol.All(
    {
        vol.Optional("above"): finite_float,
        vol.Optional("below"): finite_float,
        vol.Optional("for", default=timedelta(0)): cv.positive_time_period,
    },
    _bounded,
)
SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("cycle_from"): cv.slug,
            vol.Required("sensor"): cv.entity_id,
            vol.Required("defaults"): {
                vol.Required("stopped"): cv.slug,
                vol.Required("running"): cv.slug,
            },
            vol.Required("bands"): vol.All({cv.slug: BAND}, vol.Length(min=1)),
        }
    ),
    _distinct,
)


class Phase(PururuEntity, SensorEntity, RestoreEntity):
    """The first band that holds while the cycle runs; the defaults otherwise."""

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(
        self,
        device: Device,
        *,
        cycle: str,
        sensor: str,
        stopped: str,
        running: str,
        bands: tuple[Band, ...],
    ) -> None:
        """Follow `sensor` through `bands` while `cycle` is on."""
        self._identify(device, Platform.SENSOR, "current")
        self._cycle = cycle
        self._sensor = sensor
        self._stopped = stopped
        self._running = running
        self._bands = bands
        self._options: list[str] = [stopped, running, *(band.name for band in bands)]
        self._attr_options = self._options
        self._attr_native_value = stopped
        self._inside: set[str] = set()  # bands the value is in
        self._held: set[str] = set()  # bands it has been in for their `for`
        self._timers: dict[str, CALLBACK_TYPE] = {}
        self._seen: list[str] = []
        self._read = False  # a reading since added: until then, the phase holds

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """The bands that held during the current or last cycle."""
        return {"seen": list(self._seen)}

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the phase and what it saw, then follow the sensor and the cycle."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            if last.state in self._options:
                self._attr_native_value = last.state
            seen = last.attributes.get("seen")
            if isinstance(seen, list):
                self._seen = [band.name for band in self._bands if band.name in seen]
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._sensor, self._sensor_changed
            )
        )
        self.async_on_remove(
            async_track_state_change_event(self.hass, self._cycle, self._cycle_changed)
        )
        self.async_on_remove(self._cancel_timers)
        if self._take(self.hass.states.get(self._sensor)):
            self._update()

    @callback
    def _cancel_timers(self) -> None:
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()

    @callback
    def _take(self, state: State | None) -> bool:
        """Note which bands a reading is in; False for a reading without a value.

        A reading without a value stops every band still counting its `for`, as
        HA's numeric_state does: it counts again from the next reading inside
        it. Bands that already hold, and the phase, stay.
        """
        if (value := reading(state)) is None:
            for name in self._timers:
                self._inside.discard(name)
            self._cancel_timers()
            return False
        for band in self._bands:
            if not band.contains(value):
                self._inside.discard(band.name)
                self._held.discard(band.name)
                if (cancel := self._timers.pop(band.name, None)) is not None:
                    cancel()
            elif band.name not in self._inside:
                self._inside.add(band.name)
                if band.hold:
                    self._timers[band.name] = async_call_later(
                        self.hass, band.hold, partial(self._band_held, band.name)
                    )
                else:
                    self._held.add(band.name)
        self._read = True
        return True

    @callback
    def _band_held(self, name: str, _now: datetime) -> None:
        self._timers.pop(name, None)
        self._held.add(name)
        self._update()
        self.async_write_ha_state()

    @callback
    def _sensor_changed(self, event: Event[EventStateChangedData]) -> None:
        if self._take(event.data["new_state"]):
            self._update()
            self.async_write_ha_state()

    @callback
    def _cycle_changed(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if (
            old is not None
            and old.state == STATE_OFF
            and new is not None
            and new.state == STATE_ON
        ):
            self._seen = []  # a cycle starts (a restore comes from no state, not from off)
        self._update()
        self.async_write_ha_state()

    @callback
    def _update(self) -> None:
        """The phase from the cycle and the bands that hold; it holds while either is unknown."""
        cycle = self.hass.states.get(self._cycle)
        if cycle is None or cycle.state not in (STATE_ON, STATE_OFF):
            return
        if cycle.state == STATE_OFF:
            self._attr_native_value = self._stopped
            return
        if not self._read:
            return
        holding = next(
            (band.name for band in self._bands if band.name in self._held), None
        )
        self._attr_native_value = holding or self._running
        if holding is not None and holding not in self._seen:
            self._seen = [
                band.name
                for band in self._bands
                if band.name in self._seen or band.name == holding
            ]


def build(
    hass: HomeAssistant,
    device: Device,
    config: dict[str, Any],
    inputs: Mapping[str, str],
) -> list[PururuEntity]:
    """The phase sensor."""
    bands = tuple(
        Band(
            name=name,
            above=band.get("above"),
            below=band.get("below"),
            hold=band["for"],
        )
        for name, band in config["bands"].items()
    )
    return [
        Phase(
            device,
            cycle=inputs["cycle"],
            sensor=config["sensor"],
            stopped=config["defaults"]["stopped"],
            running=config["defaults"]["running"],
            bands=bands,
        )
    ]


PHASES = Feature(
    schema=SCHEMA,
    entity_keys={"current": Platform.SENSOR},
    build=build,
    example={
        "cycle_from": "appliance",
        "sensor": "sensor.demo_plug_power",
        "defaults": {"stopped": "idle", "running": "washing"},
        "bands": {"heating": {"above": 1000}},
    },
    namespace="phase",
    requires=("cycle",),
)
