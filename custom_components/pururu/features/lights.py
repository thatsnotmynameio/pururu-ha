"""Real lights inside the device: each shows its light's state, offers what it offers and passes commands on.

A light is HA's light group with the real light as its only member, as a switch
is a switch group of one: brightness, colours, effects and what the real light
supports are read from it at every change, never listed here. A relay driving a
lamp is a switch: its light follows it on HA's group entity, on and off only,
which is all a switch exposes.
"""

from collections.abc import Callable, Mapping
import logging
from typing import Any, override

from homeassistant.components.group.entity import GroupEntity
from homeassistant.components.group.light import LightGroup
from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import HomeAssistant, callback, split_entity_id

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


class SwitchLight(PururuEntity, GroupEntity, LightEntity):
    """The real switch's state as a light's; turning it on or off turns the real one."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, device: Device, entity_key: str, entity: str, name: str) -> None:
        """Stand for `entity` as `entity_key` of `device`, named `name`."""
        self._entity_ids = [entity]
        self._attr_extra_state_attributes = {ATTR_ENTITY_ID: [entity]}
        self._identify(device, Platform.LIGHT, entity_key, name)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the real switch on: a switch takes no brightness or colour."""
        await self._forward(SERVICE_TURN_ON)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the real switch off."""
        await self._forward(SERVICE_TURN_OFF)

    async def _forward(self, service: str) -> None:
        """Call `service` on the real switch, with the caller's context for the logbook."""
        await self.hass.services.async_call(
            Platform.SWITCH,
            service,
            {ATTR_ENTITY_ID: self._entity_ids},
            blocking=True,
            context=self._context,
        )

    @callback
    @override
    def async_update_group_state(self) -> None:
        """On or off as the real switch; unknown while it has no state, unavailable while it is."""
        self._update_assumed_state_from_members()
        states = [
            state.state
            for entity_id in self._entity_ids
            if (state := self.hass.states.get(entity_id)) is not None
        ]
        known = [s for s in states if s not in (STATE_UNKNOWN, STATE_UNAVAILABLE)]
        self._attr_is_on = any(s == STATE_ON for s in known) if known else None
        self._attr_available = any(s != STATE_UNAVAILABLE for s in states)


# The domains `entity:` takes, and the light standing for each
KINDS: dict[Platform, Callable[[Device, str, str, str], PururuEntity]] = {
    Platform.LIGHT: Light,
    Platform.SWITCH: SwitchLight,
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
