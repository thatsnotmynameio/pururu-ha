"""features/cycle/program: a detected program and its phases, the detector alone (no HA entity).

Times are seconds from T0. Each scenario of 0.1's `modes` and `phases` tests
(removed in D2) is replayed here with the same readings, the washer's 10 s
later (see washer()): the same cycles, starts and ends.
"""

import csv
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
import pytest
import voluptuous as vol

from helpers import module

T0 = datetime(2026, 9, 16, 13, 0, tzinfo=UTC)
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def seconds(when: datetime | None) -> float | None:
    return None if when is None else (when - T0).total_seconds()


class Drive:
    """Readings at seconds from T0 into a detector; what it starts and ends, in seconds."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.program = module("features.cycle.program")
        self.detector = self.program.Detector(self.program.program_of(self.program.SCHEMA(config)))
        self.kwh: float | None = None
        self.started: list[tuple[str | None, float | None]] = []
        self.ended: list[tuple[str | None, float | None, float]] = []
        self.energy: dict[str | None, float | None] = {}

    def _note(self, changes: list[Any]) -> None:
        for change in changes:
            if isinstance(change, self.program.Started):
                self.started.append((change.key, seconds(change.since)))
            else:
                cycle = change.cycle
                self.ended.append((change.key, seconds(cycle.start), seconds(cycle.end)))
                self.energy[change.key] = cycle.energy_kwh

    def read(self, second: float, value: float | None) -> None:
        self._note(self.detector.read(value, at(second), self.kwh))

    def to(self, second: float) -> None:
        self._note(self.detector.advance(at(second), self.kwh))

    def cycles(self, key: str | None) -> list[tuple[float | None, float]]:
        return [(start, end) for each, start, end in self.ended if each == key]

    @property
    def current(self) -> str:
        return self.detector.current


# --- the schema ------------------------------------------------------------------

RESFRIAR = {"name": "Resfriar", "above": 40, "below": 300, "on_delay": {"seconds": 30}, "off_delay": {"seconds": 30}}
PROGRAM: dict[str, Any] = {"above": 4, "on_delay": {"seconds": 20}, "off_delay": {"minutes": 2},
                           "phases": {"resfriar": RESFRIAR}}


@pytest.mark.parametrize("block", [
    pytest.param({**PROGRAM, "above": 5, "below": 5}, id="above equals below"),
    pytest.param({k: v for k, v in PROGRAM.items() if k != "above"}, id="no bound"),
    pytest.param({**PROGRAM, "above": "nan"}, id="bound not a number"),
    pytest.param({**PROGRAM, "phases": {}}, id="no phase"),
    pytest.param({**PROGRAM, "phases": {"Resfriar": RESFRIAR}}, id="not a slug"),
    pytest.param({**PROGRAM, "phases": {"resfriar": {k: v for k, v in RESFRIAR.items() if k != "name"}}},
                 id="a phase without name"),
    pytest.param({**PROGRAM, "phases": {"resfriar": {**RESFRIAR, "name": "  "}}}, id="blank name"),
    pytest.param({**PROGRAM, "phases": {"resfriar": {"name": "Resfriar"}}}, id="a phase without bound"),
    pytest.param({**PROGRAM, "phases": {"resfriar": {**RESFRIAR, "above": 300, "below": 40}}},
                 id="a phase's above over its below"),
    pytest.param({**PROGRAM, "phases": {"resfriar": {**RESFRIAR, "phases": {"x": RESFRIAR}}}},
                 id="phases inside a phase"),
    pytest.param({**PROGRAM, "phases": {"resfriar": {**RESFRIAR, "for": 3}}}, id="a phase's for"),
    pytest.param({**PROGRAM, "statistics": {"cycles": ["today"]}}, id="statistics: D2 mounts it"),
    pytest.param({**PROGRAM, "phases": {"idle": RESFRIAR}}, id="a phase keyed idle"),
    pytest.param({**PROGRAM, "phases": {"other": RESFRIAR}}, id="a phase keyed other"),
    pytest.param({**PROGRAM, "phases": {"current": RESFRIAR}}, id="phase_current is the detector's"),
    pytest.param({**PROGRAM, "phases": {"last": RESFRIAR}}, id="phase_last is the detector's"),
    pytest.param({**PROGRAM, "phases": {"resfriar": RESFRIAR, "resfriar_cycles_total": RESFRIAR}},
                 id="two phases creating one entity key"),
    pytest.param({**PROGRAM, "phases": {"other_cycles_total": RESFRIAR}},
                 id="a phase creating one of other's"),
    pytest.param({k: v for k, v in PROGRAM.items() if k != "phases"} | {"other": {}},
                 id="other without phases"),
    pytest.param({**PROGRAM, "other": {"name": "Outro"}}, id="other takes only delays"),
    pytest.param({**PROGRAM, "running": True}, id="unknown key"),
])
def test_invalid_program_is_refused(ha: HomeAssistant, block: dict[str, Any]) -> None:
    schema = module("features.cycle.program").SCHEMA
    with pytest.raises(vol.Invalid):
        schema(block)


def test_a_phase_creating_one_of_others_is_the_one_named(ha: HomeAssistant) -> None:
    """The user's key is the culprit, not the built-in other."""
    schema = module("features.cycle.program").SCHEMA
    block = {**PROGRAM, "phases": {"other_cycles_total": RESFRIAR}}
    with pytest.raises(vol.Invalid, match="phase other_cycles_total would create "
                                          "phase_other_cycles_total, phase other's"):
        schema(block)


