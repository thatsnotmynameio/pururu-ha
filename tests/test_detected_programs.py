"""A feature's detected programs, `programs: detected:` in an appliance's block (aspects/programs.py).

Each is a band of the appliance's power, as its running program is: a made-up
washer whose cotton wash draws over 1500 W. Its entity IDs are
<platform>.pururu_<device>_appliance_<key>[_<suffix>].
"""

from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, State
import pytest
import voluptuous as vol

from helpers import DOMAIN, fake, held, module, restart, setup, snapshot, tick

KEY = "clothes_washer"
POWER = "sensor.washer_plug_power"
ENERGY = "sensor.washer_plug_energy"
PREFIX = f"pururu_{KEY}_appliance"
RUNNING = f"binary_sensor.{PREFIX}_running"
COTTON = f"binary_sensor.{PREFIX}_cotton"
RUNNING_PROGRAM: dict[str, Any] = {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}}
DETECTED: dict[str, Any] = {"cotton": {"name": "Algodão", "above": 1500, "on_delay": {"minutes": 5}}}
LAST_CYCLE = ("last_cycle_start", "last_cycle_end", "last_cycle_duration", "last_cycle_energy")
SUFFIXES = (*LAST_CYCLE, "cycles_total", "runtime_total", "energy_total")


def appliance(**block: Any) -> dict[str, Any]:
    """The washer's appliance block with its detected programs, `block` over it."""
    return {"power": POWER, "energy": ENERGY, "running_program": RUNNING_PROGRAM,
            "programs": {"detected": DETECTED}, **block}


def devices(**block: Any) -> dict[str, Any]:
    return {KEY: {"name": "Tanquinho", "appliance": appliance(**block)}}


def sensor(entity_key: str) -> str:
    return f"sensor.{PREFIX}_{entity_key}"


def state(hass: HomeAssistant, entity_id: str) -> str:
    found = hass.states.get(entity_id)
    assert found is not None, entity_id
    return found.state


async def watts(hass: HomeAssistant, value: float) -> None:
    await fake(hass, POWER, str(value))


@pytest.fixture
async def washer(ha: HomeAssistant, freezer: Any) -> HomeAssistant:
    """Idle at 1 W, long enough to count as not running."""
    await fake(ha, ENERGY, "100")
    assert await setup(ha, devices())
    await watts(ha, 1)
    await tick(ha, freezer, 125)
    return ha


# --- what it creates ----------------------------------------------------------------


async def test_its_entities_and_their_ids(washer: HomeAssistant) -> None:
    """Its carrier and cycle entities, in the appliance's namespace, beside the appliance's own."""
    found = held(washer, KEY)
    assert COTTON in found
    assert {sensor(f"cotton_{suffix}") for suffix in SUFFIXES} <= found
    assert not {entity_id for entity_id in found if "_cotton_phase" in entity_id}


async def test_without_energy_no_energy_entity(ha: HomeAssistant) -> None:
    block = {key: value for key, value in appliance().items() if key != "energy"}
    assert await setup(ha, {KEY: {"name": "Tanquinho", "appliance": block}})
    found = held(ha, KEY)
    assert sensor("cotton_cycles_total") in found
    assert not {sensor("cotton_energy_total"), sensor("cotton_last_cycle_energy")} & found


async def test_it_runs_and_counts_apart_from_the_running_program(
        washer: HomeAssistant, freezer: Any) -> None:
    """A cotton wash is the appliance running and cotton running; a wash under 1500 W is only the appliance's."""
    await watts(washer, 2000)
    await tick(washer, freezer, 60)
    assert (state(washer, RUNNING), state(washer, COTTON)) == ("on", "off")
    await tick(washer, freezer, 240)
    assert state(washer, COTTON) == "on"
    await tick(washer, freezer, 240)
    await fake(washer, ENERGY, "101.5")
    await watts(washer, 1)
    await tick(washer, freezer, 125)
    assert (state(washer, RUNNING), state(washer, COTTON)) == ("off", "off")
    assert state(washer, sensor("cycles_total")) == "1"
    assert state(washer, sensor("cotton_cycles_total")) == "1"
    assert float(state(washer, sensor("cotton_last_cycle_duration"))) == 4.0
    assert float(state(washer, sensor("cotton_energy_total"))) == pytest.approx(1.5)
    await watts(washer, 500)
    await tick(washer, freezer, 600)
    await watts(washer, 1)
    await tick(washer, freezer, 125)
    assert state(washer, sensor("cycles_total")) == "2"
    assert state(washer, sensor("cotton_cycles_total")) == "1"


