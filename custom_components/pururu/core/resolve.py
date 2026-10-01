"""What a field of the YAML names, and the index of every entity a device can create it is found in.

A reference is a path through a device's YAML, from the block key the author
wrote (appliance.running_program); another device's starts with
device.<device>. (device.washer.appliance.running_program), a Home
Assistant entity with homeassistant. (homeassistant.binary_sensor.door). The
schema checks a reference's form (`path`); the checks resolve it in the index
(`resolve`), as the first word's meaning depends on the device.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, valid_entity_id
from homeassistant.helpers import config_validation as cv

from .feature import Device

# The first words that say whose a reference is: another device's, Home Assistant's
DEVICE = "device"
HOME_ASSISTANT = "homeassistant"


class Owner(StrEnum):
    """Whose entity a reference names."""

    HERE = "here"
    DEVICE = DEVICE
    HOME_ASSISTANT = HOME_ASSISTANT


@dataclass(frozen=True)
class Ref:
    """What a field names: a path of this device or another, or a Home Assistant entity."""

    owner: Owner
    # Another device's key; None for this device's and Home Assistant's
    device: str | None
    # The path in its device (appliance.running_program); Home Assistant's
    # entity ID (binary_sensor.door)
    path: str

    @classmethod
    def parse(cls, text: str) -> Ref:
        """The reference `text` writes, as `path` validated it.

        Any other text is a programming error, as it wouldn't read back as
        written.
        """
        first, _, rest = text.partition(".")
        if first == HOME_ASSISTANT:
            ref = cls(Owner.HOME_ASSISTANT, None, rest)
        elif first == DEVICE:
            device, _, path = rest.partition(".")
            ref = cls(Owner.DEVICE, device, path)
        else:
            ref = cls(Owner.HERE, None, text)
        if not all(ref.path.partition(".")[::2]) or ref.device == "":
            raise ValueError(f"{text!r} is not a validated reference")
        return ref

    @property
    def text(self) -> str:
        """The reference as written; a builder's inputs are keyed by it."""
        if self.owner is Owner.HOME_ASSISTANT:
            return f"{HOME_ASSISTANT}.{self.path}"
        if self.owner is Owner.DEVICE:
            return f"{DEVICE}.{self.device}.{self.path}"
        return self.path


@dataclass(frozen=True)
class Target:
    """An entity key a device can create, and what may refer to it."""

    # The device in the namespace of the builder that creates it
    device: Device
    # Qualified: appliance_running
    key: str
    # Its node in the device's YAML, from the builder's key: appliance.running_program
    path: str
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


# Device key -> path -> what it is
type Index = Mapping[str, Mapping[str, Target]]


def find(index: Index, here: str | None, ref: Ref) -> Target | None:
    """What `ref`, written in device `here`, names; None when no device creates it.

    Home Assistant's entities aren't in the index. The caller says why, in its
    own words, or asks `resolve`.
    """
    device = here if ref.owner is Owner.HERE else ref.device
    if ref.owner is Owner.HOME_ASSISTANT or device is None:
        return None
    return index.get(device, {}).get(ref.path)


def resolve(index: Index, here: str | None, ref: Ref) -> Target | str:
    """What `ref`, a device's path written in device `here`, names; else why it names nothing.

    The reason starts with the reference as written, for the caller to put
    after its place. `here` is None outside a device (a light group): no
    device names itself there. A device naming itself with device. is
    refused with the form to write: copied under another key, it would still
    name the original. Home Assistant's entities are the caller's to refuse.
    """
    if ref.owner is Owner.DEVICE and ref.device == here:
        return f"{ref.text} is this device's: write {ref.path}"
    device = here if ref.owner is Owner.HERE else ref.device
    if device is None or device not in index:
        return f"{ref.text}: device {device} is not in devices"
    if (target := index[device].get(ref.path)) is not None:
        return target
    whose = "this device" if ref.owner is Owner.HERE else f"device {device}"
    block = ref.path.partition(".")[0]
    if not any(path.partition(".")[0] == block for path in index[device]):
        return f"{ref.text}: {block} is not a block of {whose}"
    return f"{ref.text} is not an entity of {whose}"


def path(value: Any) -> str:
    """A reference, as written: a path of this device or of another, or a Home Assistant entity.

    Its segments are slugs: at least two in this device
    (appliance.running_program), the path after device.<device>. in another
    (device.washer.appliance.running_program), exactly a domain and an object
    ID after homeassistant. (homeassistant.binary_sensor.door). Whose it may
    be, and what it names, the checks decide.
    """
    text = cv.string(value)
    if not text:
        raise vol.Invalid("a path can't be empty")
    segments = text.split(".")
    if len(segments) < 2 or not all(segments):
        raise vol.Invalid(
            f"{text} is not a path: write it from its block, <block>.<key>"
        )
    for segment in segments:
        cv.slug(segment)
    if segments[0] == HOME_ASSISTANT and len(segments) != 3:
        raise vol.Invalid(
            f"{text} is not a Home Assistant entity: "
            f"{HOME_ASSISTANT}.<domain>.<object_id>"
        )
    if segments[0] == DEVICE and len(segments) < 4:
        raise vol.Invalid(
            f"{text} is not a path of another device: {DEVICE}.<device>.<block>.<key>"
        )
    return text


def homeassistant_entity(*domains: str) -> Callable[[Any], str]:
    """A field that takes only Home Assistant's entity: homeassistant.<domain>.<object_id>, of one of `domains` (any without).

    It hands its consumer the bare entity ID (sensor.plug_power), as Home
    Assistant names it; a refusal quotes what the author wrote, homeassistant.
    included.
    """

    def validate(value: Any) -> str:
        text = cv.string(value)
        first, _, written = text.partition(".")
        # Lowered, as Home Assistant's cv.entity_id does
        entity_id = written.lower()
        if first != HOME_ASSISTANT or not valid_entity_id(entity_id):
            raise vol.Invalid(
                f"{text} is not a Home Assistant entity: "
                f"{HOME_ASSISTANT}.<domain>.<object_id>"
            )
        if domains and entity_id.partition(".")[0] not in domains:
            raise vol.Invalid(f"{text} is not a {' or '.join(domains)}")
        return entity_id

    return validate


def key_alone(field: str, of: str) -> Callable[[Any], str]:
    """A field that takes one kind of thing, by its key alone: an area's, a program's.

    The field's name says what it is, so a path is refused, naming the key
    to write (then: programs.executable.blink is blink).
    """

    def validate(value: Any) -> str:
        if value == "":
            raise vol.Invalid(f"{field} can't be empty")
        if isinstance(value, str) and "." in value:
            raise vol.Invalid(
                f"{field} is its {of}'s key alone: {value.rpartition('.')[2]}"
            )
        return str(cv.slug(value))

    return validate
