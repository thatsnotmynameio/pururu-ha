"""Programs: sequences of actions on a device's own entities, as Home Assistant scripts.

A program is a method of its device: something starts it, and it turns the
device's own switches and lights on and off, with delays between. Its steps are
pururu's, translated to HA's script syntax in pururu/scripts/programs.yaml,
whose folder configuration.yaml includes (generated.py); HA runs it. No step
can reach outside the device. Each run is a cycle: its statistics are sensors
of its device (STATISTICS).
"""

from collections.abc import Collection, Hashable, Iterable, Iterator, Mapping
import logging
from typing import Any, override

import voluptuous as vol

from homeassistant.const import CONF_NAME, STATE_OFF, STATE_ON, Platform
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
    split_entity_id,
)
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from ..const import CONF_AREA, CONF_DEVICES, CONF_PROGRAMS, CONF_SCRIPTS, ENTITY_PREFIX
from ..core import generated
from ..core.entity import PururuEntity
from ..core.feature import Device, Feature, Item, qualified
from ..core.generated import Kind, Planned, period
from ..core.resolve import Index, Ref, Target, find
from ..core.roles import Generates, Items
from ..features.cycle import Cycle, CycleSource
from ..features.cycle.last import LAST_CYCLE, LastCycleValue
from ..features.cycle.statistics import PERIOD_LIST, PERIODS, Meter
from ..features.cycle.totals import CyclesTotal, RuntimeTotal

_LOGGER = logging.getLogger(__name__)

# The namespace of every program's script ID
NAMESPACE = "program"
DELAY = "delay"
# What a step can do to an entity; the device schema checks its feature takes it
ACTIONS = ("turn_on", "turn_off", "toggle")
KIND = Kind(
    domain="script",
    folder="pururu/scripts",
    file="pururu/scripts/programs.yaml",
    merge="named",
    issue="scripts_not_included",
    data_key=CONF_SCRIPTS,
    one="a script",
    plural="scripts",
    source="programs",
)

STEP = vol.Schema(
    {
        vol.Optional(DELAY): cv.positive_time_period,
        **{vol.Optional(action): cv.slug for action in ACTIONS},
    }
)


def _step(value: Any) -> dict[str, Any]:
    """One of delay, turn_on, turn_off, toggle, with its value: exactly one key."""
    step: dict[str, Any] = STEP(value)
    if len(step) != 1:
        raise vol.Invalid(f"a step is exactly one of {DELAY}, {', '.join(ACTIONS)}")
    return step


# What a run records: the last cycle's values (a script uses no energy), and totals
LAST_RUN = tuple(d for d in LAST_CYCLE if d.key != "last_cycle_energy")
COUNTERS = ("runtime", "cycles")
PER_PROGRAM: dict[str, Platform] = {
    **{description.key: Platform.SENSOR for description in LAST_RUN},
    **{f"{counter}_total": Platform.SENSOR for counter in COUNTERS},
    **{
        f"{counter}_{period}": Platform.SENSOR
        for counter in COUNTERS
        for period in PERIODS
    },
}

PROGRAM = vol.Schema(
    {
        # A blank name would show the program as its device's name alone
        vol.Required(CONF_NAME): vol.All(cv.string, vol.Strip, vol.Length(min=1)),
        vol.Required("sequence"): vol.All([_step], vol.Length(min=1)),
        vol.Optional("statistics", default={}): vol.Schema(
            {vol.Optional(counter, default=[]): PERIOD_LIST for counter in COUNTERS}
        ),
    }
)
# A schema of its own: ALLOW_EXTRA would let a key that isn't a slug through
SCHEMA = vol.All(vol.Schema({cv.slug: PROGRAM}), vol.Length(min=1))


def targets(program: Mapping[str, Any]) -> Iterator[tuple[str, str]]:
    """(action, entity key) of each step that acts on an entity, in order."""
    for step in program["sequence"]:
        yield from ((action, key) for action, key in step.items() if action != DELAY)


def script_id(device_key: str, program_key: str) -> str:
    """The script's object ID, and its unique ID: the pururu pattern."""
    return f"{ENTITY_PREFIX}_{device_key}_{qualified(NAMESPACE, program_key)}"


def _translated(
    step: Mapping[str, Any], entity_ids: Mapping[str, str]
) -> dict[str, Any]:
    """A step in HA's script syntax."""
    ((action, value),) = step.items()
    if action == DELAY:
        return {DELAY: period(value)}
    entity_id = entity_ids[value]
    return {
        "action": f"{split_entity_id(entity_id)[0]}.{action}",
        "target": {"entity_id": entity_id},
    }


def script(
    device_key: str,
    device_name: str,
    program_key: str,
    program: Mapping[str, Any],
    entity_ids: Mapping[str, str],
) -> dict[str, Any]:
    """The script of a program; `entity_ids` maps each entity key it acts on to its current ID.

    single: a start while it runs is ignored, and HA logs it.
    """
    return {
        "alias": f"{device_name} {program[CONF_NAME]}",
        "description": f"pururu: {device_key}, {program_key}",
        "mode": "single",
        "sequence": [_translated(step, entity_ids) for step in program["sequence"]],
    }


