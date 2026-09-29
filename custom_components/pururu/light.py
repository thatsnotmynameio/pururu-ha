"""Lights of the configured devices, built by the entry (see setup/lifecycle.py)."""

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .core.runtime import PururuConfigEntry

# Nothing polls, and a command goes straight on to the real light
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PururuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the lights the entry built."""
    async_add_entities(entry.runtime_data[Platform.LIGHT])
