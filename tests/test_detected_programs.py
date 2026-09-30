"""A feature's detected programs, `programs: detected:` in an appliance's block (aspects/programs.py).

Each is a band of the appliance's power, as its running program is: a made-up
washer whose cotton wash draws over 1500 W. Its entity IDs are
<platform>.pururu_<device>_appliance_<key>[_<suffix>], and with phases
…_<key>_phase_<phase>[_<suffix>] and …_<key>_phase_current/_last.
"""

import re
from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, State
import pytest
import voluptuous as vol

from helpers import DOMAIN, capture, fake, generated, held, module, restart, setup, snapshot, tick

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


# Cotton heats its water over 1800 W; the appliance's running program warms over 1000 W
WARMING: dict[str, Any] = {"name": "Aquecendo", "above": 1800}
PHASED: dict[str, Any] = {"cotton": {**DETECTED["cotton"], "phases": {"warming": WARMING}, "other": {}}}


def phased(**block: Any) -> dict[str, Any]:
    """The washer whose running program warms over 1000 W and whose cotton program heats over 1800 W."""
    return devices(**{"running_program": {**RUNNING_PROGRAM, "phases": {"warming": {"name": "Aquecendo", "above": 1000}}},
                      "programs": {"detected": PHASED}, **block})


def sensor(entity_key: str) -> str:
    return f"sensor.{PREFIX}_{entity_key}"


def paths(refused: vol.Invalid) -> list[list[Any]]:
    """Where each of its refusals is."""
    errors = refused.errors if isinstance(refused, vol.MultipleInvalid) else [refused]
    return [error.path for error in errors]


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
    """Its carrier restores its own snapshot, as the running program's does: each its own start."""
    running, cotton = "2026-09-16T16:50:00+00:00", "2026-09-16T16:57:00+00:00"
    await restart(ha, devices(), (State(RUNNING, "on"), snapshot(running)),
                  (State(COTTON, "on"), snapshot(cotton)))
    await watts(ha, 2000)
    await tick(ha, freezer, 1)
    assert (state(ha, RUNNING), state(ha, COTTON)) == ("on", "on")
    assert ha.states.get(RUNNING).attributes["cycle_start"].isoformat() == running
    assert ha.states.get(COTTON).attributes["cycle_start"].isoformat() == cotton


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
    pytest.param({}, "a feature's programs needs detected "
                 "'pururu->devices->clothes_washer->appliance->programs'", id="empty"),
    pytest.param({"cotton": DETECTED["cotton"]}, "a feature's programs needs detected "
                 "'pururu->devices->clothes_washer->appliance->programs'", id="a flat map"),
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


async def test_an_alert_and_a_reaction_can_watch_it(ha: HomeAssistant, freezer: Any) -> None:
    """The alert follows the carrier, and the reaction's automation triggers on it."""
    config = devices()
    config[KEY]["alerts"] = {"long": {"name": "Longo", "when": "appliance_cotton", "is": "on", "for": {"hours": 3}}}
    config[KEY]["reactions"] = {"done": {"name": "Pronto", "when": "appliance_cotton", "from": "on", "to": "off"}}
    await fake(ha, ENERGY, "100")
    assert await setup(ha, config)
    (reaction,) = [each for each in generated(ha) if each["id"] == f"pururu_{KEY}_reaction_done"]
    assert [trigger["entity_id"] for trigger in reaction["triggers"]] == [COTTON]
    long = f"binary_sensor.pururu_{KEY}_alert_long"
    await watts(ha, 1)
    await tick(ha, freezer, 125)
    await watts(ha, 2000)
    await tick(ha, freezer, 300)
    assert (state(ha, COTTON), state(ha, long)) == ("on", "off")
    await tick(ha, freezer, 3 * 60 * 60)
    assert state(ha, long) == "on"


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


# The refusal of a detected program keyed as the running program's phases' keys start, or cotton's
RUNNING_ONLY = "is reserved for the running program's phases (phase, phase_…): name the program otherwise"
COTTONS = "is reserved for detected program cotton's phases (cotton_phase, cotton_phase_…): name the program otherwise"


