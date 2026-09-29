"""The mode of the last mode cycle that ended."""

from functools import partial
from typing import override

from homeassistant.components.sensor import RestoreSensor, SensorDeviceClass
from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from ...core.entity import PururuEntity
from ...core.feature import Device, Item
from ..cycle import Cycle, cycle_signal


class Last(PururuEntity, RestoreSensor):
    """The mode of the last mode cycle that ended; it changes only when one ends."""

    _attr_device_class = SensorDeviceClass.ENUM
    sources = ("current",)  # its cycles

    def __init__(self, device: Device, items: tuple[Item, ...]) -> None:
        """Take the mode of every cycle of `items` that current sends."""
        self._identify(device, Platform.SENSOR, "last")
        self._device = device
        self._items = items
        self._options = [item.slug for item in items]
        self._attr_options = self._options

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the last mode, then wait for the next cycle of any mode."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and isinstance(value := last.native_value, str):
            if value in self._options:
                self._attr_native_value = value
        for item in self._items:
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    cycle_signal(self._device, item),
                    partial(self._record, item.slug),
                )
            )

    @callback
    def _record(self, slug: str, _cycle: Cycle) -> None:
        self._attr_native_value = slug
        self.async_write_ha_state()
