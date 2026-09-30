"""A detected program's block, and the program it describes: a band of a reading, and its phases."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv

from ....core.feature import TEXT, Item, bounded, finite_float
from ....core.roles import Counters
from ..last import LAST_CYCLE

# The current phase while none runs
IDLE = "idle"
# The built-in phase: the program runs outside every configured phase's band
OTHER = "other"
# Every phase's entity keys start with it: phase_<key>, phase_<key>_<suffix>
PHASE = "phase"
# other's delays when `other:` doesn't set them: a chill's 2-s spike is no phase
OTHER_DELAY = timedelta(seconds=30)

# A phase's cycle entities: phase_<key>_<suffix>
SUFFIXES: dict[str, Platform] = {
    **{description.key: Platform.SENSOR for description in LAST_CYCLE},
    "cycles_total": Platform.SENSOR,
    "runtime_total": Platform.SENSOR,
    "energy_total": Platform.SENSOR,
}
# The detector's own entity keys; the program's carrier is its builder's (the appliance's `running`)
FIXED: dict[str, Platform] = {
    f"{PHASE}_current": Platform.SENSOR,
    f"{PHASE}_last": Platform.SENSOR,
}
# The translation key of each entity the detector names, once for every builder,
# outside every namespace. A configured phase's binary sensor is named by its
# `name`; its cycle entities by phase_<suffix> with {item}; other's by phase_other*.
NAMED: dict[str, Platform] = {
    **FIXED,
    f"{PHASE}_{OTHER}": Platform.BINARY_SENSOR,
    **{f"{PHASE}_{suffix}": platform for suffix, platform in SUFFIXES.items()},
    **{f"{PHASE}_{OTHER}_{suffix}": platform for suffix, platform in SUFFIXES.items()},
}
# Each phase's totals, for the statistics aspect to meter (D2 mounts it); energy needs `energy`
COUNTERS = Counters({"runtime": None, "cycles": None, "energy": "energy"})


def phase_keys(key: str) -> dict[str, Platform]:
    """Every entity key phase `key` can create: its binary sensor, then its cycle entities."""
    slug = f"{PHASE}_{key}"
    return {
        slug: Platform.BINARY_SENSOR,
        **{f"{slug}_{suffix}": platform for suffix, platform in SUFFIXES.items()},
    }


def _reserved(phases: dict[str, Any]) -> dict[str, Any]:
    """Refuse idle (the current phase while none runs) and other (the built-in phase) as keys."""
    for key in (IDLE, OTHER):
        if key in phases:
            raise vol.Invalid(
                f"{key} is a reserved phase key: name the phase otherwise"
            )
    return phases


def _apart(phases: dict[str, Any]) -> dict[str, Any]:
    """Refuse a phase whose entity key another phase, other or the detector already creates.

    other's keys are claimed first: a configured phase colliding with them is the one named.
    """
    owners = dict.fromkeys(FIXED, "")
    for key in (OTHER, *phases):
        for entity_key in phase_keys(key):
            owner = owners.setdefault(entity_key, key)
            if owner != key:
                taken = f"phase {owner}'s" if owner else "the detector's"
                raise vol.Invalid(f"phase {key} would create {entity_key}, {taken}")
    return phases


def _delays(default: timedelta) -> dict[vol.Marker, Any]:
    """on_delay and off_delay, `default` when absent."""
    return {
        vol.Optional("on_delay", default=default): cv.positive_time_period,
        vol.Optional("off_delay", default=default): cv.positive_time_period,
    }


# A band of the reading: above, below or both (bounded)
BAND: dict[vol.Marker, Any] = {
    vol.Optional("above"): finite_float,
    vol.Optional("below"): finite_float,
}
# A phase is a program without phases (and without statistics until D2 mounts them)
PHASE_SCHEMA = vol.All(
    vol.Schema({vol.Required("name"): TEXT, **BAND, **_delays(timedelta(0))}),
    bounded("phase"),
)


def _other_needs_phases(program: dict[str, Any]) -> dict[str, Any]:
    if OTHER in program and "phases" not in program:
        raise vol.Invalid(
            f"{OTHER} is the program outside every phase: it needs phases"
        )
    return program


# A schema of its own at each level: ALLOW_EXTRA would let a key that isn't a slug through
SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("name"): TEXT,
            **BAND,
            **_delays(timedelta(0)),
            vol.Optional("phases"): vol.All(
                vol.Schema({cv.slug: PHASE_SCHEMA}),
                vol.Length(min=1),
                _reserved,
                _apart,
            ),
            vol.Optional(OTHER): vol.Schema(_delays(OTHER_DELAY)),
        }
    ),
    bounded("program"),
    _other_needs_phases,
)


@dataclass(frozen=True, kw_only=True)
class Band:
    """A band of the reading, its cycles confirmed by on_delay and off_delay."""

    above: float | None = None
    below: float | None = None
    on_delay: timedelta = timedelta(0)
    off_delay: timedelta = timedelta(0)

    def holds(self, value: float) -> bool:
        """Strictly above `above` and strictly below `below`, as HA's numeric_state."""
        return (self.above is None or value > self.above) and (
            self.below is None or value < self.below
        )


@dataclass(frozen=True, kw_only=True)
class Phase:
    """A stage of the program's cycle: a band, or other.

    other's band has no bounds, only delays: it holds for any value. The
    detector holds other in the program's band outside every phase's.
    """

    key: str
    name: str
    band: Band

    @property
    def item(self) -> Item:
        """Its entity keys' item: phase_<key>_<suffix>."""
        return Item(slug=f"{PHASE}_{self.key}", name=self.name)

    @property
    def other(self) -> bool:
        """Whether it is the built-in other."""
        return self.key == OTHER


@dataclass(frozen=True, kw_only=True)
class Program:
    """A detected program: its band, and its phases (the configured ones in order, then other)."""

    band: Band
    phases: tuple[Phase, ...] = ()


def _band(block: Mapping[str, Any]) -> Band:
    return Band(
        above=block.get("above"),
        below=block.get("below"),
        on_delay=block["on_delay"],
        off_delay=block["off_delay"],
    )


def program_of(config: Mapping[str, Any]) -> Program:
    """The program of a block SCHEMA validated: other comes with the first phase."""
    phases = [
        Phase(key=key, name=phase["name"], band=_band(phase))
        for key, phase in config.get("phases", {}).items()
    ]
    if phases:
        other = config.get(OTHER, {"on_delay": OTHER_DELAY, "off_delay": OTHER_DELAY})
        # other's band has no bounds: only its delays count; `Detector.read` decides where it holds.
        # Its name is only its item's: its entities are named by their own translations
        phases.append(Phase(key=OTHER, name=OTHER, band=Band(**other)))
    return Program(band=_band(config), phases=tuple(phases))
