"""Reactions: what a device listens to, as Home Assistant automations pururu generates.

A reaction is one source (an entity of a device, a real entity, a time of day,
the sun) and, for an entity, a condition. Each becomes an automation in
pururu/automations/reactions.yaml, whose folder configuration.yaml includes
(generated.py). It starts one of its device's programs (then), tells its
message (message, notify), or does nothing: it fires, and its trace shows when
and why. An at or sun reaction can retry: its automation triggers again, each
try skipped once the occurrence ran. Each reaction's triggers are counted:
sensors of its device (STATISTICS).
"""

from collections.abc import Collection, Hashable, Iterator, Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
import logging
from typing import Any, override

import voluptuous as vol

from homeassistant.components.sensor import RestoreSensor, SensorStateClass
from homeassistant.const import CONF_NAME, STATE_OFF, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er

from ..const import (
    CONF_AUTOMATIONS,
    CONF_DEVICES,
    CONF_MESSAGE,
    CONF_NOTIFY,
    CONF_PROGRAMS,
    CONF_REACTIONS,
    ENTITY_PREFIX,
)
from ..core import generated, messages, vocabulary
from ..core.entity import PururuEntity
from ..core.feature import (
    TEXT,
    Device,
    Feature,
    Item,
    finite_float,
    qualified,
    state_text,
)
from ..core.generated import Kind, Planned, period
from ..core.resolve import Index, Ref, Target, find
from ..core.roles import Generates, Items
from ..features.cycle.statistics import PERIOD_LIST, PERIODS, Meter
from . import programs

_LOGGER = logging.getLogger(__name__)

# The namespace of every reaction's automation ID
NAMESPACE = "reaction"
SOURCES = ("when", "entity", "at", "sun")
# HA's event when an automation runs (its conditions passed), naming it in its
# data. A string, not automation's constant: pururu doesn't depend on it
AUTOMATION_TRIGGERED = "automation_triggered"
PER_REACTION: dict[str, Platform] = {
    "triggered_total": Platform.SENSOR,
    **{f"triggered_{period}": Platform.SENSOR for period in PERIODS},
}
# Keys that only a reaction on an entity's state takes
STATE_KEYS = ("to", "from", "above", "below", "for")
# How late a reaction's last try may be, after its occurrence: a chain never
# reaches the next day's occurrence, and a sun event drifts a few minutes a day
RETRY_LIMIT = timedelta(hours=12)
# Added to a try's window: the occurrence's run is recorded a moment after it
SLACK = timedelta(minutes=1)
# Whether a try may run: the occurrence always, a try without a run in its
# window. as_timestamp takes last_triggered as HA restores it (a datetime) and
# as none (never run: 0); as_datetime refuses a datetime
RAN = "{{{{ since is not defined or as_timestamp({last}, 0) < now().timestamp() - since }}}}"


def _whole_seconds(value: timedelta) -> timedelta:
    """A try's time is HH:MM:SS: HA's time trigger refuses a fraction of a second."""
    if value.microseconds:
        raise vol.Invalid("a reaction's retry every must be whole seconds")
    return value


