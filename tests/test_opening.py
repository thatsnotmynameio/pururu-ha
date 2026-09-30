"""Features `door` and `window`: the owner's enclosure doors (UniFi Access), replayed."""

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest

from helpers import fake, held, reload, restart, setup, tick

KEY = "cercado_frente"
NAME = "Cercado frente"
CONTACT = "binary_sensor.cercado_frente"


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
    pytest.param({"contact": "sensor.cercado_frente"}, id="not a binary sensor"),
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
    pytest.param("sensor.cercado_frente", "sensor.cercado_frente is not a binary_sensor",
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


async def test_restart_with_an_impossible_start_keeps_the_opening(ha: HomeAssistant,
                                                                  kind: str) -> None:
    """A hand-edited .storage: a well-formed but impossible date is no start, and the opening goes on."""
    ha.states.async_set(CONTACT, "on")
    await restart(ha, devices(kind), (State(entity(kind, "open", "binary_sensor"), "on"),
                                      {"since": "2026-02-30T10:00:00+00:00",
                                       "since_energy": None}))
    assert opened(ha, kind) == "on"
    await contact(ha, "off")
    assert opened(ha, kind) == "off"
    assert value(ha, kind, "openings_total") == "1"
    assert value(ha, kind, "last_open_duration") == "unknown"


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
    "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
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


# --- events -------------------------------------------------------------------------

ACCESS = "event.cercado_frente_access"
DOORBELL = "event.cercado_frente_doorbell"
ACCESS_TYPES = {"access_granted": "opening", "access_denied": "denied"}
ACCESS_FIELDS = {"who": "actor", "how": "authentication", "direction": "direction"}
EVENTS = [
    {"entity": ACCESS, "types": ACCESS_TYPES, "fields": ACCESS_FIELDS},
    {"entity": DOORBELL, "types": {"ring": "ring"}},
]
# What UniFi Access sent on 2026-09-27
ENTRY = {"actor": "Alex Doe", "authentication": "PIN_CODE", "direction": "entry",
         "result": "ACCESS"}
EXIT = {"actor": "N/A", "authentication": "REX", "direction": "exit", "result": "ACCESS"}
FIELD_KEYS = ("last_opened_by", "last_opened_via", "last_direction")


async def access(hass: HomeAssistant, event_type: str = "access_granted", *,
                 at: str | None = None, **attributes: Any) -> None:
    """An access event: its state is the event's time, now unless `at`."""
    time = at or dt_util.utcnow().isoformat(timespec="milliseconds")
    await fake(hass, ACCESS, time, {"event_types": ["access_granted", "access_denied"],
                                    "event_type": event_type, **attributes})


async def ring(hass: HomeAssistant) -> None:
    await fake(hass, DOORBELL, dt_util.utcnow().isoformat(timespec="milliseconds"),
               {"event_types": ["ring"], "event_type": "ring", "device_class": "doorbell"})


def fields(hass: HomeAssistant, kind: str) -> tuple[str, str, str]:
    return tuple(value(hass, kind, entity_key) for entity_key in FIELD_KEYS)  # type: ignore[return-value]


@pytest.fixture
async def enclosure(ha: HomeAssistant, kind: str) -> HomeAssistant:
    """The front enclosure door with its access and doorbell events; the last access is old."""
    await contact(ha, "off")
    await access(ha, at="2026-09-15T10:00:00.000+00:00", **ENTRY)
    assert await setup(ha, devices(kind, events=EVENTS))
    return ha


@pytest.mark.parametrize("block", [
    pytest.param({"events": []}, id="no event"),
    pytest.param({"events": [{"entity": "sensor.x", "types": ACCESS_TYPES}]}, id="not an event"),
    pytest.param({"events": [{"entity": ACCESS, "types": {}}]}, id="no type"),
    pytest.param({"events": [{"entity": ACCESS, "types": {"access_granted": "opened"}}]},
                 id="unknown meaning"),
    pytest.param({"events": [{"entity": ACCESS, "types": ACCESS_TYPES,
                              "fields": {"user": "actor"}}]}, id="unknown field"),
    pytest.param({"events": [{"entity": ACCESS, "types": ACCESS_TYPES,
                              "fields": {"who": " "}}]}, id="blank attribute"),
    pytest.param({"events": [{"entity": ACCESS, "types": ACCESS_TYPES, "extra": 1}]},
                 id="unknown key"),
    pytest.param({"events": [{"types": ACCESS_TYPES}]}, id="no entity"),
    pytest.param({"match": "soon"}, id="match not a period"),
])
async def test_invalid_events_are_refused(ha: HomeAssistant, kind: str,
                                          block: dict[str, Any]) -> None:
    assert not await setup(ha, devices(kind, **block))


async def test_entry_by_pin_describes_the_opening(enclosure: HomeAssistant, kind: str,
                                                  freezer: Any) -> None:
    """2026-09-27 22:22:46: the contact opens, the access event comes 0.9 s later."""
    await contact(enclosure, "on")
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")
    await tick(enclosure, freezer, 0.9)
    await access(enclosure, **ENTRY)
    assert fields(enclosure, kind) == ("Alex Doe", "PIN_CODE", "entry")
    await tick(enclosure, freezer, 6)
    await contact(enclosure, "off")
    assert fields(enclosure, kind) == ("Alex Doe", "PIN_CODE", "entry")


async def test_an_event_before_the_contact_describes_it(enclosure: HomeAssistant, kind: str,
                                                        freezer: Any) -> None:
    await access(enclosure, **EXIT)
    await tick(enclosure, freezer, 1)
    await contact(enclosure, "on")
    assert fields(enclosure, kind) == ("N/A", "REX", "exit")


@pytest.mark.parametrize("event_first", [True, False])
async def test_an_event_outside_match_is_dropped(enclosure: HomeAssistant, kind: str,
                                                 freezer: Any, event_first: bool) -> None:
    if event_first:
        await access(enclosure, **EXIT)
        await tick(enclosure, freezer, 6)
        await contact(enclosure, "on")
    else:
        await contact(enclosure, "on")
        await tick(enclosure, freezer, 6)
        await access(enclosure, **EXIT)
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")


async def test_match_can_be_set(ha: HomeAssistant, kind: str, freezer: Any) -> None:
    await contact(ha, "off")
    assert await setup(ha, devices(kind, events=EVENTS, match={"seconds": 10}))
    await contact(ha, "on")
    await tick(ha, freezer, 8)
    await access(ha, **ENTRY)
    assert fields(ha, kind) == ("Alex Doe", "PIN_CODE", "entry")


async def test_the_first_event_wins(enclosure: HomeAssistant, kind: str, freezer: Any) -> None:
    await contact(enclosure, "on")
    await access(enclosure, **ENTRY)
    await tick(enclosure, freezer, 1)
    await access(enclosure, **EXIT)
    assert fields(enclosure, kind) == ("Alex Doe", "PIN_CODE", "entry")


async def test_a_short_opening_closed_before_its_event(enclosure: HomeAssistant, kind: str,
                                                       freezer: Any) -> None:
    await opening(enclosure, freezer, 0.5)
    await tick(enclosure, freezer, 0.5)
    await access(enclosure, **ENTRY)
    assert fields(enclosure, kind) == ("Alex Doe", "PIN_CODE", "entry")


async def test_an_opening_without_event_forgets_the_last(enclosure: HomeAssistant, kind: str,
                                                         freezer: Any) -> None:
    """Leaving by the front door, from inside: no event, so not the last entry's PIN again."""
    await contact(enclosure, "on")
    await access(enclosure, **ENTRY)
    await tick(enclosure, freezer, 6)
    await contact(enclosure, "off")
    await tick(enclosure, freezer, 600)
    await contact(enclosure, "on")
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")


async def test_a_quick_reopening_without_event_is_unknown(enclosure: HomeAssistant, kind: str,
                                                          freezer: Any) -> None:
    await contact(enclosure, "on")
    await access(enclosure, **ENTRY)
    await tick(enclosure, freezer, 2)
    await contact(enclosure, "off")
    await tick(enclosure, freezer, 1)
    await contact(enclosure, "on")
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")


async def test_an_event_type_not_in_types_is_ignored(enclosure: HomeAssistant, kind: str) -> None:
    await contact(enclosure, "on")
    await access(enclosure, "access_unknown", **ENTRY)
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")
    assert value(enclosure, kind, "last_denied") == "unknown"


async def test_a_missing_attribute_is_unknown(enclosure: HomeAssistant, kind: str) -> None:
    await contact(enclosure, "on")
    await access(enclosure, actor="Alex Doe")
    assert fields(enclosure, kind) == ("Alex Doe", "unknown", "unknown")


async def test_a_field_that_is_not_text_is_text(enclosure: HomeAssistant, kind: str) -> None:
    await contact(enclosure, "on")
    await access(enclosure, **{**ENTRY, "actor": 42})
    assert value(enclosure, kind, "last_opened_by") == "42"


async def test_a_state_that_is_not_a_time_is_ignored(enclosure: HomeAssistant, kind: str) -> None:
    await contact(enclosure, "on")
    await access(enclosure, at="garbage", **ENTRY)
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")


async def test_the_same_state_again_is_no_new_event(enclosure: HomeAssistant, kind: str,
                                                    freezer: Any) -> None:
    """Attributes changing under the same state (the same time) are no new event."""
    at = dt_util.utcnow().isoformat(timespec="milliseconds")
    await access(enclosure, at=at, **ENTRY)
    await tick(enclosure, freezer, 600)
    await contact(enclosure, "on")
    await access(enclosure, at=at, **EXIT)
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")


async def test_a_restart_replaying_an_old_event_describes_nothing(ha: HomeAssistant, kind: str,
                                                                  freezer: Any) -> None:
    """After a restart the event entity comes back with its last, old, time."""
    old = (dt_util.utcnow() - timedelta(hours=1)).isoformat(timespec="milliseconds")
    ha.states.async_set(CONTACT, "off")
    await restart(ha, devices(kind, events=EVENTS))
    await fake(ha, ACCESS, "unavailable")
    await access(ha, at=old, **ENTRY)
    await tick(ha, freezer, 1)
    await contact(ha, "on")
    assert fields(ha, kind) == ("unknown", "unknown", "unknown")


async def test_denied_records_its_time_and_fields(enclosure: HomeAssistant, kind: str) -> None:
    await access(enclosure, "access_denied", actor="Estranho", authentication="NFC",
                 direction="entry", result="BLOCKED")
    assert seconds_from(enclosure, kind, "last_denied") < 1
    attributes = enclosure.states.get(entity(kind, "last_denied")).attributes
    assert (attributes["who"], attributes["how"], attributes["direction"]) == (
        "Estranho", "NFC", "entry")
    assert opened(enclosure, kind) == "off"
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")


async def test_denied_keeps_its_latest(ha: HomeAssistant, kind: str) -> None:
    """A replayed older denial, after a restart, doesn't replace the restored one."""
    last = dt_util.utcnow().replace(microsecond=0) - timedelta(minutes=5)
    await restart(ha, devices(kind, events=EVENTS),
                  (State(entity(kind, "last_denied"), last.isoformat(), {"who": "Estranho"}),
                   {"native_value": {"__type": "<class 'datetime.datetime'>",
                                     "isoformat": last.isoformat()},
                    "native_unit_of_measurement": None}))
    assert dt_util.parse_datetime(value(ha, kind, "last_denied")) == last
    assert ha.states.get(entity(kind, "last_denied")).attributes["who"] == "Estranho"
    await fake(ha, ACCESS, "unavailable")
    await access(ha, "access_denied", at=(last - timedelta(minutes=1)).isoformat(),
                 actor="Outro")
    assert dt_util.parse_datetime(value(ha, kind, "last_denied")) == last
    assert ha.states.get(entity(kind, "last_denied")).attributes["who"] == "Estranho"


async def test_a_ring_is_recorded(enclosure: HomeAssistant, kind: str) -> None:
    await ring(enclosure)
    assert seconds_from(enclosure, kind, "last_ring") < 1
    assert "who" not in enclosure.states.get(entity(kind, "last_ring")).attributes


async def test_a_ring_never_describes_an_opening(enclosure: HomeAssistant, kind: str) -> None:
    await contact(enclosure, "on")
    await ring(enclosure)
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")
    assert value(enclosure, kind, "last_ring") != "unknown"


async def test_only_what_the_events_give_is_created(ha: HomeAssistant, kind: str) -> None:
    await contact(ha, "off")
    assert await setup(ha, devices(kind, events=[EVENTS[1]]))
    assert ha.states.get(entity(kind, "last_ring")) is not None
    for entity_key in (*FIELD_KEYS, "last_denied"):
        assert ha.states.get(entity(kind, entity_key)) is None, entity_key


async def test_without_events_nothing_of_theirs_is_created(door: HomeAssistant,
                                                           kind: str) -> None:
    for entity_key in (*FIELD_KEYS, "last_denied", "last_ring"):
        assert door.states.get(entity(kind, entity_key)) is None, entity_key


async def test_the_fields_restore(ha: HomeAssistant, kind: str) -> None:
    await restart(ha, devices(kind, events=EVENTS),
                  (State(entity(kind, "last_opened_by"), "Alex Doe"),
                   {"native_value": "Alex Doe", "native_unit_of_measurement": None}))
    assert value(ha, kind, "last_opened_by") == "Alex Doe"


async def test_the_fields_have_names(enclosure: HomeAssistant, kind: str) -> None:
    state = enclosure.states.get(entity(kind, "last_opened_by"))
    assert state.attributes["friendly_name"] == f"{NAME} Last opened by"


async def test_a_second_event_of_a_described_opening_describes_no_other(
        enclosure: HomeAssistant, kind: str, freezer: Any) -> None:
    """Two events for one opening (a lock and a keypad): the later one is that opening's too."""
    await contact(enclosure, "on")
    await access(enclosure, **ENTRY)
    await tick(enclosure, freezer, 0.5)
    await access(enclosure, **EXIT)
    await tick(enclosure, freezer, 1)
    await contact(enclosure, "off")
    await tick(enclosure, freezer, 1)
    await contact(enclosure, "on")
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")


NOT_AWARE_TIMES = [
    pytest.param("2026-09-16T10:00:00", id="no time zone"),
    pytest.param("2026-09-16", id="a date"),
    pytest.param("2026-13-45 10:00:00", id="out of range"),
]


@pytest.mark.parametrize("at", NOT_AWARE_TIMES)
async def test_a_time_without_zone_describes_nothing(enclosure: HomeAssistant, kind: str,
                                                     caplog: pytest.LogCaptureFixture,
                                                     at: str) -> None:
    await contact(enclosure, "on")
    await access(enclosure, at=at, **ENTRY)
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")
    assert not [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]


@pytest.mark.parametrize("at", NOT_AWARE_TIMES)
async def test_a_time_without_zone_leaves_denied_working(enclosure: HomeAssistant, kind: str,
                                                         freezer: Any,
                                                         caplog: pytest.LogCaptureFixture,
                                                         at: str) -> None:
    await access(enclosure, "access_denied", at=at, actor="Estranho")
    assert value(enclosure, kind, "last_denied") == "unknown"
    await tick(enclosure, freezer, 1)
    await access(enclosure, "access_denied", actor="Outro")
    assert seconds_from(enclosure, kind, "last_denied") < 1
    assert enclosure.states.get(entity(kind, "last_denied")).attributes["who"] == "Outro"
    assert not [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]


async def test_the_first_of_two_waiting_events_wins(enclosure: HomeAssistant, kind: str,
                                                    freezer: Any) -> None:
    await access(enclosure, **EXIT)
    await tick(enclosure, freezer, 1)
    await access(enclosure, **ENTRY)
    await tick(enclosure, freezer, 1)
    await contact(enclosure, "on")
    assert fields(enclosure, kind) == ("N/A", "REX", "exit")


async def test_a_late_event_of_the_previous_opening_describes_no_reopening(
        enclosure: HomeAssistant, kind: str, freezer: Any) -> None:
    """Closed and opened again at once; the first opening's event, 0.9 s after it, comes late."""
    first = dt_util.utcnow()
    await opening(enclosure, freezer, 1)
    await tick(enclosure, freezer, 1)
    await contact(enclosure, "on")
    await access(enclosure, at=(first + timedelta(seconds=0.9)).isoformat(timespec="milliseconds"),
                 **ENTRY)
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")


async def test_a_reload_keeps_the_opening_described(enclosure: HomeAssistant, kind: str,
                                                    freezer: Any) -> None:
    await contact(enclosure, "on")
    await access(enclosure, **ENTRY)
    await tick(enclosure, freezer, 1)
    await reload(enclosure, devices(kind, events=EVENTS))
    await tick(enclosure, freezer, 0.5)
    await access(enclosure, **EXIT)
    assert fields(enclosure, kind) == ("Alex Doe", "PIN_CODE", "entry")


async def test_an_event_after_a_reload_still_describes_the_opening(
        enclosure: HomeAssistant, kind: str, freezer: Any) -> None:
    await contact(enclosure, "on")
    await reload(enclosure, devices(kind, events=EVENTS))
    await tick(enclosure, freezer, 0.9)
    await access(enclosure, **ENTRY)
    assert fields(enclosure, kind) == ("Alex Doe", "PIN_CODE", "entry")


async def test_an_opening_saved_before_described_is_restored_undescribed(
        ha: HomeAssistant, kind: str, freezer: Any) -> None:
    """.storage from before `described` was kept: the opening takes its event."""
    ha.states.async_set(CONTACT, "on")
    await restart(ha, devices(kind, events=EVENTS), saved_open(kind, 1))
    await access(ha, **ENTRY)
    assert fields(ha, kind) == ("Alex Doe", "PIN_CODE", "entry")


async def test_a_waiting_event_too_early_leaves_the_next_to_describe(
        enclosure: HomeAssistant, kind: str, freezer: Any) -> None:
    """Events at 0 s and 4 s, the door opening at 8 s: only the second is within 5 s of it."""
    await access(enclosure, **EXIT)
    await tick(enclosure, freezer, 4)
    await access(enclosure, **ENTRY)
    await tick(enclosure, freezer, 4)
    await contact(enclosure, "on")
    assert fields(enclosure, kind) == ("Alex Doe", "PIN_CODE", "entry")
