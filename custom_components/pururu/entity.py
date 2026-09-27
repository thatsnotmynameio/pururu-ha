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
    """An entity of a configured device, named after its entity key."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    # Entity keys of its own device it takes its value from: without them it isn't created
    sources: tuple[str, ...] = ()

    def _identify(
        self,
        device: Device,
        platform: Platform,
        entity_key: str,
        name: str | None = None,
    ) -> None:
        """Take `device`'s entity ID, unique ID and device for `entity_key`, and a name.

        The name is `name` when given (an entity key from the configuration has
        no translation), else the translation of `entity_key`.
        """
        self.entity_id = device.entity_id(platform, entity_key)
        self._attr_unique_id = device.object_id(entity_key)
        self._attr_device_info = device.info
        if name is None:
            self._attr_translation_key = entity_key
        else:
            self._attr_name = name
