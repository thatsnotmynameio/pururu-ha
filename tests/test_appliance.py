"""Feature `appliance`: a made-up washer on a made-up plug."""

from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest

from helpers import capture, fake, held, reload, restart, setup, tick

KEY = "demo_washer"
POWER = "sensor.demo_plug_power"
ENERGY = "sensor.demo_plug_energy"
RUNNING = "binary_sensor.pururu_demo_washer_running"
IDLE_W = 1.4
APPLIANCE: dict[str, Any] = {
    "power": POWER,
    "energy": ENERGY,
    "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}
DEVICES = {KEY: {"name": "Demo washer", "appliance": APPLIANCE}}


def sensor(metric: str) -> str:
    return f"sensor.pururu_{KEY}_{metric}"


def running(hass: HomeAssistant) -> str:
    return hass.states.get(RUNNING).state


async def watts(hass: HomeAssistant, value: float | str) -> None:
    await fake(hass, POWER, str(value))


async def kwh(hass: HomeAssistant, value: float | str) -> None:
    await fake(hass, ENERGY, str(value))


@pytest.fixture
async def washer(ha: HomeAssistant, freezer: Any) -> HomeAssistant:
    """The demo washer, idle long enough to count as not running."""
    assert await setup(ha, DEVICES)
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 125)
    assert running(ha) == "off"
    return ha


async def start_cycle(hass: HomeAssistant, freezer: Any) -> None:
    """Long enough above the threshold to run, then the drum's pause (~7 W)."""
    await watts(hass, 120)
    await tick(hass, freezer, 65)
    assert running(hass) == "on"
    await watts(hass, 7)


async def end_cycle(hass: HomeAssistant, freezer: Any) -> None:
    await watts(hass, IDLE_W)
    await tick(hass, freezer, 125)
    assert running(hass) == "off"


# --- schema ------------------------------------------------------------------


@pytest.mark.parametrize("block", [
    pytest.param({**APPLIANCE, "statistics": {"cycles": ["today", "today"]}}, id="repeated period"),
    pytest.param({**APPLIANCE, "statistics": {"cycles": ["daily"]}}, id="unknown period"),
    pytest.param({**APPLIANCE, "running": {"threshold": 4, "on_delay": {"minutes": 1}}},
                 id="no off_delay"),
    pytest.param({"running": APPLIANCE["running"]}, id="no power"),
    pytest.param({**APPLIANCE, "watts": POWER}, id="unknown key"),
])
async def test_invalid_block_is_refused(ha: HomeAssistant, block: dict[str, Any]) -> None:
    assert not await setup(ha, {KEY: {"name": "Demo washer", "appliance": block}})


# --- running -------------------------------------------------------------------


async def test_starts_after_on_delay_above_threshold(washer: HomeAssistant, freezer: Any) -> None:
    await watts(washer, 120)
    await tick(washer, freezer, 50)
    assert running(washer) == "off"
    await watts(washer, 7)
    await tick(washer, freezer, 15)
    assert running(washer) == "on"


async def test_threshold_itself_is_not_above(washer: HomeAssistant, freezer: Any) -> None:
    await watts(washer, 4)
    await tick(washer, freezer, 180)
    assert running(washer) == "off"


async def test_press_shorter_than_on_delay_is_not_a_cycle(washer: HomeAssistant,
                                                          freezer: Any) -> None:
    await watts(washer, 55.89)
    await tick(washer, freezer, 2)
    await watts(washer, 2.68)
    await tick(washer, freezer, 180)
    assert running(washer) == "off"


async def test_ends_after_off_delay(washer: HomeAssistant, freezer: Any) -> None:
    await start_cycle(washer, freezer)
    await watts(washer, IDLE_W)
    await tick(washer, freezer, 110)
    assert running(washer) == "on"
    await tick(washer, freezer, 15)
    assert running(washer) == "off"


async def test_reading_back_above_cancels_the_end(washer: HomeAssistant, freezer: Any) -> None:
    await start_cycle(washer, freezer)
    await watts(washer, IDLE_W)
    await tick(washer, freezer, 100)
    await watts(washer, 7)
    await tick(washer, freezer, 300)
    assert running(washer) == "on"


