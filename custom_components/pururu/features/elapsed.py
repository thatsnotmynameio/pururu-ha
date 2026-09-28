"""An alert on the time since a milestone: a cycle's start or end, or its own creation.

Measured from a datetime HA keeps across restarts, so a restart in between
starts nothing over.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Self, override

from homeassistant.const import ATTR_RESTORED, Platform
from homeassistant.core import Event, EventStateChangedData, State, callback
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.restore_state import ExtraStoredData
from homeassistant.util import dt as dt_util

from ..feature import NO_READING, Device, Elapsed
from .alerts import ProblemAlert


@dataclass
class Created(ExtraStoredData):
    """When the alert was first created: its milestone until there is one."""

    at: datetime | None = None

    @override
    def as_dict(self) -> dict[str, Any]:
        """What .storage keeps."""
        return {"at": self.at.isoformat() if self.at else None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Read back what as_dict saved."""
        at = data.get("at")
        return cls(at=dt_util.parse_datetime(at) if isinstance(at, str) else None)


def _datetime(value: Any) -> datetime | None:
    """A milestone read from a state or an attribute."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return dt_util.parse_datetime(value)
    return None


class ElapsedAlert(ProblemAlert):
    """On while the watched entity is in its state and the time since the milestone is in [for, for + lasts)."""

    def __init__(
        self,
        device: Device,
        entity_key: str,
        *,
        watched: str,
        milestone: str | None,
        elapsed: Elapsed,
        hold: timedelta,
        lasts: timedelta | None,
        priority: str,
        notify: Mapping[str, str] | None,
        sources: tuple[str, ...],
    ) -> None:
        """`milestone`: the entity whose state is the milestone; None: the watched one's attribute."""
        super().__init__(watched=watched, priority=priority, notify=notify)
        self._identify(device, Platform.BINARY_SENSOR, entity_key)
        self.sources = sources
        self._milestone = milestone
        self._elapsed = elapsed
        self._hold = hold
        self._lasts = lasts
        self._created = Created()
        # When this entity saw the watched one enter its state: newer than a
        # milestone not written yet (running goes off before last_cycle_end is)
        self._entered: datetime | None = None

    @property
    @override
    def extra_restore_state_data(self) -> Created:
        """When it was first created."""
        return self._created

    @override
    async def async_added_to_hass(self) -> None:
        """Restore when it was created, or be created now; then as any alert."""
        if (extra := await self.async_get_last_extra_data()) is not None:
            self._created = Created.from_dict(extra.as_dict())
        if self._created.at is None:
            self._created = Created(at=dt_util.utcnow())
        await super().async_added_to_hass()

    @override
    @callback
    def _follow(self) -> None:
        followed = [self._watched, *([self._milestone] if self._milestone else [])]
        self.async_on_remove(
            async_track_state_change_event(self.hass, followed, self._changed)
        )
        self._evaluate()

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        """Note when the watched entity really enters its state; evaluate."""
        data = event.data
        old, new = data["old_state"], data["new_state"]
        if (
            data["entity_id"] == self._watched
            and new is not None
            and new.state == self._elapsed.state
            and old is not None
            and old.state not in (*NO_READING, self._elapsed.state)
            and not old.attributes.get(ATTR_RESTORED)
        ):
            self._entered = new.last_changed
        self._evaluate()

    def _since(self, watched: State) -> datetime | None:
        """The milestone: the newest of what the entities say and what this one saw."""
        if self._milestone is None:
            said = _datetime(
                watched.attributes.get(self._elapsed.since_attribute or "")
            )
        else:
            state = self.hass.states.get(self._milestone)
            said = _datetime(state.state) if state is not None else None
        if said is None and self._elapsed.or_since_created:
            said = self._created.at
        known = [each for each in (said, self._entered) if each is not None]
        return max(known) if known else None

    @callback
    def _evaluate(self, _now: datetime | None = None) -> None:
        """Set the state for now and schedule the next change; without a reading, keep it."""
        self._cancel()
        watched = self.hass.states.get(self._watched)
        if (
            watched is None
            or watched.state in NO_READING
            or watched.attributes.get(ATTR_RESTORED)
        ):
            return
        if watched.state != self._elapsed.state:
            self._entered = None
            self._set(on=False)
            return
        if (since := self._since(watched)) is None:
            return
        now = dt_util.utcnow()
        start = since + self._hold
        end = start + self._lasts if self._lasts is not None else None
        self._set(on=start <= now and (end is None or now < end))
        if now < start:
            upcoming: datetime | None = start
        elif end is not None and now < end:
            upcoming = end
        else:
            upcoming = None
        if upcoming is not None:
            self._pending = async_track_point_in_utc_time(
                self.hass, self._evaluate, upcoming
            )
