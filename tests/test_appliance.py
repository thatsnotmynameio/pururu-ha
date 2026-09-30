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
RUNNING = "binary_sensor.pururu_demo_washer_appliance_running"
IDLE_W = 1.4
APPLIANCE: dict[str, Any] = {
    "power": POWER,
    "energy": ENERGY,
    "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}
DEVICES = {KEY: {"name": "Demo washer", "appliance": APPLIANCE}}


def sensor(entity_key: str) -> str:
    return f"sensor.pururu_{KEY}_appliance_{entity_key}"


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
    pytest.param({key: value for key, value in APPLIANCE.items() if key != "energy"}
                 | {"statistics": {"idle_energy": ["today"]}}, id="idle_energy without energy"),
    pytest.param({**APPLIANCE, "running": {"threshold": 4, "on_delay": {"minutes": 1}}},
                 id="no off_delay"),
    pytest.param({"running": APPLIANCE["running"]}, id="no power"),
    pytest.param({**APPLIANCE, "watts": POWER}, id="unknown key"),
    pytest.param({**APPLIANCE, "running": {**APPLIANCE["running"], "threshold": "nan"}},
                 id="threshold not a number"),
    pytest.param({**APPLIANCE, "running": {**APPLIANCE["running"], "threshold": "inf"}},
                 id="threshold infinite"),
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


def value(hass: HomeAssistant, entity_key: str) -> str:
    return hass.states.get(sensor(entity_key)).state


async def test_a_finished_cycle_is_recorded(washer: HomeAssistant, freezer: Any) -> None:
    await kwh(washer, 100.0)
    await start_cycle(washer, freezer)
    started = dt_util.utcnow()
    await tick(washer, freezer, 30 * 60)
    await kwh(washer, 100.62)
    dropped = dt_util.utcnow()
    await end_cycle(washer, freezer)
    ended = dt_util.parse_datetime(value(washer, "last_cycle_end"))
    start = dt_util.parse_datetime(value(washer, "last_cycle_start"))
    assert abs((ended - dropped).total_seconds()) < 5
    assert abs((start - started).total_seconds()) < 5
    assert float(value(washer, "last_cycle_duration")) == pytest.approx(
        (ended - start).total_seconds() / 60, abs=0.1)
    assert float(value(washer, "last_cycle_energy")) == pytest.approx(0.62)
    assert value(washer, "cycles_total") == "1"


async def test_the_off_delay_is_left_out_of_the_cycle(washer: HomeAssistant,
                                                     freezer: Any) -> None:
    """A 30 min wash ends when the power goes down, not when off_delay confirms it."""
    await start_cycle(washer, freezer)
    started = dt_util.utcnow()
    await tick(washer, freezer, 30 * 60)
    dropped = dt_util.utcnow()
    await end_cycle(washer, freezer)
    assert dt_util.parse_datetime(value(washer, "last_cycle_start")) == started
    assert dt_util.parse_datetime(value(washer, "last_cycle_end")) == dropped
    assert float(value(washer, "last_cycle_duration")) == 30


async def test_a_pause_shorter_than_off_delay_stays_in_the_cycle(washer: HomeAssistant,
                                                                 freezer: Any) -> None:
    """Down for 100 s, up again for 10 min: the cycle ends at the second drop, pause included."""
    await start_cycle(washer, freezer)
    await tick(washer, freezer, 10 * 60)
    await watts(washer, IDLE_W)
    await tick(washer, freezer, 100)
    await watts(washer, 7)
    await tick(washer, freezer, 10 * 60 - 100)
    dropped = dt_util.utcnow()
    await end_cycle(washer, freezer)
    assert dt_util.parse_datetime(value(washer, "last_cycle_end")) == dropped
    assert float(value(washer, "last_cycle_duration")) == 20


async def test_reload_during_off_delay_keeps_when_the_power_went_down(
        washer: HomeAssistant, freezer: Any) -> None:
    await start_cycle(washer, freezer)
    await tick(washer, freezer, 10 * 60)
    dropped = dt_util.utcnow()
    await watts(washer, IDLE_W)
    await tick(washer, freezer, 60)
    await reload(washer, DEVICES)
    assert washer.states.get(RUNNING).attributes["cycle_end"] == dropped
    await tick(washer, freezer, 125)
    assert running(washer) == "off"
    assert dt_util.parse_datetime(value(washer, "last_cycle_end")) == dropped
    assert float(value(washer, "last_cycle_duration")) == 10


async def test_restart_during_off_delay_keeps_when_the_power_went_down(
        ha: HomeAssistant, freezer: Any) -> None:
    now = dt_util.utcnow()
    since, dropped = now - timedelta(minutes=20), now - timedelta(minutes=1)
    await restart(ha, DEVICES, (State(RUNNING, "on"), {
        "since": since.isoformat(), "since_energy": None, "until": dropped.isoformat()}))
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 125)
    assert dt_util.parse_datetime(value(ha, "last_cycle_end")) == dropped
    assert float(value(ha, "last_cycle_duration")) == 19


