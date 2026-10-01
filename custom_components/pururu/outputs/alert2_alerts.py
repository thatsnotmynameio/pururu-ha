"""Alert2's alerts: one for each pururu alert with messages, which Alert2 delivers.

pururu writes them to pururu/alert2/alerts.yaml; the user's alert2: block
includes its folder as its alerts. Alert2 renders these fields as templates:
what the user wrote is kept as text.
"""

from collections.abc import Iterable, Mapping, Sequence
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    ATTR_RESTORED,
    SERVICE_RELOAD,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.start import async_at_started
from homeassistant.util.hass_dict import HassKey

from ..aspects.problem import ProblemAlert
from ..const import ALERT2, DOMAIN, ENTITY_PREFIX
from ..core import files
from ..core.generated import async_issue
from ..core.messages import escaped
from ..core.runtime import Built, PururuConfigEntry

_LOGGER = logging.getLogger(__name__)

# Relative to HA's configuration folder, as the alert2: block's include names it
FOLDER = "pururu/alert2"
FILE = f"{FOLDER}/alerts.yaml"
# A folder, not the file: a missing folder loads as no alerts
INCLUDE = f"alerts: !include_dir_merge_list {FOLDER}"
# How the log names what the file holds
WHAT = "The Alert2 alerts"
ISSUE = "alert2_not_included"
# Set while Alert2 hasn't reloaded a file pururu wrote: it runs the alerts as
# they were, so no alert is missing, yet the next setup must reload it
DATA_PENDING: HassKey[bool] = HassKey(f"{DOMAIN}_alert2_pending")


def alert(
    object_id: str,
    entity_id: str,
    friendly_name: str,
    priority: str,
    messages: Mapping[str, str],
) -> dict[str, Any]:
    """The Alert2 alert of the pururu alert `object_id`, whose entity ID is now `entity_id`.

    Named after the object ID, so alert2.pururu_<object ID without pururu_>
    whatever the user renamed; on and off conditions, so an unavailable pururu
    alert (during a reload) leaves the Alert2 one as it is.
    """
    return {
        "domain": DOMAIN,
        "name": object_id.removeprefix(f"{ENTITY_PREFIX}_"),
        "friendly_name": escaped(friendly_name),
        "condition_on": f"{{{{ is_state('{entity_id}', 'on') }}}}",
        "condition_off": f"{{{{ is_state('{entity_id}', 'off') }}}}",
        "priority": priority,
        "message": escaped(messages["message"]),
        "done_message": escaped(messages["done_message"]),
    }


def _unique_id(name: str) -> str:
    """Alert2's unique ID of its alert `name` in pururu's domain."""
    return f"d={DOMAIN}-n={name}"


@callback
def _missing(hass: HomeAssistant, names: Iterable[str]) -> list[str]:
    """The Alert2 alerts Alert2 doesn't run; a disabled one never runs, and isn't missing.

    Found by unique ID, as the user may rename one. A restored placeholder
    (HA shows a registered alert so until Alert2 declares it) isn't running.
    """
    registry = er.async_get(hass)
    missing = []
    for name in names:
        entity_id = registry.async_get_entity_id(ALERT2, ALERT2, _unique_id(name))
        registered = registry.async_get(entity_id) if entity_id is not None else None
        if registered is not None and registered.disabled_by is not None:
            continue
        state = hass.states.get(entity_id or f"{ALERT2}.{DOMAIN}_{name}")
        if state is None or state.attributes.get(ATTR_RESTORED):
            missing.append(name)
    return missing


async def _async_reload(hass: HomeAssistant) -> bool:
    """Reload Alert2; whether it did. A failure is logged, never raised.

    Alert2 is a third party whose reload handler may raise anything: an error
    it doesn't expect is its bug, logged with the traceback that reports it.
    """
    try:
        await hass.services.async_call(ALERT2, SERVICE_RELOAD, blocking=True)
    except HomeAssistantError as err:
        _LOGGER.error("Alert2 is not reloaded: %s", err)
        return False
    except Exception:
        _LOGGER.exception("Alert2 is not reloaded")
        return False
    hass.data.pop(DATA_PENDING, None)
    return True