@pytest.mark.parametrize("gone", ["unavailable", "unknown", "not a number"])
async def test_holds_while_the_plug_has_no_value(washer: HomeAssistant, freezer: Any,
                                                 gone: str) -> None:
    await start_cycle(washer, freezer)
    await watts(washer, gone)
    await tick(washer, freezer, 600)
    assert running(washer) == "on"
    await end_cycle(washer, freezer)


async def test_holds_off_while_the_plug_has_no_value(washer: HomeAssistant, freezer: Any) -> None:
    await watts(washer, 120)
    await tick(washer, freezer, 30)
    await watts(washer, "unavailable")
    await tick(washer, freezer, 180)
    assert running(washer) == "off"


async def test_restart_restores_running(ha: HomeAssistant, freezer: Any) -> None:
    """Saved on: still on after the restart until the plug says otherwise."""
    since = (dt_util.utcnow() - timedelta(minutes=20)).isoformat()
    await restart(ha, DEVICES, (State(RUNNING, "on"), {"since": since, "since_energy": 100.0}))
    assert running(ha) == "on"
    await watts(ha, "unavailable")
    await tick(ha, freezer, 600)
    assert running(ha) == "on"
    await end_cycle(ha, freezer)


# --- mirrors, entities, names --------------------------------------------------


async def test_mirrors_follow_the_plug(washer: HomeAssistant) -> None:
    await fake(washer, POWER, "120", {"unit_of_measurement": "W", "device_class": "power",
                                      "state_class": "measurement"})
    await fake(washer, ENERGY, "100.5", {"unit_of_measurement": "kWh", "device_class": "energy",
                                         "state_class": "total_increasing"})
    power = washer.states.get(sensor("power"))
    energy = washer.states.get(sensor("energy_total"))
    assert float(power.state) == 120
    assert power.attributes["unit_of_measurement"] == "W"
    assert float(energy.state) == 100.5
    assert energy.attributes["state_class"] == "total_increasing"


async def test_device_holds_the_appliance(washer: HomeAssistant) -> None:
    assert {RUNNING, sensor("power"), sensor("energy_total")} <= held(washer, KEY)


async def test_without_energy_there_is_no_energy_total(ha: HomeAssistant) -> None:
    block = {key: value for key, value in APPLIANCE.items() if key != "energy"}
    assert await setup(ha, {KEY: {"name": "Demo washer", "appliance": block}})
    assert ha.states.get(sensor("energy_total")) is None
    assert ha.states.get(RUNNING) is not None


async def test_names_come_from_the_translations(washer: HomeAssistant) -> None:
    assert washer.states.get(RUNNING).attributes["friendly_name"] == "Demo washer Running"


async def test_names_in_portuguese(ha: HomeAssistant) -> None:
    ha.config.language = "pt-BR"
    assert await setup(ha, DEVICES)
    assert ha.states.get(RUNNING).attributes["friendly_name"] == "Demo washer Em funcionamento"
    assert ha.states.get(sensor("power")).attributes["friendly_name"] == "Demo washer Potência"


# --- the last cycle and the count ------------------------------------------------

LAST = ("last_cycle_start", "last_cycle_duration", "last_cycle_energy", "last_cycle_end")


def value(hass: HomeAssistant, metric: str) -> str:
    return hass.states.get(sensor(metric)).state


async def test_a_finished_cycle_is_recorded(washer: HomeAssistant, freezer: Any) -> None:
    await kwh(washer, 100.0)
    await start_cycle(washer, freezer)
    started = dt_util.utcnow()
    await tick(washer, freezer, 30 * 60)
    await kwh(washer, 100.62)
    await end_cycle(washer, freezer)
    ended = dt_util.parse_datetime(value(washer, "last_cycle_end"))
    start = dt_util.parse_datetime(value(washer, "last_cycle_start"))
    assert abs((ended - dt_util.utcnow()).total_seconds()) < 5
    assert abs((start - started).total_seconds()) < 5
    assert float(value(washer, "last_cycle_duration")) == pytest.approx(
        (ended - start).total_seconds() / 60, abs=0.1)
    assert float(value(washer, "last_cycle_energy")) == pytest.approx(0.62)
    assert value(washer, "cycles_total") == "1"


async def test_before_the_first_cycle_everything_is_unknown(washer: HomeAssistant) -> None:
    for metric in LAST:
        assert value(washer, metric) == "unknown", metric
    assert value(washer, "cycles_total") == "0"


