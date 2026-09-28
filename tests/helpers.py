"""Set-up, reloads, registries, restarts and simulated time for the pururu tests."""

import asyncio
from datetime import timedelta
import importlib
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

from homeassistant.core import CoreState, Event, HomeAssistant, State, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)
import yaml

DOMAIN = "pururu"
# The automations pururu generates, relative to the configuration folder
AUTOMATIONS = "pururu/automations/reactions.yaml"
# The scripts pururu generates, relative to the configuration folder
SCRIPTS = "pururu/scripts/programs.yaml"
# Loop turns settle() gives: far more than any chain of our callbacks needs
SETTLE_TURNS = 100


def module(name: str) -> ModuleType:
    """One of the integration's modules, as HA loads it (after the `ha` fixture)."""
    return importlib.import_module(f"custom_components.pururu.{name}")


def _config(devices: dict[str, Any], floors: dict[str, Any] | None,
            areas: dict[str, Any] | None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """A configuration.yaml with this `pururu:` block; `config` is its config: block."""
    block: dict[str, Any] = {"devices": devices, "floors": floors or {}, "areas": areas or {}}
    if config is not None:
        block["config"] = config
    return {DOMAIN: block}


def generated(hass: HomeAssistant) -> list[dict[str, Any]]:
    """The automations pururu wrote, as configuration.yaml's include reads them."""
    path = Path(hass.config.path(AUTOMATIONS))
    if not path.is_file():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def generated_scripts(hass: HomeAssistant) -> dict[str, Any]:
    """The scripts pururu wrote, as configuration.yaml's include reads them."""
    path = Path(hass.config.path(SCRIPTS))
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


async def setup(hass: HomeAssistant, devices: dict[str, Any], *,
                floors: dict[str, Any] | None = None,
                areas: dict[str, Any] | None = None,
                config: dict[str, Any] | None = None) -> bool:
    """Set pururu up from `pururu:`; False when HA refuses the configuration."""
    ok = await async_setup_component(hass, DOMAIN, _config(devices, floors, areas, config))
    await hass.async_block_till_done()
    return ok


async def reload(hass: HomeAssistant, devices: dict[str, Any], *,
                 floors: dict[str, Any] | None = None,
                 areas: dict[str, Any] | None = None,
                 config: dict[str, Any] | None = None) -> None:
    """pururu.reload, with a configuration.yaml holding this `pururu:` block."""
    yaml_config = _config(devices, floors, areas, config)
    # configuration.yaml includes the generated files: automations and scripts reload from them
    with patch("homeassistant.config.load_yaml_config_file",
               side_effect=lambda *_args, **_kwargs: {**yaml_config,
                                                      "automation pururu": generated(hass),
                                                      "script pururu": generated_scripts(hass)}):
        await hass.services.async_call(DOMAIN, "reload", blocking=True)
        await hass.async_block_till_done()


async def restart(hass: HomeAssistant, devices: dict[str, Any],
                  *saved: tuple[State, dict[str, Any]],
                  config: dict[str, Any] | None = None) -> None:
    """Start as after a restart: `saved` is what .storage held (state, extra data)."""
    hass.set_state(CoreState.not_running)
    mock_restore_cache_with_extra_data(hass, list(saved))
    assert await setup(hass, devices, config=config)
    await hass.async_start()
    await hass.async_block_till_done()


def device_of(hass: HomeAssistant, key: str) -> dr.DeviceEntry | None:
    """The device of `key`, if there is one."""
    found = dr.async_get(hass).async_get_devices(identifiers={(DOMAIN, key)})
    assert len(found) <= 1, found
    return found[0] if found else None


def held(hass: HomeAssistant, key: str) -> set[str]:
    """Entity IDs in device `key`, from the entity registry."""
    device = device_of(hass, key)
    assert device is not None, f"no device {key}"
    registry = er.async_get(hass)
    return {entry.entity_id for entry in er.async_entries_for_device(registry, device.id)}


async def settle() -> None:
    """Let everything that is ready run."""
    for _ in range(SETTLE_TURNS):
        await asyncio.sleep(0)


async def tick(hass: HomeAssistant, freezer: Any, seconds: float) -> None:
    """Advance simulated time by `seconds` and run what became due."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await settle()


async def fake(hass: HomeAssistant, entity_id: str, state: str,
               attributes: dict[str, Any] | None = None) -> None:
    """Play a real device: set its state and let the integration react."""
    hass.states.async_set(entity_id, state, attributes)
    await settle()


def capture(hass: HomeAssistant, *event_types: str) -> list[Event]:
    """Record events of these types, in the order they are fired."""
    captured: list[Event] = []

    @callback
    def record(event: Event) -> None:
        captured.append(event)

    for event_type in event_types:
        hass.bus.async_listen(event_type, record)
    return captured
