"""The base of every entity a device's features create, and reading a real sensor."""

import math

from homeassistant.const import ATTR_RESTORED, Platform
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity

from .feature import Device, Item, item_key


def reading(state: State | None) -> float | None:
    """A sensor's number, or None while it has none (unknown, unavailable, not finite)."""
    if state is None:
        return None
    try:
        value = float(state.state)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def other_holder(
    hass: HomeAssistant, registry: er.EntityRegistry, entity_id: str
) -> str | None:
    """Who holds `entity_id`, once it isn't ours: another integration, an entity without unique ID, or no one.

    A restored placeholder holds nothing: it is what HA shows for an entity not
    loaded yet.
    """
    if (registered := registry.async_get(entity_id)) is not None:
        return f"the {registered.platform} integration"
    if (state := hass.states.get(entity_id)) is not None and not state.attributes.get(
        ATTR_RESTORED
    ):
        return "an entity without a unique ID"
    return None


class PururuEntity(Entity):
    """An entity of a configured device, named after its entity key."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    # Entity keys of its own device it takes its value from: without them it isn't created
    sources: tuple[str, ...] = ()
    # Entity keys of other features of its device, in their namespace, it reads:
    # without them it isn't created either
    follows: tuple[str, ...] = ()
    # Its entity key in its namespace (appliance_running), and <device key>.<that key>
    key: str
    reference: str

    def _identify(
        self,
        device: Device,
        platform: Platform,
        entity_key: str,
        name: str | None = None,
        *,
        item: Item | None = None,
    ) -> None:
        """Take `device`'s entity ID, unique ID and device for `entity_key`, and a name.

        The name is `name` when given (an entity key from the configuration has
        no translation, even when the base class brings one, as LightGroup's
        "light"), else the translation of the key in its namespace. With `item`,
        `entity_key` is a suffix (Feature.per_item): the entity key is the
        item's, and its name the suffix's translation, the item's name as the
        placeholder named after the namespace ({mode}).
        """
        key = item_key(entity_key, item)
        self.key = device.qualified(key)
        self.reference = f"{device.key}.{self.key}"
        self.entity_id = device.entity_id(platform, key)
        self._attr_unique_id = device.object_id(key)
        self._attr_device_info = device.info
        if name is None:
            self._attr_translation_key = device.qualified(entity_key)
            if item is not None:
                self._attr_translation_placeholders = {device.namespace: item.name}
        else:
            self._attr_name = name
            self._attr_translation_key = None
