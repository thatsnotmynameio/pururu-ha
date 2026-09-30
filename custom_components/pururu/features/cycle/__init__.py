"""What features recording cycles share: a finished cycle, where it's sent, its start kept across restarts.

The detector (`program/`) has one for its program (the appliance's `running`)
and one per phase; a door's or a window's `open` one; an executable program's
`Runs` one per program, an Item of its block.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self, override

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.restore_state import ExtraStoredData
from homeassistant.util.signal_type import SignalType

from ...core.entity import PururuEntity, as_time
from ...core.feature import Device, Item, item_key


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


class CycleSource(PururuEntity):
    """An entity whose finished cycles are sent on its cycle and end signals, state written first.

    `Open`, `Runs`, and the detector's `Carrier` and `PhaseRunning` set the
    signals up once, in `__init__`.
    """

    def _cycle_signals(self, device: Device, item: Item | None = None) -> None:
        """The signals this entity (or this item of it) sends a finished cycle on."""
        self._signals = (cycle_signal(device, item), end_signal(device, item))

    def _send(self, cycle: Cycle) -> None:
        """Write the state, then send the cycle: its own signal first, the end's last."""
        self.async_write_ha_state()
        for signal in self._signals:  # the end's own signal last
            async_dispatcher_send(self.hass, signal, cycle)


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
        """Read back what as_dict saved; anything else, an impossible date too (a hand-edited .storage), means no running cycle."""
        energy = data.get("since_energy")
        return cls(
            since=as_time(data.get("since")),
            since_energy=float(energy) if isinstance(energy, int | float) else None,
            until=as_time(data.get("until")),
        )
