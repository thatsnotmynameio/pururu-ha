"""Every ID the whole house creates, pinned: a refactor that loses or renames one fails here.

`devices.remove_stale` deletes the registry entries of whatever isn't built, and with them
the user's customisations. PURURU_UPDATE_IDS=1 rewrites the snapshot; do it only
for IDs a change adds, never to accept one that moved or went.

Each created entity's path, its node in the YAML, is pinned too: it is what the
author writes to name it. PURURU_UPDATE_PATHS=1 rewrites that snapshot, by the
same rule: only for entities a change adds.
"""

import json
import os
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import yaml

from helpers import DOMAIN, module, setup

FIXTURES = Path(__file__).parent / "fixtures"
HOUSE = yaml.safe_load((FIXTURES / "house.yaml").read_text())
SNAPSHOT = FIXTURES / "house_ids.json"
PATHS = FIXTURES / "house_paths.json"
# The entry's data keys holding the IDs of generated scripts, and reactions' and ready-made notifications' automations
GENERATED = ("scripts", "automations")


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
        config=HOUSE["config"],
    )
    found: dict[str, Any] = ids(ha)
    if os.environ.get("PURURU_UPDATE_IDS") == "1":
        SNAPSHOT.write_text(json.dumps(found, indent=1) + "\n")
    assert found == json.loads(SNAPSHOT.read_text())


async def test_paths_are_pinned(ha: HomeAssistant) -> None:
    """Each entity the whole house creates, by unique ID, has its pinned path in the index."""
    assert await setup(
        ha,
        HOUSE["devices"],
        floors=HOUSE["floors"],
        areas=HOUSE["areas"],
        config=HOUSE["config"],
    )
    [entry] = ha.config_entries.async_entries(DOMAIN)
    created = {
        registered.unique_id
        for registered in er.async_entries_for_config_entry(er.async_get(ha), entry.entry_id)
    }
    devices = module("setup.schema").CONFIG_SCHEMA({DOMAIN: HOUSE})[DOMAIN]["devices"]
    paths = {
        target.unique_id: target.path
        for targets in module("setup.catalogue").index(devices).values()
        for target in targets.values()
        if target.unique_id in created
    }
    assert set(paths) == created  # every created entity has its path
    # The energy mirror is its setting's entity; the idle total is born unwritten
    assert paths["pururu_clothes_washer_appliance_energy_total"] == "appliance.energy"
    assert paths["pururu_clothes_washer_appliance_idle_energy_total"] == "appliance.idle_energy_total"
    found = dict(sorted(paths.items()))
    if os.environ.get("PURURU_UPDATE_PATHS") == "1":
        PATHS.write_text(json.dumps(found, indent=1) + "\n")
    assert found == json.loads(PATHS.read_text())
