"""The base of every entity a device's features create, and reading a real sensor or a time."""

from datetime import datetime
import math
from typing import Any, override

from homeassistant.const import ATTR_RESTORED, Platform
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.util import dt as dt_util

from .feature import Device, Item, item_key
from .resolve import DEVICE

# The state attribute showing an entity's reference: from inside its device, and from another
REFERENCE = "reference"


def reading(state: State | None) -> float | None:
    """A sensor's number, or None while it has none (unknown, unavailable, not finite)."""
    if state is None:
        return None
    try:
        value = float(state.state)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def as_time(value: Any) -> datetime | None:
    """A time read back (a state, an attribute, .storage); None for anything else.

    A string shaped as a time can still name no such day or month (a
    hand-edited .storage, a broken sensor): it is none too, never an error.
    """
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return dt_util.parse_datetime(value)
    except ValueError:  # well-formed, but no such day or month
        return None


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
    """An entity of a configured device, named after its entity key, showing its reference."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    # Static, and kept in the registry entry: history needn't repeat it
    _unrecorded_attributes = frozenset({REFERENCE})
    # Entity keys of its own device it takes its value from: without them it isn't created
    sources: tuple[str, ...] = ()
    # Paths of other features' entities of its device it reads
    # (appliance.running_program): without them it isn't created either
    follows: tuple[str, ...] = ()
    # Its entity key in its namespace (appliance_running)
    key: str
    # Its node in its device's YAML (appliance.running_program), and its
    # device's key: stamped by build from the index once it is built
    path: str
    device_key: str

    @override
    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Leave out of history what any base leaves out, and the reference.

        Entity reads the one `_unrecorded_attributes` the class finds first:
        PururuEntity comes before GroupEntity (entity_id, group_entities) and
        UtilityMeterSensor (next_reset), so its own set alone would hide
        theirs, and history would keep them.
        """
        cls._unrecorded_attributes = frozenset[str]().union(
            *(vars(base).get("_unrecorded_attributes", ()) for base in cls.__mro__)
        )
        super().__init_subclass__(**kwargs)

    @property
    @override
    def capability_attributes(self) -> dict[str, Any]:
        """Its base's, and its reference in both forms.

        A capability attribute: HA writes it while the entity is unavailable
        too, when it is most needed (an alert on an offline plug).
        """
        return {
            **(super().capability_attributes or {}),
            REFERENCE: {
                "inside": self.path,
                "outside": f"{DEVICE}.{self.device_key}.{self.path}",
            },
        }

    def _identify(
        self,
        device: Device,
        platform: Platform,
        entity_key: str,
        name: str | None = None,
        *,
        item: Item | None = None,
        translation: str | None = None,
    ) -> None:
        """Take `device`'s entity ID, unique ID and device for `entity_key`, and a name.

        The name is `name` when given (an entity key from the configuration has
        no translation, even when the base class brings one, as LightGroup's
        "light"), else the translation of the key in its namespace. With `item`,
        `entity_key` is a suffix (roles.Items): the entity key is the
        item's, and its name the suffix's translation, the item's name as the
        placeholder named after the namespace ({program}). With `translation` (an
        aspect's key, named once for every builder), the name is that
        translation key's, the item's name as the placeholder {item}.
        """
        key = item_key(entity_key, item)
        self.key = device.qualified(key)
        self.entity_id = device.entity_id(platform, key)
        self._attr_unique_id = device.object_id(key)
        self._attr_device_info = device.info
        if translation is not None:
            self._attr_translation_key = translation
            if item is not None:
                self._attr_translation_placeholders = {"item": item.name}
        elif name is None:
            self._attr_translation_key = device.qualified(entity_key)
            if item is not None:
                self._attr_translation_placeholders = {device.namespace: item.name}
        else:
            self._attr_name = name
            self._attr_translation_key = None
