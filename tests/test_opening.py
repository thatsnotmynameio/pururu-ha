"""Features `door` and `window`: the owner's enclosure doors (UniFi Access), replayed."""

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest

from helpers import fake, held, reload, restart, setup, tick

KEY = "clausura_frente"
NAME = "Clausura frente"
CONTACT = "binary_sensor.clausura_frente"


@pytest.fixture(params=["door", "window"])
def kind(request: pytest.FixtureRequest) -> str:
    """Both features: one code, two namespaces."""
    return str(request.param)


def devices(kind: str, **block: Any) -> dict[str, Any]:
    return {KEY: {"name": NAME, kind: {"contact": CONTACT, **block}}}


def entity(kind: str, entity_key: str, platform: str = "sensor") -> str:
    return f"{platform}.pururu_{KEY}_{kind}_{entity_key}"


def opened(hass: HomeAssistant, kind: str) -> str:
    return hass.states.get(entity(kind, "open", "binary_sensor")).state


def value(hass: HomeAssistant, kind: str, entity_key: str) -> str:
    return hass.states.get(entity(kind, entity_key)).state


def seconds_from(hass: HomeAssistant, kind: str, entity_key: str) -> float:
    """How far a timestamp sensor is from now, in seconds."""
    moment = dt_util.parse_datetime(value(hass, kind, entity_key))
    assert moment is not None
    return abs((moment - dt_util.utcnow()).total_seconds())


async def contact(hass: HomeAssistant, state: str) -> None:
    await fake(hass, CONTACT, state, {"device_class": "door"})


async def opening(hass: HomeAssistant, freezer: Any, seconds: float) -> None:
    """The contact open for `seconds`, then closed."""
    await contact(hass, "on")
    await tick(hass, freezer, seconds)
    await contact(hass, "off")


@pytest.fixture
async def door(ha: HomeAssistant, kind: str) -> HomeAssistant:
    """A closed door (or window) with no extras."""
    await contact(ha, "off")
    assert await setup(ha, devices(kind))
    return ha


# --- schema ----------------------------------------------------------------------


@pytest.mark.parametrize("block", [
    pytest.param({}, id="no contact"),
    pytest.param({"contact": "sensor.clausura_frente"}, id="not a binary sensor"),
    pytest.param({"contact": "binary_sensor.pururu_outra_door_open"}, id="a pururu binary sensor"),
    pytest.param({"contact": CONTACT, "statistics": {"openings": ["today", "today"]}},
                 id="repeated period"),
    pytest.param({"contact": CONTACT, "statistics": {"open_time": ["daily"]}}, id="unknown period"),
    pytest.param({"contact": CONTACT, "statistics": {"closings": ["today"]}},
                 id="unknown counter"),
    pytest.param({"contact": CONTACT, "sensor": CONTACT}, id="unknown key"),
])
async def test_invalid_block_is_refused(ha: HomeAssistant, kind: str,
                                        block: dict[str, Any]) -> None:
    assert not await setup(ha, {KEY: {"name": NAME, kind: block}})


@pytest.mark.parametrize(("contact_id", "message"), [
    pytest.param("sensor.clausura_frente", "sensor.clausura_frente is not a binary_sensor",
                 id="another domain"),
    pytest.param("binary_sensor.pururu_outra_door_open",
                 "binary_sensor.pururu_outra_door_open is a pururu binary_sensor: name the real one",
                 id="a pururu binary sensor"),
])
async def test_the_error_names_what_is_wrong(ha: HomeAssistant, kind: str,
                                             caplog: pytest.LogCaptureFixture,
                                             contact_id: str, message: str) -> None:
    """The messages the docs quote (troubleshooting)."""
    assert not await setup(ha, {KEY: {"name": NAME, kind: {"contact": contact_id}}})
    assert message in caplog.text


async def test_a_door_and_a_window_in_one_device(ha: HomeAssistant) -> None:
    """Their IDs differ by namespace."""
    assert await setup(ha, {KEY: {"name": NAME, "door": {"contact": CONTACT},
                                  "window": {"contact": "binary_sensor.janela"}}})
    assert ha.states.get(entity("door", "open", "binary_sensor")) is not None
    assert ha.states.get(entity("window", "open", "binary_sensor")) is not None


# --- open --------------------------------------------------------------------------


async def test_follows_the_contact(door: HomeAssistant, kind: str) -> None:
    assert opened(door, kind) == "off"
    await contact(door, "on")
    assert opened(door, kind) == "on"
    await contact(door, "off")
    assert opened(door, kind) == "off"


async def test_the_device_class_is_the_feature_s(door: HomeAssistant, kind: str) -> None:
    """A contact of class `opening` still gives a door (a window)."""
    await fake(door, CONTACT, "on", {"device_class": "opening"})
    state = door.states.get(entity(kind, "open", "binary_sensor"))
    assert state.attributes["device_class"] == kind


