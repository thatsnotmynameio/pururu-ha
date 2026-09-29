"""The vocabulary of conditions: what makes a watched state hold."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
import math
from typing import Any

from homeassistant.const import ATTR_RESTORED, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State

# States that are no reading, unless the condition is about them
NO_READING = (STATE_UNAVAILABLE, STATE_UNKNOWN)


def _period(value: timedelta) -> str:
    """A time period as HA reads it: [-]HH:MM:SS, and the fraction of a second if any.

    A copy of generated.period: generated.py imports entity.py, which imports
    feature.py, which imports this module for Condition, so this module can't
    import generated.py back without a cycle.
    """
    sign = "-" if value < timedelta(0) else ""
    minutes, seconds = divmod(abs(value), timedelta(minutes=1))
    hours, minutes = divmod(minutes, 60)
    text = f"{sign}{hours:02}:{minutes:02}:{seconds.seconds:02}"
    if seconds.microseconds:
        text += f".{seconds.microseconds:06}"
    return text


def _number(state: State) -> float | None:
    """A state's finite number, or None."""
    try:
        value = float(state.state)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


@dataclass(frozen=True, kw_only=True)
class Condition:
    """What makes the watched entity's state a problem: a state, a number, or a range."""

    state: str | float | None = None
    above: float | None = None
    below: float | None = None

    def holds(self, state: State | None) -> bool | None:
        """Whether `state` is a problem; None when it is no reading.

        A condition on unavailable or unknown holds while the entity has no
        reading, either state or missing: a plug reconnecting passes from one to
        the other. A state HA restored for an entity not loaded yet (at start,
        during a reload) is no reading, for every condition.
        """
        if state is not None and state.attributes.get(ATTR_RESTORED):
            return None
        if isinstance(self.state, str):
            return self._is(STATE_UNAVAILABLE if state is None else state.state)
        if state is None or (value := _number(state)) is None:
            return None
        if self.state is not None:  # a number
            return value == self.state
        return (self.above is None or value > self.above) and (
            self.below is None or value < self.below
        )

    def _is(self, current: str) -> bool | None:
        """`is` a state: no reading for other states, unless it is about no reading."""
        if self.state in NO_READING:
            return current in NO_READING
        if current in NO_READING:
            return None
        return current == self.state


def trigger(block: Mapping[str, Any], entity_id: str | None) -> dict[str, Any]:
    """The HA state or numeric_state trigger of a validated to/from/above/below/for block.

    With `to` and no `from`, a state coming back from no reading doesn't fire:
    a plug reconnecting (unavailable → off) is no "turned off".
    """
    result: dict[str, Any]
    if "to" in block:
        result = {"trigger": "state", "entity_id": entity_id}
        if "from" in block:
            result["from"] = block["from"]
        else:
            result["not_from"] = [STATE_UNAVAILABLE, STATE_UNKNOWN]
        result["to"] = block["to"]
    else:
        result = {"trigger": "numeric_state", "entity_id": entity_id}
        for key in ("above", "below"):
            if key in block:
                result[key] = block[key]
    if "for" in block:
        result["for"] = _period(block["for"])
    return result
