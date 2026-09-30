"""Feature `phases`: a made-up washer's phases from its plug's power."""

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest

from helpers import fake, reload, restart, setup, snapshot, tick

KEY = "demo_washer"
POWER = "sensor.demo_plug_power"
RUNNING = "binary_sensor.pururu_demo_washer_appliance_running"
PHASE = "sensor.pururu_demo_washer_phase_current"
IDLE_W = 1.4
APPLIANCE = {"power": POWER,
             "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}}}
PHASES: dict[str, Any] = {
    "cycle_from": "appliance",
    "sensor": POWER,
    "defaults": {"stopped": "idle", "running": "washing"},
    "bands": {"heating": {"above": 1000},
              "spinning": {"above": 50, "below": 1000, "for": {"minutes": 3}}},
}
DEVICES = {KEY: {"name": "Demo washer", "appliance": APPLIANCE, "phases": PHASES}}


def phase(hass: HomeAssistant) -> tuple[str, list[str]]:
    state = hass.states.get(PHASE)
    return state.state, state.attributes["seen"]


def running(hass: HomeAssistant) -> str:
    return hass.states.get(RUNNING).state


async def watts(hass: HomeAssistant, value: float | str) -> None:
    await fake(hass, POWER, str(value))


@pytest.fixture
async def washer(ha: HomeAssistant, freezer: Any) -> HomeAssistant:
    assert await setup(ha, DEVICES)
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 125)
    assert running(ha) == "off"
    return ha


async def start_cycle(hass: HomeAssistant, freezer: Any) -> None:
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
    pytest.param({**PHASES, "bands": {"spinning": {"above": 1000, "below": 50}}}, id="above over below"),
    pytest.param({**PHASES, "bands": {"spinning": {"above": 50, "below": 50}}}, id="above equals below"),
    pytest.param({**PHASES, "bands": {"spinning": {"for": {"minutes": 3}}}}, id="no bound"),
    pytest.param({**PHASES, "bands": {}}, id="no band"),
    pytest.param({**PHASES, "bands": {"heating": {"above": "nan"}}}, id="bound not a number"),
    pytest.param({**PHASES, "bands": {"heating": {"below": "inf"}}}, id="bound infinite"),
    pytest.param({**PHASES, "bands": {"idle": {"above": 1000}}}, id="band named like a default"),
    pytest.param({**PHASES, "defaults": {"stopped": "idle", "running": "idle"}}, id="defaults alike"),
    pytest.param({key: value for key, value in PHASES.items() if key != "cycle_from"}, id="no cycle_from"),
])
async def test_invalid_block_is_refused(ha: HomeAssistant, block: dict[str, Any]) -> None:
    assert not await setup(ha, {KEY: {"name": "Demo washer", "appliance": APPLIANCE,
                                      "phases": block}})


async def test_the_cycle_must_come_from_this_device(ha: HomeAssistant) -> None:
    assert not await setup(ha, {KEY: {"name": "Demo washer", "phases": PHASES}})


# --- phases --------------------------------------------------------------------


async def test_stopped_until_a_cycle_starts(washer: HomeAssistant) -> None:
    assert phase(washer) == ("idle", [])
    assert washer.states.get(PHASE).attributes["options"] == ["idle", "washing", "heating",
                                                               "spinning"]


async def test_a_cycle_starts_in_the_running_default(washer: HomeAssistant, freezer: Any) -> None:
    await start_cycle(washer, freezer)
    assert phase(washer) == ("washing", [])


async def test_a_band_without_for_holds_at_once(washer: HomeAssistant, freezer: Any) -> None:
    await start_cycle(washer, freezer)
    await watts(washer, 1900)
    assert phase(washer) == ("heating", ["heating"])
    await tick(washer, freezer, 600)
    await watts(washer, 121)
    assert phase(washer) == ("washing", ["heating"])


async def test_a_band_with_for_holds_after_it(washer: HomeAssistant, freezer: Any) -> None:
    await start_cycle(washer, freezer)
    await watts(washer, 150)
    await tick(washer, freezer, 170)
    assert phase(washer) == ("washing", [])
    await tick(washer, freezer, 15)
    assert phase(washer) == ("spinning", ["spinning"])
    await watts(washer, 22)
    assert phase(washer) == ("washing", ["spinning"])


async def test_leaving_before_for_is_not_the_band(washer: HomeAssistant, freezer: Any) -> None:
    await start_cycle(washer, freezer)
    await watts(washer, 150)
    await tick(washer, freezer, 88)
    await watts(washer, 7)
    await tick(washer, freezer, 300)
    assert phase(washer) == ("washing", [])


async def test_the_first_band_in_order_wins(ha: HomeAssistant, freezer: Any) -> None:
    """Overlapping bands: the one listed first holds."""
    bands = {"strong": {"above": 500}, "any": {"above": 50}}
    assert await setup(ha, {KEY: {"name": "Demo washer", "appliance": APPLIANCE,
                                  "phases": {**PHASES, "bands": bands}}})
    await watts(ha, 120)
    await tick(ha, freezer, 65)
    assert phase(ha) == ("any", ["any"])
    await watts(ha, 900)
    assert phase(ha) == ("strong", ["strong", "any"])


async def test_end_is_stopped_and_keeps_seen(washer: HomeAssistant, freezer: Any) -> None:
    await start_cycle(washer, freezer)
    await watts(washer, 1900)
    await tick(washer, freezer, 60)
    await watts(washer, 121)
    await end_cycle(washer, freezer)
    assert phase(washer) == ("idle", ["heating"])


