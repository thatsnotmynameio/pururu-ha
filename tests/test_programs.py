"""Programs: a made-up greenhouse's cleaning, turning its sprinkler on for two hours, as an HA script."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

from homeassistant.core import Context, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import yaml

from helpers import (DOMAIN, SCRIPTS, capture, device_of, fake, generated, generated_scripts, held, module, reload, settle,
                     setup, tick)

KEY = "greenhouse"
REAL_SPRINKLER = "switch.greenhouse_sprinkler"
SPRINKLER = "switch.pururu_greenhouse_switch_sprinkler"
CLEAN = "script.pururu_greenhouse_program_executable_clean"
SWITCHES: dict[str, Any] = {"sprinkler": {"entity": f"homeassistant.{REAL_SPRINKLER}", "name": "Irrigador"}}
TWO_HOURS = 2 * 60 * 60
CLEANING: dict[str, Any] = {"name": "Limpar", "sequence": [
    {"turn_on": "switches.sprinkler"}, {"delay": {"hours": 2}}, {"turn_off": "switches.sprinkler"}]}
APPLIANCE = {"power": "homeassistant.sensor.greenhouse_sprinkler_power",
             "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}}}


def devices(**programs: Any) -> dict[str, Any]:
    return {KEY: {"name": "Estufa", "switches": SWITCHES, "programs": {"executable": programs or {"clean": CLEANING}}}}


def reached(calls: list[Event], entity_id: str = REAL_SPRINKLER) -> list[str]:
    """The services called on `entity_id`, in order."""
    found = []
    for event in calls:
        ids = event.data["service_data"].get("entity_id")
        if ids == entity_id or (isinstance(ids, list) and entity_id in ids):
            found.append(event.data["service"])
    return found


async def start(hass: HomeAssistant, entity_id: str = CLEAN, context: Context | None = None) -> None:
    await hass.services.async_call("script", "turn_on", {"entity_id": entity_id}, blocking=True,
                                   context=context)
    await settle()


async def reload_while_running(hass: HomeAssistant, devices: dict[str, Any]) -> None:
    """Like helpers.reload, but settles instead of hass.async_block_till_done().

    A running script is HA's own asyncio task (hass._tasks, not a background one): that
    call waits for every such task, so it would wait for the whole two hours here.
    """
    config = {DOMAIN: {"devices": devices, "floors": {}, "areas": {}}}
    with patch("homeassistant.config.load_yaml_config_file",
               side_effect=lambda *_args, **_kwargs: {**config,
                                                      "automation pururu": generated(hass),
                                                      "script pururu": generated_scripts(hass)}):
        await hass.services.async_call(DOMAIN, "reload", blocking=True)
        await settle()


@pytest.fixture
async def scripts(ha: HomeAssistant) -> AsyncIterator[HomeAssistant]:
    """HA's scripts, from a configuration.yaml that includes pururu's file."""
    with patch("homeassistant.config.load_yaml_config_file",
               side_effect=lambda *_args, **_kwargs: {"script pururu": generated_scripts(ha)}):
        assert await async_setup_component(ha, "script", {"script pururu": generated_scripts(ha)})
        yield ha


@pytest.fixture
async def greenhouse(scripts: HomeAssistant) -> HomeAssistant:
    await fake(scripts, REAL_SPRINKLER, "off")
    assert await setup(scripts, devices())
    return scripts


# --- schema and the device ---------------------------------------------------------


@pytest.mark.parametrize("program", [
    pytest.param({"name": "Limpar"}, id="no sequence"),
    pytest.param({"name": "Limpar", "sequence": []}, id="empty sequence"),
    pytest.param({"sequence": [{"turn_on": "switches.sprinkler"}]}, id="no name"),
    pytest.param({"name": " ", "sequence": [{"turn_on": "switches.sprinkler"}]}, id="blank name"),
    pytest.param({"name": "Limpar", "sequence": [{"action": "switch.turn_on"}]}, id="an HA action"),
    pytest.param({"name": "Limpar", "sequence": [{"turn_on": "switches.sprinkler", "delay": 5}]},
                 id="two keys in a step"),
    pytest.param({"name": "Limpar", "sequence": [{}]}, id="an empty step"),
    pytest.param({"name": "Limpar", "sequence": ["turn_on"]}, id="a step that isn't a mapping"),
    pytest.param({"name": "Limpar", "sequence": [{"delay": -5}]}, id="a negative delay"),
    pytest.param({"name": "Limpar", "sequence": [{"turn_on": REAL_SPRINKLER}]}, id="a real entity ID"),
    pytest.param({"name": "Limpar", "sequence": [{"turn_on": "device.greenhouse.switches.sprinkler"}]},
                 id="a step with a device"),
    pytest.param({"name": "Limpar", "sequence": [{"turn_on": "switches.sprinkler"}], "icon": "mdi:greenhouse"},
                 id="unknown key"),
])
async def test_invalid_program_is_refused(ha: HomeAssistant, program: dict[str, Any]) -> None:
    assert not await setup(ha, devices(clean=program))


STEP = "'pururu->devices->greenhouse->programs->executable->clean->sequence->0->turn_on'"


@pytest.mark.parametrize(("written", "why"), [
    pytest.param("device.greenhouse.switches.sprinkler",
                 "device.greenhouse.switches.sprinkler is this device's: write switches.sprinkler",
                 id="with its own device"),
    pytest.param("device.dryer.switches.plug", "device.dryer.switches.plug is not of this device",
                 id="another device"),
    pytest.param("homeassistant.switch.greenhouse_sprinkler",
                 "homeassistant.switch.greenhouse_sprinkler is not of this device", id="Home Assistant's"),
    pytest.param(REAL_SPRINKLER, "switch.greenhouse_sprinkler: switch is not a block of this device",
                 id="an entity ID"),
    pytest.param("greenhouse.switch_sprinkler",
                 "greenhouse.switch_sprinkler: greenhouse is not a block of this device",
                 id="with its device, as before 0.2.2"),
])
async def test_a_step_acts_only_on_this_device(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, written: str, why: str) -> None:
    """A step names a path of its own device, from its block."""
    assert not await setup(ha, devices(clean={"name": "Limpar", "sequence": [{"turn_on": written}]}))
    assert f"programs: {why} {STEP}" in caplog.text


# A flat map (before D3) or a block without its group: the device's programs
# sit under executable:, said at the block
UNDER_EXECUTABLE = ("a device's programs sit under executable: (programs: executable: <key>: …) "
                    "for dictionary value 'pururu->devices->greenhouse->programs'")


@pytest.mark.parametrize(("programs", "message"), [
    pytest.param({"clean": CLEANING}, UNDER_EXECUTABLE, id="a flat map, as before D3"),
    pytest.param({}, UNDER_EXECUTABLE, id="no group"),
    pytest.param({"executable": {}}, "length of value must be at least 1", id="no program"),
    pytest.param({"executable": None},
                 "expected a mapping for dictionary value 'pururu->devices->greenhouse->programs->executable'",
                 id="executable with nothing under it"),
    pytest.param(None, "expected a mapping for dictionary value 'pururu->devices->greenhouse->programs'",
                 id="null"),
    pytest.param({"executable": {"clean": CLEANING}, "detected": {"cotton": {"name": "Algodão", "above": 1500}}},
                 "a device's programs are executable: a detected program sits in the block of the "
                 "feature whose reading it reads", id="detected at the device"),
])
async def test_the_programs_block_is_executable(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, programs: Any, message: str) -> None:
    config = devices()
    config[KEY]["programs"] = programs
    assert not await setup(ha, config)
    assert message in caplog.text


@pytest.mark.parametrize(("target", "why"), [
    pytest.param("switches.greenhouse_sprinkler", "switches.greenhouse_sprinkler is not an entity of this device",
                 id="not an entity of the device"),
    pytest.param("switches.heater", "switches.heater is not an entity of this device",
                 id="a switch the device doesn't have"),
    pytest.param("programs.executable.clean", "programs.executable.clean is not an entity of this device",
                 id="a program"),
    pytest.param("switch_sprinkler", None, id="an entity key, as before 0.2.2"),
])
async def test_a_target_not_of_another_feature_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, target: str, why: str | None) -> None:
    assert not await setup(ha, devices(clean={"name": "Limpar", "sequence": [{"turn_on": target}]}))
    if why is None:
        assert f"{target} is not a path: write it from its block, <block>.<key> for dictionary value {STEP}" in caplog.text
    else:
        assert f"programs: {why}" in caplog.text


async def test_programs_alone_are_not_a_feature(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    assert not await setup(ha, {KEY: {"name": "Estufa", "programs": {"executable": {"clean": CLEANING}}}})
    assert "a device needs at least one feature" in caplog.text


async def test_an_action_the_target_does_not_take_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    program = {"name": "Ligar", "sequence": [{"turn_on": "appliance.power"}]}
    assert not await setup(ha, {KEY: {"name": "Estufa", "appliance": APPLIANCE,
                                      "programs": {"executable": {"start": program}}}})
    assert f"programs: appliance.power does not take turn_on {STEP.replace('clean', 'start')}" in caplog.text


async def test_two_programs_with_one_script_id_are_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """greenhouse's b_program_executable_c and greenhouse_program_executable_b's c would both be pururu_greenhouse_program_executable_b_program_executable_c."""
    config = devices(b_program_executable_c=CLEANING)
    config["greenhouse_program_executable_b"] = {
        "name": "Outra", "switches": {"x": {"entity": "homeassistant.switch.dummy_x", "name": "X"}},
        "programs": {"executable": {"c": {"name": "C", "sequence": [{"turn_on": "switches.x"}]}}},
    }
    assert not await setup(ha, config)
    assert ("device greenhouse_program_executable_b: "
            "script.pururu_greenhouse_program_executable_b_program_executable_c is already "
            "a program of device greenhouse") in caplog.text


# --- the generated script ------------------------------------------------------------


async def test_the_file_holds_a_script_per_program(ha: HomeAssistant) -> None:
    assert await setup(ha, devices())
    assert generated_scripts(ha) == {"pururu_greenhouse_program_executable_clean": {
        "alias": "Estufa Limpar",
        "description": "pururu: greenhouse, clean",
        "mode": "single",
        "sequence": [
            {"action": "switch.turn_on", "target": {"entity_id": SPRINKLER}},
            {"delay": "02:00:00"},
            {"action": "switch.turn_off", "target": {"entity_id": SPRINKLER}},
        ],
    }}
    cv.SCRIPT_SCHEMA(generated_scripts(ha)["pururu_greenhouse_program_executable_clean"]["sequence"])


async def test_it_is_a_script_named_by_the_configuration(greenhouse: HomeAssistant) -> None:
    state = greenhouse.states.get(CLEAN)
    assert state is not None
    assert state.state == "off"
    assert state.attributes["friendly_name"] == "Estufa Limpar"
    entry = er.async_get(greenhouse).async_get(CLEAN)
    assert entry is not None
    assert (entry.platform, entry.unique_id) == ("script", "pururu_greenhouse_program_executable_clean")
    # HA keeps a script from YAML out of any device; its statistics are the device's
    assert CLEAN not in held(greenhouse, KEY)
    assert f"{STAT}cycles_total" in held(greenhouse, KEY)
    assert greenhouse.states.async_entity_ids("button") == []


async def test_it_is_in_its_devices_area(scripts: HomeAssistant) -> None:
    config = devices()
    config[KEY]["area"] = "patio"
    assert await setup(scripts, config, areas={"patio": {"name": "Pátio"}})
    entry = er.async_get(scripts).async_get(CLEAN)
    assert entry is not None
    assert entry.area_id == "patio"


# --- running -------------------------------------------------------------------------


async def test_turning_it_on_runs_the_sequence(greenhouse: HomeAssistant, freezer: Any) -> None:
    calls = capture(greenhouse, "call_service")
    await start(greenhouse)
    assert reached(calls) == ["turn_on"]
    await tick(greenhouse, freezer, TWO_HOURS - 1)
    assert reached(calls) == ["turn_on"]
    await tick(greenhouse, freezer, 1)
    assert reached(calls) == ["turn_on", "turn_off"]


async def test_toggle_flips_the_switch(scripts: HomeAssistant) -> None:
    await fake(scripts, REAL_SPRINKLER, "on")
    assert await setup(scripts, devices(flip={"name": "Inverter", "sequence": [{"toggle": "switches.sprinkler"}]}))
    calls = capture(scripts, "call_service")
    await start(scripts, "script.pururu_greenhouse_program_executable_flip")
    assert reached(calls) == ["turn_off"]


@pytest.mark.parametrize(("real", "attributes"), [
    pytest.param("light.biblioteca_teto", {"supported_color_modes": ["onoff"], "color_mode": "onoff"},
                 id="a real light"),
    pytest.param("switch.sonoff_teto", {}, id="a relay driving a lamp"),
])
async def test_it_turns_a_light_on_and_off(
        scripts: HomeAssistant, freezer: Any, real: str, attributes: dict[str, Any]) -> None:
    await fake(scripts, real, "off", attributes)
    evening = {"name": "Noite", "sequence": [
        {"turn_on": "lights.teto"}, {"delay": {"minutes": 30}}, {"turn_off": "lights.teto"}]}
    assert await setup(scripts, {"biblioteca": {"name": "Biblioteca",
                                          "lights": {"teto": {"entity": f"homeassistant.{real}", "name": "Teto"}},
                                          "programs": {"executable": {"evening": evening}}}})
    calls = capture(scripts, "call_service")
    await start(scripts, "script.pururu_biblioteca_program_executable_evening")
    await tick(scripts, freezer, 30 * 60)
    assert reached(calls, real) == ["turn_on", "turn_off"]


async def test_it_returns_at_once_and_is_on_while_it_runs(greenhouse: HomeAssistant) -> None:
    """As before with the button: an automation starting it doesn't wait two hours."""
    async with asyncio.timeout(5):
        await greenhouse.services.async_call("script", "turn_on", {"entity_id": CLEAN}, blocking=True)
    await settle()
    assert greenhouse.states.get(CLEAN).state == "on"