def test_a_program_takes_what_the_spec_says(ha: HomeAssistant) -> None:
    """Delays default to 0 (at once); other's to 30 s; overlapping and touching bands pass; name is optional on the program."""
    program = module("features.cycle.program")
    config = program.SCHEMA({
        "above": 4,
        "phases": {"warming": {"name": "Aquecendo", "above": 1000},
                   "wringing": {"name": "Centrifugando", "above": 50, "below": 1000},
                   "any": {"name": "Qualquer", "above": 50}},
    })
    detected = program.program_of(config)
    assert detected.band == program.Band(above=4, on_delay=timedelta(0), off_delay=timedelta(0))
    assert [phase.key for phase in detected.phases] == ["warming", "wringing", "any", "other"]
    assert detected.phases[0].band.on_delay == timedelta(0)
    other = detected.phases[-1]
    assert other.band.on_delay == timedelta(seconds=30)
    assert other.band.off_delay == timedelta(seconds=30)
    assert other.item.slug == "phase_other"
    tuned = program.program_of(program.SCHEMA({**config, "name": "Algodão",
                                               "other": {"on_delay": {"seconds": 5}}}))
    assert tuned.phases[-1].band.on_delay == timedelta(seconds=5)
    assert tuned.phases[-1].band.off_delay == timedelta(seconds=30)
    assert program.program_of(program.SCHEMA({"above": 4})).phases == ()


def test_the_keys_a_phase_creates(ha: HomeAssistant) -> None:
    """In the builder's namespace: phase_<key>, phase_<key>_<suffix>; the detector's own two."""
    program = module("features.cycle.program")
    assert set(program.phase_keys("resfriar")) == {
        "phase_resfriar", "phase_resfriar_last_cycle_start", "phase_resfriar_last_cycle_end",
        "phase_resfriar_last_cycle_duration", "phase_resfriar_last_cycle_energy",
        "phase_resfriar_cycles_total", "phase_resfriar_runtime_total", "phase_resfriar_energy_total"}
    assert set(program.FIXED) == {"phase_current", "phase_last"}
    assert set(program.PHASE_COUNTERS) == {"runtime", "cycles", "energy"}


# --- the program alone: 0.1's appliance `running` --------------------------------

ALONE = {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}}


def test_the_program_starts_after_its_on_delay_and_ends_when_the_reading_went_down(
        ha: HomeAssistant) -> None:
    drive = Drive(ALONE)
    drive.kwh = 10.0
    drive.read(0, 120)
    drive.to(59)
    assert not drive.detector.on
    drive.to(60)
    assert drive.started == [(None, 60)]
    drive.read(600, 7)
    drive.kwh = 10.5
    drive.read(700, 1.4)
    drive.to(819)
    assert drive.detector.on
    assert drive.detector.run(None).until == at(700)
    drive.to(820)
    assert drive.cycles(None) == [(60, 700)]
    assert drive.energy[None] == pytest.approx(0.5)
    assert drive.detector.due() is None


def test_the_reading_back_up_cancels_the_programs_end(ha: HomeAssistant) -> None:
    drive = Drive(ALONE)
    drive.read(0, 120)
    drive.read(100, 1.4)
    drive.read(200, 120)
    drive.to(1000)
    assert drive.detector.on
    assert drive.detector.run(None).until is None
    assert drive.ended == []


def test_no_value_counts_the_delays_again_and_keeps_the_end(ha: HomeAssistant) -> None:
    """As `running` today: off_delay counts from the next reading; the end stays when the power went down."""
    drive = Drive(ALONE)
    drive.read(0, 120)
    drive.to(60)
    drive.read(100, 1.4)
    drive.read(150, None)
    drive.to(400)
    assert drive.detector.on
    drive.read(400, 1.4)
    drive.to(519)
    assert drive.detector.on
    drive.to(520)
    assert drive.cycles(None) == [(60, 100)]


def test_the_programs_cycle_never_ends_before_it_started(ha: HomeAssistant) -> None:
    """A clock going back: the reading leaves before the program's start; its cycle is empty, not negative."""
    drive = Drive(ALONE)
    drive.read(0, 120)
    drive.to(60)
    drive.read(30, 1.4)
    drive.to(150)
    assert drive.cycles(None) == [(60, 60)]


# --- 0.1's `modes`, as phases -----------------------------------------------------

MODES: dict[str, Any] = {
    "above": 4, "on_delay": {"seconds": 20}, "off_delay": {"minutes": 2},
    "phases": {
        "bebendo": {"name": "Bebendo", "above": 4, "below": 40,
                    "on_delay": {"seconds": 5}, "off_delay": {"minutes": 5}},
        "resfriar": RESFRIAR,
        "quente": {"name": "Água quente", "above": 300,
                   "on_delay": {"seconds": 10}, "off_delay": {"seconds": 30}},
    },
}


def purifier() -> Drive:
    """The purifier of 0.1's modes tests: idle at 1 W, then 120 W from 125 s: the program at 145, resfriar at 155."""
    drive = Drive(MODES)
    drive.read(0, 1)
    drive.read(125, 120)
    drive.to(155)
    assert drive.current == "resfriar"
    return drive