async def test_a_plug_without_value_during_off_delay_keeps_when_the_power_went_down(
        washer: HomeAssistant, freezer: Any) -> None:
    """The delay counts again from the next reading; the end stays when the power went down."""
    await start_cycle(washer, freezer)
    await tick(washer, freezer, 10 * 60)
    dropped = dt_util.utcnow()
    await watts(washer, IDLE_W)
    await tick(washer, freezer, 60)
    await watts(washer, "unavailable")
    await tick(washer, freezer, 120)
    assert running(washer) == "on"
    await watts(washer, IDLE_W)
    await tick(washer, freezer, 125)
    assert running(washer) == "off"
    assert dt_util.parse_datetime(value(washer, "last_cycle_end")) == dropped


async def test_before_the_first_cycle_everything_is_unknown(washer: HomeAssistant) -> None:
    for entity_key in LAST:
        assert value(washer, entity_key) == "unknown", entity_key
    assert value(washer, "cycles_total") == "0"


async def test_end_is_written_last(washer: HomeAssistant, freezer: Any) -> None:
    await kwh(washer, 100.0)
    await start_cycle(washer, freezer)
    changes = capture(washer, "state_changed")
    await end_cycle(washer, freezer)
    order = [event.data["entity_id"] for event in changes
             if event.data["entity_id"] in {sensor(entity_key) for entity_key in LAST}]
    assert order[-1] == sensor("last_cycle_end"), order
    assert set(order) == {sensor(entity_key) for entity_key in LAST}, order


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
    """Saved 20 min into a wash; the plug reports idle after the restart: one cycle of 20 min."""
    since = (dt_util.utcnow() - timedelta(minutes=20)).isoformat()
    await restart(
        ha, DEVICES,
        (State(RUNNING, "on"), {"since": since, "since_energy": 100.0}),
        (State(sensor("cycles_total"), "5"),
         {"native_value": 5, "native_unit_of_measurement": None}),
    )
    await kwh(ha, 100.4)
    await end_cycle(ha, freezer)
    assert float(value(ha, "last_cycle_duration")) == pytest.approx(20, abs=0.2)
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
    assert ha.states.get("sensor.pururu_demo_other_appliance_cycles_total").state == "0"
    assert ha.states.get("sensor.pururu_demo_other_appliance_last_cycle_end").state == "unknown"


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
    """A cycle of `minutes`, then its 2 min off delay, which isn't runtime."""
    await watts(hass, 120)
    await tick(hass, freezer, 65)
    await watts(hass, 7)
    await tick(hass, freezer, minutes * 60 - 5)
    await end_cycle(hass, freezer)


async def test_runtime_adds_the_time_running(metered: HomeAssistant, freezer: Any) -> None:
    await wash(metered, freezer, 30)
    await wash(metered, freezer, 20)
    assert float(value(metered, "runtime_total")) == pytest.approx((30 + 20) / 60, abs=0.01)


async def test_runtime_stops_while_the_end_is_pending(metered: HomeAssistant,
                                                      freezer: Any) -> None:
    """A minute passes during off_delay: it isn't added; a pause cancelled by power is."""
    await watts(metered, 120)
    await tick(metered, freezer, 65)
    await tick(metered, freezer, 10 * 60)
    await watts(metered, IDLE_W)
    before = float(value(metered, "runtime_total"))
    await tick(metered, freezer, 110)
    assert running(metered) == "on"
    assert float(value(metered, "runtime_total")) == before
    await watts(metered, 7)
    await tick(metered, freezer, 60)
    assert float(value(metered, "runtime_total")) == pytest.approx(before + 170 / 3600,
                                                                   abs=0.001)


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