async def test_end_is_written_last(washer: HomeAssistant, freezer: Any) -> None:
    await kwh(washer, 100.0)
    await start_cycle(washer, freezer)
    changes = capture(washer, "state_changed")
    await end_cycle(washer, freezer)
    order = [event.data["entity_id"] for event in changes
             if event.data["entity_id"] in {sensor(metric) for metric in LAST}]
    assert order[-1] == sensor("last_cycle_end"), order
    assert set(order) == {sensor(metric) for metric in LAST}, order


@pytest.mark.parametrize(("unit", "start", "end"), [
    pytest.param("Wh", "100000", "100620", id="Wh"),
    pytest.param("MWh", "0.1", "0.10062", id="MWh"),
    pytest.param("kWh", "100.0", "100.62", id="kWh"),
])
async def test_energy_is_in_kwh_whatever_the_counter_unit(washer: HomeAssistant, freezer: Any,
                                                           unit: str, start: str,
                                                           end: str) -> None:
    await fake(washer, ENERGY, start, {"unit_of_measurement": unit})
    await start_cycle(washer, freezer)
    await fake(washer, ENERGY, end, {"unit_of_measurement": unit})
    await end_cycle(washer, freezer)
    assert float(value(washer, "last_cycle_energy")) == pytest.approx(0.62)


async def test_a_counter_not_in_energy_gives_no_energy(washer: HomeAssistant,
                                                        freezer: Any) -> None:
    await fake(washer, ENERGY, "100", {"unit_of_measurement": "W"})
    await start_cycle(washer, freezer)
    await fake(washer, ENERGY, "200", {"unit_of_measurement": "W"})
    await end_cycle(washer, freezer)
    assert value(washer, "last_cycle_energy") == "unknown"


async def test_energy_is_never_negative(washer: HomeAssistant, freezer: Any) -> None:
    """A counter lower at the end than at the start (the plug re-paired) is 0 kWh."""
    await kwh(washer, 100.0)
    await start_cycle(washer, freezer)
    await kwh(washer, 0.3)
    await end_cycle(washer, freezer)
    assert float(value(washer, "last_cycle_energy")) == 0


async def test_energy_unknown_at_the_start_gives_no_energy(washer: HomeAssistant,
                                                           freezer: Any) -> None:
    await kwh(washer, "unavailable")
    await start_cycle(washer, freezer)
    await kwh(washer, 100.5)
    await end_cycle(washer, freezer)
    assert value(washer, "last_cycle_energy") == "unknown"
    assert value(washer, "last_cycle_duration") != "unknown"


async def test_without_energy_there_is_no_cycle_energy(ha: HomeAssistant) -> None:
    block = {key: value for key, value in APPLIANCE.items() if key != "energy"}
    assert await setup(ha, {KEY: {"name": "Demo washer", "appliance": block}})
    assert ha.states.get(sensor("last_cycle_energy")) is None
    assert ha.states.get(sensor("last_cycle_duration")) is not None


async def test_reload_mid_cycle_counts_one(washer: HomeAssistant, freezer: Any) -> None:
    """Reloading removes and restores running: not an end, not a start."""
    await start_cycle(washer, freezer)
    started = dt_util.utcnow()
    await tick(washer, freezer, 600)
    await reload(washer, DEVICES)
    await tick(washer, freezer, 600)
    assert running(washer) == "on"
    await end_cycle(washer, freezer)
    assert value(washer, "cycles_total") == "1"
    start = dt_util.parse_datetime(value(washer, "last_cycle_start"))
    assert abs((start - started).total_seconds()) < 5


async def test_restart_mid_cycle_keeps_its_start(ha: HomeAssistant, freezer: Any) -> None:
    """Saved 20 min into a wash; the plug reports idle after the restart: one cycle of ~22 min."""
    since = (dt_util.utcnow() - timedelta(minutes=20)).isoformat()
    await restart(
        ha, DEVICES,
        (State(RUNNING, "on"), {"since": since, "since_energy": 100.0}),
        (State(sensor("cycles_total"), "5"),
         {"native_value": 5, "native_unit_of_measurement": None}),
    )
    await kwh(ha, 100.4)
    await end_cycle(ha, freezer)
    assert float(value(ha, "last_cycle_duration")) == pytest.approx(22, abs=0.2)
    assert float(value(ha, "last_cycle_energy")) == pytest.approx(0.4)
    assert value(ha, "cycles_total") == "6"


