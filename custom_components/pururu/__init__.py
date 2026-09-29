"""pururu: floors, areas and devices configured in YAML, which the integration creates.

`pururu: floors:` and `areas:` map an ID to a floor or an area (outputs/places.py).
`pururu: devices:` maps a device key to its name and features (features/).
From the real entities and settings in a feature's block, the feature creates
the device's entities. One config entry owns every floor, area, device and entity.

This module holds HA's entry points only; what they do is in setup/lifecycle.py.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .core.runtime import PururuConfigEntry
from .setup import lifecycle
from .setup.schema import CONFIG_SCHEMA as CONFIG_SCHEMA


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Keep the configuration for the entry, and apply it again on reload."""
    return await lifecycle.async_setup(hass, config)


async def async_setup_entry(hass: HomeAssistant, entry: PururuConfigEntry) -> bool:
    """Make floors and areas follow the configuration, then build every device."""
    return await lifecycle.async_setup_entry(hass, entry)


async def async_unload_entry(hass: HomeAssistant, entry: PururuConfigEntry) -> bool:
    """Remove the entities; a reload builds them again."""
    return await lifecycle.async_unload_entry(hass, entry)


async def async_remove_entry(hass: HomeAssistant, entry: PururuConfigEntry) -> None:
    """Delete everything the entry managed."""
    await lifecycle.async_remove_entry(hass, entry)