def _whole_number(value: Any) -> int:
    """An int as YAML writes it: 2.9 isn't truncated to 2, true isn't 1."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise vol.Invalid("a reaction's retry times must be a whole number")
    return value


RETRY = vol.Schema(
    {
        vol.Required("times"): vol.All(_whole_number, vol.Range(min=1)),
        vol.Required("every"): vol.All(
            cv.positive_time_period,
            vol.Range(min=timedelta(minutes=1)),
            _whole_seconds,
        ),
    }
)
KIND = Kind(
    domain="automation",
    folder="pururu/automations",
    file="pururu/automations/reactions.yaml",
    merge="list",
    issue="automations_not_included",
    data_key=CONF_AUTOMATIONS,
    one="an automation",
    plural="automations",
    source="reactions",
)


def _retry_consistent(reaction: dict[str, Any], source: str) -> None:
    """A retry only on a time or the sun, its tries within RETRY_LIMIT."""
    if "retry" not in reaction:
        return
    if source not in ("at", "sun"):
        raise vol.Invalid("a reaction's retry goes with at or sun")
    retry = reaction["retry"]
    if retry["times"] * retry["every"] > RETRY_LIMIT:
        raise vol.Invalid("a reaction's retries must end within 12 hours")


def _consistent(reaction: dict[str, Any]) -> dict[str, Any]:
    """One source, and the keys that go with it."""
    sources = [key for key in SOURCES if key in reaction]
    if len(sources) != 1:
        raise vol.Invalid("a reaction needs one source: when, entity, at or sun")
    if CONF_NOTIFY in reaction and CONF_MESSAGE not in reaction:
        raise vol.Invalid("a reaction's notify goes with message")
    if "device" in reaction and "when" not in reaction:
        raise vol.Invalid("a reaction's device goes with when")
    if "offset" in reaction and "sun" not in reaction:
        raise vol.Invalid("a reaction's offset goes with sun")
    _retry_consistent(reaction, sources[0])
    if sources[0] in ("at", "sun"):
        if any(key in reaction for key in STATE_KEYS):
            raise vol.Invalid(
                "a reaction on at or sun takes no to, from, above, below or for"
            )
        return reaction
    _state_consistent(reaction)
    return reaction


def _state_consistent(reaction: dict[str, Any]) -> None:
    """A reaction on an entity's state: to, or above and/or below, and what goes with them."""
    if ("to" in reaction) == ("above" in reaction or "below" in reaction):
        raise vol.Invalid(
            "a reaction on a state needs to, or above and/or below, not both"
        )
    if "from" in reaction and "to" not in reaction:
        raise vol.Invalid("a reaction's from goes with to")
    if (
        "above" in reaction
        and "below" in reaction
        and reaction["above"] >= reaction["below"]
    ):
        raise vol.Invalid("a reaction's above must be lower than its below")


REACTION = vol.All(
    vol.Schema(
        {
            # A blank name would show the automation as its device's name alone
            vol.Required(CONF_NAME): TEXT,
            vol.Optional("when"): cv.slug,
            vol.Optional("device"): cv.slug,
            vol.Optional("entity"): cv.entity_id,
            vol.Optional("to"): state_text,
            vol.Optional("from"): state_text,
            vol.Optional("above"): finite_float,
            vol.Optional("below"): finite_float,
            vol.Optional("for"): cv.positive_time_period,
            vol.Optional("at"): cv.time,
            vol.Optional("sun"): vol.In(("sunrise", "sunset")),
            vol.Optional("offset"): cv.time_period,
            # More tries of an at or sun occurrence, each skipped once it ran
            vol.Optional("retry"): RETRY,
            # A program of this device, started when the reaction fires
            vol.Optional("then"): cv.slug,
            # Told when the reaction fires, to its own notify or config's
            vol.Optional(CONF_MESSAGE): TEXT,
            vol.Optional(CONF_NOTIFY): messages.TARGETS,
            vol.Optional("statistics", default={}): vol.Schema(
                {vol.Optional("triggered", default=[]): PERIOD_LIST}
            ),
        }
    ),
    _consistent,
)
# A schema of its own: ALLOW_EXTRA would let a key that isn't a slug through
SCHEMA = vol.All(vol.Schema({cv.slug: REACTION}), vol.Length(min=1))


def automation_id(device_key: str, reaction_key: str) -> str:
    """The automation's ID, and the object ID of its entity ID: the pururu pattern."""
    return f"{ENTITY_PREFIX}_{device_key}_{qualified(NAMESPACE, reaction_key)}"


def _occurrence(reaction: Mapping[str, Any], later: timedelta) -> dict[str, Any]:
    """The trigger of an at or sun reaction, `later` after its time."""
    if "at" in reaction:
        at = datetime.combine(date.min, reaction["at"]) + later
        return {"trigger": "time", "at": at.time().isoformat()}
    sun: dict[str, Any] = {"trigger": "sun", "event": reaction["sun"]}
    if "offset" in reaction or later:
        sun["offset"] = period(reaction.get("offset", timedelta(0)) + later)
    return sun


