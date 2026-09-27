"""Feature `modes`: a made-up water purifier's kinds of cycle from its plug's power."""

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest

from helpers import fake, reload, restart, setup, tick

KEY = "demo_filter"
POWER = "sensor.demo_plug_power"
ENERGY = "sensor.demo_plug_energy"
RUNNING = "binary_sensor.pururu_demo_filter_appliance_running"
CURRENT = "sensor.pururu_demo_filter_mode_current"
LAST = "sensor.pururu_demo_filter_mode_last"
IDLE_W = 1.0
APPLIANCE = {"power": POWER,
             "running": {"threshold": 4, "on_delay": {"seconds": 20}, "off_delay": {"minutes": 2}}}
MODES: dict[str, Any] = {
    "cycle_from": "appliance",
    "sensor": POWER,
    "energy": ENERGY,
    "modes": {
        # Open names: none of them is translated
        "bebendo": {"name": "Bebendo", "above": 4, "below": 40,
                    "on_delay": {"seconds": 5}, "off_delay": {"minutes": 5}},
        "gelar": {"name": "Gelar", "above": 40, "below": 300,
                  "on_delay": {"seconds": 30}, "off_delay": {"seconds": 30}},
        "quente": {"name": "Água quente", "above": 300,
                   "on_delay": {"seconds": 10}, "off_delay": {"seconds": 30}},
    },
}
DEVICES = {KEY: {"name": "Demo filter", "appliance": APPLIANCE, "modes": MODES}}


def mode(hass: HomeAssistant) -> str:
    return hass.states.get(CURRENT).state


def last(hass: HomeAssistant) -> str:
    return hass.states.get(LAST).state


def running(hass: HomeAssistant) -> str:
    return hass.states.get(RUNNING).state


async def watts(hass: HomeAssistant, value: float | str) -> None:
    await fake(hass, POWER, str(value))


@pytest.fixture
async def purifier(ha: HomeAssistant, freezer: Any) -> HomeAssistant:
    """The demo purifier, idle long enough to count as not running."""
    assert await setup(ha, DEVICES)
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 125)
    assert running(ha) == "off"
    return ha


async def cool(hass: HomeAssistant, freezer: Any) -> None:
    """The compressor on: the appliance runs at 20 s, gelar starts at 30 s."""
    await watts(hass, 120)
    await tick(hass, freezer, 35)
    assert running(hass) == "on"
    assert mode(hass) == "gelar"


def with_modes(**changes: Any) -> dict[str, Any]:
    return {KEY: {"name": "Demo filter", "appliance": APPLIANCE, "modes": {**MODES, **changes}}}


# --- schema ------------------------------------------------------------------


GELAR = MODES["modes"]["gelar"]


@pytest.mark.parametrize("block", [
    pytest.param({**MODES, "modes": {"idle": GELAR}}, id="a mode named idle"),
    pytest.param({**MODES, "modes": {"gelar": GELAR, "quente": {**GELAR, "above": 250}}},
                 id="overlapping bands"),
    pytest.param({**MODES, "modes": {"a": {**GELAR, "above": 40, "below": 300},
                                     "b": {**GELAR, "above": 0, "below": 1000}}},
                 id="a band inside another"),
    pytest.param({**MODES, "modes": {"gelar": {**GELAR, "above": 300, "below": 40}}},
                 id="above over below"),
    pytest.param({**MODES, "modes": {"gelar": {**GELAR, "above": 40, "below": 40}}},
                 id="above equals below"),
    pytest.param({**MODES, "modes": {"gelar": {"name": "Gelar", "on_delay": 1, "off_delay": 1}}},
                 id="no bound"),
    pytest.param({**MODES, "modes": {"gelar": {k: v for k, v in GELAR.items() if k != "name"}}},
                 id="no name"),
    pytest.param({**MODES, "modes": {"gelar": {**GELAR, "name": "  "}}}, id="blank name"),
    pytest.param({**MODES, "modes": {"gelar": {k: v for k, v in GELAR.items() if k != "on_delay"}}},
                 id="no on_delay"),
    pytest.param({**MODES, "modes": {"gelar": {**GELAR, "above": "nan"}}}, id="bound not a number"),
    pytest.param({**MODES, "modes": {"Gelar": GELAR}}, id="not a slug"),
    pytest.param({**MODES, "modes": {"gelar": {**GELAR, "for": 3}}}, id="unknown key in a mode"),
    pytest.param({**MODES, "modes": {}}, id="no mode"),
    pytest.param({k: v for k, v in MODES.items() if k != "cycle_from"}, id="no cycle_from"),
    pytest.param({k: v for k, v in MODES.items() if k != "energy"} | {"statistics": {"energy": ["today"]}},
                 id="energy statistics without energy"),
    pytest.param({**MODES, "statistics": {"cycles": ["today", "today"]}}, id="repeated period"),
])
async def test_invalid_block_is_refused(ha: HomeAssistant, block: dict[str, Any]) -> None:
    assert not await setup(ha, {KEY: {"name": "Demo filter", "appliance": APPLIANCE,
                                      "modes": block}})


