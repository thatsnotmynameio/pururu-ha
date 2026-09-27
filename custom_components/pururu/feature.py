"""What a device and a feature are: the contract every module in features/ fulfils."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import math
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
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


def qualified(namespace: str, entity_key: str) -> str:
    """`entity_key` in `namespace`: the end of its entity ID, and its translation key.

    No exception, even for an entity key alike its namespace: a switch keyed
    `switch` is `switch_switch`.
    """
    return f"{namespace}_{entity_key}"


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