async def test_a_new_cycle_clears_seen(washer: HomeAssistant, freezer: Any) -> None:
    await start_cycle(washer, freezer)
    await watts(washer, 1900)
    await end_cycle(washer, freezer)
    await start_cycle(washer, freezer)
    assert phase(washer) == ("washing", [])


async def test_readings_while_stopped_change_nothing(washer: HomeAssistant, freezer: Any) -> None:
    await watts(washer, 1900)
    await tick(washer, freezer, 20)
    await watts(washer, 150)
    await tick(washer, freezer, 30)
    await watts(washer, IDLE_W)
    await tick(washer, freezer, 300)
    assert phase(washer) == ("idle", [])


async def test_a_band_before_the_cycle_counts_when_it_starts(washer: HomeAssistant,
                                                              freezer: Any) -> None:
    """The heater starts before the cycle counts as running: the cycle starts heating."""
    await watts(washer, 30)
    await tick(washer, freezer, 20)
    await watts(washer, 1900)
    await tick(washer, freezer, 45)
    assert running(washer) == "on"
    assert phase(washer) == ("heating", ["heating"])


async def test_holds_while_the_sensor_has_no_value(washer: HomeAssistant, freezer: Any) -> None:
    await start_cycle(washer, freezer)
    await watts(washer, 1900)
    await watts(washer, "unavailable")
    await tick(washer, freezer, 300)
    assert phase(washer) == ("heating", ["heating"])
    await watts(washer, 121)
    assert phase(washer) == ("washing", ["heating"])


async def test_a_band_pending_its_for_starts_over_after_no_value(washer: HomeAssistant,
                                                                   freezer: Any) -> None:
    """A reading without a value stops a band's `for`: it counts again from the next reading in it."""
    await start_cycle(washer, freezer)
    await watts(washer, 150)
    await tick(washer, freezer, 100)
    await watts(washer, "unavailable")
    await tick(washer, freezer, 120)
    assert phase(washer) == ("washing", [])
    await watts(washer, 150)
    await tick(washer, freezer, 170)
    assert phase(washer) == ("washing", [])
    await tick(washer, freezer, 15)
    assert phase(washer) == ("spinning", ["spinning"])


async def test_restart_holds_the_phase_until_the_first_reading(ha: HomeAssistant,
                                                                freezer: Any) -> None:
    since = (dt_util.utcnow() - timedelta(minutes=20)).isoformat()
    await restart(
        ha, DEVICES,
        (State(RUNNING, "on"), snapshot(since)),
        (State(PHASE, "heating", {"seen": ["heating"]}), {}),
    )
    assert phase(ha) == ("heating", ["heating"])
    await watts(ha, 121)
    assert phase(ha) == ("washing", ["heating"])
    await end_cycle(ha, freezer)
    assert phase(ha) == ("idle", ["heating"])


async def test_reload_while_a_band_is_pending(washer: HomeAssistant, freezer: Any,
                                              caplog: pytest.LogCaptureFixture) -> None:
    """A `for` timer pending at the reload dies with its entity: no error, no phase from it."""
    await start_cycle(washer, freezer)
    await watts(washer, 150)
    await tick(washer, freezer, 60)
    await reload(washer, DEVICES)
    # The old timer would have fired 120 s after the reload; the new entity times from its
    # own first reading, at the reload
    await tick(washer, freezer, 150)
    assert [r.getMessage() for r in caplog.records if r.levelname == "ERROR"] == []
    assert running(washer) == "on"
    assert phase(washer)[0] == "washing"
    await tick(washer, freezer, 40)
    assert phase(washer)[0] == "spinning"


async def test_follows_a_renamed_cycle(washer: HomeAssistant, freezer: Any) -> None:
    """Running renamed in the UI: the entry reloads and the phase follows the new ID."""
    er.async_get(washer).async_update_entity(RUNNING, new_entity_id="binary_sensor.washer_running")
    await washer.async_block_till_done()
    await watts(washer, 120)
    await tick(washer, freezer, 65)
    assert washer.states.get("binary_sensor.washer_running").state == "on"
    await watts(washer, 1900)
    assert phase(washer) == ("heating", ["heating"])


async def test_no_phase_when_its_cycle_is_not_created(ha: HomeAssistant,
                                                      caplog: pytest.LogCaptureFixture) -> None:
    """Running's ID belongs to another integration: nothing that follows running is created."""
    er.async_get(ha).async_get_or_create(
        "binary_sensor", "template", "someone_else", suggested_object_id="pururu_demo_washer_appliance_running")
    assert await setup(ha, DEVICES)
    assert ha.states.get(PHASE) is None
    assert ha.states.get("sensor.pururu_demo_washer_appliance_runtime_total") is None
    assert ha.states.get("sensor.pururu_demo_washer_appliance_power") is not None
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(PHASE in message and RUNNING in message for message in errors), errors
    assert any("runtime_total" in message and RUNNING in message for message in errors), errors


async def test_names_its_states_in_portuguese(ha: HomeAssistant) -> None:
    """The vocabulary exists in both languages (the frontend translates the state)."""
    ha.config.language = "pt-BR"
    assert await setup(ha, DEVICES)
    assert ha.states.get(PHASE).attributes["friendly_name"] == "Demo washer Fase"