async def test_a_restart_keeps_a_running_detected_program(ha: HomeAssistant, freezer: Any) -> None:
    """Its carrier restores its own snapshot, as the running program's does."""
    since = "2026-09-16T16:50:00+00:00"
    await restart(ha, devices(), (State(RUNNING, "on"), snapshot(since)),
                  (State(COTTON, "on"), snapshot(since)))
    await watts(ha, 2000)
    await tick(ha, freezer, 1)
    assert state(ha, COTTON) == "on"
    assert ha.states.get(COTTON).attributes["cycle_start"].isoformat() == since


@pytest.mark.parametrize(("language", "names"), [
    pytest.param("en", {COTTON: "Tanquinho Algodão", sensor("cotton_cycles_total"): "Tanquinho Algodão cycles",
                        sensor("cotton_last_cycle_start"): "Tanquinho Algodão last cycle start"}, id="en"),
    pytest.param("pt-BR", {COTTON: "Tanquinho Algodão", sensor("cotton_cycles_total"): "Tanquinho Ciclos de Algodão",
                           sensor("cotton_last_cycle_start"): "Tanquinho Início do último ciclo de Algodão"},
                 id="pt-BR"),
])
async def test_a_detected_program_is_named_after_its_name(
        ha: HomeAssistant, language: str, names: dict[str, str]) -> None:
    ha.config.language = language
    assert await setup(ha, devices())
    for entity_id, name in names.items():
        assert ha.states.get(entity_id).attributes["friendly_name"] == name


async def test_its_statistics(ha: HomeAssistant) -> None:
    """`statistics:` in the detected program: its runtime, cycles and energy per period."""
    cotton = {**DETECTED["cotton"], "statistics": {"cycles": ["today"], "energy": ["month"]}}
    assert await setup(ha, devices(programs={"detected": {"cotton": cotton}}))
    assert {sensor("cotton_cycles_today"), sensor("cotton_energy_month")} <= held(ha, KEY)


# --- where it sits, and what it can't be ------------------------------------------


@pytest.mark.parametrize(("programs", "message"), [
    pytest.param({"executable": {"clean": {"name": "Limpar", "sequence": [{"delay": 1}]}}},
                 "a feature's programs are detected: executable programs are the device's",
                 id="an executable program in a feature"),
    pytest.param({}, "a feature's programs needs detected", id="empty"),
    pytest.param({"detected": {}}, "length of value must be at least 1", id="no program"),
    pytest.param({"detected": {"cotton": {"above": 1500}}},
                 "a detected program needs a name: it names its entities", id="no name"),
    pytest.param({"detected": {"cotton": {"name": "Algodão"}}}, "a program needs above, below or both",
                 id="no band"),
    pytest.param({"detected": {"cotton": {"name": "Algodão", "above": 1500, "sequence": [{"delay": 1}]}}},
                 "'sequence' is an invalid option", id="a sequence"),
    pytest.param({"detected": {"cotton": {"name": "Algodão", "above": 1500, "statistics": {"cycles": ["daily"]}}}},
                 "value must be one of", id="an unknown period"),
])
async def test_where_programs_sit(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, programs: Any, message: str) -> None:
    assert not await setup(ha, devices(programs=programs))
    assert message in caplog.text


