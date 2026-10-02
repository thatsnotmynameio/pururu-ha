"""What a story does to Home Assistant, and only through Home Assistant.

pururu is a black box here: no module of it is imported. A story writes YAML,
plays the real devices, moves the clock and reads what Home Assistant shows.
"""

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, restore_state
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
import yaml

DOMAIN = "pururu"
# The files pururu writes, relative to the configuration folder (docs/concepts/programs.mdx, "The include")
AUTOMATIONS = "pururu/automations/automations.yaml"
SCRIPTS = "pururu/scripts/programs.yaml"
# Loop turns a wait gives: far more than any chain of callbacks needs. Never
# async_block_till_done while a script runs: it would wait out the script's delay
TURNS = 100


async def wait() -> None:
    """Let everything that is ready run."""
    for _ in range(TURNS):
        await asyncio.sleep(0)


class Home:
    """A Home Assistant with pururu, driven as its user would.

    The configuration.yaml it shows Home Assistant holds the house's `pururu:`
    block and includes the automations and scripts pururu wrote, so Home
    Assistant's own reloads read pururu's files back, as with the documented include.
    """

    def __init__(self, hass: HomeAssistant, freezer: Any) -> None:
        self.hass = hass
        self.freezer = freezer
        self.block: dict[str, Any] = {}

    def configuration(self) -> dict[str, Any]:
        """configuration.yaml as Home Assistant reads it."""
        return {DOMAIN: self.block,
                "automation pururu": self._read(AUTOMATIONS) or [],
                "script pururu": self._read(SCRIPTS) or {}}

    def _read(self, path: str) -> Any:
        file = Path(self.hass.config.path(path))
        return yaml.safe_load(file.read_text(encoding="utf-8")) if file.is_file() else None

    async def setup(self, block: dict[str, Any]) -> bool:
        """Start with this `pururu:` block: automations and scripts first, as configuration.yaml lists them."""
        self.block = block
        for domain in ("automation", "script"):
            assert await async_setup_component(self.hass, domain, self.configuration())
        ok = await async_setup_component(self.hass, DOMAIN, self.configuration())
        await self.hass.async_block_till_done()
        return ok

    async def reload(self, block: dict[str, Any]) -> None:
        """Edit configuration.yaml's `pururu:` block, then call pururu.reload."""
        self.block = block
        await self.hass.services.async_call(DOMAIN, "reload", blocking=True)
        await self.hass.async_block_till_done()

    async def restart(self) -> None:
        """Stop Home Assistant and start it again, carrying across only what it saves itself.

        Home Assistant saves its entities' states as it stops and loads them back as it
        starts; this saves and loads them through the test's storage. The registries
        and pururu's config entry stay in memory, as they would stay on disk: the HA
        test plugin's registries never save or load (StoreWithoutWriteLoad) and it
        never loads config entries, so a second Home Assistant would start without
        the user's renames or pururu's entry. So the restart stays on one instance.
        """
        hass = self.hass
        await restore_state.async_get(hass).async_dump_states()
        [entry] = hass.config_entries.async_entries(DOMAIN)
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        hass.set_state(CoreState.not_running)
        await restore_state.async_get(hass).async_load()
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_start()
        await hass.async_block_till_done()

    async def tick(self, seconds: float) -> None:
        """Move the clock by `seconds` and run what became due."""
        self.freezer.tick(timedelta(seconds=seconds))
        async_fire_time_changed(self.hass, dt_util.utcnow())
        await wait()

    async def play(self, entity_id: str, state: str,
                   attributes: dict[str, Any] | None = None) -> None:
        """A real device changes: set its state and let Home Assistant react."""
        self.hass.states.async_set(entity_id, state, attributes)
        await wait()

    def state(self, entity_id: str) -> str:
        """An entity's state; it must exist."""
        found = self.hass.states.get(entity_id)
        assert found is not None, f"no {entity_id}"
        return found.state

    def attributes(self, entity_id: str) -> dict[str, Any]:
        """An entity's attributes; it must exist."""
        found = self.hass.states.get(entity_id)
        assert found is not None, f"no {entity_id}"
        return dict(found.attributes)

    async def rename(self, entity_id: str, new_entity_id: str) -> None:
        """The user changes an entity's ID in Home Assistant's settings."""
        er.async_get(self.hass).async_update_entity(entity_id, new_entity_id=new_entity_id)
        await self.hass.async_block_till_done()

    async def disable(self, entity_id: str) -> None:
        """The user disables an entity in Home Assistant's settings."""
        er.async_get(self.hass).async_update_entity(
            entity_id, disabled_by=er.RegistryEntryDisabler.USER)
        await self.hass.async_block_till_done()

    async def enable(self, entity_id: str) -> None:
        """The user enables an entity again; Home Assistant reloads its entry after a delay."""
        er.async_get(self.hass).async_update_entity(entity_id, disabled_by=None)
        await self.hass.async_block_till_done()

    def capture(self, *event_types: str) -> list[Event]:
        """Record events of these types, in the order they are fired."""
        captured: list[Event] = []

        @callback
        def record(event: Event) -> None:
            captured.append(event)

        for event_type in event_types:
            self.hass.bus.async_listen(event_type, record)
        return captured