def _retries(reaction: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Each try k, k times `every` after the occurrence, with its window in seconds."""
    if "retry" not in reaction:
        return []
    every: timedelta = reaction["retry"]["every"]
    return [
        {
            **_occurrence(reaction, k * every),
            "id": f"retry_{k}",
            "variables": {"since": int((k * every + SLACK).total_seconds())},
        }
        for k in range(1, reaction["retry"]["times"] + 1)
    ]


def triggers(
    reaction: Mapping[str, Any], entity_id: str | None
) -> list[dict[str, Any]]:
    """The HA triggers of a validated reaction; `entity_id` is the entity it watches.

    An at or sun reaction with retry also triggers at each try (retry_<k>);
    otherwise it's the vocabulary's state or numeric_state trigger.
    """
    if "at" in reaction or "sun" in reaction:
        return [_occurrence(reaction, timedelta(0)), *_retries(reaction)]
    return [vocabulary.trigger(reaction, entity_id)]


def conditions(reaction: Mapping[str, Any], script: str | None) -> list[dict[str, Any]]:
    """With retry, a try runs only if nothing ran since the occurrence; none without.

    What ran: the program started (`script`, its current entity ID), from here
    or anywhere; without a program, the automation fired (`this`, its state
    before this run). HA restores both at a restart. A condition, not an
    action: a skipped try isn't a trigger.
    """
    if "retry" not in reaction:
        return []
    last = (
        "this.attributes.last_triggered"
        if script is None
        else f"state_attr('{script}', 'last_triggered')"
    )
    return [{"condition": "template", "value_template": RAN.format(last=last)}]


def actions(script: str | None) -> list[dict[str, Any]]:
    """Start the program's script unless it runs; nothing without one.

    The check is an action, not a condition: HA counts a trigger only once its
    conditions pass, and a trigger skipped because the program runs still is one.
    """
    if script is None:
        return []
    return [
        {
            "if": [{"condition": "state", "entity_id": script, "state": STATE_OFF}],
            "then": [{"action": "script.turn_on", "target": {"entity_id": script}}],
        }
    ]


def told(
    reaction: Mapping[str, Any],
    device_name: str,
    notify: Sequence[str],
    script: str | None,
) -> list[dict[str, Any]]:
    """Tell the reaction's message to `notify`; nothing without one.

    Once per occurrence: with retry and a program, a try runs while the program
    hasn't started, even when the occurrence ran and told it (the program was
    busy). So a try tells it only if the automation hasn't run since the
    occurrence (`this`: its state before this run), as when HA was down then.
    """
    if CONF_MESSAGE not in reaction:
        return []
    actions = messages.actions(notify, device_name, reaction[CONF_MESSAGE])
    if "retry" not in reaction or script is None:
        return actions
    ran = RAN.format(last="this.attributes.last_triggered")
    return [
        {
            "if": [{"condition": "template", "value_template": ran}],
            "then": actions,
        }
    ]


def automation(
    device_key: str,
    device_name: str,
    reaction_key: str,
    reaction: Mapping[str, Any],
    entity_id: str | None,
    script: str | None = None,
    notify: Sequence[str] = (),
) -> dict[str, Any]:
    """The automation of a reaction; `script` is the current entity ID of its program's.

    `notify` is where its message goes, its own or config's; the program starts
    first: a notify action that doesn't exist fails the run, whatever
    continue_on_error says.
    """
    written: dict[str, Any] = {
        "id": automation_id(device_key, reaction_key),
        "alias": f"{device_name} {reaction[CONF_NAME]}",
        "description": f"pururu: {device_key}, {reaction_key}",
        "triggers": triggers(reaction, entity_id),
    }
    if checks := conditions(reaction, script):
        written["conditions"] = checks
    written["actions"] = [
        *actions(script),
        *told(reaction, device_name, notify, script),
    ]
    return written


class TriggersTotal(PururuEntity, RestoreSensor):
    """A reaction's triggers, all time, whether its program started or not."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, device: Device, automation: str | None, *, item: Item) -> None:
        """Count the runs of `automation`, the entity of `item`'s reaction; None counts none."""
        self._identify(device, Platform.SENSOR, "triggered_total", item=item)
        self._automation = automation
        self._triggers = 0

    @property
    @override
    def native_value(self) -> int:
        """The count."""
        return self._triggers

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the count, then count."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and isinstance(last.native_value, int | float | Decimal):
            self._triggers = int(last.native_value)
        if self._automation is not None:
            self.async_on_remove(
                self.hass.bus.async_listen(
                    AUTOMATION_TRIGGERED, self._count, event_filter=self._of_it
                )
            )

    @callback
    def _of_it(self, data: Mapping[str, Any]) -> bool:
        return bool(data.get("entity_id") == self._automation)

    @callback
    def _count(self, _event: Event[Mapping[str, Any]]) -> None:
        self._triggers += 1
        self.async_write_ha_state()


