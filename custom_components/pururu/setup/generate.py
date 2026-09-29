"""The scripts and automations the entry generates: what each holds, and what it watches."""

from collections.abc import Collection, Mapping, Sequence
import logging
from typing import Any, Literal

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ..const import (
    CONF_AREA,
    CONF_CONFIG,
    CONF_DEVICES,
    CONF_NOTIFY,
    CONF_PROGRAMS,
    CONF_REACTIONS,
)
from ..core import generated
from ..core.resolve import Target
from ..core.runtime import Built, PururuConfigEntry
from ..device_keys import notifications, programs, reactions
from . import catalogue

_LOGGER = logging.getLogger(__name__)


def owned(
    hass: HomeAssistant, entry: PururuConfigEntry, devices: dict[str, dict[str, Any]]
) -> dict[str, str]:
    """The current entity IDs of the scripts and automations the entry generates, by ID."""
    items = watched_items(devices)
    return {
        unique_id: entity_id
        for kind in (programs.KIND, reactions.KIND)
        for unique_id, entity_id in generated.owned(
            hass,
            entry,
            kind,
            (unique_id for domain, unique_id in items if domain == kind.domain),
        ).items()
    }


def watched_items(devices: dict[str, dict[str, Any]]) -> set[tuple[str, str]]:
    """(domain, ID) of every script and automation the entry generates.

    Renamed, what watches it follows: a reaction's action, the statistics.
    """
    return {
        *(
            (programs.KIND.domain, programs.script_id(key, program))
            for key, config in devices.items()
            for program in config.get(CONF_PROGRAMS, {})
        ),
        *(
            (reactions.KIND.domain, reactions.automation_id(key, reaction))
            for key, config in devices.items()
            for reaction in config.get(CONF_REACTIONS, {})
        ),
    }


def scripts(
    hass: HomeAssistant, devices: dict[str, dict[str, Any]], created: set[str]
) -> tuple[list[generated.Item], set[str], set[str]]:
    """A script per program of every device, in the device's area; one that can't act is logged.

    Also the IDs of the scripts held while an entity they act on is disabled
    (their registry entries stay, as the user set them), and the entity IDs the
    generated scripts act on.
    """
    registry = er.async_get(hass)
    scripts: list[generated.Item] = []
    held: set[str] = set()
    targets: set[str] = set()
    for key, config in devices.items():
        found = catalogue.targets(key, config)
        for program_key, program in config.get(CONF_PROGRAMS, {}).items():
            script_id = programs.script_id(key, program_key)
            entity_ids = _acted_on(hass, registry, found, script_id, program, created)
            if entity_ids == "held":
                held.add(script_id)
                continue
            if entity_ids is None:
                continue
            targets.update(entity_ids.values())
            scripts.append(
                generated.Item(
                    unique_id=script_id,
                    config=programs.script(
                        key, config[CONF_NAME], program_key, program, entity_ids
                    ),
                    area=config.get(CONF_AREA),
                )
            )
    return scripts, held, targets


def _acted_on(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    found: Mapping[str, Target],
    script_id: str,
    program: dict[str, Any],
    created: set[str],
) -> dict[str, str] | Literal["held"] | None:
    """Each entity key the program acts on -> its current entity ID.

    None, logged, when one isn't created: the program is dropped. "held",
    logged, when all are created but one is disabled: the program is held, to
    come back as the user set it once the entity is enabled again. The entry is
    reloaded when an entity a generated script acts on is disabled (pururu's
    registry listener, `changed`), and when a disabled one is enabled again
    (HA's own).
    """
    entity_ids: dict[str, str] = {}
    for _, key in programs.targets(program):
        target = found[key]
        entity_id = target.current_entity_id(hass)
        if target.unique_id not in created:
            _LOGGER.error(
                "script.%s follows %s, which is not created; not generating it",
                script_id,
                entity_id,
            )
            return None
        entity_ids[key] = entity_id
    for entity_id in entity_ids.values():
        if (registered := registry.async_get(entity_id)) is not None and (
            registered.disabled
        ):
            _LOGGER.error(
                "script.%s acts on %s, which is disabled; not generating it",
                script_id,
                entity_id,
            )
            return "held"
    return entity_ids


