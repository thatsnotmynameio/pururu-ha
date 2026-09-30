"""Ready-made alerts: an appliance's own, on a made-up washer."""

from datetime import timedelta
from pathlib import Path
import re
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
import pytest
import yaml

from helpers import capture, fake, held, module, reload, restart, setup, tick

KEY = "demo_washer"
POWER = "sensor.demo_plug_power"
APPLIANCE: dict[str, Any] = {
    "power": POWER,
    "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}


def devices(enabled: Any, **device: Any) -> dict[str, Any]:
    return {KEY: {"name": "Demo washer", "appliance": {**APPLIANCE, "alerts": enabled}, **device}}


# --- configuration ------------------------------------------------------------------------


@pytest.mark.parametrize("alerts", [
    pytest.param({"offline": None}, id="null is every default"),
    pytest.param({"offline": {}}, id="empty is every default"),
    pytest.param({"offline": {"for": {"minutes": 1}, "priority": "high",
                              "notify": {"message": "m", "done_message": "d"}}}, id="all set"),
    pytest.param({"long_cycle": {"for": {"hours": 3}}}, id="required for"),
    pytest.param({"no_cycle": {"for": {"days": 2}}}, id="no_cycle"),
    pytest.param({"no_power": None}, id="no_power"),
])
async def test_valid_alerts_are_accepted(ha: HomeAssistant, alerts: Any) -> None:
    assert await setup(ha, devices(alerts))


@pytest.mark.parametrize(("alerts", "reason"), [
    pytest.param({"nope": None}, "nope is not a ready-made alert: offline, no_power, "
                 "long_cycle, no_cycle", id="unknown alert"),
    pytest.param({"long_cycle": None}, "required key 'for' not provided", id="for missing"),
    pytest.param({"offline": {"lasts": {"minutes": 1}}}, "'lasts' is an invalid option",
                 id="lasts on offline"),
    pytest.param({"offline": {"priority": "urgent"}}, "value must be one of",
                 id="unknown priority"),
    pytest.param({"offline": {"notify": {"message": "m"}}}, "required key 'done_message'",
                 id="incomplete notify"),
    pytest.param({}, "length of value must be at least 1", id="empty"),
    pytest.param({"offline": {"for": {"minutes": -1}}}, "offline", id="negative for"),
])
async def test_invalid_alerts_are_refused(ha: HomeAssistant, caplog: pytest.LogCaptureFixture,
                                          alerts: Any, reason: str) -> None:
    assert not await setup(ha, devices(alerts))
    assert reason in caplog.text


async def test_finished_as_an_alert_is_an_unknown_alert(ha: HomeAssistant,
                                                        caplog: pytest.LogCaptureFixture) -> None:
    """`finished` is a ready-made notification, not an alert: refused as any unknown alert."""
    assert not await setup(ha, devices({"offline": None, "finished": {"lasts": {"minutes": 30}}}))
    assert ("finished is not a ready-made alert: offline, no_power, long_cycle, no_cycle"
            in caplog.text)
    assert "is now a notification" not in caplog.text


async def test_without_alerts_none_is_enabled(ha: HomeAssistant) -> None:
    """A block without `alerts` enables no ready-made alert, and nothing is refused."""
    assert await setup(ha, {KEY: {"name": "Demo washer", "appliance": APPLIANCE}})
    assert not [entity_id for entity_id in held(ha, KEY) if "_alert_" in entity_id]


async def test_a_hand_written_alert_cannot_watch_a_ready_made_one(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    watching = {"it": {"name": "It", "when": "appliance_alert_offline", "is": "on"}}
    assert not await setup(ha, devices({"offline": None}, alerts=watching))
    assert "appliance_alert_offline is an alert: an alert can't watch another" in caplog.text


async def test_a_reaction_can_react_to_a_ready_made_alert(ha: HomeAssistant) -> None:
    reaction = {"off": {"name": "Offline", "when": "appliance_alert_offline", "to": "on"}}
    assert await setup(ha, devices({"offline": None}, reactions=reaction))


# --- condition alerts ---------------------------------------------------------------------


def alert(name: str) -> str:
    return f"binary_sensor.pururu_{KEY}_appliance_alert_{name}"


def state(ha: HomeAssistant, entity_id: str) -> str:
    found = ha.states.get(entity_id)
    assert found is not None, entity_id
    return found.state


async def test_only_enabled_alerts_are_created(ha: HomeAssistant) -> None:
    assert await setup(ha, devices({"offline": None}))
    assert alert("offline") in held(ha, KEY)
    assert ha.states.get(alert("no_power")) is None


async def test_offline_turns_on_after_ten_minutes_without_a_reading(
        ha: HomeAssistant, freezer: Any) -> None:
    assert await setup(ha, devices({"offline": None}))
    await fake(ha, POWER, "3")
    await fake(ha, POWER, "unavailable")
    await tick(ha, freezer, 599)
    assert state(ha, alert("offline")) == "off"
    await tick(ha, freezer, 1)
    assert state(ha, alert("offline")) == "on"
    await fake(ha, POWER, "3")
    assert state(ha, alert("offline")) == "off"


async def test_no_power_turns_on_at_zero_and_keeps_its_state_without_a_reading(
        ha: HomeAssistant, freezer: Any) -> None:
    assert await setup(ha, devices({"no_power": {"for": {"minutes": 1}}}))
    await fake(ha, POWER, "0.0")
    await tick(ha, freezer, 60)
    assert state(ha, alert("no_power")) == "on"
    await fake(ha, POWER, "unavailable")
    assert state(ha, alert("no_power")) == "on"
    await fake(ha, POWER, "0.4")
    assert state(ha, alert("no_power")) == "off"


async def test_its_name_attributes_and_default_texts(ha: HomeAssistant) -> None:
    assert await setup(ha, devices({"offline": {"priority": "high"}}))
    found = ha.states.get(alert("offline"))
    assert found.attributes["friendly_name"] == "Demo washer Offline"
    assert found.attributes["device_class"] == "problem"
    assert found.attributes["priority"] == "high"
    assert found.attributes["watches"] == "sensor.pururu_demo_washer_appliance_power"
    assert found.attributes["message"] == "The plug is offline."
    assert found.attributes["done_message"] == "The plug is back."


async def test_default_texts_in_the_language_of_home_assistant(ha: HomeAssistant) -> None:
    ha.config.language = "pt-BR"
    assert await setup(ha, devices({"offline": None}))
    found = ha.states.get(alert("offline"))
    assert found.attributes["message"] == "A tomada está sem conexão."
    assert found.attributes["done_message"] == "A tomada voltou."


async def test_a_language_without_translations_gets_english_texts(ha: HomeAssistant) -> None:
    ha.config.language = "de"
    assert await setup(ha, devices({"offline": None}))
    assert ha.states.get(alert("offline")).attributes["message"] == "The plug is offline."


async def test_notify_replaces_the_default_texts(ha: HomeAssistant) -> None:
    notify = {"message": "Sem Wi-Fi!", "done_message": "Voltou."}
    assert await setup(ha, devices({"offline": {"notify": notify}}))
    found = ha.states.get(alert("offline"))
    assert found.attributes["message"] == "Sem Wi-Fi!"
    assert found.attributes["done_message"] == "Voltou."


async def test_it_is_an_alert2_alert(ha: HomeAssistant) -> None:
    assert await setup(ha, devices({"offline": None}))
    path = Path(ha.config.path("pururu/alert2/alerts.yaml"))
    [entry] = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert entry == {
        "domain": "pururu",
        "name": "demo_washer_appliance_alert_offline",
        "friendly_name": "Demo washer Offline",
        "condition_on": f"{{{{ is_state('{alert('offline')}', 'on') }}}}",
        "condition_off": f"{{{{ is_state('{alert('offline')}', 'off') }}}}",
        "priority": "medium",
        "message": "The plug is offline.",
        "done_message": "The plug is back.",
    }


async def test_a_ready_made_alert_comes_back_as_it_was(ha: HomeAssistant) -> None:
    await restart(ha, devices({"offline": None}), (State(alert("offline"), "on"), {}))
    assert state(ha, alert("offline")) == "on"


# --- time since a milestone ---------------------------------------------------------------

RUNNING = f"binary_sensor.pururu_{KEY}_appliance_running"
LAST_END = f"sensor.pururu_{KEY}_appliance_last_cycle_end"


async def start_cycle(ha: HomeAssistant, freezer: Any) -> None:
    await fake(ha, POWER, "120")
    await tick(ha, freezer, 65)
    assert state(ha, RUNNING) == "on"


async def end_cycle(ha: HomeAssistant, freezer: Any) -> None:
    await fake(ha, POWER, "1")
    await tick(ha, freezer, 125)
    assert state(ha, RUNNING) == "off"


async def idle(ha: HomeAssistant, freezer: Any, enabled: Any) -> None:
    assert await setup(ha, devices(enabled))
    await fake(ha, POWER, "1")
    await tick(ha, freezer, 125)


async def test_long_cycle_turns_on_after_for_and_off_when_the_cycle_ends(
        ha: HomeAssistant, freezer: Any) -> None:
    await idle(ha, freezer, {"long_cycle": {"for": {"hours": 1}}})
    await start_cycle(ha, freezer)
    await tick(ha, freezer, 3599)
    assert state(ha, alert("long_cycle")) == "off"
    await tick(ha, freezer, 1)
    assert state(ha, alert("long_cycle")) == "on"
    await end_cycle(ha, freezer)
    assert state(ha, alert("long_cycle")) == "off"


async def test_long_cycle_counts_the_time_before_a_restart(ha: HomeAssistant, freezer: Any) -> None:
    since = dt_util.utcnow() - timedelta(minutes=50)
    await restart(ha, devices({"long_cycle": {"for": {"hours": 1}}}),
                  (State(RUNNING, "on"), {"since": since.isoformat(), "since_energy": None}))
    await fake(ha, POWER, "120")
    await tick(ha, freezer, 599)
    assert state(ha, alert("long_cycle")) == "off"
    await tick(ha, freezer, 1)
    assert state(ha, alert("long_cycle")) == "on"


async def test_no_cycle_counts_from_its_creation_without_a_cycle(
        ha: HomeAssistant, freezer: Any) -> None:
    await idle(ha, freezer, {"no_cycle": {"for": {"hours": 2}}})
    await tick(ha, freezer, 2 * 3600 - 125 - 1)
    assert state(ha, alert("no_cycle")) == "off"
    await tick(ha, freezer, 1)
    assert state(ha, alert("no_cycle")) == "on"
    await start_cycle(ha, freezer)
    assert state(ha, alert("no_cycle")) == "off"


async def test_no_cycle_counts_from_the_last_cycles_end(ha: HomeAssistant, freezer: Any) -> None:
    await idle(ha, freezer, {"no_cycle": {"for": {"hours": 2}}})
    await start_cycle(ha, freezer)
    await end_cycle(ha, freezer)
    await tick(ha, freezer, 7199)
    assert state(ha, alert("no_cycle")) == "off"
    await tick(ha, freezer, 1)
    assert state(ha, alert("no_cycle")) == "on"


async def test_no_cycle_does_not_flicker_at_a_cycle_end(ha: HomeAssistant, freezer: Any) -> None:
    """Running goes off before last_cycle_end is written: the old end must not turn it on."""
    await idle(ha, freezer, {"no_cycle": {"for": {"hours": 1}}})
    await tick(ha, freezer, 3600)
    assert state(ha, alert("no_cycle")) == "on"
    await start_cycle(ha, freezer)
    changes = capture(ha, "state_changed")
    await end_cycle(ha, freezer)
    assert [e.data["new_state"].state for e in changes
            if e.data["entity_id"] == alert("no_cycle")] == []


async def test_no_cycle_counts_across_a_restart(ha: HomeAssistant, freezer: Any) -> None:
    end = (dt_util.utcnow() - timedelta(minutes=50)).isoformat()
    await restart(ha, devices({"no_cycle": {"for": {"hours": 1}}}),
                  (State(RUNNING, "off"), {"since": None, "since_energy": None}),
                  (State(LAST_END, end),
                   {"native_value": {"__type": "<class 'datetime.datetime'>", "isoformat": end},
                    "native_unit_of_measurement": None}))
    await fake(ha, POWER, "1")
    await tick(ha, freezer, 599)
    assert state(ha, alert("no_cycle")) == "off"
    await tick(ha, freezer, 1)
    assert state(ha, alert("no_cycle")) == "on"


async def test_time_alerts_watch_running_and_are_alert2_alerts(ha: HomeAssistant) -> None:
    assert await setup(ha, devices({"no_cycle": {"for": {"days": 2}}}))
    found = ha.states.get(alert("no_cycle"))
    assert found.attributes["watches"] == RUNNING
    assert found.attributes["priority"] == "medium"
    assert found.attributes["message"] == "It hasn't run in a while."
    path = Path(ha.config.path("pururu/alert2/alerts.yaml"))
    [entry] = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert entry["name"] == "demo_washer_appliance_alert_no_cycle"


async def test_no_cycle_does_not_flicker_at_a_reload(ha: HomeAssistant, freezer: Any) -> None:
    """At a reload last_cycle_end is re-added after the alerts: no reading, not "no cycle ever"."""
    config = devices({"no_cycle": {"for": {"hours": 1}}})
    await idle(ha, freezer, {"no_cycle": {"for": {"hours": 1}}})
    await tick(ha, freezer, 7200)
    await start_cycle(ha, freezer)
    await end_cycle(ha, freezer)
    await tick(ha, freezer, 600)
    assert state(ha, alert("no_cycle")) == "off"
    changes = capture(ha, "state_changed")
    await reload(ha, config)
    assert "on" not in [e.data["new_state"].state for e in changes
                        if e.data["entity_id"] == alert("no_cycle") and e.data["new_state"]]


NOTIFY_ERROR = "has notify, but Alert2 isn't set up to deliver it"


async def test_default_texts_without_alert2_are_no_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """A ready-made alert may be enabled for a reaction alone: its own texts ask for nothing."""
    assert await setup(ha, devices({"offline": None}))
    assert NOTIFY_ERROR not in caplog.text


async def test_a_notify_of_ones_own_without_alert2_is_an_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    notify = {"message": "m", "done_message": "d"}
    assert await setup(ha, devices({"offline": {"notify": notify}}))
    assert f"{alert('offline')} {NOTIFY_ERROR}" in caplog.text


# --- the docs ----------------------------------------------------------------------------

APPLIANCE_PAGE = Path(__file__).resolve().parents[1] / "docs/features/appliance.mdx"


def test_the_appliance_page_lists_every_ready_made_alert(ha: HomeAssistant) -> None:
    page = APPLIANCE_PAGE.read_text(encoding="utf-8")
    section = re.search(r"## Ready-made alerts\n(.*?)\n## ", page, re.DOTALL)
    assert section is not None, "no Ready-made alerts section"
    for name in module("core.feature").presets_of(module("features").FEATURES["appliance"]):
        assert f"`{name}`" in section[1], name
