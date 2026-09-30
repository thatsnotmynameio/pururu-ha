"""A reference to an entity key a device can create, and the index it is found in."""

from collections.abc import Mapping
from dataclasses import dataclass

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .feature import Device


@dataclass(frozen=True)
class Ref:
    """An entity key of a device, as a block names it: on this device when `device` is None."""

    device: str | None
    # Qualified, as the entity ID ends after the device key: appliance_running
    key: str

    @property
    def text(self) -> str:
        """The reference as written; a builder's inputs are keyed by it."""
        return self.key if self.device is None else f"{self.device}.{self.key}"


@dataclass(frozen=True)
class Target:
    """An entity key a device can create, and what may refer to it."""

    # The device in the namespace of the builder that creates it
    device: Device
    # Qualified: appliance_running
    key: str
    platform: Platform
    # The builder's key in the device: appliance, switches, programs
    builder: str
    # "alerts" for a ready-made alert's key, an aspect's key (e.g. "statistics")
    # for one it adds; None for the builder's own
    by: str | None
    # The item that owns the key (a mode, a program, a reaction); None: none
    item: str | None
    # Its builder's actions, for a program's step; () without
    actions: tuple[str, ...]

    @property
    def local(self) -> str:
        """The key in its builder's namespace: running."""
        return self.key.removeprefix(f"{self.device.namespace}_")

    @property
    def unique_id(self) -> str:
        """Its unique ID, which is also its entity ID's object ID as created."""
        return self.device.object_id(self.local)

    def entity_id(self) -> str:
        """The entity ID it is created with."""
        return self.device.entity_id(self.platform, self.local)

    def current_entity_id(self, hass: HomeAssistant) -> str:
        """The entity ID it has now: the user may have renamed it in the UI."""
        return self.device.current_entity_id(hass, self.platform, self.local)


# Device key -> qualified entity key -> what it is
type Index = Mapping[str, Mapping[str, Target]]


def find(index: Index, here: str, ref: Ref) -> Target | None:
    """What `ref`, written in device `here`, names; None when that device can't create it.

    The caller says why, in its own words.
    """
    return index.get(here if ref.device is None else ref.device, {}).get(ref.key)
