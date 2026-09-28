"""Alert lights: the lights pururu's alerts borrow while they are on.

An alert with `lights` names a group of `config: alerts: lights: groups`.
While one of a light's alerts is on, the light shows the highest priority's
`turn_on`; once none is, `resolved`'s for its `for`, then it is turned off and
pururu_alert_lights_released says it is free. Only the light's turn_on and
turn_off are called: the light uses what it has.
"""

from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.light import ATTR_COLOR_NAME, LIGHT_TURN_ON_SCHEMA
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_NAME,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    Platform,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.util.color import color_name_to_rgb

from .const import CONF_ALERTS, CONF_CONFIG, CONF_LIGHTS, EVENT_ALERT_LIGHTS_RELEASED
from .feature import NO_READING, Device
from .features.alerts import PRIORITIES, ProblemAlert
from .features.lights import LIGHTS, Borrowable

_LOGGER = logging.getLogger(__name__)

GROUPS = "groups"
TURN_ON = "turn_on"
REPEAT = "repeat"
FOR = "for"
# What a light shows between its last alert's end and its release
RESOLVED = "resolved"


def _known_colour(params: dict[str, Any]) -> dict[str, Any]:
    """Refuse a colour name HA doesn't know: every call would fail."""
    if (name := params.get(ATTR_COLOR_NAME)) is not None:
        try:
            color_name_to_rgb(name)
        except ValueError as err:
            raise vol.Invalid(
                f"{name} is not a colour name Home Assistant knows"
            ) from err
    return params


# light.turn_on's data under its own names; the light is the group's, never given here
TURN_ON_SCHEMA = vol.All(vol.Schema(LIGHT_TURN_ON_SCHEMA), _known_colour)
# A whole number of seconds, written {seconds: N}
SECONDS = vol.All(
    vol.Schema({vol.Required("seconds"): vol.All(int, vol.Range(min=1))}),
    lambda value: timedelta(seconds=value["seconds"]),
)


def _distinct(lights: list[str]) -> list[str]:
    if len(set(lights)) != len(lights):
        raise vol.Invalid("a light is listed twice")
    return lights


# Device key -> keys of that device's lights; __init__ checks them against the devices
GROUP = vol.All(
    vol.Schema({cv.slug: vol.All([cv.slug], vol.Length(min=1), _distinct)}),
    vol.Length(min=1),
)
PRIORITY = vol.Schema(
    {vol.Required(TURN_ON): TURN_ON_SCHEMA, vol.Optional(REPEAT): SECONDS}
)
RESOLVED_SCHEMA = vol.Schema(
    {vol.Required(TURN_ON): TURN_ON_SCHEMA, vol.Required(FOR): SECONDS}
)


def _breathe(colour: str) -> dict[str, Any]:
    """A priority's default: breathe in `colour`, sent again every 15 s (a one-shot effect)."""
    return {
        TURN_ON: {"color_name": colour, "brightness_pct": 100, "effect": "breathe"},
        REPEAT: {"seconds": 15},
    }


# The defaults as the user would write them: validated like what the user writes
DEFAULTS: dict[str, dict[str, Any]] = {
    "high": _breathe("red"),
    "medium": _breathe("orange"),
    "low": _breathe("blue"),
    RESOLVED: {
        TURN_ON: {"color_name": "green", "brightness_pct": 50},
        FOR: {"seconds": 120},
    },
}

# config: alerts: lights:; a priority written replaces its default whole
SCHEMA = vol.Schema(
    {
        vol.Optional(GROUPS, default=dict): vol.Schema({cv.slug: GROUP}),
        **{
            vol.Optional(priority, default=DEFAULTS[priority]): PRIORITY
            for priority in PRIORITIES
        },
        vol.Optional(RESOLVED, default=DEFAULTS[RESOLVED]): RESOLVED_SCHEMA,
    }
)

# The manager's contexts a light remembers: a late report of an earlier call is still its own
RECENT = 4


def settings(configured: Mapping[str, Any]) -> dict[str, Any]:
    """The validated config: alerts: lights: of `pururu:`; every default without one."""
    block = configured.get(CONF_CONFIG, {}).get(CONF_ALERTS, {}).get(CONF_LIGHTS)
    return dict(block) if block is not None else SCHEMA({})


def light_ids(
    settings: Mapping[str, Any], devices: Mapping[str, Any]
) -> dict[str, list[str]]:
    """Each group's lights, by unique ID (pururu_<device>_light_<key>)."""
    return {
        group: [
            Device(
                key=key, name=devices[key][CONF_NAME], namespace=LIGHTS.namespace
            ).object_id(light)
            for key, lights in members.items()
            for light in lights
        ]
        for group, members in settings[GROUPS].items()
    }


