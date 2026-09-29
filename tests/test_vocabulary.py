"""The vocabulary's state trigger: a validated reaction's to/from/above/below/for as HA reads it."""

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant

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


def test_above_or_below_gives_numeric_state(ha: HomeAssistant) -> None:
    assert trigger(ha, {"above": 10}) == {
        "trigger": "numeric_state", "entity_id": ENTITY, "above": 10,
    }
    assert trigger(ha, {"below": 20}) == {
        "trigger": "numeric_state", "entity_id": ENTITY, "below": 20,
    }
    assert trigger(ha, {"above": 10, "below": 20}) == {
        "trigger": "numeric_state", "entity_id": ENTITY, "above": 10, "below": 20,
    }


def test_for_becomes_has_period(ha: HomeAssistant) -> None:
    assert trigger(ha, {"to": "on", "for": timedelta(minutes=5)}) == {
        "trigger": "state", "entity_id": ENTITY,
        "not_from": ["unavailable", "unknown"], "to": "on", "for": "00:05:00",
    }


def test_entity_id_is_set(ha: HomeAssistant) -> None:
    assert trigger(ha, {"to": "on"})["entity_id"] == ENTITY
    assert trigger(ha, {"above": 10})["entity_id"] == ENTITY
