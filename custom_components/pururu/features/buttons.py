"""Buttons of the device: a value of a real sensor, pressed when the sensor takes it.

A button is HA's button entity: its state is the time of its last press, which
HA keeps across restarts and reloads. Pressing it in HA and its sensor taking
its value are the same press. pururu knows nothing of remotes or vendors: the
configuration names a sensor and the value that counts as a press.

No press nobody made: only a change into the value presses, once HA runs,
from a real reading (see `pressed`). A value written again never does: a
sensor that holds its value and is rewritten would press by itself.
"""

from collections.abc import Hashable, Iterator, Mapping
from datetime import timedelta
import logging
from typing import Any, override

import voluptuous as vol

from homeassistant.components.button import ButtonEntity
from homeassistant.const import (
    ATTR_RESTORED,
    STATE_OFF,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import (
    Context,
    CoreState,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

# Not `from ..aspects.programs import …`: the package import reaches this module
# through features/__init__ while aspects.programs is still loading
from ..aspects import programs
from ..const import CONF_DEVICES
from ..core.entity import PururuEntity
from ..core.feature import TEXT, Device, Feature, state_text
from ..core.generated import SCRIPTS
from ..core.roles import Configured
from ..core.vocabulary import NO_READING
from . import standing

_LOGGER = logging.getLogger(__name__)

# The feature's key in a device's configuration
CONF_BUTTONS = "buttons"
# How long a sensor stays unknown before its first value can be a press: a
# sensor just set up gets its first (retained) value within milliseconds, a
# person pressing after a restart well after
SETTLE = timedelta(seconds=3)


def pressed_state(value: Any) -> str:
    """The value that counts as a press: a state, never one that means no reading."""
    state = state_text(value)
    if state in NO_READING:
        raise vol.Invalid(f"{state} is not a value a person presses")
    return state


def pressed(old: State | None, new: State | None, value: str) -> bool:
    """Whether this change of the sensor is a press of the button whose value is `value`.

    Only a change into the value, from a real reading: not the sensor
    appearing (no old state), coming back (unavailable), restored, or written
    again (attributes alone, force_update); from unknown only once it has been
    unknown for SETTLE.
    """
    if old is None or new is None or new.state != value or old.state == value:
        return False
    if old.state == STATE_UNAVAILABLE or old.attributes.get(ATTR_RESTORED):
        return False
    return old.state != STATE_UNKNOWN or new.last_changed - old.last_changed >= SETTLE


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
        # The unique ID of its program's script; None without a program
        self._script = (
            None
            if (program := button.get("program")) is None
            else programs.script_id(device.key, program)
        )

    @override
    async def async_added_to_hass(self) -> None:
        """Watch the sensor: a change into the value presses the button."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(self.hass, self._entity, self._changed)
        )

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        """Press when the sensor took the value, once HA runs.

        Not hass.is_running: it is already true while HA starts, when a value
        arriving is no person's. The press runs with a context descending from
        the sensor's write, so the logbook says where it came from.
        """
        entry = self.platform.config_entry
        if (
            entry is None
            or self.hass.state is not CoreState.running
            or not pressed(
                event.data["old_state"], event.data["new_state"], self._state
            )
        ):
            return
        self.async_set_context(Context(parent_id=event.context.id))
        entry.async_create_task(
            self.hass, self._async_press_action(), f"pururu press {self.entity_id}"
        )

    @override
    async def async_press(self) -> None:
        """Start the program, once the press's time is recorded: only when it is idle.

        Its script is found now, renamed or not: scripts are written after the
        entities. Only a script the entry manages (generated: a script of the
        user's holding its ID is theirs, never started) whose state is `off` is
        generated and idle; running, held out (HA's restored placeholder) or
        not loaded yet start nothing. Not awaited: a start single mode refuses
        would wait for the running program's next step.
        """
        entry = self.platform.config_entry
        if self._script is None or entry is None:
            return
        script = er.async_get(self.hass).async_get_entity_id(
            SCRIPTS.domain, SCRIPTS.domain, self._script
        )
        if (
            self._script not in entry.data.get(SCRIPTS.data_key, [])
            or script is None
            or not self.hass.states.is_state(script, STATE_OFF)
        ):
            _LOGGER.debug(
                "%s: script.%s is not idle; not starting it",
                self.entity_id,
                self._script,
            )
            return
        await self.hass.services.async_call(
            SCRIPTS.domain,
            "turn_on",
            {"entity_id": script},
            blocking=False,
            context=self._context,
        )


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


def check(house: Mapping[str, Any], *_: Any) -> Iterator[vol.Invalid]:
    """Refuse a button's program that isn't its device's, and one value pressing two buttons.

    A button starts one of its own device's executable programs. Two buttons
    of a device on the same sensor and value would be pressed together.
    """
    for key, device in house[CONF_DEVICES].items():
        pressing: dict[tuple[str, str], str] = {}
        for button_key, button in device.get(CONF_BUTTONS, {}).items():
            path: list[Hashable] = [CONF_DEVICES, key, CONF_BUTTONS, button_key]
            program = button.get("program")
            if program is not None and program not in programs.executable(device):
                yield vol.Invalid(
                    f"buttons: {button_key}: {program} is not an executable program "
                    "of this device",
                    path=path,
                )
            value = (button["entity"], button["state"])
            if (other := pressing.setdefault(value, button_key)) != button_key:
                yield vol.Invalid(
                    f"buttons: {button_key}: {value[0]} at {value[1]} is already "
                    f"button {other}",
                    path=path,
                )


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
