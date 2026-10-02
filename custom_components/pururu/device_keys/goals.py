"""Goals: what a device must achieve in each calendar period, and how much it did.

A goal is a target, a period and what tracks it (tracked_by): a total of
this device, of another (device.<device>.<path>), or Home Assistant's
entity (homeassistant.<entity ID>). The target is in the tracked entity's
unit. Each goal is two sensors of its device (GOALS): its target, and what
was done in the period.
"""

from collections.abc import Hashable, Iterator, Mapping
from typing import Any, override

import voluptuous as vol

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from ..const import CONF_DEVICES, CONF_GOALS, CONF_TRACKED_BY
from ..core.entity import PururuEntity
from ..core.feature import TEXT, Device, Feature, Item, finite_float
from ..core.resolve import Index, Owner, Ref, path, resolve
from ..core.roles import Items, Refers

NAMESPACE = "goal"
PER_GOAL: dict[str, Platform] = {
    "target": Platform.SENSOR,
    "done": Platform.SENSOR,
}
# The statistics aspect's periods, turning over as its meters do
PERIODS = ("today", "week", "month", "year")
# What a tracked pururu entity's key ends with: it accumulates
TOTAL = "_total"

GOAL = vol.Schema(
    {
        # A blank name would show the goal's sensors by their suffixes alone
        vol.Required(CONF_NAME): TEXT,
        # In the tracked entity's unit: none of its own
        vol.Required("target"): vol.All(
            finite_float, vol.Range(min=0, min_included=False)
        ),
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


class GoalDone(PururuEntity, SensorEntity):
    """How much the tracked entity grew in the period: not metered yet, so unknown."""

    def __init__(self, device: Device, *, item: Item, follows: tuple[str, ...]) -> None:
        """What `item`'s goal did, tracked by what it follows."""
        self._identify(device, Platform.SENSOR, "done", item=item)
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


def build(
    hass: HomeAssistant,
    device: Device,
    config: dict[str, Any],
    inputs: Mapping[str, str],
) -> list[PururuEntity]:
    """Each goal's target and done, both following its pururu tracked_by."""
    tracked = {goal_key: ref.text for (goal_key, _), ref in _refers(config)}
    entities: list[PururuEntity] = []
    for item in _items(config):
        # A pururu entity, of this device or another: none for Home Assistant's
        follows = (tracked[item.slug],) if item.slug in tracked else ()
        entities.append(
            GoalTarget(device, config[item.slug]["target"], item=item, follows=follows)
        )
        entities.append(GoalDone(device, item=item, follows=follows))
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
