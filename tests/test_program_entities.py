"""features/cycle/program's entities, in HA, through the appliance's running_program.

The carrier is the appliance's `running`; the phases' entity IDs are
<platform>.pururu_<device>_appliance_phase_<key>_<suffix>.
"""

import asyncio
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util
import pytest

from helpers import capture, fake, generated, held, module, reload, restart, setup, snapshot, tick

KEY = "dummy_station"
POWER = "sensor.dummy_plug_power"
ENERGY = "sensor.dummy_plug_energy"
IDLE_W = 1.0
PREFIX = f"pururu_{KEY}_appliance"
RUNNING = f"binary_sensor.{PREFIX}_running"
CURRENT = f"sensor.{PREFIX}_phase_current"
LAST = f"sensor.{PREFIX}_phase_last"
RESFRIAR = f"binary_sensor.{PREFIX}_phase_resfriar"
QUENTE = f"binary_sensor.{PREFIX}_phase_quente"
OTHER = f"binary_sensor.{PREFIX}_phase_other"
RUNNING_PROGRAM: dict[str, Any] = {
    "above": 4, "on_delay": {"seconds": 20}, "off_delay": {"minutes": 2},
    "phases": {
        "resfriar": {"name": "Resfriar", "above": 40, "below": 300,
                  "on_delay": {"seconds": 30}, "off_delay": {"seconds": 30}},
        "quente": {"name": "Água quente", "above": 300,
                   "on_delay": {"seconds": 10}, "off_delay": {"seconds": 30}},
    },
}
DEVICES = {KEY: {"name": "Dummy station",
                 "appliance": {"power": POWER, "energy": ENERGY,
                               "running_program": RUNNING_PROGRAM}}}
LAST_CYCLE = ("last_cycle_start", "last_cycle_end", "last_cycle_duration", "last_cycle_energy")
SUFFIXES = (*LAST_CYCLE, "cycles_total", "runtime_total", "energy_total")


def sensor(entity_key: str) -> str:
    return f"sensor.{PREFIX}_{entity_key}"


# The appliance's own, beside its running program's phases
OWN = {RUNNING, *(sensor(key) for key in (
    "power", "energy_total", *LAST_CYCLE, "cycles_total", "runtime_total", "idle_energy_total"))}


@pytest.fixture
async def purifier(ha: HomeAssistant, freezer: Any) -> HomeAssistant:
    """Idle at 1 W, long enough to count as not running."""
    assert await setup(ha, DEVICES)
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 125)
    assert state(ha, RUNNING) == "off"
    return ha


def state(hass: HomeAssistant, entity_id: str) -> str:
    found = hass.states.get(entity_id)
    assert found is not None, entity_id
    return found.state


async def watts(hass: HomeAssistant, value: float | str) -> None:
    await fake(hass, POWER, str(value))


async def kwh(hass: HomeAssistant, value: float | str) -> None:
    await fake(hass, ENERGY, str(value))


async def cool(hass: HomeAssistant, freezer: Any) -> None:
    """The program runs at 20 s, resfriar at 30 s."""
    await watts(hass, 120)
    await tick(hass, freezer, 35)
    assert state(hass, RUNNING) == "on"
    assert state(hass, CURRENT) == "resfriar"


# --- what it creates ----------------------------------------------------------------


async def test_its_entities_and_their_ids(ha: HomeAssistant) -> None:
    """The carrier under the builder's key, the current and last phase, and per phase (other too) its binary sensor and cycle entities."""
    assert await setup(ha, DEVICES)
    phases = ("resfriar", "quente", "other")
    assert held(ha, KEY) == {
        *OWN, CURRENT, LAST,
        *(f"binary_sensor.{PREFIX}_phase_{phase}" for phase in phases),
        *(sensor(f"phase_{phase}_{suffix}") for phase in phases for suffix in SUFFIXES),
    }
    registry = er.async_get(ha)
    assert registry.async_get(RESFRIAR).unique_id == f"{PREFIX}_phase_resfriar"
    assert registry.async_get(sensor("phase_other_cycles_total")).unique_id == (
        f"{PREFIX}_phase_other_cycles_total")


async def test_without_energy_no_energy_per_phase(ha: HomeAssistant) -> None:
    appliance = {"power": POWER, "running_program": RUNNING_PROGRAM}
    assert await setup(ha, {KEY: {"name": "Dummy station", "appliance": appliance}})
    assert ha.states.get(sensor("phase_resfriar_energy_total")) is None
    assert ha.states.get(sensor("phase_resfriar_last_cycle_energy")) is None
    assert ha.states.get(sensor("phase_resfriar_cycles_total")) is not None


async def test_without_phases_no_phase_entity(ha: HomeAssistant) -> None:
    appliance = {"power": POWER, "running_program": {"above": 4}}
    assert await setup(ha, {KEY: {"name": "Dummy station", "appliance": appliance}})
    assert held(ha, KEY) == {RUNNING, *(sensor(key) for key in (
        "power", *LAST_CYCLE[:3], "cycles_total", "runtime_total"))}


