"""A detected program: a band of a reading with delays, and its phases, each a band too (spec Part 4).

`schema` validates a program's block and describes it (`Program`); `detector`
is pure (readings and time in, cycles out); `entities` puts it in HA: the
program's carrier, and per phase a binary sensor and its cycle entities. A
builder reading a sensor calls `build` (the appliance's `running_program`), or
`build_detected` for a detected program of `programs: detected:` (the programs
aspect).
"""

from .detector import Change, Detector, Ended, Run, Started
from .entities import build, build_detected
from .schema import (
    DETECTED_AT,
    DETECTED_NAMED,
    DETECTED_SCHEMA,
    FIXED,
    IDLE,
    NAMED,
    OTHER,
    OTHER_DELAY,
    PHASE,
    PHASE_COUNTERS,
    SCHEMA,
    SUFFIXES,
    Band,
    Phase,
    Program,
    counted,
    counted_each,
    detected_keys,
    keys_of,
    phase_keys,
    program_of,
    unreserved,
)

__all__ = [
    "DETECTED_AT",
    "DETECTED_NAMED",
    "DETECTED_SCHEMA",
    "FIXED",
    "IDLE",
    "NAMED",
    "OTHER",
    "OTHER_DELAY",
    "PHASE",
    "PHASE_COUNTERS",
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
    "build_detected",
    "counted",
    "counted_each",
    "detected_keys",
    "keys_of",
    "phase_keys",
    "program_of",
    "unreserved",
]