def test_a_phase_starts_after_its_on_delay(ha: HomeAssistant) -> None:
    drive = Drive(MODES)
    drive.read(0, 1)
    drive.read(125, 120)
    drive.to(150)
    assert drive.detector.on
    assert drive.current == "idle"
    drive.to(155)
    assert drive.started == [(None, 145), ("resfriar", 155)]
    assert drive.current == "resfriar"
    # Its reading hasn't left: it has no end yet
    assert drive.detector.end_so_far(drive.detector.run("resfriar")) is None


def test_a_phase_ends_after_its_off_delay_at_when_it_left(ha: HomeAssistant) -> None:
    drive = purifier()
    drive.read(160, 1)
    drive.to(189)
    assert drive.current == "resfriar"
    drive.to(190)
    assert drive.current == "idle"
    assert drive.cycles("resfriar") == [(155, 160)]


def test_back_in_its_band_cancels_the_end(ha: HomeAssistant) -> None:
    drive = purifier()
    drive.read(160, 1)
    drive.read(180, 120)
    drive.to(240)
    assert drive.current == "resfriar"
    assert drive.cycles("resfriar") == []


def test_after_a_dip_another_phase_waits_for_the_running_one(ha: HomeAssistant) -> None:
    """From 120 W to 1000 W: quente's on_delay passes at 170, it starts when resfriar ends at 190, from 170."""
    drive = purifier()
    drive.read(160, 1000)
    drive.to(172)
    assert drive.current == "resfriar"
    assert drive.detector.running == ["resfriar"]
    drive.to(190)
    assert drive.current == "quente"
    assert drive.cycles("resfriar") == [(155, 160)]
    assert drive.started[-1] == ("quente", 170)


def test_a_dip_into_another_band_does_not_split_the_cycle(ha: HomeAssistant) -> None:
    drive = purifier()
    drive.read(160, 20)
    drive.read(170, 120)
    drive.to(800)
    assert drive.current == "resfriar"
    assert drive.ended == []


def test_a_short_visit_to_another_band_is_nothing(ha: HomeAssistant) -> None:
    drive = purifier()
    drive.read(160, 1000)
    drive.read(165, 120)
    drive.to(800)
    assert drive.current == "resfriar"
    assert drive.ended == []


def test_a_phase_armed_before_the_program_starts_with_it(ha: HomeAssistant) -> None:
    drive = Drive(MODES)
    drive.read(0, 1)
    drive.read(125, 1000)
    drive.to(140)
    assert drive.current == "idle"
    drive.to(145)
    assert drive.started == [(None, 145), ("quente", 145)]


def test_the_program_ending_ends_the_phase_at_its_end(ha: HomeAssistant) -> None:
    """bebendo's off_delay (5 min) outlasts the program's (2 min): the program ends it, when the reading left."""
    drive = Drive(MODES)
    drive.read(0, 1)
    drive.read(125, 20)
    drive.to(150)
    assert drive.current == "bebendo"
    drive.read(150, 1)
    drive.to(270)
    assert not drive.detector.on
    assert drive.current == "idle"
    assert drive.cycles(None) == [(145, 150)]
    assert drive.cycles("bebendo") == [(145, 150)]
    assert [key for key, *_ in drive.ended] == [None, "bebendo"]


def test_no_value_keeps_the_phase_and_counts_its_delays_again(ha: HomeAssistant) -> None:
    drive = purifier()
    drive.read(160, 1000)
    drive.read(165, None)
    drive.to(765)
    assert drive.current == "resfriar"
    drive.read(765, 1000)
    drive.to(790)
    assert drive.current == "resfriar"  # its off_delay counts from 765
    drive.to(795)
    assert drive.current == "quente"
    assert drive.cycles("resfriar") == [(155, 160)]
    assert drive.started[-1] == ("quente", 775)


def test_a_handover_never_shows_idle(ha: HomeAssistant) -> None:
    """resfriar ends and quente starts in one step: nothing in between."""
    drive = purifier()
    drive.read(160, 1000)
    drive.to(189)
    changes = drive.detector.advance(at(190), None)
    assert [type(change).__name__ for change in changes] == ["Ended", "Started"]
    assert drive.current == "quente"


def test_a_phases_energy_is_the_counter_from_its_start_to_its_end(ha: HomeAssistant) -> None:
    drive = Drive(MODES)
    drive.kwh = 100.0
    drive.read(0, 1)
    drive.read(125, 120)
    drive.to(155)
    drive.kwh = 100.05
    drive.read(755, 1)
    drive.to(790)
    assert drive.cycles("resfriar") == [(155, 755)]
    assert drive.energy["resfriar"] == pytest.approx(0.05)


def test_after_the_program_a_band_still_holding_starts_with_the_next(ha: HomeAssistant) -> None:
    """A phase band reaching below the program's: armed at the program's end, it starts with the next one."""
    drive = Drive({"above": 10, "on_delay": {"seconds": 20}, "off_delay": {"seconds": 30},
                   "phases": {"baixo": {"name": "Baixo", "above": 5, "below": 20,
                                        "on_delay": {"seconds": 5}}}})
    drive.read(0, 15)
    drive.to(20)
    assert drive.started == [(None, 20), ("baixo", 20)]
    drive.read(100, 8)
    drive.to(130)
    assert drive.cycles("baixo") == [(20, 100)]
    drive.read(200, 15)
    drive.to(220)
    assert drive.started[-1] == ("baixo", 220)


