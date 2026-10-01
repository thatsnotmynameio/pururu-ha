"""The vocabulary of conditions and triggers: what makes a watched state hold, the HA trigger that watches it, and a period as HA reads it."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
import math
from typing import Any

from homeassistant.const import ATTR_RESTORED, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State

# States that are no reading, unless the condition is about them
NO_READING = (STATE_UNAVAILABLE, STATE_UNKNOWN)


def period(value: timedelta) -> str:
    """A time period as HA reads it: [-]HH:MM:SS, and the fraction of a second if any."""
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


def band(value: float, above: float | None, below: float | None) -> bool:
    """Whether `value` is strictly above `above` and strictly below `below`, as HA's numeric_state; None is no bound."""
    return (above is None or value > above) and (below is None or value < below)


@dataclass(frozen=True, kw_only=True)
class Condition:
    """What makes the watched entity's state hold: a state, a band, or (code only) a number.

    `state` is text, compared as HA's condition: state compares: `1` matches
    `1`, not `1.0`. `equals` compares a reading as a number: only a ready-made
    alert's (no_power), never the YAML's, and no trigger takes it.
    """

    state: str | None = None
    above: float | None = None
    below: float | None = None
    equals: float | None = None

    def holds(self, state: State | None) -> bool | None:
        """Whether `state` holds; None when it is no reading.

        A condition on unavailable or unknown holds while the entity has no
        reading, either state or missing: a plug reconnecting passes from one to
        the other. A state HA restored for an entity not loaded yet (at start,
        during a reload) is no reading, for every condition.
        """
        if state is not None and state.attributes.get(ATTR_RESTORED):
            return None
        if self.state is not None:
            return self._is(STATE_UNAVAILABLE if state is None else state.state)
        if state is None or (value := _number(state)) is None:
            return None
        if self.equals is not None:
            return value == self.equals
        return band(value, self.above, self.below)

    def _is(self, current: str) -> bool | None:
        """`state`: no reading for other states, unless it is about no reading."""
        if self.state in NO_READING:
            return current in NO_READING
        if current in NO_READING:
            return None
        return current == self.state


def parse(block: Mapping[str, Any], word: str = "state") -> Condition:
    """The Condition of a validated block: an alert's `state` (`word`), a reaction's `to`, or above/below."""
    return Condition(
        state=block.get(word), above=block.get("above"), below=block.get("below")
    )


def trigger(
    entity_id: str | None,
    when: Condition,
    *,
    from_: str | None = None,
    hold: timedelta | None = None,
) -> dict[str, Any]:
    """The HA state or numeric_state trigger of `when` on `entity_id`: `from_` the state it leaves, `hold` its for.

    With a state and no `from_`, a state coming back from no reading doesn't
    fire: a plug reconnecting (unavailable → off) is no "turned off". A
    Condition with `equals` is code's only: no trigger takes it.
    """
    if when.equals is not None:
        raise ValueError("a trigger takes a state or a band, not equals")
    result: dict[str, Any]
    if when.state is not None:
        result = {"trigger": "state", "entity_id": entity_id}
        if from_ is not None:
            result["from"] = from_
        else:
            result["not_from"] = [STATE_UNAVAILABLE, STATE_UNKNOWN]
        result["to"] = when.state
    else:
        result = {"trigger": "numeric_state", "entity_id": entity_id}
        if when.above is not None:
            result["above"] = when.above
        if when.below is not None:
            result["below"] = when.below
    if hold is not None:
        result["for"] = period(hold)
    return result