@pytest.mark.parametrize("gone", ["unavailable", "unknown"])
async def test_holds_while_the_contact_has_no_state(door: HomeAssistant, kind: str,
                                                    freezer: Any, gone: str) -> None:
    await contact(door, "on")
    await fake(door, CONTACT, gone)
    await tick(door, freezer, 600)
    assert opened(door, kind) == "on"
    await contact(door, "off")
    assert opened(door, kind) == "off"
    assert value(door, kind, "openings_total") == "1"


async def test_a_contact_open_at_set_up_is_an_opening(ha: HomeAssistant, kind: str,
                                                     freezer: Any) -> None:
    await contact(ha, "on")
    assert await setup(ha, devices(kind))
    assert opened(ha, kind) == "on"
    await tick(ha, freezer, 4)
    await contact(ha, "off")
    assert value(ha, kind, "openings_total") == "1"
    assert float(value(ha, kind, "last_open_duration")) == 4


async def test_the_device_holds_the_door(door: HomeAssistant, kind: str) -> None:
    assert {entity(kind, "open", "binary_sensor"), entity(kind, "last_opened"),
            entity(kind, "last_closed"), entity(kind, "last_open_duration"),
            entity(kind, "openings_total"), entity(kind, "open_time_total")} <= held(door, KEY)


async def test_without_statistics_there_are_no_meters(door: HomeAssistant, kind: str) -> None:
    for counter in ("openings", "open_time"):
        assert door.states.get(entity(kind, f"{counter}_today")) is None


async def test_names_come_from_the_translations(door: HomeAssistant, kind: str) -> None:
    state = door.states.get(entity(kind, "open", "binary_sensor"))
    assert state.attributes["friendly_name"] == f"{NAME} Open"
    total = door.states.get(entity(kind, "openings_total"))
    assert total.attributes["friendly_name"] == f"{NAME} Openings"
    assert total.attributes["unit_of_measurement"] == "openings"


async def test_names_in_portuguese(ha: HomeAssistant, kind: str) -> None:
    ha.config.language = "pt-BR"
    assert await setup(ha, devices(kind))
    state = ha.states.get(entity(kind, "open", "binary_sensor"))
    assert state.attributes["friendly_name"] == f"{NAME} Aberta"
    total = ha.states.get(entity(kind, "openings_total"))
    assert total.attributes["friendly_name"] == f"{NAME} Aberturas"
    # HA reads a unit's translation in its default language: statistics keep one unit
    assert total.attributes["unit_of_measurement"] == "openings"


# --- the last opening and the totals ------------------------------------------------


async def test_before_the_first_opening_everything_is_unknown(door: HomeAssistant,
                                                              kind: str) -> None:
    for entity_key in ("last_opened", "last_closed", "last_open_duration"):
        assert value(door, kind, entity_key) == "unknown", entity_key
    assert value(door, kind, "openings_total") == "0"


async def test_an_opening_is_recorded(door: HomeAssistant, kind: str, freezer: Any) -> None:
    """Entry by the front door, 2026-09-27 22:22:46: open for about 6 s."""
    await opening(door, freezer, 6)
    assert seconds_from(door, kind, "last_opened") == pytest.approx(6, abs=1)
    assert seconds_from(door, kind, "last_closed") < 1
    assert float(value(door, kind, "last_open_duration")) == 6
    assert door.states.get(entity(kind, "last_open_duration")).attributes[
        "unit_of_measurement"] == "s"
    assert value(door, kind, "openings_total") == "1"


async def test_open_time_adds_the_time_open(door: HomeAssistant, kind: str,
                                            freezer: Any) -> None:
    await opening(door, freezer, 6)
    await tick(door, freezer, 60)
    await opening(door, freezer, 54)
    assert float(value(door, kind, "open_time_total")) == pytest.approx(60 / 3600, abs=1e-3)
    assert value(door, kind, "openings_total") == "2"


async def test_meters_count_their_totals(ha: HomeAssistant, kind: str, freezer: Any) -> None:
    await contact(ha, "off")
    assert await setup(ha, devices(kind, statistics={"openings": ["today"],
                                                     "open_time": ["today"]}))
    await opening(ha, freezer, 6)
    await tick(ha, freezer, 60)
    await opening(ha, freezer, 54)
    await tick(ha, freezer, 60)
    assert float(value(ha, kind, "openings_today")) == 2
    assert float(value(ha, kind, "open_time_today")) == pytest.approx(
        float(value(ha, kind, "open_time_total")), abs=1e-3)
    assert ha.states.get(entity(kind, "openings_week")) is None


