"""Every ID the whole house creates, pinned: a refactor that loses or renames one fails here.

`_remove_stale` deletes the registry entries of whatever isn't built, and with them
the user's customisations. PURURU_UPDATE_IDS=1 rewrites the snapshot; do it only
for IDs a change adds, never to accept one that moved or went.
"""

import json
import os
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import yaml

from helpers import DOMAIN, setup

FIXTURES = Path(__file__).parent / "fixtures"
HOUSE = yaml.safe_load((FIXTURES / "house.yaml").read_text())
SNAPSHOT = FIXTURES / "house_ids.json"
# The entry's data keys holding the IDs of generated scripts and automations
GENERATED = ("scripts", "automations", "notifications")


def ids(hass: HomeAssistant) -> dict[str, list[list[str]]]:
    """The entry's entities as (platform, unique ID), and its generated items as (data key, ID), sorted."""
    [entry] = hass.config_entries.async_entries(DOMAIN)
    registry = er.async_get(hass)
    entities = sorted(
        [registered.domain, registered.unique_id]
        for registered in er.async_entries_for_config_entry(registry, entry.entry_id)
    )
    generated = sorted(
        [key, unique_id] for key in GENERATED for unique_id in entry.data.get(key, [])
    )
    return {"entities": entities, "generated": generated}


async def test_ids_are_pinned(ha: HomeAssistant) -> None:
    """The whole house builds exactly the pinned IDs, no more, no fewer."""
    assert await setup(
        ha,
        HOUSE["devices"],
        floors=HOUSE["floors"],
        areas=HOUSE["areas"],
        events=HOUSE["events"],
        config=HOUSE["config"],
    )
    found: dict[str, Any] = ids(ha)
    if os.environ.get("PURURU_UPDATE_IDS") == "1":
        SNAPSHOT.write_text(json.dumps(found, indent=1) + "\n")
    assert found == json.loads(SNAPSHOT.read_text())
