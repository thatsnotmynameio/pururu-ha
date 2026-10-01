"""The vocabulary: a Condition, the band it reads, its trigger, and a period as HA reads it."""

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
import pytest

from helpers import module

ENTITY = "binary_sensor.door"


def vocabulary(ha: HomeAssistant) -> Any:
    return module("core.vocabulary")


def condition(ha: HomeAssistant, **fields: Any) -> Any:
    return vocabulary(ha).Condition(**fields)


def trigger(ha: HomeAssistant, when: Any, **kwargs: Any) -> dict[str, Any]:
    return vocabulary(ha).trigger(ENTITY, when, **kwargs)


# --- band ---------------------------------------------------------------------


@pytest.mark.parametrize(("value", "above", "below", "expected"), [
    pytest.param(5, 4, None, True, id="above"),
    pytest.param(4, 4, None, False, id="above is strict"),
    pytest.param(5, None, 6, True, id="below"),
    pytest.param(6, None, 6, False, id="below is strict"),
    pytest.param(5, 4, 6, True, id="between"),
    pytest.param(7, 4, 6, False, id="out of the band"),
    pytest.param(-1e9, None, None, True, id="no bound"),
])
def test_band_is_strict_as_numeric_state(ha: HomeAssistant, value: float, above: float | None,
                                         below: float | None, expected: bool) -> None:
    assert vocabulary(ha).band(value, above, below) is expected


# --- holds --------------------------------------------------------------------


@pytest.mark.parametrize(("fields", "reading", "expected"), [
    pytest.param({"state": "1"}, "1", True, id="state is text"),
    pytest.param({"state": "1"}, "1.0", False, id="1 is not 1.0"),
    pytest.param({"state": "on"}, "unavailable", None, id="no reading"),
    pytest.param({"state": "unavailable"}, "unknown", True, id="about no reading"),
    pytest.param({"above": 50}, "51", True, id="above"),
    pytest.param({"above": 50}, "on", None, id="above on no number"),
    pytest.param({"equals": 0.0}, "0.0", True, id="equals is a number"),
    pytest.param({"equals": 0.0}, "0", True, id="equals 0 is 0.0"),
    pytest.param({"equals": 0.0}, "0.5", False, id="equals only that number"),
])
def test_holds(ha: HomeAssistant, fields: dict[str, Any], reading: str,
               expected: bool | None) -> None:
    assert condition(ha, **fields).holds(State("sensor.x", reading)) is expected


def test_a_missing_state_is_unavailable(ha: HomeAssistant) -> None:
    assert condition(ha, state="unavailable").holds(None) is True
    assert condition(ha, above=1).holds(None) is None


def test_a_restored_state_is_no_reading(ha: HomeAssistant) -> None:
    restored = State("sensor.x", "unavailable", {"restored": True})
    assert condition(ha, state="unavailable").holds(restored) is None


# --- parse --------------------------------------------------------------------


def test_an_alerts_state_and_a_reactions_to_are_one_condition(ha: HomeAssistant) -> None:
    """state: "1" in an alert and to: "1" in a reaction are one Condition: they hold for the same states."""
    parse = vocabulary(ha).parse
    assert parse({"state": "1"}) == parse({"to": "1", "from": "0"}, "to") == condition(ha, state="1")
    assert parse({"above": 5, "below": 9}) == condition(ha, above=5, below=9)


# --- trigger ------------------------------------------------------------------


def test_a_state_without_from_adds_not_from_unavailable_unknown(ha: HomeAssistant) -> None:
    assert trigger(ha, condition(ha, state="on")) == {
        "trigger": "state", "entity_id": ENTITY,
        "not_from": ["unavailable", "unknown"], "to": "on",
    }


def test_from_replaces_not_from(ha: HomeAssistant) -> None:
    assert trigger(ha, condition(ha, state="on"), from_="off") == {
        "trigger": "state", "entity_id": ENTITY, "from": "off", "to": "on",
    }


@pytest.mark.parametrize(("fields", "expected"), [
    pytest.param({"above": 10}, {"trigger": "numeric_state", "entity_id": ENTITY, "above": 10},
                 id="above only"),
    pytest.param({"below": 20}, {"trigger": "numeric_state", "entity_id": ENTITY, "below": 20},
                 id="below only"),
    pytest.param({"above": 10, "below": 20},
                 {"trigger": "numeric_state", "entity_id": ENTITY, "above": 10, "below": 20},
                 id="above and below"),
])
def test_above_or_below_gives_numeric_state(
        ha: HomeAssistant, fields: dict[str, Any], expected: dict[str, Any]) -> None:
    assert trigger(ha, condition(ha, **fields)) == expected


def test_hold_becomes_for_as_a_period(ha: HomeAssistant) -> None:
    assert trigger(ha, condition(ha, state="on"), hold=timedelta(minutes=5)) == {
        "trigger": "state", "entity_id": ENTITY,
        "not_from": ["unavailable", "unknown"], "to": "on", "for": "00:05:00",
    }


def test_equals_is_refused_by_a_trigger(ha: HomeAssistant) -> None:
    """equals is code's only (no_power): no YAML writes it, no automation compares with it."""
    no_power = condition(ha, equals=0.0)
    with pytest.raises(ValueError, match="a trigger takes a state or a band, not equals"):
        trigger(ha, no_power)


# --- period -------------------------------------------------------------------


def test_period_of_whole_seconds(ha: HomeAssistant) -> None:
    assert vocabulary(ha).period(timedelta(hours=1, minutes=2, seconds=3)) == "01:02:03"


def test_period_of_a_fraction_of_a_second(ha: HomeAssistant) -> None:
    assert vocabulary(ha).period(timedelta(seconds=1, microseconds=500000)) == "00:00:01.500000"


def test_period_of_a_negative_value(ha: HomeAssistant) -> None:
    assert vocabulary(ha).period(timedelta(seconds=-5)) == "-00:00:05"
