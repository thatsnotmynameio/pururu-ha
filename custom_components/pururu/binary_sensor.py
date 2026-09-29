"""Binary sensors of the configured devices, built by the entry (see __init__.py)."""

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .runtime import PururuConfigEntry

# Nothing polls: every entity reacts to state changes and timers
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PururuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the binary sensors the entry built."""
    async_add_entities(entry.runtime_data[Platform.BINARY_SENSOR])
