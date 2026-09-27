"""Names shared by the integration's modules."""

from typing import Any, Final

from homeassistant.const import Platform
from homeassistant.util.hass_dict import HassKey

DOMAIN: Final = "pururu"
CONF_DEVICES: Final = "devices"
# Every entity ID is <platform>.pururu_<device key>_<metric>
ENTITY_PREFIX: Final = "pururu"
PLATFORMS: Final = [Platform.BINARY_SENSOR, Platform.SENSOR]
# The configured devices, from async_setup (and each reload) to the entry
DATA_DEVICES: HassKey[dict[str, dict[str, Any]]] = HassKey(DOMAIN)
