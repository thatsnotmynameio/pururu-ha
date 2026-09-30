"""Every feature a device can have, by its key in the device's configuration."""

from ..core.feature import Feature
from .appliance import APPLIANCE
from .lights import LIGHTS
from .modes import MODES
from .opening import DOOR, WINDOW
from .phases import PHASES
from .switches import SWITCHES

FEATURES: dict[str, Feature] = {
    "appliance": APPLIANCE,
    "door": DOOR,
    "window": WINDOW,
    "lights": LIGHTS,
    "phases": PHASES,
    "modes": MODES,
    "switches": SWITCHES,
}