def baixo(on_delay: dict[str, int]) -> Drive:
    """A phase band reaching below the program's: heavy runs at 50 W; at 100 s, 8 W leaves the program's band (off_delay 30 s) for baixo's."""
    drive = Drive({"above": 10, "off_delay": {"seconds": 30},
                   "phases": {"heavy": {"name": "Pesado", "above": 20},
                              "baixo": {"name": "Baixo", "above": 5, "below": 20,
                                        "on_delay": on_delay}}})
    drive.read(0, 50)
    drive.read(100, 8)
    return drive


@pytest.mark.parametrize("on_delay", [{"seconds": 5}, {"seconds": 0}], ids=["5 s", "0"])
def test_no_phase_starts_while_the_programs_reading_is_out(
        ha: HomeAssistant, on_delay: dict[str, int]) -> None:
    """baixo's band holds during the program's off_delay: it waits, and starts with the next cycle; no empty cycle."""
    drive = baixo(on_delay)
    drive.to(130)
    assert drive.cycles(None) == [(0, 100)]
    assert drive.cycles("heavy") == [(0, 100)]
    assert drive.cycles("baixo") == []
    assert "baixo" not in drive.detector.seen
    drive.read(200, 15)
    assert drive.started[-1] == ("baixo", 200)


def test_the_programs_reading_back_starts_the_phase_that_waited(ha: HomeAssistant) -> None:
    """15 W at 110 s: the program's cycle goes on, and baixo starts from when its on_delay passed."""
    drive = baixo({"seconds": 5})
    drive.to(106)
    drive.read(110, 15)
    assert drive.current == "baixo"
    assert drive.started[-1] == ("baixo", 105)
    drive.to(1000)
    assert drive.cycles(None) == []


# --- overlapping bands ------------------------------------------------------------

OVERLAP: dict[str, Any] = {
    "above": 4,
    "phases": {"a": {"name": "A", "above": 10, "below": 100, "off_delay": {"seconds": 60}},
               "b": {"name": "B", "above": 50, "below": 200}},
}


def test_a_phase_armed_in_a_dip_starts_when_the_reading_holds_both(ha: HomeAssistant) -> None:
    """a runs at 30 W; 150 W is a dip into b's band alone, so b waits for a; 60 W holds both: b starts at once, from the dip."""
    drive = Drive(OVERLAP)
    drive.read(0, 30)
    assert drive.current == "a"
    drive.read(100, 150)
    assert drive.detector.running == ["a"]
    drive.read(110, 60)
    assert drive.detector.running == ["a", "b"]
    assert drive.current == "b"
    assert drive.started[-1] == ("b", 100)
    drive.read(120, 30)
    assert drive.cycles("b") == [(100, 120)]
    assert drive.cycles("a") == []


@pytest.mark.parametrize(("order", "current"), [(["x", "y"], "y"), (["y", "x"], "x")],
                         ids=["x then y", "y then x"])
def test_phases_starting_at_one_instant_start_in_the_configurations_order(
        ha: HomeAssistant, order: list[str], current: str) -> None:
    """Two bands holding at once with the same on_delay: both start at that instant, the later configured one is current."""
    phase = {"above": 10, "on_delay": {"seconds": 5}}
    drive = Drive({"above": 4, "phases": {key: {"name": key.upper(), **phase} for key in order}})
    drive.read(0, 50)
    drive.to(5)
    assert drive.started == [(None, 0), (order[0], 5), (order[1], 5)]
    assert drive.current == current


# --- 0.1's `phases` ---------------------------------------------------------------

WASHER: dict[str, Any] = {
    "above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2},
    "phases": {"warming": {"name": "Aquecendo", "above": 1000},
               "wringing": {"name": "Centrifugando", "above": 50, "below": 1000,
                            "on_delay": {"minutes": 3}}},
}


def washer(config: dict[str, Any] = WASHER) -> Drive:
    """The washer of 0.1's phases tests: idle at 1.4 W; 120 W from 125 s runs it at 185, then 7 W at 190.

    Its first reading came at the same instant as the 7 W, so every instant
    here is 10 s later.
    """
    drive = Drive(config)
    drive.read(0, 1.4)
    drive.read(125, 120)
    drive.to(185)
    assert drive.detector.on
    drive.read(190, 7)
    return drive


def test_a_band_without_on_delay_holds_at_once_and_ends_at_once(ha: HomeAssistant) -> None:
    drive = washer()
    drive.read(200, 1900)
    assert drive.current == "warming"
    drive.read(800, 121)
    assert drive.cycles("warming") == [(200, 800)]
    assert drive.detector.seen == ["warming"]


def test_a_band_with_on_delay_holds_after_it(ha: HomeAssistant) -> None:
    drive = washer()
    drive.read(200, 150)
    drive.to(379)
    assert "wringing" not in drive.detector.running
    drive.to(380)
    assert drive.current == "wringing"
    drive.read(400, 22)
    assert drive.cycles("wringing") == [(380, 400)]


def test_leaving_before_its_on_delay_is_not_the_phase(ha: HomeAssistant) -> None:
    drive = washer()
    drive.read(200, 150)
    drive.read(288, 7)
    drive.to(700)
    assert "wringing" not in drive.detector.seen