async def test_an_executable_program_takes_no_band(ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """A device's program is executable: `above` is a detected program's."""
    clean = {"name": "Limpar", "above": 1500, "sequence": [{"delay": 1}]}
    config = devices()
    config[KEY]["programs"] = {"executable": {"clean": clean}}
    assert not await setup(ha, config)
    assert "'above' is an invalid option" in caplog.text


async def test_its_energy_needs_the_appliances(ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    cotton = {**DETECTED["cotton"], "statistics": {"energy": ["today"]}}
    block = {key: value for key, value in appliance(programs={"detected": {"cotton": cotton}}).items()
             if key != "energy"}
    assert not await setup(ha, {KEY: {"name": "Tanquinho", "appliance": block}})
    assert "statistics.energy needs energy" in caplog.text


async def test_then_names_an_executable_program(ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """A detected program can't be started: a reaction's then names an executable one."""
    config = devices()
    config[KEY]["reactions"] = {"it": {"name": "X", "at": "08:00", "then": "cotton"}}
    assert not await setup(ha, config)
    assert "reactions: it: cotton is not an executable program of this device" in caplog.text


async def test_a_step_on_a_detected_program_is_refused(ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    config = devices()
    config[KEY]["programs"] = {"executable": {"start": {"name": "X", "sequence": [{"turn_on": "appliance_cotton"}]}}}
    assert not await setup(ha, config)
    assert "programs: appliance_cotton does not take turn_on" in caplog.text


async def test_an_alert_and_a_reaction_can_watch_it(ha: HomeAssistant) -> None:
    config = devices()
    config[KEY]["alerts"] = {"long": {"name": "Longo", "when": "appliance_cotton", "is": "on", "for": {"hours": 3}}}
    config[KEY]["reactions"] = {"done": {"name": "Pronto", "when": "appliance_cotton", "from": "on", "to": "off"}}
    assert await setup(ha, config)
    assert ha.states.get(f"binary_sensor.pururu_{KEY}_alert_long") is not None


def reserved(block: dict[str, Any]) -> set[str]:
    """Every key a detected program can't take in this appliance's block, computed.

    Each key the block lists (catalogue.keys: the appliance's own, its derived,
    its ready-made alerts', every meter), as the program's carrier; and each
    key that is the program's key plus one of its suffixes (its cycle
    entities', its meters').
    """
    catalogue = module("setup.catalogue")
    statistics = module("aspects.statistics")
    program = module("features.cycle.program")
    appliance_ = catalogue.builders()["appliance"]
    listed = {key for _, key, *_ in catalogue.keys({"appliance": catalogue.mount(appliance_, "appliance", block)})}
    suffixes = [*program.SUFFIXES,
                *(f"{counter}_{period}" for counter in program.PHASE_COUNTERS for period in statistics.PERIODS)]
    return listed | {key.removesuffix(f"_{suffix}") for key in listed for suffix in suffixes
                     if key.endswith(f"_{suffix}") and key != suffix}


# The appliance with everything that adds keys: energy, a phase and other
FULL = {"power": POWER, "energy": ENERGY, "running_program": {
    **RUNNING_PROGRAM, "phases": {"warming": {"name": "Aquecendo", "above": 1000}}, "other": {}}}


def test_the_reserved_keys(ha: HomeAssistant) -> None:
    """What reserved() computes, for the record: the appliance's own and its running program's keys, and idle."""
    keys = reserved(FULL)
    assert {"power", "running", "cycles_total", "idle_energy_total", "idle", "alert_offline",
            "runtime_today", "phase_current", "phase_warming", "phase_other_cycles_total"} <= keys
    assert "cotton" not in keys


async def test_a_detected_program_may_not_take_a_key_of_the_appliance(ha: HomeAssistant) -> None:
    """Each reserved key, as a detected program's, is refused at the configuration (checks.keys_distinct); cotton passes."""
    schema = module("setup.schema").CONFIG_SCHEMA
    for key in sorted(reserved(FULL)):
        detected = {key: {"name": "X", "above": 1500}}
        house = {"devices": {KEY: {"name": "Tanquinho", "appliance": {**FULL, "programs": {"detected": detected}}}}}
        with pytest.raises(vol.Invalid, match="would be two entities"):
            schema({DOMAIN: house})
    house = {"devices": {KEY: {"name": "Tanquinho", "appliance": {**FULL, "programs": {"detected": DETECTED}}}}}
    schema({DOMAIN: house})


async def test_detected_programs_may_not_take_each_others_keys(ha: HomeAssistant) -> None:
    """Each key cotton creates, as another detected program's key, is refused (Place.derived's pairs)."""
    schema = module("setup.schema").CONFIG_SCHEMA
    program = module("features.cycle.program")
    cotton = DETECTED["cotton"]
    for key in sorted(set(program.detected_keys("cotton")) - {"cotton"}):
        detected = {"cotton": cotton, key: {"name": "X", "above": 1500}}
        house = {"devices": {KEY: {"name": "Tanquinho", "appliance": appliance(programs={"detected": detected})}}}
        with pytest.raises(vol.Invalid, match="would be two entities"):
            schema({DOMAIN: house})


def test_its_keys_are_in_the_index(ha: HomeAssistant) -> None:
    """By the programs aspect, in the appliance's namespace."""
    catalogue = module("setup.catalogue")
    appliance_ = catalogue.builders()["appliance"]
    rows = {key: (platform, by) for _, key, platform, by, _ in catalogue.keys(
        {"appliance": catalogue.mount(appliance_, "appliance", appliance())})}
    assert rows["cotton"] == (Platform.BINARY_SENSOR, "programs")
    assert rows["cotton_cycles_total"] == (Platform.SENSOR, "programs")
    assert rows["cotton_cycles_today"] == (Platform.SENSOR, "statistics")
