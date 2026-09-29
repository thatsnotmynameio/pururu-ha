"""The roles a builder composes: what it is beyond its five fields, asked for by type (Feature.role)."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.const import Platform

if TYPE_CHECKING:  # feature.py imports this module
    from .feature import Happening, Item, Preset
    from .resolve import Ref


@dataclass(frozen=True)
class Provides:
    """A capability others take through <capability>_from, carried by one of its entity keys."""

    capability: str
    key: str


@dataclass(frozen=True)
class Requires:
    """A capability it takes through <capability>_from: build() gets its current entity ID.

    Its entities aren't created when the provider's entity isn't.
    """

    capability: str


@dataclass(frozen=True)
class Configured:
    """Its entity keys are its block's keys, all on this platform, named by each block's `name`."""

    platform: Platform


@dataclass(frozen=True)
class Actions:
    """Services its entities take on their own platform: what a program's step may call."""

    actions: tuple[str, ...]


@dataclass(frozen=True)
class Items:
    """Its block is a map of items, each with entity keys of its own: <slug>_<suffix>.

    Each is named by the suffix's translation, with the item's name as the
    placeholder named after the namespace ({mode}).
    """

    keys: Mapping[str, Platform]
    items: Callable[[Any], Iterable[Item]]


@dataclass(frozen=True)
class Refers:
    """Entity keys of other features its validated block names.

    Validated against the device; build() gets their current entity IDs in
    `inputs`, by each reference as written (Ref.text).
    """

    refers: Callable[[Any], Iterable[Ref]]


@dataclass(frozen=True)
class Presets:
    """Ready-made alerts, by name: each enabled one is the entity key alert_<name>.

    Enabled in its block's `alerts` (presets.validate); preset_keys goes in its entity_keys.
    """

    presets: Mapping[str, Preset]


@dataclass(frozen=True)
class Happenings:
    """Ready-made notifications, by name: each enabled one, in its block's `notifications`, is an automation."""

    happenings: Mapping[str, Happening]


type Role = (
    Provides | Requires | Configured | Actions | Items | Refers | Presets | Happenings
)
