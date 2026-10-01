"""A detected program's block, and the program it describes: a band of a reading, and its phases."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv

from ....const import CONF_DETECTED, CONF_PROGRAMS
from ....core.feature import EACH, TEXT, Born, Item, Path, at, bounded, finite_float
from ....core.roles import Counted
from ....core.vocabulary import band
from ..last import LAST_CYCLE

# The current phase while none runs
IDLE = "idle"
# The built-in phase: the program runs outside every configured phase's band
OTHER = "other"
# Every phase's entity keys have it: phase_<key>[_<suffix>], or
# <of>_phase_<key>[_<suffix>] in detected program `of`
PHASE = "phase"
# other's delays when `other:` doesn't set them: a chill's 2-s spike is no phase
OTHER_DELAY = timedelta(seconds=30)

# A cycle source's entities: <slug>_<suffix> (a phase's, a detected program's)
SUFFIXES: dict[str, Platform] = {
    **{description.key: Platform.SENSOR for description in LAST_CYCLE},
    "cycles_total": Platform.SENSOR,
    "runtime_total": Platform.SENSOR,
    "energy_total": Platform.SENSOR,
}
# The detector's own entity keys; the program's carrier is its builder's (the
# appliance's `running`), or <of>_… and the carrier <of> in detected program `of`
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
# Where a feature's detected programs sit in its block: `programs: detected:`,
# the programs aspect's key (aspects/programs.py)
DETECTED_AT: Path = (CONF_PROGRAMS, CONF_DETECTED, EACH)
# A detected program's translations, once for every builder, all with {item},
# its name: detected_<suffix> for its cycle entities, detected_phase_current and
# _last for its fixed ones, detected_phase_other* for its other's (a configured
# phase's are phase_<suffix>, with the phase's name, as the running program's)
DETECTED = "detected"
DETECTED_NAMED: dict[str, Platform] = {
    **{f"{DETECTED}_{suffix}": platform for suffix, platform in SUFFIXES.items()},
    **{f"{DETECTED}_{key}": platform for key, platform in FIXED.items()},
    f"{DETECTED}_{PHASE}_{OTHER}": Platform.BINARY_SENSOR,
    **{
        f"{DETECTED}_{PHASE}_{OTHER}_{suffix}": platform
        for suffix, platform in SUFFIXES.items()
    },
}
# Each phase's totals, for the statistics aspect to meter; energy needs the builder's `energy`
PHASE_COUNTERS: dict[str, str | None] = {
    "runtime": None,
    "cycles": None,
    "energy": "energy",
}


def _of(entity_key: str, of: str | None) -> str:
    """`entity_key` of the running program, or of detected program `of`: <of>_<entity_key>."""
    return entity_key if of is None else f"{of}_{entity_key}"


def phase_slug(key: str, of: str | None = None) -> str:
    """A phase's entity keys' slug: phase_<key>, or <of>_phase_<key> in detected program `of`; the one rule every phase key uses."""
    return _of(f"{PHASE}_{key}", of)


def _phase_item(block: Any, path: Path) -> Item:
    """A configured phase's item, at `path` of the builder's block: phase_<key>, named by its name."""
    return Item(slug=phase_slug(path[-1]), name=at(block, path)["name"])


def _other_item(*_: Any) -> Item:
    """Other's item: phase_other; its entities are named by their own translations."""
    return Item(slug=f"{PHASE}_{OTHER}", name=OTHER)


def counted(where: Path) -> tuple[Counted, ...]:
    """Where a detected program at `where` counts: its own runtime and cycles, each phase's and other's.

    The program's own totals are its builder's (the appliance's runtime_total,
    cycles_total); a phase's and other's are phase_<key>_<counter>_total,
    other's meters named by their own translations (phase_other_*).
    """
    return (
        Counted(needs={"runtime": None, "cycles": None}, at=where),
        Counted(needs=PHASE_COUNTERS, at=(*where, "phases", EACH), item=_phase_item),
        Counted(
            needs=PHASE_COUNTERS,
            at=(*where, OTHER),
            item=_other_item,
            named=f"{PHASE}_{OTHER}",
        ),
    )


