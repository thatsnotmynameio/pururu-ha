"""The last finished cycle's values: they change only when a cycle ends."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import override

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntityDescription,
)
from homeassistant.const import Platform, UnitOfEnergy, UnitOfTime
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from ...core.entity import PururuEntity
from ...core.feature import Device, Item
from . import Cycle, cycle_signal, end_signal


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
        value=lambda cycle: (
            None if cycle.energy_kwh is None else round(cycle.energy_kwh, 3)
        ),
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

    def __init__(
        self,
        device: Device,
        description: LastCycleDescription,
        *,
        source: str,
        item: Item | None = None,
    ) -> None:
        """Take `description`'s value from every cycle (of `item`) that `source` sends."""
        self.entity_description = description
        self.sources = (source,)
        self._identify(device, Platform.SENSOR, description.key, item=item)
        self._signal = (
            end_signal(device, item)
            if description.written_last
            else cycle_signal(device, item)
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
