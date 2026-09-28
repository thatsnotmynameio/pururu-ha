"""Programs: a made-up pool's cleaning, turning its pump on for two hours, as an HA script."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

from homeassistant.core import Context, Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from helpers import DOMAIN, capture, device_of, fake, generated, generated_scripts, held, reload, settle, setup, tick

KEY = "pool"
REAL_PUMP = "switch.pool_pump"
PUMP = "switch.pururu_pool_switch_pump"
CLEAN = "script.pururu_pool_program_clean"
SWITCHES: dict[str, Any] = {"pump": {"entity": REAL_PUMP, "name": "Bomba"}}
TWO_HOURS = 2 * 60 * 60
CLEANING: dict[str, Any] = {"name": "Limpar", "sequence": [
    {"turn_on": "switch_pump"}, {"delay": {"hours": 2}}, {"turn_off": "switch_pump"}]}
APPLIANCE = {"power": "sensor.pool_pump_power",
             "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}}}


def devices(**programs: Any) -> dict[str, Any]:
    return {KEY: {"name": "Piscina", "switches": SWITCHES, "programs": programs or {"clean": CLEANING}}}


def reached(calls: list[Event], entity_id: str = REAL_PUMP) -> list[str]:
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
async def pool(scripts: HomeAssistant) -> HomeAssistant:
    await fake(scripts, REAL_PUMP, "off")
    assert await setup(scripts, devices())
    return scripts


# --- schema and the device ---------------------------------------------------------


@pytest.mark.parametrize("program", [
    pytest.param({"name": "Limpar"}, id="no sequence"),
    pytest.param({"name": "Limpar", "sequence": []}, id="empty sequence"),
    pytest.param({"sequence": [{"turn_on": "switch_pump"}]}, id="no name"),
    pytest.param({"name": " ", "sequence": [{"turn_on": "switch_pump"}]}, id="blank name"),
    pytest.param({"name": "Limpar", "sequence": [{"action": "switch.turn_on"}]}, id="an HA action"),
    pytest.param({"name": "Limpar", "sequence": [{"turn_on": "switch_pump", "delay": 5}]},
                 id="two keys in a step"),
    pytest.param({"name": "Limpar", "sequence": [{}]}, id="an empty step"),
    pytest.param({"name": "Limpar", "sequence": ["turn_on"]}, id="a step that isn't a mapping"),
    pytest.param({"name": "Limpar", "sequence": [{"delay": -5}]}, id="a negative delay"),
    pytest.param({"name": "Limpar", "sequence": [{"turn_on": REAL_PUMP}]}, id="a real entity ID"),
    pytest.param({"name": "Limpar", "sequence": [{"turn_on": "switch_pump"}], "icon": "mdi:pool"},
                 id="unknown key"),
])
async def test_invalid_program_is_refused(ha: HomeAssistant, program: dict[str, Any]) -> None:
    assert not await setup(ha, devices(clean=program))


@pytest.mark.parametrize("target", [
    pytest.param("switch_pool_pump", id="not an entity key of the device"),
    pytest.param("switch_heater", id="a switch the device doesn't have"),
    pytest.param("program_clean", id="a program"),
])
async def test_a_target_not_of_another_feature_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, target: str) -> None:
    assert not await setup(ha, devices(clean={"name": "Limpar", "sequence": [{"turn_on": target}]}))
    assert f"programs: {target} is not an entity key of another feature of this device" in caplog.text


async def test_programs_alone_are_not_a_feature(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    assert not await setup(ha, {KEY: {"name": "Piscina", "programs": {"clean": CLEANING}}})
    assert "a device needs at least one feature" in caplog.text


async def test_an_action_the_target_does_not_take_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    program = {"name": "Ligar", "sequence": [{"turn_on": "appliance_power"}]}
    assert not await setup(ha, {KEY: {"name": "Piscina", "appliance": APPLIANCE,
                                      "programs": {"start": program}}})
    assert "programs: appliance_power does not take turn_on" in caplog.text


async def test_two_programs_with_one_script_id_are_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """pool's b_program_c and pool_program_b's c would both be pururu_pool_program_b_program_c."""
    config = devices(b_program_c=CLEANING)
    config["pool_program_b"] = {
        "name": "Outra", "switches": {"x": {"entity": "switch.demo_x", "name": "X"}},
        "programs": {"c": {"name": "C", "sequence": [{"turn_on": "switch_x"}]}},
    }
    assert not await setup(ha, config)
    assert ("device pool_program_b: script.pururu_pool_program_b_program_c is already "
            "a program of device pool") in caplog.text


# --- the generated script ------------------------------------------------------------


async def test_the_file_holds_a_script_per_program(ha: HomeAssistant) -> None:
    assert await setup(ha, devices())
    assert generated_scripts(ha) == {"pururu_pool_program_clean": {
        "alias": "Piscina Limpar",
        "description": "pururu: pool, clean",
        "mode": "single",
        "sequence": [
            {"action": "switch.turn_on", "target": {"entity_id": PUMP}},
            {"delay": "02:00:00"},
            {"action": "switch.turn_off", "target": {"entity_id": PUMP}},
        ],
    }}
    cv.SCRIPT_SCHEMA(generated_scripts(ha)["pururu_pool_program_clean"]["sequence"])


async def test_it_is_a_script_named_by_the_configuration(pool: HomeAssistant) -> None:
    state = pool.states.get(CLEAN)
    assert state is not None
    assert state.state == "off"
    assert state.attributes["friendly_name"] == "Piscina Limpar"
    entry = er.async_get(pool).async_get(CLEAN)
    assert entry is not None
    assert (entry.platform, entry.unique_id) == ("script", "pururu_pool_program_clean")
    assert held(pool, KEY) == {PUMP}
    assert pool.states.async_entity_ids("button") == []


async def test_it_is_in_its_devices_area(scripts: HomeAssistant) -> None:
    config = devices()
    config[KEY]["area"] = "quintal"
    assert await setup(scripts, config, areas={"quintal": {"name": "Quintal"}})
    entry = er.async_get(scripts).async_get(CLEAN)
    assert entry is not None
    assert entry.area_id == "quintal"


# --- running -------------------------------------------------------------------------


async def test_turning_it_on_runs_the_sequence(pool: HomeAssistant, freezer: Any) -> None:
    calls = capture(pool, "call_service")
    await start(pool)
    assert reached(calls) == ["turn_on"]
    await tick(pool, freezer, TWO_HOURS - 1)
    assert reached(calls) == ["turn_on"]
    await tick(pool, freezer, 1)
    assert reached(calls) == ["turn_on", "turn_off"]


async def test_toggle_flips_the_switch(scripts: HomeAssistant) -> None:
    await fake(scripts, REAL_PUMP, "on")
    assert await setup(scripts, devices(flip={"name": "Inverter", "sequence": [{"toggle": "switch_pump"}]}))
    calls = capture(scripts, "call_service")
    await start(scripts, "script.pururu_pool_program_flip")
    assert reached(calls) == ["turn_off"]


@pytest.mark.parametrize(("real", "attributes"), [
    pytest.param("light.sala_teto", {"supported_color_modes": ["onoff"], "color_mode": "onoff"},
                 id="a real light"),
    pytest.param("switch.sonoff_teto", {}, id="a relay driving a lamp"),
])
async def test_it_turns_a_light_on_and_off(
        scripts: HomeAssistant, freezer: Any, real: str, attributes: dict[str, Any]) -> None:
    await fake(scripts, real, "off", attributes)
    evening = {"name": "Noite", "sequence": [
        {"turn_on": "light_teto"}, {"delay": {"minutes": 30}}, {"turn_off": "light_teto"}]}
    assert await setup(scripts, {"sala": {"name": "Sala",
                                          "lights": {"teto": {"entity": real, "name": "Teto"}},
                                          "programs": {"evening": evening}}})
    calls = capture(scripts, "call_service")
    await start(scripts, "script.pururu_sala_program_evening")
    await tick(scripts, freezer, 30 * 60)
    assert reached(calls, real) == ["turn_on", "turn_off"]


async def test_it_returns_at_once_and_is_on_while_it_runs(pool: HomeAssistant) -> None:
    """As before with the button: an automation starting it doesn't wait two hours."""
    async with asyncio.timeout(5):
        await pool.services.async_call("script", "turn_on", {"entity_id": CLEAN}, blocking=True)
    await settle()
    assert pool.states.get(CLEAN).state == "on"