# --- restarts and reloads -------------------------------------------------------------


def saved_open(kind: str, seconds_ago: float) -> tuple[State, dict[str, Any]]:
    """`open` as .storage holds it, open since `seconds_ago`."""
    since = (dt_util.utcnow() - timedelta(seconds=seconds_ago)).isoformat()
    return (State(entity(kind, "open", "binary_sensor"), "on"),
            {"since": since, "since_energy": None})


async def test_restart_with_the_contact_closed_ends_the_opening(ha: HomeAssistant,
                                                                kind: str) -> None:
    """Saved open 30 s ago; the contact is closed once HA has started."""
    ha.states.async_set(CONTACT, "off")
    await restart(ha, devices(kind), saved_open(kind, 30))
    assert opened(ha, kind) == "off"
    assert value(ha, kind, "openings_total") == "1"
    assert float(value(ha, kind, "last_open_duration")) == 30


async def test_restart_with_the_contact_open_keeps_the_opening(ha: HomeAssistant, kind: str,
                                                               freezer: Any) -> None:
    ha.states.async_set(CONTACT, "on")
    await restart(ha, devices(kind), saved_open(kind, 30))
    assert opened(ha, kind) == "on"
    await tick(ha, freezer, 10)
    await contact(ha, "off")
    assert value(ha, kind, "openings_total") == "1"
    assert float(value(ha, kind, "last_open_duration")) == 40


async def test_restart_before_the_contact_has_a_state_holds(ha: HomeAssistant, kind: str,
                                                            freezer: Any) -> None:
    await restart(ha, devices(kind), saved_open(kind, 30))
    assert opened(ha, kind) == "on"
    await tick(ha, freezer, 5)
    await contact(ha, "off")
    assert float(value(ha, kind, "last_open_duration")) == 35


async def test_reload_mid_opening_counts_one(door: HomeAssistant, kind: str,
                                             freezer: Any) -> None:
    await contact(door, "on")
    await tick(door, freezer, 10)
    await reload(door, devices(kind))
    await tick(door, freezer, 10)
    assert opened(door, kind) == "on"
    await contact(door, "off")
    assert value(door, kind, "openings_total") == "1"
    assert float(value(door, kind, "last_open_duration")) == 20


async def test_the_last_opening_restores(ha: HomeAssistant, kind: str) -> None:
    await restart(ha, devices(kind),
                  (State(entity(kind, "last_open_duration"), "7"),
                   {"native_value": 7, "native_unit_of_measurement": "s"}),
                  (State(entity(kind, "openings_total"), "12"),
                   {"native_value": 12, "native_unit_of_measurement": None}))
    assert float(value(ha, kind, "last_open_duration")) == 7
    assert value(ha, kind, "openings_total") == "12"


# --- a pururu contact, and what builds on the door -----------------------------------

WASHER = {"name": "Lavadora", "appliance": {
    "power": "sensor.lavadora_power",
    "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}}


async def test_a_renamed_pururu_contact_stands_for_nothing(
        ha: HomeAssistant, kind: str, caplog: pytest.LogCaptureFixture) -> None:
    """Renamed in the UI, a pururu binary sensor gets past the schema: the registry knows it."""
    config = {"lavadora": WASHER,
              KEY: {"name": NAME, kind: {"contact": "binary_sensor.lavadora_rodando"}}}
    assert await setup(ha, config)
    er.async_get(ha).async_update_entity("binary_sensor.pururu_lavadora_appliance_running",
                                         new_entity_id="binary_sensor.lavadora_rodando")
    await ha.async_block_till_done()
    caplog.clear()
    await reload(ha, config)
    assert opened(ha, kind) == "unavailable"
    assert value(ha, kind, "openings_total") == "0"
    assert ("binary_sensor.lavadora_rodando is a pururu binary sensor: name the real contact; "
            f"{entity(kind, 'open', 'binary_sensor')} stands for nothing") in caplog.text


async def test_the_openings_are_a_cycle_for_phases(ha: HomeAssistant, kind: str) -> None:
    """`cycle_from: door` (window): a phase runs while it's open."""
    await contact(ha, "off")
    phases = {"cycle_from": kind, "sensor": "sensor.vento",
              "defaults": {"stopped": "parada", "running": "aberta"},
              "bands": {"ventania": {"above": 50}}}
    assert await setup(ha, {KEY: {"name": NAME, kind: {"contact": CONTACT}, "phases": phases}})
    await fake(ha, "sensor.vento", "10")
    phase = f"sensor.pururu_{KEY}_phase_current"
    assert ha.states.get(phase).state == "parada"
    await contact(ha, "on")
    assert ha.states.get(phase).state == "aberta"
    await contact(ha, "off")
    assert ha.states.get(phase).state == "parada"