def test_overlapping_bands_run_at_once_and_none_wins(ha: HomeAssistant) -> None:
    """Today the first listed band won; now both run, and the current phase is the one that started last."""
    drive = washer({**WASHER, "phases": {"strong": {"name": "Forte", "above": 500},
                                         "any": {"name": "Qualquer", "above": 50}}})
    drive.read(200, 120)
    assert drive.current == "any"
    drive.read(300, 900)
    assert drive.current == "strong"
    assert drive.detector.running == ["strong", "any"]
    assert drive.detector.seen == ["strong", "any"]
    drive.read(400, 120)
    assert drive.current == "any"
    assert drive.cycles("strong") == [(300, 400)]
    drive.read(500, 7)
    # 120 W from 125 s held `any` before the program ran: it started with it, and 7 W ended it
    assert drive.cycles("any") == [(185, 190), (200, 500)]


def test_seen_stays_after_the_program_and_clears_with_the_next(ha: HomeAssistant) -> None:
    drive = washer()
    drive.read(200, 1900)
    drive.read(260, 121)
    drive.read(300, 1.4)
    drive.to(420)
    assert not drive.detector.on
    assert drive.current == "idle"
    assert drive.detector.seen == ["warming"]
    drive.read(500, 120)
    drive.to(560)
    assert drive.detector.seen == []


def test_seen_holds_after_the_program_over_a_restart(ha: HomeAssistant) -> None:
    """The washer finished after warming, then HA restarts: seen still shows warming."""
    drive = washer()
    drive.read(200, 1900)
    drive.read(260, 121)
    drive.read(300, 1.4)
    drive.to(420)
    restored = drive.program.Detector(drive.detector.program)
    restored.restore(drive.detector.snapshot())
    assert not restored.on
    assert restored.current == "idle"
    assert restored.running == []
    assert restored.seen == ["warming"]


def test_readings_while_stopped_start_nothing(ha: HomeAssistant) -> None:
    drive = Drive(WASHER)
    drive.read(0, 1.4)
    drive.read(125, 1900)
    drive.read(145, 150)
    drive.read(175, 1.4)
    drive.to(500)
    assert drive.started == []


def test_a_band_before_the_program_counts_when_it_starts(ha: HomeAssistant) -> None:
    drive = Drive(WASHER)
    drive.read(0, 1.4)
    drive.read(125, 30)
    drive.read(145, 1900)
    drive.to(185)
    assert drive.started == [(None, 185), ("warming", 185)]


def test_a_band_pending_its_on_delay_starts_over_after_no_value(ha: HomeAssistant) -> None:
    drive = washer()
    drive.read(200, 150)
    drive.read(300, None)
    drive.read(420, 150)
    drive.to(599)
    assert "wringing" not in drive.detector.running
    drive.to(600)
    assert drive.current == "wringing"


def test_no_value_keeps_a_phase_whose_band_held(ha: HomeAssistant) -> None:
    drive = washer()
    drive.read(200, 1900)
    drive.read(210, None)
    drive.to(510)
    assert drive.current == "warming"
    drive.read(510, 121)
    assert drive.cycles("warming") == [(200, 510)]


# --- the idle gap -----------------------------------------------------------------


def test_after_an_idle_gap_the_next_phase_does_not_wait(ha: HomeAssistant) -> None:
    """resfriar leaves for no band (40 W is neither's); a sip 10 s later starts at its on_delay.

    Today it waits for resfriar's off_delay, and a sip shorter than that is lost.
    """
    drive = purifier()
    drive.read(160, 40)
    drive.read(170, 20)
    drive.to(175)
    assert drive.current == "bebendo"
    assert drive.detector.running == ["bebendo", "resfriar"]
    drive.read(180, 1)
    drive.to(190)
    assert drive.cycles("resfriar") == [(155, 160)]
    drive.to(300)
    assert drive.cycles("bebendo") == [(175, 180)]


def test_after_an_idle_gap_below_the_program_the_next_phase_does_not_wait(
        ha: HomeAssistant) -> None:
    """The purifier: a chill's tail drops to 0.8 W, a sip comes 20 s later, shorter than the chill's off_delay."""
    drive = Drive(PURIFIER)
    drive.read(0, 0.8)
    drive.read(10, 12)
    drive.to(20)
    assert drive.current == "frosting"
    drive.read(300, 0.8)
    drive.read(320, 3.2)
    drive.to(321)
    assert drive.current == "pouring"
    drive.read(330, 0.8)
    drive.to(600)
    assert drive.cycles("frosting") == [(20, 300)]
    assert drive.cycles("pouring") == [(321, 330)]
    assert drive.cycles(None) == [(11, 330)]


def test_a_gap_then_back_in_its_band_is_still_one_cycle(ha: HomeAssistant) -> None:
    drive = purifier()
    drive.read(160, 40)
    drive.read(170, 120)
    drive.to(800)
    assert drive.current == "resfriar"
    assert drive.ended == []


# --- other ------------------------------------------------------------------------


def test_other_runs_outside_every_band_after_its_on_delay(ha: HomeAssistant) -> None:
    """The washer at 7 W: in the program's band, in no phase's."""
    drive = washer()
    drive.to(219)
    assert drive.current == "idle"
    drive.to(220)
    assert drive.started[-1] == ("other", 220)
    assert drive.current == "other"
    assert drive.detector.seen == ["other"]


def test_other_ends_at_once_when_a_phase_starts(ha: HomeAssistant) -> None:
    drive = washer()
    drive.read(300, 1900)
    assert drive.current == "warming"
    assert drive.cycles("other") == [(220, 300)]
    assert drive.detector.running == ["warming"]


