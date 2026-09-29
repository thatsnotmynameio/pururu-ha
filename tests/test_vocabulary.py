"""The vocabulary's state trigger and period: a validated block as HA reads it."""

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
import pytest

from helpers import module

ENTITY = "binary_sensor.door"


def trigger(ha: HomeAssistant, block: dict[str, Any]) -> dict[str, Any]:
    return module("core.vocabulary").trigger(block, ENTITY)


def test_to_without_from_adds_not_from_unavailable_unknown(ha: HomeAssistant) -> None:
    assert trigger(ha, {"to": "on"}) == {
        "trigger": "state", "entity_id": ENTITY,
        "not_from": ["unavailable", "unknown"], "to": "on",
    }


def test_to_with_from_replaces_not_from(ha: HomeAssistant) -> None:
    assert trigger(ha, {"to": "on", "from": "off"}) == {
        "trigger": "state", "entity_id": ENTITY, "from": "off", "to": "on",
    }


@pytest.mark.parametrize(("block", "expected"), [
    pytest.param({"above": 10}, {"trigger": "numeric_state", "entity_id": ENTITY, "above": 10},
                 id="above only"),
    pytest.param({"below": 20}, {"trigger": "numeric_state", "entity_id": ENTITY, "below": 20},
                 id="below only"),
    pytest.param({"above": 10, "below": 20},
                 {"trigger": "numeric_state", "entity_id": ENTITY, "above": 10, "below": 20},
                 id="above and below"),
])
def test_above_or_below_gives_numeric_state(
        ha: HomeAssistant, block: dict[str, Any], expected: dict[str, Any]) -> None:
    assert trigger(ha, block) == expected


def test_for_becomes_has_period(ha: HomeAssistant) -> None:
    assert trigger(ha, {"to": "on", "for": timedelta(minutes=5)}) == {
        "trigger": "state", "entity_id": ENTITY,
        "not_from": ["unavailable", "unknown"], "to": "on", "for": "00:05:00",
    }


# --- period ------------------------------------------------------------------


def test_period_of_whole_seconds(ha: HomeAssistant) -> None:
    assert module("core.vocabulary").period(timedelta(hours=1, minutes=2, seconds=3)) == "01:02:03"


def test_period_of_a_fraction_of_a_second(ha: HomeAssistant) -> None:
    assert (module("core.vocabulary").period(timedelta(seconds=1, microseconds=500000))
            == "00:00:01.500000")


def test_period_of_a_negative_value(ha: HomeAssistant) -> None:
    assert module("core.vocabulary").period(timedelta(seconds=-5)) == "-00:00:05"
