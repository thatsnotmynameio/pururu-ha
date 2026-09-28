"""Device keys that aren't features but create entities of the device: their statistics.

A device's programs and reactions (programs.py, reactions.py) are generated
files; each program's runs are sensors of the device, built as a Feature's
entities are. They don't count as a device's feature.
"""

from . import programs
from .feature import Feature

DEVICE_KEYS: dict[str, Feature] = {"programs": programs.STATISTICS}