async def test_a_meter_is_not_created_without_its_total(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """The statistics aspect's meter follows its builder's total: a total not created takes it along."""
    er.async_get(ha).async_get_or_create(
        "sensor", "template", "someone_else", suggested_object_id="pururu_demo_washer_appliance_cycles_total")
    assert await setup(ha, {KEY: {"name": "Demo washer", "appliance": STATISTICS}})
    assert ha.states.get(sensor("cycles_today")) is None
    assert ha.states.get(sensor("runtime_today")) is not None
    assert (f"{sensor('cycles_today')} follows {sensor('cycles_total')}, which is not created; "
            "not creating it") in caplog.text


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
    assert float(ha.states.get("sensor.pururu_demo_other_appliance_cycles_today").state) == 0


# --- cycle_start -------------------------------------------------------------


async def test_cycle_start_is_shown_while_running(washer: HomeAssistant, freezer: Any) -> None:
    assert "cycle_start" not in washer.states.get(RUNNING).attributes
    started = dt_util.utcnow() + timedelta(seconds=65)
    await start_cycle(washer, freezer)
    assert washer.states.get(RUNNING).attributes["cycle_start"] == started
    await end_cycle(washer, freezer)
    assert "cycle_start" not in washer.states.get(RUNNING).attributes


async def test_cycle_end_is_shown_while_the_end_is_pending(washer: HomeAssistant,
                                                          freezer: Any) -> None:
    await start_cycle(washer, freezer)
    assert "cycle_end" not in washer.states.get(RUNNING).attributes
    dropped = dt_util.utcnow()
    await watts(washer, IDLE_W)
    assert washer.states.get(RUNNING).attributes["cycle_end"] == dropped
    await tick(washer, freezer, 60)
    await watts(washer, 7)
    assert "cycle_end" not in washer.states.get(RUNNING).attributes
    await end_cycle(washer, freezer)
    assert "cycle_end" not in washer.states.get(RUNNING).attributes


async def test_cycle_start_is_kept_across_a_restart(ha: HomeAssistant) -> None:
    since = dt_util.utcnow() - timedelta(minutes=20)
    await restart(ha, DEVICES, (State(RUNNING, "on"),
                                {"since": since.isoformat(), "since_energy": 100.0}))
    assert ha.states.get(RUNNING).attributes["cycle_start"] == since


# --- idle energy ---------------------------------------------------------------

IDLE = {**APPLIANCE, "statistics": {"idle_energy": ["today", "month"]}}


@pytest.fixture
async def idle(ha: HomeAssistant, freezer: Any) -> HomeAssistant:
    """The demo washer counting its idle energy, idle, its counter at 100 kWh."""
    assert await setup(ha, {KEY: {"name": "Demo washer", "appliance": IDLE}})
    await kwh(ha, 100.0)
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 125)
    assert running(ha) == "off"
    return ha


def idle_kwh(hass: HomeAssistant) -> float:
    return float(value(hass, "idle_energy_total"))


async def test_idle_energy_adds_what_the_counter_grows_while_idle(idle: HomeAssistant) -> None:
    assert idle_kwh(idle) == 0
    await kwh(idle, 100.01)
    await kwh(idle, 100.025)
    assert idle_kwh(idle) == pytest.approx(0.025)
    state = idle.states.get(sensor("idle_energy_total"))
    assert state.attributes["unit_of_measurement"] == "kWh"
    assert state.attributes["device_class"] == "energy"
    assert state.attributes["state_class"] == "total_increasing"


async def test_idle_energy_leaves_the_cycles_out(idle: HomeAssistant, freezer: Any) -> None:
    """The cycle's energy and the idle energy add up to the counter's growth, no overlap."""
    await kwh(idle, 100.01)
    await watts(idle, 120)
    await kwh(idle, 100.02)  # the on_delay: still idle
    await tick(idle, freezer, 65)
    assert running(idle) == "on"
    await kwh(idle, 100.5)
    await kwh(idle, 100.8)
    await watts(idle, IDLE_W)
    await kwh(idle, 100.81)  # the off_delay: still the cycle
    await tick(idle, freezer, 125)
    assert running(idle) == "off"
    await kwh(idle, 100.83)
    assert idle_kwh(idle) == pytest.approx(0.02 + 0.02)
    assert float(value(idle, "last_cycle_energy")) == pytest.approx(0.79)


