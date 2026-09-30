"""features/cycle/program's entities, in HA, through a test-only builder in the appliance's namespace.

No feature uses the detector until D2: `detecting` swaps FEATURES["appliance"]
for a builder whose block is `power`, `energy` and `running_program`, so the
entity IDs are D2's: <platform>.pururu_<device>_appliance_phase_<key>_<suffix>.
"""

import asyncio
from datetime import timedelta
from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_state_change_event
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


async def test_a_reading_without_a_value_holds_the_phase(
        purifier: HomeAssistant, freezer: Any) -> None:
    """unavailable for longer than every off_delay: the program and its phase stay on; the idle reading after ends them."""
    await cool(purifier, freezer)
    await watts(purifier, "unavailable")
    await tick(purifier, freezer, 600)
    assert (state(purifier, RUNNING), state(purifier, GELAR)) == ("on", "on")
    assert state(purifier, CURRENT) == "gelar"
    await watts(purifier, IDLE_W)
    await tick(purifier, freezer, 125)
    assert (state(purifier, RUNNING), state(purifier, GELAR)) == ("off", "off")
    assert state(purifier, sensor("phase_gelar_cycles_total")) == "1"


async def test_an_energy_entity_without_a_state(purifier: HomeAssistant, freezer: Any) -> None:
    """energy is configured, its entity never set: a cycle counts, with no energy."""
    await cool(purifier, freezer)
    await watts(purifier, IDLE_W)
    await tick(purifier, freezer, 35)
    assert state(purifier, sensor("phase_gelar_cycles_total")) == "1"
    assert state(purifier, sensor("phase_gelar_last_cycle_energy")) == "unknown"
    assert float(state(purifier, sensor("phase_gelar_energy_total"))) == 0.0


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


@pytest.mark.parametrize(("attributes", "running", "seen"), [
    pytest.param({"running": ["gelar"], "seen": ["quente", "gelar"]},
                 ["gelar"], ["gelar", "quente"], id="its attributes"),
    pytest.param({}, ["gelar"], ["gelar"], id="none saved: its phase"),
    pytest.param({"running": ["nope", 3], "seen": "gelar"}, ["gelar"], ["gelar"],
                 id="unusable: its phase"),
])
async def test_the_current_phase_restored_before_the_carrier(
        detecting: HomeAssistant, monkeypatch: pytest.MonkeyPatch,
        attributes: dict[str, Any], running: list[str], seen: list[str]) -> None:
    """The carrier held until phase_current is written: it shows its restored phase, and its running and seen, until the carrier restored the detector."""
    entities = module("features.cycle.program.entities")
    written = asyncio.Event()

    @callback
    def current_written(_event: Any) -> None:
        written.set()

    async_track_state_change_event(detecting, [CURRENT], current_written)
    added = entities.Carrier.async_added_to_hass

    async def after_current(self: Any) -> None:
        await written.wait()
        await added(self)

    monkeypatch.setattr(entities.Carrier, "async_added_to_hass", after_current)
    since = (dt_util.utcnow() - timedelta(minutes=20)).isoformat()
    changes = capture(detecting, "state_changed")
    await restart(
        detecting, DEVICES,
        (State(RUNNING, "on"), snapshot(since, gelar={"since": since})),
        (State(CURRENT, "gelar", attributes), {}),
    )
    shown = [(event.data["entity_id"], event.data["new_state"].state) for event in changes
             if event.data["entity_id"] in (RUNNING, CURRENT)]
    assert shown[0] == (CURRENT, "gelar"), shown  # written before the carrier restored
    first = next(event.data["new_state"] for event in changes
                 if event.data["entity_id"] == CURRENT)
    assert (first.attributes["running"], first.attributes["seen"]) == (running, seen)
    assert (CURRENT, "idle") not in shown, shown
    assert state(detecting, CURRENT) == "gelar"
    assert state(detecting, RUNNING) == "on"


# Every delay at its default, 0: a reading ends or starts a phase at once
AT_ONCE: dict[str, Any] = {
    "above": 4,
    "phases": {"gelar": {"name": "Gelar", "above": 40, "below": 300},
               "quente": {"name": "Água quente", "above": 300}},
}


@pytest.mark.parametrize(("restored", "watts_now", "ended", "now_running"), [
    pytest.param("other", 120, "other", GELAR, id="gelar starts, other ends"),
    pytest.param("gelar", 1000, "gelar", QUENTE, id="gelar leaves, quente starts"),
])
async def test_a_restart_ending_a_phase_at_once_counts_its_cycle(
        detecting: HomeAssistant, restored: str, watts_now: float, ended: str,
        now_running: str) -> None:
    """The reading already ends the restored phase: its cycle reaches its entities, as every view listens before the carrier's first step."""
    devices = {KEY: {"name": "Demo filter",
                     "appliance": {"power": POWER, "running_program": AT_ONCE}}}
    since = (dt_util.utcnow() - timedelta(minutes=20)).isoformat()
    phase_since = dt_util.utcnow() - timedelta(minutes=10)
    detecting.states.async_set(POWER, str(watts_now))
    await restart(
        detecting, devices,
        (State(RUNNING, "on"), snapshot(since, **{restored: {"since": phase_since.isoformat()}})),
        (State(f"binary_sensor.{PREFIX}_phase_{restored}", "on"), {}),
        (State(CURRENT, restored), {}),
    )
    assert state(detecting, now_running) == "on"
    assert state(detecting, f"binary_sensor.{PREFIX}_phase_{ended}") == "off"
    assert state(detecting, sensor(f"phase_{ended}_cycles_total")) == "1"
    assert dt_util.parse_datetime(
        state(detecting, sensor(f"phase_{ended}_last_cycle_start"))) == phase_since
    assert dt_util.parse_datetime(
        state(detecting, sensor(f"phase_{ended}_last_cycle_end"))) == dt_util.utcnow()
    assert state(detecting, LAST) == ended