def test_other_ends_after_its_off_delay_when_no_phase_starts(ha: HomeAssistant) -> None:
    """150 W is wringing's band, whose on_delay is 3 min: other ends at its off_delay, from when it left."""
    drive = washer()
    drive.read(300, 150)
    drive.to(329)
    assert drive.current == "other"
    drive.to(330)
    assert drive.current == "idle"
    assert drive.cycles("other") == [(220, 300)]


def test_other_ends_with_the_program(ha: HomeAssistant) -> None:
    drive = washer()
    drive.read(300, 1.4)
    drive.to(420)
    assert drive.cycles(None) == [(185, 300)]
    assert drive.cycles("other") == [(220, 300)]


def test_other_is_not_below_the_programs_band(ha: HomeAssistant) -> None:
    """The reading under the program's band ends the program: it isn't other."""
    drive = Drive(PURIFIER)
    drive.read(0, 0.8)
    drive.read(10, 12)
    drive.to(21)
    drive.read(300, 0.8)
    drive.to(600)
    assert "other" not in drive.detector.seen


def test_a_spike_shorter_than_others_on_delay_is_nothing(ha: HomeAssistant) -> None:
    """A chill's onset: one reading of 500 W, above every band, for 2 s."""
    drive = Drive(PURIFIER)
    drive.read(0, 0.8)
    drive.read(10, 500)
    drive.read(12, 12)
    drive.to(600)
    assert drive.detector.seen == ["frosting"]


def test_others_delays_are_tuned(ha: HomeAssistant) -> None:
    drive = washer({**WASHER, "other": {"on_delay": {"seconds": 5}, "off_delay": {"seconds": 1}}})
    drive.to(195)
    assert drive.current == "other"
    drive.read(300, 150)
    drive.to(301)
    assert drive.cycles("other") == [(195, 300)]


def test_no_other_without_phases(ha: HomeAssistant) -> None:
    drive = Drive(ALONE)
    drive.read(0, 7)
    drive.to(1000)
    assert drive.started == [(None, 60)]
    assert drive.current == "idle"


# --- time and restarts ------------------------------------------------------------


def test_each_delay_passes_at_its_own_time(ha: HomeAssistant) -> None:
    """One late advance gives the same cycles as a timer on time: the program at 145, resfriar at 155, quente at 170."""
    drive = Drive(MODES)
    drive.read(0, 1)
    drive.read(125, 120)
    drive.read(160, 1000)
    drive.to(10_000)
    assert drive.started[:3] == [(None, 145), ("resfriar", 155), ("quente", 170)]
    assert drive.cycles("resfriar") == [(155, 160)]


def test_a_phase_whose_delay_passes_as_the_program_ends_waits_for_the_next(
        ha: HomeAssistant) -> None:
    """At 130 s the program's off_delay and baixo's on_delay pass together: the program ends first, baixo waits for the next cycle."""
    drive = Drive({"above": 10, "off_delay": {"seconds": 30},
                   "phases": {"baixo": {"name": "Baixo", "above": 5, "below": 10,
                                        "on_delay": {"seconds": 30}},
                              "alto": {"name": "Alto", "above": 10}}})
    drive.read(0, 50)
    drive.read(100, 8)
    drive.to(130)
    assert "baixo" not in [key for key, _ in drive.started]
    assert drive.cycles(None) == [(0, 100)]
    assert drive.cycles("baixo") == []


def test_at_one_instant_the_program_ends_before_its_phases(ha: HomeAssistant) -> None:
    """The program's and a phase's off_delay pass together: the program's cycle comes first."""
    drive = Drive({"above": 4, "off_delay": {"seconds": 30},
                   "phases": {"p": {"name": "P", "above": 4, "off_delay": {"seconds": 30}}}})
    drive.read(0, 50)
    drive.read(100, 1)
    changes = drive.detector.advance(at(130), None)
    assert [(type(c).__name__, c.key) for c in changes] == [("Ended", None), ("Ended", "p")]


@pytest.mark.parametrize("keys", [["x", "y"], ["y", "x"]], ids=["x configured first", "y first"])
@pytest.mark.parametrize(("value", "ended"), [(5, ["y", "x"]), (1, [None, "y", "x"])],
                         ids=["their off_delays", "the program's end"])
def test_phases_ending_at_one_instant_end_in_the_order_they_started(
        ha: HomeAssistant, keys: list[str], value: float, ended: list[str | None]) -> None:
    """y starts at 0 s and x, the current phase, at 10 s, whatever the configuration's order; both left at 100 s: y ends first, x last."""
    bands = {"x": {"name": "X", "above": 20, "off_delay": {"seconds": 5}},
             "y": {"name": "Y", "above": 10, "off_delay": {"seconds": 5}}}
    drive = Drive({"above": 4, "off_delay": {"seconds": 5},
                   "phases": {key: bands[key] for key in keys}})
    drive.read(0, 15)
    drive.read(10, 50)
    assert drive.current == "x"
    drive.read(100, value)
    changes = drive.detector.advance(at(105), None)
    assert [c.key for c in changes] == ended
    assert all(c.cycle.end == at(100) for c in changes)


def _program_leaving() -> Drive:
    """The washer's program: 120 W from 125 s, its on_delay passing at 185 s, when 1.4 W comes."""
    drive = Drive(WASHER)
    drive.read(0, 1.4)
    drive.read(125, 120)
    drive.read(185, 1.4)
    return drive