async def test_last_cycle_restores(ha: HomeAssistant) -> None:
    # A timestamp sensor's state renders with second precision (HA's SensorEntity.state,
    # `isoformat(timespec="seconds")`), so this round-trip is compared at that precision too.
    end = (dt_util.utcnow() - timedelta(days=1)).replace(microsecond=0).isoformat()
    await restart(
        ha, DEVICES,
        (State(sensor("last_cycle_end"), end),
         {"native_value": {"__type": "<class 'datetime.datetime'>", "isoformat": end},
          "native_unit_of_measurement": None}),
        (State(sensor("last_cycle_duration"), "50.0"),
         {"native_value": 50.0, "native_unit_of_measurement": "min"}),
    )
    assert dt_util.parse_datetime(value(ha, "last_cycle_end")) == dt_util.parse_datetime(end)
    assert float(value(ha, "last_cycle_duration")) == 50


async def test_devices_do_not_cross(ha: HomeAssistant, freezer: Any) -> None:
    """Two washers: a cycle on one counts only there."""
    other = {**APPLIANCE, "power": "sensor.demo_other_power", "energy": "sensor.demo_other_energy"}
    assert await setup(ha, {**DEVICES, "demo_other": {"name": "Other", "appliance": other}})
    await watts(ha, IDLE_W)
    await fake(ha, "sensor.demo_other_power", str(IDLE_W))
    await tick(ha, freezer, 125)
    await start_cycle(ha, freezer)
    await end_cycle(ha, freezer)
    assert value(ha, "cycles_total") == "1"
    assert ha.states.get("sensor.pururu_demo_other_cycles_total").state == "0"
    assert ha.states.get("sensor.pururu_demo_other_last_cycle_end").state == "unknown"


# --- runtime and statistics --------------------------------------------------------

STATISTICS = {**APPLIANCE, "statistics": {"runtime": ["today", "week"],
                                          "cycles": ["today", "month"]}}


@pytest.fixture
async def metered(ha: HomeAssistant, freezer: Any) -> HomeAssistant:
    """The demo washer with statistics, idle."""
    assert await setup(ha, {KEY: {"name": "Demo washer", "appliance": STATISTICS}})
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 125)
    return ha


async def wash(hass: HomeAssistant, freezer: Any, minutes: float) -> None:
    """A cycle on for `minutes` plus its 2 min off delay."""
    await watts(hass, 120)
    await tick(hass, freezer, 65)
    await watts(hass, 7)
    await tick(hass, freezer, minutes * 60 - 5)
    await end_cycle(hass, freezer)


async def test_runtime_adds_the_time_running(metered: HomeAssistant, freezer: Any) -> None:
    await wash(metered, freezer, 30)
    await wash(metered, freezer, 20)
    assert float(value(metered, "runtime_total")) == pytest.approx((30 + 2 + 20 + 2) / 60,
                                                                  abs=0.01)


async def test_runtime_grows_while_running(metered: HomeAssistant, freezer: Any) -> None:
    await watts(metered, 120)
    await tick(metered, freezer, 65)
    await tick(metered, freezer, 10 * 60)
    assert float(value(metered, "runtime_total")) == pytest.approx(10 / 60, abs=0.02)


async def test_meters_count_their_total(metered: HomeAssistant, freezer: Any) -> None:
    await wash(metered, freezer, 30)
    await wash(metered, freezer, 20)
    await tick(metered, freezer, 60)
    assert float(value(metered, "cycles_today")) == 2
    assert float(value(metered, "cycles_month")) == 2
    assert float(value(metered, "runtime_today")) == pytest.approx(
        float(value(metered, "runtime_total")), abs=0.01)
    assert metered.states.get(sensor("runtime_month")) is None


async def test_today_resets_at_local_midnight(ha: HomeAssistant, freezer: Any) -> None:
    """At local 16:00 (UTC midnight is 17:00 in HA's test zone): UTC midnight resets nothing."""
    zone = dt_util.get_time_zone(ha.config.time_zone)
    freezer.move_to(datetime(2026, 9, 16, 16, 0, tzinfo=zone))
    assert await setup(ha, {KEY: {"name": "Demo washer", "appliance": STATISTICS}})
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 125)
    await wash(ha, freezer, 30)
    assert float(value(ha, "cycles_today")) == 1
    utc_midnight = datetime(2026, 9, 17, tzinfo=dt_util.UTC)
    assert dt_util.now() < utc_midnight
    await tick(ha, freezer, (utc_midnight - dt_util.utcnow()).total_seconds() + 60)
    assert float(value(ha, "cycles_today")) == 1
    local_midnight = datetime(2026, 9, 17, tzinfo=zone)
    await tick(ha, freezer, (local_midnight - dt_util.utcnow()).total_seconds() + 60)
    assert float(value(ha, "cycles_today")) == 0
    assert value(ha, "cycles_total") == "1"


