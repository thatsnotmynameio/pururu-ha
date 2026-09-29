"""The vocabulary of conditions: what makes a watched state hold."""

from dataclasses import dataclass
import math

from homeassistant.const import ATTR_RESTORED, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State

# States that are no reading, unless the condition is about them
NO_READING = (STATE_UNAVAILABLE, STATE_UNKNOWN)


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
