"""Every feature a device can have, by its key in the device's configuration."""

from ..feature import Feature
from .alerts import ALERTS
from .appliance import APPLIANCE
from .phases import PHASES
from .switches import SWITCHES

FEATURES: dict[str, Feature] = {
    "appliance": APPLIANCE,
    "phases": PHASES,
    "switches": SWITCHES,
    "alerts": ALERTS,
}