async def test_the_program_ends_after_its_phases(detecting: HomeAssistant, freezer: Any) -> None:
    """Both end in the program's step: the phases' ends are written first, the program's off and its end signal last."""
    program = {**RUNNING_PROGRAM, "off_delay": {"seconds": 30},
               "phases": {**RUNNING_PROGRAM["phases"],
                          "gelar": {**RUNNING_PROGRAM["phases"]["gelar"],
                                    "off_delay": {"minutes": 1}}}}
    assert await setup(detecting, {KEY: {"name": "Demo filter", "appliance": {
        "power": POWER, "running_program": program}}})
    await watts(detecting, IDLE_W)
    await tick(detecting, freezer, 35)
    await cool(detecting, freezer)
    device = module("core.feature").Device(key=KEY, name="Demo filter", namespace="appliance")
    seen: list[tuple[str, ...]] = []
    async_dispatcher_connect(
        detecting, module("features.cycle").end_signal(device),
        lambda _cycle: seen.append(tuple(state(detecting, each)
                                         for each in (RUNNING, GELAR, CURRENT, LAST))))
    changes = capture(detecting, "state_changed")
    await watts(detecting, IDLE_W)
    await tick(detecting, freezer, 35)
    assert seen == [("off", "off", "idle", "gelar")]
    order = [event.data["entity_id"] for event in changes
             if event.data["entity_id"] in (RUNNING, GELAR, CURRENT, LAST)
             and event.data["new_state"].state != event.data["old_state"].state]
    assert order[-1] == RUNNING, order
    assert set(order) == {RUNNING, GELAR, CURRENT, LAST}, order


@pytest.mark.parametrize("extra", [
    pytest.param(["not", "a", "map"], id="not a map"),
    pytest.param({"program": {"since": "2020-02-30T10:00:00+00:00"}}, id="an impossible date"),
])
async def test_a_snapshot_the_detector_cannot_use_is_ignored(
        detecting: HomeAssistant, freezer: Any, extra: Any) -> None:
    """A hand-edited .storage: the carrier starts from nothing, and the phases follow the readings."""
    await restart(detecting, DEVICES, (State(RUNNING, "on"), extra), (State(CURRENT, "gelar"), {}))
    assert state(detecting, RUNNING) == "off"
    assert state(detecting, CURRENT) == "idle"
    await watts(detecting, 120)
    await tick(detecting, freezer, 35)
    assert state(detecting, RUNNING) == "on"
    assert state(detecting, CURRENT) == "gelar"


async def test_a_phases_impossible_date_is_no_start(
        detecting: HomeAssistant, freezer: Any) -> None:
    """A hand-edited .storage: the program and its phase run on, the phase without a start, and end with the readings."""
    since = (dt_util.utcnow() - timedelta(minutes=20)).isoformat()
    await restart(detecting, DEVICES,
                  (State(RUNNING, "on"), snapshot(since, gelar={"since": "2020-02-30T10:00:00+00:00"})),
                  (State(CURRENT, "gelar"), {}))
    assert state(detecting, RUNNING) == "on"
    assert state(detecting, CURRENT) == "gelar"
    await watts(detecting, IDLE_W)
    await tick(detecting, freezer, 125)
    assert state(detecting, RUNNING) == "off"
    assert state(detecting, CURRENT) == "idle"
    assert state(detecting, sensor("phase_gelar_cycles_total")) == "1"
    assert state(detecting, sensor("phase_gelar_last_cycle_start")) == "unknown"


async def test_a_disabled_carrier_leaves_the_phases_idle(detecting: HomeAssistant) -> None:
    """The carrier is disabled: the detector never runs, so phase_current is idle as every phase is off, not its restored phase."""
    er.async_get(detecting).async_get_or_create(
        "binary_sensor", "pururu", f"{PREFIX}_running",
        suggested_object_id=f"{PREFIX}_running",
        disabled_by=er.RegistryEntryDisabler.USER)
    await restart(detecting, DEVICES, (State(CURRENT, "gelar", {"running": ["gelar"]}), {}))
    assert detecting.states.get(RUNNING) is None
    assert state(detecting, GELAR) == "off"
    assert state(detecting, CURRENT) == "idle"
    assert detecting.states.get(CURRENT).attributes["running"] == []


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


async def test_a_carrier_renamed_mid_phase_follows_the_reading(
        purifier: HomeAssistant, freezer: Any) -> None:
    """Renamed in the UI: HA adds it again to the loaded entry, then the entry reloads; the phase's cycle counts once."""
    await cool(purifier, freezer)
    renamed = "binary_sensor.demo_filter_program"
    er.async_get(purifier).async_update_entity(RUNNING, new_entity_id=renamed)
    await purifier.async_block_till_done()
    assert state(purifier, renamed) == "on"
    assert state(purifier, GELAR) == "on"
    await watts(purifier, IDLE_W)
    await tick(purifier, freezer, 125)
    assert state(purifier, renamed) == "off"
    assert state(purifier, sensor("phase_gelar_cycles_total")) == "1"


async def test_last_restores(detecting: HomeAssistant) -> None:
    await restart(detecting, DEVICES, (State(LAST, "quente"), {
        "native_value": "quente", "native_unit_of_measurement": None}))
    assert state(detecting, LAST) == "quente"
