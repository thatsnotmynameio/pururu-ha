"""The recorder leaves out every pururu entity's `reference`, and still what its Home Assistant base leaves out.

`PururuEntity` comes before `GroupEntity` (entity_id, group_entities) and
`UtilityMeterSensor` (next_reset) in Mirror, Switch, Light, SwitchLight and
Meter: a set of its own would hide theirs, and history would start keeping
them, with no error. The recorder's own code reads what each state stores.
"""

import json
from typing import Any

from homeassistant.components.recorder.db_schema import StateAttributes
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.entity import Entity
import pytest

from helpers import fake, module, setup

KEY = "kitchen"
DEVICES: dict[str, Any] = {KEY: {
    "name": "Kitchen",
    "appliance": {
        "power": "homeassistant.sensor.kitchen_plug_power",
        "energy": "homeassistant.sensor.kitchen_plug_energy",
        "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
        "statistics": {"idle_energy": ["today"]},
    },
    "switches": {"kettle": {"entity": "homeassistant.switch.kitchen_kettle", "name": "Kettle"}},
    "lights": {
        "ceiling": {"entity": "homeassistant.light.kitchen_ceiling", "name": "Ceiling"},
        "strip": {"entity": "homeassistant.switch.kitchen_strip", "name": "Strip"},
    },
}}
# Each class, and what its Home Assistant base leaves out of history (with the state showing it)
ENTITIES = {
    "Mirror": ("sensor.pururu_kitchen_appliance_power", {"entity_id"}),
    "Switch": ("switch.pururu_kitchen_switch_kettle", {"entity_id"}),
    "Light": ("light.pururu_kitchen_light_ceiling", {"entity_id"}),
    "SwitchLight": ("light.pururu_kitchen_light_strip", {"entity_id"}),
    "Meter": ("sensor.pururu_kitchen_appliance_idle_energy_today", {"next_reset"}),
}
# What a group or a meter leaves out, whether or not this state shows it
BASES = {"entity_id", "group_entities", "next_reset"}


def recorded(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    """The attributes the recorder stores for the entity's current state."""
    state = hass.states.get(entity_id)
    event = Event(EVENT_STATE_CHANGED, {"entity_id": entity_id, "old_state": None, "new_state": state})
    return json.loads(StateAttributes.shared_attrs_bytes_from_event(event, None))


@pytest.fixture
async def kitchen(ha: HomeAssistant) -> HomeAssistant:
    await fake(ha, "sensor.kitchen_plug_power", "1.4", {"unit_of_measurement": "W"})
    await fake(ha, "sensor.kitchen_plug_energy", "100", {"unit_of_measurement": "kWh"})
    await fake(ha, "switch.kitchen_kettle", "off")
    await fake(ha, "light.kitchen_ceiling", "on",
               {"supported_color_modes": ["onoff"], "color_mode": "onoff"})
    await fake(ha, "switch.kitchen_strip", "off")
    assert await setup(ha, DEVICES)
    return ha


@pytest.mark.parametrize("name", list(ENTITIES))
async def test_reference_is_shown_not_recorded(kitchen: HomeAssistant, name: str) -> None:
    entity_id, shown = ENTITIES[name]
    attributes = kitchen.states.get(entity_id).attributes
    assert "reference" in attributes, entity_id
    assert shown <= set(attributes), (entity_id, set(attributes))
    kept = recorded(kitchen, entity_id)
    assert "reference" not in kept, entity_id
    assert not BASES & set(kept), (entity_id, kept)


@pytest.mark.parametrize(("where", "name"), [
    ("features.appliance.mirrors", "Mirror"),
    ("features.switches", "Switch"),
    ("features.lights", "Light"),
    ("features.lights", "SwitchLight"),
    ("aspects.statistics", "Meter"),
])
def test_each_class_leaves_out_every_base_set(ha: HomeAssistant, where: str, name: str) -> None:
    """The union over the MRO: what any base leaves out (group_entities too, shown only by a group helper), and reference."""
    cls = getattr(module(where), name)
    combined = getattr(cls, "_Entity__combined_unrecorded_attributes")
    every = frozenset().union(*(vars(base).get("_unrecorded_attributes", frozenset())
                                for base in cls.__mro__ if issubclass(base, Entity)))
    assert "reference" in combined, combined
    assert every <= combined, every - combined
