"""Buttons of the device: a value of a real sensor, pressed when the sensor takes it.

A button is HA's button entity: its state is the time of its last press, which
HA keeps across restarts and reloads. Pressing it in HA and its sensor taking
its value are the same press. pururu knows nothing of remotes or vendors: the
configuration names a sensor and the value that counts as a press.
"""

from collections.abc import Mapping
import logging
from typing import Any, override

import voluptuous as vol

from homeassistant.components.button import ButtonEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from ..core.entity import PururuEntity
from ..core.feature import TEXT, Device, Feature, state_text
from ..core.roles import Configured
from . import standing

_LOGGER = logging.getLogger(__name__)

# What a sensor shows while it has no reading: no person presses it
NO_READING = (STATE_UNAVAILABLE, STATE_UNKNOWN)


def pressed_state(value: Any) -> str:
    """The value that counts as a press: a state, never one that means no reading."""
    state = state_text(value)
    if state in NO_READING:
        raise vol.Invalid(f"{state} is not a value a person presses")
    return state


ITEM = vol.Schema(
    {
        vol.Required("entity"): standing.real_entity(Platform.SENSOR),
        vol.Required("state"): pressed_state,
        # A blank name would show the button as its device's name alone
        vol.Required("name"): TEXT,
        vol.Optional("program"): cv.slug,
    }
)

# A schema of its own: ALLOW_EXTRA would let a key that isn't a slug through
SCHEMA = vol.All(vol.Schema({cv.slug: ITEM}), vol.Length(min=1))


class Button(PururuEntity, ButtonEntity):
    """A press records its time; always available, so the time survives a restart."""

    def __init__(
        self, device: Device, entity_key: str, button: Mapping[str, Any]
    ) -> None:
        """The button `entity_key` of `device`, as configured."""
        self._identify(device, Platform.BUTTON, entity_key, button["name"])
        self._entity = button["entity"]
        self._state = button["state"]

    @override
    async def async_press(self) -> None:
        """What a press does once its time is recorded."""


def build(
    hass: HomeAssistant,
    device: Device,
    config: dict[str, Any],
    inputs: Mapping[str, str],
) -> list[PururuEntity]:
    """A button per key of the block; none on a pururu sensor.

    The configuration refuses sensor.pururu_…; a pururu sensor renamed in the
    UI gets past that, and only the registry still knows it is ours.
    """
    buttons: list[PururuEntity] = []
    for entity_key, button in config.items():
        if standing.is_pururu(hass, button["entity"]):
            _LOGGER.error(
                "%s is a pururu sensor: name the real one; not creating %s",
                button["entity"],
                device.current_entity_id(hass, Platform.BUTTON, entity_key),
            )
            continue
        buttons.append(Button(device, entity_key, button))
    return buttons


BUTTONS = Feature(
    schema=SCHEMA,
    entity_keys={},
    build=build,
    example={
        "read": {
            "entity": "sensor.dummy_remote_action",
            "state": "1_single",
            "name": "Read",
        }
    },
    namespace="button",
    roles=(Configured(Platform.BUTTON),),
)
