# Refactor D1: the detector of detected programs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the detector of detected programs, `features/cycle/program`, and test it on its own. A detected program is a band of a reading with `on_delay`/`off_delay`, and its phases are bands too (spec Part 4). The detector merges today's two detectors: the bands of `features/phases.py`, and the one-at-a-time arbitration and delays of `features/modes/current.py`. It adds three decided behaviours: overlapping bands run at once, the idle-gap end, and the built-in `other` phase. No feature uses it yet: D2 builds the appliance's `running_program` with it and removes `modes`, `phases` and the appliance's `running`. Nothing a user sees changes in D1.

**Architecture:**
- **`features/cycle/program/`**, a package (the spec's `features/cycle/program.py`, same import path `features.cycle.program`), in L1's shared machinery `features/cycle`:
  - `schema.py`: the detected `Program` block (`SCHEMA`), `Band`, `Phase`, `Program`, `program_of()`. Also the entity keys it creates (`phase_keys()`, `FIXED`), the translation keys it names (`NAMED`), and the phases' `COUNTERS`.
  - `detector.py`: `Detector`, pure: readings and time in, `Started`/`Ended` changes out, no HA. Each delay passes at its own time, however late `advance` is called. So a whole real day of a water purifier (anonymised) replays in milliseconds, exactly.
  - `entities.py`: the detector in HA. The **carrier** (`Carrier`, a `CycleSource` binary sensor under the key its builder gives, `running` for the appliance) owns the detector, restores it and follows the reading. It calls its **views** after its own state each step: per phase a `PhaseRunning` binary sensor (a `CycleSource`: the phase's cycles), `PhaseCurrent`, and `PhaseLast`. Each phase's cycle entities are today's `features/cycle` classes (last cycle, totals, energy), named with the detector's own translation keys. `build()` returns them all.
- **Entity keys**, in the builder's namespace as decided (spec "Decided when D starts" 2 and 3): `phase_<key>` (binary sensor), `phase_<key>_<suffix>` (last cycle, `cycles_total`, `runtime_total`, `energy_total`), `phase_current`, `phase_last`. With the appliance they are `appliance_phase_<key>_*`, D2's IDs.
- **Landing (ruling 1):** a module no registered builder uses. It gets thorough unit tests of the pure detector and entity tests through a test-only builder, swapped in for `FEATURES["appliance"]` inside the test file (`monkeypatch.setitem`). The alternative, a `Feature` in the package but not registered, would be dead code that no contract test reaches and that D2 deletes anyway. Here nothing in `FEATURES`, `DEVICE_KEYS`, `ASPECTS`, the schema or the ID snapshot changes, and the entity tests still run the real wiring (`setup`, `build`, `creatable`, the platforms, restore, reload) with D2's entity IDs.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3, voluptuous, pytest (pytest-homeassistant-custom-component), ruff, mypy strict, uv.

**Spec:** `docs/superpowers/specs/2026-09-29-yaml-contract-coherence-design.md`: Part 4 ("The model", "In the code", "Decided when D starts" 1–6, "Not in 0.2.0"), Part 3 ("Layers"), PRs → D1, "Why this order", A1's ID snapshot rule (D updates `tests/test_ids.py` on purpose only for modes and phases, which is D2).

**Base:** `main` at 217bb52 (B4 merged, #54), with the spec commit d5cae7c rebased onto it (Task 1, Step 0). The branch `refactor/d1-detector` was cut from f7ac13e, before B4 merged. `git merge-tree` shows the rebase is clean.

## Global Constraints

- Version stays `0.2.0`.
- `tests/test_ids.py` and `tests/fixtures/house_ids.json` unchanged. D1 registers no builder, so no entity or generated item appears or goes. D2 updates the snapshot on purpose for modes and phases.
- Nothing user-visible changes. `FEATURES`, `DEVICE_KEYS`, `ASPECTS`, `CHECKS`, the schema and the docs' Guide tab stay as they are. The shared code D1 touches only gains:
  - an optional `translation=` on the cycle entities (`features/cycle/last.py`, `totals.py`); without it, everything is as today;
  - new translation and icon keys. The only existing key it touches, `phase_current`, keeps its name and gains two states (`other`, `dispensing`).
- Layers (`tests/test_code.py`, unchanged): `features/cycle/program/` imports only `core/`, `const` and `features/cycle`. `features/modes`, `features/phases.py` and `features/appliance` don't import it (D2 does).
- `uv run pytest` green at every commit: ruff, ruff format, mypy strict, hassfest, the layer table, the quality scale.
- Per-function coverage not lower than B4's (20 missed lines at 217bb52), measured the same way on both: `uv run pytest --cov=custom_components/pururu --cov-report=json:<file>`, B4's in a `git archive 217bb52` scratch copy, each function compared by name (a moved function under its new name). Every function of `features/cycle/program/` is fully covered.
- Commits end with exactly:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM
  ```
- Never `git stash` (shared with other sessions), and never checkout, restore or reset the worktree's files. A RED against the old code runs in a scratch copy:
  - `git archive HEAD | tar -x -C <scratchpad>/<dir>`;
  - copy `.hassfest` and the new test in, then `uv sync --locked` there;
  - run it there, then delete the dir.
- Every review finding fixed, minors included; ask when in doubt.
- The PR flow:
  1. After Task 1: push, open a **draft** PR `pururu: refactor D1, the detector of detected programs (0.2.0)`. Wait until `gh pr view <n> --json headRefOid -q .headRefOid` equals `git rev-parse HEAD`, then add `claude-review`.
  2. Each later task: push, wait for `headRefOid` again, add `claude-review` (remove it first if it's still there). Fix what the review finds before the next label.
  3. After the final review's fixes: the `greptile` label, then `gh pr ready`, then `@greptileai review` once if Greptile answers "does not match any trigger rule".
  4. If `gh pr edit --add-label` fails with a GraphQL error: `gh api -X POST repos/thatsnotmynameio/pururu-ha/issues/<n>/labels -f 'labels[]=<label>'`.

## Review Focus

The five input classes most likely to bite, each with the tests that pin it:

1. **Readings at the edges between bands: a dip vs an idle gap.** From a running phase's band straight into another's (a dip), the other waits. Via a reading outside every band (a gap: exactly on a strict bound, like 40 W between `below: 40` and `above: 40`, or under the program's band, like the purifier's 0.8 W), it doesn't wait. The phase that left still ends at the moment it left, and coming back to its band cancels its end. Pinned in Task 1:
   - `test_after_a_dip_another_phase_waits_for_the_running_one`, `test_a_dip_into_another_band_does_not_split_the_cycle`;
   - `test_after_an_idle_gap_the_next_phase_does_not_wait`, `test_after_an_idle_gap_below_the_program_the_next_phase_does_not_wait`;
   - `test_a_gap_then_back_in_its_band_is_still_one_cycle`, `test_other_is_not_below_the_programs_band`;
   - `test_a_phase_armed_in_a_dip_starts_when_the_reading_holds_both` (a dip into an overlap);
   - `test_no_phase_starts_while_the_programs_reading_is_out`, `test_the_programs_reading_back_starts_the_phase_that_waited` (a phase band reaching below the program's).
2. **Several things at one instant.** Overlapping bands start and end independently. Deadlines at the same instant pass in a fixed order: the program's, then the phases' ends in the order they started, then their starts in the configuration's order. A reading at the very instant a delay passes comes before it. A handover writes `phase_current` once, never `idle` in between. A configured phase starting ends `other` at once. Pinned:
   - Task 1: `test_overlapping_bands_run_at_once_and_none_wins`, `test_a_handover_never_shows_idle`, `test_other_ends_at_once_when_a_phase_starts`, `test_each_delay_passes_at_its_own_time`;
   - Task 1, the order (ruling 17): `test_at_one_instant_the_program_ends_before_its_phases`, `test_at_one_instant_a_phase_ends_before_another_starts`, `test_phases_starting_at_one_instant_start_in_the_configurations_order`, `test_phases_ending_at_one_instant_end_in_the_order_they_started`, `test_a_phase_whose_delay_passes_as_the_program_ends_waits_for_the_next`;
   - Task 1, a reading at a delay's instant: `test_a_reading_leaving_as_its_on_delay_passes_starts_nothing`, `test_a_reading_back_as_its_off_delay_passes_keeps_the_cycle`;
   - Task 2: `test_a_handover_never_shows_idle` (the entity), `test_a_phases_cycle_is_sent_after_its_state_its_end_last`.
3. **Readings without a value** (`unavailable`, `unknown`, not a number; the CSV has them). Every delay counts again from the next reading. Runs, and when a run's reading left, stay. Pinned in Task 1:
   - `test_no_value_counts_the_delays_again_and_keeps_the_end`, `test_no_value_keeps_the_phase_and_counts_its_delays_again`;
   - `test_a_band_pending_its_on_delay_starts_over_after_no_value`, `test_no_value_keeps_a_phase_whose_band_held`;
   - the replay, which reads the CSV's `unavailable` rows.
4. **Restored state that doesn't fit.** A snapshot can name phases no longer configured, repeat a key, hold garbage, or lack a start. The views can be added before the carrier restored the detector (`phase_current` is on another platform). A restart must neither flicker a phase off then on, nor count HA's downtime as runtime. Pinned:
   - Task 1: `test_a_snapshot_restores_the_running_cycles`, `test_a_phase_restored_twice_runs_once`, `test_seen_holds_after_the_program_over_a_restart`;
   - Task 1: `test_a_snapshot_it_cannot_use_is_ignored`, whose params include `seen while stopped`, `program without a start`, the times without a zone, `keys not strings`, and the impossible dates;
   - Task 2: `test_a_restart_keeps_the_running_phase`, `test_a_reload_mid_phase_counts_one_cycle`, `test_last_restores`, `test_a_snapshot_the_detector_cannot_use_is_ignored`, `test_a_phases_impossible_date_is_no_start`;
   - the shared `CycleStart.from_dict`: `test_appliance.py`'s `test_restart_with_an_impossible_start_restores_running`.
5. **Phase keys that collide or are reserved.** These keys are refused with a message, before any entity ID can meet another: `idle` and `other`; `current` and `last` (the detector's `phase_current` and `phase_last`); `gelar` beside `gelar_cycles_total`; `other_cycles_total`. Pinned in Task 1: `test_invalid_program_is_refused`'s params.

## Rulings

Where the spec is silent, decided here:

1. **How D1 lands:** the detector is a module no registered builder uses. Its entities are tested through a test-only builder swapped in for `FEATURES["appliance"]` (Architecture explains why).
2. **A package, not one file:** `features/cycle/program/` (`schema.py`, `detector.py`, `entities.py`; `__init__` re-exports). As one file it would be about 900 lines. The import path is the spec's.
3. **The detector is pure.** It holds no HA object and reads no clock. It takes `(value, now, kwh)` and returns `Started`/`Ended`, and each delay passes at its own deadline. The carrier's one timer waits for `due()`.
4. **What stays of the arbitration (spec item 1 vs "the modes' one-at-a-time arbitration", Tests #6):** overlapping bands run at once and no band wins. A phase whose band holds while another phase's cycle *ends after a dip* waits for that end, or for a reading back in both bands, then starts from when its on_delay passed (today's handover, and today's dip protection: a chill's tail dipping into the sip band is no drink). Without overlap, every cycle, start and end is today's, two edge cases excepted: a phase band reaching below the program's (ruling 21), and a reading at the very instant a delay passes (ruling 17). None of today's configurations has the first; the second needs a reading at exactly a deadline's time.
5. **The idle gap (item 5), in the detector's terms:** a running phase's `gap` is set by any reading outside every configured band after it left its own; a reading under the program's band is one. A gap blocks nothing: a phase whose on_delay passes starts at once, without waiting for the gap's phase's off_delay, and both run until that off_delay passes (`running` lists both). The gap's phase still ends then, at the moment it left. Its reading back in its band cancels the end and clears the gap. A phase that left straight into another band (a dip, ruling 4) has no gap, and the other waits for it; a gap reading during its off_delay sets the gap then.
6. **`other` (item 4):**
   - its region is the program's band minus every configured band; a reading under the program's band (the program ending) isn't `other`;
   - it exists only with at least one configured phase;
   - it waits for nothing; a configured phase starting ends it at once, at the moment its reading left its region;
   - `other:` takes only `on_delay` and `off_delay` (30 s each by default);
   - its entities are named by their own translations (`phase_other*`), not by an item name.
7. **`phase_current`'s state (item 3 says it "lists the phases running"):** it's an enum sensor. Its state is the running phase that started last, `idle` when none runs. That includes the program's first seconds before a phase's on_delay passes, as `mode_current` shows today. Its attributes: `running` (the running phases, the configuration's order) and `seen` (the phases that ran in the program's current or last cycle, `other` included, cleared when a program cycle starts: today's phases' `seen`).
8. **`phase_last`:** the phase of the last phase cycle that ended, restored, as today's `mode_last`.
9. **`statistics` in a program or a phase:** refused by D1's schema. The statistics aspect owns the key (D6), and L1 can't import L2, so D2 mounts it through `catalogue.mount` inside `running_program` and its phases. D1 declares the phases' `COUNTERS` and builds every total the meters read.
10. **`name`:** required on a phase (it names the phase's entities); optional on a program (`running_program` is named by its builder's key; D3 decides for `detected:` items).
11. **Delays:** `on_delay`/`off_delay` default to 0 (at once) on a program and a phase, as the spec says for phases. Today's appliance and modes require theirs, and D2 decides whether `running_program` does.
12. **Entity-key collisions** are refused by the schema (`_apart`), whatever the platform. The carrier's key is its builder's, so the builder avoids `phase_*`.
13. **The program's own cycle entities** (last cycle, totals, idle energy) stay the builder's. The appliance keeps `appliance_last_cycle_*` etc. with `source="running"`. D1 builds only the carrier, under the key the builder passes.
14. **Energy:** a cycle's energy is the counter's growth from its start to when its end is processed (today's rule for modes and `running`), however far back the end is dated.
15. **Restoring:**
    - The carrier stores the whole snapshot: the running cycles, the order they started in, and `seen`. Delays and armed phases aren't stored; they count again from the next reading.
    - `seen` is restored whether or not the program runs: after a restart, a finished program still shows the phases it saw, as before it. Only phases still configured are kept.
    - The program runs only with a start: a snapshot whose program has none, or one the detector can't read, restores no running cycle. A running phase is restored with or without a start (one without ends when its reading left).
    - What the detector can't read is dropped: a key that isn't a string or no longer configured, a time without a zone, and an impossible date (`2026-02-30`), which `CycleStart.from_dict` reads as no time. That helper is shared with the appliance's `running`, `modes` and the openings, which gain the same guard.
    - A `PhaseRunning` is added after the carrier on the same platform (`build`'s order; HA adds one platform's entities one by one), so it never shows an unrestored state.
    - `PhaseCurrent` (another platform) shows its restored state and attributes (`running`, `seen`) until the carrier is `ready`.
    - The carrier follows the reading only once its entry is set up (`LOADED`): a step at add could end a restored phase (delays of 0) before its entities listen, and the cycle would be lost. A reading before that is read by its first step.
    - A snapshot that isn't a map is none: the carrier starts from nothing. Anything in a map goes to the detector, which drops what it can't read (above), so the carrier needs no guard of its own.
16. **After the program ends,** a running phase whose band still holds is armed, and starts with the next program cycle (today's modes). When the program ends, its running phases end with it, in the order they started (ruling 17).
17. **Ordering at one instant:**
    - The program's deadline first, then the phases' ends, then their starts. The phases' ends go in the order the phases started, whether their off_delays pass together or the program's end ends them: the current phase ends last, so `phase_last` shows it. Their starts go in the configuration's order (no start order exists yet), so the later configured one is current.
    - A reading at the very instant a delay passes comes before it. `read` passes the delays before its instant, applies the reading, then passes those at its instant (delays of 0 among them). So a band held for exactly its on_delay isn't held, and no cycle is empty for it; a reading back in its band as its off_delay passes keeps the cycle; a reading without a value at that instant stops the delay, as any other. `advance` alone passes the delays at its instant too.
    - The detector returns the program's `Ended` before its phases' (its deadline passes first). The carrier wraps its phases' entities: its state is written before theirs when the program starts, and after theirs when it ends (its `running` → `off` and its end signal come with its phases ended, `phase_current` idle and `phase_last` set: the events' `states` agree).
18. **Translation keys owned by the detector (`NAMED`)**, outside every namespace, as the statistics aspect's:
    - `phase_current` (today's key of `phases`, whose name is the same; D2 deletes `phases` and the key stays);
    - `phase_last`;
    - `phase_<suffix>` with `{item}`, for a configured phase's cycle entities;
    - `phase_other` and `phase_other_<suffix>`, for other's.

    A configured phase's binary sensor is named by its `name`, as a configured entity is. The contract test counts `NAMED` as created and checks each is named and has an icon.
19. **The 10:10 heating of the purifier's day is not truncated on `main` already.** On `main`, today's modes record 189 s at a 1-s replay and 185 s at a 30-s step; the handover's start from when it was armed came with 0.1.20 (#30). The ~69 s once pinned elsewhere comes from a replay of an older version. D1's replay pins the detector's result, 10:10:50.569 → 10:13:59.899 UTC on the anonymised day (189.33 s, its on_delay excluded). D1's own gain on that data is the idle gap: a phase armed during another's gap is no longer lost (Task 1's idle-gap tests). On that day itself the counts are unchanged (14 drinks, 21 chills, 2 heatings, 33 appliance cycles), and `other` never runs.
20. **A disabled carrier:** HA never adds it, so the detector never runs. Its phases' entities are still created (`creatable` ignores a disabled source, as for every follower today): each `phase_<key>` shows off and `phase_current` shows `idle`, not its restored phase. Dropping the followers of a disabled source would change every feature, not only this one.
21. **While the program's reading is out** (its off_delay counting), no phase starts. One whose on_delay passes then stays armed: it starts on the program's reading back, dated from when its on_delay passed, or with the next program cycle. Only a phase band reaching below the program's can hold then. Today's modes start it and end it with the program, a zero-length cycle; none of today's configurations has such a band.

---

### Task 1: The detector alone

The `Program` schema and the pure `Detector`, tested without HA entities. Today's modes and phases scenarios are replayed with the same readings, and a real day of a water purifier (anonymised) is replayed from a CSV. The draft PR opens after this task.

**Files:**
- Create `custom_components/pururu/features/cycle/program/__init__.py`, `schema.py`, `detector.py`.
- Create `tests/test_program.py`.
- Create `tests/fixtures/purifier_day.csv`, an anonymised copy of a real day's History export of a water purifier (Step 1). Its rows are `entity_id,state,last_changed` (UTC); `PURIFIER` below is that device's configuration in the detector's syntax.

**Interfaces:**

Consumes (all exist at 217bb52):
- `features/cycle/__init__.py`: `Cycle(start, end, energy_kwh)`, `CycleStart(since, since_energy, until)` with `as_dict()` / `from_dict()`.
- `features/cycle/energy.py`: `kwh_used(start: float | None, end: float | None) -> float | None`.
- `features/cycle/last.py`: `LAST_CYCLE` (its keys name the phases' suffixes).
- `core/feature.py`: `TEXT`, `Item(slug, name)`, `bounded(what)`, `finite_float`.
- `core/roles.py`: `Counters(needs, mount="block")`.

Produces:

```python
# features/cycle/program/schema.py
IDLE = "idle"; OTHER = "other"; PHASE = "phase"; OTHER_DELAY = timedelta(seconds=30)
SUFFIXES: dict[str, Platform]   # last_cycle_start/end/duration/energy, cycles_total, runtime_total, energy_total
FIXED: dict[str, Platform]      # phase_current, phase_last
NAMED: dict[str, Platform]      # the translation keys the detector names (Task 3 names them)
COUNTERS: Counters              # runtime, cycles, energy (needs "energy")
def phase_keys(key: str) -> dict[str, Platform]          # phase_<key>, phase_<key>_<suffix>
SCHEMA: Callable[[Any], dict[str, Any]]                   # a detected program's block
@dataclass(frozen=True, kw_only=True)
class Band:  above: float | None; below: float | None; on_delay: timedelta; off_delay: timedelta
    def holds(self, value: float) -> bool
@dataclass(frozen=True, kw_only=True)
class Phase: key: str; name: str; band: Band
    item: Item   # property: Item(slug=f"phase_{key}", name=name)
    other: bool  # property
@dataclass(frozen=True, kw_only=True)
class Program: band: Band; phases: tuple[Phase, ...] = ()   # configured, then other
def program_of(config: Mapping[str, Any]) -> Program

# features/cycle/program/detector.py
@dataclass
class Run: since: datetime | None; since_energy: float | None = None; until: datetime | None = None; gap: bool = False
    def as_dict(self) -> dict[str, Any]
    @classmethod
    def from_dict(cls, data: Any) -> Self | None
@dataclass(frozen=True)
class Started: key: str | None; since: datetime | None     # key None: the program
@dataclass(frozen=True)
class Ended: key: str | None; cycle: Cycle
type Change = Started | Ended
class Detector:
    def __init__(self, program: Program) -> None
    program: Program
    on: bool                                   # property
    current: str                               # property: the phase started last, or "idle"
    running: list[str]                         # property: configuration's order
    seen: list[str]                            # property: configuration's order
    def run(self, key: str | None) -> Run | None
    def end_so_far(self, run: Run) -> datetime | None
    def due(self) -> datetime | None
    def read(self, value: float | None, now: datetime, kwh: float | None) -> list[Change]
    def advance(self, now: datetime, kwh: float | None) -> list[Change]
    def snapshot(self) -> dict[str, Any]
    def restore(self, data: Mapping[str, Any]) -> None
```

- [ ] **Step 0: Rebase onto `main`.** The branch was cut before B4 merged.

  ```sh
  git fetch origin
  git rebase origin/main
  git log --oneline -3
  ```

  Expected: the rebase is clean, and the log shows `docs: refactor D1 plan`, then `docs: the owner's decisions for D …`, then `217bb52 pururu: refactor B4, …`. Then `uv sync --locked`.

- [ ] **Step 1: Copy the fixture.** `tests/fixtures/purifier_day.csv` is an anonymised copy of the purifier's History export: its entity IDs renamed (`sensor.purifier_power`, `sensor.purifier_energy`), and every `last_changed` shifted by one constant offset so the day starts at 2020-01-01T00:00:00.000Z. The milliseconds, every interval between rows and every value are kept.

  ```sh
  wc -l tests/fixtures/purifier_day.csv
  ```

  Expected: `326 tests/fixtures/purifier_day.csv`.

- [ ] **Step 2: Write the failing tests.** Create `tests/test_program.py`:

  ```python
  """features/cycle/program: a detected program and its phases, the detector alone (no HA entity).

  Times are seconds from T0. Each scenario of today's modes and phases tests is
  replayed here with the same readings, the washer's 10 s later (see washer()):
  the same cycles, starts and ends.
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

  GELAR = {"name": "Gelar", "above": 40, "below": 300, "on_delay": {"seconds": 30}, "off_delay": {"seconds": 30}}
  PROGRAM: dict[str, Any] = {"above": 4, "on_delay": {"seconds": 20}, "off_delay": {"minutes": 2},
                             "phases": {"gelar": GELAR}}


  @pytest.mark.parametrize("block", [
      pytest.param({**PROGRAM, "above": 5, "below": 5}, id="above equals below"),
      pytest.param({k: v for k, v in PROGRAM.items() if k != "above"}, id="no bound"),
      pytest.param({**PROGRAM, "above": "nan"}, id="bound not a number"),
      pytest.param({**PROGRAM, "phases": {}}, id="no phase"),
      pytest.param({**PROGRAM, "phases": {"Gelar": GELAR}}, id="not a slug"),
      pytest.param({**PROGRAM, "phases": {"gelar": {k: v for k, v in GELAR.items() if k != "name"}}},
                   id="a phase without name"),
      pytest.param({**PROGRAM, "phases": {"gelar": {**GELAR, "name": "  "}}}, id="blank name"),
      pytest.param({**PROGRAM, "phases": {"gelar": {"name": "Gelar"}}}, id="a phase without bound"),
      pytest.param({**PROGRAM, "phases": {"gelar": {**GELAR, "above": 300, "below": 40}}},
                   id="a phase's above over its below"),
      pytest.param({**PROGRAM, "phases": {"gelar": {**GELAR, "phases": {"x": GELAR}}}},
                   id="phases inside a phase"),
      pytest.param({**PROGRAM, "phases": {"gelar": {**GELAR, "for": 3}}}, id="a phase's for"),
      pytest.param({**PROGRAM, "statistics": {"cycles": ["today"]}}, id="statistics: D2 mounts it"),
      pytest.param({**PROGRAM, "phases": {"idle": GELAR}}, id="a phase keyed idle"),
      pytest.param({**PROGRAM, "phases": {"other": GELAR}}, id="a phase keyed other"),
      pytest.param({**PROGRAM, "phases": {"current": GELAR}}, id="phase_current is the detector's"),
      pytest.param({**PROGRAM, "phases": {"last": GELAR}}, id="phase_last is the detector's"),
      pytest.param({**PROGRAM, "phases": {"gelar": GELAR, "gelar_cycles_total": GELAR}},
                   id="two phases creating one entity key"),
      pytest.param({**PROGRAM, "phases": {"other_cycles_total": GELAR}},
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
      block = {**PROGRAM, "phases": {"other_cycles_total": GELAR}}
      with pytest.raises(vol.Invalid, match="phase other_cycles_total would create "
                                            "phase_other_cycles_total, phase other's"):
          schema(block)


  def test_a_program_takes_what_the_spec_says(ha: HomeAssistant) -> None:
      """Delays default to 0 (at once); other's to 30 s; overlapping and touching bands pass; name is optional on the program."""
      program = module("features.cycle.program")
      config = program.SCHEMA({
          "above": 4,
          "phases": {"heating": {"name": "Aquecendo", "above": 1000},
                     "spinning": {"name": "Centrifugando", "above": 50, "below": 1000},
                     "any": {"name": "Qualquer", "above": 50}},
      })
      detected = program.program_of(config)
      assert detected.band == program.Band(above=4, on_delay=timedelta(0), off_delay=timedelta(0))
      assert [phase.key for phase in detected.phases] == ["heating", "spinning", "any", "other"]
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
      assert set(program.phase_keys("gelar")) == {
          "phase_gelar", "phase_gelar_last_cycle_start", "phase_gelar_last_cycle_end",
          "phase_gelar_last_cycle_duration", "phase_gelar_last_cycle_energy",
          "phase_gelar_cycles_total", "phase_gelar_runtime_total", "phase_gelar_energy_total"}
      assert set(program.FIXED) == {"phase_current", "phase_last"}
      assert set(program.COUNTERS.needs) == {"runtime", "cycles", "energy"}


  # --- the program alone: today's appliance `running` ------------------------------

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


  # --- today's modes, as phases -----------------------------------------------------

  MODES: dict[str, Any] = {
      "above": 4, "on_delay": {"seconds": 20}, "off_delay": {"minutes": 2},
      "phases": {
          "bebendo": {"name": "Bebendo", "above": 4, "below": 40,
                      "on_delay": {"seconds": 5}, "off_delay": {"minutes": 5}},
          "gelar": GELAR,
          "quente": {"name": "Água quente", "above": 300,
                     "on_delay": {"seconds": 10}, "off_delay": {"seconds": 30}},
      },
  }


  def purifier() -> Drive:
      """test_modes' purifier: idle at 1 W, then 120 W from 125 s: the program at 145, gelar at 155."""
      drive = Drive(MODES)
      drive.read(0, 1)
      drive.read(125, 120)
      drive.to(155)
      assert drive.current == "gelar"
      return drive


  def test_a_phase_starts_after_its_on_delay(ha: HomeAssistant) -> None:
      drive = Drive(MODES)
      drive.read(0, 1)
      drive.read(125, 120)
      drive.to(150)
      assert drive.detector.on
      assert drive.current == "idle"
      drive.to(155)
      assert drive.started == [(None, 145), ("gelar", 155)]
      assert drive.current == "gelar"
      # Its reading hasn't left: it has no end yet
      assert drive.detector.end_so_far(drive.detector.run("gelar")) is None


  def test_a_phase_ends_after_its_off_delay_at_when_it_left(ha: HomeAssistant) -> None:
      drive = purifier()
      drive.read(160, 1)
      drive.to(189)
      assert drive.current == "gelar"
      drive.to(190)
      assert drive.current == "idle"
      assert drive.cycles("gelar") == [(155, 160)]


  def test_back_in_its_band_cancels_the_end(ha: HomeAssistant) -> None:
      drive = purifier()
      drive.read(160, 1)
      drive.read(180, 120)
      drive.to(240)
      assert drive.current == "gelar"
      assert drive.cycles("gelar") == []


  def test_after_a_dip_another_phase_waits_for_the_running_one(ha: HomeAssistant) -> None:
      """From 120 W to 1000 W: quente's on_delay passes at 170, it starts when gelar ends at 190, from 170."""
      drive = purifier()
      drive.read(160, 1000)
      drive.to(172)
      assert drive.current == "gelar"
      assert drive.detector.running == ["gelar"]
      drive.to(190)
      assert drive.current == "quente"
      assert drive.cycles("gelar") == [(155, 160)]
      assert drive.started[-1] == ("quente", 170)


  def test_a_dip_into_another_band_does_not_split_the_cycle(ha: HomeAssistant) -> None:
      drive = purifier()
      drive.read(160, 20)
      drive.read(170, 120)
      drive.to(800)
      assert drive.current == "gelar"
      assert drive.ended == []


  def test_a_short_visit_to_another_band_is_nothing(ha: HomeAssistant) -> None:
      drive = purifier()
      drive.read(160, 1000)
      drive.read(165, 120)
      drive.to(800)
      assert drive.current == "gelar"
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
      assert drive.current == "gelar"
      drive.read(765, 1000)
      drive.to(790)
      assert drive.current == "gelar"  # its off_delay counts from 765
      drive.to(795)
      assert drive.current == "quente"
      assert drive.cycles("gelar") == [(155, 160)]
      assert drive.started[-1] == ("quente", 775)


  def test_a_handover_never_shows_idle(ha: HomeAssistant) -> None:
      """gelar ends and quente starts in one step: nothing in between."""
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
      assert drive.cycles("gelar") == [(155, 755)]
      assert drive.energy["gelar"] == pytest.approx(0.05)


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


  # --- today's phases ---------------------------------------------------------------

  WASHER: dict[str, Any] = {
      "above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2},
      "phases": {"heating": {"name": "Aquecendo", "above": 1000},
                 "spinning": {"name": "Centrifugando", "above": 50, "below": 1000,
                              "on_delay": {"minutes": 3}}},
  }


  def washer(config: dict[str, Any] = WASHER) -> Drive:
      """test_phases' washer: idle at 1.4 W; 120 W from 125 s runs it at 185, then 7 W at 190.

      Each scenario's first reading comes 10 s after the 7 W (test_phases writes
      it at the same instant), so every instant is 10 s later than there.
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
      assert drive.current == "heating"
      drive.read(800, 121)
      assert drive.cycles("heating") == [(200, 800)]
      assert drive.detector.seen == ["heating"]


  def test_a_band_with_on_delay_holds_after_it(ha: HomeAssistant) -> None:
      drive = washer()
      drive.read(200, 150)
      drive.to(379)
      assert "spinning" not in drive.detector.running
      drive.to(380)
      assert drive.current == "spinning"
      drive.read(400, 22)
      assert drive.cycles("spinning") == [(380, 400)]


  def test_leaving_before_its_on_delay_is_not_the_phase(ha: HomeAssistant) -> None:
      drive = washer()
      drive.read(200, 150)
      drive.read(288, 7)
      drive.to(700)
      assert "spinning" not in drive.detector.seen


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
      assert drive.detector.seen == ["heating"]
      drive.read(500, 120)
      drive.to(560)
      assert drive.detector.seen == []


  def test_seen_holds_after_the_program_over_a_restart(ha: HomeAssistant) -> None:
      """The washer finished after heating, then HA restarts: seen still shows heating."""
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
      assert restored.seen == ["heating"]


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
      assert drive.started == [(None, 185), ("heating", 185)]


  def test_a_band_pending_its_on_delay_starts_over_after_no_value(ha: HomeAssistant) -> None:
      drive = washer()
      drive.read(200, 150)
      drive.read(300, None)
      drive.read(420, 150)
      drive.to(599)
      assert "spinning" not in drive.detector.running
      drive.to(600)
      assert drive.current == "spinning"


  def test_no_value_keeps_a_phase_whose_band_held(ha: HomeAssistant) -> None:
      drive = washer()
      drive.read(200, 1900)
      drive.read(210, None)
      drive.to(510)
      assert drive.current == "heating"
      drive.read(510, 121)
      assert drive.cycles("heating") == [(200, 510)]


  # --- the idle gap -----------------------------------------------------------------


  def test_after_an_idle_gap_the_next_phase_does_not_wait(ha: HomeAssistant) -> None:
      """gelar leaves for no band (40 W is neither's); a sip 10 s later starts at its on_delay.

      Today it waits for gelar's off_delay, and a sip shorter than that is lost.
      """
      drive = purifier()
      drive.read(160, 40)
      drive.read(170, 20)
      drive.to(175)
      assert drive.current == "bebendo"
      assert drive.detector.running == ["bebendo", "gelar"]
      drive.read(180, 1)
      drive.to(190)
      assert drive.cycles("gelar") == [(155, 160)]
      drive.to(300)
      assert drive.cycles("bebendo") == [(175, 180)]


  def test_after_an_idle_gap_below_the_program_the_next_phase_does_not_wait(
          ha: HomeAssistant) -> None:
      """The purifier: a chill's tail drops to 0.8 W, a sip comes 20 s later, shorter than the chill's off_delay."""
      drive = Drive(PURIFIER)
      drive.read(0, 0.8)
      drive.read(10, 12)
      drive.to(20)
      assert drive.current == "cooling"
      drive.read(300, 0.8)
      drive.read(320, 3.2)
      drive.to(321)
      assert drive.current == "dispensing"
      drive.read(330, 0.8)
      drive.to(600)
      assert drive.cycles("cooling") == [(20, 300)]
      assert drive.cycles("dispensing") == [(321, 330)]
      assert drive.cycles(None) == [(11, 330)]


  def test_a_gap_then_back_in_its_band_is_still_one_cycle(ha: HomeAssistant) -> None:
      drive = purifier()
      drive.read(160, 40)
      drive.read(170, 120)
      drive.to(800)
      assert drive.current == "gelar"
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
      assert drive.current == "heating"
      assert drive.cycles("other") == [(220, 300)]
      assert drive.detector.running == ["heating"]


  def test_other_ends_after_its_off_delay_when_no_phase_starts(ha: HomeAssistant) -> None:
      """150 W is spinning's band, whose on_delay is 3 min: other ends at its off_delay, from when it left."""
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
      assert drive.detector.seen == ["cooling"]


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
      """One late advance gives the same cycles as a timer on time: the program at 145, gelar at 155, quente at 170."""
      drive = Drive(MODES)
      drive.read(0, 1)
      drive.read(125, 120)
      drive.read(160, 1000)
      drive.to(10_000)
      assert drive.started[:3] == [(None, 145), ("gelar", 155), ("quente", 170)]
      assert drive.cycles("gelar") == [(155, 160)]


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
      """spinning: 150 W from 200 s, its on_delay passing at 380 s, when 7 W comes."""
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
      pytest.param(_phase_leaving, "spinning", id="a phase"),
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
      """gelar left at 160 s; 120 W comes back at 190 s, the instant its off_delay passes: the reading first, gelar goes on."""
      drive = purifier()
      drive.read(160, 1)
      drive.read(190, 120)
      drive.to(1000)
      assert drive.current == "gelar"
      assert drive.ended == []


  def test_at_one_instant_a_phase_ends_before_another_starts(ha: HomeAssistant) -> None:
      """gelar left for no band at 160 s (its end at 190); bebendo's on_delay passes at 190 too: gelar's end comes first."""
      drive = purifier()
      drive.read(160, 40)
      drive.read(185, 20)
      changes = drive.detector.advance(at(190), None)
      assert [(type(c).__name__, c.key) for c in changes] == [("Ended", "gelar"),
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
      assert restored.current == "gelar"
      assert restored.run("gelar").until == at(160)
      assert restored.seen == ["gelar"]
      # Its delays count again from the next reading, and the end stays
      assert restored.due() is None
      changes = restored.read(1000, at(200), None)
      assert changes == []
      changes = restored.advance(at(230), None)
      # gelar's end is confirmed 30 s after the first reading; quente, armed at 210, waited for it
      assert [(type(c).__name__, c.key) for c in changes] == [("Ended", "gelar"),
                                                               ("Started", "quente")]
      assert changes[0].cycle.end == at(160)
      assert changes[1].since == at(210)


  NAIVE = "2026-09-16T13:00:00"


  @pytest.mark.parametrize(("data", "on", "running", "seen"), [
      pytest.param({}, False, [], [], id="empty"),
      pytest.param({"program": None, "phases": {"gelar": {"since": None}}}, False, [], [],
                   id="a phase without the program"),
      pytest.param({"program": None, "seen": ["gone", 5, "gelar"]}, False, [], ["gelar"],
                   id="seen while stopped"),
      pytest.param({"program": "garbage"}, False, [], [], id="program not a map"),
      pytest.param({"program": {}, "seen": ["gelar"]}, False, [], ["gelar"],
                   id="program without a start"),
      pytest.param({"program": {"since": NAIVE}}, False, [], [], id="program's start without a zone"),
      pytest.param({"program": {"since": "2026-02-30T10:00:00+00:00"}, "seen": ["gelar"]},
                   False, [], ["gelar"], id="program's impossible date"),
      pytest.param({"program": {"since": T0.isoformat()},
                    "phases": {"gelar": {"since": "2026-13-45T00:00:00+00:00",
                                         "until": "2026-02-30T10:00:00+00:00"}},
                    "order": ["gelar"], "seen": ["gelar"]}, True, ["gelar"], ["gelar"],
                   id="a phase's impossible dates"),
      pytest.param({"program": {"since": T0.isoformat()}, "phases": {"gone": {"since": T0.isoformat()}},
                    "order": ["gone", 5], "seen": ["gone", "gelar"]}, True, [], ["gelar"],
                   id="a phase no longer configured"),
      pytest.param({"program": {"since": T0.isoformat()}, "phases": {"gelar": {}},
                    "order": [["x"], "gelar"], "seen": [["x"], "gelar"]}, True, ["gelar"], ["gelar"],
                   id="keys not strings"),
      pytest.param({"program": {"since": T0.isoformat()},
                    "phases": {"gelar": {"since": NAIVE, "until": NAIVE}},
                    "order": ["gelar"], "seen": ["gelar"]}, True, ["gelar"], ["gelar"],
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
                        "phases": {"gelar": {"until": at(60).isoformat()}},
                        "order": ["gelar", "gelar"], "seen": ["gelar"]})
      assert detector.running == ["gelar"]
      assert detector.end_so_far(detector.run("gelar")) == at(60)
      changes = detector.read(1, at(100), None)
      changes += detector.advance(at(130), None)
      assert [(c.key, c.cycle.start, c.cycle.end) for c in changes] == [("gelar", None, at(60))]


  # --- a real day of a water purifier (anonymised) ----------------------------------

  PURIFIER: dict[str, Any] = {
      "above": 2.9, "on_delay": {"seconds": 1}, "off_delay": {"minutes": 1},
      "phases": {
          "dispensing": {"name": "Beber água", "above": 2.9, "below": 4,
                         "on_delay": {"seconds": 1}, "off_delay": {"minutes": 1}},
          "cooling": {"name": "Gelar", "above": 4, "below": 150,
                      "on_delay": {"seconds": 10}, "off_delay": {"minutes": 3}},
          "heating": {"name": "Esquentar", "above": 150, "below": 400,
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
      """Each drink, chill and heating its own cycle, as today's modes count them; no `other`."""
      ended = replay("purifier_day.csv")
      assert Counter(key for key, *_ in ended) == {
          None: 33, "dispensing": 14, "cooling": 21, "heating": 2}


  @pytest.mark.usefixtures("ha")
  def test_the_heating_at_10_10_is_not_truncated() -> None:
      """10:10 UTC: a 3m39s plateau from 10:10:20, 48 s after a chill's tail.

      Recorded from its on_delay (10:10:50) to when it left (10:13:59): 189 s.
      An older replay of the modes recorded ~69 s, the rest credited to cooling.
      """
      heatings = [(start, end) for key, start, end in replay("purifier_day.csv") if key == "heating"]
      start, end = heatings[-1]
      assert start == datetime(2020, 1, 1, 10, 10, 50, 569000, tzinfo=UTC)
      assert end == datetime(2020, 1, 1, 10, 13, 59, 899000, tzinfo=UTC)
  ```

- [ ] **Step 3: Run them: RED.**

  ```sh
  uv run pytest tests/test_program.py -n 0 -q
  ```

  Expected: `85 failed`, each with `ModuleNotFoundError: No module named 'custom_components.pururu.features.cycle.program'`.

- [ ] **Step 4: The schema.** Create `custom_components/pururu/features/cycle/program/schema.py`:

  ```python
  """A detected program's block, and the program it describes: a band of a reading, and its phases."""

  from collections.abc import Mapping
  from dataclasses import dataclass
  from datetime import timedelta
  from typing import Any

  import voluptuous as vol

  from homeassistant.const import Platform
  from homeassistant.helpers import config_validation as cv

  from ....core.feature import TEXT, Item, bounded, finite_float
  from ....core.roles import Counters
  from ..last import LAST_CYCLE

  # The current phase while none runs
  IDLE = "idle"
  # The built-in phase: the program runs outside every configured phase's band
  OTHER = "other"
  # Every phase's entity keys start with it: phase_<key>, phase_<key>_<suffix>
  PHASE = "phase"
  # other's delays when `other:` doesn't set them: a chill's 2-s spike is no phase
  OTHER_DELAY = timedelta(seconds=30)

  # A phase's cycle entities: phase_<key>_<suffix>
  SUFFIXES: dict[str, Platform] = {
      **{description.key: Platform.SENSOR for description in LAST_CYCLE},
      "cycles_total": Platform.SENSOR,
      "runtime_total": Platform.SENSOR,
      "energy_total": Platform.SENSOR,
  }
  # The detector's own entity keys; the program's carrier is its builder's (the appliance's `running`)
  FIXED: dict[str, Platform] = {
      f"{PHASE}_current": Platform.SENSOR,
      f"{PHASE}_last": Platform.SENSOR,
  }
  # The translation key of each entity the detector names, once for every builder,
  # outside every namespace. A configured phase's binary sensor is named by its
  # `name`; its cycle entities by phase_<suffix> with {item}; other's by phase_other*.
  NAMED: dict[str, Platform] = {
      **FIXED,
      f"{PHASE}_{OTHER}": Platform.BINARY_SENSOR,
      **{f"{PHASE}_{suffix}": platform for suffix, platform in SUFFIXES.items()},
      **{f"{PHASE}_{OTHER}_{suffix}": platform for suffix, platform in SUFFIXES.items()},
  }
  # Each phase's totals, for the statistics aspect to meter (D2 mounts it); energy needs `energy`
  COUNTERS = Counters({"runtime": None, "cycles": None, "energy": "energy"})


  def phase_keys(key: str) -> dict[str, Platform]:
      """Every entity key phase `key` can create: its binary sensor, then its cycle entities."""
      slug = f"{PHASE}_{key}"
      return {
          slug: Platform.BINARY_SENSOR,
          **{f"{slug}_{suffix}": platform for suffix, platform in SUFFIXES.items()},
      }


  def _reserved(phases: dict[str, Any]) -> dict[str, Any]:
      """Refuse idle (the current phase while none runs) and other (the built-in phase) as keys."""
      for key in (IDLE, OTHER):
          if key in phases:
              raise vol.Invalid(
                  f"{key} is a reserved phase key: name the phase otherwise"
              )
      return phases


  def _apart(phases: dict[str, Any]) -> dict[str, Any]:
      """Refuse a phase whose entity key another phase, other or the detector already creates.

      other's keys are claimed first: a configured phase colliding with them is the one named.
      """
      owners = dict.fromkeys(FIXED, "")
      for key in (OTHER, *phases):
          for entity_key in phase_keys(key):
              owner = owners.setdefault(entity_key, key)
              if owner != key:
                  taken = f"phase {owner}'s" if owner else "the detector's"
                  raise vol.Invalid(f"phase {key} would create {entity_key}, {taken}")
      return phases


  def _delays(default: timedelta) -> dict[vol.Marker, Any]:
      """on_delay and off_delay, `default` when absent."""
      return {
          vol.Optional("on_delay", default=default): cv.positive_time_period,
          vol.Optional("off_delay", default=default): cv.positive_time_period,
      }


  # A band of the reading: above, below or both (bounded)
  BAND: dict[vol.Marker, Any] = {
      vol.Optional("above"): finite_float,
      vol.Optional("below"): finite_float,
  }
  # A phase is a program without phases (and without statistics until D2 mounts them)
  PHASE_SCHEMA = vol.All(
      vol.Schema({vol.Required("name"): TEXT, **BAND, **_delays(timedelta(0))}),
      bounded("phase"),
  )


  def _other_needs_phases(program: dict[str, Any]) -> dict[str, Any]:
      if OTHER in program and "phases" not in program:
          raise vol.Invalid(
              f"{OTHER} is the program outside every phase: it needs phases"
          )
      return program


  # A schema of its own at each level: ALLOW_EXTRA would let a key that isn't a slug through
  SCHEMA = vol.All(
      vol.Schema(
          {
              vol.Optional("name"): TEXT,
              **BAND,
              **_delays(timedelta(0)),
              vol.Optional("phases"): vol.All(
                  vol.Schema({cv.slug: PHASE_SCHEMA}),
                  vol.Length(min=1),
                  _reserved,
                  _apart,
              ),
              vol.Optional(OTHER): vol.Schema(_delays(OTHER_DELAY)),
          }
      ),
      bounded("program"),
      _other_needs_phases,
  )


  @dataclass(frozen=True, kw_only=True)
  class Band:
      """A band of the reading, its cycles confirmed by on_delay and off_delay."""

      above: float | None = None
      below: float | None = None
      on_delay: timedelta = timedelta(0)
      off_delay: timedelta = timedelta(0)

      def holds(self, value: float) -> bool:
          """Strictly above `above` and strictly below `below`, as HA's numeric_state."""
          return (self.above is None or value > self.above) and (
              self.below is None or value < self.below
          )


  @dataclass(frozen=True, kw_only=True)
  class Phase:
      """A stage of the program's cycle: a band, or other.

      other's band has no bounds, only delays: it holds for any value. The
      detector holds other in the program's band outside every phase's.
      """

      key: str
      name: str
      band: Band

      @property
      def item(self) -> Item:
          """Its entity keys' item: phase_<key>_<suffix>."""
          return Item(slug=f"{PHASE}_{self.key}", name=self.name)

      @property
      def other(self) -> bool:
          """Whether it is the built-in other."""
          return self.key == OTHER


  @dataclass(frozen=True, kw_only=True)
  class Program:
      """A detected program: its band, and its phases (the configured ones in order, then other)."""

      band: Band
      phases: tuple[Phase, ...] = ()


  def _band(block: Mapping[str, Any]) -> Band:
      return Band(
          above=block.get("above"),
          below=block.get("below"),
          on_delay=block["on_delay"],
          off_delay=block["off_delay"],
      )


  def program_of(config: Mapping[str, Any]) -> Program:
      """The program of a block SCHEMA validated: other comes with the first phase."""
      phases = [
          Phase(key=key, name=phase["name"], band=_band(phase))
          for key, phase in config.get("phases", {}).items()
      ]
      if phases:
          other = config.get(OTHER, {"on_delay": OTHER_DELAY, "off_delay": OTHER_DELAY})
          # other's band has no bounds: only its delays count; `Detector.read` decides where it holds.
          # Its name is only its item's: its entities are named by their own translations
          phases.append(Phase(key=OTHER, name=OTHER, band=Band(**other)))
      return Program(band=_band(config), phases=tuple(phases))
  ```

- [ ] **Step 5: The detector.** Create `custom_components/pururu/features/cycle/program/detector.py`:

  ```python
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
          changes = self._pass(now, kwh, at_now=False)
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
  ```

  Create `custom_components/pururu/features/cycle/program/__init__.py`:

  ```python
  """A detected program: a band of a reading with delays, and its phases, each a band too (spec Part 4).

  `schema` validates a program's block and describes it (`Program`); `detector`
  is pure: readings and time in, cycles out.
  """

  from .detector import Change, Detector, Ended, Run, Started
  from .schema import (
      COUNTERS,
      FIXED,
      IDLE,
      NAMED,
      OTHER,
      OTHER_DELAY,
      PHASE,
      SCHEMA,
      SUFFIXES,
      Band,
      Phase,
      Program,
      phase_keys,
      program_of,
  )

  __all__ = [
      "COUNTERS",
      "FIXED",
      "IDLE",
      "NAMED",
      "OTHER",
      "OTHER_DELAY",
      "PHASE",
      "SCHEMA",
      "SUFFIXES",
      "Band",
      "Change",
      "Detector",
      "Ended",
      "Phase",
      "Program",
      "Run",
      "Started",
      "phase_keys",
      "program_of",
  ]
  ```

- [ ] **Step 6: GREEN.**

  ```sh
  uv run pytest tests/test_program.py -n 0 -q --cov=custom_components/pururu/features/cycle/program --cov-report=term-missing
  ```

  Expected: `85 passed`; `schema.py`, `detector.py` and `__init__.py` at 100%. If a scenario fails, the detector is wrong, not the scenario. Each scenario is today's modes or phases test with the same readings: compare with `tests/test_modes.py` / `tests/test_phases.py`, which stay unchanged and passing.

- [ ] **Step 7: The whole suite.**

  ```sh
  uv run pytest -q
  ```

  Expected: `1283 passed` (217bb52's 1198, plus 85). `test_code.py` passes: ruff, ruff format, mypy strict, and the layer table (`features/cycle/program/` imports only `core/` and its own package, `features/cycle`).

- [ ] **Step 8: Commit, push, open the draft PR.**

  ```sh
  git add custom_components/pururu/features/cycle/program tests/test_program.py tests/fixtures/purifier_day.csv
  git commit -m "pururu: the detector of detected programs, alone (refactor D1)

  features/cycle/program: the detected Program's schema and a pure Detector
  (bands with on_delay/off_delay, overlap allowed, the dip wait, the idle-gap
  end, the built-in other), tested on today's modes and phases scenarios and
  on a real purifier day (anonymised).

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM"
  git push -u origin refactor/d1-detector --force-with-lease
  gh pr create --draft --base main --title "pururu: refactor D1, the detector of detected programs (0.2.0)" --body-file <scratchpad>/pr.md
  ```

  (`--force-with-lease`: Step 0's rebase rewrote the spec commit, if the branch was pushed before.) The PR body says:
  - what D1 is, and that nothing user-visible changes;
  - the Rulings, in short;
  - the 10:10 finding (ruling 19).

  It ends with:

  ```
  🤖 Generated with [Claude Code](https://claude.com/claude-code)

  https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM
  ```

  Then wait for `gh pr view <n> --json headRefOid -q .headRefOid` to equal `git rev-parse HEAD`, and add `claude-review`.

---

### Task 2: The entities

The detector in HA: the carrier, per phase a binary sensor and its cycle entities, `phase_current` and `phase_last`. They are tested through a test-only builder in the appliance's namespace, so their entity IDs are D2's.

**Files:**
- Create `custom_components/pururu/features/cycle/program/entities.py`.
- Modify `custom_components/pururu/features/cycle/program/__init__.py` (export `build`), `features/cycle/last.py` and `features/cycle/totals.py` (an optional `translation=`).
- Create `tests/test_program_entities.py`.
- Modify `tests/test_cycle.py` (one test).

**Interfaces:**

Consumes:
- Task 1's `schema` and `detector`.
- `features/cycle`: `CycleSource` (`_cycle_signals`, `_send`), `cycle_signal`, `Cycle`; `energy.kwh_now`; `last.LastCycleValue`, `LAST_CYCLE`; `totals.CyclesTotal`, `RuntimeTotal`, `EnergyTotal`.
- `core/entity.py`: `PururuEntity._identify(device, platform, entity_key, name=None, *, item=None, translation=None)`, `reading(state)`.
- `core/feature.py`: `Device`.

Produces:

```python
# features/cycle/last.py, totals.py: one more keyword, default None (as today)
LastCycleValue(device, description, *, source, item=None, translation=None)
CyclesTotal(device, *, source, item=None, entity_key="cycles_total", translation=None)
EnergyTotal(device, *, source, item=None, translation=None)
RuntimeTotal(device, watched, state, *, source, item=None, entity_key="runtime_total", translation=None)

# features/cycle/program/entities.py (build re-exported by the package)
type View = Callable[[list[Change]], None]
class Carrier(CycleSource, BinarySensorEntity, RestoreEntity):
    def __init__(self, device: Device, key: str, *, program: Program, reading: str, energy: str | None) -> None
    detector: Detector
    ready: bool                                   # the detector restored
    def subscribe(self, view: View) -> CALLBACK_TYPE
class PhaseRunning(CycleSource, BinarySensorEntity)          # phase_<key>
class PhaseCurrent(PururuEntity, SensorEntity, RestoreEntity)  # phase_current
class PhaseLast(PururuEntity, RestoreSensor)                   # phase_last
def build(hass: HomeAssistant, device: Device, program: Program, *, key: str,
          reading: str, energy: str | None) -> list[PururuEntity]
```

- [ ] **Step 1: The failing test for `translation=`.** Append to `tests/test_cycle.py`:

  ```python
  def test_a_cycle_entity_takes_a_translation(ha: HomeAssistant) -> None:
      """The detector names a phase's cycle entities with its own keys ({item}); without one, the builder's namespace as today."""
      feature = module("core.feature")
      last, totals = module("features.cycle.last"), module("features.cycle.totals")
      device = feature.Device(key="dev", name="Dev", namespace="appliance")
      item = feature.Item(slug="phase_gelar", name="Gelar")
      named = [
          last.LastCycleValue(device, last.LAST_CYCLE[0], source="phase_gelar", item=item,
                              translation="phase_last_cycle_start"),
          totals.CyclesTotal(device, source="phase_gelar", item=item,
                             translation="phase_cycles_total"),
          totals.RuntimeTotal(device, None, "on", source="phase_gelar", item=item,
                              translation="phase_runtime_total"),
          totals.EnergyTotal(device, source="phase_gelar", item=item,
                             translation="phase_energy_total"),
      ]
      assert [(e.entity_id, e.translation_key, e.translation_placeholders) for e in named] == [
          (f"sensor.pururu_dev_appliance_phase_gelar_{suffix}", f"phase_{suffix}", {"item": "Gelar"})
          for suffix in ("last_cycle_start", "cycles_total", "runtime_total", "energy_total")
      ]
      plain = totals.CyclesTotal(device, source="running")
      assert (plain.entity_id, plain.translation_key) == (
          "sensor.pururu_dev_appliance_cycles_total", "appliance_cycles_total")
  ```

  ```sh
  uv run pytest tests/test_cycle.py -n 0 -q
  ```

  Expected: `1 failed, 4 passed`, with `TypeError: LastCycleValue.__init__() got an unexpected keyword argument 'translation'`.

- [ ] **Step 2: `translation=` on the cycle entities.** Apply:

  ```diff
  --- a/custom_components/pururu/features/cycle/last.py
  +++ b/custom_components/pururu/features/cycle/last.py
  @@ -68,11 +68,14 @@
           *,
           source: str,
           item: Item | None = None,
  +        translation: str | None = None,
       ) -> None:
  -        """Take `description`'s value from every cycle (of `item`) that `source` sends."""
  +        """Take `description`'s value from every cycle (of `item`) that `source` sends; named `translation` if given."""
           self.entity_description = description
           self.sources = (source,)
  -        self._identify(device, Platform.SENSOR, description.key, item=item)
  +        self._identify(
  +            device, Platform.SENSOR, description.key, item=item, translation=translation
  +        )
           self._signal = (
               end_signal(device, item)
               if description.written_last
  ```

  ```diff
  --- a/custom_components/pururu/features/cycle/totals.py
  +++ b/custom_components/pururu/features/cycle/totals.py
  @@ -45,10 +45,13 @@
           source: str,
           item: Item | None = None,
           entity_key: str = "cycles_total",
  +        translation: str | None = None,
       ) -> None:
           """Count the cycles (of `item`) that `source` sends, as `entity_key` (a door's openings)."""
           self.sources = (source,)
  -        self._identify(device, Platform.SENSOR, entity_key, item=item)
  +        self._identify(
  +            device, Platform.SENSOR, entity_key, item=item, translation=translation
  +        )
           self._signal = cycle_signal(device, item)  # only _watch reads it
           self._cycles = 0
   
  @@ -88,11 +91,18 @@
       _attr_suggested_display_precision = 3
   
       def __init__(
  -        self, device: Device, *, source: str, item: Item | None = None
  +        self,
  +        device: Device,
  +        *,
  +        source: str,
  +        item: Item | None = None,
  +        translation: str | None = None,
       ) -> None:
           """Add up the energy of the cycles (of `item`) that `source` sends."""
           self.sources = (source,)
  -        self._identify(device, Platform.SENSOR, "energy_total", item=item)
  +        self._identify(
  +            device, Platform.SENSOR, "energy_total", item=item, translation=translation
  +        )
           self._signal = cycle_signal(device, item)
           self._kwh = 0.0
   
  @@ -144,10 +154,13 @@
           source: str,
           item: Item | None = None,
           entity_key: str = "runtime_total",
  +        translation: str | None = None,
       ) -> None:
           """Add up the time `watched`, the entity of `source`, is in `state`, as `entity_key`."""
           self.sources = (source,)
  -        self._identify(device, Platform.SENSOR, entity_key, item=item)
  +        self._identify(
  +            device, Platform.SENSOR, entity_key, item=item, translation=translation
  +        )
           self._watched = watched
           self._state = state
           self._hours = 0.0
  ```

  ```sh
  uv run pytest tests/test_cycle.py -n 0 -q
  ```

  Expected: `5 passed`.

- [ ] **Step 3: The failing entity tests.** Create `tests/test_program_entities.py`:

  ```python
  """features/cycle/program's entities, in HA, through a test-only builder in the appliance's namespace.

  No feature uses the detector until D2: `detecting` swaps FEATURES["appliance"]
  for a builder whose block is `power`, `energy` and `running_program`, so the
  entity IDs are D2's: <platform>.pururu_<device>_appliance_phase_<key>_<suffix>.
  """

  from datetime import timedelta
  from typing import Any

  from homeassistant.const import Platform
  from homeassistant.core import HomeAssistant, State
  from homeassistant.helpers import config_validation as cv, entity_registry as er
  from homeassistant.helpers.dispatcher import async_dispatcher_connect
  from homeassistant.util import dt as dt_util
  import pytest
  import voluptuous as vol

  from helpers import capture, fake, held, module, reload, restart, setup, tick

  KEY = "demo_filter"
  POWER = "sensor.demo_plug_power"
  ENERGY = "sensor.demo_plug_energy"
  IDLE_W = 1.0
  PREFIX = f"pururu_{KEY}_appliance"
  RUNNING = f"binary_sensor.{PREFIX}_running"
  CURRENT = f"sensor.{PREFIX}_phase_current"
  LAST = f"sensor.{PREFIX}_phase_last"
  GELAR = f"binary_sensor.{PREFIX}_phase_gelar"
  QUENTE = f"binary_sensor.{PREFIX}_phase_quente"
  OTHER = f"binary_sensor.{PREFIX}_phase_other"
  RUNNING_PROGRAM: dict[str, Any] = {
      "above": 4, "on_delay": {"seconds": 20}, "off_delay": {"minutes": 2},
      "phases": {
          "gelar": {"name": "Gelar", "above": 40, "below": 300,
                    "on_delay": {"seconds": 30}, "off_delay": {"seconds": 30}},
          "quente": {"name": "Água quente", "above": 300,
                     "on_delay": {"seconds": 10}, "off_delay": {"seconds": 30}},
      },
  }
  DEVICES = {KEY: {"name": "Demo filter",
                   "appliance": {"power": POWER, "energy": ENERGY,
                                 "running_program": RUNNING_PROGRAM}}}
  LAST_CYCLE = ("last_cycle_start", "last_cycle_end", "last_cycle_duration", "last_cycle_energy")
  SUFFIXES = (*LAST_CYCLE, "cycles_total", "runtime_total", "energy_total")


  def builder() -> Any:
      """A builder reading `power` through the detector, as D2's appliance will; only for these tests."""
      program = module("features.cycle.program")

      def build(hass: HomeAssistant, device: Any, config: dict[str, Any],
                inputs: Any) -> list[Any]:
          return program.build(hass, device, program.program_of(config["running_program"]),
                               key="running", reading=config["power"],
                               energy=config.get("energy"))

      return module("core.feature").Feature(
          schema=vol.Schema({vol.Required("power"): cv.entity_id,
                             vol.Optional("energy"): cv.entity_id,
                             vol.Required("running_program"): program.SCHEMA}),
          entity_keys={"running": Platform.BINARY_SENSOR, **program.FIXED},
          build=build,
          example={"power": POWER, "running_program": {"above": 4}},
          namespace="appliance",
      )


  @pytest.fixture
  def detecting(ha: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> HomeAssistant:
      """`ha` with the test builder as the appliance."""
      monkeypatch.setitem(module("features").FEATURES, "appliance", builder())
      return ha


  @pytest.fixture
  async def purifier(detecting: HomeAssistant, freezer: Any) -> HomeAssistant:
      """Idle at 1 W, long enough to count as not running."""
      assert await setup(detecting, DEVICES)
      await watts(detecting, IDLE_W)
      await tick(detecting, freezer, 125)
      assert state(detecting, RUNNING) == "off"
      return detecting


  def state(hass: HomeAssistant, entity_id: str) -> str:
      found = hass.states.get(entity_id)
      assert found is not None, entity_id
      return found.state


  def sensor(entity_key: str) -> str:
      return f"sensor.{PREFIX}_{entity_key}"


  async def watts(hass: HomeAssistant, value: float | str) -> None:
      await fake(hass, POWER, str(value))


  async def kwh(hass: HomeAssistant, value: float | str) -> None:
      await fake(hass, ENERGY, str(value))


  async def cool(hass: HomeAssistant, freezer: Any) -> None:
      """The program runs at 20 s, gelar at 30 s."""
      await watts(hass, 120)
      await tick(hass, freezer, 35)
      assert state(hass, RUNNING) == "on"
      assert state(hass, CURRENT) == "gelar"


  # --- what it creates ----------------------------------------------------------------


  async def test_its_entities_and_their_ids(detecting: HomeAssistant) -> None:
      """The carrier under the builder's key, the current and last phase, and per phase (other too) its binary sensor and cycle entities."""
      assert await setup(detecting, DEVICES)
      phases = ("gelar", "quente", "other")
      assert held(detecting, KEY) == {
          RUNNING, CURRENT, LAST,
          *(f"binary_sensor.{PREFIX}_phase_{phase}" for phase in phases),
          *(sensor(f"phase_{phase}_{suffix}") for phase in phases for suffix in SUFFIXES),
      }
      registry = er.async_get(detecting)
      assert registry.async_get(GELAR).unique_id == f"{PREFIX}_phase_gelar"
      assert registry.async_get(sensor("phase_other_cycles_total")).unique_id == (
          f"{PREFIX}_phase_other_cycles_total")


  async def test_without_energy_no_energy_per_phase(detecting: HomeAssistant) -> None:
      appliance = {"power": POWER, "running_program": RUNNING_PROGRAM}
      assert await setup(detecting, {KEY: {"name": "Demo filter", "appliance": appliance}})
      assert detecting.states.get(sensor("phase_gelar_energy_total")) is None
      assert detecting.states.get(sensor("phase_gelar_last_cycle_energy")) is None
      assert detecting.states.get(sensor("phase_gelar_cycles_total")) is not None


  async def test_without_phases_only_the_carrier(detecting: HomeAssistant) -> None:
      appliance = {"power": POWER, "running_program": {"above": 4}}
      assert await setup(detecting, {KEY: {"name": "Demo filter", "appliance": appliance}})
      assert held(detecting, KEY) == {RUNNING}


  async def test_nothing_of_the_phases_when_the_carrier_is_not_created(
          detecting: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
      """The carrier's ID belongs to another integration: every phase entity follows it, so none is created."""
      er.async_get(detecting).async_get_or_create(
          "binary_sensor", "template", "someone_else", suggested_object_id=f"{PREFIX}_running")
      assert await setup(detecting, DEVICES)
      assert detecting.states.get(CURRENT) is None
      assert detecting.states.get(GELAR) is None
      assert detecting.states.get(sensor("phase_gelar_cycles_total")) is None
      errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
      assert any(GELAR in message and RUNNING in message for message in errors), errors


  # --- what they show -------------------------------------------------------------------


  async def test_idle_until_a_phase_starts(purifier: HomeAssistant) -> None:
      assert state(purifier, CURRENT) == "idle"
      assert purifier.states.get(CURRENT).attributes["options"] == ["idle", "gelar", "quente", "other"]
      assert purifier.states.get(CURRENT).attributes["running"] == []
      assert state(purifier, LAST) == "unknown"
      assert purifier.states.get(LAST).attributes["options"] == ["gelar", "quente", "other"]
      assert state(purifier, GELAR) == "off"


  async def test_a_phase_runs_and_ends(purifier: HomeAssistant, freezer: Any) -> None:
      await kwh(purifier, 100.0)
      await cool(purifier, freezer)
      started = dt_util.utcnow() - timedelta(seconds=5)
      assert state(purifier, GELAR) == "on"
      assert purifier.states.get(GELAR).attributes["cycle_start"] == started
      assert purifier.states.get(CURRENT).attributes["running"] == ["gelar"]
      assert purifier.states.get(CURRENT).attributes["seen"] == ["gelar"]
      await tick(purifier, freezer, 600)
      await kwh(purifier, 100.05)
      left = dt_util.utcnow()
      await watts(purifier, IDLE_W)
      assert purifier.states.get(GELAR).attributes["cycle_end"] == left
      await tick(purifier, freezer, 35)
      assert state(purifier, GELAR) == "off"
      assert state(purifier, CURRENT) == "idle"
      assert state(purifier, LAST) == "gelar"
      assert dt_util.parse_datetime(state(purifier, sensor("phase_gelar_last_cycle_start"))) == started
      assert dt_util.parse_datetime(state(purifier, sensor("phase_gelar_last_cycle_end"))) == left
      assert float(state(purifier, sensor("phase_gelar_last_cycle_duration"))) == pytest.approx(10.1, abs=0.1)
      assert float(state(purifier, sensor("phase_gelar_last_cycle_energy"))) == pytest.approx(0.05)
      assert state(purifier, sensor("phase_gelar_cycles_total")) == "1"
      assert float(state(purifier, sensor("phase_gelar_energy_total"))) == pytest.approx(0.05)
      assert float(state(purifier, sensor("phase_gelar_runtime_total"))) == pytest.approx(
          605 / 3600, abs=0.0005)
      assert state(purifier, sensor("phase_quente_cycles_total")) == "0"


  async def test_a_phases_cycle_is_sent_after_its_state_its_end_last(
          purifier: HomeAssistant, freezer: Any) -> None:
      """CycleSource's order: the binary sensor is off when each signal fires, the cycle's signal first; last_cycle_end written last."""
      cycle = module("features.cycle")
      feature = module("core.feature")
      device = feature.Device(key=KEY, name="Demo filter", namespace="appliance")
      item = feature.Item(slug="phase_gelar", name="Gelar")
      await cool(purifier, freezer)
      seen: list[tuple[str, str]] = []
      for name, signal in (("cycle", cycle.cycle_signal(device, item)),
                           ("end", cycle.end_signal(device, item))):
          async_dispatcher_connect(
              purifier, signal, lambda _cycle, name=name: seen.append((name, state(purifier, GELAR))))
      changes = capture(purifier, "state_changed")
      await watts(purifier, IDLE_W)
      await tick(purifier, freezer, 35)
      assert seen == [("cycle", "off"), ("end", "off")]
      watched = {LAST, *(sensor(f"phase_gelar_{key}") for key in LAST_CYCLE)}
      order = [event.data["entity_id"] for event in changes if event.data["entity_id"] in watched]
      assert order[-1] == sensor("phase_gelar_last_cycle_end"), order


  async def test_the_programs_cycle_is_sent_on_the_carriers_signals(
          purifier: HomeAssistant, freezer: Any) -> None:
      cycle = module("features.cycle")
      device = module("core.feature").Device(key=KEY, name="Demo filter", namespace="appliance")
      cycles: list[Any] = []
      async_dispatcher_connect(purifier, cycle.cycle_signal(device), cycles.append)
      await cool(purifier, freezer)
      left = dt_util.utcnow()
      await watts(purifier, IDLE_W)
      await tick(purifier, freezer, 125)
      assert state(purifier, RUNNING) == "off"
      assert [each.end for each in cycles] == [left]


  async def test_a_handover_never_shows_idle(purifier: HomeAssistant, freezer: Any) -> None:
      """gelar to quente after a dip: phase_current goes straight from gelar to quente."""
      await cool(purifier, freezer)
      changes = capture(purifier, "state_changed")
      await watts(purifier, 1000)
      await tick(purifier, freezer, 30)
      states = [event.data["new_state"].state for event in changes
                if event.data["entity_id"] == CURRENT
                and event.data["new_state"].state != event.data["old_state"].state]
      assert states == ["quente"], states
      assert state(purifier, LAST) == "gelar"
      assert (state(purifier, GELAR), state(purifier, QUENTE)) == ("off", "on")


  async def test_other_is_a_phase_with_its_entities(purifier: HomeAssistant, freezer: Any) -> None:
      """300 W is neither gelar's (below 300) nor quente's (above 300): other, after 30 s."""
      await watts(purifier, 300)
      await tick(purifier, freezer, 25)
      assert state(purifier, RUNNING) == "on"
      assert state(purifier, OTHER) == "off"
      await tick(purifier, freezer, 10)
      assert state(purifier, OTHER) == "on"
      assert state(purifier, CURRENT) == "other"
      await watts(purifier, 1000)
      await tick(purifier, freezer, 10)
      assert state(purifier, OTHER) == "off"
      assert state(purifier, CURRENT) == "quente"
      assert state(purifier, sensor("phase_other_cycles_total")) == "1"
      assert state(purifier, LAST) == "other"


  # --- restarts and reloads ------------------------------------------------------------


  def snapshot(since: str, **phases: dict[str, Any]) -> dict[str, Any]:
      return {"program": {"since": since, "since_energy": None, "until": None, "gap": False},
              "phases": {key: {"since_energy": None, "until": None, "gap": False, **run}
                         for key, run in phases.items()},
              "order": list(phases), "seen": list(phases)}


  async def test_a_restart_keeps_the_running_phase(detecting: HomeAssistant, freezer: Any) -> None:
      """The phase shows from the first write (no off in between) and counts from the restart, not from before."""
      since = (dt_util.utcnow() - timedelta(minutes=20)).isoformat()
      changes = capture(detecting, "state_changed")
      await restart(
          detecting, DEVICES,
          (State(RUNNING, "on"), snapshot(since, gelar={"since": since})),
          (State(GELAR, "on"), {}),
          (State(CURRENT, "gelar"), {}),
      )
      assert state(detecting, GELAR) == "on"
      assert state(detecting, CURRENT) == "gelar"
      shown = [event.data["new_state"].state for event in changes
               if event.data["entity_id"] in (GELAR, CURRENT)]
      assert "off" not in shown and "idle" not in shown, shown
      await watts(detecting, 120)
      await tick(detecting, freezer, 600)
      await watts(detecting, IDLE_W)
      await tick(detecting, freezer, 35)
      assert state(detecting, CURRENT) == "idle"
      assert float(state(detecting, sensor("phase_gelar_last_cycle_duration"))) == pytest.approx(
          30, abs=0.2)
      assert state(detecting, sensor("phase_gelar_cycles_total")) == "1"
      assert float(state(detecting, sensor("phase_gelar_runtime_total"))) == pytest.approx(
          600 / 3600, abs=0.0005)


  async def test_a_reload_mid_phase_counts_one_cycle(purifier: HomeAssistant, freezer: Any) -> None:
      await cool(purifier, freezer)
      started = dt_util.utcnow() - timedelta(seconds=5)
      await tick(purifier, freezer, 600)
      await reload(purifier, DEVICES)
      assert state(purifier, CURRENT) == "gelar"
      await tick(purifier, freezer, 600)
      await watts(purifier, IDLE_W)
      await tick(purifier, freezer, 35)
      assert state(purifier, sensor("phase_gelar_cycles_total")) == "1"
      assert dt_util.parse_datetime(state(purifier, sensor("phase_gelar_last_cycle_start"))) == started


  async def test_last_restores(detecting: HomeAssistant) -> None:
      await restart(detecting, DEVICES, (State(LAST, "quente"), {
          "native_value": "quente", "native_unit_of_measurement": None}))
      assert state(detecting, LAST) == "quente"
  ```

  ```sh
  uv run pytest tests/test_program_entities.py -n 0 -q
  ```

  Expected: `13 failed`: the package exports no `build` yet (`AttributeError: … has no attribute 'build'` when the builder builds, so no entity exists).

- [ ] **Step 4: The entities.** Create `custom_components/pururu/features/cycle/program/entities.py`:

  ```python
  """The detector in HA: the program's carrier, and its phases' entities showing it."""

  from collections.abc import Callable, Iterator
  from dataclasses import dataclass
  from datetime import datetime
  from functools import partial
  from typing import Any, override

  from homeassistant.components.binary_sensor import (
      BinarySensorDeviceClass,
      BinarySensorEntity,
  )
  from homeassistant.components.sensor import (
      RestoreSensor,
      SensorDeviceClass,
      SensorEntity,
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
  from homeassistant.helpers.dispatcher import async_dispatcher_connect
  from homeassistant.helpers.event import (
      async_track_point_in_utc_time,
      async_track_state_change_event,
  )
  from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
  from homeassistant.util import dt as dt_util

  from ....core.entity import PururuEntity, reading
  from ....core.feature import Device
  from .. import Cycle, CycleSource, cycle_signal
  from ..energy import kwh_now
  from ..last import LAST_CYCLE, LastCycleValue
  from ..totals import CyclesTotal, EnergyTotal, RuntimeTotal
  from .detector import Change, Detector, Ended
  from .schema import IDLE, OTHER, PHASE, Phase, Program

  type View = Callable[[list[Change]], None]


  @dataclass
  class Snapshot(ExtraStoredData):
      """The detector's snapshot, as .storage keeps it."""

      data: dict[str, Any]

      @override
      def as_dict(self) -> dict[str, Any]:
          """What .storage keeps."""
          return self.data


  class Carrier(CycleSource, BinarySensorEntity, RestoreEntity):
      """On while the program runs: it owns the detector, and the phases' entities show it.

      It follows the reading and waits for the detector's next delay. Each step
      writes its own state (sending the program's cycle when it ends), then calls
      each view (`subscribe`) with the step's changes.
      """

      _attr_device_class = BinarySensorDeviceClass.RUNNING

      def __init__(
          self,
          device: Device,
          key: str,
          *,
          program: Program,
          reading: str,
          energy: str | None,
      ) -> None:
          """`program` read from `reading`, as `key` of `device`; `energy` gives each cycle's kWh."""
          self._identify(device, Platform.BINARY_SENSOR, key)
          self._cycle_signals(device)
          self.detector = Detector(program)
          self._reading = reading
          self._energy = energy
          self._views: list[View] = []
          # Whether the detector holds what was restored: until then, a view shows its own
          self.ready = False
          self._timer: CALLBACK_TYPE | None = None

      @property
      @override
      def is_on(self) -> bool:
          """Whether the program runs."""
          return self.detector.on

      @property
      @override
      def extra_restore_state_data(self) -> Snapshot:
          """Every running cycle, and the phases seen."""
          return Snapshot(self.detector.snapshot())

      @property
      @override
      def extra_state_attributes(self) -> dict[str, Any] | None:
          """The running cycle's start, and its end while off_delay runs: the appliance's `running`'s."""
          if (run := self.detector.run(None)) is None:
              return None
          attributes: dict[str, Any] = {}
          if run.since is not None:
              attributes["cycle_start"] = run.since
          if run.until is not None:
              attributes["cycle_end"] = run.until
          return attributes or None

      @callback
      def subscribe(self, view: View) -> CALLBACK_TYPE:
          """Call `view` with each step's changes, after the carrier's own; returns the unsubscribe."""
          self._views.append(view)
          return partial(self._views.remove, view)

      @override
      async def async_added_to_hass(self) -> None:
          """Restore the detector, then follow the reading from its current state."""
          await super().async_added_to_hass()
          if (extra := await self.async_get_last_extra_data()) is not None:
              self.detector.restore(extra.as_dict())
          self.ready = True
          self.async_on_remove(
              async_track_state_change_event(
                  self.hass, self._reading, self._reading_changed
              )
          )
          self.async_on_remove(self._cancel_timer)
          self._step(self._read(self.hass.states.get(self._reading)))

      def _read(self, state: State | None) -> list[Change]:
          return self.detector.read(
              reading(state), dt_util.utcnow(), kwh_now(self.hass, self._energy)
          )

      @callback
      def _reading_changed(self, event: Event[EventStateChangedData]) -> None:
          self._step(self._read(event.data["new_state"]))

      @callback
      def _delay_passed(self, _now: datetime) -> None:
          self._timer = None
          self._step(
              self.detector.advance(dt_util.utcnow(), kwh_now(self.hass, self._energy))
          )

      @callback
      def _cancel_timer(self) -> None:
          if self._timer is not None:
              self._timer()
              self._timer = None

      @callback
      def _step(self, changes: list[Change]) -> None:
          """Show a step: the carrier's state (and the program's cycle), then each view; then wait for the next delay."""
          ended = next(
              (c.cycle for c in changes if isinstance(c, Ended) and c.key is None), None
          )
          if ended is not None:
              self._send(ended)
          else:
              self.async_write_ha_state()
          for view in list(self._views):
              view(changes)
          self._cancel_timer()
          if (due := self.detector.due()) is not None:
              self._timer = async_track_point_in_utc_time(
                  self.hass, self._delay_passed, due
              )


  class PhaseRunning(CycleSource, BinarySensorEntity):
      """On while its phase runs: the source of the phase's cycles.

      Added after the carrier on the same platform, so the detector is restored
      by then: its first state is already the restored one.
      """

      _attr_device_class = BinarySensorDeviceClass.RUNNING

      def __init__(
          self, device: Device, carrier: Carrier, phase: Phase, *, source: str
      ) -> None:
          """Show `phase` of `carrier`'s detector; `source`: the carrier's entity key."""
          item = phase.item
          if phase.other:
              self._identify(
                  device,
                  Platform.BINARY_SENSOR,
                  item.slug,
                  translation=f"{PHASE}_{OTHER}",
              )
          else:
              self._identify(device, Platform.BINARY_SENSOR, item.slug, name=phase.name)
          self.sources = (source,)
          self._cycle_signals(device, item)
          self._carrier = carrier
          self._key = phase.key

      @property
      @override
      def is_on(self) -> bool:
          """Whether its phase runs."""
          return self._carrier.detector.run(self._key) is not None

      @property
      @override
      def extra_state_attributes(self) -> dict[str, Any] | None:
          """The running cycle's start, and its end should it end now."""
          detector = self._carrier.detector
          if (run := detector.run(self._key)) is None:
              return None
          attributes: dict[str, Any] = {}
          if run.since is not None:
              attributes["cycle_start"] = run.since
          if (end := detector.end_so_far(run)) is not None:
              attributes["cycle_end"] = end
          return attributes or None

      @override
      async def async_added_to_hass(self) -> None:
          """Show each step of the carrier's."""
          await super().async_added_to_hass()
          self.async_on_remove(self._carrier.subscribe(self._changed))

      @callback
      def _changed(self, changes: list[Change]) -> None:
          """Its phase's cycle ended: the state, then its signals; else the state."""
          ended = next(
              (c.cycle for c in changes if isinstance(c, Ended) and c.key == self._key),
              None,
          )
          if ended is not None:
              self._send(ended)
          else:
              self.async_write_ha_state()


  class PhaseCurrent(PururuEntity, SensorEntity, RestoreEntity):
      """The phase that started last among those running, or idle; those running and seen as attributes."""

      _attr_device_class = SensorDeviceClass.ENUM

      def __init__(self, device: Device, carrier: Carrier, *, source: str) -> None:
          """Show `carrier`'s detector; `source`: the carrier's entity key."""
          self._identify(
              device, Platform.SENSOR, f"{PHASE}_current", translation=f"{PHASE}_current"
          )
          self.sources = (source,)
          self._carrier = carrier
          phases = carrier.detector.program.phases
          self._options = [IDLE, *(phase.key for phase in phases)]
          self._attr_options = self._options
          self._restored = IDLE

      @property
      @override
      def native_value(self) -> str:
          """The current phase; the restored one until the carrier restored the detector (another platform may add it first)."""
          if not self._carrier.ready:
              return self._restored
          return self._carrier.detector.current

      @property
      @override
      def extra_state_attributes(self) -> dict[str, Any]:
          """The running phases, and those the program's current or last cycle saw, in the configuration's order."""
          detector = self._carrier.detector
          return {"running": detector.running, "seen": detector.seen}

      @override
      async def async_added_to_hass(self) -> None:
          """Take the restored phase, then show each step of the carrier's."""
          await super().async_added_to_hass()
          last = await self.async_get_last_state()
          if last is not None and last.state in self._options:
              self._restored = last.state
          self.async_on_remove(self._carrier.subscribe(self._changed))

      @callback
      def _changed(self, _changes: list[Change]) -> None:
          self.async_write_ha_state()


  class PhaseLast(PururuEntity, RestoreSensor):
      """The phase of the last phase cycle that ended; it changes only when one ends."""

      _attr_device_class = SensorDeviceClass.ENUM

      def __init__(self, device: Device, program: Program, *, source: str) -> None:
          """Take the phase of every cycle `program`'s phases send; `source`: the carrier's entity key."""
          self._identify(
              device, Platform.SENSOR, f"{PHASE}_last", translation=f"{PHASE}_last"
          )
          self.sources = (source,)
          self._device = device
          self._phases = program.phases
          self._options = [phase.key for phase in program.phases]
          self._attr_options = self._options

      @override
      async def async_added_to_hass(self) -> None:
          """Restore the last phase, then wait for the next phase cycle."""
          await super().async_added_to_hass()
          last = await self.async_get_last_sensor_data()
          if last is not None and last.native_value in self._options:
              self._attr_native_value = last.native_value
          for phase in self._phases:
              self.async_on_remove(
                  async_dispatcher_connect(
                      self.hass,
                      cycle_signal(self._device, phase.item),
                      partial(self._record, phase.key),
                  )
              )

      @callback
      def _record(self, key: str, _cycle: Cycle) -> None:
          self._attr_native_value = key
          self.async_write_ha_state()


  def _translation(phase: Phase, suffix: str) -> str:
      """What a phase's cycle entity is named under: phase_<suffix> with {item}, or other's own."""
      return f"{PHASE}_{OTHER}_{suffix}" if phase.other else f"{PHASE}_{suffix}"


  def _cycle_entities(
      hass: HomeAssistant, device: Device, phase: Phase, energy: str | None
  ) -> Iterator[PururuEntity]:
      """A phase's last cycle and totals, its energy with `energy`, all following its binary sensor."""
      item = phase.item
      source = item.slug
      for description in LAST_CYCLE:
          if energy is not None or description.key != "last_cycle_energy":
              yield LastCycleValue(
                  device,
                  description,
                  source=source,
                  item=item,
                  translation=_translation(phase, description.key),
              )
      yield CyclesTotal(
          device,
          source=source,
          item=item,
          translation=_translation(phase, "cycles_total"),
      )
      yield RuntimeTotal(
          device,
          device.current_entity_id(hass, Platform.BINARY_SENSOR, source),
          STATE_ON,
          source=source,
          item=item,
          translation=_translation(phase, "runtime_total"),
      )
      if energy is not None:
          yield EnergyTotal(
              device,
              source=source,
              item=item,
              translation=_translation(phase, "energy_total"),
          )


  def build(
      hass: HomeAssistant,
      device: Device,
      program: Program,
      *,
      key: str,
      reading: str,
      energy: str | None,
  ) -> list[PururuEntity]:
      """The program's carrier as `key`; with phases, the current and last phase and each phase's entities.

      The carrier comes first: its platform adds it, and it restores the
      detector, before the phases' binary sensors.
      """
      carrier = Carrier(device, key, program=program, reading=reading, energy=energy)
      entities: list[PururuEntity] = [carrier]
      if not program.phases:
          return entities
      entities.append(PhaseCurrent(device, carrier, source=key))
      entities.append(PhaseLast(device, program, source=key))
      for phase in program.phases:
          entities.append(PhaseRunning(device, carrier, phase, source=key))
          entities.extend(_cycle_entities(hass, device, phase, energy))
      return entities
  ```

  Replace `custom_components/pururu/features/cycle/program/__init__.py` with (the docstring names `entities`; `build` is exported):

  ```python
  """A detected program: a band of a reading with delays, and its phases, each a band too (spec Part 4).

  `schema` validates a program's block and describes it (`Program`); `detector`
  is pure (readings and time in, cycles out); `entities` puts it in HA: the
  program's carrier, and per phase a binary sensor and its cycle entities. A
  builder reading a sensor calls `build` (D2: the appliance's `running_program`).
  """

  from .detector import Change, Detector, Ended, Run, Started
  from .entities import build
  from .schema import (
      COUNTERS,
      FIXED,
      IDLE,
      NAMED,
      OTHER,
      OTHER_DELAY,
      PHASE,
      SCHEMA,
      SUFFIXES,
      Band,
      Phase,
      Program,
      phase_keys,
      program_of,
  )

  __all__ = [
      "COUNTERS",
      "FIXED",
      "IDLE",
      "NAMED",
      "OTHER",
      "OTHER_DELAY",
      "PHASE",
      "SCHEMA",
      "SUFFIXES",
      "Band",
      "Change",
      "Detector",
      "Ended",
      "Phase",
      "Program",
      "Run",
      "Started",
      "build",
      "phase_keys",
      "program_of",
  ]
  ```

- [ ] **Step 5: GREEN, and the whole suite.**

  ```sh
  uv run pytest tests/test_program_entities.py tests/test_cycle.py -n 0 -q --cov=custom_components/pururu/features/cycle --cov-report=term-missing
  uv run pytest -q
  ```

  Expected: `18 passed`, `features/cycle/program/entities.py` at 100%. Then `1297 passed` (1283 + 13 + 1).

  The entities have no names yet (Task 3): HA names them after the device alone, and no test here reads a name.

- [ ] **Step 6: The restart's order, by perturbation.** `test_a_restart_keeps_the_running_phase` must catch a `PhaseRunning` added before the carrier. Change `build`'s last line to `return [*entities[1:], carrier]` (the carrier last), run the test, and put the file back:

  ```sh
  cp custom_components/pururu/features/cycle/program/entities.py <scratchpad>/entities.py.keep
  # edit build(): return [*entities[1:], carrier]
  uv run pytest "tests/test_program_entities.py::test_a_restart_keeps_the_running_phase" -n 0 -q
  cp <scratchpad>/entities.py.keep custom_components/pururu/features/cycle/program/entities.py
  ```

  Expected: `1 failed` with `assert ('off' not in ['off', 'on', 'gelar'])`, then the file back as it was.

- [ ] **Step 7: Commit and push.**

  ```sh
  git add custom_components/pururu/features/cycle tests/test_program_entities.py tests/test_cycle.py
  git commit -m "pururu: the detector's entities, on CycleSource (refactor D1)

  The carrier owns the detector and restores it; per phase a binary sensor
  (phase_<key>, a CycleSource) and its cycle entities, phase_current and
  phase_last, in the builder's namespace. The cycle entities take a
  translation of their own. Tested through a test-only builder in the
  appliance's namespace: D2's entity IDs.

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM"
  git push
  ```

  Wait for `headRefOid`, then `claude-review`.

---

### Task 3: Names and the contract

The detector's translation keys (`NAMED`), in both languages and with icons. The contract test counts them as created and checks each.

**Files:**
- Modify `custom_components/pururu/translations/en.json`, `translations/pt-BR.json`, `icons.json`.
- Modify `tests/test_features.py` (one test extended, one added).
- Modify `tests/test_program_entities.py` (the names).

**Interfaces:** Consumes `program.NAMED`, `SUFFIXES`, `PHASE`, `IDLE`, `OTHER` (Task 1). Produces the translation keys below; nothing in code.

- [ ] **Step 1: The failing tests.**

  In `tests/test_features.py`, replace `test_every_translated_entity_key_is_created` with the following, which adds `test_the_detectors_keys_are_named` after it:

  ```python
  def test_every_translated_entity_key_is_created(features: dict[str, Any]) -> None:
      """A name or an icon under a key no feature creates is left over, as from before namespaces."""
      qualified = module("core.feature").qualified
      created = {(str(platform), qualified(feature.namespace, entity_key))
                 for feature in features.values()
                 for entity_key, platform in named_keys(feature).items()}
      created |= {(str(platform), group) for aspect, _, feature in offered(features)
                  for group, platform in aspect_groups(aspect, feature).items()}
      # The detector's (features/cycle/program): named once for every builder using it
      created |= {(str(platform), key)
                  for key, platform in module("features.cycle.program").NAMED.items()}
      for name in ("translations/en.json", "icons.json"):
          listed = {(platform, key) for platform, keys in load(name)["entity"].items() for key in keys}
          assert listed <= created, f"{name}: {sorted(listed - created)}"


  def test_the_detectors_keys_are_named(ha: HomeAssistant) -> None:
      """Each key the detector names, in both languages and with an icon: a phase's own with {item}, other's and its own two without.

      The states it shows by itself are named too: idle (the current phase only) and other.
      """
      program = module("features.cycle.program")
      en, pt, icons = load("translations/en.json"), load("translations/pt-BR.json"), load("icons.json")
      per_phase = {f"{program.PHASE}_{suffix}" for suffix in program.SUFFIXES}
      for key, platform in program.NAMED.items():
          for translations in (en, pt):
              text = translations["entity"][platform][key]["name"]
              assert text, key
              assert ("{item}" in text) == (key in per_phase), key
          assert icons["entity"][platform][key]["default"].startswith("mdi:"), key
      for translations in (en, pt):
          sensors = translations["entity"]["sensor"]
          assert {program.IDLE, program.OTHER} <= set(sensors["phase_current"]["state"])
          assert program.OTHER in sensors["phase_last"]["state"]
          assert program.IDLE not in sensors["phase_last"]["state"]
  ```

  Append to `tests/test_program_entities.py`:

  ```python
  # --- names ------------------------------------------------------------------------------

  NAMES = {
      "en": {GELAR: "Demo filter Gelar", OTHER: "Demo filter Other phase",
             CURRENT: "Demo filter Phase", LAST: "Demo filter Last phase",
             sensor("phase_quente_cycles_total"): "Demo filter Água quente cycles",
             sensor("phase_gelar_last_cycle_start"): "Demo filter Gelar last cycle start",
             sensor("phase_other_runtime_total"): "Demo filter Other phase runtime"},
      "pt-BR": {GELAR: "Demo filter Gelar", OTHER: "Demo filter Outra fase",
                CURRENT: "Demo filter Fase", LAST: "Demo filter Última fase",
                sensor("phase_quente_cycles_total"): "Demo filter Ciclos de Água quente",
                sensor("phase_gelar_last_cycle_start"): "Demo filter Início do último ciclo de Gelar",
                sensor("phase_other_runtime_total"): "Demo filter Tempo de outra fase"},
  }


  @pytest.mark.parametrize("language", ["en", "pt-BR"])
  async def test_names(detecting: HomeAssistant, language: str) -> None:
      """A phase's binary sensor is its name; its cycle entities carry it; other's and the detector's are translated."""
      detecting.config.language = language
      assert await setup(detecting, DEVICES)
      for entity_id, name in NAMES[language].items():
          assert detecting.states.get(entity_id).attributes["friendly_name"] == name, entity_id
      if language == "en":
          assert detecting.states.get(sensor("phase_gelar_cycles_total")).attributes[
              "unit_of_measurement"] == "cycles"
  ```

  ```sh
  uv run pytest tests/test_features.py tests/test_program_entities.py -n 0 -q
  ```

  Expected: `3 failed`:
  - `test_the_detectors_keys_are_named`, with `KeyError: 'phase_last'`;
  - both `test_names`: `phase_other` has no name yet (it shows the device class's, `Demo filter Running`).

- [ ] **Step 2: The translations.** Add each group next to the existing `phase_current`, in each file's own layout; no other line is reformatted.

  `translations/en.json`, under `entity.binary_sensor`:

  ```json
  "phase_other": {"name": "Other phase"}
  ```

  `translations/en.json`, under `entity.sensor`. `phase_current` gains two states, and the rest is new:

  ```json
  "phase_current": {"name": "Phase", "state": {"idle": "Idle", "washing": "Washing", "heating": "Heating", "spinning": "Spinning", "rinsing": "Rinsing", "drying": "Drying", "cooling": "Cooling", "other": "Other", "dispensing": "Dispensing"}},
  "phase_last": {"name": "Last phase", "state": {"washing": "Washing", "heating": "Heating", "spinning": "Spinning", "rinsing": "Rinsing", "drying": "Drying", "cooling": "Cooling", "other": "Other", "dispensing": "Dispensing"}},
  "phase_last_cycle_start": {"name": "{item} last cycle start"},
  "phase_last_cycle_end": {"name": "{item} last cycle end"},
  "phase_last_cycle_duration": {"name": "{item} last cycle duration"},
  "phase_last_cycle_energy": {"name": "{item} last cycle energy"},
  "phase_cycles_total": {"name": "{item} cycles", "unit_of_measurement": "cycles"},
  "phase_runtime_total": {"name": "{item} runtime"},
  "phase_energy_total": {"name": "{item} energy"},
  "phase_other_last_cycle_start": {"name": "Other phase last cycle start"},
  "phase_other_last_cycle_end": {"name": "Other phase last cycle end"},
  "phase_other_last_cycle_duration": {"name": "Other phase last cycle duration"},
  "phase_other_last_cycle_energy": {"name": "Other phase last cycle energy"},
  "phase_other_cycles_total": {"name": "Other phase cycles", "unit_of_measurement": "cycles"},
  "phase_other_runtime_total": {"name": "Other phase runtime"},
  "phase_other_energy_total": {"name": "Other phase energy"}
  ```

  `translations/pt-BR.json`, the same keys:
  - `phase_other`: `"Outra fase"`;
  - `phase_current.state` gains `"other": "Outra"`, `"dispensing": "Dispensando"`;
  - `phase_last`: `"Última fase"`, its states `phase_current`'s without `idle`: `"washing": "Lavando"`, `"heating": "Aquecendo"`, `"spinning": "Centrifugando"`, `"rinsing": "Enxaguando"`, `"drying": "Secando"`, `"cooling": "Esfriando"`, `"other": "Outra"`, `"dispensing": "Dispensando"`;
  - `phase_last_cycle_start`: `"Início do último ciclo de {item}"`;
  - `phase_last_cycle_end`: `"Fim do último ciclo de {item}"`;
  - `phase_last_cycle_duration`: `"Duração do último ciclo de {item}"`;
  - `phase_last_cycle_energy`: `"Energia do último ciclo de {item}"`;
  - `phase_cycles_total`: `"Ciclos de {item}"`, unit `"ciclos"`;
  - `phase_runtime_total`: `"Tempo de {item}"`;
  - `phase_energy_total`: `"Energia de {item}"`;
  - `phase_other_*`: the same texts with `outra fase` for `{item}` (`"Ciclos de outra fase"`, unit `"ciclos"`; `"Tempo de outra fase"`; …).

  `icons.json`:
  - under `entity.binary_sensor`: `"phase_other": {"default": "mdi:progress-question"}`;
  - under `entity.sensor`: `"phase_last": {"default": "mdi:history"}`;
  - each `phase_<suffix>` and `phase_other_<suffix>` takes `mode_<suffix>`'s icon: `last_cycle_start` `mdi:clock-start`, `last_cycle_end` `mdi:clock-end`, `last_cycle_duration` `mdi:timer-outline`, `last_cycle_energy` `mdi:lightning-bolt-outline`, `cycles_total` `mdi:counter`, `runtime_total` `mdi:timer-sand`, `energy_total` `mdi:lightning-bolt`.

- [ ] **Step 3: GREEN, and the whole suite.**

  ```sh
  uv run pytest tests/test_features.py tests/test_program_entities.py -n 0 -q
  uv run pytest -q
  ```

  Expected: every test passes, then `1300 passed` (1297 + 1 + 2). hassfest (in `test_code.py`) accepts the translations. `test_translation_files_match` holds: en and pt-BR have the same keys.

- [ ] **Step 4: The contract catches a missing name, by perturbation.** Copy `translations/pt-BR.json` aside, delete `phase_other_energy_total` from it, and run `uv run pytest tests/test_features.py -n 0 -q`. Expected: `test_translation_files_match` and `test_the_detectors_keys_are_named` fail. Copy it back.

- [ ] **Step 5: Commit and push.**

  ```sh
  git add custom_components/pururu/translations custom_components/pururu/icons.json tests/test_features.py tests/test_program_entities.py
  git commit -m "pururu: the detector's names and icons, in the contract (refactor D1)

  NAMED's translation keys in en and pt-BR with icons; the contract test counts
  them as created and checks each: a phase's own carry {item}, other's and the
  detector's two don't. phase_current's states gain other and dispensing.

  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NW7HwrCq9naArexx5sDXpM"
  git push
  ```

  Wait for `headRefOid`, then `claude-review`.

---

### Task 4: Docs, coverage, final review, PR

- [ ] **Step 1: Docs.** No Guide page: the detector's concept page comes with D2, when users can configure it. The Develop pages and CLAUDE.md say what D1 adds:
  - `CLAUDE.md`, Architecture → Features, after the `features/cycle/` sentence, a bullet **Detected programs** (`features/cycle/program/`; no builder uses it until D2):
    - `schema.py`: `SCHEMA`, `Program`, `program_of`, `phase_keys`, `FIXED`, `NAMED`, `COUNTERS`.
    - `detector.py`: the pure `Detector`. `read(value, now, kwh)` and `advance(now, kwh)` return `Started`/`Ended`, each delay at its own time. Overlapping bands run at once, a dip waits, an idle gap blocks nothing, and `other` never waits and ends when a phase starts.
    - `entities.py`: `build(hass, device, program, *, key, reading, energy)`. The `Carrier` under the builder's key owns and restores the detector and calls its views after its own state. `PhaseRunning` (`phase_<key>`, a `CycleSource`), `PhaseCurrent`, `PhaseLast`, and each phase's cycle entities, named by `NAMED`, which the contract test counts.
    - Its tests: `tests/test_program.py` (pure; today's modes and phases scenarios; the purifier day's replay, `tests/fixtures/purifier_day.csv`) and `tests/test_program_entities.py` (a test-only builder swapped in for `FEATURES["appliance"]`).
  - `docs/develop/architecture.mdx`:
    - under "Features", a short "Detected programs" paragraph saying the same, with the rulings a contributor needs: dip vs gap, `other`, `phase_current`'s state, `NAMED`;
    - under "Restoring state", a bullet: the carrier keeps the detector's snapshot, and `phase_current` shows its restored state until the carrier is ready.
  - `docs/develop/index.mdx`, the tree: under `features/`, a `cycle/` line (`the cycle machinery: CycleSource, last cycle, totals, energy`) and `program/` (`the detector of detected programs: schema, detector, entities`).
  - `docs/develop/testing.mdx`, "Test files":
    - a row for `test_program.py` (the pure detector, today's modes and phases scenarios with the same readings, the real day's replay);
    - a row for `test_program_entities.py` (the entities through a test-only builder: IDs, states, the handover, restarts, reloads, names);
    - `test_cycle.py`'s row also says the cycle entities take a translation;
    - `test_features.py`'s row says the detector's keys (`NAMED`) are counted and named.
  - Every example in these pages that imports a module names one that exists (`test_code.py` checks it).

  ```sh
  pnpm install
  pnpm docs:check
  ```

  Expected: no broken link.

- [ ] **Step 2: Coverage per function, against B4's.**

  ```sh
  uv run pytest -q --cov=custom_components/pururu --cov-report=json:<scratchpad>/after.json
  ```

  In a `git archive 217bb52` scratch copy (with `.hassfest`, `uv sync --locked`), run the same command into `<scratchpad>/before.json`. Compare the `functions` of each file:
  - no function misses more lines than before;
  - every function of `features/cycle/program/` misses none;
  - the total is at most B4's 20 missed lines.

  Write the table (file, function, before, after) into the PR text.

- [ ] **Step 3: The final whole-branch review** (opus): `git diff 217bb52...HEAD`, against this plan, the spec's Part 4, the rulings and the Review Focus. Fix every finding, minors included, each behaviour fix with a test that failed first. Commit the fixes as `pururu: D1 final review: <what> (refactor D1)` and the docs as `docs: the detector, Develop pages and CLAUDE.md (refactor D1)`. Each commit ends with the two attribution lines. Push, wait for `headRefOid`, then `claude-review`.

- [ ] **Step 4: Ready.** Once `claude-review`'s findings are fixed:
  1. add `greptile`;
  2. `gh pr ready`;
  3. if Greptile answers "does not match any trigger rule", post `@greptileai review` once.

  Fix its findings too.
