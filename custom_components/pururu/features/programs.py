"""Programs: sequences of actions on the device's own entities, each run by a button.

A program is a method of its device: someone presses it, and it turns the
device's own switches on and off, with delays between. Its steps are pururu's,
translated to Home Assistant's script syntax and run by HA's Script helper; no
step can reach outside the device.
"""

from collections.abc import Iterator, Mapping
import logging
from typing import Any, override

import voluptuous as vol

from homeassistant.components.button import ButtonEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, split_entity_id
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.script import SCRIPT_MODE_SINGLE, Script

from ..const import DOMAIN
from ..entity import PururuEntity
from ..feature import Device, Feature

_LOGGER = logging.getLogger(__name__)

DELAY = "delay"
# What a step can do to an entity; `_device` checks the entity's feature takes it.
# Fixed here: this module can't read FEATURES, which imports it
ACTIONS = ("turn_on", "turn_off", "toggle")

STEP = vol.Schema(
    {
        vol.Optional(DELAY): cv.positive_time_period,
        **{vol.Optional(action): cv.slug for action in ACTIONS},
    }
)


def _step(value: Any) -> dict[str, Any]:
    """One of delay, turn_on, turn_off, toggle, with its value: exactly one key."""
    step: dict[str, Any] = STEP(value)
    if len(step) != 1:
        raise vol.Invalid(f"a step is exactly one of {DELAY}, {', '.join(ACTIONS)}")
    return step


PROGRAM = vol.Schema(
    {
        # A blank name would show the program as its device's name alone
        vol.Required("name"): vol.All(cv.string, vol.Strip, vol.Length(min=1)),
        vol.Required("sequence"): vol.All([_step], vol.Length(min=1)),
    }
)
# A schema of its own: ALLOW_EXTRA would let a key that isn't a slug through
SCHEMA = vol.All(vol.Schema({cv.slug: PROGRAM}), vol.Length(min=1))


def _targets(program: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """(action, entity key) of each step that acts on an entity, in order."""
    for step in program["sequence"]:
        yield from ((action, key) for action, key in step.items() if action != DELAY)


def _acts(config: dict[str, Any]) -> list[tuple[str, str]]:
    return [pair for program in config.values() for pair in _targets(program)]


def _refers(config: dict[str, Any]) -> set[str]:
    return {key for _, key in _acts(config)}


def _translated(
    program: dict[str, Any], inputs: Mapping[str, str]
) -> list[dict[str, Any]]:
    """The steps in Home Assistant's script syntax, on the targets' current entity IDs."""
    sequence: list[dict[str, Any]] = []
    for step in program["sequence"]:
        ((action, value),) = step.items()
        if action == DELAY:
            sequence.append({DELAY: value})
            continue
        entity_id = inputs[value]
        sequence.append(
            {
                "action": f"{split_entity_id(entity_id)[0]}.{action}",
                "target": {"entity_id": entity_id},
            }
        )
    validated: list[dict[str, Any]] = cv.SCRIPT_SCHEMA(sequence)
    return validated


class Program(PururuEntity, ButtonEntity):
    """Pressed, it starts its sequence and returns; a press while it runs is ignored."""

    def __init__(
        self,
        device: Device,
        entity_key: str,
        name: str,
        sequence: list[dict[str, Any]],
        follows: tuple[str, ...],
    ) -> None:
        """Run `sequence` as `entity_key` of `device`, named `name`, acting on `follows`."""
        self._identify(device, Platform.BUTTON, entity_key, name)
        self.follows = follows
        self._title = f"{device.name} {name}"
        self._sequence = sequence
        # Built once added: an entity that is never added leaves no script behind
        self._script: Script | None = None

    @override
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._script = Script(
            self.hass,
            self._sequence,
            self._title,
            DOMAIN,
            logger=_LOGGER,
            script_mode=SCRIPT_MODE_SINGLE,
        )

    @override
    async def async_press(self) -> None:
        """Start the sequence without waiting for it, as script.turn_on."""
        if self._script is None:
            return
        self.hass.async_create_background_task(
            self._run(self._script),
            f"{DOMAIN} program {self.entity_id}",
        )

    async def _run(self, script: Script) -> None:
        """Run it once; a failed step stops it, and the script has logged why."""
        try:
            await script.async_run(context=self._context)
        except Exception:  # noqa: BLE001 - logged by the script, with the program's name
            return


def build(
    hass: HomeAssistant,
    device: Device,
    config: dict[str, Any],
    inputs: Mapping[str, str],
) -> list[PururuEntity]:
    """A button per program, on the current entity IDs of what it acts on."""
    return [
        Program(
            device,
            entity_key,
            program["name"],
            _translated(program, inputs),
            tuple(dict.fromkeys(key for _, key in _targets(program))),
        )
        for entity_key, program in config.items()
    ]


PROGRAMS = Feature(
    schema=SCHEMA,
    entity_keys={},
    build=build,
    example={
        "clean": {
            "name": "Clean",
            "sequence": [
                {"turn_on": "switch_pump"},
                {"delay": {"hours": 2}},
                {"turn_off": "switch_pump"},
            ],
        }
    },
    namespace="program",
    configured=Platform.BUTTON,
    refers=_refers,
    acts=_acts,
)
