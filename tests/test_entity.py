"""reading(): a sensor's number, or None while it has none; as_time(): a time read back; an entity's key and reference."""

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

from helpers import DOMAIN, module, setup


def value(state: str | None) -> float | None:
    entity = module("core.entity")
    return entity.reading(None if state is None else State("sensor.demo", state))


def test_a_number_is_read(ha: HomeAssistant) -> None:
    assert value("5") == 5.0
    assert value("5.5") == 5.5


def test_unknown_and_unavailable_have_no_reading(ha: HomeAssistant) -> None:
    assert value("unknown") is None
    assert value("unavailable") is None


def test_not_a_number_has_no_reading(ha: HomeAssistant) -> None:
    assert value("abc") is None


def test_no_state_has_no_reading(ha: HomeAssistant) -> None:
    assert value(None) is None


def test_non_finite_numbers_have_no_reading(ha: HomeAssistant) -> None:
    assert value("nan") is None
    assert value("inf") is None
    assert value("-inf") is None



def test_a_time_is_read_back(ha: HomeAssistant) -> None:
    """A datetime as it is, a time's string parsed; an impossible date and anything else, none."""
    as_time = module("core.entity").as_time
    moment = dt_util.utcnow()
    assert as_time(moment) is moment
    assert as_time(moment.isoformat()) == moment
    assert as_time("2026-02-30T10:00:00+00:00") is None
    assert as_time("not a time") is None
    assert as_time(None) is None
    assert as_time(5) is None


async def test_an_entity_knows_its_key_and_reference(ha: HomeAssistant) -> None:
    """`<device>.<entity key>`: the event_name events fire, the reference form C adds to the YAML."""
    pool = {"name": "Piscina", "switches": {"pump": {"entity": "switch.pool_pump", "name": "Bomba"}}}
    assert await setup(ha, {"pool": pool})
    [entry] = ha.config_entries.async_entries(DOMAIN)
    [switch] = entry.runtime_data[Platform.SWITCH]
    assert (switch.key, switch.reference) == ("switch_pump", "pool.switch_pump")