def _phase_leaving() -> Drive:
    """wringing: 150 W from 200 s, its on_delay passing at 380 s, when 7 W comes."""
    drive = washer()
    drive.read(200, 150)
    drive.read(380, 7)
    return drive


def _other_leaving() -> Drive:
    """other: 7 W from 190 s, its on_delay passing at 220 s, when 150 W comes."""
    drive = washer()
    drive.read(220, 150)
    return drive


@pytest.mark.parametrize(("leaving", "key"), [
    pytest.param(_program_leaving, None, id="the program"),
    pytest.param(_phase_leaving, "wringing", id="a phase"),
    pytest.param(_other_leaving, "other", id="other"),
])
def test_a_reading_leaving_as_its_on_delay_passes_starts_nothing(
        ha: HomeAssistant, leaving: Any, key: str | None) -> None:
    """The reading at the instant a delay passes comes before it: in for exactly its on_delay isn't in, and no empty cycle."""
    drive = leaving()
    drive.to(1000)
    assert key not in [each for each, _ in drive.started]
    assert drive.cycles(key) == []


def test_a_reading_back_as_its_off_delay_passes_keeps_the_cycle(ha: HomeAssistant) -> None:
    """resfriar left at 160 s; 120 W comes back at 190 s, the instant its off_delay passes: the reading first, resfriar goes on."""
    drive = purifier()
    drive.read(160, 1)
    drive.read(190, 120)
    drive.to(1000)
    assert drive.current == "resfriar"
    assert drive.ended == []


def test_catch_up_is_what_a_late_reading_passes_first(ha: HomeAssistant) -> None:
    """on_delay 0, the program's off_delay passed at 130 s, 100 W read at 140 s: catch_up gives its end alone, then read its restart; together, read's own changes."""
    config = {"above": 4, "off_delay": {"minutes": 2}}
    alone, split = Drive(config), Drive(config)
    for drive in (alone, split):
        drive.read(0, 100)
        drive.read(10, 1)
    alone.read(140, 100)
    split._note(split.detector.catch_up(at(140), None))
    assert (split.started, split.ended) == ([(None, 0)], [(None, 0, 10)])
    split.read(140, 100)
    assert (split.started, split.ended) == (alone.started, alone.ended)
    assert alone.started == [(None, 0), (None, 140)]


def test_at_one_instant_a_phase_ends_before_another_starts(ha: HomeAssistant) -> None:
    """resfriar left for no band at 160 s (its end at 190); bebendo's on_delay passes at 190 too: resfriar's end comes first."""
    drive = purifier()
    drive.read(160, 40)
    drive.read(185, 20)
    changes = drive.detector.advance(at(190), None)
    assert [(type(c).__name__, c.key) for c in changes] == [("Ended", "resfriar"),
                                                             ("Started", "bebendo")]


def test_a_snapshot_restores_the_running_cycles(ha: HomeAssistant) -> None:
    drive = purifier()
    drive.read(160, 1000)
    drive.to(175)
    data = drive.detector.snapshot()
    program = drive.program
    restored = program.Detector(drive.detector.program)
    restored.restore(data)
    assert restored.on
    assert restored.current == "resfriar"
    assert restored.run("resfriar").until == at(160)
    assert restored.seen == ["resfriar"]
    # Its delays count again from the next reading, and the end stays
    assert restored.due() is None
    changes = restored.read(1000, at(200), None)
    assert changes == []
    changes = restored.advance(at(230), None)
    # resfriar's end is confirmed 30 s after the first reading; quente, armed at 210, waited for it
    assert [(type(c).__name__, c.key) for c in changes] == [("Ended", "resfriar"),
                                                             ("Started", "quente")]
    assert changes[0].cycle.end == at(160)
    assert changes[1].since == at(210)


NAIVE = "2026-09-16T13:00:00"


