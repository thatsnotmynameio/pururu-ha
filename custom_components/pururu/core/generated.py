"""What pururu writes for Home Assistant to run: automations and scripts, a file per kind.

Each kind is a file in a folder that configuration.yaml includes once, under
HA's own domain: HA loads it, runs it and shows it (traces, on/off, its list).
pururu gives each item the pururu entity ID, drops what the configuration no
longer has once HA no longer runs it, holds what it can't generate for now
(its registry entry and the user's settings stay), and raises a Repairs issue
while HA doesn't load what the file holds.
"""

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_RESTORED, EVENT_STATE_CHANGED, SERVICE_RELOAD
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HassJob,
    HomeAssistant,
    callback,
    split_entity_id,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.start import async_at_started

from ..const import DOMAIN
from . import files
from .entity import other_holder

_LOGGER = logging.getLogger(__name__)

# Quiet time after the domain's last state change before the include is checked:
# a reload adds its items one by one, so a check in between finds some missing
QUIET = timedelta(seconds=1)


@dataclass(frozen=True, kw_only=True)
class Kind:
    """An HA domain pururu generates items of: where they go, how HA includes them."""

    # HA's domain, and the platform of its items' registry entries
    domain: str
    # Relative to HA's configuration folder, as configuration.yaml's include names them
    folder: str
    file: str
    # How the include merges the folder, and so how the file is dumped: "list"
    # (automations, each with its id) or "named" (scripts, object ID -> script)
    merge: str
    # The Repairs issue while an item isn't loaded, and its translation key
    issue: str
    # The key of the entry's data holding the IDs of the items it tracks
    data_key: str
    # Words of the log messages: "an automation", "automations", "reactions"
    one: str
    plural: str
    source: str

    @property
    def include(self) -> str:
        """configuration.yaml's line for the folder.

        A folder, not the file: a missing folder loads as nothing, while a plain
        include of a missing file stops HA from loading its configuration.
        """
        return f"{self.domain} pururu: !include_dir_merge_{self.merge} {self.folder}"


@dataclass(frozen=True, kw_only=True)
class Item:
    """A generated item: its ID (its entity ID's object ID too), its HA config, its area."""

    unique_id: str
    config: Mapping[str, Any]
    # The area its registry entry goes in; None leaves it where it is
    area: str | None = None


@dataclass(frozen=True)
class Planned:
    """What a kind's plan() gives: the items for its file, the IDs held, the entity IDs they act on.

    A held item is kept out of the file while an entity it needs is disabled;
    its registry entry and tracked ID stay. Disabling a target rebuilds the entry.
    """

    items: list[Item]
    held: frozenset[str] = frozenset()
    targets: frozenset[str] = frozenset()


def _holder(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    kind: Kind,
    unique_id: str,
    managed: Collection[str],
) -> str | None:
    """Who else holds <domain>.<ID>, if anyone: None when it is free, or already this item's.

    An item with this ID is this one only if the entry manages it: else it is
    someone's own, which keeps its ID and what it does.
    """
    entity_id = f"{kind.domain}.{unique_id}"
    if (
        same := registry.async_get_entity_id(kind.domain, kind.domain, unique_id)
    ) is not None:
        return None if unique_id in managed else f"{same}, {kind.one} with the same ID"
    return other_holder(hass, registry, entity_id)


def _free(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    kind: Kind,
    unique_id: str,
    managed: Collection[str],
) -> bool:
    """Whether <domain>.<ID> is free, or already this item's; the holder logged."""
    if (holder := _holder(hass, registry, kind, unique_id, managed)) is None:
        return True
    _LOGGER.error(
        "%s.%s is already taken by %s; not generating it",
        kind.domain,
        unique_id,
        holder,
    )
    return False


