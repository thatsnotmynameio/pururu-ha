"""What features recording cycles share: a finished cycle, where it's sent, its start kept across restarts.

`appliance` has one kind of cycle; `modes` one per mode, an Item of its block.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self, override

from homeassistant.helpers.restore_state import ExtraStoredData
from homeassistant.util import dt as dt_util
from homeassistant.util.signal_type import SignalType

from ...feature import Device, Item, item_key


@dataclass(frozen=True, kw_only=True)
class Cycle:
    """A finished cycle, as its source sends it."""

    start: datetime | None
    end: datetime
    energy_kwh: float | None

    @property
    def duration_min(self) -> float | None:
        """Minutes from start to end, when the start is known."""
        if self.start is None:
            return None
        return round((self.end - self.start).total_seconds() / 60, 1)


def cycle_signal(device: Device, item: Item | None = None) -> SignalType[Cycle]:
    """Each finished cycle (of `item`) is sent here first."""
    return SignalType(device.object_id(item_key("cycle", item)))


def end_signal(device: Device, item: Item | None = None) -> SignalType[Cycle]:
    """Then here, for last_cycle_end: what it triggers reads the rest already updated."""
    return SignalType(device.object_id(item_key("cycle_end", item)))


@dataclass
class CycleStart(ExtraStoredData):
    """The running cycle's start, kept across restarts and reloads, and its end while off_delay runs."""

    since: datetime | None = None
    since_energy: float | None = None
    until: datetime | None = None

    @override
    def as_dict(self) -> dict[str, Any]:
        """What .storage keeps."""
        return {
            "since": self.since.isoformat() if self.since else None,
            "since_energy": self.since_energy,
            "until": self.until.isoformat() if self.until else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Read back what as_dict saved; anything else means no running cycle."""
        since = data.get("since")
        energy = data.get("since_energy")
        until = data.get("until")
        return cls(
            since=dt_util.parse_datetime(since) if isinstance(since, str) else None,
            since_energy=float(energy) if isinstance(energy, int | float) else None,
            until=dt_util.parse_datetime(until) if isinstance(until, str) else None,
        )