@pytest.mark.parametrize(("data", "on", "running", "seen"), [
    pytest.param({}, False, [], [], id="empty"),
    pytest.param({"program": None, "phases": {"resfriar": {"since": None}}}, False, [], [],
                 id="a phase without the program"),
    pytest.param({"program": None, "seen": ["gone", 5, "resfriar"]}, False, [], ["resfriar"],
                 id="seen while stopped"),
    pytest.param({"program": "garbage"}, False, [], [], id="program not a map"),
    pytest.param({"program": {}, "seen": ["resfriar"]}, False, [], ["resfriar"],
                 id="program without a start"),
    pytest.param({"program": {"since": NAIVE}}, False, [], [], id="program's start without a zone"),
    pytest.param({"program": {"since": "2026-02-30T10:00:00+00:00"}, "seen": ["resfriar"]},
                 False, [], ["resfriar"], id="program's impossible date"),
    pytest.param({"program": {"since": T0.isoformat()},
                  "phases": {"resfriar": {"since": "2026-13-45T00:00:00+00:00",
                                       "until": "2026-02-30T10:00:00+00:00"}},
                  "order": ["resfriar"], "seen": ["resfriar"]}, True, ["resfriar"], ["resfriar"],
                 id="a phase's impossible dates"),
    pytest.param({"program": {"since": T0.isoformat()}, "phases": {"gone": {"since": T0.isoformat()}},
                  "order": ["gone", 5], "seen": ["gone", "resfriar"]}, True, [], ["resfriar"],
                 id="a phase no longer configured"),
    pytest.param({"program": {"since": T0.isoformat()}, "phases": {"resfriar": {}},
                  "order": [["x"], "resfriar"], "seen": [["x"], "resfriar"]}, True, ["resfriar"], ["resfriar"],
                 id="keys not strings"),
    pytest.param({"program": {"since": T0.isoformat()},
                  "phases": {"resfriar": {"since": NAIVE, "until": NAIVE}},
                  "order": ["resfriar"], "seen": ["resfriar"]}, True, ["resfriar"], ["resfriar"],
                 id="a phase's times without a zone"),
    pytest.param({"program": {"since": T0.isoformat()}, "phases": "garbage", "order": "garbage",
                  "seen": "garbage"}, True, [], [], id="garbage"),
])
def test_a_snapshot_it_cannot_use_is_ignored(
        ha: HomeAssistant, data: dict[str, Any], on: bool, running: list[str], seen: list[str]) -> None:
    """Only a program with a start runs, with its phases still configured; seen keeps those, running or not.

    Keys that aren't strings and times without a zone (a hand-edited .storage)
    are dropped, and the readings after go on.
    """
    program = module("features.cycle.program")
    detector = program.Detector(program.program_of(program.SCHEMA(MODES)))
    detector.restore(data)
    assert detector.on is on
    assert detector.running == running
    assert detector.seen == seen
    detector.read(50, at(100), None)
    detector.read(1, at(200), None)
    detector.advance(at(1000), None)
    assert not detector.on


def test_a_phase_restored_twice_runs_once(ha: HomeAssistant) -> None:
    """A repeated key in the snapshot's order is one run; one without a start ends when it left."""
    program = module("features.cycle.program")
    detector = program.Detector(program.program_of(program.SCHEMA(MODES)))
    detector.restore({"program": {"since": T0.isoformat()},
                      "phases": {"resfriar": {"until": at(60).isoformat()}},
                      "order": ["resfriar", "resfriar"], "seen": ["resfriar"]})
    assert detector.running == ["resfriar"]
    assert detector.end_so_far(detector.run("resfriar")) == at(60)
    changes = detector.read(1, at(100), None)
    changes += detector.advance(at(130), None)
    assert [(c.key, c.cycle.start, c.cycle.end) for c in changes] == [("resfriar", None, at(60))]


# --- a real day of a water purifier (anonymised) ----------------------------------

PURIFIER: dict[str, Any] = {
    "above": 2.9, "on_delay": {"seconds": 1}, "off_delay": {"minutes": 1},
    "phases": {
        "pouring": {"name": "Servir água", "above": 2.9, "below": 4,
                       "on_delay": {"seconds": 1}, "off_delay": {"minutes": 1}},
        "frosting": {"name": "Resfriar", "above": 4, "below": 150,
                    "on_delay": {"seconds": 10}, "off_delay": {"minutes": 3}},
        "warming": {"name": "Aquecer", "above": 150, "below": 400,
                    "on_delay": {"seconds": 30}, "off_delay": {"seconds": 30}},
    },
}
POWER = "sensor.purifier_power"


def replay(name: str) -> list[tuple[str | None, datetime | None, datetime]]:
    """Every cycle the purifier's detector ends over a History CSV export, (key, start, end)."""
    program = module("features.cycle.program")
    reading = module("core.entity").reading
    detector = program.Detector(program.program_of(program.SCHEMA(PURIFIER)))
    ended: list[tuple[str | None, datetime | None, datetime]] = []
    kwh: float | None = None
    last = T0
    with (FIXTURES / name).open() as file:
        for row in csv.DictReader(file):
            when = datetime.fromisoformat(row["last_changed"].replace("Z", "+00:00"))
            value = reading(type("State", (), {"state": row["state"]})())
            if row["entity_id"] == POWER:
                changes = detector.read(value, when, kwh)
            else:
                changes = detector.advance(when, kwh)
                kwh = value
            ended.extend((c.key, c.cycle.start, c.cycle.end)
                         for c in changes if isinstance(c, program.Ended))
            last = when
    ended.extend((c.key, c.cycle.start, c.cycle.end)
                 for c in detector.advance(last + timedelta(hours=1), kwh)
                 if isinstance(c, program.Ended))
    return ended


@pytest.mark.usefixtures("ha")
def test_the_real_day_counts_each_kind() -> None:
    """Each drink, chill and warming its own cycle, as 0.1's `modes` count them; no `other`."""
    ended = replay("purifier_day.csv")
    assert Counter(key for key, *_ in ended) == {
        None: 33, "pouring": 14, "frosting": 21, "warming": 2}


@pytest.mark.usefixtures("ha")
def test_the_warming_at_10_10_is_not_truncated() -> None:
    """10:10 UTC: a 3m39s plateau from 10:10:20, 48 s after a chill's tail.

    Recorded from its on_delay (10:10:50) to when it left (10:13:59): 189 s.
    An older replay of the modes recorded ~69 s, the rest credited to frosting.
    """
    heatings = [(start, end) for key, start, end in replay("purifier_day.csv") if key == "warming"]
    start, end = heatings[-1]
    assert start == datetime(2020, 1, 1, 10, 10, 50, 569000, tzinfo=UTC)
    assert end == datetime(2020, 1, 1, 10, 13, 59, 899000, tzinfo=UTC)
