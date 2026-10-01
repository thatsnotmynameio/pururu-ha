"""Real switches inside the device: each shows its switch's state and passes commands on.

A switch is HA's switch group with the real switch as its only member, as a
mirror is a sensor group of one. Only switch.* is taken: a light, fan or cover
gets a feature of its own, on its own group, so it keeps what its domain offers.
"""

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.components.group.switch import SwitchGroup
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from ..core.entity import PururuEntity
from ..core.feature import Device, Feature
from ..core.roles import Actions, Configured
from . import standing

_LOGGER = logging.getLogger(__name__)


class Switch(PururuEntity, SwitchGroup):
    """The real switch's state; turning it on or off turns the real one."""

    def __init__(
        self, device: Device, entity_key: str, entity: str | None, name: str
    ) -> None:
        """Stand for `entity` as `entity_key` of `device`, named `name`; None: for nothing."""
        SwitchGroup.__init__(self, None, name, standing.members(entity), None)
        self._identify(device, Platform.SWITCH, entity_key, name)


def build(
    hass: HomeAssistant,
    device: Device,
    config: dict[str, Any],
    inputs: Mapping[str, str],
) -> list[PururuEntity]:
    """A switch per key of the block; none standing for a pururu switch.

    The configuration refuses switch.pururu_…; a pururu switch renamed in the
    UI gets past that, and only the registry still knows it is ours. A switch
    renamed to its own entity is kept, standing for nothing: unavailable, never
    calling itself, its rename kept, and every reload gives the same.
    """
    switches: list[PururuEntity] = []
    for entity_key, switch in config.items():
        entity = switch["entity"]
        current = device.current_entity_id(hass, Platform.SWITCH, entity_key)
        if entity == current:
            _LOGGER.error("%s is this switch itself: name the real one", entity)
            switches.append(Switch(device, entity_key, None, switch["name"]))
            continue
        if standing.is_pururu(hass, entity):
            _LOGGER.error(
                "%s is a pururu switch: name the real one; not creating %s",
                entity,
                current,
            )
            continue
        switches.append(Switch(device, entity_key, entity, switch["name"]))
    return switches


SWITCHES = Feature(
    schema=standing.schema(Platform.SWITCH),
    entity_keys={},
    build=build,
    example={
        "sprinkler": {
            "entity": "homeassistant.switch.dummy_sprinkler",
            "name": "Sprinkler",
        }
    },
    namespace="switch",
    roles=(Configured(Platform.SWITCH), Actions(("turn_on", "turn_off", "toggle"))),
)