async def test_nothing_that_follows_the_carrier_when_it_is_not_created(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """The carrier's ID belongs to another integration: no phase entity, nor the appliance's cycle entities, is created; its mirrors are."""
    er.async_get(ha).async_get_or_create(
        "binary_sensor", "template", "someone_else", suggested_object_id=f"{PREFIX}_running")
    assert await setup(ha, DEVICES)
    assert ha.states.get(CURRENT) is None
    assert ha.states.get(RESFRIAR) is None
    assert ha.states.get(sensor("phase_resfriar_cycles_total")) is None
    assert ha.states.get(sensor("runtime_total")) is None
    assert ha.states.get(sensor("power")) is not None
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(RESFRIAR in message and RUNNING in message for message in errors), errors
    assert any(sensor("runtime_total") in message and RUNNING in message for message in errors), errors


# --- what they show -------------------------------------------------------------------


async def test_idle_until_a_phase_starts(purifier: HomeAssistant) -> None:
    assert state(purifier, CURRENT) == "idle"
    assert purifier.states.get(CURRENT).attributes["options"] == ["idle", "resfriar", "quente", "other"]
    assert purifier.states.get(CURRENT).attributes["running"] == []
    assert state(purifier, LAST) == "unknown"
    assert purifier.states.get(LAST).attributes["options"] == ["resfriar", "quente", "other"]
    assert state(purifier, RESFRIAR) == "off"


async def test_a_phase_runs_and_ends(purifier: HomeAssistant, freezer: Any) -> None:
    await kwh(purifier, 100.0)
    await cool(purifier, freezer)
    started = dt_util.utcnow() - timedelta(seconds=5)
    assert state(purifier, RESFRIAR) == "on"
    assert purifier.states.get(RESFRIAR).attributes["cycle_start"] == started
    assert purifier.states.get(CURRENT).attributes["running"] == ["resfriar"]
    assert purifier.states.get(CURRENT).attributes["seen"] == ["resfriar"]
    await tick(purifier, freezer, 600)
    await kwh(purifier, 100.05)
    left = dt_util.utcnow()
    await watts(purifier, IDLE_W)
    assert purifier.states.get(RESFRIAR).attributes["cycle_end"] == left
    await tick(purifier, freezer, 35)
    assert state(purifier, RESFRIAR) == "off"
    assert state(purifier, CURRENT) == "idle"
    assert state(purifier, LAST) == "resfriar"
    assert dt_util.parse_datetime(state(purifier, sensor("phase_resfriar_last_cycle_start"))) == started
    assert dt_util.parse_datetime(state(purifier, sensor("phase_resfriar_last_cycle_end"))) == left
    assert float(state(purifier, sensor("phase_resfriar_last_cycle_duration"))) == pytest.approx(10.1, abs=0.1)
    assert float(state(purifier, sensor("phase_resfriar_last_cycle_energy"))) == pytest.approx(0.05)
    assert state(purifier, sensor("phase_resfriar_cycles_total")) == "1"
    assert float(state(purifier, sensor("phase_resfriar_energy_total"))) == pytest.approx(0.05)
    assert float(state(purifier, sensor("phase_resfriar_runtime_total"))) == pytest.approx(
        605 / 3600, abs=0.0005)
    assert state(purifier, sensor("phase_quente_cycles_total")) == "0"
    for key in LAST_CYCLE:
        assert state(purifier, sensor(f"phase_quente_{key}")) == "unknown", key


async def test_a_phases_cycle_is_sent_after_its_state_its_end_last(
        purifier: HomeAssistant, freezer: Any) -> None:
    """CycleSource's order: the binary sensor is off when each signal fires, the cycle's signal first; last_cycle_end written last."""
    cycle = module("features.cycle")
    feature = module("core.feature")
    device = feature.Device(key=KEY, name="Dummy station", namespace="appliance")
    item = feature.Item(slug="phase_resfriar", name="Resfriar")
    await kwh(purifier, 100.0)
    await cool(purifier, freezer)
    seen: list[tuple[str, str]] = []
    for name, signal in (("cycle", cycle.cycle_signal(device, item)),
                         ("end", cycle.end_signal(device, item))):
        async_dispatcher_connect(
            purifier, signal,
            callback(lambda _cycle, name=name: seen.append((name, state(purifier, RESFRIAR)))))
    changes = capture(purifier, "state_changed")
    await watts(purifier, IDLE_W)
    await tick(purifier, freezer, 35)
    assert seen == [("cycle", "off"), ("end", "off")]
    watched = {LAST, *(sensor(f"phase_resfriar_{key}") for key in LAST_CYCLE)}
    order = [event.data["entity_id"] for event in changes if event.data["entity_id"] in watched]
    assert order[-1] == sensor("phase_resfriar_last_cycle_end"), order
    assert set(order) == watched, order


async def test_the_programs_cycle_is_sent_on_the_carriers_signals(
        purifier: HomeAssistant, freezer: Any) -> None:
    cycle = module("features.cycle")
    device = module("core.feature").Device(key=KEY, name="Dummy station", namespace="appliance")
    cycles: list[Any] = []
    async_dispatcher_connect(purifier, cycle.cycle_signal(device),
                             callback(lambda each: cycles.append(each)))
    await cool(purifier, freezer)
    left = dt_util.utcnow()
    await watts(purifier, IDLE_W)
    await tick(purifier, freezer, 125)
    assert state(purifier, RUNNING) == "off"
    assert [each.end for each in cycles] == [left]


def shown(changes: list[Any], entity_id: str) -> list[str]:
    """The states `entity_id` went through in `changes`, attribute-only writes left out."""
    return [event.data["new_state"].state for event in changes
            if event.data["entity_id"] == entity_id
            and event.data["new_state"].state != event.data["old_state"].state]


async def test_a_late_timer_ends_the_phases_before_the_next_cycle(ha: HomeAssistant, freezer: Any) -> None:
    """on_delay 0: a reading back above after the program's off_delay passed, before its timer ran, ends the program and its phase, then starts both again; each shows its end."""
    quick = {"above": 4, "off_delay": {"minutes": 2},
             "phases": {"resfriar": {"name": "Resfriar", "above": 40, "off_delay": {"minutes": 5}}}}
    assert await setup(ha, {KEY: {"name": "Dummy station",
                                  "appliance": {"power": POWER, "running_program": quick}}})
    await watts(ha, IDLE_W)
    await watts(ha, 120)
    assert (state(ha, RUNNING), state(ha, RESFRIAR), state(ha, CURRENT)) == ("on", "on", "resfriar")
    changes = capture(ha, "state_changed")
    await watts(ha, IDLE_W)
    freezer.tick(timedelta(seconds=130))  # the program's off_delay passed at 120 s; its timer hasn't run
    ha.states.async_set(POWER, "120")  # handled at once, before the timer
    await ha.async_block_till_done()
    assert shown(changes, RUNNING) == ["off", "on"]
    assert shown(changes, RESFRIAR) == ["off", "on"]
    assert shown(changes, CURRENT) == ["idle", "resfriar"]
    assert state(ha, sensor("cycles_total")) == "1"
    assert state(ha, sensor("phase_resfriar_cycles_total")) == "1"


async def test_a_late_timer_ends_a_phase_alone_before_it_starts_again(
        ha: HomeAssistant, freezer: Any) -> None:
    """The program runs on: a reading back in the phase's band after its off_delay passed, before its timer ran, ends the phase, then starts it again; the program shows no change."""
    quick = {"above": 4, "off_delay": {"minutes": 10},
             "phases": {"resfriar": {"name": "Resfriar", "above": 40, "off_delay": {"minutes": 2}}}}
    assert await setup(ha, {KEY: {"name": "Dummy station",
                                  "appliance": {"power": POWER, "running_program": quick}}})
    await watts(ha, IDLE_W)
    await watts(ha, 120)
    assert (state(ha, RUNNING), state(ha, RESFRIAR)) == ("on", "on")
    changes = capture(ha, "state_changed")
    await watts(ha, 10)
    freezer.tick(timedelta(seconds=130))  # the phase's off_delay passed at 120 s; its timer hasn't run
    ha.states.async_set(POWER, "120")  # handled at once, before the timer
    await ha.async_block_till_done()
    assert shown(changes, RUNNING) == []
    assert shown(changes, RESFRIAR) == ["off", "on"]
    assert state(ha, sensor("phase_resfriar_cycles_total")) == "1"
    assert state(ha, sensor("cycles_total")) == "0"


async def test_a_handover_never_shows_idle(purifier: HomeAssistant, freezer: Any) -> None:
    """resfriar to quente after a dip: phase_current goes straight from resfriar to quente."""
    await cool(purifier, freezer)
    changes = capture(purifier, "state_changed")
    await watts(purifier, 1000)
    await tick(purifier, freezer, 30)
    states = [event.data["new_state"].state for event in changes
              if event.data["entity_id"] == CURRENT
              and event.data["new_state"].state != event.data["old_state"].state]
    assert states == ["quente"], states
    assert state(purifier, LAST) == "resfriar"
    assert (state(purifier, RESFRIAR), state(purifier, QUENTE)) == ("off", "on")


async def test_other_is_a_phase_with_its_entities(purifier: HomeAssistant, freezer: Any) -> None:
    """300 W is neither resfriar's (below 300) nor quente's (above 300): other, after 30 s."""
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


@pytest.mark.parametrize(("language", "other"), [("en", "Other phase"), ("pt-BR", "Outra fase")])
async def test_the_current_phase_names_its_phase(
        ha: HomeAssistant, freezer: Any, language: str, other: str) -> None:
    """Its `name` attribute: a configured phase's `name` in every language, other's translation, none while idle."""
    ha.config.language = language
    assert await setup(ha, DEVICES)
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 125)

    def named() -> tuple[str, Any]:
        return state(ha, CURRENT), ha.states.get(CURRENT).attributes["name"]

    assert named() == ("idle", None)
    await cool(ha, freezer)
    assert named() == ("resfriar", "Resfriar")
    await watts(ha, 300)
    await tick(ha, freezer, 35)
    assert named() == ("other", other)
    await watts(ha, 1000)
    await tick(ha, freezer, 10)
    assert named() == ("quente", "Água quente")
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 125)
    assert named() == ("idle", None)