def automations(
    hass: HomeAssistant,
    devices: dict[str, dict[str, Any]],
    created: set[str],
    scripts: Collection[str],
    held_scripts: Collection[str],
    notify: Sequence[str],
) -> tuple[list[generated.Item], set[str]]:
    """An automation per reaction of every device; one that can't work is logged.

    One watching an entity not created, or starting a program whose script
    isn't generated, isn't generated. Also the IDs of those held with their
    program. `notify` is config's: where a message without its own goes.
    """
    registry = er.async_get(hass)
    automations: list[generated.Item] = []
    held: set[str] = set()
    for key, config in devices.items():
        for reaction_key, reaction in config.get(CONF_REACTIONS, {}).items():
            automation_id = reactions.automation_id(key, reaction_key)
            watched, entity_id = _watched(
                hass, devices, key, automation_id, reaction, created
            )
            if not watched:
                continue
            startable, script = _started(
                registry, key, automation_id, reaction, scripts
            )
            if not startable:
                if programs.script_id(key, reaction["then"]) in held_scripts:
                    held.add(automation_id)
                continue
            automations.append(
                generated.Item(
                    unique_id=automation_id,
                    config=reactions.automation(
                        key,
                        config[CONF_NAME],
                        reaction_key,
                        reaction,
                        entity_id,
                        script,
                        reaction.get(CONF_NOTIFY, notify),
                    ),
                )
            )
    return automations, held


def _watched(
    hass: HomeAssistant,
    devices: dict[str, dict[str, Any]],
    key: str,
    automation_id: str,
    reaction: dict[str, Any],
    created: set[str],
) -> tuple[bool, str | None]:
    """Whether the reaction can watch what it names, and the entity ID it watches.

    A pururu entity not created can't be, logged; `at` and `sun` watch none.
    """
    if (when := reaction.get("when")) is None:
        return True, reaction.get("entity")
    owner_key = reaction.get("device", key)
    target = catalogue.targets(owner_key, devices[owner_key])[when]
    if target.unique_id not in created:
        _LOGGER.error(
            "automation.%s follows %s, which is not created; not generating it",
            automation_id,
            target.entity_id(),
        )
        return False, None
    return True, target.current_entity_id(hass)


def _started(
    registry: er.EntityRegistry,
    key: str,
    automation_id: str,
    reaction: dict[str, Any],
    scripts: Collection[str],
) -> tuple[bool, str | None]:
    """Whether the reaction can start its program, and its script's current entity ID.

    A script not generated can't be started, logged; without `then`, none is.
    """
    if (then := reaction.get("then")) is None:
        return True, None
    script_id = programs.script_id(key, then)
    if script_id not in scripts:
        _LOGGER.error(
            "automation.%s runs script.%s, which is not generated; not generating it",
            automation_id,
            script_id,
        )
        return False, None
    # Registered by the scripts' sync
    return True, registry.async_get_entity_id(
        programs.KIND.domain, programs.KIND.domain, script_id
    )


async def async_step(
    hass: HomeAssistant, entry: PururuConfigEntry, built: Built, targets: set[str]
) -> None:
    """The programs' scripts, then the reactions' and the ready-made notifications' automations.

    The scripts come first: a reaction starts one. Adds the entity IDs the
    generated scripts act on to `targets`: disabling one rebuilds the entry.
    """
    devices = built.house.get(CONF_DEVICES, {})
    created = set(built.created)
    items, held, acted_on = scripts(hass, devices, created)
    targets.update(acted_on)
    generated_scripts = await generated.async_sync(
        hass, entry, programs.KIND, items, held
    )
    # Where a message goes without a notify of its own
    notify = built.house.get(CONF_CONFIG, {}).get(CONF_NOTIFY, [])
    reactions_items, held_automations = automations(
        hass, devices, created, generated_scripts, held, notify
    )
    await generated.async_sync(
        hass, entry, reactions.KIND, reactions_items, held_automations
    )
    await generated.async_sync(
        hass,
        entry,
        notifications.KIND,
        notifications.items(hass, devices, created, built.texts, notify),
    )
