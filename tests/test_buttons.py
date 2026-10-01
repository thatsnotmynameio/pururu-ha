"""Feature `buttons`: a made-up library's remote, its keys pressing buttons that start programs."""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

from homeassistant.core import Context, CoreState, HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from homeassistant.setup import async_setup_component
import pytest

from helpers import capture, fake, generated_scripts, held, reload, restart, settle, setup, tick

KEY = "biblioteca"
REMOTE = "sensor.controle_biblioteca_action"
LER = "button.pururu_biblioteca_button_ler"
EXTRA = "button.pururu_biblioteca_button_extra"
LER_TOTAL = "sensor.pururu_biblioteca_button_ler_triggered_total"
EXTRA_TOTAL = "sensor.pururu_biblioteca_button_extra_triggered_total"
BUTTONS: dict[str, Any] = {"ler": {"entity": REMOTE, "state": "1_single", "name": "Ler"},
                           "extra": {"entity": REMOTE, "state": "2_single", "name": "Extra"}}
DEVICES = {KEY: {"name": "Biblioteca", "buttons": BUTTONS}}
# A press the button recorded before a restart
PRESSED = "2026-09-16T09:00:00+00:00"


def state(hass: HomeAssistant, entity_id: str) -> str:
    return hass.states.get(entity_id).state


def now() -> str:
    """A press now, as a button records it."""
    return dt_util.utcnow().isoformat()


async def press(hass: HomeAssistant, entity_id: str, context: Context | None = None) -> None:
    """Press the button in Home Assistant.

    Settles rather than waiting for every task: a program it starts is HA's own task,
    and waiting for it would wait for the whole program.
    """
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True,
                                   context=context)
    await settle()


@pytest.fixture
async def library(ha: HomeAssistant) -> HomeAssistant:
    await fake(ha, REMOTE, "")
    assert await setup(ha, DEVICES)
    return ha


# --- schema ------------------------------------------------------------------


@pytest.mark.parametrize("block", [
    pytest.param({"ler": {"state": "1_single", "name": "Ler"}}, id="no entity"),
    pytest.param({"ler": {"entity": REMOTE, "name": "Ler"}}, id="no state"),
    pytest.param({"ler": {"entity": REMOTE, "state": "1_single"}}, id="no name"),
    pytest.param({"ler": {"entity": REMOTE, "state": "1_single", "name": "  "}}, id="blank name"),
    pytest.param({"ler": {"entity": REMOTE, "state": "  ", "name": "Ler"}}, id="blank state"),
    pytest.param({"ler": {"entity": "binary_sensor.controle", "state": "on", "name": "Ler"}},
                 id="another domain"),
    pytest.param({"ler": {"entity": "sensor.pururu_biblioteca_appliance_power", "state": "1",
                          "name": "Ler"}}, id="a pururu sensor"),
    pytest.param({"ler": {"entity": REMOTE, "state": "unavailable", "name": "Ler"}},
                 id="state unavailable"),
    pytest.param({"ler": {"entity": REMOTE, "state": "unknown", "name": "Ler"}}, id="state unknown"),
    pytest.param({"ler": {"entity": REMOTE, "state": "1_single", "name": "Ler", "icon": "mdi:book"}},
                 id="unknown key"),
    pytest.param({"Ler": {"entity": REMOTE, "state": "1_single", "name": "Ler"}}, id="key not a slug"),
    pytest.param({}, id="no button"),
])
async def test_invalid_block_is_refused(ha: HomeAssistant, block: dict[str, Any]) -> None:
    assert not await setup(ha, {KEY: {"name": "Biblioteca", "buttons": block}})


