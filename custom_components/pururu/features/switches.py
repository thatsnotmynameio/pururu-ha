"""Real switches inside the device: each shows its switch's state and passes commands on.

A switch is HA's switch group with the real switch as its only member, as a
mirror is a sensor group of one. Only switch.* is taken: a light, fan or cover
gets a feature of its own, on its own group, so it keeps what its domain offers.
"""

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.group.switch import SwitchGroup
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_registry as er

from ..const import DOMAIN, ENTITY_PREFIX
from ..entity import PururuEntity
from ..feature import Device, Feature

_LOGGER = logging.getLogger(__name__)


def _not_pururu(entity_id: str) -> str:
    """A pururu switch standing for itself would call itself forever."""
    if entity_id.startswith(f"{Platform.SWITCH}.{ENTITY_PREFIX}_"):
        raise vol.Invalid(f"{entity_id} is a pururu switch: name the real one")
    return entity_id


SWITCH = vol.Schema(
    {
        vol.Required("entity"): vol.All(cv.entity_domain(Platform.SWITCH), _not_pururu),
        # A blank name would show the switch as its device's name alone
        vol.Required("name"): vol.All(cv.string, vol.Strip, vol.Length(min=1)),
    }
)
# A schema of its own: ALLOW_EXTRA would let a key that isn't a slug through
SCHEMA = vol.All(vol.Schema({cv.slug: SWITCH}), vol.Length(min=1))


class Switch(PururuEntity, SwitchGroup):
    """The real switch's state; turning it on or off turns the real one."""

    def __init__(self, device: Device, entity_key: str, entity: str, name: str) -> None:
        """Stand for `entity` as `entity_key` of `device`, named `name`."""
        SwitchGroup.__init__(self, None, name, [entity], None)
        self._identify(device, Platform.SWITCH, entity_key, name)


def build(
    hass: HomeAssistant,
    device: Device,
    config: dict[str, Any],
    inputs: Mapping[str, str],
) -> list[PururuEntity]:
    """A switch per key of the block; none standing for a pururu switch.

    The configuration refuses switch.pururu_…; a pururu switch renamed in the
    UI gets past that, and only the registry still knows it is ours.
    """
    registry = er.async_get(hass)
    switches: list[PururuEntity] = []
    for entity_key, switch in config.items():
        entity = switch["entity"]
        registered = registry.async_get(entity)
        if registered is not None and registered.platform == DOMAIN:
            _LOGGER.error(
                "%s is a pururu switch: name the real one; not creating %s",
                entity,
                device.current_entity_id(hass, Platform.SWITCH, entity_key),
            )
            continue
        switches.append(Switch(device, entity_key, entity, switch["name"]))
    return switches


SWITCHES = Feature(
    schema=SCHEMA,
    entity_keys={},
    build=build,
    example={"pump": {"entity": "switch.demo_pump", "name": "Pump"}},
    configured=Platform.SWITCH,
)
