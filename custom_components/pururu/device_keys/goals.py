"""Goals: what a device must achieve in each calendar period, and how much it did.

A goal is a target, a period and what tracks it (tracked_by): a total of
this device, of another (device.<device>.<path>), or Home Assistant's
entity (homeassistant.<entity ID>). The target is in the tracked entity's
unit. Each goal is two sensors of its device (GOALS): its target, and what
was done in the period, a meter of the tracked entity (aspects/statistics.py).
"""

from collections.abc import Hashable, Iterator, Mapping
import logging
from typing import Any, override

import voluptuous as vol

from homeassistant.components.sensor import (
    ATTR_STATE_CLASS,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_registry as er

from ..aspects.statistics import PERIODS, Meter
from ..const import CONF_DEVICES, CONF_GOALS, CONF_TRACKED_BY, DATA_CONFIG
from ..core.entity import PururuEntity
from ..core.feature import TEXT, Device, Feature, Item, finite_float
from ..core.resolve import Index, Owner, Ref, path, resolve
from ..core.roles import Items, Refers

_LOGGER = logging.getLogger(__name__)

NAMESPACE = "goal"
PER_GOAL: dict[str, Platform] = {
    "target": Platform.SENSOR,
    "done": Platform.SENSOR,
}
# What a tracked pururu entity's key ends with: it accumulates
TOTAL = "_total"
# The state classes of what accumulates
ACCUMULATING = (SensorStateClass.TOTAL, SensorStateClass.TOTAL_INCREASING)

GOAL = vol.Schema(
    {
        # A blank name would show the goal's sensors by their suffixes alone
        vol.Required(CONF_NAME): TEXT,
        # In the tracked entity's unit: none of its own
        vol.Required("target"): vol.All(
            finite_float, vol.Range(min=0, min_included=False)
        ),
        # The statistics aspect's periods, turning over as its meters do
        vol.Required("period"): vol.In(
            PERIODS, msg=f"a goal's period is one of {', '.join(PERIODS)}"
        ),
        # A path: of this device, of another (device.<device>.<path>), or
        # Home Assistant's entity (homeassistant.<entity ID>), kept whole
        vol.Required(CONF_TRACKED_BY): path,
    }
)
# A schema of its own: ALLOW_EXTRA would let a key that isn't a slug through
SCHEMA = vol.All(vol.Schema({cv.slug: GOAL}), vol.Length(min=1))


class GoalTarget(PururuEntity, SensorEntity):
    """A goal's target, as written."""

    def __init__(
        self,
        device: Device,
        target: float,
        *,
        item: Item,
        follows: tuple[str, ...],
    ) -> None:
        """Show `target`, the goal of `item`'s, tracked by what it follows."""
        self._identify(device, Platform.SENSOR, "target", item=item)
        self._target = target
        self.follows = follows

    @property
    @override
    def native_value(self) -> float:
        """The target."""
        return self._target


class GoalDone(Meter):
    """How much the tracked entity grew in the period: a meter of it, of this definition alone."""

    def __init__(
        self,
        device: Device,
        source: str,
        goal: Mapping[str, Any],
        *,
        item: Item,
        follows: tuple[str, ...],
    ) -> None:
        """Meter `source`, what `goal` is tracked by, over its period, following what it follows.

        Its fingerprint is the goal's tracked_by as written, and its period:
        a saved value of another is of something else, so it starts at 0; a
        tracked entity renamed in the UI keeps it.
        """
        super().__init__(
            device,
            "done",
            source,
            goal["period"],
            item=item,
            fingerprint=f"{goal[CONF_TRACKED_BY]} {goal['period']}",
        )
        self.follows = follows


def _item(key: str, goal: Mapping[str, Any]) -> Item:
    return Item(slug=key, name=goal[CONF_NAME], path=(key,))


def _items(config: Mapping[str, Any]) -> list[Item]:
    return [_item(key, goal) for key, goal in config.items()]


def _refers(config: Mapping[str, Any]) -> list[tuple[tuple[str, ...], Ref]]:
    """What each goal tracks, at its tracked_by: a path of a device; Home Assistant's is no index reference."""
    return [
        ((goal_key, CONF_TRACKED_BY), ref)
        for goal_key, goal in config.items()
        if (ref := Ref.parse(goal[CONF_TRACKED_BY])).owner is not Owner.HOME_ASSISTANT
    ]


def _real(hass: HomeAssistant, here: str, ref: Ref) -> str | None:
    """The Home Assistant entity whose state class says whether `ref` accumulates; None: a pururu total.

    Home Assistant's entity itself; for a path whose node in its device's
    validated block is Home Assistant's entity (appliance.energy, the energy
    mirror: it shows its plug's reading and state class), that entity.
    """
    if ref.owner is Owner.HOME_ASSISTANT:
        return ref.path
    node: Any = hass.data[DATA_CONFIG][CONF_DEVICES][ref.device or here]
    for segment in ref.path.split("."):
        if not isinstance(node, Mapping) or segment not in node:
            return None
        node = node[segment]
    return node if isinstance(node, str) else None


def _state_class(hass: HomeAssistant, entity_id: str) -> str | None:
    """Its state class, from the registry first (known before it is loaded), then its state; None: not known yet."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is not None and entry.capabilities:
        if (state_class := entry.capabilities.get(ATTR_STATE_CLASS)) is not None:
            return str(state_class)
    state = hass.states.get(entity_id)
    if state is None or (state_class := state.attributes.get(ATTR_STATE_CLASS)) is None:
        return None
    return str(state_class)


def build(
    hass: HomeAssistant,
    device: Device,
    config: dict[str, Any],
    inputs: Mapping[str, str],
) -> list[PururuEntity]:
    """Each goal's target and done, both following its pururu tracked_by.

    A goal tracked by what doesn't accumulate, its state class known (Home
    Assistant's entity, or the plug an energy mirror shows), is logged and
    not created; one not known yet is: done waits for its first reading.
    """
    entities: list[PururuEntity] = []
    for item in _items(config):
        goal = config[item.slug]
        ref = Ref.parse(goal[CONF_TRACKED_BY])
        real = _real(hass, device.key, ref)
        state_class = None if real is None else _state_class(hass, real)
        if state_class is not None and state_class not in ACCUMULATING:
            _LOGGER.error(
                "%s: %s: %s: %s doesn't accumulate (state class %s); not creating it",
                device.key,
                CONF_GOALS,
                item.slug,
                ref.text,
                state_class,
            )
            continue
        if ref.owner is Owner.HOME_ASSISTANT:
            follows: tuple[str, ...] = ()
            source = ref.path
        else:
            # A pururu entity, of this device or another: by its current ID
            follows = (ref.text,)
            source = inputs[ref.text]
        entities.append(GoalTarget(device, goal["target"], item=item, follows=follows))
        entities.append(GoalDone(device, source, goal, item=item, follows=follows))
    return entities


# Not a device's feature: its goals, built as a Feature's entities
GOALS = Feature(
    schema=SCHEMA,
    entity_keys={},
    build=build,
    example={
        "filtering": {
            "name": "Filtering",
            "target": 6,
            "period": "today",
            "tracked_by": "appliance.running_program.runtime_total",
        }
    },
    namespace=NAMESPACE,
    roles=(Items(PER_GOAL, _items), Refers(_refers, other_devices=True)),
)


def check(house: Mapping[str, Any], index: Index, *_: Any) -> Iterator[vol.Invalid]:
    """Refuse a goal tracked by a pururu entity that isn't a total (a schema check), at its tracked_by.

    A total accumulates; its key, not its path, says it (the energy mirror,
    appliance.energy, is appliance_energy_total). What names no entity, or
    this block's own, is checks.references' refusal, so each is refused once.
    Home Assistant's entity is checked when the entry sets up: it may not be
    loaded yet.
    """
    for key, device in house[CONF_DEVICES].items():
        for (goal_key, field), ref in _refers(device.get(CONF_GOALS, {})):
            found = resolve(index, key, ref)
            if isinstance(found, str) or found.key.endswith(TOTAL):
                continue
            if found.builder == CONF_GOALS and found.device.key == key:
                continue
            place: list[Hashable] = [CONF_DEVICES, key, CONF_GOALS, goal_key, field]
            yield vol.Invalid(
                f"{CONF_GOALS}: {goal_key}: {ref.text} is not a total", path=place
            )
