"""The roles a builder composes: what it is beyond its five fields, asked for by type (Feature.role)."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from homeassistant.const import Platform

if TYPE_CHECKING:  # feature.py imports this module
    from .feature import Happening, Item, Preset
    from .resolve import Ref


@dataclass(frozen=True)
class Configured:
    """Its entity keys are its block's keys, all on this platform, named by each block's `name`."""

    platform: Platform


@dataclass(frozen=True)
class Derived:
    """Entity keys its validated block adds beyond entity_keys: the appliance's phases'.

    `of` takes the validated block. catalogue.keys lists them, so the index
    knows them: an alert, a reaction or a `when:` can name one.
    """

    of: Callable[[Any], Mapping[str, Platform]]


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


@dataclass(frozen=True)
class Counters:
    """Totals it builds as <counter>_total; the statistics aspect meters them per period.

    `needs`: counter -> the setting of its block it needs (None: none).
    `mount`: where `statistics:` sits, the block or each item; with Items, the
    meters repeat per item either way.
    """

    needs: Mapping[str, str | None]
    mount: Literal["block", "item"] = "block"


@dataclass(frozen=True)
class Refers:
    """Entity keys of other features its validated block names.

    Validated against the device; build() gets their current entity IDs in
    `inputs`, by each reference as written (Ref.text).
    """

    of: Callable[[Any], Iterable[Ref]]


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
    | Derived
    | Actions
    | Items
    | Counters
    | Refers
    | Presets
    | Happenings
    | Generates
)