def _items(config: Mapping[str, Any]) -> list[Item]:
    return [
        Item(slug=key, name=reaction[CONF_NAME]) for key, reaction in config.items()
    ]


def build(
    hass: HomeAssistant,
    device: Device,
    config: dict[str, Any],
    inputs: Mapping[str, str],
) -> list[PururuEntity]:
    """Each reaction's trigger count, and the meters asked for.

    `inputs` are the entity IDs of the automations the entry generates, by ID:
    a reaction whose automation ID someone else holds counts nothing.
    """
    entities: list[PururuEntity] = []
    for item in _items(config):
        automation = inputs.get(automation_id(device.key, item.slug))
        entities.append(TriggersTotal(device, automation, item=item))
        source = device.current_entity_id(
            hass, Platform.SENSOR, item.key("triggered_total")
        )
        entities.extend(
            Meter(
                device,
                f"triggered_{period}",
                "triggered_total",
                source,
                period,
                item=item,
            )
            for period in config[item.slug]["statistics"]["triggered"]
        )
    return entities


# Not a device's feature: its reactions' statistics, built as a Feature's entities
STATISTICS = Feature(
    schema=SCHEMA,
    entity_keys={},
    build=build,
    example={"night": {"name": "Night", "at": "22:00"}},
    namespace=NAMESPACE,
    roles=(
        Items(PER_REACTION, _items),
        Generates(
            "reaction",
            lambda key, config: ((KIND.domain, automation_id(key, r)) for r in config),
        ),
    ),
)


def check(house: Mapping[str, Any], index: Index, *_: Any) -> Iterator[vol.Invalid]:
    """Refuse a reaction's `when`, `device` or `then` it can't have (a schema check).

    `when` without `device` names an entity key of the device, and never one of
    the reaction's own statistics; `device` names a device; `then` one of the
    device's programs.
    """
    devices = house[CONF_DEVICES]
    for key, device in devices.items():
        for reaction_key, reaction in device.get(CONF_REACTIONS, {}).items():
            if (
                refused := _refused(index, devices, key, reaction_key, reaction)
            ) is not None:
                yield refused


def _own_statistic(target: Target | None, key: str, reaction_key: str) -> bool:
    """Whether it counts this reaction: watching it, the reaction would feed itself."""
    return (
        target is not None
        and target.device.key == key
        and target.builder == CONF_REACTIONS
        and target.item == reaction_key
    )


