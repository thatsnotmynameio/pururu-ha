"""What a device and a feature are: the contract every module in features/ fulfils."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
import math
from typing import TYPE_CHECKING, Any, Literal

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
    # Its entities, from its validated block and the entity IDs of what it requires
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


# hass, the device in the builder's namespace, the builder, its validated block
# (the aspect's value in it, or in each item), the common texts
type AspectBuild = Callable[
    [HomeAssistant, Device, Feature, Any, Texts], list[PururuEntity]
]


@dataclass(frozen=True, kw_only=True)
class Aspect:
    """A concern written once, mounted in the block (or each item) of every builder offering it."""

    # The block key it mounts: "statistics", "alerts", "notifications"
    key: str
    # Whether this builder offers it: it has what the aspect needs (Counters;
    # at least one ready-made alert; at least one Happening)
    offered: Callable[[Feature], bool]
    # Validates the aspect's value, for this builder and its key in the device,
    # for an aspect whose messages name the builder: the notifications
    # aspect uses it; the alerts and statistics aspects don't need it
    schema: Callable[[Feature, str], Callable[[Any], Any]]
    # The local entity keys it adds: suffixes for an Items builder; none for
    # the ready-made notifications (automations)
    keys: Callable[[Feature], Mapping[str, Platform]]
    # The translation key one of its local keys is named under, for this
    # builder: statistics' own at the block level, or under the builder's
    # namespace (the ready-made alerts')
    named: Callable[[Feature, str], str]
    # A valid value, for the contract test
    example: Callable[[Feature], Any]
    # Where its key sits for this builder: in the block, or in each item
    placed: Callable[[Feature], Literal["block", "item"]]
    # Its entities, from the builder's validated block
    build: AspectBuild
    # Refuses (vol.Invalid) what it can't be once validated, given the builder,
    # its key in the device, and each container (the block, or an item) with
    # its value put back
    check: Callable[[Feature, str, Mapping[str, Any]], None] | None = None
    # Its key absent (or its container not a map): validated as `{}` and
    # mounted (statistics: no counter asks a period), or left out, as nothing
    # asked (ready-made alerts and notifications: none enabled; an explicit
    # `{}` is still refused)
    mount_absent: bool = True
