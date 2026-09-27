"""Names shared by the integration's modules."""

from typing import Any, Final

from homeassistant.const import Platform
from homeassistant.util.hass_dict import HassKey

DOMAIN: Final = "pururu"
CONF_DEVICES: Final = "devices"
CONF_FLOORS: Final = "floors"
CONF_AREAS: Final = "areas"
# Keys of a floor's or an area's block (name and icon are HA's CONF_NAME, CONF_ICON)
CONF_FLOOR: Final = "floor"
CONF_LEVEL: Final = "level"
CONF_ALIASES: Final = "aliases"
# A device's area: a key of areas
CONF_AREA: Final = "area"
# Every entity ID is <platform>.pururu_<device key>_<namespace>_<entity key>
ENTITY_PREFIX: Final = "pururu"
PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]
# The validated `pururu:` block, from async_setup (and each reload) to the entry
DATA_CONFIG: HassKey[dict[str, Any]] = HassKey(DOMAIN)
