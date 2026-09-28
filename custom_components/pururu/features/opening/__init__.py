"""A door or a window: its contact opens and closes it, and each opening is a cycle.

`door` and `window` are one feature under two namespaces: they differ only in
their `open`'s device class and their texts. The contact is required; what
describes the openings (events.py) is optional.
"""

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import STATE_ON, Platform, UnitOfTime
from homeassistant.core import HomeAssistant

from ...entity import PururuEntity
from ...feature import Build, Device, Feature
from .. import standing
from ..cycle.last import LastCycleDescription, LastCycleValue
from ..cycle.statistics import PERIOD_LIST, PERIODS, Meter
from ..cycle.totals import CyclesTotal, RuntimeTotal
from .open import Open

_LOGGER = logging.getLogger(__name__)

# A counter in statistics -> its total is <counter>_total, its meters <counter>_<period>
COUNTERS = ("openings", "open_time")

SCHEMA = vol.Schema(
    {
        vol.Required("contact"): standing.real_entity(Platform.BINARY_SENSOR),
        vol.Optional("statistics", default={}): vol.Schema(
            {vol.Optional(counter, default=[]): PERIOD_LIST for counter in COUNTERS}
        ),
    }
)

# The last opening, as the appliance's last cycle: a door opens for seconds, not minutes
LAST_OPENING: tuple[LastCycleDescription, ...] = (
    LastCycleDescription(
        key="last_opened",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda cycle: cycle.start,
    ),
    LastCycleDescription(
        key="last_open_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value=lambda cycle: (
            None
            if cycle.start is None
            else round((cycle.end - cycle.start).total_seconds())
        ),
    ),
    LastCycleDescription(
        key="last_closed",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda cycle: cycle.end,
        written_last=True,
    ),
)

ENTITY_KEYS: dict[str, Platform] = {
    "open": Platform.BINARY_SENSOR,
    **{description.key: Platform.SENSOR for description in LAST_OPENING},
    **{f"{counter}_total": Platform.SENSOR for counter in COUNTERS},
    **{
        f"{counter}_{period}": Platform.SENSOR
        for counter in COUNTERS
        for period in PERIODS
    },
}


def _builder(device_class: BinarySensorDeviceClass) -> Build:
    """The build of a door (window), whose `open` has `device_class`."""

    def build(
        hass: HomeAssistant,
        device: Device,
        config: dict[str, Any],
        inputs: Mapping[str, str],
    ) -> list[PururuEntity]:
        """The door's entities; with a contact that is pururu's own, `open` stands for nothing.

        The configuration refuses binary_sensor.pururu_…; one renamed in the UI
        gets past that, and only the registry still knows it is ours. Its
        entities are kept, so every reload gives the same.
        """
        watched = device.current_entity_id(hass, Platform.BINARY_SENSOR, "open")
        contact: str = config["contact"]
        real: str | None = contact
        if standing.is_pururu(hass, contact):
            _LOGGER.error(
                "%s is a pururu binary sensor: name the real contact; %s stands for nothing",
                contact,
                watched,
            )
            real = None
        entities: list[PururuEntity] = [
            Open(device, device_class, contact=real),
            *(
                LastCycleValue(device, description, source="open")
                for description in LAST_OPENING
            ),
            CyclesTotal(device, source="open", entity_key="openings_total"),
            RuntimeTotal(
                device, watched, STATE_ON, source="open", entity_key="open_time_total"
            ),
        ]
        for counter in COUNTERS:
            total = f"{counter}_total"
            source = device.current_entity_id(hass, Platform.SENSOR, total)
            entities.extend(
                Meter(device, f"{counter}_{period}", total, source, period)
                for period in config["statistics"][counter]
            )
        return entities

    return build


def _opening(namespace: str, device_class: BinarySensorDeviceClass) -> Feature:
    """The feature of a door or a window: one code, its own namespace and device class."""
    return Feature(
        schema=SCHEMA,
        entity_keys=ENTITY_KEYS,
        build=_builder(device_class),
        example={"contact": f"binary_sensor.demo_{namespace}_contact"},
        namespace=namespace,
        provides={"cycle": "open"},
    )


DOOR = _opening("door", BinarySensorDeviceClass.DOOR)
WINDOW = _opening("window", BinarySensorDeviceClass.WINDOW)
