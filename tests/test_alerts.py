"""Feature `alerts`: problems on a made-up washer's own entities (its appliance and a switch)."""

from typing import Any

from homeassistant.core import CoreState, HomeAssistant, State
from homeassistant.helpers import entity_registry as er
import pytest

from helpers import capture, fake, held, reload, restart, settle, setup, tick

KEY = "demo_washer"
POWER = "sensor.demo_plug_power"
MIRROR = "sensor.pururu_demo_washer_appliance_power"
REAL_PUMP = "switch.demo_pump"
APPLIANCE: dict[str, Any] = {
    "power": POWER,
    "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}
SWITCHES = {"pump": {"entity": REAL_PUMP, "name": "Bomba"}}
OVERLOAD = {"name": "Overload", "when": "appliance_power", "above": 2500}
PUMP_ON = {"name": "Pump on", "when": "switch_pump", "is": "on"}


def alert(key: str) -> str:
    return f"binary_sensor.pururu_{KEY}_alert_{key}"


def devices(**alerts: dict[str, Any]) -> dict[str, Any]:
    return {KEY: {"name": "Demo washer", "appliance": APPLIANCE, "switches": SWITCHES,
                  "alerts": alerts}}


def state(hass: HomeAssistant, entity_id: str) -> str:
    return hass.states.get(entity_id).state


# --- configuration ----------------------------------------------------------------


NOT_AN_ENTITY_KEY = "is not an entity key of another feature of this device"


@pytest.mark.parametrize(("block", "reason"), [
    pytest.param({"when": "appliance_power", "above": 1},
                 "required key 'name' not provided", id="no name"),
    pytest.param({**OVERLOAD, "name": " "},
                 "length of value must be at least 1 for dictionary value "
                 "'pururu->devices->demo_washer->alerts->overload->name'", id="empty name"),
    pytest.param({"name": "X", "above": 1}, "required key 'when' not provided", id="no when"),
    pytest.param({"name": "X", "when": "appliance_power"},
                 "an alert needs is, or above and/or below, not both", id="no condition"),
    pytest.param({**OVERLOAD, "is": "on"},
                 "an alert needs is, or above and/or below, not both", id="is and above"),
    pytest.param({**OVERLOAD, "below": 2500},
                 "an alert's above must be lower than its below", id="above not lower than below"),
    pytest.param({**OVERLOAD, "above": "nan"},
                 "expected a finite number, got 'nan'", id="above not finite"),
    pytest.param({**OVERLOAD, "priority": "urgent"},
                 "value must be one of ['high', 'low', 'medium'] for dictionary value "
                 "'pururu->devices->demo_washer->alerts->overload->priority'", id="unknown priority"),
    pytest.param({**OVERLOAD, "for": "soon"},
                 "'pururu->devices->demo_washer->alerts->overload->for', got 'soon'",
                 id="for not a period"),
    pytest.param({**OVERLOAD, "colour": "red"},
                 "'colour' is an invalid option for 'pururu', check: "
                 "pururu->devices->demo_washer->alerts->overload->colour", id="unknown key"),
    pytest.param({**OVERLOAD, "when": "appliance_nothing"},
                 f"alerts: appliance_nothing {NOT_AN_ENTITY_KEY}", id="when an unknown entity key"),
    pytest.param({**OVERLOAD, "when": "switch_heater"},
                 f"alerts: switch_heater {NOT_AN_ENTITY_KEY}", id="when a switch the device lacks"),
    pytest.param({**OVERLOAD, "when": "alert_other"},
                 f"alerts: alert_other {NOT_AN_ENTITY_KEY}", id="when an alert"),
    pytest.param({**OVERLOAD, "when": "power"},
                 f"alerts: power {NOT_AN_ENTITY_KEY}", id="when without its namespace"),
])
async def test_invalid_alert_is_refused(ha: HomeAssistant, caplog: pytest.LogCaptureFixture,
                                        block: dict[str, Any], reason: str) -> None:
    """Refused, and for its own reason: a typo in the test would be refused for another one."""
    assert not await setup(ha, devices(overload=block, other=OVERLOAD))
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(reason in message for message in errors), errors


async def test_an_empty_block_is_refused(ha: HomeAssistant) -> None:
    assert not await setup(ha, devices())


async def test_alerts_alone_are_not_a_feature(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """`alerts` is a device key, like `programs`: neither counts as a device's feature."""
    program = {"name": "X", "sequence": [{"turn_on": "switch_pump"}]}
    assert not await setup(ha, {KEY: {"name": "Demo washer", "programs": {"it": program},
                                      "alerts": {"overload": OVERLOAD}}})
    # Only the real features, in FEATURES' order: alerts is none of them
    assert ("a device needs at least one feature "
            "(appliance, door, window, lights, phases, modes, switches)" in caplog.text)


async def test_a_when_of_no_entity_key_names_it(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    assert not await setup(ha, devices(overload={**OVERLOAD, "when": "appliance_nothing"}))
    assert ("alerts: appliance_nothing is not an entity key of another feature of this device"
            in caplog.text)


async def test_an_alert_may_watch_a_meter(ha: HomeAssistant) -> None:
    """A meter the statistics aspect adds is another feature's entity key: an alert watches it."""
    long_day = {"name": "Long day", "when": "appliance_runtime_today", "above": 5}
    metered = {**APPLIANCE, "statistics": {"runtime": ["today"]}}
    assert await setup(ha, {KEY: {"name": "Demo washer", "appliance": metered,
                                  "alerts": {"long_day": long_day}}})
    assert ha.states.get(alert("long_day")) is not None


async def test_an_alert_may_watch_a_programs_statistic(ha: HomeAssistant) -> None:
    """A program's statistic is a device key's entity key, not a feature's: an alert still watches it."""
    program = {"name": "Clean", "sequence": [{"turn_on": "switch_pump"}]}
    too_many = {"name": "Too many", "when": "program_clean_cycles_total", "above": 5}
    assert await setup(ha, {KEY: {"name": "Demo washer", "switches": SWITCHES,
                                  "programs": {"clean": program},
                                  "alerts": {"too_many": too_many}}})
    assert ha.states.get(alert("too_many")) is not None


NOTIFY = {"message": "Overload!", "done_message": "Back to normal."}
NOTIFY_PATH = "pururu->devices->demo_washer->alerts->overload->notify"


@pytest.mark.parametrize(("notify", "reason"), [
    pytest.param({"done_message": "OK"}, "required key 'message' not provided", id="no message"),
    pytest.param({"message": "X"}, "required key 'done_message' not provided",
                 id="no done_message"),
    pytest.param({**NOTIFY, "message": " "},
                 f"length of value must be at least 1 for dictionary value '{NOTIFY_PATH}->message'",
                 id="empty message"),
    pytest.param({**NOTIFY, "title": "X"},
                 f"'title' is an invalid option for 'pururu', check: {NOTIFY_PATH}->title",
                 id="unknown key"),
])
async def test_invalid_notify_is_refused(ha: HomeAssistant, caplog: pytest.LogCaptureFixture,
                                         notify: dict[str, Any], reason: str) -> None:
    assert not await setup(ha, devices(overload={**OVERLOAD, "notify": notify}))
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(reason in message for message in errors), errors


# --- the entity ---------------------------------------------------------------------


async def test_an_alert_is_a_problem_sensor_in_the_device(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(overload=OVERLOAD))
    overload = ha.states.get(alert("overload"))
    assert overload.state == "off"
    assert overload.attributes["friendly_name"] == "Demo washer Overload"
    assert overload.attributes["device_class"] == "problem"
    assert overload.attributes["priority"] == "low"
    assert overload.attributes["watches"] == MIRROR
    assert alert("overload") in held(ha, KEY)
    entry = er.async_get(ha).async_get(alert("overload"))
    assert entry is not None
    assert entry.unique_id == "pururu_demo_washer_alert_overload"
    assert entry.translation_key is None
    assert entry.entity_category is None


async def test_priority_is_an_attribute(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(overload={**OVERLOAD, "priority": "high"}))
    assert ha.states.get(alert("overload")).attributes["priority"] == "high"


async def test_the_name_is_the_same_in_portuguese(ha: HomeAssistant) -> None:
    ha.config.language = "pt-BR"
    assert await setup(ha, devices(overload=OVERLOAD))
    assert ha.states.get(alert("overload")).attributes["friendly_name"] == "Demo washer Overload"


async def test_notify_texts_are_attributes(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(overload={**OVERLOAD, "notify": NOTIFY}))
    attributes = ha.states.get(alert("overload")).attributes
    assert attributes["message"] == "Overload!"
    assert attributes["done_message"] == "Back to normal."


async def test_without_notify_there_are_no_texts(ha: HomeAssistant) -> None:
    """Only an alert with notify carries what to tell."""
    assert await setup(ha, devices(overload=OVERLOAD))
    attributes = ha.states.get(alert("overload")).attributes
    assert "message" not in attributes
    assert "done_message" not in attributes


# --- Alert2 ------------------------------------------------------------------------------

NOTIFY_ERROR = "has notify, but Alert2 isn't set up to deliver it"


def notify_errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.levelname == "ERROR" and NOTIFY_ERROR in r.getMessage()]


async def test_notify_without_alert2_is_an_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    assert await setup(ha, devices(overload={**OVERLOAD, "notify": NOTIFY}, other=OVERLOAD))
    assert notify_errors(caplog) == [f"{alert('overload')} {NOTIFY_ERROR}"]


async def test_notify_with_alert2_is_no_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    ha.config.components.add("alert2")
    assert await setup(ha, devices(overload={**OVERLOAD, "notify": NOTIFY}))
    assert notify_errors(caplog) == []


async def test_without_notify_there_is_no_alert2_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    assert await setup(ha, devices(overload=OVERLOAD))
    assert notify_errors(caplog) == []


async def test_alert2_set_up_before_the_start_is_no_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Alert2 may load after pururu: the check waits for Home Assistant to start."""
    ha.set_state(CoreState.not_running)
    assert await setup(ha, devices(overload={**OVERLOAD, "notify": NOTIFY}))
    ha.config.components.add("alert2")
    await ha.async_start()
    await ha.async_block_till_done()
    assert notify_errors(caplog) == []


async def test_the_alert2_error_is_logged_once_per_setup(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    config = devices(overload={**OVERLOAD, "notify": NOTIFY})
    assert await setup(ha, config)
    caplog.clear()
    await reload(ha, config)
    assert notify_errors(caplog) == [f"{alert('overload')} {NOTIFY_ERROR}"]


# --- is ------------------------------------------------------------------------------


async def test_is_turns_on_after_for_and_off_at_once(ha: HomeAssistant, freezer: Any) -> None:
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, devices(pump_on={**PUMP_ON, "for": {"minutes": 5}}))
    await fake(ha, REAL_PUMP, "on")
    await tick(ha, freezer, 299)
    assert state(ha, alert("pump_on")) == "off"
    await tick(ha, freezer, 1)
    assert state(ha, alert("pump_on")) == "on"
    await fake(ha, REAL_PUMP, "off")
    assert state(ha, alert("pump_on")) == "off"


async def test_without_for_it_turns_on_at_once(ha: HomeAssistant) -> None:
    await fake(ha, REAL_PUMP, "on")
    assert await setup(ha, devices(pump_on=PUMP_ON))
    assert state(ha, alert("pump_on")) == "on"


async def test_unquoted_on_means_the_on_state(ha: HomeAssistant) -> None:
    """YAML reads `is: on` as a boolean."""
    await fake(ha, REAL_PUMP, "on")
    assert await setup(ha, devices(pump_on={**PUMP_ON, "is": True}))
    assert state(ha, alert("pump_on")) == "on"


@pytest.mark.parametrize("unquoted", [True, "yes"])
async def test_yaml_booleans_mean_on(ha: HomeAssistant, unquoted: Any) -> None:
    """YAML reads unquoted on, yes and true alike; "yes" stands for what the loader gives."""
    await fake(ha, REAL_PUMP, "on")
    value = True if unquoted == "yes" else unquoted
    assert await setup(ha, devices(pump_on={**PUMP_ON, "is": value}))
    assert state(ha, alert("pump_on")) == "on"


@pytest.mark.parametrize("watts", ["1", "1.0", "1.00"])
async def test_a_number_in_is_compares_as_a_number(ha: HomeAssistant, watts: str) -> None:
    assert await setup(ha, devices(one={"name": "One", "when": "appliance_power", "is": 1}))
    await fake(ha, POWER, watts)
    assert state(ha, alert("one")) == "on"


async def test_a_number_in_is_holds_its_state_without_a_reading(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(one={"name": "One", "when": "appliance_power", "is": 1}))
    await fake(ha, POWER, "1")
    await fake(ha, POWER, "unavailable")
    assert state(ha, alert("one")) == "on"
    await fake(ha, POWER, "2")
    assert state(ha, alert("one")) == "off"


async def test_for_starts_over_when_the_condition_stops_holding(
        ha: HomeAssistant, freezer: Any) -> None:
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, devices(pump_on={**PUMP_ON, "for": {"minutes": 5}}))
    await fake(ha, REAL_PUMP, "on")
    await tick(ha, freezer, 240)
    await fake(ha, REAL_PUMP, "off")
    await fake(ha, REAL_PUMP, "on")
    await tick(ha, freezer, 240)
    assert state(ha, alert("pump_on")) == "off"
    await tick(ha, freezer, 60)
    assert state(ha, alert("pump_on")) == "on"


# --- above and below ----------------------------------------------------------------


@pytest.mark.parametrize(("condition", "watts", "expected"), [
    pytest.param({"above": 2500}, "2500", "off", id="at above"),
    pytest.param({"above": 2500}, "2501", "on", id="above above"),
    pytest.param({"below": 1}, "1", "off", id="at below"),
    pytest.param({"below": 1}, "0.5", "on", id="below below"),
    pytest.param({"above": 100, "below": 200}, "150", "on", id="inside a range"),
    pytest.param({"above": 100, "below": 200}, "200", "off", id="at a range's below"),
])
async def test_above_and_below_are_strict(
        ha: HomeAssistant, condition: dict[str, float], watts: str, expected: str) -> None:
    assert await setup(ha, devices(power={"name": "Power", "when": "appliance_power",
                                          **condition}))
    await fake(ha, POWER, watts)
    assert state(ha, alert("power")) == expected


async def test_above_on_a_state_that_is_not_a_number_never_turns_on(ha: HomeAssistant) -> None:
    await fake(ha, REAL_PUMP, "on")
    assert await setup(ha, devices(pump={"name": "Pump", "when": "switch_pump", "above": 0}))
    assert state(ha, alert("pump")) == "off"


# --- no reading ---------------------------------------------------------------------


@pytest.mark.parametrize("gone", ["unavailable", "unknown", "not a number"])
async def test_no_reading_keeps_on(ha: HomeAssistant, gone: str) -> None:
    assert await setup(ha, devices(overload=OVERLOAD))
    await fake(ha, POWER, "3000")
    assert state(ha, alert("overload")) == "on"
    await fake(ha, POWER, gone)
    assert state(ha, alert("overload")) == "on"


async def test_no_reading_keeps_off_and_cancels_a_pending_for(
        ha: HomeAssistant, freezer: Any) -> None:
    assert await setup(ha, devices(overload={**OVERLOAD, "for": {"minutes": 1}}))
    await fake(ha, POWER, "3000")
    await tick(ha, freezer, 50)
    await fake(ha, POWER, "unavailable")
    await tick(ha, freezer, 20)
    assert state(ha, alert("overload")) == "off"
    await fake(ha, POWER, "3000")
    await tick(ha, freezer, 50)
    assert state(ha, alert("overload")) == "off"
    await tick(ha, freezer, 10)
    assert state(ha, alert("overload")) == "on"


async def test_is_unavailable_turns_on_when_the_plug_goes_offline(
        ha: HomeAssistant, freezer: Any) -> None:
    offline = {"name": "Offline", "when": "appliance_power", "is": "unavailable",
               "for": {"minutes": 10}}
    assert await setup(ha, devices(offline=offline))
    await fake(ha, POWER, "10")
    assert state(ha, alert("offline")) == "off"
    await fake(ha, POWER, "unavailable")
    await tick(ha, freezer, 599)
    assert state(ha, alert("offline")) == "off"
    await tick(ha, freezer, 1)
    assert state(ha, alert("offline")) == "on"
    await fake(ha, POWER, "5")
    assert state(ha, alert("offline")) == "off"


OFFLINE = {"name": "Offline", "when": "appliance_power", "is": "unavailable"}


def states_of(events: list[Any], entity_id: str) -> list[str]:
    """The states `entity_id` was written with, in order."""
    return [event.data["new_state"].state for event in events
            if event.data["entity_id"] == entity_id and event.data["new_state"] is not None]


async def test_setting_up_with_a_reading_raises_no_false_alarm(ha: HomeAssistant) -> None:
    """At setup, the watched entity may not exist yet: that's no reading, not offline."""
    await fake(ha, POWER, "10")
    events = capture(ha, "state_changed")
    assert await setup(ha, devices(offline=OFFLINE))
    assert "on" not in states_of(events, alert("offline"))
    assert state(ha, alert("offline")) == "off"


async def test_a_reload_with_a_reading_raises_no_false_alarm(ha: HomeAssistant) -> None:
    await fake(ha, POWER, "10")
    assert await setup(ha, devices(offline=OFFLINE))
    events = capture(ha, "state_changed")
    await reload(ha, devices(offline=OFFLINE))
    assert "on" not in states_of(events, alert("offline"))
    assert state(ha, alert("offline")) == "off"


async def test_a_restart_with_a_reading_raises_no_false_alarm(ha: HomeAssistant) -> None:
    await fake(ha, POWER, "10")
    events = capture(ha, "state_changed")
    await restart(ha, devices(offline=OFFLINE), (State(alert("offline"), "off"), {}))
    assert "on" not in states_of(events, alert("offline"))
    assert state(ha, alert("offline")) == "off"


async def test_a_plug_offline_at_start_turns_it_on(ha: HomeAssistant) -> None:
    await fake(ha, POWER, "unavailable")
    await restart(ha, devices(offline=OFFLINE), (State(alert("offline"), "off"), {}))
    assert state(ha, alert("offline")) == "on"


@pytest.mark.parametrize("condition", ["unavailable", "unknown"])
@pytest.mark.parametrize("gone", ["unavailable", "unknown"])
async def test_unavailable_and_unknown_are_both_offline(
        ha: HomeAssistant, condition: str, gone: str) -> None:
    assert await setup(ha, devices(offline={**OFFLINE, "is": condition}))
    await fake(ha, POWER, "10")
    await fake(ha, POWER, gone)
    assert state(ha, alert("offline")) == "on"


async def test_passing_between_unavailable_and_unknown_keeps_counting(
        ha: HomeAssistant, freezer: Any) -> None:
    """A plug reconnecting shows unknown for a moment: still offline, for goes on."""
    assert await setup(ha, devices(offline={**OFFLINE, "for": {"minutes": 10}}))
    await fake(ha, POWER, "10")
    await fake(ha, POWER, "unavailable")
    await tick(ha, freezer, 480)
    await fake(ha, POWER, "unknown")
    await fake(ha, POWER, "unavailable")
    await tick(ha, freezer, 119)
    assert state(ha, alert("offline")) == "off"
    await tick(ha, freezer, 1)
    assert state(ha, alert("offline")) == "on"


async def test_a_missing_entity_counts_as_unavailable(ha: HomeAssistant) -> None:
    offline = {"name": "Offline", "when": "appliance_power", "is": "unavailable"}
    assert await setup(ha, devices(offline=offline))
    await fake(ha, POWER, "10")
    assert state(ha, alert("offline")) == "off"
    ha.states.async_remove(MIRROR)
    await settle()
    assert state(ha, alert("offline")) == "on"


# --- what it follows ----------------------------------------------------------------


async def test_an_alert_on_an_entity_its_settings_dont_build_is_not_created(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """appliance_runtime_month is an entity key appliance can create: valid, never built here."""
    month = {"name": "Month", "when": "appliance_runtime_month", "above": 10}
    assert await setup(ha, devices(month=month))
    assert ha.states.get(alert("month")) is None
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert (f"{alert('month')} watches sensor.pururu_demo_washer_appliance_runtime_month, which "
            "this device's settings don't create (turn it on, or watch another entity); "
            "not creating it" in errors), errors


async def test_no_alert_when_its_entity_is_not_created(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(
        "sensor", "template", "someone_else", suggested_object_id="pururu_demo_washer_appliance_power")
    assert await setup(ha, devices(overload=OVERLOAD))
    assert ha.states.get(alert("overload")) is None
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(alert("overload") in message and MIRROR in message for message in errors), errors


async def test_follows_a_renamed_entity(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(overload=OVERLOAD))
    er.async_get(ha).async_update_entity(MIRROR, new_entity_id="sensor.washer_power")
    await ha.async_block_till_done()
    assert ha.states.get(alert("overload")).attributes["watches"] == "sensor.washer_power"
    await fake(ha, POWER, "3000")
    assert state(ha, alert("overload")) == "on"


# --- restarts ----------------------------------------------------------------------------


async def test_restart_keeps_on_while_it_holds(ha: HomeAssistant) -> None:
    await fake(ha, POWER, "3000")
    await restart(ha, devices(overload={**OVERLOAD, "for": {"minutes": 1}}),
                  (State(alert("overload"), "on"), {}))
    assert state(ha, alert("overload")) == "on"


async def test_restart_keeps_the_restored_state_without_a_reading(ha: HomeAssistant) -> None:
    await restart(ha, devices(overload=OVERLOAD), (State(alert("overload"), "on"), {}))
    assert state(ha, alert("overload")) == "on"


async def test_restart_starts_a_pending_for_over(ha: HomeAssistant, freezer: Any) -> None:
    await fake(ha, POWER, "3000")
    await restart(ha, devices(overload={**OVERLOAD, "for": {"minutes": 1}}),
                  (State(alert("overload"), "off"), {}))
    assert state(ha, alert("overload")) == "off"
    await tick(ha, freezer, 59)
    assert state(ha, alert("overload")) == "off"
    await tick(ha, freezer, 1)
    assert state(ha, alert("overload")) == "on"
