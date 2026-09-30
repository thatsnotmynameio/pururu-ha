"""A detected program: a band of a reading with delays, and its phases, each a band too (spec Part 4).

`schema` validates a program's block and describes it (`Program`); `detector`
is pure: readings and time in, cycles out.
"""

from .detector import Change, Detector, Ended, Run, Started
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
    "phase_keys",
    "program_of",
]