@dataclass(eq=False)
class _Light:
    """A light some alerts may borrow, and what the manager does to it now."""

    entity: Borrowable
    # The created alerts whose group holds it
    alerts: list[ProblemAlert] = field(default_factory=list)
    # What it shows: a priority, resolved, or None while free
    shown: str | None = None
    # The ids of the manager's latest contexts on it
    recent: deque[str] = field(default_factory=lambda: deque(maxlen=RECENT))
    repeating: CALLBACK_TYPE | None = None
    resolving: CALLBACK_TYPE | None = None

    def own(self) -> Context:
        """A new context for the manager's next change of this light."""
        context = Context()
        self.recent.append(context.id)
        return context

    def stop_repeating(self) -> None:
        """Stop sending the priority again."""
        if self.repeating is not None:
            self.repeating()
            self.repeating = None

    def stop_resolving(self) -> None:
        """Stop counting resolved's `for`."""
        if self.resolving is not None:
            self.resolving()
            self.resolving = None


class AlertLights:
    """Lends each light to its alerts: the highest priority on, then resolved, then free."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        settings: Mapping[str, Any],
        lights: list[_Light],
    ) -> None:
        """Lend `lights` as `settings` say; nothing happens before start()."""
        self._hass = hass
        self._entry = entry
        self._settings = settings
        self._lights = lights
        self._by_id = {light.entity.entity_id: light for light in lights}
        # Each alert's last on (True) or off: a state that is neither changes nothing
        self._on: dict[str, bool] = {}

    @callback
    def start(self) -> None:
        """Show what each light's alerts say now, then follow them."""
        for light in self._lights:
            for alert in light.alerts:
                state = self._hass.states.get(alert.entity_id)
                self._on[alert.entity_id] = (
                    state is not None and state.state == STATE_ON
                )
        for light in self._lights:
            if self._level(light) is None and light.entity.restored_alert is not None:
                # Borrowed before the restart or reload, and none of its alerts is on now
                self._resolve(light)
            else:
                self._update(light)
        self._entry.async_on_unload(self._stop)
        self._entry.async_on_unload(
            async_track_state_change_event(
                self._hass, list(self._on), self._alert_changed
            )
        )
        self._entry.async_on_unload(
            async_track_state_change_event(
                self._hass, list(self._by_id), self._light_changed
            )
        )

    @callback
    def _stop(self) -> None:
        """Cancel the timers: an unload calls nothing on the lights."""
        for light in self._lights:
            light.stop_repeating()
            light.stop_resolving()

    def _holding(self, light: _Light) -> list[str]:
        """The entity IDs of the light's alerts that are on."""
        return [
            alert.entity_id for alert in light.alerts if self._on.get(alert.entity_id)
        ]

    def _level(self, light: _Light) -> str | None:
        """The highest priority among the light's alerts that are on; None if none is."""
        on = [alert.priority for alert in light.alerts if self._on.get(alert.entity_id)]
        return max(on, key=PRIORITIES.index) if on else None

    @callback
    def _alert_changed(self, event: Event[EventStateChangedData]) -> None:
        """An alert turned on or off: update the lights of its group."""
        new = event.data["new_state"]
        if new is None or new.state not in (STATE_ON, STATE_OFF):
            return
        entity_id = event.data["entity_id"]
        on = new.state == STATE_ON
        if self._on.get(entity_id) == on:
            return
        self._on[entity_id] = on
        for light in self._lights:
            if any(alert.entity_id == entity_id for alert in light.alerts):
                self._update(light)

    @callback
    def _light_changed(self, event: Event[EventStateChangedData]) -> None:
        """Someone else changed a borrowed light: put it back, or during resolved let it go.

        The manager's own changes carry one of its recent contexts. A light
        without a reading was taken by nobody; one back from it during
        resolved shows resolved again, its `for` running on.
        """
        light = self._by_id[event.data["entity_id"]]
        old, new = event.data["old_state"], event.data["new_state"]
        if light.shown is None or old is None or new is None:
            return
        if new.state in NO_READING or event.context.id in light.recent:
            return
        if light.shown != RESOLVED:
            self._apply(light, light.shown)
        elif old.state in NO_READING:
            self._apply(light, RESOLVED)
        else:
            self._release(light, turn_off=False)

    @callback
    def _update(self, light: _Light) -> None:
        """Show what the light's alerts say: the highest priority on, resolved once the last ends."""
        level = self._level(light)
        if level is None:
            if light.shown in PRIORITIES:
                self._resolve(light)
            return
        light.stop_resolving()
        if level == light.shown:
            # An alert of the same priority joined or left
            light.entity.async_show_alert(level, self._holding(light), light.own())
            return
        light.stop_repeating()
        self._apply(light, level)
        if (repeat := self._settings[level].get(REPEAT)) is not None:
            light.repeating = async_track_time_interval(
                self._hass, partial(self._repeat, light), repeat
            )

    @callback
    def _repeat(self, light: _Light, _now: datetime) -> None:
        """Send the priority's turn_on again: a one-shot effect has ended by now."""
        if light.shown is not None and light.shown != RESOLVED:
            self._apply(light, light.shown)

    @callback
    def _apply(self, light: _Light, shown: str) -> None:
        """Show `shown` on the light and turn it on as its settings say, as the manager's change."""
        context = light.own()
        light.shown = shown
        light.entity.async_show_alert(shown, self._holding(light), context)
        self._call(light, SERVICE_TURN_ON, self._settings[shown][TURN_ON], context)

    @callback
    def _resolve(self, light: _Light) -> None:
        """Show resolved for its `for`, then hand the light back."""
        light.stop_repeating()
        light.stop_resolving()
        self._apply(light, RESOLVED)
        light.resolving = async_call_later(
            self._hass, self._settings[RESOLVED][FOR], partial(self._resolved, light)
        )

    @callback
    def _resolved(self, light: _Light, _now: datetime) -> None:
        light.resolving = None
        self._release(light, turn_off=True)

    @callback
    def _release(self, light: _Light, *, turn_off: bool) -> None:
        """Free the light: turned off first, unless someone took it back."""
        light.stop_repeating()
        light.stop_resolving()
        context = light.own()
        light.shown = None
        light.entity.async_show_alert(None, (), context)
        released = partial(self._released, light, context)
        if turn_off:
            self._call(light, SERVICE_TURN_OFF, {}, context, then=released)
        else:
            released()

    @callback
    def _released(self, light: _Light, context: Context) -> None:
        """Say the light is free, unless an alert took it again meanwhile."""
        if light.shown is None:
            self._hass.bus.async_fire(
                EVENT_ALERT_LIGHTS_RELEASED,
                {ATTR_ENTITY_ID: light.entity.entity_id},
                context=context,
            )

    @callback
    def _call(
        self,
        light: _Light,
        service: str,
        data: Mapping[str, Any],
        context: Context,
        then: Callable[[], None] | None = None,
    ) -> None:
        """Call light.`service` on the light in a task of the entry; `then` once it returned."""
        self._entry.async_create_task(
            self._hass,
            self._async_call(light.entity.entity_id, service, data, context, then),
            f"pururu alert lights {service}",
        )

    async def _async_call(
        self,
        entity_id: str,
        service: str,
        data: Mapping[str, Any],
        context: Context,
        then: Callable[[], None] | None,
    ) -> None:
        """A failure is a warning: the next repeat or change tries again."""
        try:
            await self._hass.services.async_call(
                Platform.LIGHT,
                service,
                {ATTR_ENTITY_ID: entity_id, **data},
                blocking=True,
                context=context,
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "The alert lights couldn't call light.%s on %s: %s",
                service,
                entity_id,
                err,
            )
        if then is not None:
            then()


