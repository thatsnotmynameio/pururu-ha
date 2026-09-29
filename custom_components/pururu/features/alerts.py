"""Alerts: conditions on the device's own entities that mean something is wrong.

Each alert is a problem binary sensor, on while its condition holds (after
`for`). With `notify`, it also says what to tell; Alert2 does the telling,
reading its attributes. pururu sends nothing.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
import logging
from typing import Any, override

import voluptuous as vol

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import STATE_ON, Platform
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.start import async_at_started

from ..const import ALERT2, DEFAULT_ALERT_LIGHTS
from ..entity import PururuEntity
from ..feature import PRIORITIES, TEXT, Device, Feature, finite_float, state_text
from ..vocabulary import Condition

_LOGGER = logging.getLogger(__name__)


def _state(value: Any) -> str | float:
    """A state to compare with, or a number to compare a reading with.

    A number is compared as a number, so 1 matches a state of 1.0.
    """
    if isinstance(value, int | float) and not isinstance(value, bool):
        return finite_float(value)
    return state_text(value)


def _one_condition(alert: dict[str, Any]) -> dict[str, Any]:
    if ("is" in alert) == ("above" in alert or "below" in alert):
        raise vol.Invalid("an alert needs is, or above and/or below, not both")
    if "above" in alert and "below" in alert and alert["above"] >= alert["below"]:
        raise vol.Invalid("an alert's above must be lower than its below")
    return alert


# What to tell, for Alert2 to deliver; a schema of its own, so unknown keys are refused
NOTIFY = vol.Schema({vol.Required("message"): TEXT, vol.Required("done_message"): TEXT})


def lights_group(value: Any) -> str | None:
    """An alert's alert lights group (alert_lights.py): true is the default group, false none."""
    if isinstance(value, bool):
        return DEFAULT_ALERT_LIGHTS if value else None
    return str(cv.slug(value))


ALERT = vol.All(
    vol.Schema(
        {
            # A blank name would show the alert as its device's name alone
            vol.Required("name"): TEXT,
            vol.Required("when"): cv.slug,
            vol.Optional("is"): _state,
            vol.Optional("above"): finite_float,
            vol.Optional("below"): finite_float,
            vol.Optional("for", default=timedelta(0)): cv.positive_time_period,
            vol.Optional("priority", default="low"): vol.In(PRIORITIES),
            vol.Optional("notify"): NOTIFY,
            vol.Optional("lights"): lights_group,
        }
    ),
    _one_condition,
)
# A schema of its own: ALLOW_EXTRA would let a key that isn't a slug through
SCHEMA = vol.All(vol.Schema({cv.slug: ALERT}), vol.Length(min=1))


class ProblemAlert(PururuEntity, BinarySensorEntity, RestoreEntity):
    """On while something is wrong: what it watches, its priority, what to tell.

    Restores its state; follows what it watches once HA has started (entities
    pass through unavailable while it starts).
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        *,
        watched: str,
        priority: str,
        notify: Mapping[str, str] | None,
        asks_alert2: bool = True,
        lights: str | None = None,
    ) -> None:
        """Watch `watched`; `notify` is what Alert2 tells, `lights` the group it borrows.

        `asks_alert2` False: its notify is a ready-made alert's own texts, not a
        request of the user's, so no error without Alert2.
        """
        self._watched = watched
        self._asks_alert2 = asks_alert2 and notify is not None
        self.priority = priority
        self.notify = notify
        self.lights = lights
        self._attr_is_on = False
        self._attr_extra_state_attributes = {
            "priority": priority,
            "watches": watched,
            **({"lights": lights} if lights is not None else {}),
            **(notify or {}),
        }
        self._pending: CALLBACK_TYPE | None = None

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the state, then follow what it watches once HA has started."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == STATE_ON
        self.async_on_remove(self._cancel)
        self.async_on_remove(async_at_started(self.hass, self._start))

    @callback
    def _start(self, _hass: HomeAssistant) -> None:
        """Follow; also the time to know whether Alert2, which delivers `notify`, is set up.

        Alert2 may load after pururu.
        """
        if self._asks_alert2 and ALERT2 not in self.hass.config.components:
            _LOGGER.error(
                "%s has notify, but Alert2 isn't set up to deliver it", self.entity_id
            )
        self._follow()

    @callback
    def _follow(self) -> None:
        """Track what it watches and evaluate it now."""
        raise NotImplementedError

    @callback
    def _cancel(self) -> None:
        if self._pending is not None:
            self._pending()
            self._pending = None

    @callback
    def _set(self, *, on: bool) -> None:
        if on != self._attr_is_on:
            self._attr_is_on = on
            self.async_write_ha_state()


class Alert(ProblemAlert):
    """On while its condition holds, after `for`; holds while the watched entity has no reading."""

    def __init__(
        self,
        device: Device,
        entity_key: str,
        *,
        name: str | None,
        watched: str,
        condition: Condition,
        hold: timedelta,
        priority: str,
        notify: Mapping[str, str] | None,
        follows: tuple[str, ...] = (),
        sources: tuple[str, ...] = (),
        asks_alert2: bool = True,
        lights: str | None = None,
    ) -> None:
        """Watch `watched` for `condition` held for `hold`; `name` None: translated."""
        super().__init__(
            watched=watched,
            priority=priority,
            notify=notify,
            asks_alert2=asks_alert2,
            lights=lights,
        )
        self._identify(device, Platform.BINARY_SENSOR, entity_key, name)
        self.follows = follows
        self.sources = sources
        self._condition = condition
        self._hold = hold

    @override
    @callback
    def _follow(self) -> None:
        self.async_on_remove(
            async_track_state_change_event(self.hass, self._watched, self._changed)
        )
        # Not there yet, as the device's other platforms set up alongside: no reading
        if (state := self.hass.states.get(self._watched)) is not None:
            self._evaluate(state)

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        self._evaluate(event.data["new_state"])

    @callback
    def _evaluate(self, state: State | None) -> None:
        """Turn off at once, start `for` towards on, or, without a reading, keep the state."""
        holds = self._condition.holds(state)
        if not holds:
            self._cancel()
            if holds is False:
                self._set(on=False)
        elif not self._attr_is_on and self._pending is None:
            if self._hold:
                self._pending = async_call_later(self.hass, self._hold, self._turn_on)
            else:
                self._set(on=True)

    @callback
    def _turn_on(self, _now: datetime) -> None:
        self._pending = None
        self._set(on=True)


def build(
    hass: HomeAssistant,
    device: Device,
    config: dict[str, Any],
    inputs: Mapping[str, str],
) -> list[PururuEntity]:
    """An alert per key of the block, watching the entity its `when` names."""
    return [
        Alert(
            device,
            entity_key,
            name=alert["name"],
            watched=inputs[alert["when"]],
            condition=Condition(
                state=alert.get("is"),
                above=alert.get("above"),
                below=alert.get("below"),
            ),
            hold=alert["for"],
            priority=alert["priority"],
            notify=alert.get("notify"),
            lights=alert.get("lights"),
            follows=(alert["when"],),
        )
        for entity_key, alert in config.items()
    ]


def _refers(config: dict[str, Any]) -> set[str]:
    """The entity keys the alerts watch."""
    return {alert["when"] for alert in config.values()}


ALERTS = Feature(
    schema=SCHEMA,
    entity_keys={},
    build=build,
    example={"too_long": {"name": "Too long", "when": "appliance_running", "is": "on"}},
    namespace="alert",
    configured=Platform.BINARY_SENSOR,
    refers=_refers,
)