def owned(
    hass: HomeAssistant, entry: ConfigEntry, kind: Kind, unique_ids: Iterable[str]
) -> dict[str, str]:
    """The current entity ID of each of these items the entry has or will have, by ID.

    Not one someone else holds: the entry never watches what it doesn't manage.
    """
    registry = er.async_get(hass)
    managed = entry.data.get(kind.data_key, [])
    return {
        unique_id: registry.async_get_entity_id(kind.domain, kind.domain, unique_id)
        or f"{kind.domain}.{unique_id}"
        for unique_id in unique_ids
        if _holder(hass, registry, kind, unique_id, managed) is None
    }


def _register(
    hass: HomeAssistant, registry: er.EntityRegistry, kind: Kind, item: Item
) -> None:
    """Register the item's entity ID before HA loads it, so it gets the pururu one; place it.

    HA would derive an automation's from its alias. An area that isn't created
    is left out: the device's placement already logs it.
    """
    registered = registry.async_get_or_create(
        kind.domain, kind.domain, item.unique_id, suggested_object_id=item.unique_id
    )
    if (
        item.area is not None
        and registered.area_id != item.area
        and ar.async_get(hass).async_get_area(item.area) is not None
    ):
        registry.async_update_entity(registered.entity_id, area_id=item.area)


def _remove(registry: er.EntityRegistry, kind: Kind, unique_ids: Iterable[str]) -> None:
    """Remove the entity registry entries of these items, by their IDs."""
    for unique_id in unique_ids:
        entity_id = registry.async_get_entity_id(kind.domain, kind.domain, unique_id)
        if entity_id is not None:
            registry.async_remove(entity_id)


async def _async_write(
    hass: HomeAssistant, kind: Kind, items: list[Item]
) -> bool | None:
    """Write the file if it changed; whether it did, or None on failure.

    The items are dumped as the include merges them: a list (each with its id)
    or a mapping (object ID -> config). A failure is logged, never raised: the
    caller must tell "unchanged" (False) from "failed" (None), since a failed
    write must drop nothing stale.
    """
    content: list[dict[str, Any]] | dict[str, dict[str, Any]] = (
        [dict(item.config) for item in items]
        if kind.merge == "list"
        else {item.unique_id: dict(item.config) for item in items}
    )
    return await files.async_write(hass, kind.file, f"The {kind.plural}", content)


async def _async_ids_in_file(hass: HomeAssistant, kind: Kind) -> set[str]:
    """The IDs of the items the file on disk holds: after a failed write, what HA will load.

    None of them when it is missing or can't be read.
    """
    content = await files.async_read(hass, kind.file)
    if kind.merge == "list" and isinstance(content, list):
        return {
            item["id"] for item in content if isinstance(item, dict) and "id" in item
        }
    if kind.merge == "named" and isinstance(content, dict):
        return set(content)
    return set()


async def _async_reload(hass: HomeAssistant, kind: Kind) -> bool:
    """Reload HA's domain, if HA has it; whether it did. A failure is logged, never raised."""
    if kind.domain not in hass.config.components:
        return False
    try:
        await hass.services.async_call(kind.domain, SERVICE_RELOAD, blocking=True)
    except HomeAssistantError as err:
        _LOGGER.error("The %s are not reloaded: %s", kind.plural, err)
        return False
    return True


@callback
def _runs(
    hass: HomeAssistant, registry: er.EntityRegistry, kind: Kind, unique_id: str
) -> bool:
    """Whether HA runs the item: its entity has a state, and not a restored placeholder.

    One HA doesn't run but has registered gets a restored placeholder at start.
    """
    entity_id = registry.async_get_entity_id(kind.domain, kind.domain, unique_id)
    state = hass.states.get(entity_id) if entity_id is not None else None
    return state is not None and not state.attributes.get(ATTR_RESTORED)


@callback
def _missing(
    hass: HomeAssistant, registry: er.EntityRegistry, kind: Kind, ids: Iterable[str]
) -> list[str]:
    """The generated items HA doesn't run; a disabled one never runs, and isn't missing."""
    missing = []
    for unique_id in ids:
        entity_id = registry.async_get_entity_id(kind.domain, kind.domain, unique_id)
        registered = registry.async_get(entity_id) if entity_id is not None else None
        if not _runs(hass, registry, kind, unique_id) and (
            registered is None or registered.disabled_by is None
        ):
            missing.append(unique_id)
    return missing


