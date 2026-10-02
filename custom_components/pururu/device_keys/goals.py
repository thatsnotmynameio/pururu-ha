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
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    Platform,
)
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util.enum import try_parse_enum

from ..aspects.statistics import PERIODS, Meter
from ..const import CONF_DEVICES, CONF_GOALS, CONF_TRACKED_BY, DATA_CONFIG
from ..core.entity import PururuEntity, reading
from ..core.feature import TEXT, Device, Feature, Item, finite_float
from ..core.resolve import Index, Owner, Ref, find, path, resolve
from ..core.roles import Items, Refers
from ..core.runtime import Built, PururuConfigEntry

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


class GoalTarget(PururuEntity, RestoreSensor):
    """A goal's target, as written, in the unit and device class of what tracks it.

    Taken from its state's attributes, where utility_meter takes done's: both
    always share a unit. Before it reports, from its registry entry, else as
    last saved. Never unavailable for its sake: the number is always known.
    """

    def __init__(
        self,
        device: Device,
        target: float,
        source: str,
        *,
        item: Item,
        follows: tuple[str, ...],
        disabled: Mapping[str, str],
    ) -> None:
        """Show `target`, the goal of `item`'s, in `source`'s unit, tracked by what it follows."""
        self._identify(device, Platform.SENSOR, "target", item=item)
        self._attr_native_value = target
        self._source = source
        self.follows = follows
        self.disabled = disabled

    @override
    async def async_added_to_hass(self) -> None:
        """Take the unit as saved, then its registry entry's, then its reading's, and follow it."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_unit_of_measurement = last.native_unit_of_measurement
        if (state := await self.async_get_last_state()) is not None:
            self._take_class(state.attributes.get(ATTR_DEVICE_CLASS))
        if (entry := er.async_get(self.hass).async_get(self._source)) is not None:
            self._attr_native_unit_of_measurement = entry.unit_of_measurement
            self._take_class(entry.original_device_class)
        self._take(self.hass.states.get(self._source))
        self.async_on_remove(
            async_track_state_change_event(self.hass, self._source, self._changed)
        )

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        if self._take(event.data["new_state"]):
            self.async_write_ha_state()

    def _take(self, state: State | None) -> bool:
        """Take `state`'s unit and device class, as utility_meter does: only from a reading."""
        if reading(state) is None:
            return False
        assert state is not None  # a reading has a state
        self._attr_native_unit_of_measurement = state.attributes.get(
            ATTR_UNIT_OF_MEASUREMENT
        )
        self._take_class(state.attributes.get(ATTR_DEVICE_CLASS))
        return True

    def _take_class(self, device_class: Any) -> None:
        self._attr_device_class = try_parse_enum(SensorDeviceClass, device_class)


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
        disabled: Mapping[str, str],
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
        self.disabled = disabled


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


def _disabled(hass: HomeAssistant, entity_id: str) -> dict[str, str]:
    """The tracked pururu entity, unique ID -> entity ID, when it is disabled: the goal isn't created then.

    The entry is reloaded when it is disabled (async_step's targets, pururu's
    registry listener) and when it is enabled again (HA's own).
    """
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or not entry.disabled:
        return {}
    return {entry.unique_id: entity_id}


def build(
    hass: HomeAssistant,
    device: Device,
    config: dict[str, Any],
    inputs: Mapping[str, str],
) -> list[PururuEntity]:
    """Each goal's target and done, both following its pururu tracked_by.

    A goal tracked by what doesn't accumulate, its state class known (Home
    Assistant's entity, or the plug an energy mirror shows), is logged and
    not created; one not known yet is: done waits for its first reading. A
    goal tracked by a disabled pururu entity isn't created either (creatable).
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
            disabled = {}
        else:
            # A pururu entity, of this device or another: by its current ID
            follows = (ref.text,)
            source = inputs[ref.text]
            disabled = _disabled(hass, source)
        entities.append(
            GoalTarget(
                device,
                goal["target"],
                source,
                item=item,
                follows=follows,
                disabled=disabled,
            )
        )
        entities.append(
            GoalDone(
                device, source, goal, item=item, follows=follows, disabled=disabled
            )
        )
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


async def async_step(
    hass: HomeAssistant, entry: PururuConfigEntry, built: Built, targets: set[str]
) -> None:
    """Adds what each goal tracks, a pururu entity, to `targets`, the goal created or not.

    Disabling it rebuilds the entry, which drops the goal; HA reloads the
    entry itself once it is enabled again.
    """
    for key, device in built.house.get(CONF_DEVICES, {}).items():
        for _, ref in _refers(device.get(CONF_GOALS, {})):
            if (target := find(built.index, key, ref)) is not None:
                targets.add(target.current_entity_id(hass))
