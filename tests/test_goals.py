"""Goals: a made-up pool pump, what it must run each period, and a living room's window that can track one."""

from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
import voluptuous as vol

from helpers import DOMAIN, capture, fake, module, reload, restart, setup, tick

POOL = "pool"
LIVING_ROOM = "living_room"
APPLIANCE: dict[str, Any] = {
    "power": "homeassistant.sensor.pool_pump_power",
    "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}
FILTERING: dict[str, Any] = {
    "name": "Filtragem", "target": 6, "period": "today",
    "tracked_by": "appliance.running_program.runtime_total",
}
WINDOW = {"contact": "homeassistant.binary_sensor.living_room_window"}
TARGET = "sensor.pururu_pool_goal_filtering_target"
DONE = "sensor.pururu_pool_goal_filtering_done"
GOAL = ["devices", POOL, "goals", "filtering"]
# The pool's runtime total, which its goal and the living room's track
RUNTIME_TOTAL = "sensor.pururu_pool_appliance_runtime_total"
AIRING: dict[str, Any] = {
    "name": "Arejar", "target": 1, "period": "today",
    "tracked_by": f"device.{POOL}.appliance.running_program.runtime_total",
}
AIRING_TARGET = "sensor.pururu_living_room_goal_airing_target"
AIRING_DONE = "sensor.pururu_living_room_goal_airing_done"
TRANSLATIONS = Path(__file__).resolve().parents[1] / "custom_components/pururu/translations"


def pool(**goal: Any) -> dict[str, Any]:
    """The pool, its filtering goal with `goal`'s fields over FILTERING's."""
    return {"name": "Piscina", "appliance": APPLIANCE, "goals": {"filtering": {**FILTERING, **goal}}}


def house(*others: tuple[str, dict[str, Any]], **goal: Any) -> dict[str, Any]:
    """A `pururu:` block with the pool, and other devices."""
    return {"devices": {POOL: pool(**goal), **dict(others)}}


def living_room() -> dict[str, Any]:
    """The living room, its airing goal tracking the pool's runtime total."""
    return {"name": "Sala", "window": WINDOW, "goals": {"airing": AIRING}}


def taken(hass: HomeAssistant, entity_id: str) -> None:
    """`entity_id` held by another integration."""
    domain, object_id = entity_id.split(".")
    er.async_get(hass).async_get_or_create(
        domain, "template", "someone_else", suggested_object_id=object_id)


def refused(block: dict[str, Any]) -> vol.Invalid:
    """The first refusal of the `pururu:` block."""
    schema = module("setup.schema").CONFIG_SCHEMA
    with pytest.raises(vol.Invalid) as error:
        schema({DOMAIN: block})
    return error.value


# --- configuration ----------------------------------------------------------------


async def test_a_goal_creates_its_target_and_done(ha: HomeAssistant) -> None:
    """Covers R1, R2: each named after the device, then the goal."""
    assert await setup(ha, {POOL: pool()})
    target, done = ha.states.get(TARGET), ha.states.get(DONE)
    assert target.attributes["friendly_name"] == "Piscina Filtragem target"
    assert done.attributes["friendly_name"] == "Piscina Filtragem done"
    assert float(target.state) == 6


def test_its_names_in_portuguese() -> None:
    sensors = json.loads((TRANSLATIONS / "pt-BR.json").read_text())["entity"]["sensor"]
    assert sensors["goal_target"]["name"] == "Meta de {goal}"
    assert sensors["goal_done"]["name"] == "Realizado de {goal}"


async def test_each_carries_its_reference(ha: HomeAssistant) -> None:
    """Covers R9."""
    assert await setup(ha, {POOL: pool()})
    for entity_id, node in ((TARGET, "goals.filtering.target"), (DONE, "goals.filtering.done")):
        assert ha.states.get(entity_id).attributes["reference"] == {
            "inside": node, "outside": f"device.{POOL}.{node}"}


def test_a_device_of_goals_alone_is_refused(ha: HomeAssistant) -> None:
    """Covers R1."""
    block = {"devices": {POOL: {"name": "Piscina", "goals": {"filtering": FILTERING}}}}
    assert refused(block).msg.startswith("a device needs at least one feature")


@pytest.mark.parametrize(("goal", "field"), [
    pytest.param({"target": 0}, "target", id="target 0"),
    pytest.param({"target": -1}, "target", id="target -1"),
    pytest.param({"target": "six"}, "target", id="target six"),
    pytest.param({"period": "fortnight"}, "period", id="period fortnight"),
])
def test_a_wrong_target_or_period_is_refused_at_its_field(
        ha: HomeAssistant, goal: dict[str, Any], field: str) -> None:
    """Covers R3, R4."""
    assert refused(house(**goal)).path == [DOMAIN, *GOAL, field]


def test_a_wrong_period_names_the_four(ha: HomeAssistant) -> None:
    """Covers R4."""
    assert refused(house(period="fortnight")).msg == (
        "a goal's period is one of today, week, month, year")


@pytest.mark.parametrize("tracked_by", [
    pytest.param("appliance.running_program", id="the carrier"),
    pytest.param("appliance.running_program.statistics.runtime.today", id="a meter"),
    pytest.param(f"device.{LIVING_ROOM}.goals.airing.done", id="a goal's sensor"),
])
def test_what_isnt_a_total_is_refused(ha: HomeAssistant, tracked_by: str) -> None:
    """Covers R5: only what accumulates tracks a goal."""
    airing = {"name": "Arejar", "target": 1, "period": "today",
              "tracked_by": "window.open_time_total"}
    living_room = {"name": "Sala", "window": WINDOW, "goals": {"airing": airing}}
    error = refused(house((LIVING_ROOM, living_room), tracked_by=tracked_by))
    assert error.msg == f"goals: filtering: {tracked_by} is not a total"
    assert error.path == [DOMAIN, *GOAL, "tracked_by"]


def test_its_own_goals_sensor_is_refused_once(ha: HomeAssistant) -> None:
    """Covers R5: a goal of this device is its own block's, refused by checks.references alone."""
    block = house(tracked_by="goals.airing.done")
    block["devices"][POOL]["goals"]["airing"] = {**FILTERING, "name": "Arejar"}
    schema = module("setup.schema").CONFIG_SCHEMA
    with pytest.raises(vol.MultipleInvalid) as error:
        schema({DOMAIN: block})
    assert [(each.msg, each.path) for each in error.value.errors] == [
        ("goals: goals.airing.done is not another block's entity",
         [DOMAIN, *GOAL, "tracked_by"])]


def test_another_devices_total_passes(ha: HomeAssistant) -> None:
    """Covers R5: a goal reaches another device, as a reaction's when does."""
    block = house((LIVING_ROOM, {"name": "Sala", "window": WINDOW}),
                  tracked_by=f"device.{LIVING_ROOM}.window.open_time_total")
    module("setup.schema").CONFIG_SCHEMA({DOMAIN: block})


def test_its_own_device_named_is_refused(ha: HomeAssistant) -> None:
    """Covers R5: written from its own device, with the form to write."""
    error = refused(house(tracked_by=f"device.{POOL}.appliance.running_program.runtime_total"))
    assert error.msg == (f"goals: device.{POOL}.appliance.running_program.runtime_total is this "
                         "device's: write appliance.running_program.runtime_total")
    assert error.path == [DOMAIN, *GOAL, "tracked_by"]


def test_the_energy_mirror_passes(ha: HomeAssistant) -> None:
    """Covers R5: its key is appliance_energy_total, a total, though its path isn't."""
    block = house(tracked_by="appliance.energy")
    block["devices"][POOL]["appliance"] = {**APPLIANCE, "energy": "homeassistant.sensor.pool_pump_energy"}
    module("setup.schema").CONFIG_SCHEMA({DOMAIN: block})


def test_a_home_assistant_entity_passes_the_check(ha: HomeAssistant) -> None:
    """Covers R5: checked when the entry sets up, not here."""
    module("setup.schema").CONFIG_SCHEMA({DOMAIN: house(tracked_by="homeassistant.sensor.pool_pump_runtime")})


@pytest.mark.parametrize(("tracked_by", "write"), [
    pytest.param("homeassistant.sensor.pururu_pool_appliance_runtime_total",
                 "appliance.running_program.runtime_total", id="its own device's"),
    pytest.param("homeassistant.sensor.pururu_living_room_window_open_time_total",
                 f"device.{LIVING_ROOM}.window.open_time_total", id="another device's"),
])
def test_pururus_total_written_as_home_assistants_is_refused(
        ha: HomeAssistant, tracked_by: str, write: str) -> None:
    """Covers R5, R11: as Home Assistant's, it would never be followed; its path is what to write."""
    error = refused(house((LIVING_ROOM, {"name": "Sala", "window": WINDOW}), tracked_by=tracked_by))
    assert error.msg == f"goals: filtering: {tracked_by} is pururu's: write {write}"
    assert error.path == [DOMAIN, *GOAL, "tracked_by"]


def test_a_reaction_on_a_goal_names_its_sensors(ha: HomeAssistant) -> None:
    """Covers R9: a goal is no entity; its target and done are."""
    block = house()
    block["devices"][POOL]["reactions"] = {"met": {"name": "Feito", "when": "goals.filtering", "above": 5}}
    error = refused(block)
    assert error.msg == ("reactions: met: goals.filtering is a goal: watch goals.filtering.target "
                         "or goals.filtering.done")
    assert error.path == [DOMAIN, "devices", POOL, "reactions", "met", "when"]


def test_a_reaction_on_a_goals_done_passes(ha: HomeAssistant) -> None:
    """Covers R9."""
    block = house()
    block["devices"][POOL]["reactions"] = {"met": {"name": "Feito", "when": "goals.filtering.done", "above": 5}}
    module("setup.schema").CONFIG_SCHEMA({DOMAIN: block})


# --- following what tracks it ------------------------------------------------------


async def test_a_goal_tracking_another_devices_total_is_created(ha: HomeAssistant) -> None:
    """Covers R11: it follows the pool's total, created."""
    assert await setup(ha, {POOL: {"name": "Piscina", "appliance": APPLIANCE},
                            LIVING_ROOM: living_room()})
    assert ha.states.get(AIRING_TARGET) is not None
    assert ha.states.get(AIRING_DONE) is not None


async def test_a_goal_whose_other_devices_total_isnt_created_isnt_either(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Covers R11: the pool's total held by another integration; the rest of the pool is created."""
    taken(ha, RUNTIME_TOTAL)
    assert await setup(ha, {POOL: {"name": "Piscina", "appliance": APPLIANCE},
                            LIVING_ROOM: living_room()})
    assert ha.states.get(AIRING_TARGET) is None
    assert ha.states.get(AIRING_DONE) is None
    assert ha.states.get("binary_sensor.pururu_pool_appliance_running") is not None
    for entity_id in (AIRING_TARGET, AIRING_DONE):
        assert (f"{entity_id} follows {RUNTIME_TOTAL}, which is not created; "
                "not creating it") in caplog.text


async def test_a_goal_whose_own_devices_total_isnt_created_isnt_either(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Covers R11: following its own device as any entity does."""
    taken(ha, RUNTIME_TOTAL)
    assert await setup(ha, {POOL: pool()})
    assert ha.states.get(TARGET) is None
    assert ha.states.get(DONE) is None
    assert ha.states.get("binary_sensor.pururu_pool_appliance_running") is not None
    assert (f"{DONE} follows {RUNTIME_TOTAL}, which is not created; "
            "not creating it") in caplog.text


async def test_a_goal_tracked_by_home_assistant_follows_nothing(ha: HomeAssistant) -> None:
    """Home Assistant's entity is no pururu entity to follow: the goal is created without it."""
    assert await setup(ha, {POOL: pool(tracked_by="homeassistant.sensor.pool_pump_runtime")})
    assert ha.states.get(TARGET) is not None
    assert ha.states.get(DONE) is not None


# --- what was done ---------------------------------------------------------------

POWER = "sensor.pool_pump_power"
ENERGY = "sensor.pool_pump_energy"
RUNNING = "binary_sensor.pururu_pool_appliance_running"
# Home Assistant's own runtime total of the pump, which a goal can track instead
PUMP_RUNTIME = "sensor.pool_pump_runtime"
HOURS = {"state_class": "total_increasing", "unit_of_measurement": "h", "device_class": "duration"}
# What the filtering goal's done is of, as its saved state keeps it
FINGERPRINT = "appliance.running_program.runtime_total today"


def value(hass: HomeAssistant, entity_id: str) -> float:
    return float(hass.states.get(entity_id).state)


def saved_total(hours: float) -> tuple[State, dict[str, Any]]:
    """The pool's runtime total, as .storage keeps it."""
    return State(RUNTIME_TOTAL, str(hours)), {"native_value": hours, "native_unit_of_measurement": "h"}


def saved_done(done: float, *, total: float, last_reset: datetime,
               fingerprint: str = FINGERPRINT, entity_id: str = DONE) -> tuple[State, dict[str, Any]]:
    """A goal's done, as .storage keeps it: utility_meter's extra data, and what it is of."""
    return State(entity_id, str(done)), {
        "native_value": {"__type": "<class 'decimal.Decimal'>", "decimal_str": str(done)},
        "native_unit_of_measurement": "h", "last_period": "0",
        "last_reset": last_reset.isoformat(), "last_valid_state": str(total),
        "status": "collecting", "input_device_class": "duration", "fingerprint": fingerprint}


async def idle(hass: HomeAssistant, freezer: Any) -> None:
    """The pump idle long enough to count as not running."""
    await fake(hass, POWER, "1.4")
    await tick(hass, freezer, 125)
    assert hass.states.get(RUNNING).state == "off"


async def pump(hass: HomeAssistant, freezer: Any, hours: float) -> None:
    """The pump runs `hours`, from when on_delay passed to when it drops, then its off delay, which isn't runtime."""
    await fake(hass, POWER, "120")
    await tick(hass, freezer, 65)
    await tick(hass, freezer, hours * 3600 - 5)
    await idle(hass, freezer)


async def test_done_is_what_ran_since_midnight(ha: HomeAssistant, freezer: Any) -> None:
    """Covers AE1: the goal in place since before midnight; at midnight done is 0 again."""
    await restart(ha, {POOL: pool()}, saved_total(100))
    await idle(ha, freezer)
    assert value(ha, DONE) == 0
    await pump(ha, freezer, 2)
    assert value(ha, RUNTIME_TOTAL) == pytest.approx(102, abs=0.01)
    assert value(ha, DONE) == pytest.approx(2, abs=0.01)
    assert ha.states.get(DONE).attributes["unit_of_measurement"] == "h"
    await tick(ha, freezer, (dt_util.start_of_local_day() + timedelta(days=1) - dt_util.now()
                             ).total_seconds() + 60)
    assert value(ha, DONE) == 0
    assert value(ha, TARGET) == 6


async def test_a_goal_set_up_mid_period_counts_from_then(ha: HomeAssistant, freezer: Any) -> None:
    """KTD1: the 2 h the pump ran this morning aren't done; the next hour is."""
    freezer.move_to(dt_util.start_of_local_day() + timedelta(hours=15))
    await restart(ha, {POOL: pool()}, saved_total(102))
    await idle(ha, freezer)
    assert value(ha, DONE) == 0
    await pump(ha, freezer, 1)
    assert value(ha, DONE) == pytest.approx(1, abs=0.01)


async def test_done_is_kept_across_a_restart(ha: HomeAssistant, freezer: Any) -> None:
    """Covers AE5: 3 h done at 15:00, and the pump didn't run while Home Assistant was down."""
    midnight = dt_util.start_of_local_day()
    freezer.move_to(midnight + timedelta(hours=15))
    await restart(ha, {POOL: pool()}, saved_total(103), saved_done(3, total=103, last_reset=midnight))
    done = ha.states.get(DONE)
    assert float(done.state) == 3
    assert done.attributes["unit_of_measurement"] == "h"
    assert dt_util.parse_datetime(done.attributes["last_reset"]) == midnight


async def test_what_home_assistants_total_grew_while_down_counts_at_its_next_change(
        ha: HomeAssistant) -> None:
    """Core counts from the total's last valid state, once the total changes again."""
    await fake(ha, PUMP_RUNTIME, "53", HOURS)
    tracked_by = f"homeassistant.{PUMP_RUNTIME}"
    await restart(ha, {POOL: pool(tracked_by=tracked_by)},
                  saved_done(3, total=50, last_reset=dt_util.start_of_local_day(),
                             fingerprint=f"{tracked_by} today"))
    assert value(ha, DONE) == 3
    await fake(ha, PUMP_RUNTIME, "54", HOURS)
    assert value(ha, DONE) == 7


async def test_done_from_yesterday_is_0_at_start(ha: HomeAssistant) -> None:
    """Covers R8: midnight passed while Home Assistant was down."""
    yesterday = dt_util.start_of_local_day() - timedelta(days=1)
    await restart(ha, {POOL: pool()}, saved_total(103), saved_done(3, total=103, last_reset=yesterday))
    assert value(ha, DONE) == 0


async def test_a_reload_keeps_done(ha: HomeAssistant, freezer: Any) -> None:
    """Covers R10: unavailable while the entry reloads, then back where it was, neither 0 nor doubled."""
    assert await setup(ha, {POOL: pool()})
    await idle(ha, freezer)
    await pump(ha, freezer, 1)
    before = ha.states.get(DONE).state
    assert float(before) == pytest.approx(1, abs=0.01)
    changes = capture(ha, "state_changed")
    await reload(ha, {POOL: pool()})
    seen = [event.data["new_state"].state for event in changes
            if event.data["entity_id"] == DONE and event.data["new_state"] is not None]
    assert "unavailable" in seen
    assert "0" not in seen
    assert ha.states.get(DONE).state == before


@pytest.mark.parametrize("goal", [
    pytest.param({"period": "week"}, id="period"),
    pytest.param({"tracked_by": f"homeassistant.{PUMP_RUNTIME}"}, id="tracked_by"),
])
async def test_done_starts_again_for_another_definition(
        ha: HomeAssistant, goal: dict[str, Any]) -> None:
    """KTD2: the saved 3 h were of the runtime total today; the goal now counts something else."""
    await fake(ha, PUMP_RUNTIME, "50", HOURS)
    await restart(ha, {POOL: pool(**goal)}, saved_total(103),
                  saved_done(3, total=103, last_reset=dt_util.start_of_local_day()))
    assert value(ha, DONE) == 0


async def test_done_follows_its_total_renamed_in_the_ui(ha: HomeAssistant, freezer: Any) -> None:
    """KTD2: the same tracked_by, so done keeps its value, and meters the total by its new ID."""
    assert await setup(ha, {POOL: pool()})
    await idle(ha, freezer)
    await pump(ha, freezer, 1)
    er.async_get(ha).async_update_entity(RUNTIME_TOTAL, new_entity_id="sensor.pool_filtering_hours")
    await ha.async_block_till_done()
    assert value(ha, DONE) == pytest.approx(1, abs=0.01)
    await pump(ha, freezer, 1)
    assert value(ha, "sensor.pool_filtering_hours") == pytest.approx(2, abs=0.02)
    assert value(ha, DONE) == pytest.approx(2, abs=0.02)


@pytest.mark.parametrize("known_by", ["registry", "state"])
async def test_what_doesnt_accumulate_creates_no_goal(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, known_by: str) -> None:
    """Covers AE3: a power reading, its state class known from the registry or its state; the rest of the pool is created."""
    if known_by == "registry":
        er.async_get(ha).async_get_or_create(
            "sensor", "plug", "pool_pump_power", suggested_object_id="pool_pump_power",
            capabilities={"state_class": "measurement"})
    else:
        await fake(ha, POWER, "120", {"state_class": "measurement", "unit_of_measurement": "W"})
    assert await setup(ha, {POOL: pool(tracked_by=f"homeassistant.{POWER}")})
    assert ha.states.get(TARGET) is None
    assert ha.states.get(DONE) is None
    assert ha.states.get(RUNNING) is not None
    assert (f"{POOL}: goals: filtering: homeassistant.{POWER} doesn't accumulate "
            "(state class measurement); not creating it") in caplog.text


async def test_home_assistants_entity_not_loaded_yet_gives_a_goal(ha: HomeAssistant) -> None:
    """KTD4: unknown until it first reports, then counted from there."""
    assert await setup(ha, {POOL: pool(tracked_by=f"homeassistant.{PUMP_RUNTIME}")})
    assert ha.states.get(TARGET) is not None
    assert ha.states.get(DONE).state == "unknown"
    await fake(ha, PUMP_RUNTIME, "10", HOURS)
    assert value(ha, DONE) == 0
    await fake(ha, PUMP_RUNTIME, "11", HOURS)
    assert value(ha, DONE) == 1


async def test_done_is_unavailable_while_its_total_is(ha: HomeAssistant) -> None:
    """What the total grew meanwhile counts when it is back."""
    await fake(ha, PUMP_RUNTIME, "10", HOURS)
    assert await setup(ha, {POOL: pool(tracked_by=f"homeassistant.{PUMP_RUNTIME}")})
    await fake(ha, PUMP_RUNTIME, "unavailable")
    assert ha.states.get(DONE).state == "unavailable"
    await fake(ha, PUMP_RUNTIME, "12", HOURS)
    assert value(ha, DONE) == 2


async def test_done_is_0_while_its_total_doesnt_change(ha: HomeAssistant, freezer: Any) -> None:
    """Started from the total's reading at setup, not left unknown."""
    await fake(ha, PUMP_RUNTIME, "10", HOURS)
    assert await setup(ha, {POOL: pool(tracked_by=f"homeassistant.{PUMP_RUNTIME}")})
    await tick(ha, freezer, 3600)
    assert value(ha, DONE) == 0


async def test_a_goal_meters_another_devices_total(ha: HomeAssistant, freezer: Any) -> None:
    """Covers R7: the living room's airing done is what the pool's total grew."""
    await restart(ha, {POOL: {"name": "Piscina", "appliance": APPLIANCE}, LIVING_ROOM: living_room()},
                  saved_total(100))
    await idle(ha, freezer)
    assert value(ha, AIRING_DONE) == 0
    await pump(ha, freezer, 1)
    assert value(ha, RUNTIME_TOTAL) == pytest.approx(101, abs=0.01)
    assert value(ha, AIRING_DONE) == pytest.approx(1, abs=0.01)


@pytest.mark.parametrize(("device", "tracked_by", "target", "done"), [
    pytest.param(POOL, "appliance.energy", TARGET, DONE, id="its own"),
    pytest.param(LIVING_ROOM, f"device.{POOL}.appliance.energy", AIRING_TARGET, AIRING_DONE,
                 id="another device's"),
])
async def test_an_energy_mirror_whose_plug_doesnt_accumulate_creates_no_goal(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture,
        device: str, tracked_by: str, target: str, done: str) -> None:
    """Covers R5: the energy mirror is a total by its key, but it shows its plug's reading."""
    await fake(ha, ENERGY, "5", {"state_class": "measurement", "unit_of_measurement": "kWh"})
    appliance = {**APPLIANCE, "energy": f"homeassistant.{ENERGY}"}
    goal = "filtering" if device == POOL else "airing"
    devices = {POOL: {"name": "Piscina", "appliance": appliance},
               LIVING_ROOM: living_room()}
    devices[device]["goals"] = {goal: {**(FILTERING if device == POOL else AIRING),
                                       "tracked_by": tracked_by}}
    assert await setup(ha, devices)
    assert ha.states.get(target) is None
    assert ha.states.get(done) is None
    assert ha.states.get(RUNNING) is not None
    assert (f"{device}: goals: {goal}: {tracked_by} doesn't accumulate "
            "(state class measurement); not creating it") in caplog.text


# --- a disabled total -------------------------------------------------------------

# The pool's runtime today: a meter of the runtime total, which a disabled total keeps
RUNTIME_TODAY = "sensor.pururu_pool_appliance_runtime_today"
# An entity of the pool that no goal tracks
CYCLES_TOTAL = "sensor.pururu_pool_appliance_cycles_total"


def metered(device: dict[str, Any]) -> dict[str, Any]:
    """`device` with its runtime metered today."""
    running = {**device["appliance"]["running_program"], "statistics": {"runtime": ["today"]}}
    return {**device, "appliance": {**device["appliance"], "running_program": running}}


async def disable(hass: HomeAssistant, freezer: Any, entity_id: str, disabled: bool = True) -> None:
    """Disable `entity_id` in the registry, or enable it again, and wait out HA's own reload."""
    er.async_get(hass).async_update_entity(
        entity_id, disabled_by=er.RegistryEntryDisabler.USER if disabled else None)
    await tick(hass, freezer, 31)
    await hass.async_block_till_done()


def counting_reloads(hass: HomeAssistant) -> Any:
    """Count the entry's reloads, pururu's own and HA's."""
    return patch.object(hass.config_entries, "async_reload", wraps=hass.config_entries.async_reload)


def assert_dropped(hass: HomeAssistant, caplog: pytest.LogCaptureFixture, *entity_ids: str) -> None:
    """Not created, no registry entry, logged as following the total, which is not created."""
    registry = er.async_get(hass)
    for entity_id in entity_ids:
        assert hass.states.get(entity_id) is None
        assert registry.async_get(entity_id) is None
        assert (f"{entity_id} follows {RUNTIME_TOTAL}, which is not created; "
                "not creating it") in caplog.text


async def test_a_disabled_total_creates_no_goal(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Covers AE4: the rest of the pool is created, the total's meter included, and the total stays disabled."""
    er.async_get(ha).async_get_or_create(
        "sensor", DOMAIN, "pururu_pool_appliance_runtime_total",
        suggested_object_id="pururu_pool_appliance_runtime_total",
        disabled_by=er.RegistryEntryDisabler.USER)
    assert await setup(ha, {POOL: metered(pool())})
    assert_dropped(ha, caplog, TARGET, DONE)
    assert ha.states.get(RUNNING) is not None
    assert ha.states.get(RUNTIME_TODAY) is not None
    assert er.async_get(ha).async_get(RUNTIME_TOTAL).disabled_by is er.RegistryEntryDisabler.USER


async def test_disabling_the_total_drops_the_goal(
        ha: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    """Covers R11: one reload, after which the goal's sensors and their registry entries are gone."""
    assert await setup(ha, {POOL: pool()})
    assert ha.states.get(DONE) is not None
    with counting_reloads(ha) as reloads:
        await disable(ha, freezer, RUNTIME_TOTAL)
    assert reloads.call_count == 1
    assert_dropped(ha, caplog, TARGET, DONE)
    assert er.async_get(ha).async_get(RUNTIME_TOTAL).disabled_by is er.RegistryEntryDisabler.USER


@pytest.mark.parametrize(("days", "expected"), [
    pytest.param(0, 1, id="the same day"),
    pytest.param(1, 0, id="the next day"),
])
async def test_enabling_the_total_brings_the_goal_back(
        ha: HomeAssistant, freezer: Any, days: int, expected: float) -> None:
    """KTD3: HA's own reload; done as it was when dropped, 0 once the period turned over."""
    assert await setup(ha, {POOL: pool()})
    await idle(ha, freezer)
    await pump(ha, freezer, 1)
    await disable(ha, freezer, RUNTIME_TOTAL)
    assert ha.states.get(DONE) is None
    await tick(ha, freezer, days * 86400)
    with counting_reloads(ha) as reloads:
        await disable(ha, freezer, RUNTIME_TOTAL, disabled=False)
    assert reloads.call_count == 1
    assert value(ha, TARGET) == 6
    assert value(ha, DONE) == pytest.approx(expected, abs=0.01)


async def test_disabling_another_devices_total_drops_its_goal(
        ha: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    """Covers R11: the living room's airing follows the pool's total."""
    assert await setup(ha, {POOL: {"name": "Piscina", "appliance": APPLIANCE},
                            LIVING_ROOM: living_room()})
    assert ha.states.get(AIRING_DONE) is not None
    with counting_reloads(ha) as reloads:
        await disable(ha, freezer, RUNTIME_TOTAL)
    assert reloads.call_count == 1
    assert_dropped(ha, caplog, AIRING_TARGET, AIRING_DONE)


async def test_disabling_what_no_goal_tracks_reloads_nothing(ha: HomeAssistant, freezer: Any) -> None:
    assert await setup(ha, {POOL: pool()})
    with counting_reloads(ha) as reloads:
        await disable(ha, freezer, CYCLES_TOTAL)
    assert reloads.call_count == 0
    assert ha.states.get(DONE) is not None


# --- the target ----------------------------------------------------------------------

ENERGY_TOTAL = {"state_class": "total_increasing", "unit_of_measurement": "kWh", "device_class": "energy"}


def saved_target(target: float, unit: str, device_class: str) -> tuple[State, dict[str, Any]]:
    """The filtering goal's target, as .storage keeps it."""
    return State(TARGET, str(target), {"unit_of_measurement": unit, "device_class": device_class}), {
        "native_value": target, "native_unit_of_measurement": unit}


async def test_a_target_of_cycles_is_in_cycles(ha: HomeAssistant) -> None:
    """Covers AE2: the cycles total's unit, translated in English alone, as done's; a count has no device class."""
    assert await setup(ha, {POOL: pool(
        target=2, period="week", tracked_by="appliance.running_program.cycles_total")})
    target = ha.states.get(TARGET)
    assert float(target.state) == 2
    assert target.attributes["unit_of_measurement"] == "cycles"
    assert target.attributes["unit_of_measurement"] == ha.states.get(DONE).attributes["unit_of_measurement"]
    assert "device_class" not in target.attributes


async def test_a_target_of_runtime_is_in_hours(ha: HomeAssistant) -> None:
    """Covers R6: the runtime total's unit and device class; never graphed as a measurement."""
    assert await setup(ha, {POOL: pool()})
    target = ha.states.get(TARGET)
    assert float(target.state) == 6
    assert target.attributes["unit_of_measurement"] == "h"
    assert target.attributes["device_class"] == "duration"
    assert "state_class" not in target.attributes


@pytest.mark.parametrize("known_by", ["registry", "state"])
async def test_a_target_of_home_assistants_energy_is_in_kwh(ha: HomeAssistant, known_by: str) -> None:
    """Covers R6: its unit and device class from its registry entry before it reports, else from its state."""
    if known_by == "registry":
        er.async_get(ha).async_get_or_create(
            "sensor", "plug", "pool_pump_energy", suggested_object_id="pool_pump_energy",
            capabilities={"state_class": "total_increasing"},
            unit_of_measurement="kWh", original_device_class="energy")
    else:
        await fake(ha, ENERGY, "5", ENERGY_TOTAL)
    assert await setup(ha, {POOL: pool(tracked_by=f"homeassistant.{ENERGY}")})
    target = ha.states.get(TARGET)
    assert float(target.state) == 6
    assert target.attributes["unit_of_measurement"] == "kWh"
    assert target.attributes["device_class"] == "energy"


async def test_a_target_takes_its_unit_once_its_entity_reports(ha: HomeAssistant) -> None:
    """Covers R6: a number without a unit while its entity isn't there; never unavailable for its sake."""
    assert await setup(ha, {POOL: pool(tracked_by=f"homeassistant.{ENERGY}")})
    target = ha.states.get(TARGET)
    assert float(target.state) == 6
    assert "unit_of_measurement" not in target.attributes
    assert "device_class" not in target.attributes
    await fake(ha, ENERGY, "5", ENERGY_TOTAL)
    target = ha.states.get(TARGET)
    assert target.attributes["unit_of_measurement"] == "kWh"
    assert target.attributes["device_class"] == "energy"
    await fake(ha, ENERGY, "unavailable")
    target = ha.states.get(TARGET)
    assert float(target.state) == 6
    assert target.attributes["unit_of_measurement"] == "kWh"
    assert target.attributes["device_class"] == "energy"


async def test_a_target_keeps_its_unit_across_a_restart(ha: HomeAssistant) -> None:
    """Covers R6: kWh before its entity reports again."""
    await restart(ha, {POOL: pool(tracked_by=f"homeassistant.{ENERGY}")}, saved_target(6, "kWh", "energy"))
    target = ha.states.get(TARGET)
    assert float(target.state) == 6
    assert target.attributes["unit_of_measurement"] == "kWh"
    assert target.attributes["device_class"] == "energy"


async def test_a_restart_shows_the_written_target_in_its_saved_unit(ha: HomeAssistant) -> None:
    """Covers R3: the number is the one written, not the one saved; the unit is the saved one."""
    await restart(ha, {POOL: pool(tracked_by=f"homeassistant.{PUMP_RUNTIME}")},
                  saved_target(4, "h", "duration"))
    target = ha.states.get(TARGET)
    assert float(target.state) == 6
    assert target.attributes["unit_of_measurement"] == "h"
    assert target.attributes["device_class"] == "duration"