async def test_turning_it_off_stops_it(pool: HomeAssistant, freezer: Any) -> None:
    calls = capture(pool, "call_service")
    await start(pool)
    await tick(pool, freezer, 60)
    await pool.services.async_call("script", "turn_off", {"entity_id": CLEAN}, blocking=True)
    await settle()
    assert pool.states.get(CLEAN).state == "off"
    await tick(pool, freezer, TWO_HOURS)
    assert reached(calls) == ["turn_on"]


async def test_what_it_does_carries_the_callers_context(pool: HomeAssistant) -> None:
    """The logbook names who started it."""
    calls = capture(pool, "call_service")
    context = Context()
    await start(pool, context=context)
    real = [event for event in calls if reached([event]) == ["turn_on"]]
    assert real
    assert all(context.id in (event.context.id, event.context.parent_id) for event in real)


async def test_starting_it_while_it_runs_is_ignored(
        pool: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    """A blocking script.turn_on on an already-running single-mode script returns at its
    next change (its next step, or its end), not at once: under frozen time that's two
    hours away, so this second call is non-blocking instead."""
    calls = capture(pool, "call_service")
    await start(pool)
    await tick(pool, freezer, 60)
    await pool.services.async_call("script", "turn_on", {"entity_id": CLEAN}, blocking=False)
    await settle()
    assert "Piscina Limpar: Already running" in caplog.text
    await tick(pool, freezer, TWO_HOURS)
    assert reached(calls) == ["turn_on", "turn_off"]


async def test_an_unavailable_switch_does_not_stop_it(scripts: HomeAssistant, freezer: Any) -> None:
    """No real switch: the pururu switch is unavailable, HA skips it, the program goes on."""
    assert await setup(scripts, devices())
    calls = capture(scripts, "call_service")
    await start(scripts)
    await tick(scripts, freezer, TWO_HOURS)
    assert reached(calls, PUMP) == ["turn_on", "turn_off"]


async def test_a_failing_step_stops_it_and_is_logged(
        pool: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    """A step's failure raises inside the background task script.turn_on's domain service
    starts and never awaits (it only waits for the run to start): retrieve its exception
    ourselves, so HA's test harness doesn't also flag it as "never retrieved" at teardown."""
    calls = capture(pool, "call_service")
    created: list[asyncio.Task[Any]] = []
    original = pool.async_create_task_internal

    def capture_task(coro: Any, name: str | None = None, eager_start: bool = True) -> Any:
        task = original(coro, name, eager_start)
        if isinstance(task, asyncio.Task):
            created.append(task)
        return task

    pool.async_create_task_internal = capture_task
    try:
        with patch("homeassistant.components.group.switch.SwitchGroup.async_turn_on",
                   side_effect=HomeAssistantError("the relay is stuck")):
            await start(pool)
        await tick(pool, freezer, TWO_HOURS)
    finally:
        pool.async_create_task_internal = original
    for task in created:
        if task.done() and not task.cancelled():
            task.exception()
    assert reached(calls, PUMP) == ["turn_on"]
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any("Piscina Limpar" in message and "the relay is stuck" in message
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
        pool: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    """A script that looks usable and does part of its job would mislead: it goes, logged.

    HA's own config entry reload-on-disable only fires when an entity is
    *re-enabled* (config_entries.py's disable handler explicitly skips scheduling
    one while the entity stays disabled); pururu's own registry listener in
    async_setup_entry schedules the reload here instead.
    """
    await disable(pool, PUMP)
    await tick(pool, freezer, 31)
    await pool.async_block_till_done()
    assert generated_scripts(pool) == {}
    assert_held_out(pool, CLEAN)
    assert f"{CLEAN} acts on {PUMP}, which is disabled; not generating it" in caplog.text


async def test_it_comes_back_when_the_target_is_enabled(pool: HomeAssistant, freezer: Any) -> None:
    await disable(pool, PUMP)
    await tick(pool, freezer, 31)
    await disable(pool, PUMP, disabled=False)
    await tick(pool, freezer, 31)
    await pool.async_block_till_done()
    calls = capture(pool, "call_service")
    await start(pool)
    assert reached(calls) == ["turn_on"]


async def set_target(hass: HomeAssistant, freezer: Any, disabled: bool) -> None:
    await disable(hass, PUMP, disabled)
    await tick(hass, freezer, 31)
    await hass.async_block_till_done()


async def test_a_program_the_user_disabled_stays_disabled_once_its_target_is_back(
        pool: HomeAssistant, freezer: Any) -> None:
    """Held while its target is disabled, not dropped: its registry entry stays as the user set it.

    Not left to HA's restore of a deleted entry's settings on re-creation: that
    one lasts 30 days for an entry without a config entry, and then is purged.
    """
    registry = er.async_get(pool)
    before = registry.async_get(CLEAN)
    assert before is not None
    registry.async_update_entity(CLEAN, disabled_by=er.RegistryEntryDisabler.USER)
    await tick(pool, freezer, 31)
    await pool.async_block_till_done()
    await set_target(pool, freezer, disabled=True)
    held_entry = registry.async_get(CLEAN)
    assert held_entry is not None
    assert held_entry.id == before.id
    assert held_entry.disabled_by is er.RegistryEntryDisabler.USER
    await set_target(pool, freezer, disabled=False)
    after = registry.async_get(CLEAN)
    assert after is not None
    assert after.id == before.id
    assert after.disabled_by is er.RegistryEntryDisabler.USER
    assert pool.states.get(CLEAN) is None
    assert "pururu_pool_program_clean" in generated_scripts(pool)


async def test_a_program_renamed_keeps_its_entity_id_once_its_target_is_back(
        pool: HomeAssistant, freezer: Any) -> None:
    registry = er.async_get(pool)
    registry.async_update_entity(CLEAN, new_entity_id="script.limpar_piscina")
    await pool.async_block_till_done()
    await set_target(pool, freezer, disabled=True)
    assert_held_out(pool, "script.limpar_piscina")
    assert registry.async_get_entity_id(
        "script", "script", "pururu_pool_program_clean") == "script.limpar_piscina"
    await set_target(pool, freezer, disabled=False)
    assert pool.states.get(CLEAN) is None
    calls = capture(pool, "call_service")
    await start(pool, "script.limpar_piscina")
    assert reached(calls) == ["turn_on"]


async def test_a_held_program_stays_tracked_without_a_repairs_issue(
        pool: HomeAssistant, freezer: Any) -> None:
    await set_target(pool, freezer, disabled=True)
    assert_held_out(pool, CLEAN)
    assert er.async_get(pool).async_get(CLEAN) is not None
    assert pool.config_entries.async_entries("pururu")[0].data["scripts"] == [
        "pururu_pool_program_clean"]
    assert ir.async_get(pool).async_get_issue(DOMAIN, "scripts_not_included") is None
    calls = capture(pool, "call_service")
    await start(pool)
    assert reached(calls) == []  # held out: starting it does nothing


FILTER = "switch.pururu_pool_switch_filter"
TWO_SWITCHES: dict[str, Any] = {**SWITCHES, "filter": {"entity": "switch.pool_filter", "name": "Filtro"}}


async def two_switches(hass: HomeAssistant, *keys: str) -> None:
    """The pool with a pump and a filter; its program turns on the switches of `keys`."""
    await fake(hass, "switch.pool_filter", "off")
    program = {"name": "Limpar", "sequence": [{"turn_on": f"switch_{key}"} for key in keys]}
    assert await setup(hass, {KEY: {"name": "Piscina", "switches": TWO_SWITCHES,
                                    "programs": {"clean": program}}})


def counting_reloads(hass: HomeAssistant) -> Any:
    """Count the entry's reloads, pururu's own and HA's."""
    return patch.object(hass.config_entries, "async_reload",
                        wraps=hass.config_entries.async_reload)


async def test_disabling_an_entity_no_program_acts_on_reloads_nothing(
        scripts: HomeAssistant, freezer: Any) -> None:
    await two_switches(scripts, "pump")
    with counting_reloads(scripts) as reloads:
        await disable(scripts, FILTER)
        await tick(scripts, freezer, 31)
        await scripts.async_block_till_done()
    assert reloads.call_count == 0
    assert scripts.states.get(CLEAN) is not None


async def test_enabling_a_target_again_reloads_once(
        pool: HomeAssistant, freezer: Any) -> None:
    """HA's own reload: pururu doesn't add one."""
    await disable(pool, PUMP)
    await tick(pool, freezer, 31)
    await pool.async_block_till_done()
    with counting_reloads(pool) as reloads:
        await disable(pool, PUMP, disabled=False)
        await tick(pool, freezer, 31)
        await pool.async_block_till_done()
    assert reloads.call_count == 1
    assert pool.states.get(CLEAN) is not None


async def test_disabling_several_targets_at_once_reloads_once(
        scripts: HomeAssistant, freezer: Any) -> None:
    await two_switches(scripts, "pump", "filter")
    registry = er.async_get(scripts)
    with counting_reloads(scripts) as reloads:
        for entity_id in (PUMP, FILTER):
            registry.async_update_entity(entity_id, disabled_by=er.RegistryEntryDisabler.USER)
        await tick(scripts, freezer, 31)
        await scripts.async_block_till_done()
    assert reloads.call_count == 1
    assert_held_out(scripts, CLEAN)


async def test_disabling_the_device_reloads_once(scripts: HomeAssistant, freezer: Any) -> None:
    """HA disables each of its entities in turn: one reload drops the program."""
    await two_switches(scripts, "pump", "filter")
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


async def test_a_reload_keeps_an_unchanged_program_running(pool: HomeAssistant, freezer: Any) -> None:
    calls = capture(pool, "call_service")
    await start(pool)
    await reload_while_running(pool, devices())
    await tick(pool, freezer, TWO_HOURS)
    assert reached(calls) == ["turn_on", "turn_off"]


async def test_a_reload_that_changes_the_program_stops_it(pool: HomeAssistant, freezer: Any) -> None:
    """HA loads the new script: what the old one did stays, the pump stays on."""
    longer = {**CLEANING, "sequence": [
        {"turn_on": "switch_pump"}, {"delay": {"hours": 3}}, {"turn_off": "switch_pump"}]}
    calls = capture(pool, "call_service")
    await start(pool)
    await reload_while_running(pool, devices(clean=longer))
    await tick(pool, freezer, TWO_HOURS)
    assert reached(calls) == ["turn_on"]
    assert pool.states.get(CLEAN).state == "off"


async def test_a_reload_that_drops_it_removes_it(pool: HomeAssistant) -> None:
    await reload(pool, {KEY: {"name": "Piscina", "switches": SWITCHES}})
    assert generated_scripts(pool) == {}
    assert pool.states.get(CLEAN) is None
    assert er.async_get(pool).async_get(CLEAN) is None
    assert pool.config_entries.async_entries("pururu")[0].data["scripts"] == []


async def test_it_follows_its_target_renamed(pool: HomeAssistant) -> None:
    er.async_get(pool).async_update_entity(PUMP, new_entity_id="switch.piscina_bomba")
    await pool.async_block_till_done()
    calls = capture(pool, "call_service")
    await start(pool)
    assert reached(calls, "switch.piscina_bomba") == ["turn_on"]
    assert reached(calls) == ["turn_on"]


async def test_renamed_it_still_runs_and_stays_renamed(pool: HomeAssistant) -> None:
    er.async_get(pool).async_update_entity(CLEAN, new_entity_id="script.limpar_piscina")
    await pool.async_block_till_done()
    calls = capture(pool, "call_service")
    await start(pool, "script.limpar_piscina")
    assert reached(calls) == ["turn_on"]
    await reload_while_running(pool, devices())
    renamed = er.async_get(pool).async_get("script.limpar_piscina")
    assert renamed is not None
    assert renamed.unique_id == "pururu_pool_program_clean"
    assert pool.states.get(CLEAN) is None


async def test_an_id_taken_by_another_integration_is_not_generated(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(
        "script", "template", "someone_else", suggested_object_id="pururu_pool_program_clean")
    assert await setup(ha, devices())
    assert generated_scripts(ha) == {}
    assert (f"{CLEAN} is already taken by the template integration; "
            "not generating it") in caplog.text


async def test_a_script_of_ones_own_with_the_same_id_is_not_adopted(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(
        "script", "script", "pururu_pool_program_clean", suggested_object_id="mine")
    assert await setup(ha, devices())
    assert generated_scripts(ha) == {}
    assert (f"{CLEAN} is already taken by script.mine, a script with the same ID; "
            "not generating it") in caplog.text


async def test_a_program_whose_target_is_not_created_is_not_generated(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(
        "switch", "template", "someone_else", suggested_object_id="pururu_pool_switch_pump")
    assert await setup(ha, devices())
    assert generated_scripts(ha) == {}
    assert f"{CLEAN} follows {PUMP}, which is not created; not generating it" in caplog.text


async def test_the_old_button_is_removed(ha: HomeAssistant) -> None:
    """Up to 0.1.14 a program was button.pururu_<device>_program_<key>."""
    entry = MockConfigEntry(domain="pururu", source="import", data={})
    entry.add_to_hass(ha)
    er.async_get(ha).async_get_or_create(
        "button", "pururu", "pururu_pool_program_clean", config_entry=entry,
        suggested_object_id="pururu_pool_program_clean")
    assert await setup(ha, devices())
    assert er.async_get(ha).async_get("button.pururu_pool_program_clean") is None