async def test_a_reading_without_a_value_holds_the_phase(
        purifier: HomeAssistant, freezer: Any) -> None:
    """unavailable for longer than every off_delay: the program and its phase stay on; the idle reading after ends them."""
    await cool(purifier, freezer)
    await watts(purifier, "unavailable")
    await tick(purifier, freezer, 600)
    assert (state(purifier, RUNNING), state(purifier, RESFRIAR)) == ("on", "on")
    assert state(purifier, CURRENT) == "resfriar"
    await watts(purifier, IDLE_W)
    await tick(purifier, freezer, 125)
    assert (state(purifier, RUNNING), state(purifier, RESFRIAR)) == ("off", "off")
    assert state(purifier, sensor("phase_resfriar_cycles_total")) == "1"


async def test_an_energy_entity_without_a_state(purifier: HomeAssistant, freezer: Any) -> None:
    """energy is configured, its entity never set: a cycle counts, with no energy."""
    await cool(purifier, freezer)
    await watts(purifier, IDLE_W)
    await tick(purifier, freezer, 35)
    assert state(purifier, sensor("phase_resfriar_cycles_total")) == "1"
    assert state(purifier, sensor("phase_resfriar_last_cycle_energy")) == "unknown"
    assert float(state(purifier, sensor("phase_resfriar_energy_total"))) == 0.0


