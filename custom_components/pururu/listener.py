"""The registry listener: build the entry again when what it built is renamed, or a target disabled."""

from collections.abc import Mapping
from typing import Any, Literal

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .runtime import PururuConfigEntry


def async_listen(
    hass: HomeAssistant,
    entry: PururuConfigEntry,
    watched: set[tuple[str, str]],
    targets: set[str],
) -> None:
    """Build the entry again when one of its entities or generated items is renamed, or a target disabled."""
    registry = er.async_get(hass)
    # Whether a reload is already scheduled: a burst of disables reloads once
    reloading = False

    @callback
    def changed(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        """One of the entry's entities or generated items got a new ID, or a program's target was disabled: build again.

        A rename is followed: of a pururu entity, or of a script or automation
        it generates (a reaction's action and the statistics would watch an ID
        that no longer is). A program acting on an entity just disabled is dropped (`_acted_on`),
        and a light or alert the alert lights follow is left out, once
        for a burst of them: HA reloads the entry itself once an entity is
        enabled again, but not when one is disabled (config_entries.py leaves
        that to the entity, which merely clears its own state). No other
        disable or enable concerns what is built here (`rebuild_for`).
        """
        nonlocal reloading
        data = event.data
        if data["action"] != "update":
            return
        registered = registry.async_get(data["entity_id"])
        if registered is None:
            return
        why = rebuild_for(entry.entry_id, registered, data["changes"], watched, targets)
        if why is None or (why == "disabled" and reloading):
            return
        reloading = True
        hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, changed)
    )


def rebuild_for(
    entry_id: str,
    registered: er.RegistryEntry,
    changes: Mapping[str, Any],
    watched: set[tuple[str, str]],
    targets: set[str],
) -> Literal["renamed", "disabled"] | None:
    """Why this registry update needs the entry built again, if it does.

    Renamed: one of the entry's entities, or a script or automation it
    generates (a reaction starts one, the statistics watch them).
    Disabled: an entity a generated script acts on, or a light or an alert the
    alert lights follow, just now (the old value
    of `disabled_by` is None).
    """
    ours = registered.config_entry_id == entry_id
    if "entity_id" in changes:
        generated_item = (registered.platform, registered.unique_id) in watched
        return "renamed" if ours or generated_item else None
    if (
        ours
        and "disabled_by" in changes
        and changes["disabled_by"] is None
        and registered.disabled
        and registered.entity_id in targets
    ):
        return "disabled"
    return None