def refusal(key: str) -> tuple[str, list[Any]]:
    """What refuses a detected program keyed `key` beside cotton, and where.

    A phase's form (phase[_…], cotton_phase[_…]) at the program, by its
    block's schema; any other key at the device, as two entities
    (checks.keys_distinct).
    """
    for form, message in (("phase", RUNNING_ONLY), ("cotton_phase", COTTONS)):
        if key == form or key.startswith(f"{form}_"):
            return f"^{re.escape(f'{key} {message}')}", [
                DOMAIN, "devices", KEY, "appliance", "programs", "detected", key]
    return "would be two entities", [DOMAIN, "devices", KEY]


async def test_a_detected_program_may_not_take_a_key_of_the_appliance(ha: HomeAssistant) -> None:
    """Each reserved key, as a detected program's, is refused at the configuration; cotton passes."""
    schema = module("setup.schema").CONFIG_SCHEMA
    for key in sorted(reserved(FULL)):
        detected = {key: {"name": "X", "above": 1500}}
        house = {"devices": {KEY: {"name": "Tanquinho", "appliance": {**FULL, "programs": {"detected": detected}}}}}
        match, path = refusal(key)
        with pytest.raises(vol.Invalid, match=match) as refused:
            schema({DOMAIN: house})
        assert path in paths(refused.value), key
    house = {"devices": {KEY: {"name": "Tanquinho", "appliance": {**FULL, "programs": {"detected": DETECTED}}}}}
    schema({DOMAIN: house})


async def test_detected_programs_may_not_take_each_others_keys(ha: HomeAssistant) -> None:
    """Each key cotton creates (with a phase and other), as another detected program's key, is refused.

    Its carrier's, cycle entities' and phases' (Place.derived's pairs:
    cotton_phase_current, cotton_phase_warming, cotton_phase_other_cycles_total…),
    and each of its meters', its phases' and other's (the statistics aspect's
    rows, by their items): listed whether asked for or not.
    """
    catalogue = module("setup.catalogue")
    schema = module("setup.schema").CONFIG_SCHEMA
    program = module("features.cycle.program")
    periods = module("aspects.statistics").PERIODS
    cotton = {**PHASED["cotton"],
              "statistics": {counter: list(periods) for counter in program.PHASE_COUNTERS}}
    block = catalogue.mount(catalogue.builders()["appliance"], "appliance",
                            appliance(programs={"detected": {"cotton": cotton}}))
    items = {"cotton", "cotton_phase_warming", "cotton_phase_other"}
    meters = {key for _, key, _, by, item in catalogue.keys({"appliance": block})
              if by == "statistics" and item in items}
    assert len(meters) == len(items) * len(program.PHASE_COUNTERS) * len(periods)
    derived = set(program.detected_keys("cotton", cotton))
    assert {"cotton_phase_current", "cotton_phase_warming", "cotton_phase_other_cycles_total"} <= derived
    for key in sorted((derived | meters) - {"cotton"}):
        detected = {"cotton": cotton, key: {"name": "X", "above": 1500}}
        house = {"devices": {KEY: {"name": "Tanquinho", "appliance": appliance(programs={"detected": detected})}}}
        match, path = refusal(key)
        with pytest.raises(vol.Invalid, match=match) as refused:
            schema({DOMAIN: house})
        assert path in paths(refused.value), key


def test_its_keys_are_in_the_index(ha: HomeAssistant) -> None:
    """By the programs aspect, in the appliance's namespace."""
    catalogue = module("setup.catalogue")
    appliance_ = catalogue.builders()["appliance"]
    rows = {key: (platform, by) for _, key, platform, by, _ in catalogue.keys(
        {"appliance": catalogue.mount(appliance_, "appliance", appliance())})}
    assert rows["cotton"] == (Platform.BINARY_SENSOR, "programs")
    assert rows["cotton_cycles_total"] == (Platform.SENSOR, "programs")
    assert rows["cotton_cycles_today"] == (Platform.SENSOR, "statistics")


# --- keys a later setting would create ----------------------------------------------