class Runs(CyclesTotal, CycleSource):
    """A program's finished runs, all time; it sends each one: its script on, then off.

    The run's start is the `on` state's: a pururu reload while it runs keeps it.
    """

    def __init__(self, device: Device, script: str | None, *, item: Item) -> None:
        """Count the runs of `script`, the entity of `item`'s program; None watches none."""
        super().__init__(device, source="cycles_total", item=item)
        # The script isn't pururu's: nothing of the device to wait for
        self.sources = ()
        self._script = script
        self._cycle_signals(device, item)

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the count and count, then watch the script."""
        await super().async_added_to_hass()
        if self._script is not None:
            self.async_on_remove(
                async_track_state_change_event(self.hass, self._script, self._changed)
            )

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if (
            old is None
            or new is None
            or (old.state, new.state) != (STATE_ON, STATE_OFF)
        ):
            return
        run = Cycle(start=old.last_changed, end=new.last_changed, energy_kwh=None)
        self._send(run)


def _items(config: Mapping[str, Any]) -> list[Item]:
    return [Item(slug=key, name=program[CONF_NAME]) for key, program in config.items()]


def build(
    hass: HomeAssistant,
    device: Device,
    config: dict[str, Any],
    inputs: Mapping[str, str],
) -> list[PururuEntity]:
    """Each program's runs as cycles: its last run, totals, the meters asked for.

    `inputs` are the entity IDs of the scripts the entry generates, by ID: a
    program whose script ID someone else holds counts nothing.
    """
    entities: list[PururuEntity] = []
    for item in _items(config):
        script = inputs.get(script_id(device.key, item.slug))
        counted = item.key("cycles_total")
        entities.append(Runs(device, script, item=item))
        entities.extend(
            LastCycleValue(device, description, source=counted, item=item)
            for description in LAST_RUN
        )
        entities.append(
            RuntimeTotal(device, script, STATE_ON, source=counted, item=item)
        )
        for counter in COUNTERS:
            total = f"{counter}_total"
            source = device.current_entity_id(hass, Platform.SENSOR, item.key(total))
            entities.extend(
                Meter(device, f"{counter}_{period}", total, source, period, item=item)
                for period in config[item.slug]["statistics"][counter]
            )
    return entities


# Not a device's feature: its programs' statistics, built as a Feature's entities
STATISTICS = Feature(
    schema=SCHEMA,
    entity_keys={},
    build=build,
    example={"clean": {"name": "Clean", "sequence": [{"delay": 1}]}},
    namespace=NAMESPACE,
    roles=(
        Items(PER_PROGRAM, _items),
        Generates(
            "program",
            lambda key, config: ((KIND.domain, script_id(key, p)) for p in config),
        ),
    ),
)


def check(house: Mapping[str, Any], index: Index, *_: Any) -> Iterator[vol.Invalid]:
    """Refuse a step on what isn't another feature's entity key of the device taking its action (a schema check)."""
    for key, device in house[CONF_DEVICES].items():
        for program_key, program in device.get(CONF_PROGRAMS, {}).items():
            path: list[Hashable] = [CONF_DEVICES, key, CONF_PROGRAMS, program_key]
            for action, entity_key in targets(program):
                target = find(index, key, Ref(None, entity_key))
                if target is None:
                    yield vol.Invalid(
                        f"programs: {entity_key} is not an entity key of another "
                        "feature of this device",
                        path=path,
                    )
                    break
                if action not in target.actions:
                    yield vol.Invalid(
                        f"programs: {entity_key} does not take {action}", path=path
                    )
                    break


def plan(
    hass: HomeAssistant,
    devices: Mapping[str, Any],
    index: Index,
    created: Collection[str],
) -> Planned:
    """A script per program of every device, in the device's area; one that can't act is logged.

    Held: the scripts whose entity is disabled (their registry entries stay, as
    the user set them). Targets: the entity IDs the generated scripts act on.
    """
    registry = er.async_get(hass)
    scripts: list[generated.Item] = []
    held: set[str] = set()
    targets_: set[str] = set()
    for key, config in devices.items():
        for program_key, program in config.get(CONF_PROGRAMS, {}).items():
            unique_id = script_id(key, program_key)
            entity_ids = _acted_on(hass, index[key], unique_id, program, created)
            if entity_ids is None:
                continue
            if _disabled(registry, unique_id, entity_ids.values()):
                held.add(unique_id)
                continue
            targets_.update(entity_ids.values())
            scripts.append(
                generated.Item(
                    unique_id=unique_id,
                    config=script(
                        key, config[CONF_NAME], program_key, program, entity_ids
                    ),
                    area=config.get(CONF_AREA),
                )
            )
    return Planned(scripts, frozenset(held), frozenset(targets_))


def _acted_on(
    hass: HomeAssistant,
    found: Mapping[str, Target],
    unique_id: str,
    program: Mapping[str, Any],
    created: Collection[str],
) -> dict[str, str] | None:
    """Each entity key the program acts on -> its current entity ID; None, logged, when one isn't created."""
    entity_ids: dict[str, str] = {}
    for _, key in targets(program):
        target = found[key]
        entity_id = target.current_entity_id(hass)
        if target.unique_id not in created:
            _LOGGER.error(
                "script.%s follows %s, which is not created; not generating it",
                unique_id,
                entity_id,
            )
            return None
        entity_ids[key] = entity_id
    return entity_ids


def _disabled(
    registry: er.EntityRegistry, unique_id: str, entity_ids: Iterable[str]
) -> bool:
    """Whether one of them is disabled, logged: the program is held.

    It comes back as the user set it once the entity is enabled again. The
    entry is reloaded when an entity a generated script acts on is disabled
    (pururu's registry listener), and when a disabled one is enabled again
    (HA's own).
    """
    for entity_id in entity_ids:
        if (registered := registry.async_get(entity_id)) is not None and (
            registered.disabled
        ):
            _LOGGER.error(
                "script.%s acts on %s, which is disabled; not generating it",
                unique_id,
                entity_id,
            )
            return True
    return False