async def test_a_phases_energy_adds_its_cycles_and_skips_the_unknown(
        purifier: HomeAssistant, freezer: Any) -> None:
    """A cycle whose counter had no reading at its start adds nothing; the others add theirs."""
    for start, end in ((100.0, 100.05), ("unavailable", 100.2), (100.2, 100.23)):
        await kwh(purifier, start)
        await cool(purifier, freezer)
        await kwh(purifier, end)
        await watts(purifier, IDLE_W)
        await tick(purifier, freezer, 125)
    assert state(purifier, sensor("phase_resfriar_cycles_total")) == "3"
    assert float(state(purifier, sensor("phase_resfriar_energy_total"))) == pytest.approx(0.08)


async def test_short_phases_add_up_their_energy(purifier: HomeAssistant, freezer: Any) -> None:
    """A sip uses a fraction of a Wh: rounding each cycle to 0.001 kWh would add nothing."""
    for start, end in ((100.0, 100.0004), (100.0004, 100.0008)):
        await kwh(purifier, start)
        await cool(purifier, freezer)
        await kwh(purifier, end)
        await watts(purifier, IDLE_W)
        await tick(purifier, freezer, 125)
    assert float(state(purifier, sensor("phase_resfriar_energy_total"))) == pytest.approx(0.0008, abs=1e-6)
    assert state(purifier, sensor("phase_resfriar_last_cycle_energy")) == "0.0"


async def test_each_phases_runtime_counts_from_its_start(purifier: HomeAssistant, freezer: Any) -> None:
    """resfriar from 30 s to 635 s; quente, armed at 645 s after the dip, starts when resfriar ends (665 s), dated 645 s, until 965 s."""
    await cool(purifier, freezer)
    await tick(purifier, freezer, 600)
    await watts(purifier, 1000)
    await tick(purifier, freezer, 10)
    await tick(purifier, freezer, 20)
    await tick(purifier, freezer, 300)
    await watts(purifier, IDLE_W)
    await tick(purifier, freezer, 30)
    await tick(purifier, freezer, 95)
    assert float(state(purifier, sensor("phase_resfriar_runtime_total"))) == pytest.approx(605 / 3600, abs=0.0005)
    assert float(state(purifier, sensor("phase_quente_runtime_total"))) == pytest.approx(320 / 3600, abs=0.0005)
    assert float(state(purifier, sensor("phase_other_runtime_total"))) == 0


async def test_meters_per_phase(ha: HomeAssistant, freezer: Any) -> None:
    """Each phase's statistics meter its own totals; a period not asked has no meter."""
    periods = {"runtime": ["today"], "cycles": ["today", "month"], "energy": ["today"]}
    program = {**RUNNING_PROGRAM, "phases": {key: {**phase, "statistics": periods}
                                             for key, phase in RUNNING_PROGRAM["phases"].items()}}
    assert await setup(ha, {KEY: {"name": "Dummy station", "appliance": {
        "power": POWER, "energy": ENERGY, "running_program": program}}})
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 125)
    for _ in range(2):
        await kwh(ha, 100.0)
        await cool(ha, freezer)
        await kwh(ha, 100.05)
        await watts(ha, IDLE_W)
        await tick(ha, freezer, 125)
    await tick(ha, freezer, 60)
    assert float(state(ha, sensor("phase_resfriar_cycles_today"))) == 2
    assert float(state(ha, sensor("phase_resfriar_cycles_month"))) == 2
    assert float(state(ha, sensor("phase_resfriar_energy_today"))) == pytest.approx(0.1)
    assert float(state(ha, sensor("phase_resfriar_runtime_today"))) == pytest.approx(
        float(state(ha, sensor("phase_resfriar_runtime_total"))), abs=0.01)
    assert float(state(ha, sensor("phase_quente_cycles_today"))) == 0
    assert ha.states.get(sensor("phase_resfriar_runtime_month")) is None
    assert ha.states.get(sensor("phase_resfriar_cycles_today")).attributes["unit_of_measurement"] == "cycles"