# A plain detected program, and one heating over 1800 W without other:
PLAIN: dict[str, Any] = {"name": "X", "above": 1500}
PHASED_ONLY: dict[str, Any] = {**PLAIN, "phases": {"warming": WARMING}}
PHASES = {"phases": {"warming": {"name": "Aquecendo", "above": 1000}}}


def house(running: dict[str, Any], detected: dict[str, Any]) -> dict[str, Any]:
    """The washer's configuration: its running program's settings over RUNNING_PROGRAM, and its detected programs."""
    block = {"power": POWER, "running_program": {**RUNNING_PROGRAM, **running}, "programs": {"detected": detected}}
    return {DOMAIN: {"devices": {KEY: {"name": "Tanquinho", "appliance": block}}}}


@pytest.mark.parametrize(("key", "now", "later", "message"), [
    # The running program's: its fixed keys, a phase's, other's and other's meters, once it has phases
    pytest.param("phase_current", ({}, {}), (PHASES, {}), RUNNING_ONLY, id="the running program's current phase"),
    pytest.param("phase_warming", ({}, {}), (PHASES, {}), RUNNING_ONLY, id="the running program's phase"),
    pytest.param("phase", ({}, {}), ({"phases": {"cycles_total": WARMING}}, {}), RUNNING_ONLY,
                 id="phase, beside a phase's cycles_total"),
    pytest.param("phase_idle", ({}, {}), ({"phases": {"idle_cycles_total": WARMING}}, {}), RUNNING_ONLY,
                 id="phase_idle, though idle is no phase"),
    pytest.param("phase_other", ({}, {}), (PHASES, {}), RUNNING_ONLY, id="the running program's other"),
    pytest.param("phase_other_runtime_today", (PHASES, {}), ({**PHASES, "other": {}}, {}), RUNNING_ONLY,
                 id="other's meter, once other is set"),
    # Another detected program's, once it has phases
    pytest.param("cotton_phase_current", ({}, {"cotton": PLAIN}), ({}, {"cotton": PHASED_ONLY}), COTTONS,
                 id="cotton's current phase"),
    pytest.param("cotton_phase_warming", ({}, {"cotton": PLAIN}), ({}, {"cotton": PHASED_ONLY}), COTTONS,
                 id="cotton's phase"),
    pytest.param("cotton_phase", ({}, {"cotton": PLAIN}), ({}, {"cotton": {**PLAIN, "phases": {"cycles_total": WARMING}}}),
                 COTTONS, id="cotton_phase, beside a phase's cycles_total"),
    pytest.param("cotton_phase_other_cycles_today", ({}, {"cotton": PHASED_ONLY}),
                 ({}, {"cotton": {**PHASED_ONLY, "other": {}}}), COTTONS, id="cotton's other's meter, once other is set"),
])
def test_a_key_a_later_setting_would_create_is_refused_now(
        ha: HomeAssistant, key: str, now: tuple[dict[str, Any], dict[str, Any]],
        later: tuple[dict[str, Any], dict[str, Any]], message: str) -> None:
    """A detected program keyed as a phase's keys start is refused before the setting that makes the phase.

    Else adding phases (or other) to the running program, or to another
    detected program, would refuse the configuration then.
    """
    schema = module("setup.schema").CONFIG_SCHEMA
    match, path = refusal(key)
    assert match == f"^{re.escape(f'{key} {message}')}"
    for running, detected in (now, later):
        config = house(running, {**detected, key: PLAIN})
        with pytest.raises(vol.Invalid, match=match) as refused:
            schema(config)
        assert path in paths(refused.value)


@pytest.mark.parametrize("key", [
    # The appliance's energy, without energy
    "energy_total", "last_cycle_energy", "idle_energy_today",
    # Meters, without statistics: the appliance's, its running program's, another detected program's
    "runtime_week", "cycles_year", "cotton_energy_month",
    # A ready-made alert, not enabled
    "alert_offline",
])
def test_a_key_a_later_setting_creates_is_listed_already(ha: HomeAssistant, key: str) -> None:
    """Every other key a setting adds is listed whatever the settings (catalogue.keys): refused already, as two entities."""
    schema = module("setup.schema").CONFIG_SCHEMA
    config = house({}, {"cotton": PLAIN, key: PLAIN})
    with pytest.raises(vol.Invalid, match="would be two entities"):
        schema(config)