async def test_idle_energy_is_in_kwh_whatever_the_counter_unit(idle: HomeAssistant) -> None:
    await fake(idle, ENERGY, "100000", {"unit_of_measurement": "Wh"})
    await fake(idle, ENERGY, "100040", {"unit_of_measurement": "Wh"})
    assert idle_kwh(idle) == pytest.approx(0.04)


async def test_idle_energy_carries_over_a_counter_without_value(idle: HomeAssistant) -> None:
    await kwh(idle, "unavailable")
    await kwh(idle, 100.03)
    assert idle_kwh(idle) == pytest.approx(0.03)


async def test_idle_energy_starts_from_the_first_reading(ha: HomeAssistant,
                                                         freezer: Any) -> None:
    """Idle before the counter has a value: counting starts from its first reading."""
    assert await setup(ha, {KEY: {"name": "Demo washer", "appliance": IDLE}})
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 125)
    await kwh(ha, 100.0)
    await kwh(ha, 100.01)
    assert idle_kwh(ha) == pytest.approx(0.01)


async def test_idle_energy_is_never_negative(idle: HomeAssistant) -> None:
    """A counter going down (the plug re-paired) adds nothing and counts on from there."""
    await kwh(idle, 100.01)
    await kwh(idle, 0.2)
    await kwh(idle, 0.21)
    assert idle_kwh(idle) == pytest.approx(0.02)


async def test_idle_energy_unknown_when_a_cycle_starts_is_lost(idle: HomeAssistant,
                                                               freezer: Any) -> None:
    await kwh(idle, "unavailable")
    await start_cycle(idle, freezer)
    await kwh(idle, 100.5)
    await end_cycle(idle, freezer)
    await kwh(idle, 100.52)
    assert idle_kwh(idle) == pytest.approx(0.02)


async def test_idle_energy_restores_without_the_time_ha_was_down(ha: HomeAssistant) -> None:
    """The counter's reading at the start may be from before the restart: count from the next."""
    await kwh(ha, 100.4)
    await restart(ha, {KEY: {"name": "Demo washer", "appliance": IDLE}},
                  (State(RUNNING, "off"), {"since": None, "since_energy": None}),
                  (State(sensor("idle_energy_total"), "1.5"),
                   {"native_value": 1.5, "native_unit_of_measurement": "kWh"}))
    assert idle_kwh(ha) == 1.5
    await kwh(ha, 100.9)  # the plug's first fresh reading: a cycle may have run meanwhile
    assert idle_kwh(ha) == 1.5
    await kwh(ha, 100.91)
    assert idle_kwh(ha) == pytest.approx(1.51)


async def test_idle_energy_after_a_reload_counts_from_the_next_reading(
        idle: HomeAssistant) -> None:
    await kwh(idle, 100.01)
    await reload(idle, {KEY: {"name": "Demo washer", "appliance": IDLE}})
    await kwh(idle, 100.02)
    assert idle_kwh(idle) == pytest.approx(0.01)
    await kwh(idle, 100.03)
    assert idle_kwh(idle) == pytest.approx(0.02)


async def test_idle_energy_meters(idle: HomeAssistant, freezer: Any) -> None:
    await kwh(idle, 100.02)
    await tick(idle, freezer, 60)
    assert float(value(idle, "idle_energy_today")) == pytest.approx(0.02)
    assert float(value(idle, "idle_energy_month")) == pytest.approx(0.02)
    assert idle.states.get(sensor("idle_energy_week")) is None


async def test_idle_energy_names(idle: HomeAssistant) -> None:
    assert (idle.states.get(sensor("idle_energy_total")).attributes["friendly_name"]
            == "Demo washer Idle energy")
    assert (idle.states.get(sensor("idle_energy_today")).attributes["friendly_name"]
            == "Demo washer Idle energy today")


async def test_without_energy_there_is_no_idle_energy(ha: HomeAssistant) -> None:
    block = {key: value for key, value in APPLIANCE.items() if key != "energy"}
    assert await setup(ha, {KEY: {"name": "Demo washer", "appliance": block}})
    assert ha.states.get(sensor("idle_energy_total")) is None
