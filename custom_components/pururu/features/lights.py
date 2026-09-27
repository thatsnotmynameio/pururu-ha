"""Real lights inside the device: each shows its light's state, offers what it offers and passes commands on.

A light is HA's light group with the real light as its only member, as a switch
is a switch group of one: brightness, colours, effects and what the real light
supports are read from it at every change, never listed here.
"""

from collections.abc import Callable, Mapping
import logging
from typing import Any

from homeassistant.components.group.light import LightGroup
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, split_entity_id

from ..entity import PururuEntity
from ..feature import Device, Feature
from . import standing

_LOGGER = logging.getLogger(__name__)


class Light(PururuEntity, LightGroup):
    """The real light's state and what it offers; commands go to the real one."""

    def __init__(self, device: Device, entity_key: str, entity: str, name: str) -> None:
        """Stand for `entity` as `entity_key` of `device`, named `name`."""
        LightGroup.__init__(self, None, name, [entity], None)
        self._identify(device, Platform.LIGHT, entity_key, name)


# The domains `entity:` takes, and the light standing for each
KINDS: dict[Platform, Callable[[Device, str, str, str], PururuEntity]] = {
    Platform.LIGHT: Light,
}


def build(
    hass: HomeAssistant,
    device: Device,
    config: dict[str, Any],
    inputs: Mapping[str, str],
) -> list[PururuEntity]:
    """A light per key of the block, of the kind its real entity's domain gives.

    The configuration refuses <domain>.pururu_…; a pururu entity renamed in the
    UI gets past that, and only the registry still knows it is ours.
    """
    lights: list[PururuEntity] = []
    for entity_key, light in config.items():
        entity = light["entity"]
        domain = split_entity_id(entity)[0]
        if standing.is_pururu(hass, entity):
            _LOGGER.error(
                "%s is a pururu %s: name the real one; not creating %s",
                entity,
                domain,
                device.current_entity_id(hass, Platform.LIGHT, entity_key),
            )
            continue
        kind = KINDS[Platform(domain)]
        lights.append(kind(device, entity_key, entity, light["name"]))
    return lights


LIGHTS = Feature(
    schema=standing.schema(*KINDS),
    entity_keys={},
    build=build,
    example={"ceiling": {"entity": "light.demo_ceiling", "name": "Ceiling"}},
    namespace="light",
    configured=Platform.LIGHT,
)