def _refused(
    index: Index,
    devices: Mapping[str, Any],
    key: str,
    reaction_key: str,
    reaction: Mapping[str, Any],
) -> vol.Invalid | None:
    """Why this reaction can't be, the first reason; None when it can."""
    path: list[Hashable] = [CONF_DEVICES, key, CONF_REACTIONS, reaction_key]
    when, other = reaction.get("when"), reaction.get("device")
    target = None if when is None else find(index, key, Ref(other, when))
    if other is None and _own_statistic(target, key, reaction_key):
        return vol.Invalid(
            f"reactions: {reaction_key}: {when} is its own statistic", path=path
        )
    then = reaction.get("then")
    if then is not None and then not in devices[key].get(CONF_PROGRAMS, {}):
        return vol.Invalid(
            f"reactions: {reaction_key}: {then} is not a program of this device",
            path=path,
        )
    if when is None:
        return None
    if other is None:
        if target is None:
            return vol.Invalid(
                f"reactions: {reaction_key}: {when} is not an entity key of this device",
                path=path,
            )
        return None
    where = f"device {key}: reactions: {reaction_key}"
    if other not in devices:
        return vol.Invalid(f"{where}: device {other} is not in devices", path=path)
    if _own_statistic(target, key, reaction_key):
        return vol.Invalid(f"{where}: {when} is its own statistic", path=path)
    if target is None:
        return vol.Invalid(
            f"{where}: {when} is not an entity key of device {other}", path=path
        )
    return None


def plan(
    hass: HomeAssistant,
    devices: Mapping[str, Any],
    index: Index,
    created: Collection[str],
    scripts: Collection[str],
    held_scripts: Collection[str],
    notify: Sequence[str],
) -> Planned:
    """An automation per reaction of every device; one that can't work is logged.

    One watching an entity not created, or starting a program whose script
    isn't generated (`scripts`: the IDs generated), isn't generated; held with
    its program when that is. `notify` is config's: where a message without its
    own goes.
    """
    registry = er.async_get(hass)
    automations: list[generated.Item] = []
    held: set[str] = set()
    for key, config in devices.items():
        for reaction_key, reaction in config.get(CONF_REACTIONS, {}).items():
            unique_id = automation_id(key, reaction_key)
            watched, entity_id = _watched(
                hass, index, key, unique_id, reaction, created
            )
            if not watched:
                continue
            startable, started = _started(registry, key, unique_id, reaction, scripts)
            if not startable:
                if programs.script_id(key, reaction["then"]) in held_scripts:
                    held.add(unique_id)
                continue
            automations.append(
                generated.Item(
                    unique_id=unique_id,
                    config=automation(
                        key,
                        config[CONF_NAME],
                        reaction_key,
                        reaction,
                        entity_id,
                        started,
                        reaction.get(CONF_NOTIFY, notify),
                    ),
                )
            )
    return Planned(automations, frozenset(held))


def _watched(
    hass: HomeAssistant,
    index: Index,
    key: str,
    unique_id: str,
    reaction: Mapping[str, Any],
    created: Collection[str],
) -> tuple[bool, str | None]:
    """Whether the reaction can watch what it names, and the entity ID it watches.

    A pururu entity not created can't be, logged; `at` and `sun` watch none.
    """
    if (when := reaction.get("when")) is None:
        return True, reaction.get("entity")
    target = find(index, key, Ref(reaction.get("device"), when))
    assert target is not None  # the schema checked it (check)
    if target.unique_id not in created:
        _LOGGER.error(
            "automation.%s follows %s, which is not created; not generating it",
            unique_id,
            target.entity_id(),
        )
        return False, None
    return True, target.current_entity_id(hass)


def _started(
    registry: er.EntityRegistry,
    key: str,
    unique_id: str,
    reaction: Mapping[str, Any],
    scripts: Collection[str],
) -> tuple[bool, str | None]:
    """Whether the reaction can start its program, and its script's current entity ID.

    A script not generated can't be started, logged; without `then`, none is.
    """
    if (then := reaction.get("then")) is None:
        return True, None
    script = programs.script_id(key, then)
    if script not in scripts:
        _LOGGER.error(
            "automation.%s runs script.%s, which is not generated; not generating it",
            unique_id,
            script,
        )
        return False, None
    # Registered by the scripts' sync
    return True, registry.async_get_entity_id(
        programs.KIND.domain, programs.KIND.domain, script
    )