# --- restarts and reloads ------------------------------------------------------------


async def test_a_restart_keeps_the_running_phase(ha: HomeAssistant, freezer: Any) -> None:
    """The phase shows from the first write (no off in between) and counts from the restart, not from before."""
    since = (dt_util.utcnow() - timedelta(minutes=20)).isoformat()
    changes = capture(ha, "state_changed")
    await restart(
        ha, DEVICES,
        (State(RUNNING, "on"), snapshot(since, resfriar={"since": since})),
        (State(RESFRIAR, "on"), {}),
        (State(CURRENT, "resfriar"), {}),
    )
    assert state(ha, RESFRIAR) == "on"
    assert state(ha, CURRENT) == "resfriar"
    assert ha.states.get(CURRENT).attributes["name"] == "Resfriar"
    shown = [event.data["new_state"].state for event in changes
             if event.data["entity_id"] in (RESFRIAR, CURRENT)]
    assert "off" not in shown, shown
    assert "idle" not in shown, shown
    await watts(ha, 120)
    await tick(ha, freezer, 600)
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 35)
    assert state(ha, CURRENT) == "idle"
    assert float(state(ha, sensor("phase_resfriar_last_cycle_duration"))) == pytest.approx(
        30, abs=0.2)
    assert state(ha, sensor("phase_resfriar_cycles_total")) == "1"
    assert float(state(ha, sensor("phase_resfriar_runtime_total"))) == pytest.approx(
        600 / 3600, abs=0.0005)


@pytest.mark.parametrize(("attributes", "running", "seen"), [
    pytest.param({"running": ["resfriar"], "seen": ["quente", "resfriar"]},
                 ["resfriar"], ["resfriar", "quente"], id="its attributes"),
    pytest.param({"name": "Antes", "running": ["resfriar"], "seen": ["resfriar"]},
                 ["resfriar"], ["resfriar"], id="a name saved before a rename: its name now"),
    pytest.param({}, ["resfriar"], ["resfriar"], id="none saved: its phase"),
    pytest.param({"running": ["nope", 3], "seen": "resfriar"}, ["resfriar"], ["resfriar"],
                 id="unusable: its phase"),
])
async def test_the_current_phase_restored_before_the_carrier(
        ha: HomeAssistant, monkeypatch: pytest.MonkeyPatch,
        attributes: dict[str, Any], running: list[str], seen: list[str]) -> None:
    """The carrier held until phase_current is written: it shows its restored phase, named as configured now, and its running and seen, until the carrier restored the detector."""
    entities = module("features.cycle.program.entities")
    written = asyncio.Event()

    @callback
    def current_written(_event: Any) -> None:
        written.set()

    async_track_state_change_event(ha, [CURRENT], current_written)
    added = entities.Carrier.async_added_to_hass

    async def after_current(self: Any) -> None:
        await written.wait()
        await added(self)

    monkeypatch.setattr(entities.Carrier, "async_added_to_hass", after_current)
    since = (dt_util.utcnow() - timedelta(minutes=20)).isoformat()
    changes = capture(ha, "state_changed")
    await restart(
        ha, DEVICES,
        (State(RUNNING, "on"), snapshot(since, resfriar={"since": since})),
        (State(CURRENT, "resfriar", attributes), {}),
    )
    shown = [(event.data["entity_id"], event.data["new_state"].state) for event in changes
             if event.data["entity_id"] in (RUNNING, CURRENT)]
    assert shown[0] == (CURRENT, "resfriar"), shown  # written before the carrier restored
    first = next(event.data["new_state"] for event in changes
                 if event.data["entity_id"] == CURRENT)
    assert (first.attributes["running"], first.attributes["seen"]) == (running, seen)
    assert first.attributes["name"] == "Resfriar"
    assert (CURRENT, "idle") not in shown, shown
    assert state(ha, CURRENT) == "resfriar"
    assert ha.states.get(CURRENT).attributes["name"] == "Resfriar"
    assert state(ha, RUNNING) == "on"


# Every delay at its default, 0: a reading ends or starts a phase at once
AT_ONCE: dict[str, Any] = {
    "above": 4,
    "phases": {"resfriar": {"name": "Resfriar", "above": 40, "below": 300},
               "quente": {"name": "Água quente", "above": 300}},
}