def detected_item(key: str, config: Mapping[str, Any]) -> Item:
    """A detected program's item: its key, named by its name."""
    return Item(slug=key, name=config["name"])


def _detected_item(block: Any, path: Path) -> Item:
    """The detected program at `path` of the builder's block."""
    return detected_item(path[-1], at(block, path))


def _detected_phase_item(block: Any, path: Path) -> Item:
    """A phase of a detected program, at `path` (…, <program>, phases, <phase>): <program>_phase_<phase>, named by its name."""
    return Item(slug=phase_slug(path[-1], path[-3]), name=at(block, path)["name"])


def _detected_other_item(block: Any, path: Path) -> Item:
    """A detected program's other, at `path` (…, <program>, other): <program>_phase_other, named with its program's name."""
    return Item(slug=phase_slug(OTHER, path[-2]), name=at(block, path[:-1])["name"])


def counted_each(where: Path) -> tuple[Counted, ...]:
    """Where each detected program of the map at `where` counts: its runtime, cycles and energy, as its item's; each phase's and other's.

    Unlike running_program's (the builder's own totals), a detected program's
    totals are its own: <key>_runtime_total, <key>_cycles_total,
    <key>_energy_total (energy needs the builder's `energy`, D3 ruling 7). Its
    phases' are <key>_phase_<phase>_<counter>_total; its other's meters are
    named by detected_phase_other_*, with its name.
    """
    return (
        Counted(needs=PHASE_COUNTERS, at=where, item=_detected_item),
        Counted(
            needs=PHASE_COUNTERS,
            at=(*where, "phases", EACH),
            item=_detected_phase_item,
        ),
        Counted(
            needs=PHASE_COUNTERS,
            at=(*where, OTHER),
            item=_detected_other_item,
            named=f"{DETECTED}_{PHASE}_{OTHER}",
        ),
    )


def _cycle(slug: str, node: Path) -> dict[str, Born]:
    """A cycle source's entity keys: its binary sensor `slug` at `node`, then each cycle entity under it (<node>.<suffix>)."""
    return {
        slug: Born(Platform.BINARY_SENSOR, node),
        **{
            f"{slug}_{suffix}": Born(platform, (*node, suffix))
            for suffix, platform in SUFFIXES.items()
        },
    }


def detected_keys(
    key: str, config: Mapping[str, Any], node: Path = ()
) -> dict[str, Born]:
    """Every entity key detected program `key` can create: its carrier, its cycle entities, then its phases'.

    `node` is the program's, from where its keys are listed: each is born under it.
    """
    return {**_cycle(key, node), **keys_of(config, of=key, node=node)}


def phase_keys(key: str, of: str | None = None, node: Path = ()) -> dict[str, Born]:
    """Every entity key phase `key` (of detected program `of`) can create: its binary sensor, then its cycle entities.

    `node` is its program's: a phase sits at <node>.phases.<key>, other at <node>.other.
    """
    at_phase = (*node, OTHER) if key == OTHER else (*node, "phases", key)
    return _cycle(phase_slug(key, of), at_phase)


def keys_of(
    config: Mapping[str, Any], of: str | None = None, node: Path = ()
) -> dict[str, Born]:
    """Every entity key a program block's phases create, other's too: none without phases.

    `of`: a detected program's key, before each (<of>_phase_current, …).
    `node`: the program's, each key born under it (<node>.phase_current,
    <node>.phases.<key>, <node>.other).
    """
    if "phases" not in config:
        return {}
    return {
        **{
            _of(key, of): Born(platform, (*node, key))
            for key, platform in FIXED.items()
        },
        **{
            entity_key: born
            for key in (*config["phases"], OTHER)
            for entity_key, born in phase_keys(key, of, node).items()
        },
    }


def _reserved(phases: dict[str, Any]) -> dict[str, Any]:
    """Refuse idle (the current phase while none runs), and other or other_… (the built-in phase's).

    A phase keyed other_… meets other's keys: its cycle entities (listed with
    the first phase), and its meters (listed only once `other:` is written).
    Were only today's refused, writing `other:` would refuse the configuration
    then; so the whole form is other's, the user's key the one named.
    """
    if IDLE in phases:
        raise vol.Invalid(
            f"{IDLE} is a reserved phase key: name the phase otherwise", path=[IDLE]
        )
    for key in phases:
        if key == OTHER or key.startswith(f"{OTHER}_"):
            raise vol.Invalid(
                f"{key} is reserved for the built-in phase {OTHER} "
                f"({OTHER}, {OTHER}_…): name the phase otherwise",
                path=[key],
            )
    return phases