@callback
def async_issue(
    hass: HomeAssistant,
    issue: str,
    missing: bool,
    warn: Callable[[], None],
    placeholders: dict[str, str],
) -> None:
    """Raise `issue` while something isn't included, else delete it; `warn` once while it is open.

    The warning is logged when the issue is raised: an open one is left as it
    is. One a restart restored is inactive, and is raised again.
    """
    if not missing:
        ir.async_delete_issue(hass, DOMAIN, issue)
        return
    if (found := ir.async_get(hass).async_get_issue(DOMAIN, issue)) is not None and (
        found.active
    ):
        return
    warn()
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=issue,
        translation_placeholders=placeholders,
    )


@callback
def _check_included(
    hass: HomeAssistant, registry: er.EntityRegistry, kind: Kind, ids: Iterable[str]
) -> None:
    """Raise the Repairs issue while a generated item isn't loaded, else delete it."""
    async_issue(
        hass,
        kind.issue,
        bool(_missing(hass, registry, kind, ids)),
        lambda: _LOGGER.warning(
            'The %s of pururu\'s %s are not loaded: add "%s" to configuration.yaml',
            kind.plural,
            kind.source,
            kind.include,
        ),
        {"include": kind.include, "file": kind.file},
    )


class _Checker:
    """Checks the include once a burst of the domain's state changes is over.

    A reload removes and adds its items one by one: checked in between, some
    look missing (no state yet, or a restored placeholder) and the issue would
    come and go. So each state change of the domain (a user's own reload, an
    item added or removed) postpones the check until the domain has been quiet
    for QUIET; while pururu's own reload of the domain runs, they are ignored,
    as it checks once it is done.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        registry: er.EntityRegistry,
        kind: Kind,
        checked: list[str],
    ) -> None:
        """Check these items of this kind."""
        self._hass = hass
        self._registry = registry
        self._kind = kind
        self.checked = checked
        self._job = HassJob(
            self._run, f"pururu {kind.plural} include", cancel_on_shutdown=True
        )
        self._pending: CALLBACK_TYPE | None = None
        # True while pururu's own reload of the domain runs
        self.reloading = False

    @callback
    def of_kind(self, data: EventStateChangedData) -> bool:
        """Whether the state change is of the domain, and not during pururu's reload."""
        return (
            not self.reloading
            and split_entity_id(data["entity_id"])[0] == self._kind.domain
        )

    @callback
    def schedule(self, _event: Event[EventStateChangedData]) -> None:
        """Check once the domain has been quiet for QUIET."""
        self.cancel()
        self._pending = async_call_later(self._hass, QUIET, self._job)

    @callback
    def cancel(self) -> None:
        """Drop a scheduled check."""
        if self._pending is not None:
            self._pending()
            self._pending = None

    @callback
    def check(self) -> None:
        """Check now, dropping a scheduled check."""
        self.cancel()
        _check_included(self._hass, self._registry, self._kind, self.checked)

    @callback
    def _run(self, _now: datetime) -> None:
        self._pending = None
        self.check()


async def _finish(
    hass: HomeAssistant,
    entry: ConfigEntry,
    kind: Kind,
    changed: bool,
    ids: list[str],
    held: list[str],
    stale: set[str],
    checker: _Checker,
) -> None:
    """Once HA has started: apply the file, drop what HA no longer runs, check the include.

    HA reloads when the file changed and holds items or drops some, and also
    when it doesn't run the file as written (a reload that failed, the include added since): the reload is
    retried, and so is one that didn't take a held item out. A dropped item HA
    still runs keeps its entity ID, and stays tracked, until a reload drops it;
    a held one stays tracked anyway. The reload is blocking: the include is
    checked on what it loaded, once: the state changes of the reload itself are
    ignored.
    """
    registry = er.async_get(hass)
    if (
        # A file of no items and nothing dropped loads and unloads nothing: a
        # dropped item may be disabled, not running, and still loaded
        (changed and (ids or stale))
        or _missing(hass, registry, kind, checker.checked)
        or any(_runs(hass, registry, kind, unique_id) for unique_id in stale)
        or any(_runs(hass, registry, kind, unique_id) for unique_id in held)
    ):
        checker.reloading = True
        try:
            await _async_reload(hass, kind)
        finally:
            checker.reloading = False
    running = {
        unique_id for unique_id in stale if _runs(hass, registry, kind, unique_id)
    }
    _remove(registry, kind, stale - running)
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, kind.data_key: [*ids, *held, *sorted(running)]},
    )
    checker.check()


