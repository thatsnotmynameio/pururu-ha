"""The roles a builder composes: what it is beyond its five fields, asked for by type (Feature.role)."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.const import Platform

if TYPE_CHECKING:  # feature.py imports this module
    from .feature import Born, Happening, Item, Path, Preset
    from .resolve import Ref


@dataclass(frozen=True)
class Configured:
    """Its block's keys are entity keys on this platform, named by each block's `name`.

    Items may add keys of their own beside them, one item per block key (a
    button's total); an aspect sits only inside an item, never at the block.
    """

    platform: Platform


@dataclass(frozen=True)
class Nodes:
    """Where its fixed entity keys (entity_keys) sit in its block, by key; one it doesn't name, at the block under its own name.

    A path (feature.Path) from the block: a written setting's is the entity
    derived from it (the appliance's energy_total, at energy), a declared
    thing's is the thing (running, at running_program), an unwritten key's is
    the node it is born under, then its name (running_program, last_cycle_end).
    """

    of: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class Derived:
    """Entity keys its validated block adds beyond entity_keys: the appliance's phases'.

    `of` takes the validated block, and gives each key born at its path from
    the block (feature.Born). catalogue.keys lists them, so the index knows
    them: an alert, a reaction or a `when:` can name one.
    """

    of: Callable[[Any], Mapping[str, Born]]


@dataclass(frozen=True)
class Programs:
    """It takes detected programs, `programs: detected:` in its block: each a band of the setting `reading`.

    `energy` is the setting giving each cycle's kWh, None: none. The programs
    aspect (aspects/programs.py) mounts `programs:`, lists their keys and
    builds them.
    """

    reading: str
    energy: str | None = None


@dataclass(frozen=True)
class Actions:
    """Services its entities take on their own platform: what a program's step may call."""

    services: tuple[str, ...]


@dataclass(frozen=True)
class Items:
    """Its block is a map of items, each with entity keys of its own: <slug>_<suffix>.

    Each is named by the suffix's translation, with the item's name as the
    placeholder named after the namespace ({program}).
    """

    keys: Mapping[str, Platform]
    of: Callable[[Any], Iterable[Item]]


@dataclass(frozen=True, kw_only=True)
class Counted:
    """Totals it builds at one place of its block, <counter>_total; `statistics:` there asks for their meters."""

    # Counter -> the setting of the builder's whole block it needs (None: none)
    needs: Mapping[str, str | None]
    # Where `statistics:` sits: the path from the block to its containers
    # (feature.Path; EACH for each item of a map)
    at: tuple[str, ...] = ()
    # The item the container at a path of the builder's validated block is
    # (feature.ItemOf: the block, the container's path): its totals and meters
    # are the item's, named with {item}; None: the builder's own
    item: Callable[[Any, tuple[str, ...]], Item] | None = None
    # The prefix its meters' translations are named under (<named>_<counter>_<period>,
    # other's own), instead of the statistics aspect's
    named: str | None = None


@dataclass(frozen=True)
class Counters:
    """Totals it builds, at each of its places (Counted); the statistics aspect meters them per period."""

    places: tuple[Counted, ...]


@dataclass(frozen=True)
class Refers:
    """Entities of other features its validated block names, each a path, with the field that names it.

    `of` gives (the field's path in the block, the reference) pairs:
    (("stuck", "when"), appliance.running_program). Validated against the
    device, refused at the field (checks.references); build() gets their
    current entity IDs in `inputs`, by each reference as written (Ref.text).
    `others`: whether it may name another device's (device.<device>.…); a
    Home Assistant entity is never one.
    """

    of: Callable[[Any], Iterable[tuple[Path, Ref]]]
    others: bool = False


@dataclass(frozen=True)
class Presets:
    """Ready-made alerts, by name: each enabled one is the entity key alert_<name>.

    Enabled in its block's `alerts`: the alerts aspect (aspects/alerts.py)
    validates them and adds their keys.
    """

    offered: Mapping[str, Preset]


@dataclass(frozen=True)
class Happenings:
    """Ready-made notifications, by name: each enabled one, in its block's `notifications`, is an automation."""

    offered: Mapping[str, Happening]


@dataclass(frozen=True)
class Generates:
    """What it writes to a generated kind: (domain, object ID) from (device key, validated block).

    `what` names one in a message: "program", "reaction".
    """

    what: str
    ids: Callable[[str, Any], Iterable[tuple[str, str]]]


type Role = (
    Configured
    | Nodes
    | Derived
    | Programs
    | Actions
    | Items
    | Counters
    | Refers
    | Presets
    | Happenings
    | Generates
)
