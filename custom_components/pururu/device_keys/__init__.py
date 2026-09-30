"""Device keys that aren't features but create entities of the device: their statistics, and alerts.

A device's programs and reactions (programs.py, reactions.py) are generated
files; each program's runs and each reaction's triggers are sensors of the
device, built as a Feature's entities are. `alerts` (aspects/alerts.py) is
hand-written alerts on the device's own entities. None of them count as a
device's feature.
"""

from ..aspects.alerts import ALERTS
from ..core.feature import Feature
from . import programs, reactions

DEVICE_KEYS: dict[str, Feature] = {
    "programs": programs.STATISTICS,
    "reactions": reactions.STATISTICS,
    "alerts": ALERTS,
}
