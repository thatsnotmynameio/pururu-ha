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
# A device's reactions: each one an automation pururu generates
CONF_REACTIONS: Final = "reactions"
# A reaction's message, and where messages go (a reaction's, a notification's, config's)
CONF_MESSAGE: Final = "message"
CONF_NOTIFY: Final = "notify"
# A device's ready-made notifications: feature key -> name -> settings
CONF_NOTIFICATIONS: Final = "notifications"
# A device's alerts: the feature whose alerts with notify Alert2 delivers
CONF_ALERTS: Final = "alerts"
# The key of the entry's data holding the IDs of the automations it generated
CONF_AUTOMATIONS: Final = "automations"
# Programs: a device's (executable, each one a script pururu generates) and a
# feature's (detected, each a band of its reading)
CONF_PROGRAMS: Final = "programs"
# The programs pururu runs: a device's, each one a script
CONF_EXECUTABLE: Final = "executable"
# The programs pururu tells from a reading: a feature's
CONF_DETECTED: Final = "detected"
# The key of the entry's data holding the IDs of the scripts it generated
CONF_SCRIPTS: Final = "scripts"
# Alert2 (HACS) delivers what an alert's notify says
ALERT2: Final = "alert2"
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
# pururu: config: settings of the whole house, not of a device
CONF_CONFIG: Final = "config"
# A device's lights, config: alerts: lights:, and an alert's lights
CONF_LIGHTS: Final = "lights"
# The alert lights group of an alert's `lights: true`
DEFAULT_ALERT_LIGHTS: Final = "default"
# Fired when the alert lights hand a light back: {"entity_id": the pururu light}
EVENT_ALERT_LIGHTS_RELEASED: Final = "pururu_alert_lights_released"
