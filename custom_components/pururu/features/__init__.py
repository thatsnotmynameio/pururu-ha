"""Every feature a device can have, by its key in the device's configuration."""

from ..core.feature import Feature
from .appliance import APPLIANCE
from .buttons import BUTTONS
from .lights import LIGHTS
from .opening import DOOR, WINDOW
from .switches import SWITCHES

FEATURES: dict[str, Feature] = {
    "appliance": APPLIANCE,
    "door": DOOR,
    "window": WINDOW,
    "lights": LIGHTS,
    "switches": SWITCHES,
    "buttons": BUTTONS,
}