@pytest.mark.parametrize(("restored", "watts_now", "ended", "now_running"), [
    pytest.param("other", 120, "other", RESFRIAR, id="resfriar starts, other ends"),
    pytest.param("resfriar", 1000, "resfriar", QUENTE, id="resfriar leaves, quente starts"),
])
async def test_a_restart_ending_a_phase_at_once_counts_its_cycle(
        ha: HomeAssistant, restored: str, watts_now: float, ended: str,
        now_running: str) -> None:
    """The reading already ends the restored phase: its cycle reaches its entities, as every view listens before the carrier's first step."""
    devices = {KEY: {"name": "Dummy station",
                     "appliance": {"power": POWER, "running_program": AT_ONCE}}}
    since = (dt_util.utcnow() - timedelta(minutes=20)).isoformat()
    phase_since = dt_util.utcnow() - timedelta(minutes=10)
    ha.states.async_set(POWER, str(watts_now))
    await restart(
        ha, devices,
        (State(RUNNING, "on"), snapshot(since, **{restored: {"since": phase_since.isoformat()}})),
        (State(f"binary_sensor.{PREFIX}_phase_{restored}", "on"), {}),
        (State(CURRENT, restored), {}),
    )
    assert state(ha, now_running) == "on"
    assert state(ha, f"binary_sensor.{PREFIX}_phase_{ended}") == "off"
    assert state(ha, sensor(f"phase_{ended}_cycles_total")) == "1"
    assert dt_util.parse_datetime(
        state(ha, sensor(f"phase_{ended}_last_cycle_start"))) == phase_since
    assert dt_util.parse_datetime(
        state(ha, sensor(f"phase_{ended}_last_cycle_end"))) == dt_util.utcnow()
    assert state(ha, LAST) == ended


async def test_the_program_ends_after_its_phases(ha: HomeAssistant, freezer: Any) -> None:
    """Both end in the program's step: the phases' ends are written first, the program's off and its end signal last."""
    program = {**RUNNING_PROGRAM, "off_delay": {"seconds": 30},
               "phases": {**RUNNING_PROGRAM["phases"],
                          "resfriar": {**RUNNING_PROGRAM["phases"]["resfriar"],
                                    "off_delay": {"minutes": 1}}}}
    assert await setup(ha, {KEY: {"name": "Dummy station", "appliance": {
        "power": POWER, "running_program": program}}})
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 35)
    await cool(ha, freezer)
    device = module("core.feature").Device(key=KEY, name="Dummy station", namespace="appliance")
    seen: list[tuple[str, ...]] = []
    async_dispatcher_connect(
        ha, module("features.cycle").end_signal(device),
        callback(lambda _cycle: seen.append(tuple(state(ha, each)
                                                  for each in (RUNNING, RESFRIAR, CURRENT, LAST)))))
    changes = capture(ha, "state_changed")
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 35)
    assert seen == [("off", "off", "idle", "resfriar")]
    order = [event.data["entity_id"] for event in changes
             if event.data["entity_id"] in (RUNNING, RESFRIAR, CURRENT, LAST)
             and event.data["new_state"].state != event.data["old_state"].state]
    assert order[-1] == RUNNING, order
    assert set(order) == {RUNNING, RESFRIAR, CURRENT, LAST}, order


@pytest.mark.parametrize("extra", [
    pytest.param(["not", "a", "map"], id="not a map"),
    pytest.param({"program": {"since": "2020-02-30T10:00:00+00:00"}}, id="an impossible date"),
])
async def test_a_snapshot_the_detector_cannot_use_is_ignored(
        ha: HomeAssistant, freezer: Any, extra: Any) -> None:
    """A hand-edited .storage: the carrier starts from nothing, and the phases follow the readings."""
    await restart(ha, DEVICES, (State(RUNNING, "on"), extra), (State(CURRENT, "resfriar"), {}))
    assert state(ha, RUNNING) == "off"
    assert state(ha, CURRENT) == "idle"
    await watts(ha, 120)
    await tick(ha, freezer, 35)
    assert state(ha, RUNNING) == "on"
    assert state(ha, CURRENT) == "resfriar"


async def test_a_phases_impossible_date_is_no_start(
        ha: HomeAssistant, freezer: Any) -> None:
    """A hand-edited .storage: the program and its phase run on, the phase without a start, and end with the readings."""
    since = (dt_util.utcnow() - timedelta(minutes=20)).isoformat()
    await restart(ha, DEVICES,
                  (State(RUNNING, "on"), snapshot(since, resfriar={"since": "2020-02-30T10:00:00+00:00"})),
                  (State(CURRENT, "resfriar"), {}))
    assert state(ha, RUNNING) == "on"
    assert state(ha, CURRENT) == "resfriar"
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 125)
    assert state(ha, RUNNING) == "off"
    assert state(ha, CURRENT) == "idle"
    assert state(ha, sensor("phase_resfriar_cycles_total")) == "1"
    assert state(ha, sensor("phase_resfriar_last_cycle_start")) == "unknown"


async def test_a_disabled_carrier_leaves_the_phases_idle(ha: HomeAssistant) -> None:
    """The carrier is disabled: the detector never runs, so phase_current is idle as every phase is off, not its restored phase."""
    er.async_get(ha).async_get_or_create(
        "binary_sensor", "pururu", f"{PREFIX}_running",
        suggested_object_id=f"{PREFIX}_running",
        disabled_by=er.RegistryEntryDisabler.USER)
    await restart(ha, DEVICES, (State(CURRENT, "resfriar",
                                     {"name": "Resfriar", "running": ["resfriar"]}), {}))
    assert ha.states.get(RUNNING) is None
    assert state(ha, RESFRIAR) == "off"
    assert state(ha, CURRENT) == "idle"
    assert ha.states.get(CURRENT).attributes["running"] == []
    assert ha.states.get(CURRENT).attributes["name"] is None