@pytest.mark.parametrize("key", ["phases", "phaser", "cotton_phases", "rinse_phase", "rinse_phase_warming"])
def test_a_key_no_phase_can_take_passes(ha: HomeAssistant, key: str) -> None:
    """Only phase[_…] and a present program's <program>_phase[_…] are reserved; rinse is no program here."""
    module("setup.schema").CONFIG_SCHEMA(house(PHASES, {"cotton": PHASED_ONLY, key: PLAIN}))


# The refusal of a phase keyed as the built-in other's keys begin
OTHERS = "is reserved for the built-in phase other (other, other_…): name the phase otherwise"


@pytest.mark.parametrize(("of", "key"), [
    pytest.param(None, "other_cycles_today", id="the running program's phase, as other's cycles today"),
    pytest.param(None, "other_energy_month", id="the running program's phase, as other's energy this month"),
    pytest.param("cotton", "other_runtime_week", id="cotton's phase, as its other's runtime this week"),
])
def test_a_phase_key_other_would_take_later_is_refused_now(ha: HomeAssistant, of: str | None, key: str) -> None:
    """A phase keyed as one of other's meters is refused before `other:` is set.

    other's meters are listed only once `other:` is written: were the key
    accepted without it, writing `other:` would refuse the configuration then
    (… would be two entities).
    """
    schema = module("setup.schema").CONFIG_SCHEMA
    phases = {"phases": {"warming": WARMING, key: WARMING}}
    where = (["running_program"] if of is None else ["programs", "detected", of]) + ["phases", key]
    for other in ({}, {"other": {}}):
        if of is None:
            config = house({**phases, **other}, {"cotton": PLAIN})
        else:
            config = house({}, {of: {**PLAIN, **phases, **other}})
        with pytest.raises(vol.Invalid, match=f"^{re.escape(f'{key} {OTHERS}')}") as refused:
            schema(config)
        assert [DOMAIN, "devices", KEY, "appliance", *where] in paths(refused.value)


# --- its phases ---------------------------------------------------------------------


async def test_its_phases_entities_and_ids(ha: HomeAssistant) -> None:
    """<key>_phase_<phase>…, <key>_phase_current and _last, beside the running program's phase_… of the same key."""
    assert await setup(ha, phased())
    found = held(ha, KEY)
    for phase in ("warming", "other"):
        assert f"binary_sensor.{PREFIX}_cotton_phase_{phase}" in found
        assert {sensor(f"cotton_phase_{phase}_{suffix}") for suffix in SUFFIXES} <= found
    assert {sensor("cotton_phase_current"), sensor("cotton_phase_last"), sensor("phase_current"),
            f"binary_sensor.{PREFIX}_phase_warming"} <= found


async def test_a_detected_programs_phases_count_apart(ha: HomeAssistant, freezer: Any) -> None:
    """Cotton's warming and the running program's warming run on their own signals: each counts its own cycles."""
    await fake(ha, ENERGY, "100")
    assert await setup(ha, phased())
    await watts(ha, 1)
    await tick(ha, freezer, 125)
    await watts(ha, 2000)
    await tick(ha, freezer, 600)
    assert state(ha, sensor("cotton_phase_current")) == "warming"
    await watts(ha, 1)
    await tick(ha, freezer, 125)
    assert state(ha, sensor("phase_warming_cycles_total")) == "1"
    assert state(ha, sensor("cotton_phase_warming_cycles_total")) == "1"
    assert state(ha, sensor("cotton_phase_last")) == "warming"
    await watts(ha, 1200)
    await tick(ha, freezer, 600)
    await watts(ha, 1)
    await tick(ha, freezer, 125)
    assert state(ha, sensor("phase_warming_cycles_total")) == "2"
    assert state(ha, sensor("cotton_phase_warming_cycles_total")) == "1"


