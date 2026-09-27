"""Buttons of the configured devices (programs), built by the entry (see __init__.py)."""

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PururuConfigEntry

# Nothing polls, and a press only starts a program
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PururuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the buttons the entry built."""
    async_add_entities(entry.runtime_data[Platform.BUTTON])
