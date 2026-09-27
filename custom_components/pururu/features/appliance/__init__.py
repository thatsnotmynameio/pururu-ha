"""An appliance on a power-measuring plug: when it runs, its cycles and their statistics.

The configuration names the plug's entities and the threshold and delays measured
on that appliance.
"""

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.const import STATE_ON, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from ...entity import PururuEntity
from ...feature import Device, Feature, finite_float
from ..cycle.last import LAST_CYCLE, LastCycleValue
from ..cycle.statistics import PERIOD_LIST, PERIODS, Meter
from ..cycle.totals import CyclesTotal, RuntimeTotal
from .mirrors import Mirror
from .running import Running

SCHEMA = vol.Schema(
    {
        vol.Required("power"): cv.entity_id,
        vol.Optional("energy"): cv.entity_id,
        vol.Required("running"): {
            vol.Required("threshold"): finite_float,
            vol.Required("on_delay"): cv.positive_time_period,
            vol.Required("off_delay"): cv.positive_time_period,
        },
        vol.Optional("statistics", default={}): {
            vol.Optional("runtime", default=[]): PERIOD_LIST,
            vol.Optional("cycles", default=[]): PERIOD_LIST,
        },
    }
)

ENTITY_KEYS: dict[str, Platform] = {
    "power": Platform.SENSOR,
    "energy_total": Platform.SENSOR,
    "running": Platform.BINARY_SENSOR,
    "last_cycle_start": Platform.SENSOR,
    "last_cycle_end": Platform.SENSOR,
    "last_cycle_duration": Platform.SENSOR,
    "last_cycle_energy": Platform.SENSOR,
    "cycles_total": Platform.SENSOR,
    "runtime_total": Platform.SENSOR,
    **{
        f"{counter}_{period}": Platform.SENSOR
        for counter in ("runtime", "cycles")
        for period in PERIODS
    },
}


def build(
    hass: HomeAssistant,
    device: Device,
    config: dict[str, Any],
    inputs: Mapping[str, str],
) -> list[PururuEntity]:
    """The appliance's entities; those following another one take its current ID."""
    energy: str | None = config.get("energy")
    settings = config["running"]
    entities: list[PururuEntity] = [
        Mirror(hass, device, "power", config["power"]),
        Running(
            device,
            power=config["power"],
            energy=energy,
            threshold=settings["threshold"],
            on_delay=settings["on_delay"],
            off_delay=settings["off_delay"],
        ),
        *(
            LastCycleValue(device, description, source="running")
            for description in LAST_CYCLE
            if energy is not None or description.key != "last_cycle_energy"
        ),
        CyclesTotal(device, source="running"),
        RuntimeTotal(
            device,
            device.current_entity_id(hass, Platform.BINARY_SENSOR, "running"),
            STATE_ON,
            source="running",
        ),
    ]
    if energy is not None:
        entities.append(Mirror(hass, device, "energy_total", energy))
    for counter in ("runtime", "cycles"):
        total = f"{counter}_total"
        source = device.current_entity_id(hass, Platform.SENSOR, total)
        entities.extend(
            Meter(device, f"{counter}_{period}", total, source, period)
            for period in config["statistics"][counter]
        )
    return entities


APPLIANCE = Feature(
    schema=SCHEMA,
    entity_keys=ENTITY_KEYS,
    build=build,
    example={
        "power": "sensor.demo_plug_power",
        "running": {
            "threshold": 4,
            "on_delay": {"minutes": 1},
            "off_delay": {"minutes": 2},
        },
    },
    namespace="appliance",
    provides={"cycle": "running"},
)
