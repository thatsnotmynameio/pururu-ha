"""The plug's own readings inside the device, as HA's sensor group of one (type last)."""

from homeassistant.components.group.sensor import SensorGroup
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from ...entity import PururuEntity
from ...feature import Device


class Mirror(PururuEntity, SensorGroup):
    """One real sensor's value, unit and classes."""

    def __init__(
        self, hass: HomeAssistant, device: Device, entity_key: str, source: str
    ) -> None:
        """Follow `source` as `entity_key` of `device`."""
        SensorGroup.__init__(
            self, hass, None, entity_key, [source], False, "last", None, None, None
        )
        del self._attr_name  # the name comes from the entity key's translation
        self._identify(device, Platform.SENSOR, entity_key)
