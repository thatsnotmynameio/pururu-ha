"""Device keys that aren't features but create entities of the device: their statistics, alerts and goals.

A device's executable programs (aspects/programs.py) and its reactions
(reactions.py) are generated files; each program's runs and each reaction's
triggers are sensors of the device, built as a Feature's entities are.
`alerts` (aspects/alerts.py) is hand-written alerts on the device's own
entities; `goals` (goals.py) each goal's target and what was done. None of
them count as a device's feature.
"""

from ..aspects.alerts import ALERTS
from ..aspects.programs import PROGRAMS
from ..core.feature import Feature
from . import goals, reactions

DEVICE_KEYS: dict[str, Feature] = {
    "programs": PROGRAMS,
    "reactions": reactions.STATISTICS,
    "alerts": ALERTS,
    "goals": goals.GOALS,
}