async def test_bands_that_only_touch_are_accepted(ha: HomeAssistant) -> None:
    """Strict bounds: `below: 40` and `above: 40` share no reading."""
    above_only = {k: v for k, v in GELAR.items() if k != "below"}
    assert await setup(ha, with_modes(modes={"a": {**GELAR, "above": 4, "below": 40},
                                             "b": {**above_only, "above": 40}}))


async def test_the_cycle_must_come_from_this_device(ha: HomeAssistant) -> None:
    assert not await setup(ha, {KEY: {"name": "Demo filter", "modes": MODES}})


# --- the running mode ----------------------------------------------------------


async def test_idle_until_a_mode_starts(purifier: HomeAssistant) -> None:
    assert mode(purifier) == "idle"
    assert last(purifier) == "unknown"
    assert purifier.states.get(CURRENT).attributes["options"] == ["idle", "bebendo", "gelar",
                                                                   "quente"]
    assert purifier.states.get(LAST).attributes["options"] == ["bebendo", "gelar", "quente"]


async def test_a_mode_starts_after_its_on_delay(purifier: HomeAssistant, freezer: Any) -> None:
    await watts(purifier, 120)
    await tick(purifier, freezer, 25)
    assert running(purifier) == "on"
    assert mode(purifier) == "idle"
    await tick(purifier, freezer, 10)
    assert mode(purifier) == "gelar"


async def test_a_mode_ends_after_its_off_delay(purifier: HomeAssistant, freezer: Any) -> None:
    await cool(purifier, freezer)
    await watts(purifier, IDLE_W)
    await tick(purifier, freezer, 25)
    assert mode(purifier) == "gelar"
    await tick(purifier, freezer, 10)
    assert mode(purifier) == "idle"
    assert last(purifier) == "gelar"


async def test_a_reading_back_in_the_band_cancels_the_end(purifier: HomeAssistant,
                                                           freezer: Any) -> None:
    await cool(purifier, freezer)
    await watts(purifier, IDLE_W)
    await tick(purifier, freezer, 20)
    await watts(purifier, 120)
    await tick(purifier, freezer, 60)
    assert mode(purifier) == "gelar"
    assert last(purifier) == "unknown"


async def test_another_mode_waits_for_the_running_one(purifier: HomeAssistant,
                                                      freezer: Any) -> None:
    """From 120 W to 1000 W: quente is armed at 10 s, and starts when gelar ends at 30 s."""
    await cool(purifier, freezer)
    await watts(purifier, 1000)
    await tick(purifier, freezer, 12)
    assert mode(purifier) == "gelar"
    assert last(purifier) == "unknown"
    await tick(purifier, freezer, 20)
    assert mode(purifier) == "quente"
    assert last(purifier) == "gelar"


async def test_a_dip_into_another_band_does_not_split_the_cycle(purifier: HomeAssistant,
                                                                freezer: Any) -> None:
    """A chilling tail dips into bebendo's band for 10 s (bebendo armed at 5 s), then rises."""
    await cool(purifier, freezer)
    await watts(purifier, 20)
    await tick(purifier, freezer, 10)
    await watts(purifier, 120)
    await tick(purifier, freezer, 600)
    assert mode(purifier) == "gelar"
    assert last(purifier) == "unknown"


async def test_a_short_visit_to_another_band_is_nothing(purifier: HomeAssistant,
                                                        freezer: Any) -> None:
    await cool(purifier, freezer)
    await watts(purifier, 1000)
    await tick(purifier, freezer, 5)
    await watts(purifier, 120)
    await tick(purifier, freezer, 60)
    assert mode(purifier) == "gelar"
    assert last(purifier) == "unknown"


async def test_a_mode_armed_before_the_cycle_starts_with_it(purifier: HomeAssistant,
                                                             freezer: Any) -> None:
    """quente's 10 s pass before the appliance's 20 s: quente starts when the appliance runs."""
    await watts(purifier, 1000)
    await tick(purifier, freezer, 15)
    assert running(purifier) == "off"
    assert mode(purifier) == "idle"
    await tick(purifier, freezer, 10)
    assert running(purifier) == "on"
    assert mode(purifier) == "quente"


async def test_the_cycle_ending_ends_the_mode(purifier: HomeAssistant, freezer: Any) -> None:
    """bebendo's off_delay (5 min) outlasts the appliance's (2 min): the appliance ends it."""
    await watts(purifier, 20)
    await tick(purifier, freezer, 25)
    assert mode(purifier) == "bebendo"
    await watts(purifier, IDLE_W)
    await tick(purifier, freezer, 125)
    assert running(purifier) == "off"
    assert mode(purifier) == "idle"
    assert last(purifier) == "bebendo"