async def test_cycles_unit_comes_from_the_translations(metered: HomeAssistant,
                                                       freezer: Any) -> None:
    await wash(metered, freezer, 5)
    await tick(metered, freezer, 60)
    assert metered.states.get(sensor("cycles_total")).attributes["unit_of_measurement"] == "cycles"
    assert metered.states.get(sensor("cycles_today")).attributes["unit_of_measurement"] == "cycles"


async def test_runtime_restores(ha: HomeAssistant) -> None:
    await restart(ha, {KEY: {"name": "Demo washer", "appliance": STATISTICS}},
                  (State(sensor("runtime_total"), "1.5"),
                   {"native_value": 1.5, "native_unit_of_measurement": "h"}))
    assert float(value(ha, "runtime_total")) == 1.5


async def test_a_restored_meter_is_not_seeded_again(ha: HomeAssistant, freezer: Any) -> None:
    """Restore wins over seeding from the total: 3 today stays 3, and the next cycle makes 4."""
    midnight = dt_util.start_of_local_day()
    await restart(
        ha, {KEY: {"name": "Demo washer", "appliance": STATISTICS}},
        (State(sensor("cycles_total"), "10"),
         {"native_value": 10, "native_unit_of_measurement": None}),
        # utility_meter's own extra data (UtilitySensorExtraStoredData.as_dict)
        (State(sensor("cycles_today"), "3"),
         {"native_value": {"__type": "<class 'decimal.Decimal'>", "decimal_str": "3"},
          "native_unit_of_measurement": None, "last_period": "0",
          "last_reset": midnight.isoformat(), "last_valid_state": "10",
          "status": "collecting", "input_device_class": "None"}),
    )
    assert value(ha, "cycles_total") == "10"
    assert float(value(ha, "cycles_today")) == 3
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 125)
    await wash(ha, freezer, 5)
    await tick(ha, freezer, 60)
    assert value(ha, "cycles_total") == "11"
    assert float(value(ha, "cycles_today")) == 4


async def test_runtime_follows_a_renamed_running(metered: HomeAssistant, freezer: Any) -> None:
    """Renamed in the UI: the entry reloads and runtime_total follows the new ID."""
    er.async_get(metered).async_update_entity(RUNNING, new_entity_id="binary_sensor.washer_running")
    await metered.async_block_till_done()
    await watts(metered, 120)
    await tick(metered, freezer, 65)
    assert metered.states.get("binary_sensor.washer_running").state == "on"
    await tick(metered, freezer, 10 * 60)
    assert float(value(metered, "runtime_total")) == pytest.approx(10 / 60, abs=0.02)


async def test_a_meter_follows_its_renamed_total(metered: HomeAssistant, freezer: Any) -> None:
    er.async_get(metered).async_update_entity(sensor("cycles_total"),
                                              new_entity_id="sensor.washer_cycles")
    await metered.async_block_till_done()
    await wash(metered, freezer, 5)
    await tick(metered, freezer, 60)
    assert metered.states.get("sensor.washer_cycles").state == "1"
    assert float(value(metered, "cycles_today")) == 1


async def test_two_devices_have_their_own_meters(ha: HomeAssistant, freezer: Any) -> None:
    other = {**STATISTICS, "power": "sensor.demo_other_power", "energy": "sensor.demo_other_energy"}
    assert await setup(ha, {KEY: {"name": "Demo washer", "appliance": STATISTICS},
                            "demo_other": {"name": "Other", "appliance": other}})
    await watts(ha, IDLE_W)
    await fake(ha, "sensor.demo_other_power", str(IDLE_W))
    await tick(ha, freezer, 125)
    await wash(ha, freezer, 5)
    await tick(ha, freezer, 60)
    assert float(value(ha, "cycles_today")) == 1
    assert float(ha.states.get("sensor.pururu_demo_other_cycles_today").state) == 0