async def test_turning_it_off_stops_it(greenhouse: HomeAssistant, freezer: Any) -> None:
    calls = capture(greenhouse, "call_service")
    await start(greenhouse)
    await tick(greenhouse, freezer, 60)
    await greenhouse.services.async_call("script", "turn_off", {"entity_id": CLEAN}, blocking=True)
    await settle()
    assert greenhouse.states.get(CLEAN).state == "off"
    await tick(greenhouse, freezer, TWO_HOURS)
    assert reached(calls) == ["turn_on"]


async def test_what_it_does_carries_the_callers_context(greenhouse: HomeAssistant) -> None:
    """The logbook names who started it."""
    calls = capture(greenhouse, "call_service")
    context = Context()
    await start(greenhouse, context=context)
    real = [event for event in calls if reached([event]) == ["turn_on"]]
    assert real
    assert all(context.id in (event.context.id, event.context.parent_id) for event in real)


async def test_starting_it_while_it_runs_is_ignored(
        greenhouse: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    """A blocking script.turn_on on an already-running single-mode script returns at its
    next change (its next step, or its end), not at once: under frozen time that's two
    hours away, so this second call is non-blocking instead."""
    calls = capture(greenhouse, "call_service")
    await start(greenhouse)
    await tick(greenhouse, freezer, 60)
    await greenhouse.services.async_call("script", "turn_on", {"entity_id": CLEAN}, blocking=False)
    await settle()
    assert "Estufa Limpar: Already running" in caplog.text
    await tick(greenhouse, freezer, TWO_HOURS)
    assert reached(calls) == ["turn_on", "turn_off"]


async def test_an_unavailable_switch_does_not_stop_it(scripts: HomeAssistant, freezer: Any) -> None:
    """No real switch: the pururu switch is unavailable, HA skips it, the program goes on."""
    assert await setup(scripts, devices())
    calls = capture(scripts, "call_service")
    await start(scripts)
    await tick(scripts, freezer, TWO_HOURS)
    assert reached(calls, SPRINKLER) == ["turn_on", "turn_off"]


async def test_a_failing_step_stops_it_and_is_logged(
        greenhouse: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    """A step's failure raises inside the background task script.turn_on's domain service
    starts and never awaits (it only waits for the run to start): retrieve its exception
    ourselves, so HA's test harness doesn't also flag it as "never retrieved" at teardown."""
    calls = capture(greenhouse, "call_service")
    created: list[asyncio.Task[Any]] = []
    original = greenhouse.async_create_task_internal

    def capture_task(coro: Any, name: str | None = None, eager_start: bool = True) -> Any:
        task = original(coro, name, eager_start)
        if isinstance(task, asyncio.Task):
            created.append(task)
        return task

    greenhouse.async_create_task_internal = capture_task
    try:
        with patch("homeassistant.components.group.switch.SwitchGroup.async_turn_on",
                   side_effect=HomeAssistantError("the relay is stuck")):
            await start(greenhouse)
        await tick(greenhouse, freezer, TWO_HOURS)
    finally:
        greenhouse.async_create_task_internal = original
    for task in created:
        if task.done() and not task.cancelled():
            task.exception()
    assert reached(calls, SPRINKLER) == ["turn_on"]
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any("Estufa Limpar" in message and "the relay is stuck" in message
               for message in errors), errors


# --- a disabled target -----------------------------------------------------------------


def assert_held_out(hass: HomeAssistant, entity_id: str) -> None:
    """Out of HA's scripts, its registry entry kept: HA shows the placeholder of an entity not provided."""
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "unavailable"
    assert state.attributes.get("restored") is True


async def disable(hass: HomeAssistant, entity_id: str, disabled: bool = True) -> None:
    er.async_get(hass).async_update_entity(
        entity_id, disabled_by=er.RegistryEntryDisabler.USER if disabled else None)
    await hass.async_block_till_done()


async def test_a_disabled_target_drops_the_program(
        greenhouse: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    """A script that looks usable and does part of its job would mislead: it goes, logged.

    HA's own config entry reload-on-disable only fires when an entity is
    *re-enabled* (config_entries.py's disable handler explicitly skips scheduling
    one while the entity stays disabled); pururu's own registry listener in
    async_setup_entry schedules the reload here instead.
    """
    await disable(greenhouse, SPRINKLER)
    await tick(greenhouse, freezer, 31)
    await greenhouse.async_block_till_done()
    assert generated_scripts(greenhouse) == {}
    assert_held_out(greenhouse, CLEAN)
    assert f"{CLEAN} acts on {SPRINKLER}, which is disabled; not generating it" in caplog.text


async def test_it_comes_back_when_the_target_is_enabled(greenhouse: HomeAssistant, freezer: Any) -> None:
    await disable(greenhouse, SPRINKLER)
    await tick(greenhouse, freezer, 31)
    await disable(greenhouse, SPRINKLER, disabled=False)
    await tick(greenhouse, freezer, 31)
    await greenhouse.async_block_till_done()
    calls = capture(greenhouse, "call_service")
    await start(greenhouse)
    assert reached(calls) == ["turn_on"]


async def set_target(hass: HomeAssistant, freezer: Any, disabled: bool) -> None:
    await disable(hass, SPRINKLER, disabled)
    await tick(hass, freezer, 31)
    await hass.async_block_till_done()


async def test_a_program_the_user_disabled_stays_disabled_once_its_target_is_back(
        greenhouse: HomeAssistant, freezer: Any) -> None:
    """Held while its target is disabled, not dropped: its registry entry stays as the user set it.

    Not left to HA's restore of a deleted entry's settings on re-creation: that
    one lasts 30 days for an entry without a config entry, and then is purged.
    """
    registry = er.async_get(greenhouse)
    before = registry.async_get(CLEAN)
    assert before is not None
    registry.async_update_entity(CLEAN, disabled_by=er.RegistryEntryDisabler.USER)
    await tick(greenhouse, freezer, 31)
    await greenhouse.async_block_till_done()
    await set_target(greenhouse, freezer, disabled=True)
    held_entry = registry.async_get(CLEAN)
    assert held_entry is not None
    assert held_entry.id == before.id
    assert held_entry.disabled_by is er.RegistryEntryDisabler.USER
    await set_target(greenhouse, freezer, disabled=False)
    after = registry.async_get(CLEAN)
    assert after is not None
    assert after.id == before.id
    assert after.disabled_by is er.RegistryEntryDisabler.USER
    assert greenhouse.states.get(CLEAN) is None
    assert "pururu_greenhouse_program_executable_clean" in generated_scripts(greenhouse)


async def test_a_program_renamed_keeps_its_entity_id_once_its_target_is_back(
        greenhouse: HomeAssistant, freezer: Any) -> None:
    registry = er.async_get(greenhouse)
    registry.async_update_entity(CLEAN, new_entity_id="script.limpar_estufa")
    await greenhouse.async_block_till_done()
    await set_target(greenhouse, freezer, disabled=True)
    assert_held_out(greenhouse, "script.limpar_estufa")
    assert registry.async_get_entity_id(
        "script", "script", "pururu_greenhouse_program_executable_clean") == "script.limpar_estufa"
    await set_target(greenhouse, freezer, disabled=False)
    assert greenhouse.states.get(CLEAN) is None
    calls = capture(greenhouse, "call_service")
    await start(greenhouse, "script.limpar_estufa")
    assert reached(calls) == ["turn_on"]


async def test_a_held_program_stays_tracked_without_a_repairs_issue(
        greenhouse: HomeAssistant, freezer: Any) -> None:
    await set_target(greenhouse, freezer, disabled=True)
    assert_held_out(greenhouse, CLEAN)
    assert er.async_get(greenhouse).async_get(CLEAN) is not None
    assert greenhouse.config_entries.async_entries("pururu")[0].data["scripts"] == [
        "pururu_greenhouse_program_executable_clean"]
    assert ir.async_get(greenhouse).async_get_issue(DOMAIN, "scripts_not_included") is None
    calls = capture(greenhouse, "call_service")
    await start(greenhouse)
    assert reached(calls) == []  # held out: starting it does nothing


VENT = "switch.pururu_greenhouse_switch_vent"
TWO_SWITCHES: dict[str, Any] = {**SWITCHES, "vent": {"entity": "homeassistant.switch.greenhouse_vent", "name": "Ventilação"}}


async def two_switches(hass: HomeAssistant, *keys: str) -> None:
    """The greenhouse with a sprinkler and a vent; its program turns on the switches of `keys`."""
    await fake(hass, "switch.greenhouse_vent", "off")
    program = {"name": "Limpar", "sequence": [{"turn_on": f"switches.{key}"} for key in keys]}
    assert await setup(hass, {KEY: {"name": "Estufa", "switches": TWO_SWITCHES,
                                    "programs": {"executable": {"clean": program}}}})


def counting_reloads(hass: HomeAssistant) -> Any:
    """Count the entry's reloads, pururu's own and HA's."""
    return patch.object(hass.config_entries, "async_reload",
                        wraps=hass.config_entries.async_reload)


async def test_disabling_an_entity_no_program_acts_on_reloads_nothing(
        scripts: HomeAssistant, freezer: Any) -> None:
    await two_switches(scripts, "sprinkler")
    with counting_reloads(scripts) as reloads:
        await disable(scripts, VENT)
        await tick(scripts, freezer, 31)
        await scripts.async_block_till_done()
    assert reloads.call_count == 0
    assert scripts.states.get(CLEAN) is not None


async def test_enabling_a_target_again_reloads_once(
        greenhouse: HomeAssistant, freezer: Any) -> None:
    """HA's own reload: pururu doesn't add one."""
    await disable(greenhouse, SPRINKLER)
    await tick(greenhouse, freezer, 31)
    await greenhouse.async_block_till_done()
    with counting_reloads(greenhouse) as reloads:
        await disable(greenhouse, SPRINKLER, disabled=False)
        await tick(greenhouse, freezer, 31)
        await greenhouse.async_block_till_done()
    assert reloads.call_count == 1
    assert greenhouse.states.get(CLEAN) is not None


async def test_a_target_is_followed_when_a_later_generated_kind_fails(
        scripts: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    """The scripts are written before the notifications fail: disabling their target still rebuilds."""
    await fake(scripts, REAL_SPRINKLER, "off")
    with patch.object(module("aspects.notifications"), "plan", side_effect=RuntimeError("boom")):
        assert await setup(scripts, devices())
    assert "Step generate failed" in caplog.text
    caplog.clear()  # expected: the autouse fixture would fail on it
    with counting_reloads(scripts) as reloads:
        await disable(scripts, SPRINKLER)
        await tick(scripts, freezer, 31)
        await scripts.async_block_till_done()
    assert reloads.call_count == 1


async def test_disabling_several_targets_at_once_reloads_once(
        scripts: HomeAssistant, freezer: Any) -> None:
    await two_switches(scripts, "sprinkler", "vent")
    registry = er.async_get(scripts)
    with counting_reloads(scripts) as reloads:
        for entity_id in (SPRINKLER, VENT):
            registry.async_update_entity(entity_id, disabled_by=er.RegistryEntryDisabler.USER)
        await tick(scripts, freezer, 31)
        await scripts.async_block_till_done()
    assert reloads.call_count == 1
    assert_held_out(scripts, CLEAN)


async def test_disabling_the_device_reloads_once(scripts: HomeAssistant, freezer: Any) -> None:
    """HA disables each of its entities in turn: one reload drops the program."""
    await two_switches(scripts, "sprinkler", "vent")
    device = device_of(scripts, KEY)
    assert device is not None
    with counting_reloads(scripts) as reloads:
        dr.async_get(scripts).async_update_device(device.id,
                                                  disabled_by=dr.DeviceEntryDisabler.USER)
        await tick(scripts, freezer, 31)
        await scripts.async_block_till_done()
    assert reloads.call_count == 1
    assert_held_out(scripts, CLEAN)


# --- reloads, renames, taken IDs, upgrades ------------------------------------------------


async def test_a_reload_keeps_an_unchanged_program_running(greenhouse: HomeAssistant, freezer: Any) -> None:
    calls = capture(greenhouse, "call_service")
    await start(greenhouse)
    await reload_while_running(greenhouse, devices())
    await tick(greenhouse, freezer, TWO_HOURS)
    assert reached(calls) == ["turn_on", "turn_off"]


async def test_a_reload_that_changes_the_program_stops_it(greenhouse: HomeAssistant, freezer: Any) -> None:
    """HA loads the new script: what the old one did stays, the sprinkler stays on."""
    longer = {**CLEANING, "sequence": [
        {"turn_on": "switches.sprinkler"}, {"delay": {"hours": 3}}, {"turn_off": "switches.sprinkler"}]}
    calls = capture(greenhouse, "call_service")
    await start(greenhouse)
    await reload_while_running(greenhouse, devices(clean=longer))
    await tick(greenhouse, freezer, TWO_HOURS)
    assert reached(calls) == ["turn_on"]
    assert greenhouse.states.get(CLEAN).state == "off"


async def test_a_reload_that_drops_it_removes_it(greenhouse: HomeAssistant) -> None:
    await reload(greenhouse, {KEY: {"name": "Estufa", "switches": SWITCHES}})
    assert generated_scripts(greenhouse) == {}
    assert greenhouse.states.get(CLEAN) is None
    assert er.async_get(greenhouse).async_get(CLEAN) is None
    assert greenhouse.config_entries.async_entries("pururu")[0].data["scripts"] == []


async def test_it_follows_its_target_renamed(greenhouse: HomeAssistant) -> None:
    er.async_get(greenhouse).async_update_entity(SPRINKLER, new_entity_id="switch.estufa_irrigador")
    await greenhouse.async_block_till_done()
    calls = capture(greenhouse, "call_service")
    await start(greenhouse)
    assert reached(calls, "switch.estufa_irrigador") == ["turn_on"]
    assert reached(calls) == ["turn_on"]


async def test_renamed_it_still_runs_and_stays_renamed(greenhouse: HomeAssistant) -> None:
    er.async_get(greenhouse).async_update_entity(CLEAN, new_entity_id="script.limpar_estufa")
    await greenhouse.async_block_till_done()
    calls = capture(greenhouse, "call_service")
    await start(greenhouse, "script.limpar_estufa")
    assert reached(calls) == ["turn_on"]
    await reload_while_running(greenhouse, devices())
    renamed = er.async_get(greenhouse).async_get("script.limpar_estufa")
    assert renamed is not None
    assert renamed.unique_id == "pururu_greenhouse_program_executable_clean"
    assert greenhouse.states.get(CLEAN) is None


async def test_an_id_taken_by_another_integration_is_not_generated(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(
        "script", "template", "someone_else", suggested_object_id="pururu_greenhouse_program_executable_clean")
    assert await setup(ha, devices())
    assert generated_scripts(ha) == {}
    assert (f"{CLEAN} is already taken by the template integration; "
            "not generating it") in caplog.text


async def test_a_script_of_ones_own_with_the_same_id_is_not_adopted(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(
        "script", "script", "pururu_greenhouse_program_executable_clean", suggested_object_id="mine")
    assert await setup(ha, devices())
    assert generated_scripts(ha) == {}
    assert (f"{CLEAN} is already taken by script.mine, a script with the same ID; "
            "not generating it") in caplog.text


async def test_a_program_whose_target_is_not_created_is_not_generated(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(
        "switch", "template", "someone_else", suggested_object_id="pururu_greenhouse_switch_sprinkler")
    assert await setup(ha, devices())
    assert generated_scripts(ha) == {}
    assert f"{CLEAN} follows {SPRINKLER}, which is not created; not generating it" in caplog.text


async def test_the_update_leaves_no_old_id(scripts: HomeAssistant) -> None:
    """0.2.0 before D3: script.pururu_<device>_program_<key> and its sensors; after it, only the program_executable_ ones.

    The old script is a generated item the entry managed: dropped from the file,
    its registry entry goes once HA no longer runs it. The old sensors are stale.
    """
    old = "pururu_greenhouse_program_clean"
    path = Path(scripts.config.path(SCRIPTS))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({old: {"alias": "Estufa Limpar", "sequence": [{"delay": 1}]}}))
    await scripts.services.async_call("script", "reload", blocking=True)
    registry = er.async_get(scripts)
    assert registry.async_get_entity_id("script", "script", old) is not None
    entry = MockConfigEntry(domain=DOMAIN, source="import", data={"scripts": [old]})
    entry.add_to_hass(scripts)
    registry.async_get_or_create("sensor", DOMAIN, f"{old}_cycles_total", config_entry=entry,
                                 suggested_object_id=f"{old}_cycles_total")
    await fake(scripts, REAL_SPRINKLER, "off")
    assert await setup(scripts, devices())
    assert registry.async_get_entity_id("script", "script", old) is None
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{old}_cycles_total") is None
    assert registry.async_get(CLEAN) is not None
    assert registry.async_get(STAT + "cycles_total") is not None
    assert entry.data["scripts"] == ["pururu_greenhouse_program_executable_clean"]


async def test_the_old_button_is_removed(ha: HomeAssistant) -> None:
    """Up to 0.1.14 a program was button.pururu_<device>_program_<key>."""
    entry = MockConfigEntry(domain="pururu", source="import", data={})
    entry.add_to_hass(ha)
    er.async_get(ha).async_get_or_create(
        "button", "pururu", "pururu_greenhouse_program_clean", config_entry=entry,
        suggested_object_id="pururu_greenhouse_program_clean")
    assert await setup(ha, devices())
    assert er.async_get(ha).async_get("button.pururu_greenhouse_program_clean") is None


# --- statistics --------------------------------------------------------------------

STAT = "sensor.pururu_greenhouse_program_executable_clean_"


def value(hass: HomeAssistant, suffix: str) -> str:
    state = hass.states.get(STAT + suffix)
    assert state is not None, f"no {STAT}{suffix}"
    return state.state


async def test_a_run_is_a_cycle(greenhouse: HomeAssistant, freezer: Any) -> None:
    await start(greenhouse)
    started = dt_util.utcnow()
    assert value(greenhouse, "cycles_total") == "0"
    await tick(greenhouse, freezer, TWO_HOURS)
    await greenhouse.async_block_till_done()
    assert value(greenhouse, "cycles_total") == "1"
    assert value(greenhouse, "last_cycle_duration") == "120.0"
    assert dt_util.parse_datetime(value(greenhouse, "last_cycle_start")) == started
    assert dt_util.parse_datetime(value(greenhouse, "last_cycle_end")) == dt_util.utcnow()
    assert float(value(greenhouse, "runtime_total")) == pytest.approx(2, abs=0.01)


async def test_a_run_counts_itself_before_it_sends_its_cycle(
    scripts: HomeAssistant, freezer: Any
) -> None:
    """cycles_total already carries the run when the cycle signal fires: Runs counts itself, then sends.

    The probe connects to the signal before pururu's own setup does (a
    dispatcher calls its listeners in the order they connected), so it runs
    before anything Runs itself connects: a stale write, were `_send` still
    to make one, would show here.
    """
    cycle = module("features.cycle")
    device = module("core.feature").Device(key=KEY, name="Estufa", namespace="program")
    item = module("core.feature").Item(slug="executable_clean", name="Limpar")
    seen: list[str | None] = []

    @callback
    def record(_cycle: Any) -> None:
        state = scripts.states.get(STAT + "cycles_total")
        seen.append(state.state if state is not None else None)

    async_dispatcher_connect(scripts, cycle.cycle_signal(device, item), record)
    await fake(scripts, REAL_SPRINKLER, "off")
    assert await setup(scripts, devices())
    await start(scripts)
    await tick(scripts, freezer, TWO_HOURS)
    await scripts.async_block_till_done()
    assert seen == ["1"]


async def test_its_statistics_are_named_by_the_program(greenhouse: HomeAssistant) -> None:
    state = greenhouse.states.get(STAT + "cycles_total")
    assert state is not None
    assert state.attributes["friendly_name"] == "Estufa Limpar cycles"


async def test_meters_are_asked_for(scripts: HomeAssistant) -> None:
    program = {**CLEANING, "statistics": {"runtime": ["today"], "cycles": ["month", "year"]}}
    assert await setup(scripts, devices(clean=program))
    for suffix in ("runtime_today", "cycles_month", "cycles_year"):
        assert scripts.states.get(STAT + suffix) is not None, suffix
    assert scripts.states.get(STAT + "runtime_week") is None


async def test_a_program_keyed_statistics_is_a_program(scripts: HomeAssistant) -> None:
    """A program keyed like the statistics aspect is a program, with statistics of its own."""
    program = {**CLEANING, "statistics": {"cycles": ["today"]}}
    assert await setup(scripts, devices(statistics=program))
    assert scripts.states.get(
        "sensor.pururu_greenhouse_program_executable_statistics_cycles_today") is not None


def test_a_whole_number_key_keeps_its_statistics(ha: HomeAssistant) -> None:
    """YAML reads a program keyed 1 (a reaction keyed 2) as an int; cv.slug makes it "1": its statistics follow."""
    statistics = {"cycles": ["today"]}
    house = {"devices": {KEY: {
        "name": "Estufa",
        "programs": {"executable": {1: {"name": "Limpar", "sequence": [{"delay": 1}], "statistics": statistics}}},
        "reactions": {2: {"name": "Noite", "at": "22:00", "statistics": {"triggered": ["week"]}}},
        "switches": {"sprinkler": {"entity": f"homeassistant.{REAL_SPRINKLER}", "name": "Irrigador"}},
    }}}
    device = module("setup.schema").CONFIG_SCHEMA({DOMAIN: house})[DOMAIN]["devices"][KEY]
    assert device["programs"]["executable"]["1"]["statistics"] == {"runtime": [], "cycles": ["today"]}
    assert device["reactions"]["2"]["statistics"] == {"triggered": ["week"]}


@pytest.mark.parametrize("statistics", [
    {"runtime": ["today", "today"]}, {"runs": ["today"]}, {"cycles": ["daily"]}])
async def test_invalid_statistics_are_refused(ha: HomeAssistant, statistics: dict[str, Any]) -> None:
    assert not await setup(ha, devices(clean={**CLEANING, "statistics": statistics}))


async def test_a_reload_mid_run_counts_it_once_from_its_start(greenhouse: HomeAssistant,
                                                              freezer: Any) -> None:
    await start(greenhouse)
    started = dt_util.utcnow()
    await tick(greenhouse, freezer, 60)
    await reload_while_running(greenhouse, devices())
    await tick(greenhouse, freezer, TWO_HOURS - 60)
    await greenhouse.async_block_till_done()
    assert value(greenhouse, "cycles_total") == "1"
    assert dt_util.parse_datetime(value(greenhouse, "last_cycle_start")) == started


async def test_a_held_program_keeps_its_statistics(greenhouse: HomeAssistant, freezer: Any) -> None:
    """Held, its script leaves the file, not its statistics; back, it counts on from them."""
    await start(greenhouse)
    await tick(greenhouse, freezer, TWO_HOURS)
    await greenhouse.async_block_till_done()
    await disable(greenhouse, SPRINKLER)
    await tick(greenhouse, freezer, 31)
    await greenhouse.async_block_till_done()
    assert generated_scripts(greenhouse) == {}
    assert er.async_get(greenhouse).async_get(STAT + "cycles_total") is not None
    assert value(greenhouse, "cycles_total") == "1"
    await disable(greenhouse, SPRINKLER, disabled=False)
    await tick(greenhouse, freezer, 31)
    await greenhouse.async_block_till_done()
    assert "pururu_greenhouse_program_executable_clean" in generated_scripts(greenhouse)
    await start(greenhouse)
    await tick(greenhouse, freezer, TWO_HOURS)
    await greenhouse.async_block_till_done()
    assert value(greenhouse, "cycles_total") == "2"


async def test_a_program_or_reaction_keyed_alerts_is_no_ready_made_alert(
        scripts: HomeAssistant) -> None:
    """`alerts` is a slug like any other: not the ready-made alerts a feature's block enables."""
    config = devices(alerts=CLEANING)
    config[KEY]["reactions"] = {"alerts": {"name": "A", "at": "22:00"}}
    assert await setup(scripts, config)
    assert value_of(scripts, "sensor.pururu_greenhouse_program_executable_alerts_cycles_total") == "0"
    assert value_of(scripts, "sensor.pururu_greenhouse_reaction_alerts_triggered_total") == "0"


def value_of(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, f"no {entity_id}"
    return state.state


async def test_a_removed_program_takes_its_statistics(greenhouse: HomeAssistant) -> None:
    wash = {"name": "Lavar", "sequence": [{"turn_on": "switches.sprinkler"}]}
    await reload(greenhouse, devices(wash=wash))
    assert er.async_get(greenhouse).async_get(STAT + "cycles_total") is None
    assert er.async_get(greenhouse).async_get("sensor.pururu_greenhouse_program_executable_wash_cycles_total") is not None


async def test_its_statistics_follow_the_script_renamed(greenhouse: HomeAssistant, freezer: Any) -> None:
    er.async_get(greenhouse).async_update_entity(CLEAN, new_entity_id="script.limpar_estufa")
    await greenhouse.async_block_till_done()
    await start(greenhouse, "script.limpar_estufa")
    await tick(greenhouse, freezer, TWO_HOURS)
    await greenhouse.async_block_till_done()
    assert value(greenhouse, "cycles_total") == "1"


async def test_statistics_never_follow_a_script_pururu_does_not_generate(
        ha: HomeAssistant, freezer: Any) -> None:
    """Its ID taken by another integration: the program isn't generated, and that script isn't counted."""
    er.async_get(ha).async_get_or_create(
        "script", "template", "someone_else", suggested_object_id="pururu_greenhouse_program_executable_clean")
    assert await setup(ha, devices())
    await fake(ha, CLEAN, "on")
    await tick(ha, freezer, 60 * 60)
    await fake(ha, CLEAN, "off")
    assert value(ha, "cycles_total") == "0"
    assert float(value(ha, "runtime_total")) == 0
