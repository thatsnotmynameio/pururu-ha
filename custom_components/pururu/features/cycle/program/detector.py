"""The detector: a program's cycles and its phases', from readings and time; nothing of HA."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self

from .. import Cycle, CycleStart
from ..energy import kwh_used
from .schema import IDLE, OTHER, Band, Phase, Program


def _aware(when: datetime | None) -> datetime | None:
    """A time with its zone; one without (a hand-edited .storage) is none."""
    return when if when is not None and when.tzinfo is not None else None


@dataclass
class Run:
    """A running cycle: its start, when its reading left (while its off_delay runs), and whether for no band."""

    since: datetime | None
    since_energy: float | None = None
    until: datetime | None = None
    gap: bool = False

    def as_dict(self) -> dict[str, Any]:
        """What .storage keeps."""
        start = CycleStart(
            since=self.since, since_energy=self.since_energy, until=self.until
        )
        return {**start.as_dict(), "gap": self.gap}

    @classmethod
    def from_dict(cls, data: Any) -> Self | None:
        """Read back what as_dict saved; anything but a map is no run, and a time without a zone none."""
        if not isinstance(data, dict):
            return None
        start = CycleStart.from_dict(data)
        return cls(
            since=_aware(start.since),
            since_energy=start.since_energy,
            until=_aware(start.until),
            gap=data.get("gap") is True,
        )


@dataclass
class _Track:
    """What the detector knows of the program or of one phase."""

    # Whether the last reading held its band
    inside: bool = False
    # When its on_delay passes, while it counts
    starting: datetime | None = None
    # When its on_delay passed, while it waits to start
    armed: datetime | None = None
    run: Run | None = None
    # When its off_delay passes, while it counts
    ending: datetime | None = None


@dataclass(frozen=True)
class Started:
    """A cycle started: the program's (key None) or a phase's, and from when."""

    key: str | None
    since: datetime | None


@dataclass(frozen=True)
class Ended:
    """A cycle ended: the program's (key None) or a phase's."""

    key: str | None
    cycle: Cycle


type Change = Started | Ended


class Detector:
    """A program's cycles and its phases', from readings and time.

    - The program runs while the reading holds its band, confirmed by its
      delays, as the appliance's `running` today.
    - A phase runs inside the program's cycle while the reading holds its band,
      confirmed by its delays. Phases whose bands hold at once run at once: no
      band wins, and the current phase is the one that started last.
    - A dip: the reading goes from a running phase's band straight into
      another's. The other phase, its on_delay passed, waits for the first to
      end (its off_delay), or for a reading back in both bands, then starts
      from when its on_delay passed.
    - While the program's reading is out (its off_delay counting), no phase
      starts: one whose on_delay passes waits for the reading back, or for the
      next program cycle.
    - An idle gap: a reading outside every phase's band once a phase left its
      own. That phase blocks nothing, and still ends at the moment it left.
    - `other` runs while the reading holds the program's band and no phase's;
      it waits for nothing, and ends at once when a phase starts.
    - A cycle ends when its reading left, or when the program's did if earlier:
      off_delay only confirms it. Each delay passes at its own time, however
      late `advance` comes; a reading at the very instant a delay passes comes
      before it, so a band held for exactly its on_delay isn't held, and no
      cycle is empty for it.
    - At one instant: the program's delay first, then the phases' ends, in the
      order they started (the current phase last), then their starts, in the
      configuration's order.
    """

    def __init__(self, program: Program) -> None:
        """Nothing running, nothing counting."""
        self.program = program
        self._program = _Track()
        self._phases = {phase.key: _Track() for phase in program.phases}
        # The running phases, in the order they started
        self._order: list[str] = []
        # The phases that ran in the program's current or last cycle
        self._seen: set[str] = set()

    # --- what it shows ---

    @property
    def on(self) -> bool:
        """Whether the program runs."""
        return self._program.run is not None

    def run(self, key: str | None) -> Run | None:
        """The program's (None) or a phase's running cycle."""
        return self._track(key).run

    @property
    def current(self) -> str:
        """The phase that started last among those running, or idle."""
        return self._order[-1] if self._order else IDLE

    @property
    def running(self) -> list[str]:
        """The running phases, in the configuration's order (other last)."""
        return [key for key in self._phases if key in self._order]

    @property
    def seen(self) -> list[str]:
        """The phases that ran in the program's current or last cycle, in the configuration's order."""
        return [key for key in self._phases if key in self._seen]

    def end_so_far(self, run: Run) -> datetime | None:
        """A phase's cycle's end should it end now: when it left, or the program's if earlier; never before it started."""
        program = self._program.run
        ends = [
            end
            for end in (run.until, None if program is None else program.until)
            if end is not None
        ]
        if not ends:
            return None
        return min(ends) if run.since is None else max(min(ends), run.since)

    def due(self) -> datetime | None:
        """When the next delay passes; None while none counts."""
        return min((when for when, *_ in self._deadlines()), default=None)

    # --- what moves it ---

    def read(
        self, value: float | None, now: datetime, kwh: float | None
    ) -> list[Change]:
        """A reading at `now` (None: it has no value), `kwh` the energy counter then; what it started and ended.

        The delays passed before `now` pass first; those passing at `now`, once
        the reading counted. A reading without a value stops every delay
        counting: each counts again from the next reading, and every run, and
        when it left, stays.
        """
        changes = self.catch_up(now, kwh)
        if value is None:
            for track in (self._program, *self._phases.values()):
                track.starting = track.ending = None
            return changes
        band = self.program.band
        self._follow(self._program, band.holds(value), now, band)
        holds = {
            phase.key: phase.band.holds(value)
            for phase in self.program.phases
            if not phase.other
        }
        gap = not any(holds.values())
        if OTHER in self._phases:
            holds[OTHER] = gap and band.holds(value)
        for phase in self.program.phases:
            track = self._phases[phase.key]
            if gap and track.run is not None:
                track.run.gap = True
            self._follow(track, holds[phase.key], now, phase.band)
        # The delays passing now, a delay of 0 too; then a phase that waited
        # (a dip, the program's reading out) starts if this reading ended its wait
        return [*changes, *self.advance(now, kwh), *self._start_armed(kwh)]

    def catch_up(self, now: datetime, kwh: float | None) -> list[Change]:
        """Every delay passed before `now`, each at its own time: what `read` passes first.

        Called before `read` at the same `now`, it splits one reading's step
        in two, and `read` then passes none of them again: a late timer's end
        comes before what the reading starts, a program ended and started
        again by one reading (on_delay 0) too.
        """
        return self._pass(now, kwh, at_now=False)

    def advance(self, now: datetime, kwh: float | None) -> list[Change]:
        """Every delay passed by `now`, each at its own time; what they started and ended."""
        return self._pass(now, kwh, at_now=True)

    def _pass(self, now: datetime, kwh: float | None, *, at_now: bool) -> list[Change]:
        """Every delay passed before `now`, and those passing at `now` if `at_now`."""
        changes: list[Change] = []
        while (deadline := min(self._deadlines(), default=None)) is not None:
            when, _, _, position, ending = deadline
            if when > now or (when == now and not at_now):
                break
            key = None if position < 0 else self.program.phases[position].key
            changes.extend(self._passed(key, ending, when, kwh))
        return changes

    def _deadlines(self) -> Iterator[tuple[datetime, int, int, int, bool]]:
        """(when, rank, order, position, ending) of each delay counting.

        At one instant: the program's first, then the phases' ends in the
        order they started, then their starts in the configuration's order
        (position -1: the program).
        """
        yield from self._program_deadlines()
        for position, (key, track) in enumerate(self._phases.items()):
            if track.ending is not None:
                yield (track.ending, 1, self._order.index(key), position, True)
            if track.starting is not None:
                yield (track.starting, 2, position, position, False)

    def _program_deadlines(self) -> Iterator[tuple[datetime, int, int, int, bool]]:
        track = self._program
        if track.ending is not None:
            yield (track.ending, 0, 0, -1, True)
        if track.starting is not None:
            yield (track.starting, 0, 0, -1, False)

    def _track(self, key: str | None) -> _Track:
        return self._program if key is None else self._phases[key]

    @staticmethod
    def _follow(track: _Track, holds: bool, now: datetime, band: Band) -> None:
        """Count the delay a reading asks for; cancel the one it no longer asks for.

        Back in its band cancels a run's end; out of it, off_delay counts from
        the first reading out, and when it left stays. Out of its band stops a
        start; in it, on_delay counts from the first reading in.
        """
        track.inside = holds
        if (run := track.run) is not None:
            if holds:
                track.ending = None
                run.until = None
                run.gap = False
            elif track.ending is None:
                if run.until is None:
                    run.until = now
                track.ending = now + band.off_delay
        elif not holds:
            track.starting = track.armed = None
        elif track.armed is None and track.starting is None:
            track.starting = now + band.on_delay

    def _passed(
        self, key: str | None, ending: bool, when: datetime, kwh: float | None
    ) -> list[Change]:
        """A delay passed at `when`: a cycle starts or ends, and what waited for it may start."""
        track = self._track(key)
        if ending:
            track.ending = None
            if key is None:
                return self._program_ends(when, kwh)
            assert track.run is not None
            ended = self._end(key, self.end_so_far(track.run) or when, kwh)
            return [ended, *self._start_armed(kwh)]
        track.starting = None
        if key is None:
            track.run = Run(since=when, since_energy=kwh)
            self._seen.clear()
            return [Started(None, when), *self._start_armed(kwh)]
        track.armed = when
        return self._start_armed(kwh)

    def _program_ends(self, when: datetime, kwh: float | None) -> list[Change]:
        """The program's cycle ends when its reading left; each running phase's with it, if not before, in the order they started.

        A phase whose band still holds is armed: it starts with the next cycle.
        """
        run = self._program.run
        assert run is not None
        end = run.until or when
        if run.since is not None:
            end = max(end, run.since)
        ended: list[Change] = []
        for key in self._order.copy():
            track = self._phases[key]
            assert track.run is not None
            ended.append(self._end(key, self.end_so_far(track.run) or end, kwh))
            if track.inside:
                track.armed = when
        self._program.run = None
        cycle = Cycle(
            start=run.since, end=end, energy_kwh=kwh_used(run.since_energy, kwh)
        )
        return [Ended(None, cycle), *ended]

    def _end(self, key: str, end: datetime, kwh: float | None) -> Ended:
        """Phase `key`'s cycle ends at `end`; its energy is the counter's growth until now."""
        track = self._phases[key]
        run = track.run
        assert run is not None
        track.run = None
        track.ending = None
        self._order.remove(key)
        return Ended(
            key,
            Cycle(start=run.since, end=end, energy_kwh=kwh_used(run.since_energy, kwh)),
        )

    def _waits(self) -> bool:
        """Whether a configured phase waits: another ends after a dip."""
        return any(
            track.run is not None and track.run.until is not None and not track.run.gap
            for key, track in self._phases.items()
            if key != OTHER
        )

    def _start_armed(self, kwh: float | None) -> list[Change]:
        """Start every armed phase that may: the program runs with its reading in, and a configured one waits for no dip.

        While the program's reading is out, every armed phase stays armed: it
        starts if the reading comes back, or with the next program cycle.
        A phase starts from when its on_delay passed, or the program's start if
        later.
        """
        program = self._program.run
        if program is None or program.until is not None:
            return []
        changes: list[Change] = []
        for phase in self.program.phases:
            track = self._phases[phase.key]
            if track.armed is None or track.run is not None:
                continue
            if not phase.other and self._waits():
                continue
            since = track.armed
            if program.since is not None:
                since = max(since, program.since)
            changes.extend(self._start(phase, since, kwh))
        return changes

    def _start(self, phase: Phase, since: datetime, kwh: float | None) -> list[Change]:
        """Phase `phase` starts from `since`; a configured phase starting ends other at once."""
        track = self._phases[phase.key]
        track.armed = None
        track.run = Run(since=since, since_energy=kwh)
        self._order.append(phase.key)
        self._seen.add(phase.key)
        changes: list[Change] = [Started(phase.key, since)]
        other = self._phases.get(OTHER)
        if not phase.other and other is not None and other.run is not None:
            changes.append(self._end(OTHER, self.end_so_far(other.run) or since, kwh))
        return changes

    # --- across restarts ---

    def snapshot(self) -> dict[str, Any]:
        """The running cycles and the phases seen, for .storage; delays aren't kept."""
        program = self._program.run
        return {
            "program": None if program is None else program.as_dict(),
            "phases": {
                key: run.as_dict()
                for key in self._order
                if (run := self._phases[key].run) is not None
            },
            "order": list(self._order),
            "seen": self.seen,
        }

    def restore(self, data: Mapping[str, Any]) -> None:
        """Take back a snapshot: the phases seen, and the running cycles of phases still configured.

        The program runs only with a start. Delays count from the next reading.
        """
        if isinstance(seen := data.get("seen"), list):
            self._seen = {
                key for key in seen if isinstance(key, str) and key in self._phases
            }
        program = Run.from_dict(data.get("program"))
        if program is None or program.since is None:
            return
        self._program.run = program
        phases, order = data.get("phases"), data.get("order")
        if isinstance(phases, dict) and isinstance(order, list):
            for key in order:
                if (
                    not isinstance(key, str)
                    or key not in self._phases
                    or key in self._order
                ):
                    continue
                if (run := Run.from_dict(phases.get(key))) is not None:
                    self._phases[key].run = run
                    self._order.append(key)
