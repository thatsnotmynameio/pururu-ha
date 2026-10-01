"""A reference to an entity key a device can create, and the index it is found in."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .feature import Device


@dataclass(frozen=True)
class Ref:
    """An entity key of a device, as a block names it: on this device when `device` is None."""

    device: str | None
    # Qualified, as the entity ID ends after the device key: appliance_running
    key: str

    @classmethod
    def parse(cls, text: str) -> Ref:
        """The reference `text` writes: appliance_running, or washer.appliance_running.

        `text` is as `reference` or `device_reference` validated it: any other
        is a programming error, as it wouldn't read back as written.
        """
        device, dot, key = text.partition(".")
        if not device or (dot and (not key or "." in key)):
            raise ValueError(f"{text!r} is not a validated reference")
        return cls(device, key) if dot else cls(None, device)

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
    # The key of the aspect that adds it ("alerts", "statistics"); None for
    # the builder's own
    by: str | None
    # The item that owns the key (a program, a reaction); None: none
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


# The domains of entities, to tell an entity ID from <device>.<key>: a
# device keyed as one is told apart by being in devices
# The domains an entity ID begins with: HA's platforms, and the helpers and
# generated items that aren't one (pururu's own scripts and automations among them)
_DOMAINS = frozenset(platform.value for platform in Platform) | {
    "automation",
    "counter",
    "group",
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "person",
    "schedule",
    "script",
    "timer",
    "zone",
}


def entity_id_hint(index: Index, ref: Ref, real: str) -> str:
    """Why `ref`, whose device isn't one, may be an entity ID, in parentheses; "" when it isn't.

    An entity ID was the way to name an entity before 0.2.1: a pururu
    entity's (as created) says its reference; a real one's, told by its
    domain, says `real`, the caller's advice.
    """
    for device, targets in index.items():
        for target in targets.values():
            if target.entity_id() == ref.text:
                return f" ({ref.text} is an entity ID: write {device}.{target.key})"
    if ref.device in _DOMAINS:
        return f" ({ref.text} is an entity ID: {real})"
    return ""


def _text(value: Any) -> str:
    """A reference's text: never empty, which would name nothing."""
    text = cv.string(value)
    if not text:
        raise vol.Invalid("an entity key can't be empty")
    return text


def reference(value: Any) -> str:
    """An entity key, of this device (appliance_running) or of another (washer.appliance_running)."""
    text = _text(value)
    parts = text.split(".")
    if len(parts) > 2 or not all(parts):
        raise vol.Invalid(f"{text} is neither an entity key nor <device>.<key>")
    return ".".join(str(cv.slug(part)) for part in parts)


def local_key(value: Any) -> str:
    """An entity key of this device: an alert's when, a program's step, a reaction's then."""
    text = _text(value)
    if "." in text:
        raise vol.Invalid(
            f"{text} must be of this device: its entity key, without <device>. "
            "or <domain>."
        )
    return str(cv.slug(text))


def device_reference(value: Any) -> str:
    """An entity key of a named device, as a light group's: always washer.appliance_running."""
    text = reference(value)
    if "." not in text:
        raise vol.Invalid(f"{text} needs its device: <device>.{text}")
    return text
