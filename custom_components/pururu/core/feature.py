"""What a device and a feature are: the contract every module in features/ fulfils."""

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
import math
from typing import TYPE_CHECKING, Any, NamedTuple

import voluptuous as vol

from homeassistant.const import STATE_OFF, STATE_ON, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from ..const import DOMAIN, ENTITY_PREFIX
from .roles import Happenings, Presets, Role
from .texts import Texts
from .vocabulary import Condition

# entity.py imports Device from here
if TYPE_CHECKING:
    from .entity import PururuEntity


def finite_float(value: Any) -> float:
    """A number for a feature's configuration: `nan` and infinities are refused."""
    number = float(vol.Coerce(float)(value))
    if not math.isfinite(number):
        raise vol.Invalid(f"expected a finite number, got {value!r}")
    return number


# How serious a problem is, lowest first
PRIORITIES = ("low", "medium", "high")

# Text a person reads, or a state: a blank one would say nothing
TEXT = vol.All(cv.string, vol.Strip, vol.Length(min=1))


def state_text(value: Any) -> str:
    """A state as text: YAML reads an unquoted on/yes/true (off/no/false) as a boolean."""
    if isinstance(value, bool):
        return STATE_ON if value else STATE_OFF
    return str(TEXT(value))


def state_of(word: str) -> Callable[[Any], str]:
    """`word`'s state as text (`state_text`), a YAML number refused.

    A state is compared as text, and pururu can't tell which entity shows 1
    as 1.0: a number is a reading's (above, below) or a quoted state. The
    message shows the value as YAML read it (12:30 is 750, 1.50 is 1.5), not
    as written: the loader keeps no text.
    """

    def validate(value: Any) -> str:
        if not isinstance(value, bool) and isinstance(value, int | float):
            raise vol.Invalid(
                f"{word}: YAML reads it as the number {value}: compare a reading "
                'with above or below, or quote the state as the entity shows it ("1.0")'
            )
        return state_text(value)

    return validate