async def test_a_restart_keeps_a_detected_programs_phase(ha: HomeAssistant) -> None:
    """Cotton's carrier restores its phase's run, as the running program's does: from its own start, with no reading yet."""
    since = "2026-09-16T16:50:00+00:00"
    warming, current = f"binary_sensor.{PREFIX}_cotton_phase_warming", sensor("cotton_phase_current")
    changes = capture(ha, "state_changed")
    await restart(ha, phased(), (State(COTTON, "on"), snapshot(since, warming={"since": since})),
                  (State(warming, "on"), {}), (State(current, "warming"), {}))
    assert state(ha, warming) == "on"
    assert ha.states.get(warming).attributes["cycle_start"].isoformat() == since
    assert state(ha, current) == "warming"
    assert ha.states.get(current).attributes["name"] == "Aquecendo"
    shown = [event.data["new_state"].state for event in changes if event.data["entity_id"] in (warming, current)]
    assert "off" not in shown, shown
    assert "idle" not in shown, shown


@pytest.mark.parametrize(("language", "names"), [
    pytest.param("en", {
        sensor("cotton_phase_current"): "Tanquinho Algodão phase",
        sensor("cotton_phase_last"): "Tanquinho Algodão last phase",
        f"binary_sensor.{PREFIX}_cotton_phase_warming": "Tanquinho Aquecendo",
        sensor("cotton_phase_warming_cycles_total"): "Tanquinho Aquecendo cycles",
        sensor("cotton_phase_warming_cycles_today"): "Tanquinho Aquecendo cycles today",
        f"binary_sensor.{PREFIX}_cotton_phase_other": "Tanquinho Algodão other phase",
        sensor("cotton_phase_other_cycles_total"): "Tanquinho Algodão other phase cycles",
        sensor("cotton_phase_other_energy_month"): "Tanquinho Algodão other phase energy this month",
    }, id="en"),
    pytest.param("pt-BR", {
        sensor("cotton_phase_current"): "Tanquinho Fase de Algodão",
        sensor("cotton_phase_last"): "Tanquinho Última fase de Algodão",
        sensor("cotton_phase_warming_cycles_today"): "Tanquinho Ciclos de Aquecendo hoje",
        f"binary_sensor.{PREFIX}_cotton_phase_other": "Tanquinho Outra fase de Algodão",
        sensor("cotton_phase_other_cycles_total"): "Tanquinho Ciclos de outra fase de Algodão",
        sensor("cotton_phase_other_energy_month"): "Tanquinho Energia de outra fase de Algodão no mês",
    }, id="pt-BR"),
])
async def test_a_detected_programs_phases_are_named(
        ha: HomeAssistant, language: str, names: dict[str, str]) -> None:
    """A phase by its name, as the running program's; the fixed ones and other's with the program's name."""
    ha.config.language = language
    cotton = {**PHASED["cotton"], "phases": {"warming": {**WARMING, "statistics": {"cycles": ["today"]}}},
              "other": {"statistics": {"energy": ["month"]}}}
    assert await setup(ha, phased(programs={"detected": {"cotton": cotton}}))
    for entity_id, name in names.items():
        assert ha.states.get(entity_id).attributes["friendly_name"] == name


async def test_a_detected_programs_phase_statistics(ha: HomeAssistant) -> None:
    cotton = {**PHASED["cotton"], "phases": {"warming": {**WARMING, "statistics": {"cycles": ["today"]}}},
              "other": {"statistics": {"runtime": ["week"]}}}
    assert await setup(ha, phased(programs={"detected": {"cotton": cotton}}))
    assert {sensor("cotton_phase_warming_cycles_today"), sensor("cotton_phase_other_runtime_week")} <= held(ha, KEY)


async def test_an_alert_can_watch_a_detected_programs_phase(ha: HomeAssistant) -> None:
    config = phased()
    config[KEY]["alerts"] = {"hot": {"name": "Quente", "when": "appliance_cotton_phase_current", "is": "warming",
                                     "for": {"hours": 1}}}
    assert await setup(ha, config)
    assert ha.states.get(f"binary_sensor.pururu_{KEY}_alert_hot") is not None
