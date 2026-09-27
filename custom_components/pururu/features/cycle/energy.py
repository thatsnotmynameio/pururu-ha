"""An energy counter read in kWh, and what a cycle used."""

from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_conversion import EnergyConverter

from ...entity import reading


def kwh_now(hass: HomeAssistant, counter: str | None) -> float | None:
    """The counter in kWh (no unit: kWh); None without a counter, a reading or an energy unit."""
    if counter is None:
        return None
    state = hass.states.get(counter)
    if state is None or (value := reading(state)) is None:
        return None
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, UnitOfEnergy.KILO_WATT_HOUR)
    if unit not in EnergyConverter.VALID_UNITS:
        return None
    return EnergyConverter.convert(value, unit, UnitOfEnergy.KILO_WATT_HOUR)


def kwh_used(start: float | None, end: float | None) -> float | None:
    """How much the counter grew from `start` to `end`, never negative; None when either is unknown.

    Not rounded: a sip's fraction of a Wh must still add up in a total.
    """
    if start is None or end is None:
        return None
    return max(end - start, 0.0)