def forward_then_fail(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    """The setup raises once the platforms are added."""
    entries = hass.config_entries
    forward = entries.async_forward_entry_setups

    async def forwarded(entry: Any, platforms: Any) -> None:
        await forward(entry, platforms)
        raise RuntimeError("after the platforms")

    monkeypatch.setattr(entries, "async_forward_entry_setups", forwarded)


async def test_an_entry_failing_after_its_platforms_drops_the_waiting_carrier(
        ha: HomeAssistant, freezer: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The platforms unloaded: the carrier, removed while it waits, never starts; a reload brings it back, following the reading."""
    started: list[Any] = []
    carrier = module("features.cycle.program.entities").Carrier
    start = carrier._start

    def spy(self: Any) -> None:
        started.append(self)
        start(self)

    monkeypatch.setattr(carrier, "_start", spy)
    with monkeypatch.context() as failing:
        forward_then_fail(ha, failing)
        assert await setup(ha, DEVICES)
    [entry] = ha.config_entries.async_entries("pururu")
    assert entry.state is ConfigEntryState.SETUP_ERROR
    removed = ha.states.get(RUNNING)
    assert removed is not None
    assert removed.state == "unavailable"
    assert removed.attributes["restored"]  # HA's placeholder: the entity is gone
    assert not started
    await reload(ha, DEVICES)
    assert started
    assert entry.state is ConfigEntryState.LOADED
    assert state(ha, RUNNING) == "off"
    await cool(ha, freezer)


async def test_an_entry_failing_after_its_platforms_kept_still_runs_the_carrier(
        ha: HomeAssistant, freezer: Any, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    """The platforms not unloaded either: SETUP_ERROR, HA keeps the entities, and the carrier follows the reading."""
    forward_then_fail(ha, monkeypatch)

    async def not_unloaded(entry: Any, platforms: Any) -> bool:
        return False

    monkeypatch.setattr(ha.config_entries, "async_unload_platforms", not_unloaded)
    assert await setup(ha, DEVICES)
    [entry] = ha.config_entries.async_entries("pururu")
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert "Unloading the platforms of a failed setup left some" in caplog.text
    assert state(ha, RUNNING) == "off"
    await cool(ha, freezer)


async def test_a_reload_mid_phase_counts_one_cycle(purifier: HomeAssistant, freezer: Any) -> None:
    await cool(purifier, freezer)
    started = dt_util.utcnow() - timedelta(seconds=5)
    await tick(purifier, freezer, 600)
    await reload(purifier, DEVICES)
    assert state(purifier, CURRENT) == "resfriar"
    await tick(purifier, freezer, 600)
    await watts(purifier, IDLE_W)
    await tick(purifier, freezer, 35)
    assert state(purifier, sensor("phase_resfriar_cycles_total")) == "1"
    assert dt_util.parse_datetime(state(purifier, sensor("phase_resfriar_last_cycle_start"))) == started


async def test_a_carrier_renamed_mid_phase_follows_the_reading(
        purifier: HomeAssistant, freezer: Any) -> None:
    """Renamed in the UI: HA adds it again to the loaded entry, then the entry reloads; the phase's cycle counts once."""
    await cool(purifier, freezer)
    renamed = "binary_sensor.dummy_station_program"
    er.async_get(purifier).async_update_entity(RUNNING, new_entity_id=renamed)
    await purifier.async_block_till_done()
    assert state(purifier, renamed) == "on"
    assert state(purifier, RESFRIAR) == "on"
    await watts(purifier, IDLE_W)
    await tick(purifier, freezer, 125)
    assert state(purifier, renamed) == "off"
    assert state(purifier, sensor("phase_resfriar_cycles_total")) == "1"


async def test_a_phases_totals_restore(ha: HomeAssistant) -> None:
    await restart(
        ha, DEVICES,
        (State(sensor("phase_resfriar_cycles_total"), "7"), {"native_value": 7, "native_unit_of_measurement": None}),
        (State(sensor("phase_resfriar_energy_total"), "1.2"), {"native_value": 1.2, "native_unit_of_measurement": "kWh"}),
        (State(sensor("phase_resfriar_runtime_total"), "3.5"), {"native_value": 3.5, "native_unit_of_measurement": "h"}),
    )
    assert state(ha, sensor("phase_resfriar_cycles_total")) == "7"
    assert float(state(ha, sensor("phase_resfriar_energy_total"))) == 1.2
    assert float(state(ha, sensor("phase_resfriar_runtime_total"))) == 3.5


async def test_a_reload_while_a_phase_is_pending(
        purifier: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    """A delay pending at the reload dies with its carrier: no error, no phase from it; the new carrier counts from its first reading."""
    await watts(purifier, 120)
    await tick(purifier, freezer, 25)
    assert state(purifier, RUNNING) == "on"
    await reload(purifier, DEVICES)
    await tick(purifier, freezer, 10)
    assert [r.getMessage() for r in caplog.records if r.levelname == "ERROR"] == []
    assert state(purifier, CURRENT) == "idle"
    await tick(purifier, freezer, 25)
    assert state(purifier, CURRENT) == "resfriar"


async def test_last_restores(ha: HomeAssistant) -> None:
    await restart(ha, DEVICES, (State(LAST, "quente"), {
        "native_value": "quente", "native_unit_of_measurement": None}))
    assert state(ha, LAST) == "quente"


# --- names ------------------------------------------------------------------------------

NAMES = {
    "en": {RESFRIAR: "Dummy station Resfriar", OTHER: "Dummy station Other phase",
           CURRENT: "Dummy station Phase", LAST: "Dummy station Last phase",
           sensor("phase_quente_cycles_total"): "Dummy station Água quente cycles",
           sensor("phase_resfriar_last_cycle_start"): "Dummy station Resfriar last cycle start",
           sensor("phase_other_runtime_total"): "Dummy station Other phase runtime"},
    "pt-BR": {RESFRIAR: "Dummy station Resfriar", OTHER: "Dummy station Outra fase",
              CURRENT: "Dummy station Fase", LAST: "Dummy station Última fase",
              sensor("phase_quente_cycles_total"): "Dummy station Ciclos de Água quente",
              sensor("phase_resfriar_last_cycle_start"): "Dummy station Início do último ciclo de Resfriar",
              sensor("phase_other_runtime_total"): "Dummy station Tempo de outra fase"},
}


@pytest.mark.parametrize("language", ["en", "pt-BR"])
async def test_names(ha: HomeAssistant, language: str) -> None:
    """A phase's binary sensor is its name; its cycle entities carry it; other's and the detector's are translated."""
    ha.config.language = language
    assert await setup(ha, DEVICES)
    for entity_id, name in NAMES[language].items():
        assert ha.states.get(entity_id).attributes["friendly_name"] == name, entity_id
    if language == "en":
        assert ha.states.get(sensor("phase_resfriar_cycles_total")).attributes[
            "unit_of_measurement"] == "cycles"


# --- what refers to a phase ------------------------------------------------------------

HOT = "binary_sensor.pururu_dummy_station_alert_hot"


def with_alert(**alert: Any) -> dict[str, Any]:
    return {KEY: {**DEVICES[KEY], "alerts": {"hot": {"name": "Esquentando", **alert}}}}


async def test_an_alert_can_watch_the_current_phase(ha: HomeAssistant, freezer: Any) -> None:
    assert await setup(ha, with_alert(when="appliance_phase_current", **{"is": "quente"}))
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 125)
    assert state(ha, HOT) == "off"
    await watts(ha, 1000)
    await tick(ha, freezer, 25)
    assert state(ha, HOT) == "on"


async def test_an_alert_can_watch_a_phases_binary_sensor(ha: HomeAssistant, freezer: Any) -> None:
    assert await setup(ha, with_alert(when="appliance_phase_quente", **{"is": "on"}))
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 125)
    assert state(ha, HOT) == "off"
    await watts(ha, 1000)
    await tick(ha, freezer, 25)
    assert state(ha, HOT) == "on"


async def test_an_alert_can_watch_a_phases_total(ha: HomeAssistant) -> None:
    assert await setup(ha, with_alert(when="appliance_phase_quente_cycles_total", above=10))
    assert state(ha, HOT) == "off"


async def test_a_reaction_can_watch_a_phase(ha: HomeAssistant) -> None:
    devices = {KEY: {**DEVICES[KEY], "reactions": {
        "hot": {"name": "Quente", "when": "appliance_phase_quente", "to": "on"}}}}
    assert await setup(ha, devices)
    assert generated(ha)[0]["triggers"][0]["entity_id"] == QUENTE


@pytest.mark.parametrize("when", [
    pytest.param("appliance_phase_morno_cycles_total", id="a phase not configured"),
    pytest.param("appliance_phase_morno", id="its binary sensor"),
])
async def test_a_reference_to_a_phase_not_configured_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, when: str) -> None:
    assert not await setup(ha, with_alert(when=when, above=10))
    assert f"alerts: {when} is not an entity key of another feature of this device" in caplog.text


async def test_no_phase_keys_without_phases(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Without phases the appliance creates no phase entity, so none can be named."""
    devices = {KEY: {"name": "Dummy station",
                     "appliance": {"power": POWER, "running_program": {"above": 4}},
                     "alerts": {"hot": {"name": "Esquentando", "when": "appliance_phase_current",
                                        "is": "quente"}}}}
    assert not await setup(ha, devices)
    assert ("alerts: appliance_phase_current is not an entity key of another feature "
            "of this device") in caplog.text


async def test_a_renamed_phase_is_followed(purifier: HomeAssistant, freezer: Any) -> None:
    """Renamed in the UI: the entry reloads, and the phase's runtime follows the new ID."""
    renamed = "binary_sensor.dummy_station_resfriar"
    er.async_get(purifier).async_update_entity(RESFRIAR, new_entity_id=renamed)
    await purifier.async_block_till_done()
    await cool(purifier, freezer)
    assert state(purifier, renamed) == "on"
    await tick(purifier, freezer, 600)
    await watts(purifier, IDLE_W)
    await tick(purifier, freezer, 35)
    assert float(state(purifier, sensor("phase_resfriar_runtime_total"))) == pytest.approx(
        605 / 3600, abs=0.0005)
