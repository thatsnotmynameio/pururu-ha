"""Real lights inside the device: each shows its light's state, offers what it offers and passes commands on.

A light is HA's light group with the real light as its only member, as a switch
is a switch group of one: brightness, colours, effects and what the real light
supports are read from it at every change, never listed here. A relay driving a
lamp is a switch: its light follows it on HA's group entity, on and off only,
which is all a switch exposes. Both kinds can be borrowed by the alert lights
(alert_lights.py): they show what for, and remember it across restarts.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import logging
from typing import Any, override

from homeassistant.components.group.entity import GroupEntity
from homeassistant.components.group.light import LightGroup
from homeassistant.components.light import ATTR_EFFECT, ColorMode, LightEntity
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import Context, HomeAssistant, callback, split_entity_id
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from ..core.entity import PururuEntity
from ..core.feature import Device, Feature
from ..core.roles import Actions, Configured
from . import standing

_LOGGER = logging.getLogger(__name__)

# What the alert lights show on a light they borrow (alert_lights.py)
ATTR_ALERT = "alert"
ATTR_ALERTS = "alerts"


@dataclass(frozen=True)
class AlertShown(ExtraStoredData):
    """What the alert lights showed on a light, kept apart from its state.

    HA saves no attributes of an unavailable entity, and a bulb may well be
    offline at a restart or reload.
    """

    alert: str | None

    @override
    def as_dict(self) -> dict[str, Any]:
        return {ATTR_ALERT: self.alert}


class Borrowable(PururuEntity, RestoreEntity):
    """A light the alert lights may borrow: says what for, and remembers it across restarts."""

    # What the alert lights showed before a restart or reload; None: nothing
    restored_alert: str | None = None
    _alert: str | None = None
    _alerts: tuple[str, ...] = ()

    @override
    async def async_added_to_hass(self) -> None:
        """Follow the real entity as the group does, then read what the alert lights showed."""
        await super().async_added_to_hass()
        if (extra := await self.async_get_last_extra_data()) is not None:
            self.restored_alert = extra.as_dict().get(ATTR_ALERT)

    @property
    @override
    def extra_restore_state_data(self) -> AlertShown:
        """What the alert lights show now, restored whether or not the light is available."""
        return AlertShown(self._alert)

    @callback
    def async_show_alert(
        self, alert: str | None, alerts: Iterable[str], context: Context
    ) -> None:
        """Show what the alert lights use it for (None: free), written as their change."""
        self._alert = alert
        self._alerts = tuple(alerts)
        self.async_set_context(context)
        self.async_write_ha_state()

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The group's attributes; while borrowed, what for and by which alerts."""
        attributes = dict(super().extra_state_attributes or {})
        if self._alert is not None:
            attributes[ATTR_ALERT] = self._alert
            attributes[ATTR_ALERTS] = list(self._alerts)
        return attributes


class Light(Borrowable, LightGroup):
    """The real light's state and what it offers; commands go to the real one."""

    def __init__(
        self, device: Device, entity_key: str, entity: str | None, name: str
    ) -> None:
        """Stand for `entity` as `entity_key` of `device`, named `name`; None: for nothing."""
        LightGroup.__init__(self, None, name, standing.members(entity), None)
        self._identify(device, Platform.LIGHT, entity_key, name)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Pass everything on, but an effect the real light doesn't list.

        HA drops an effect only for a light without effects; a bulb with
        others would refuse this one.
        """
        if ATTR_EFFECT in kwargs and kwargs[ATTR_EFFECT] not in (
            self.effect_list or ()
        ):
            kwargs = {key: value for key, value in kwargs.items() if key != ATTR_EFFECT}
        await super().async_turn_on(**kwargs)


class SwitchLight(Borrowable, GroupEntity, LightEntity):
    """The real switch's state as a light's; turning it on or off turns the real one."""

    # Until HA starts and it reads the real switch, as LightGroup and SwitchGroup
    _attr_available = False
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(
        self, device: Device, entity_key: str, entity: str | None, name: str
    ) -> None:
        """Stand for `entity` as `entity_key` of `device`, named `name`; None: for nothing."""
        self._entity_ids = standing.members(entity)
        self._attr_extra_state_attributes = {ATTR_ENTITY_ID: self._entity_ids}
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
KINDS: dict[Platform, Callable[[Device, str, str | None, str], PururuEntity]] = {
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
    UI gets past that, and only the registry still knows it is ours. A light
    renamed to its own entity is kept, standing for nothing: unavailable, never
    calling itself, its rename kept, and every reload gives the same.
    """
    lights: list[PururuEntity] = []
    for entity_key, light in config.items():
        entity = light["entity"]
        domain = split_entity_id(entity)[0]
        kind = KINDS[Platform(domain)]
        current = device.current_entity_id(hass, Platform.LIGHT, entity_key)
        if entity == current:
            _LOGGER.error("%s is this light itself: name the real one", entity)
            lights.append(kind(device, entity_key, None, light["name"]))
            continue
        if standing.is_pururu(hass, entity):
            _LOGGER.error(
                "%s is a pururu %s: name the real one; not creating %s",
                entity,
                domain,
                current,
            )
            continue
        lights.append(kind(device, entity_key, entity, light["name"]))
    return lights


LIGHTS = Feature(
    schema=standing.schema(*KINDS),
    entity_keys={},
    build=build,
    example={"ceiling": {"entity": "light.demo_ceiling", "name": "Ceiling"}},
    namespace="light",
    roles=(Configured(Platform.LIGHT), Actions(("turn_on", "turn_off", "toggle"))),
)
