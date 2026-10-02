"""What a story does to Home Assistant, and only through Home Assistant.

pururu is a black box here: no module of it is imported. A story writes YAML,
plays the real devices, moves the clock and reads what Home Assistant shows.
"""

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import CoreState, Event, HomeAssistant, ServiceCall, callback
from homeassistant.helpers import entity_registry as er, restore_state
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)
import yaml

DOMAIN = "pururu"
# The files pururu writes, relative to the configuration folder (docs/concepts/programs.mdx, "The include")
AUTOMATIONS = "pururu/automations/automations.yaml"
SCRIPTS = "pururu/scripts/programs.yaml"
# Loop turns a wait gives: far more than any chain of callbacks needs. Never
# async_block_till_done while a script runs: it would wait out the script's delay
TURNS = 100

# The reference house, and the calm states of the real entities it names
HOUSE: dict[str, Any] = yaml.safe_load(
    (Path(__file__).resolve().parent / "house.yaml").read_text(encoding="utf-8"))
# A colour bulb as Zigbee2MQTT shows it: hs colour, breathe among its effects
BULB = {"supported_color_modes": ["hs"], "color_mode": "hs", "brightness": 255,
        "hs_color": [240.0, 100.0], "effect_list": ["blink", "breathe"], "supported_features": 44}
WATTS = {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}
KWH = {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}
CALM: dict[str, tuple[str, dict[str, Any]]] = {
    "sensor.washer_plug_power": ("0", WATTS),              # between cycles
    "sensor.washer_plug_energy": ("120.0", KWH),
    "sensor.fridge_plug_power": ("80", WATTS),             # idle, never 0
    "binary_sensor.front_door_contact": ("off", {}),        # closed
    "binary_sensor.bedroom_window_contact": ("off", {}),
    "light.living_room_ceiling": ("off", BULB),
    "switch.living_room_lamp_relay": ("off", {}),
    "switch.garden_pump": ("off", {}),
    "sensor.garden_remote_action": ("idle", {}),            # no button's value
}
# The notify action house.yaml's config: notify names
NOTIFY = ("notify", "phone")


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
        self.calm = Calm(hass)

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

    async def setup_house(self) -> None:
        """The reference house, from its calm states."""
        for entity_id, (state, attributes) in CALM.items():
            self.hass.states.async_set(entity_id, state, attributes)
        assert await self.setup(HOUSE)

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
        """A real device changes: set its state (its attributes kept unless given) and let Home Assistant react."""
        if attributes is None and (current := self.hass.states.get(entity_id)) is not None:
            attributes = dict(current.attributes)
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


class Calm:
    """What turned up unasked: every pururu alert turning on, every notification sent.

    A story names the alerts and notifications it causes; the `home` fixture
    fails the story, naming each one, when anything else turned up.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.alerts: list[str] = []
        self.told: list[str] = []
        self.expected: set[str] = set()
        self.notify = async_mock_service(hass, *NOTIFY)
        hass.bus.async_listen(EVENT_STATE_CHANGED, self._changed)

    @callback
    def _changed(self, event: Event) -> None:
        entity_id: str = event.data["entity_id"]
        old, new = event.data["old_state"], event.data["new_state"]
        if (entity_id.startswith("binary_sensor.pururu_") and "_alert_" in entity_id
                and new is not None and new.state == "on" and (old is None or old.state != "on")):
            self.alerts.append(entity_id)

    def expect(self, *caused: str) -> None:
        """The alerts (entity IDs) and notifications (titles) the story causes."""
        self.expected.update(caused)

    def sent(self) -> list[ServiceCall]:
        """The notifications sent, in order."""
        return list(self.notify)

    def unexpected(self) -> list[str]:
        """What turned up and the story didn't cause."""
        alerts = [f"alert {entity_id}" for entity_id in self.alerts if entity_id not in self.expected]
        told = [f"notification {call.data.get('title')}: {call.data.get('message')}"
                for call in self.notify if call.data.get("title") not in self.expected]
        return alerts + told
