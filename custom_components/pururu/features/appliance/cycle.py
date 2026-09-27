"""A finished cycle: the signals running sends it on, the last cycle's sensors, the count."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import override

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import Platform, UnitOfEnergy, UnitOfTime
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util.signal_type import SignalType

from ...const import DOMAIN
from ...entity import PururuEntity
from ...feature import Device


@dataclass(frozen=True, kw_only=True)
class Cycle:
    """A finished cycle, as running sends it."""

    start: datetime | None
    end: datetime
    energy_kwh: float | None

    @property
    def duration_min(self) -> float | None:
        """Minutes from start to end, when the start is known."""
        if self.start is None:
            return None
        return round((self.end - self.start).total_seconds() / 60, 1)


def cycle_signal(device: Device) -> SignalType[Cycle]:
    """Running sends each finished cycle here first."""
    return SignalType(f"{DOMAIN}_{device.key}_cycle")


def end_signal(device: Device) -> SignalType[Cycle]:
    """Then here, for last_cycle_end: what it triggers reads the rest already updated."""
    return SignalType(f"{DOMAIN}_{device.key}_cycle_end")


@dataclass(frozen=True, kw_only=True)
class LastCycleDescription(SensorEntityDescription):
    """One value of the last cycle."""

    value: Callable[[Cycle], datetime | float | None]
    written_last: bool = False


LAST_CYCLE: tuple[LastCycleDescription, ...] = (
    LastCycleDescription(
        key="last_cycle_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda cycle: cycle.start,
    ),
    LastCycleDescription(
        key="last_cycle_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value=lambda cycle: cycle.duration_min,
    ),
    LastCycleDescription(
        key="last_cycle_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value=lambda cycle: cycle.energy_kwh,
    ),
    LastCycleDescription(
        key="last_cycle_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda cycle: cycle.end,
        written_last=True,
    ),
)


class LastCycleValue(PururuEntity, RestoreSensor):
    """One value of the last finished cycle: it changes only when a cycle ends."""

    entity_description: LastCycleDescription
    sources = ("running",)  # its cycles

    def __init__(self, device: Device, description: LastCycleDescription) -> None:
        """Take `description`'s value from every cycle `device`'s running sends."""
        self.entity_description = description
        self._identify(device, Platform.SENSOR, description.key)
        self._signal = (
            end_signal(device) if description.written_last else cycle_signal(device)
        )

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the last value, then wait for the next cycle."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last.native_value
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._signal, self._record)
        )

    @callback
    def _record(self, cycle: Cycle) -> None:
        self._attr_native_value = self.entity_description.value(cycle)
        self.async_write_ha_state()


class CyclesTotal(PururuEntity, RestoreSensor):
    """Finished cycles, all time; the cycle meters (statistics.py) measure it."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    sources = ("running",)  # its cycles

    def __init__(self, device: Device) -> None:
        """Count the cycles `device`'s running sends."""
        self._identify(device, Platform.SENSOR, "cycles_total")
        self._signal = cycle_signal(device)
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
