"""What a device and a feature are: the contract every module in features/ fulfils."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
import math
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.const import (
    ATTR_RESTORED,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, ENTITY_PREFIX

if TYPE_CHECKING:  # entity.py imports Device from here
    from .entity import PururuEntity


def finite_float(value: Any) -> float:
    """A number for a feature's configuration: `nan` and infinities are refused."""
    number = float(vol.Coerce(float)(value))
    if not math.isfinite(number):
        raise vol.Invalid(f"expected a finite number, got {value!r}")
    return number


# Text a person reads, or a state: a blank one would say nothing
TEXT = vol.All(cv.string, vol.Strip, vol.Length(min=1))


def state_text(value: Any) -> str:
    """A state as text: YAML reads an unquoted on/yes/true (off/no/false) as a boolean."""
    if isinstance(value, bool):
        return STATE_ON if value else STATE_OFF
    return str(TEXT(value))


def bounded(what: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """A band of a sensor's value (`what`: band, mode): above, below or both, above lower."""

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
    """An item of a feature's block with entity keys of its own (Feature.per_item): a mode."""

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


# States that are no reading, unless the condition is about them
NO_READING = (STATE_UNAVAILABLE, STATE_UNKNOWN)


def _number(state: State) -> float | None:
    """A state's finite number, or None (entity.reading, which imports this module)."""
    try:
        value = float(state.state)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


@dataclass(frozen=True, kw_only=True)
class Condition:
    """What makes the watched entity's state a problem: a state, a number, or a range."""

    state: str | float | None = None
    above: float | None = None
    below: float | None = None

    def holds(self, state: State | None) -> bool | None:
        """Whether `state` is a problem; None when it is no reading.

        A condition on unavailable or unknown holds while the entity has no
        reading, either state or missing: a plug reconnecting passes from one to
        the other. A state HA restored for an entity not loaded yet (at start,
        during a reload) is no reading, for every condition.
        """
        if state is not None and state.attributes.get(ATTR_RESTORED):
            return None
        if isinstance(self.state, str):
            return self._is(STATE_UNAVAILABLE if state is None else state.state)
        if state is None or (value := _number(state)) is None:
            return None
        if self.state is not None:  # a number
            return value == self.state
        return (self.above is None or value > self.above) and (
            self.below is None or value < self.below
        )

    def _is(self, current: str) -> bool | None:
        """`is` a state: no reading for other states, unless it is about no reading."""
        if self.state in NO_READING:
            return current in NO_READING
        if current in NO_READING:
            return None
        return current == self.state


@dataclass(frozen=True, kw_only=True)
class Elapsed:
    """On while the watched entity is `state` and the time since a milestone is in [for, for + lasts).

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
    # The default `for`; None: the user gives it. An alert with `lasts` takes no `for`
    hold: timedelta | None
    # How long it stays on after its milestone; the user may change it
    lasts: timedelta | None = None


# The key of a feature's block that enables its ready-made alerts
ALERTS_KEY = "alerts"


def preset_keys(presets: Mapping[str, Preset]) -> dict[str, Platform]:
    """The entity keys of a feature's ready-made alerts: alert_<name>, binary sensors."""
    return {f"alert_{name}": Platform.BINARY_SENSOR for name in presets}


@dataclass(frozen=True, kw_only=True)
class Happening:
    """A ready-made notification of a feature: what happens, as a reaction's trigger.

    Off until the device's `notifications` enables it; it creates no entity.
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
    # capability -> the entity key whose entity carries it; others take it with <capability>_from
    provides: Mapping[str, str] = field(default_factory=dict)
    # capabilities it takes through <capability>_from: build() gets their current
    # entity IDs, and its entities aren't created when those entities aren't
    requires: tuple[str, ...] = ()
    # Its entity keys are the keys of its block, all on this platform, named by
    # their block's `name`; None: they are entity_keys, named by the translations
    configured: Platform | None = None
    # Entity keys of other features of the device, in their namespace
    # (appliance_running), that its validated block names: validated against the
    # device, and build() gets their current entity IDs in `inputs`, by that key
    refers: Callable[[Any], Iterable[str]] | None = None
    # Services its entities take, on their own platform (turn_on → switch.turn_on
    # for a switch): a program's step can call them (programs.py)
    actions: tuple[str, ...] = ()
    # Entity keys repeated for every item of its block: suffix -> platform. An
    # item's entity key is <slug>_<suffix>, named by the suffix's translation
    # with the item's name as the placeholder named after the namespace ({mode})
    per_item: Mapping[str, Platform] = field(default_factory=dict)
    # The items of its validated block, when it has per_item
    items: Callable[[Any], Iterable[Item]] | None = None
    # Ready-made alerts it offers, by name: each enabled one is the entity key
    # alert_<name> (put preset_keys in entity_keys), enabled in its block's
    # `alerts` (presets.validate)
    alerts: Mapping[str, Preset] = field(default_factory=dict)
    # Ready-made notifications it offers, by name: each enabled one, in the
    # device's `notifications`, is an automation (notifications.py)
    notifications: Mapping[str, Happening] = field(default_factory=dict)
