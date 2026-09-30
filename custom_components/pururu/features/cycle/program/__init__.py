"""A detected program: a band of a reading with delays, and its phases, each a band too (spec Part 4).

`schema` validates a program's block and describes it (`Program`); `detector`
is pure (readings and time in, cycles out); `entities` puts it in HA: the
program's carrier, and per phase a binary sensor and its cycle entities. A
builder reading a sensor calls `build` (D2: the appliance's `running_program`).
"""

from .detector import Change, Detector, Ended, Run, Started
from .entities import build
from .schema import (
    COUNTERS,
    FIXED,
    IDLE,
    NAMED,
    OTHER,
    OTHER_DELAY,
    PHASE,
    SCHEMA,
    SUFFIXES,
    Band,
    Phase,
    Program,
    keys_of,
    phase_keys,
    program_of,
)

__all__ = [
    "COUNTERS",
    "FIXED",
    "IDLE",
    "NAMED",
    "OTHER",
    "OTHER_DELAY",
    "PHASE",
    "SCHEMA",
    "SUFFIXES",
    "Band",
    "Change",
    "Detector",
    "Ended",
    "Phase",
    "Program",
    "Run",
    "Started",
    "build",
    "keys_of",
    "phase_keys",
    "program_of",
]