def _apart(phases: dict[str, Any]) -> dict[str, Any]:
    """Refuse a phase whose entity key another phase or the detector already creates.

    other's can't meet a configured phase's: other and other_… are refused before (_reserved).
    """
    owners = dict.fromkeys(FIXED, "")
    for key in phases:
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
# A phase is a program without phases; its statistics are the statistics aspect's
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


def _named(block: Any) -> Any:
    """Refuse a detected program without a name: it names its entities."""
    if isinstance(block, dict) and "name" not in block:
        raise vol.Invalid("a detected program needs a name: it names its entities")
    return block


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

# A detected program of `programs: detected:`: a program with a name
DETECTED_SCHEMA = vol.All(_named, SCHEMA)


def unreserved(programs: dict[str, Any]) -> dict[str, Any]:
    """Refuse a detected program keyed as phases' keys begin: phase[_…], the running program's; <of>_phase[_…], detected program `of`'s.

    A phase comes with a setting (`phases`, `other`, their `statistics`) and
    can take any key of that form: were only today's phases' keys refused,
    adding a phase would refuse the configuration then. Every other key a
    setting adds is listed whatever the settings (catalogue.keys), so
    checks.keys_distinct refuses it already.
    """
    for key in programs:
        for of in (None, *(sibling for sibling in programs if sibling != key)):
            form = _of(PHASE, of)
            if key == form or key.startswith(f"{form}_"):
                whose = (
                    "the running program's"
                    if of is None
                    else f"detected program {of}'s"
                )
                raise vol.Invalid(
                    f"{key} is reserved for {whose} phases ({form}, {form}_…): "
                    "name the program otherwise",
                    path=[key],
                )
    return programs


@dataclass(frozen=True, kw_only=True)
class Band:
    """A band of the reading, its cycles confirmed by on_delay and off_delay."""

    above: float | None = None
    below: float | None = None
    on_delay: timedelta = timedelta(0)
    off_delay: timedelta = timedelta(0)

    def holds(self, value: float) -> bool:
        """Strictly above `above` and strictly below `below`, as HA's numeric_state."""
        return band(value, self.above, self.below)


@dataclass(frozen=True, kw_only=True)
class Phase:
    """A stage of the program's cycle: a band, or other.

    other's band has no bounds, only delays: it holds for any value. The
    detector holds other in the program's band outside every phase's.
    """

    key: str
    name: str
    band: Band
    # The detected program it is a phase of: None, the builder's running program
    of: Item | None = None

    @property
    def item(self) -> Item:
        """Its entity keys' item: phase_<key>_<suffix>, or <of>_phase_<key>_<suffix>.

        A detected program's other is named with the program's name: its
        translations (detected_phase_other_*) carry {item}.
        """
        if self.of is None:
            return Item(slug=phase_slug(self.key), name=self.name)
        name = self.of.name if self.other else self.name
        return Item(slug=phase_slug(self.key, self.of.slug), name=name)

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


def program_of(config: Mapping[str, Any], of: Item | None = None) -> Program:
    """The program of a block SCHEMA validated: other comes with the first phase.

    `of`: a detected program's item, its phases' (Phase.of).
    """
    phases = [
        Phase(key=key, name=phase["name"], band=_band(phase), of=of)
        for key, phase in config.get("phases", {}).items()
    ]
    if phases:
        other = config.get(OTHER, {"on_delay": OTHER_DELAY, "off_delay": OTHER_DELAY})
        # other's band has no bounds: only its delays count; `Detector.read` decides where it holds.
        # Its name is unused with `of` (its item takes the program's); its
        # entities are named by their own translations.
        # Only its delays: the mounted block holds its statistics too
        band = Band(on_delay=other["on_delay"], off_delay=other["off_delay"])
        phases.append(Phase(key=OTHER, name=OTHER, band=band, of=of))
    return Program(band=_band(config), phases=tuple(phases))