async def test_no_mode_starts_while_the_cycle_is_unknown(purifier: HomeAssistant,
                                                         freezer: Any) -> None:
    await cool(purifier, freezer)
    await fake(purifier, RUNNING, "unavailable")
    await watts(purifier, 1000)
    await tick(purifier, freezer, 15)
    assert mode(purifier) == "gelar"  # quente is armed; gelar's off_delay still runs
    await tick(purifier, freezer, 20)
    assert mode(purifier) == "idle"
    await fake(purifier, RUNNING, "on")
    assert mode(purifier) == "quente"


async def test_a_reading_without_a_value_cancels_pending_and_keeps_the_mode(
        purifier: HomeAssistant, freezer: Any) -> None:
    await cool(purifier, freezer)
    await watts(purifier, 1000)
    await tick(purifier, freezer, 5)
    await watts(purifier, "unavailable")
    await tick(purifier, freezer, 600)
    assert mode(purifier) == "gelar"
    await watts(purifier, 1000)
    await tick(purifier, freezer, 25)
    assert mode(purifier) == "gelar"  # gelar's off_delay counts from this reading
    await tick(purifier, freezer, 6)
    assert mode(purifier) == "quente"


async def test_restart_keeps_the_running_mode(ha: HomeAssistant, freezer: Any) -> None:
    since = (dt_util.utcnow() - timedelta(minutes=20)).isoformat()
    await restart(
        ha, DEVICES,
        (State(RUNNING, "on"), {"since": since, "since_energy": None}),
        (State(CURRENT, "gelar"), {"since": since, "since_energy": None}),
    )
    assert mode(ha) == "gelar"
    await watts(ha, 120)
    await tick(ha, freezer, 60)
    assert mode(ha) == "gelar"
    await watts(ha, IDLE_W)
    await tick(ha, freezer, 35)
    assert mode(ha) == "idle"
    assert last(ha) == "gelar"


async def test_last_restores(ha: HomeAssistant) -> None:
    await restart(ha, DEVICES, (State(LAST, "quente"), {"native_value": "quente",
                                                        "native_unit_of_measurement": None}))
    assert last(ha) == "quente"


async def test_reload_keeps_the_running_mode(purifier: HomeAssistant, freezer: Any) -> None:
    await cool(purifier, freezer)
    await reload(purifier, DEVICES)
    await tick(purifier, freezer, 60)
    assert mode(purifier) == "gelar"
    await watts(purifier, IDLE_W)
    await tick(purifier, freezer, 35)
    assert mode(purifier) == "idle"
    assert last(purifier) == "gelar"


async def test_follows_a_renamed_cycle(purifier: HomeAssistant, freezer: Any) -> None:
    er.async_get(purifier).async_update_entity(RUNNING, new_entity_id="binary_sensor.filter_running")
    await purifier.async_block_till_done()
    await watts(purifier, 1000)
    await tick(purifier, freezer, 25)
    assert purifier.states.get("binary_sensor.filter_running").state == "on"
    assert mode(purifier) == "quente"


async def test_no_modes_when_its_cycle_is_not_created(ha: HomeAssistant,
                                                      caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(
        "binary_sensor", "template", "someone_else",
        suggested_object_id="pururu_demo_filter_appliance_running")
    assert await setup(ha, DEVICES)
    assert ha.states.get(CURRENT) is None
    assert ha.states.get(LAST) is None
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(CURRENT in message and RUNNING in message for message in errors), errors


async def test_an_alert_can_watch_the_mode(ha: HomeAssistant, freezer: Any) -> None:
    alert = "binary_sensor.pururu_demo_filter_alert_hot"
    assert await setup(ha, {KEY: {**DEVICES[KEY], "alerts": {
        "hot": {"name": "Esquentando", "when": "mode_current", "is": "quente"}}}})
    await watts(ha, 1000)
    await tick(ha, freezer, 25)
    assert ha.states.get(alert).state == "on"


async def test_names(ha: HomeAssistant) -> None:
    assert await setup(ha, DEVICES)
    assert ha.states.get(CURRENT).attributes["friendly_name"] == "Demo filter Mode"
    assert ha.states.get(LAST).attributes["friendly_name"] == "Demo filter Last mode"


async def test_names_in_portuguese(ha: HomeAssistant) -> None:
    ha.config.language = "pt-BR"
    assert await setup(ha, DEVICES)
    assert ha.states.get(CURRENT).attributes["friendly_name"] == "Demo filter Modo"
    assert ha.states.get(LAST).attributes["friendly_name"] == "Demo filter Último modo"
