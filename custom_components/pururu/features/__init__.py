"""Every feature a device can have, by its key in the device's configuration."""

from ..feature import Feature
from .appliance import APPLIANCE
from .phases import PHASES

FEATURES: dict[str, Feature] = {"appliance": APPLIANCE, "phases": PHASES}