@pytest.mark.parametrize(("value", "message"), [
    pytest.param("unavailable", "unavailable is not a value a person presses", id="unavailable"),
    pytest.param("unknown", "unknown is not a value a person presses", id="unknown"),
])
async def test_the_error_names_the_refused_state(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, value: str, message: str) -> None:
    """The messages the docs quote (troubleshooting)."""
    assert not await setup(ha, {KEY: {"name": "Biblioteca", "buttons": {
        "ler": {"entity": REMOTE, "state": value, "name": "Ler"}}}})
    assert message in caplog.text


async def test_an_unquoted_on_is_the_state_on(ha: HomeAssistant) -> None:
    """YAML reads an unquoted on as true: the button's state is still `on`."""
    assert await setup(ha, {KEY: {"name": "Biblioteca", "buttons": {
        "ler": {"entity": REMOTE, "state": True, "name": "Ler"}}}})
    assert held(ha, KEY) == {LER, LER_TOTAL}


# --- what a block refers to (buttons.check) -------------------------------------------


async def test_a_program_of_another_device_is_refused(ha: HomeAssistant) -> None:
    """Covers AE8: a button starts its own device's executable programs only."""
    other = {"name": "Estufa", "switches": {"sprinkler": {"entity": "switch.x", "name": "X"}},
             "programs": {"executable": {"regar": {"name": "Regar", "sequence": [{"turn_on": "switch_sprinkler"}]}}}}
    assert not await setup(ha, {"estufa": other, KEY: {"name": "Biblioteca", "buttons": {
        "ler": {**BUTTONS["ler"], "program": "regar"}}}})


async def test_one_value_in_two_devices_is_accepted(ha: HomeAssistant) -> None:
    """A remote may press a button of each of two devices: each starts its own program."""
    assert await setup(ha, {KEY: {"name": "Biblioteca", "buttons": {"ler": BUTTONS["ler"]}},
                            "sala": {"name": "Sala", "buttons": {"ler": BUTTONS["ler"]}}})
    assert held(ha, "sala") == {"button.pururu_sala_button_ler",
                                "sensor.pururu_sala_button_ler_triggered_total"}