def bounded(what: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """A band of a sensor's value (`what`: program, phase): above, below or both, above lower."""

    def validate(band: dict[str, Any]) -> dict[str, Any]:
        if "above" not in band and "below" not in band:
            raise vol.Invalid(f"a {what} needs above, below or both")
        if "above" in band and "below" in band and band["above"] >= band["below"]:
            raise vol.Invalid(f"a {what}'s above must be lower than its below")
        return band

    return validate


def qualified(namespace: str, entity_key: str) -> str:
    """`entity_key` in `namespace`: the end of its entity ID, and its translation key.

    No exception, even for an entity key alike its namespace: a switch keyed
    `switch` is `switch_switch`.
    """
    return f"{namespace}_{entity_key}"


@dataclass(frozen=True, kw_only=True)
class Item:
    """An item of a feature's block with entity keys of its own (roles.Items): a program, a reaction; the detector names each phase's entities with one too (Phase.item)."""

    slug: str
    name: str
    # Where it sits in its builder's block (Path), its keys under it:
    # (executable, clean) for executable_clean; () for an item no Items role
    # lists (a phase: program.keys_of gives its keys' paths)
    path: tuple[str, ...] = ()

    def key(self, suffix: str) -> str:
        """The entity key of `suffix` for this item."""
        return f"{self.slug}_{suffix}"


def item_key(suffix: str, item: Item | None) -> str:
    """`suffix` as an entity key: the item's own, or the feature's without an item."""
    return suffix if item is None else item.key(suffix)


@dataclass(frozen=True, kw_only=True)
class Device:
    """A configured device as one of its features sees it: key, display name, that feature's namespace."""

    key: str
    name: str
    # The feature's namespace: every entity key it names is in it
    namespace: str

    @property
    def info(self) -> DeviceInfo:
        """The device every entity of this device belongs to, whatever its feature."""
        return DeviceInfo(identifiers={(DOMAIN, self.key)}, name=self.name)

    def qualified(self, entity_key: str) -> str:
        """`entity_key` in this feature's namespace."""
        return qualified(self.namespace, entity_key)

    def object_id(self, entity_key: str) -> str:
        """The entity ID of `entity_key` without its platform, which is also its unique ID."""
        return f"{ENTITY_PREFIX}_{self.key}_{self.qualified(entity_key)}"

    def entity_id(self, platform: Platform, entity_key: str) -> str:
        """The entity ID `entity_key` is created with."""
        return f"{platform}.{self.object_id(entity_key)}"

    def current_entity_id(
        self, hass: HomeAssistant, platform: Platform, entity_key: str
    ) -> str:
        """The entity ID `entity_key` has now: the user may have renamed it in the UI."""
        return er.async_get(hass).async_get_entity_id(
            platform, DOMAIN, self.object_id(entity_key)
        ) or self.entity_id(platform, entity_key)


@dataclass(frozen=True, kw_only=True)
class Elapsed:
    """On while the watched entity is `state` and the time since a milestone is longer than `for`.

    The milestone is the state (a datetime) of `since_key`, an entity key of the
    feature, or the watched entity's attribute `since_attribute`: exactly one.
    With `or_since_created`, an alert with no milestone yet counts from its creation.
    """

    state: str
    since_key: str | None = None
    since_attribute: str | None = None
    or_since_created: bool = False


@dataclass(frozen=True, kw_only=True)
class Preset:
    """A ready-made alert of a feature: off until the feature's block enables it."""

    # The entity key, in the feature's namespace, it watches
    watches: str
    kind: Condition | Elapsed
    priority: str
    # The default `for`; None: the user gives it
    hold: timedelta | None


# The key of a feature's block that enables its ready-made alerts
ALERTS_KEY = "alerts"


def presets_of(feature: Feature) -> Mapping[str, Preset]:
    """The ready-made alerts the builder offers; none without Presets."""
    return role.offered if (role := feature.role(Presets)) else {}


def happenings_of(feature: Feature) -> Mapping[str, Happening]:
    """The ready-made notifications the builder offers; none without Happenings."""
    return role.offered if (role := feature.role(Happenings)) else {}


@dataclass(frozen=True, kw_only=True)
class Happening:
    """A ready-made notification of a feature: what happens, as a reaction's trigger.

    Off until its feature's block's `notifications` enables it (the
    notifications aspect); it creates no entity.
    """

    # The entity key, in the feature's namespace, it watches
    watches: str
    # The state it goes to, and from: a reaction's to and from
    to: str
    from_: str | None = None


type Build = Callable[
    [HomeAssistant, Device, dict[str, Any], Mapping[str, str]], list[PururuEntity]
]


@dataclass(frozen=True, kw_only=True)
class Feature:
    """A part of a device: its configuration block and the entities it creates."""

    # Validates its block; refuses unknown keys
    schema: Callable[[Any], Any]
    # Everything it can create: entity key -> the platform of its entity
    entity_keys: Mapping[str, Platform]
    # Its entities, from its validated block and the entity IDs of what it refers to
    # (Refers), or of the scripts and automations it generates (Generates)
    build: Build
    # A minimal valid block, for the contract test
    example: Mapping[str, Any]
    # Every entity key it creates is in it, so no two features' entity IDs meet
    namespace: str
    # What it is beyond these fields (roles.py), asked for by type
    roles: tuple[Role, ...] = ()

    def role[R: Role](self, kind: type[R]) -> R | None:
        """Its role of that type, if it has one."""
        return next((each for each in self.roles if isinstance(each, kind)), None)


# From a builder's block to a container of it: the keys to follow, EACH for
# every key of a map. () is the block itself
type Path = tuple[str, ...]
# Every key of a map, in a Path: no slug is "*"
EACH = "*"


class Born(NamedTuple):
    """An entity key where it is born: its platform, and its node's path.

    The path is the keys from where the key is listed (a builder's block, an
    aspect's value) to the node the author reads it at: a declared thing's own
    (running_program, phases, warming), or the node an unwritten key is born
    under, then its name (running_program, phase_current).
    """

    platform: Platform
    path: Path


def walk(value: Any, path: Path, where: Path = ()) -> Iterator[tuple[Path, Any]]:
    """Each container `path` names in `value`, with its own path (EACH made each key).

    A key missing, or a map expected where there's none, names no container:
    nothing is yielded for it. The last container may be anything.
    """
    if not path:
        yield where, value
        return
    if not isinstance(value, Mapping):
        return
    head, *rest = path
    present = (head,) if head in value else ()
    keys = value if head == EACH else present
    for key in keys:
        # As the builder's schema returns it: cv.slug makes YAML's 1 "1"
        yield from walk(value[key], tuple(rest), (*where, str(key)))


def at(block: Any, path: Path) -> Any:
    """The container at `path` in `block`: a concrete path, as walk yields it."""
    for key in path:
        block = block[key]
    return block


# The item the container at a path of the builder's validated block is (a
# program, a phase): the block and the container's concrete path
type ItemOf = Callable[[Any, Path], Item]


@dataclass(frozen=True, kw_only=True)
class Place:
    """Where an aspect's key sits in a builder's block, and what the aspect has there."""

    # The containers of its key; () the block itself
    path: Path = ()
    # Validates the aspect's value in a container there
    schema: Callable[[Any], Any]
    # The local entity keys it adds per container: suffixes of the container's
    # item, with one; none for the ready-made notifications (automations)
    keys: Mapping[str, Platform]
    # The translation key each of its keys is named under
    named: Callable[[str], str]
    # A valid value, for the contract test
    example: Any
    # The item a container there is (ItemOf): its keys are the item's
    # (<slug>_<key>); None: the builder's own
    item: ItemOf | None = None
    # Each of `keys`' path from the aspect's value in a container, the leaf:
    # alert_<name>'s (<name>,), <counter>_<period>'s (<counter>, <period>)
    leaves: Mapping[str, Path] = field(default_factory=dict)
    # The local keys a container's validated value of the aspect adds beyond
    # `keys`, the builder's own and no item's (a detected program's, its
    # phases'), each born at a path from that value: they vary with the value,
    # as Derived's with a block. Pairs, not a map: a key two of them add comes
    # twice, for checks.keys_distinct
    derived: Callable[[Any], Iterable[tuple[str, Born]]] | None = None
    # Refuses (vol.Invalid) what it can't be once validated, given the
    # builder's whole block and the container, its value put back
    check: Callable[[Mapping[str, Any], Mapping[str, Any]], None] | None = None


# hass, the device in the builder's namespace, the builder, its validated block
# (the aspect's value put back at each of its places), the common texts
type AspectBuild = Callable[
    [HomeAssistant, Device, Feature, Any, Texts], list[PururuEntity]
]


@dataclass(frozen=True, kw_only=True)
class Aspect:
    """A concern written once, mounted at its places in the block of every builder offering it."""

    # The key it mounts: "statistics", "alerts", "notifications", "programs"
    key: str
    # Whether this builder offers it: it has what the aspect needs (Counters;
    # at least one ready-made alert; at least one Happening; the Programs role)
    offered: Callable[[Feature], bool]
    # Where its key sits for this builder, given the builder's key in the
    # device (the notifications' refusals name it): the block, a map's items,
    # or deeper (a running program, each of its phases, a detected program)
    places: Callable[[Feature, str], tuple[Place, ...]]
    # Its entities, from the builder's validated block
    build: AspectBuild
    # Its key absent (or its container not a map): validated as `{}` and
    # mounted (statistics: no counter asks a period), or left out, as nothing
    # asked (ready-made alerts and notifications: none enabled; an explicit
    # `{}` is still refused)
    mount_absent: bool = True