@callback
def _check_included(hass: HomeAssistant, names: Iterable[str]) -> None:
    """Raise the Repairs issue while Alert2 doesn't run an alert of the file, else delete it."""
    async_issue(
        hass,
        ISSUE,
        bool(_missing(hass, names)),
        lambda: _LOGGER.warning(
            "Alert2 doesn't run pururu's alerts: add \"%s\" to the alert2: block "
            "of configuration.yaml",
            INCLUDE,
        ),
        {"include": INCLUDE, "file": FILE},
    )


async def _finish(hass: HomeAssistant, names: list[str]) -> None:
    """Once HA has started: reload Alert2 if it doesn't run the file as written, check the include.

    Without Alert2 there is nothing to reload nor include: each alert with
    texts of its own logs so. A written file stays pending until a reload
    succeeds, so a failed one is retried at the next reload; it raises no
    issue, the include may be there.
    """
    if ALERT2 not in hass.config.components:
        ir.async_delete_issue(hass, DOMAIN, ISSUE)
        return
    pending = hass.data.get(DATA_PENDING, False)
    if (pending or _missing(hass, names)) and not await _async_reload(hass):
        return
    _check_included(hass, names)


@callback
def _pending(hass: HomeAssistant) -> None:
    """Alert2 must reload the file just written: until it does, the next setup reloads it."""
    hass.data[DATA_PENDING] = True


async def async_sync(
    hass: HomeAssistant, entry: ConfigEntry, alerts: list[dict[str, Any]]
) -> None:
    """Write the Alert2 alerts; once HA has started, have Alert2 run them.

    Alert2 loaded the file as it was at start; the rest waits for HA to have
    started (Alert2 may set up after pururu), in a task the entry's unload
    waits for. After a failed write the file is the previous one: nothing is
    reloaded nor checked.
    """
    written = await files.async_write(hass, FILE, WHAT, alerts)
    if written is None:
        return
    if written:
        _pending(hass)
    names = [each["name"] for each in alerts]

    @callback
    def finish(_hass: HomeAssistant) -> None:
        entry.async_create_task(
            hass, _finish(hass, names), "pururu alert2", eager_start=False
        )

    entry.async_on_unload(async_at_started(hass, finish))


async def async_remove(hass: HomeAssistant) -> None:
    """Write no alerts: an empty file, still valid for the include; Alert2 drops them.

    A reload that fails stays pending: pururu set up again reloads Alert2,
    though the empty file is then unchanged.
    """
    ir.async_delete_issue(hass, DOMAIN, ISSUE)
    if not await files.async_write(hass, FILE, WHAT, []):
        return
    _pending(hass)
    if hass.is_running and ALERT2 in hass.config.components:
        await _async_reload(hass)


def items(
    hass: HomeAssistant, built: Mapping[Platform, Sequence[Entity]]
) -> list[dict[str, Any]]:
    """An Alert2 alert per created alert with messages, hand-written or ready-made.

    Named as HA shows it: its device's name and its own, translated or not.
    """
    alerts: list[dict[str, Any]] = []
    for entity in built[Platform.BINARY_SENSOR]:
        if not isinstance(entity, ProblemAlert) or entity.messages is None:
            continue
        state = hass.states.get(entity.entity_id)
        name = state.attributes.get(ATTR_FRIENDLY_NAME) if state else None
        alerts.append(
            alert(
                str(entity.unique_id),
                entity.entity_id,
                str(name or entity.entity_id),
                entity.priority,
                entity.messages,
            )
        )
    return alerts


async def async_step(
    hass: HomeAssistant, entry: PururuConfigEntry, built: Built, targets: set[str]
) -> None:
    """Write Alert2's alerts: one per created alert with messages."""
    await async_sync(hass, entry, items(hass, built.entities))