async def async_sync(
    hass: HomeAssistant,
    entry: ConfigEntry,
    kind: Kind,
    items: list[Item],
    held: Collection[str] = (),
) -> list[str]:
    """Generate the items, keep in the entry the IDs it tracks, return those generated.

    The IDs generated are the items' whose IDs are free (`_free`) and that are
    in the file: after a failed write, only those the file on disk still holds.

    `held` are the IDs of items not generated for now (a program whose target is
    disabled): out of the file, and so out of HA, but not dropped. Their
    registry entries stay, with what the user set (disabled, entity ID, area),
    and so does their tracking, for when they are generated again. They are
    neither stale nor checked for the include.

    Each entity ID is registered first. At start, HA has already loaded the
    file; the rest waits for HA to have started, in a task the entry's unload
    waits for, so a reload never overlaps the previous one. The tracked IDs are
    the generated ones and the dropped ones still registered: their entries go
    once HA no longer runs them. After a failed write, the file is the previous
    one: only what it holds is checked for the include. Once HA has started, a
    state change of the domain (a user's own reload) checks the include again,
    once the domain is quiet (`_Checker`).
    """
    registry = er.async_get(hass)
    previous = entry.data.get(kind.data_key, [])
    kept = [
        item for item in items if _free(hass, registry, kind, item.unique_id, previous)
    ]
    for item in kept:
        _register(hass, registry, kind, item)
    ids = [item.unique_id for item in kept]
    written = await _async_write(hass, kind, kept)
    registered = {
        unique_id
        for unique_id in previous
        if unique_id not in ids
        and registry.async_get_entity_id(kind.domain, kind.domain, unique_id)
        is not None
    }
    # Only what the entry already tracks and has a registry entry: nothing else to keep
    kept_held = sorted(registered.intersection(held))
    stale = registered.difference(held)
    in_file = ids if written is not None else await _async_ids_in_file(hass, kind)
    checked = [i for i in ids if i in in_file]
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, kind.data_key: [*ids, *kept_held, *sorted(stale)]},
    )

    checker = _Checker(hass, registry, kind, checked)

    @callback
    def finish(_hass: HomeAssistant) -> None:
        entry.async_create_task(
            hass,
            _finish(hass, entry, kind, bool(written), ids, kept_held, stale, checker),
            f"pururu {kind.plural}",
            eager_start=False,
        )
        entry.async_on_unload(
            hass.bus.async_listen(
                EVENT_STATE_CHANGED, checker.schedule, event_filter=checker.of_kind
            )
        )
        entry.async_on_unload(checker.cancel)

    entry.async_on_unload(async_at_started(hass, finish))
    return checked


async def async_remove(hass: HomeAssistant, entry: ConfigEntry, kind: Kind) -> None:
    """Generate nothing: an empty file, still valid for the include.

    An item HA still runs (the file couldn't be written, or the reload failed)
    keeps its entity ID.
    """
    if await _async_write(hass, kind, []) and hass.is_running:
        await _async_reload(hass, kind)
    registry = er.async_get(hass)
    _remove(
        registry,
        kind,
        [
            unique_id
            for unique_id in entry.data.get(kind.data_key, [])
            if not _runs(hass, registry, kind, unique_id)
        ],
    )
    ir.async_delete_issue(hass, DOMAIN, kind.issue)
