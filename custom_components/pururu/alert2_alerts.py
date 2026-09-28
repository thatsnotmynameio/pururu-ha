"""Alert2's alerts: one for each pururu alert with notify, which Alert2 delivers.

pururu writes them to pururu/alert2/alerts.yaml; the user's alert2: block
includes its folder as its alerts. Alert2 renders these fields as templates:
what the user wrote is kept as text.
"""

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import files
from .const import DOMAIN, ENTITY_PREFIX

# Alert2 (HACS) delivers what an alert's notify says
ALERT2 = "alert2"
# Relative to HA's configuration folder, as the alert2: block's include names it
FOLDER = "pururu/alert2"
FILE = f"{FOLDER}/alerts.yaml"
# A folder, not the file: a missing folder loads as no alerts
INCLUDE = f"alerts: !include_dir_merge_list {FOLDER}"
# How the log names what the file holds
WHAT = "The Alert2 alerts"


def _text(text: str) -> str:
    """`text` as Alert2 shows it: every template delimiter starts with {."""
    return f"{{% raw %}}{text}{{% endraw %}}" if "{" in text else text


def alert(
    object_id: str,
    entity_id: str,
    friendly_name: str,
    priority: str,
    notify: Mapping[str, str],
) -> dict[str, Any]:
    """The Alert2 alert of the pururu alert `object_id`, whose entity ID is now `entity_id`.

    Named after the object ID, so alert2.pururu_<object ID without pururu_>
    whatever the user renamed; on and off conditions, so an unavailable pururu
    alert (during a reload) leaves the Alert2 one as it is.
    """
    return {
        "domain": DOMAIN,
        "name": object_id.removeprefix(f"{ENTITY_PREFIX}_"),
        "friendly_name": _text(friendly_name),
        "condition_on": f"{{{{ is_state('{entity_id}', 'on') }}}}",
        "condition_off": f"{{{{ is_state('{entity_id}', 'off') }}}}",
        "priority": priority,
        "message": _text(notify["message"]),
        "done_message": _text(notify["done_message"]),
    }


async def async_sync(
    hass: HomeAssistant, entry: ConfigEntry, alerts: list[dict[str, Any]]
) -> None:
    """Write the Alert2 alerts."""
    await files.async_write(hass, FILE, WHAT, alerts)


async def async_remove(hass: HomeAssistant) -> None:
    """Write no alerts: an empty file, still valid for the include."""
    await files.async_write(hass, FILE, WHAT, [])
