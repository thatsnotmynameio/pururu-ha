"""The base of every entity a device's features create, and reading a real sensor."""

import math

from homeassistant.const import Platform
from homeassistant.core import State
from homeassistant.helpers.entity import Entity

from .feature import Device


def reading(state: State | None) -> float | None:
    """A sensor's number, or None while it has none (unknown, unavailable, not finite)."""
    if state is None:
        return None
    try:
        value = float(state.state)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


class PururuEntity(Entity):
    """An entity of a configured device, named after its metric."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    # Metrics of its own device it takes its value from: without them it isn't created
    sources: tuple[str, ...] = ()

    def _identify(self, device: Device, platform: Platform, metric: str) -> None:
        """Take `device`'s entity ID, unique ID, device and name translation for `metric`."""
        self.entity_id = device.entity_id(platform, metric)
        self._attr_unique_id = device.object_id(metric)
        self._attr_device_info = device.info
        self._attr_translation_key = metric