async def test_a_refusal_is_told_with_the_others(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    assert not await setup(ha, {KEY: {"name": "Biblioteca", "buttons": {
        "ler": {**BUTTONS["ler"], "program": "regar"}},
        "reactions": {"x": {"name": "X", "when": "nothing", "to": "on"}}}})
    assert "buttons: ler: regar is not an executable program of this device" in caplog.text
    assert "reactions: x: nothing is not an entity key of this device" in caplog.text


# --- the device ----------------------------------------------------------------


async def test_each_key_is_a_button_of_the_device(library: HomeAssistant) -> None:
    assert held(library, KEY) == {LER, EXTRA, LER_TOTAL, EXTRA_TOTAL}


async def test_a_button_is_named_by_its_name(library: HomeAssistant) -> None:
    assert library.states.get(LER).attributes["friendly_name"] == "Biblioteca Ler"
    assert er.async_get(library).async_get(LER).translation_key is None


async def test_a_button_keyed_button_repeats_it(ha: HomeAssistant) -> None:
    """No exception to the pattern: the namespace, then the key, even when they are alike."""
    assert await setup(ha, {KEY: {"name": "Biblioteca", "buttons": {"button": BUTTONS["ler"]}}})
    assert held(ha, KEY) == {"button.pururu_biblioteca_button_button",
                             "sensor.pururu_biblioteca_button_button_triggered_total"}


async def test_a_button_never_pressed_is_unknown(library: HomeAssistant) -> None:
    assert state(library, LER) == "unknown"


# --- pressing in Home Assistant --------------------------------------------------


async def test_pressing_records_the_time(library: HomeAssistant) -> None:
    await press(library, LER)
    assert state(library, LER) == now()
    assert state(library, EXTRA) == "unknown"


# --- pressing on the sensor -------------------------------------------------------
#
# Every guard has its own test: a write nobody made with a finger must never press.


async def write(hass: HomeAssistant, value: str, attributes: dict[str, Any] | None = None, *,
                force_update: bool = False, context: Context | None = None) -> None:
    """The remote's sensor writes `value`."""
    hass.states.async_set(REMOTE, value, attributes, force_update=force_update, context=context)
    await settle()


async def test_the_sensor_taking_the_value_presses(library: HomeAssistant) -> None:
    """Covers AE1: the press is recorded, descending from the sensor's write."""
    context = Context()
    await write(library, "1_single", context=context)
    pressed = library.states.get(LER)
    assert pressed.state == now()
    assert pressed.context.parent_id == context.id
    assert state(library, EXTRA) == "unknown"


async def test_each_change_into_the_value_is_a_press(library: HomeAssistant, freezer: Any) -> None:
    await write(library, "1_single")
    await write(library, "")
    await tick(library, freezer, 1)
    await write(library, "1_single")
    assert state(library, LER) == now()


async def test_another_value_is_no_press(library: HomeAssistant) -> None:
    """Covers AE3."""
    await write(library, "1_hold")
    assert state(library, LER) == "unknown"


@pytest.mark.parametrize(("attributes", "force_update"), [
    pytest.param(None, False, id="the same attributes"),
    pytest.param({"linkquality": 120}, False, id="new attributes"),
    pytest.param(None, True, id="force_update"),
])
async def test_the_value_written_again_is_no_press(
        library: HomeAssistant, freezer: Any, attributes: dict[str, Any] | None,
        force_update: bool) -> None:
    """Covers AE2: a sensor holding its value and rewritten never presses by itself."""
    await write(library, "1_single")
    first = state(library, LER)
    await tick(library, freezer, 1)
    await write(library, "1_single", attributes, force_update=force_update)
    assert state(library, LER) == first


async def test_from_unavailable_is_no_press(library: HomeAssistant) -> None:
    """Covers AE4: the sensor coming back with the value."""
    await write(library, "unavailable")
    await write(library, "1_single")
    assert state(library, LER) == "unknown"


async def test_a_sensor_appearing_with_the_value_is_no_press(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    assert await setup(ha, DEVICES)
    await write(ha, "1_single")
    assert state(ha, LER) == "unknown"
    assert not [r for r in caplog.records if r.levelname == "ERROR"]


async def test_a_sensor_removed_is_no_press(
        library: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    """Its removal has no new state; coming back after it has no old one: neither presses.

    Time moves before each, as a press written again in the same instant looks unchanged.
    """
    await write(library, "1_single")
    pressed = state(library, LER)
    await tick(library, freezer, 1)
    library.states.async_remove(REMOTE)
    await settle()
    assert state(library, LER) == pressed
    assert not [r for r in caplog.records if r.levelname == "ERROR"]
    await tick(library, freezer, 1)
    await write(library, "1_single")
    assert state(library, LER) == pressed


async def test_from_a_restored_state_is_no_press(ha: HomeAssistant) -> None:
    await fake(ha, REMOTE, "", {"restored": True})
    assert await setup(ha, DEVICES)
    await write(ha, "1_single")
    assert state(ha, LER) == "unknown"


@pytest.mark.parametrize("before", ["", "1_hold", "unknown"])
async def test_nothing_presses_while_ha_starts(library: HomeAssistant, freezer: Any, before: str) -> None:
    """Covers AE9: a value arriving as HA starts is no press, from any reading."""
    await write(library, before)
    await tick(library, freezer, 5)
    library.set_state(CoreState.starting)
    await write(library, "1_single")
    assert state(library, LER) == "unknown"
    library.set_state(CoreState.running)
    await write(library, "")
    await write(library, "1_single")
    assert state(library, LER) == now()


async def test_from_unknown_held_a_while_is_a_press(library: HomeAssistant, freezer: Any) -> None:
    """Covers AE10: the first press after a restart counts."""
    await write(library, "unknown")
    await tick(library, freezer, 5)
    await write(library, "1_single")
    assert state(library, LER) == now()


async def test_from_unknown_at_once_is_no_press(library: HomeAssistant, freezer: Any) -> None:
    """Covers AE11: a sensor just set up receiving its first value."""
    await write(library, "unknown")
    await tick(library, freezer, 1)
    await write(library, "1_single")
    assert state(library, LER) == "unknown"


async def test_a_restart_with_the_sensor_at_the_value_presses_nothing(greenhouse_remote_at_value: Any) -> None:
    """Covers AE5."""
    hass, calls = greenhouse_remote_at_value
    assert state(hass, CLEAN_BUTTON) == PRESSED
    assert started(calls) == []


async def test_a_reload_with_the_sensor_at_the_value_presses_nothing(library: HomeAssistant) -> None:
    await write(library, "1_single")
    pressed = state(library, LER)
    await reload(library, DEVICES)
    assert state(library, LER) == pressed


async def test_a_sensor_press_starts_the_program(greenhouse: HomeAssistant) -> None:
    """Covers AE1: the remote's press runs the program."""
    calls = capture(greenhouse, "call_service")
    greenhouse.states.async_set(GREENHOUSE_REMOTE, "1_single")
    await settle()
    assert state(greenhouse, CLEAN_BUTTON) == now()
    assert started(calls) == [CLEAN]
    assert sprinkled(calls) == ["turn_on"]


# --- availability, restarts, reloads -----------------------------------------------


@pytest.mark.parametrize("sensor", ["unavailable", None], ids=["unavailable", "missing"])
async def test_a_button_stays_available_without_its_sensor(
        ha: HomeAssistant, sensor: str | None) -> None:
    if sensor is not None:
        await fake(ha, REMOTE, sensor)
    assert await setup(ha, DEVICES)
    assert state(ha, LER) == "unknown"
    await press(ha, LER)
    assert state(ha, LER) == now()


async def test_a_restart_keeps_the_last_press(ha: HomeAssistant) -> None:
    """Covers AE5 (restore part): the last press is back, and restoring it is no press."""
    await fake(ha, REMOTE, "")
    await restart(ha, DEVICES, (State(LER, PRESSED), {}))
    assert state(ha, LER) == PRESSED


async def test_a_reload_keeps_the_last_press(library: HomeAssistant) -> None:
    await press(library, LER)
    await reload(library, DEVICES)
    assert state(library, LER) == now()


# --- IDs -----------------------------------------------------------------------


async def test_follows_its_own_rename(library: HomeAssistant) -> None:
    er.async_get(library).async_update_entity(LER, new_entity_id="button.ler_livro")
    await library.async_block_till_done()
    await press(library, "button.ler_livro")
    assert state(library, "button.ler_livro") == now()
    assert held(library, KEY) == {"button.ler_livro", EXTRA, LER_TOTAL, EXTRA_TOTAL}
    assert state(library, LER_TOTAL) == "1"


async def test_an_id_already_taken_is_an_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    other = er.async_get(ha).async_get_or_create(
        "button", "template", "someone_else", suggested_object_id="pururu_biblioteca_button_ler")
    assert other.entity_id == LER
    await fake(ha, REMOTE, "")
    assert await setup(ha, DEVICES)
    assert held(ha, KEY) == {EXTRA, EXTRA_TOTAL}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(LER in message and "template" in message for message in errors), errors
    assert f"{LER_TOTAL} follows {LER}, which is not created; not creating it" in errors


async def test_a_renamed_pururu_sensor_is_not_a_real_one(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Renamed in the UI, it no longer starts with sensor.pururu_: the registry still knows it."""
    er.async_get(ha).async_get_or_create("sensor", "pururu", "pururu_x_appliance_power",
                                         suggested_object_id="potencia")
    assert await setup(ha, {KEY: {"name": "Biblioteca", "buttons": {
        "ler": {"entity": "sensor.potencia", "state": "1_single", "name": "Ler"}}}})
    assert ha.states.get(LER) is None
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any("sensor.potencia is a pururu sensor" in message and LER in message
               for message in errors), errors


# --- starting the program ------------------------------------------------------------

GREENHOUSE = "greenhouse"
REAL_SPRINKLER = "switch.greenhouse_sprinkler"
SPRINKLER = "switch.pururu_greenhouse_switch_sprinkler"
GREENHOUSE_REMOTE = "sensor.greenhouse_remote_action"
CLEAN = "script.pururu_greenhouse_program_executable_clean"
CLEAN_BUTTON = "button.pururu_greenhouse_button_clean"
BELL = "button.pururu_greenhouse_button_bell"
CLEANING: dict[str, Any] = {"name": "Limpar", "sequence": [
    {"turn_on": "switch_sprinkler"}, {"delay": {"hours": 2}}, {"turn_off": "switch_sprinkler"}]}
GREENHOUSE_DEVICES: dict[str, Any] = {GREENHOUSE: {
    "name": "Estufa",
    "switches": {"sprinkler": {"entity": REAL_SPRINKLER, "name": "Irrigador"}},
    "programs": {"executable": {"clean": CLEANING}},
    "buttons": {
        "clean": {"entity": GREENHOUSE_REMOTE, "state": "1_single", "name": "Limpar", "program": "clean"},
        "bell": {"entity": GREENHOUSE_REMOTE, "state": "2_single", "name": "Sino"},
    },
}}


def started(calls: list[Any]) -> list[str]:
    """The scripts script.turn_on was called on, in order."""
    return [entity for event in calls
            if (event.data["domain"], event.data["service"]) == ("script", "turn_on")
            for entity in _ids(event.data["service_data"].get("entity_id"))]


def _ids(value: Any) -> list[str]:
    return [value] if isinstance(value, str) else list(value or [])


def sprinkled(calls: list[Any]) -> list[str]:
    """The services called on the real sprinkler, in order."""
    return [event.data["service"] for event in calls
            if REAL_SPRINKLER in _ids(event.data["service_data"].get("entity_id"))]


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
    await fake(scripts, GREENHOUSE_REMOTE, "")
    assert await setup(scripts, GREENHOUSE_DEVICES)
    return scripts


async def test_a_press_starts_its_program(greenhouse: HomeAssistant) -> None:
    """Covers AE1 (from Home Assistant): the program's script runs its first step."""
    calls = capture(greenhouse, "call_service")
    await press(greenhouse, CLEAN_BUTTON)
    assert started(calls) == [CLEAN]
    assert sprinkled(calls) == ["turn_on"]
    assert greenhouse.states.get(CLEAN).state == "on"


async def test_a_button_without_a_program_starts_nothing(greenhouse: HomeAssistant) -> None:
    """Covers AE7: the press is recorded, and that is all."""
    calls = capture(greenhouse, "call_service")
    await press(greenhouse, BELL)
    assert state(greenhouse, BELL) == now()
    assert started(calls) == []


async def test_a_press_while_it_runs_records_and_starts_nothing(
        greenhouse: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    """Covers AE6: the program keeps its run, and HA has nothing to refuse."""
    await press(greenhouse, CLEAN_BUTTON)
    await tick(greenhouse, freezer, 60)
    calls = capture(greenhouse, "call_service")
    await press(greenhouse, CLEAN_BUTTON)
    assert state(greenhouse, CLEAN_BUTTON) == now()
    assert started(calls) == []
    assert "Already running" not in caplog.text
    assert greenhouse.states.get(CLEAN).state == "on"


async def test_a_press_whose_program_is_not_generated_starts_nothing(
        greenhouse: HomeAssistant, freezer: Any) -> None:
    """Its target disabled, the program isn't generated: the press is still recorded."""
    er.async_get(greenhouse).async_update_entity(SPRINKLER, disabled_by=er.RegistryEntryDisabler.USER)
    await greenhouse.async_block_till_done()
    await tick(greenhouse, freezer, 31)
    await greenhouse.async_block_till_done()
    assert generated_scripts(greenhouse) == {}
    calls = capture(greenhouse, "call_service")
    await press(greenhouse, CLEAN_BUTTON)
    assert state(greenhouse, CLEAN_BUTTON) == now()
    assert started(calls) == []


async def test_a_press_whose_program_is_dropped_starts_nothing(
        scripts: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Its target's ID held by another integration, the program is dropped: no script at all."""
    er.async_get(scripts).async_get_or_create(
        "switch", "template", "someone_else", suggested_object_id="pururu_greenhouse_switch_sprinkler")
    await fake(scripts, REAL_SPRINKLER, "off")
    await fake(scripts, GREENHOUSE_REMOTE, "")
    assert await setup(scripts, GREENHOUSE_DEVICES)
    assert generated_scripts(scripts) == {}
    assert er.async_get(scripts).async_get_entity_id("script", "script", "pururu_greenhouse_program_executable_clean") is None
    caplog.clear()
    calls = capture(scripts, "call_service")
    await press(scripts, CLEAN_BUTTON)
    assert state(scripts, CLEAN_BUTTON) == now()
    assert started(calls) == []
    assert not [r for r in caplog.records if r.levelname == "ERROR"]


async def test_a_press_before_the_scripts_run_starts_nothing(ha: HomeAssistant) -> None:
    """HA's scripts not loaded (as at startup, before pururu writes them): no script to start."""
    await fake(ha, REAL_SPRINKLER, "off")
    assert await setup(ha, GREENHOUSE_DEVICES)
    calls = capture(ha, "call_service")
    await press(ha, CLEAN_BUTTON)
    assert state(ha, CLEAN_BUTTON) == now()
    assert started(calls) == []


async def test_a_script_of_ones_own_with_the_programs_id_is_not_started(ha: HomeAssistant) -> None:
    """The user's script holds the program's ID: pururu doesn't generate it, and a press never starts it."""
    er.async_get(ha).async_get_or_create(
        "script", "script", "pururu_greenhouse_program_executable_clean", suggested_object_id="mine")
    ha.states.async_set("script.mine", "off")
    await fake(ha, REAL_SPRINKLER, "off")
    assert await setup(ha, GREENHOUSE_DEVICES)
    assert generated_scripts(ha) == {}
    calls = capture(ha, "call_service")
    await press(ha, CLEAN_BUTTON)
    assert state(ha, CLEAN_BUTTON) == now()
    assert started(calls) == []


async def test_a_renamed_program_is_still_started(greenhouse: HomeAssistant) -> None:
    er.async_get(greenhouse).async_update_entity(CLEAN, new_entity_id="script.limpar_estufa")
    await greenhouse.async_block_till_done()
    calls = capture(greenhouse, "call_service")
    await press(greenhouse, CLEAN_BUTTON)
    assert started(calls) == ["script.limpar_estufa"]
    assert sprinkled(calls) == ["turn_on"]


async def test_the_program_runs_with_the_press_context(greenhouse: HomeAssistant) -> None:
    """The logbook names who pressed: the program's calls descend from the press."""
    context = Context()
    calls = capture(greenhouse, "call_service")
    await press(greenhouse, CLEAN_BUTTON, context)
    real = [event for event in calls if REAL_SPRINKLER in _ids(event.data["service_data"].get("entity_id"))]
    assert real
    assert all(context.id in (event.context.id, event.context.parent_id) for event in real)


async def test_the_sensor_press_runs_the_program_with_the_sensor_context(
        greenhouse: HomeAssistant) -> None:
    """The logbook follows the remote: the program's calls descend from the sensor's write."""
    context = Context()
    calls = capture(greenhouse, "call_service")
    greenhouse.states.async_set(GREENHOUSE_REMOTE, "1_single", context=context)
    await settle()
    button = greenhouse.states.get(CLEAN_BUTTON).context
    assert button.parent_id == context.id
    real = [event for event in calls if REAL_SPRINKLER in _ids(event.data["service_data"].get("entity_id"))]
    assert real
    assert all(event.context.parent_id in (context.id, button.id) for event in real)


@pytest.fixture
async def greenhouse_remote_at_value(scripts: HomeAssistant) -> Any:
    """A restart while the greenhouse's remote shows its clean button's value."""
    calls = capture(scripts, "call_service")
    await fake(scripts, REAL_SPRINKLER, "off")
    await fake(scripts, GREENHOUSE_REMOTE, "1_single")
    await restart(scripts, GREENHOUSE_DEVICES, (State(CLEAN_BUTTON, PRESSED), {}))
    await settle()
    return scripts, calls


# --- counting: each button's presses, all time, and per period --------------------------


def total(hass: HomeAssistant, entity_id: str = LER_TOTAL) -> str:
    return state(hass, entity_id)


async def test_a_new_total_is_zero(library: HomeAssistant) -> None:
    assert total(library) == "0"
    assert total(library, EXTRA_TOTAL) == "0"


async def test_every_press_counts(library: HomeAssistant, freezer: Any) -> None:
    """Covers AE1: two presses of the remote and one in Home Assistant."""
    await write(library, "1_single")
    await write(library, "")
    await tick(library, freezer, 1)
    await write(library, "1_single")
    await press(library, LER)
    assert total(library) == "3"
    assert total(library, EXTRA_TOTAL) == "0"


async def test_two_presses_at_one_instant_count_twice(library: HomeAssistant) -> None:
    """Counted from the press, not from the button's state: both are the same time."""
    await press(library, LER)
    await press(library, LER)
    assert total(library) == "2"


async def test_a_write_that_is_no_press_counts_nothing(library: HomeAssistant) -> None:
    await write(library, "1_single")
    await write(library, "1_single", force_update=True)
    await write(library, "1_hold")
    assert total(library) == "1"


async def test_a_restart_keeps_the_total(ha: HomeAssistant) -> None:
    """Covers AE3: restoring is no press; the next one counts on from it."""
    await fake(ha, REMOTE, "")
    await restart(ha, DEVICES, (State(LER_TOTAL, "7"),
                                {"native_value": 7, "native_unit_of_measurement": None}))
    assert total(ha) == "7"
    await press(ha, LER)
    assert total(ha) == "8"


async def test_a_reload_keeps_the_total(library: HomeAssistant) -> None:
    await press(library, LER)
    await reload(library, DEVICES)
    assert total(library) == "1"


async def test_a_disabled_button_counts_nothing(library: HomeAssistant) -> None:
    """R4: a disabled button follows no sensor, so it presses nothing."""
    er.async_get(library).async_update_entity(LER, disabled_by=er.RegistryEntryDisabler.USER)
    await reload(library, DEVICES)
    await write(library, "1_single")
    assert library.states.get(LER) is None
    assert total(library) == "0"


@pytest.mark.parametrize(("language", "expected"), [
    pytest.param("en", "Biblioteca Ler triggers", id="en"),
    pytest.param("pt-BR", "Biblioteca Disparos de Ler", id="pt-BR"),
])
async def test_the_total_is_named_by_its_button(ha: HomeAssistant, language: str, expected: str) -> None:
    ha.config.language = language
    await fake(ha, REMOTE, "")
    assert await setup(ha, DEVICES)
    assert ha.states.get(LER_TOTAL).attributes["friendly_name"] == expected
    assert er.async_get(ha).async_get(LER_TOTAL).translation_key == "button_triggered_total"


async def test_statistics_meter_the_total(ha: HomeAssistant) -> None:
    """Covers AE4: the periods asked, each counting the press; none other."""
    await fake(ha, REMOTE, "")
    buttons = {**BUTTONS, "ler": {**BUTTONS["ler"], "statistics": {"triggered": ["today", "month"]}}}
    assert await setup(ha, {KEY: {"name": "Biblioteca", "buttons": buttons}})
    await press(ha, LER)
    meter = "sensor.pururu_biblioteca_button_ler_triggered_{}"
    assert state(ha, meter.format("today")) == "1"
    assert state(ha, meter.format("month")) == "1"
    assert ha.states.get(meter.format("week")) is None
    assert ha.states.get(meter.format("year")) is None
    assert ha.states.get(meter.format("today")).attributes["friendly_name"] == "Biblioteca Ler triggers today"


@pytest.mark.parametrize("statistics", [
    pytest.param({"presses": ["today"]}, id="unknown counter"),
    pytest.param({"triggered": ["daily"]}, id="unknown period"),
    pytest.param({"triggered": ["today", "today"]}, id="a period twice"),
])
async def test_wrong_statistics_are_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, statistics: dict[str, Any]) -> None:
    """Covers AE5."""
    buttons = {"ler": {**BUTTONS["ler"], "statistics": statistics}}
    assert not await setup(ha, {KEY: {"name": "Biblioteca", "buttons": buttons}})
    assert "statistics" in caplog.text


async def test_a_key_alike_another_buttons_total_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    buttons = {"ler": BUTTONS["ler"], "ler_triggered_total": BUTTONS["extra"]}
    assert not await setup(ha, {KEY: {"name": "Biblioteca", "buttons": buttons}})
    assert "would be two entities" in caplog.text


async def test_a_button_whose_id_is_taken_has_no_statistics(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Its total follows it, and its meters follow the total: none is created, each told."""
    er.async_get(ha).async_get_or_create(
        "button", "template", "someone_else", suggested_object_id="pururu_biblioteca_button_ler")
    await fake(ha, REMOTE, "")
    buttons = {**BUTTONS, "ler": {**BUTTONS["ler"], "statistics": {"triggered": ["today"]}}}
    assert await setup(ha, {KEY: {"name": "Biblioteca", "buttons": buttons}})
    meter = "sensor.pururu_biblioteca_button_ler_triggered_today"
    assert held(ha, KEY) == {EXTRA, EXTRA_TOTAL}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert f"{meter} follows {LER_TOTAL}, which is not created; not creating it" in errors


async def test_a_button_on_a_pururu_sensor_has_no_total(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Its meters watch a total the build skipped: dropped, and told."""
    er.async_get(ha).async_get_or_create("sensor", "pururu", "pururu_x_appliance_power",
                                         suggested_object_id="potencia")
    assert await setup(ha, {KEY: {"name": "Biblioteca", "buttons": {"ler": {
        "entity": "sensor.potencia", "state": "1_single", "name": "Ler",
        "statistics": {"triggered": ["today"]}}}}})
    assert ha.states.get(LER_TOTAL) is None
    assert ha.states.get("sensor.pururu_biblioteca_button_ler_triggered_today") is None
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any("triggered_today watches" in message and "settings don't create" in message
               for message in errors), errors


async def test_a_press_while_its_program_runs_still_counts(
        greenhouse: HomeAssistant, freezer: Any) -> None:
    """Covers AE2: the program isn't started again; the press is counted."""
    await press(greenhouse, CLEAN_BUTTON)
    await tick(greenhouse, freezer, 60)
    calls = capture(greenhouse, "call_service")
    await press(greenhouse, CLEAN_BUTTON)
    assert started(calls) == []
    assert state(greenhouse, "sensor.pururu_greenhouse_button_clean_triggered_total") == "2"


async def test_a_press_without_a_program_counts(greenhouse: HomeAssistant) -> None:
    await press(greenhouse, BELL)
    assert state(greenhouse, "sensor.pururu_greenhouse_button_bell_triggered_total") == "1"