@callback
def async_setup(
    hass: HomeAssistant,
    entry: ConfigEntry,
    settings: Mapping[str, Any],
    groups: Mapping[str, list[str]],
    alerts: Iterable[ProblemAlert],
    lights: Iterable[Borrowable],
) -> None:
    """Lend the created lights to the created alerts with lights, once HA has started.

    `groups`: each group's lights, by unique ID. A light of a group that isn't
    created is logged and left out; a disabled one is left out, as HA never
    added it. A light the alert lights had before a restart or reload is
    handed back even when it is in no group now.
    """
    registry = er.async_get(hass)
    built = list(lights)
    created = {str(light.unique_id) for light in built}
    for group, members in groups.items():
        for unique_id in members:
            if unique_id not in created:
                _LOGGER.warning(
                    "%s.%s is not created: the alert lights group %s goes without it",
                    Platform.LIGHT,
                    unique_id,
                    group,
                )
    enabled = {
        str(light.unique_id): light for light in built if _enabled(registry, light)
    }
    borrowed: dict[str, _Light] = {}
    for alert in alerts:
        if alert.lights is None:
            continue
        for unique_id in groups[alert.lights]:
            if (entity := enabled.get(unique_id)) is not None:
                borrowed.setdefault(unique_id, _Light(entity)).alerts.append(alert)
    for unique_id, entity in enabled.items():
        if unique_id not in borrowed and entity.restored_alert is not None:
            borrowed[unique_id] = _Light(entity)
    manager = AlertLights(hass, entry, settings, list(borrowed.values()))

    @callback
    def start(_hass: HomeAssistant) -> None:
        manager.start()

    entry.async_on_unload(async_at_started(hass, start))


def _enabled(registry: er.EntityRegistry, light: Borrowable) -> bool:
    """Whether the user left the light enabled."""
    registered = registry.async_get(light.entity_id)
    return registered is None or not registered.disabled
