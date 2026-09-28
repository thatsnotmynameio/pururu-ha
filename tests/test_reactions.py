"""Reactions: a made-up washer and the laundry's lights, which react to it, to a door, to time."""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.sun import get_astral_event_next
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.file import WriteError
import pytest
import voluptuous as vol

from helpers import capture, fake, generated, generated_scripts, module, reload, settle, setup, tick

WASHER = "washer"
LIGHTS = "lights"
POWER = "sensor.demo_plug_power"
DOOR = "binary_sensor.demo_door"
TETO = "light.demo_teto"
MIRROR = "sensor.pururu_washer_appliance_power"
APPLIANCE: dict[str, Any] = {
    "power": POWER,
    "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}
DOOR_OPENS = {"name": "Porta abriu", "entity": DOOR, "to": "on"}
OVERLOAD = {"name": "Sobrecarga", "device": WASHER, "when": "appliance_power", "above": 2500}


def devices(**reactions: dict[str, Any]) -> dict[str, Any]:
    lights: dict[str, Any] = {"name": "Luzes", "lights": {"teto": {"entity": TETO, "name": "Teto"}}}
    if reactions:
        lights["reactions"] = reactions
    return {WASHER: {"name": "Washer", "appliance": APPLIANCE}, LIGHTS: lights}


# --- configuration ----------------------------------------------------------------


@pytest.mark.parametrize("reaction", [
    pytest.param({"name": "Teto", "when": "light_teto", "to": "on"}, id="own entity"),
    pytest.param({"name": "Teto", "device": LIGHTS, "when": "light_teto", "to": "on"},
                 id="own device named"),
    pytest.param(OVERLOAD, id="other device"),
    pytest.param({**DOOR_OPENS, "from": "off", "for": {"minutes": 5}}, id="real entity"),
    pytest.param({"name": "Noite", "at": "22:00"}, id="time"),
    pytest.param({"name": "Anoitecer", "sun": "sunset", "offset": {"minutes": -30}}, id="sun"),
    pytest.param({"name": "Mês", "device": WASHER, "when": "appliance_runtime_month", "to": "1"},
                 id="an entity the settings don't build"),
])
async def test_valid_reaction_is_accepted(ha: HomeAssistant, reaction: dict[str, Any]) -> None:
    assert await setup(ha, devices(it=reaction))


PATH = "'pururu->devices->lights->reactions->it"


@pytest.mark.parametrize(("reaction", "reason"), [
    pytest.param({"entity": DOOR, "to": "on"}, "required key 'name' not provided", id="no name"),
    pytest.param({**DOOR_OPENS, "name": " "}, f"length of value must be at least 1 for dictionary "
                 f"value {PATH}->name'", id="blank name"),
    pytest.param({"name": "X"}, "a reaction needs one source: when, entity, at or sun",
                 id="no source"),
    pytest.param({**DOOR_OPENS, "at": "22:00"},
                 "a reaction needs one source: when, entity, at or sun", id="two sources"),
    pytest.param({**DOOR_OPENS, "device": WASHER}, "a reaction's device goes with when",
                 id="device without when"),
    pytest.param({"name": "X", "at": "22:00", "offset": {"minutes": 1}},
                 "a reaction's offset goes with sun", id="offset without sun"),
    pytest.param({"name": "X", "at": "22:00", "for": {"minutes": 1}},
                 "a reaction on at or sun takes no to, from, above, below or for",
                 id="for on a time"),
    pytest.param({"name": "X", "sun": "sunset", "to": "on"},
                 "a reaction on at or sun takes no to, from, above, below or for",
                 id="to on the sun"),
    pytest.param({"name": "X", "entity": DOOR},
                 "a reaction on a state needs to, or above and/or below, not both", id="no condition"),
    pytest.param({**DOOR_OPENS, "above": 1},
                 "a reaction on a state needs to, or above and/or below, not both",
                 id="to and above"),
    pytest.param({"name": "X", "entity": POWER, "above": 1, "from": "0"},
                 "a reaction's from goes with to", id="from without to"),
    pytest.param({"name": "X", "entity": POWER, "above": 2, "below": 1},
                 "a reaction's above must be lower than its below", id="above not lower"),
    pytest.param({**DOOR_OPENS, "sun": "noon"}, "value must be one of ['sunrise', 'sunset']",
                 id="unknown sun event"),
    pytest.param({**DOOR_OPENS, "entity": "door"}, "Entity ID door is an invalid entity ID",
                 id="entity not an entity ID"),
    pytest.param({**DOOR_OPENS, "colour": "red"},
                 f"'colour' is an invalid option for 'pururu', check: {PATH[1:]}->colour",
                 id="unknown key"),
    pytest.param({"name": "X", "when": "appliance_power", "to": "on"},
                 "reactions: it: appliance_power is not an entity key of this device",
                 id="when of another device, without device"),
    pytest.param({"name": "X", "when": "reaction_other", "to": "on"},
                 "reactions: it: reaction_other is not an entity key of this device",
                 id="when a reaction"),
    pytest.param({"name": "X", "device": "dryer", "when": "appliance_power", "to": "on"},
                 "device lights: reactions: it: device dryer is not in devices",
                 id="device not in devices"),
    pytest.param({"name": "X", "device": WASHER, "when": "light_teto", "to": "on"},
                 "device lights: reactions: it: light_teto is not an entity key of device washer",
                 id="when not of that device"),
])
async def test_invalid_reaction_is_refused(ha: HomeAssistant, caplog: pytest.LogCaptureFixture,
                                           reaction: dict[str, Any], reason: str) -> None:
    """Refused, and for its own reason: a typo in the test would be refused for another one."""
    assert not await setup(ha, devices(it=reaction, other=DOOR_OPENS))
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(reason in message for message in errors), errors


async def test_an_empty_block_is_refused(ha: HomeAssistant) -> None:
    config = devices()
    config[LIGHTS]["reactions"] = {}
    assert not await setup(ha, config)


async def test_reactions_alone_are_not_a_feature(ha: HomeAssistant,
                                                 caplog: pytest.LogCaptureFixture) -> None:
    assert not await setup(ha, {LIGHTS: {"name": "Luzes", "reactions": {"door": DOOR_OPENS}}})
    assert "a device needs at least one feature" in caplog.text


async def test_the_american_spelling_of_a_key_is_refused(ha: HomeAssistant) -> None:
    config = devices()
    config[LIGHTS]["reaction"] = {"door": DOOR_OPENS}
    assert not await setup(ha, config)


async def test_two_reactions_with_one_automation_id_are_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """lights' b_reaction_c and lights_reaction_b's c would both be pururu_lights_reaction_b_reaction_c."""
    config = devices(b_reaction_c=DOOR_OPENS)
    config["lights_reaction_b"] = {
        "name": "Outras", "lights": {"x": {"entity": "light.demo_x", "name": "X"}},
        "reactions": {"c": DOOR_OPENS},
    }
    assert not await setup(ha, config)
    assert ("device lights_reaction_b: automation.pururu_lights_reaction_b_reaction_c is already "
            "a reaction of device lights") in caplog.text


CLEAN_PROGRAM = {"name": "Limpar", "sequence": [{"turn_on": "light_teto"}]}


def with_program(**reactions: dict[str, Any]) -> dict[str, Any]:
    config = devices(**reactions)
    config[LIGHTS]["programs"] = {"clean": CLEAN_PROGRAM}
    return config


@pytest.mark.parametrize("reaction", [
    pytest.param({**DOOR_OPENS, "then": "clean"}, id="real entity"),
    pytest.param({**OVERLOAD, "then": "clean"}, id="another device's entity, its own program"),
])
async def test_then_a_program_of_the_device_is_accepted(ha: HomeAssistant,
                                                        reaction: dict[str, Any]) -> None:
    assert await setup(ha, with_program(it=reaction))


@pytest.mark.parametrize("config", [
    pytest.param(with_program(it={**DOOR_OPENS, "then": "wash"}), id="no such program"),
    pytest.param(with_program(it={**DOOR_OPENS, "then": ""}), id="empty"),
    pytest.param(devices(it={**DOOR_OPENS, "then": "clean"}), id="the device has no programs"),
])
async def test_then_not_a_program_of_the_device_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, config: dict[str, Any]) -> None:
    then = config[LIGHTS]["reactions"]["it"]["then"]
    assert not await setup(ha, config)
    assert f"reactions: it: {then} is not a program of this device" in caplog.text


async def test_then_another_devices_program_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """The washer's program isn't the lights': a reaction runs its own device's."""
    config = devices(it={**OVERLOAD, "then": "clean"})
    config[WASHER]["programs"] = {"clean": {"name": "X", "sequence": [{"delay": 1}]}}
    assert not await setup(ha, config)
    assert "reactions: it: clean is not a program of this device" in caplog.text


# --- translation ----------------------------------------------------------------------


def translated(ha: HomeAssistant, reaction: dict[str, Any],
               entity_id: str | None = None) -> list[dict[str, Any]]:
    """The triggers of a reaction as validated, watching `entity_id`."""
    reactions = module("reactions")
    return reactions.triggers(reactions.REACTION(reaction), entity_id)


def test_to_adds_not_from_unavailable(ha: HomeAssistant) -> None:
    assert translated(ha, DOOR_OPENS, DOOR) == [{
        "trigger": "state", "entity_id": DOOR,
        "not_from": ["unavailable", "unknown"], "to": "on",
    }]


def test_from_replaces_not_from(ha: HomeAssistant) -> None:
    assert translated(ha, {**DOOR_OPENS, "from": "off", "for": {"minutes": 5}}, DOOR) == [{
        "trigger": "state", "entity_id": DOOR, "from": "off", "to": "on", "for": "00:05:00",
    }]


def test_unquoted_on_and_off_are_states(ha: HomeAssistant) -> None:
    triggers = translated(ha, {**DOOR_OPENS, "from": False, "to": True}, DOOR)
    assert (triggers[0]["from"], triggers[0]["to"]) == ("off", "on")


def test_a_number_in_to_is_text(ha: HomeAssistant) -> None:
    assert translated(ha, {**DOOR_OPENS, "to": 1}, DOOR)[0]["to"] == "1"


def test_above_and_below_are_numeric_state(ha: HomeAssistant) -> None:
    assert translated(ha, {"name": "X", "entity": POWER, "above": 10, "below": 2500,
                           "for": {"hours": 1, "seconds": 5}}, POWER) == [{
        "trigger": "numeric_state", "entity_id": POWER, "above": 10.0, "below": 2500.0,
        "for": "01:00:05",
    }]


def test_at_is_a_time_trigger(ha: HomeAssistant) -> None:
    assert translated(ha, {"name": "Noite", "at": "22:00"}) == [
        {"trigger": "time", "at": "22:00:00"}]


def test_sun_with_a_negative_offset(ha: HomeAssistant) -> None:
    assert translated(ha, {"name": "X", "sun": "sunset", "offset": {"minutes": -30}}) == [
        {"trigger": "sun", "event": "sunset", "offset": "-00:30:00"}]


def test_sun_without_offset(ha: HomeAssistant) -> None:
    assert translated(ha, {"name": "X", "sun": "sunrise"}) == [
        {"trigger": "sun", "event": "sunrise"}]


def test_a_fraction_of_a_second_is_kept(ha: HomeAssistant) -> None:
    """A reaction never fires earlier than configured: HA reads the fraction back."""
    held = translated(ha, {**DOOR_OPENS, "for": {"seconds": 1.9}}, DOOR)[0]["for"]
    assert held == "00:00:01.900000"
    assert cv.time_period(held) == timedelta(seconds=1.9)
    offset = translated(ha, {"name": "X", "sun": "sunset", "offset": {"seconds": -0.5}})[0]
    assert offset["offset"] == "-00:00:00.500000"
    assert cv.time_period(offset["offset"]) == timedelta(seconds=-0.5)


def test_the_automation_of_a_reaction(ha: HomeAssistant) -> None:
    reactions = module("reactions")
    assert reactions.automation(LIGHTS, "Luzes", "door", reactions.REACTION(DOOR_OPENS),
                                DOOR) == {
        "id": "pururu_lights_reaction_door",
        "alias": "Luzes Porta abriu",
        "description": "pururu: lights, door",
        "triggers": translated(ha, DOOR_OPENS, DOOR),
        "actions": [],
    }


def test_then_starts_its_program_unless_it_runs(ha: HomeAssistant) -> None:
    reactions = module("reactions")
    reaction = reactions.REACTION({**DOOR_OPENS, "then": "clean"})
    script = "script.pururu_lights_program_clean"
    assert reactions.automation(LIGHTS, "Luzes", "door", reaction, DOOR, script)["actions"] == [{
        "if": [{"condition": "state", "entity_id": script, "state": "off"}],
        "then": [{"action": "script.turn_on", "target": {"entity_id": script}}],
    }]


@pytest.mark.parametrize("then", [["clean"], "script.pururu_lights_program_clean"])
def test_then_is_a_slug(ha: HomeAssistant, then: Any) -> None:
    reaction = module("reactions").REACTION
    with pytest.raises(vol.Invalid):
        reaction({**DOOR_OPENS, "then": then})


# --- generation --------------------------------------------------------------------------


def automation(key: str) -> str:
    return f"automation.pururu_lights_reaction_{key}"


def fired(ha: HomeAssistant, key: str) -> bool:
    """Whether the reaction's automation has fired."""
    state: State | None = ha.states.get(automation(key))
    assert state is not None, f"no {automation(key)}"
    return state.attributes["last_triggered"] is not None


@pytest.fixture
async def automations(ha: HomeAssistant) -> AsyncIterator[None]:
    """HA's automations, from a configuration.yaml that includes pururu's file."""
    with patch("homeassistant.config.load_yaml_config_file",
               side_effect=lambda *_args, **_kwargs: {"automation pururu": generated(ha)}):
        assert await async_setup_component(ha, "automation",
                                           {"automation pururu": generated(ha)})
        yield


async def test_the_file_holds_an_automation_per_reaction(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(door=DOOR_OPENS, night={"name": "Noite", "at": "22:00"}))
    assert [a["id"] for a in generated(ha)] == ["pururu_lights_reaction_door",
                                                "pururu_lights_reaction_night"]


async def test_when_is_the_current_entity_id_of_the_watched_entity(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(overload=OVERLOAD))
    assert generated(ha)[0]["triggers"][0]["entity_id"] == MIRROR
    er.async_get(ha).async_update_entity(MIRROR, new_entity_id="sensor.washer_power")
    await ha.async_block_till_done()
    assert generated(ha)[0]["triggers"][0]["entity_id"] == "sensor.washer_power"


async def test_a_reaction_on_an_entity_not_created_is_not_generated(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    month = {"name": "Mês", "device": WASHER, "when": "appliance_runtime_month", "to": "1"}
    assert await setup(ha, devices(month=month, door=DOOR_OPENS))
    assert [a["id"] for a in generated(ha)] == ["pururu_lights_reaction_door"]
    assert ("automation.pururu_lights_reaction_month follows "
            "sensor.pururu_washer_appliance_runtime_month, which is not created; "
            "not generating it") in caplog.text


async def test_the_automation_has_the_pururu_entity_id(ha: HomeAssistant,
                                                       automations: None) -> None:
    assert await setup(ha, devices(door=DOOR_OPENS))
    state = ha.states.get(automation("door"))
    assert state is not None
    assert state.attributes["friendly_name"] == "Luzes Porta abriu"
    assert state.attributes["id"] == "pururu_lights_reaction_door"


async def test_a_state_reaction_fires(ha: HomeAssistant, automations: None) -> None:
    await fake(ha, DOOR, "off")
    assert await setup(ha, devices(door=DOOR_OPENS))
    assert not fired(ha, "door")
    await fake(ha, DOOR, "on")
    assert fired(ha, "door")


async def test_for_waits(ha: HomeAssistant, freezer: Any, automations: None) -> None:
    await fake(ha, DOOR, "off")
    assert await setup(ha, devices(door={**DOOR_OPENS, "for": {"minutes": 5}}))
    await fake(ha, DOOR, "on")
    await tick(ha, freezer, 299)
    assert not fired(ha, "door")
    await tick(ha, freezer, 1)
    assert fired(ha, "door")


async def test_coming_back_from_unavailable_does_not_fire(ha: HomeAssistant,
                                                          automations: None) -> None:
    await fake(ha, DOOR, "on")
    assert await setup(ha, devices(closed={"name": "Fechou", "entity": DOOR, "to": "off"}))
    await fake(ha, DOOR, "unavailable")
    await fake(ha, DOOR, "off")
    assert not fired(ha, "closed")
    await fake(ha, DOOR, "on")
    await fake(ha, DOOR, "off")
    assert fired(ha, "closed")


async def test_another_devices_entity_fires(ha: HomeAssistant, automations: None) -> None:
    await fake(ha, POWER, "100")
    assert await setup(ha, devices(overload=OVERLOAD))
    await fake(ha, POWER, "3000")
    assert fired(ha, "overload")


async def test_its_own_entity_fires(ha: HomeAssistant, automations: None) -> None:
    await fake(ha, TETO, "off")
    assert await setup(ha, devices(teto={"name": "Teto", "when": "light_teto", "to": "on"}))
    await fake(ha, TETO, "on")
    assert fired(ha, "teto")


async def test_a_time_fires(ha: HomeAssistant, freezer: Any, automations: None) -> None:
    assert await setup(ha, devices(soon={"name": "Logo", "at": "10:05"}))
    await tick(ha, freezer, 299)
    assert not fired(ha, "soon")
    await tick(ha, freezer, 1)
    assert fired(ha, "soon")


async def test_the_sun_fires_at_its_offset(ha: HomeAssistant, freezer: Any,
                                           automations: None) -> None:
    assert await setup(ha, devices(dusk={"name": "Anoitecer", "sun": "sunset",
                                         "offset": {"minutes": -30}}))
    sunset = get_astral_event_next(ha, "sunset")
    await tick(ha, freezer, (sunset - dt_util.utcnow()).total_seconds() - 1800 - 1)
    assert not fired(ha, "dusk")
    await tick(ha, freezer, 1)
    assert fired(ha, "dusk")


# --- then: its program ------------------------------------------------------------------

POOL = "pool"
REAL_PUMP = "switch.pool_pump"
PUMP = "switch.pururu_pool_switch_pump"
CLEAN = "script.pururu_pool_program_clean"
CLEANING: dict[str, Any] = {"name": "Limpar", "sequence": [
    {"turn_on": "switch_pump"}, {"delay": {"hours": 2}}, {"turn_off": "switch_pump"}]}


def pool(**reactions: dict[str, Any]) -> dict[str, Any]:
    """The pool: its pump, its cleaning, and reactions to the door; `clean` also a reaction key."""
    return {POOL: {"name": "Piscina",
                   "switches": {"pump": {"entity": REAL_PUMP, "name": "Bomba"}},
                   "programs": {"clean": CLEANING},
                   "reactions": reactions or {"clean": {**DOOR_OPENS, "then": "clean"}}}}


@pytest.fixture
async def both(ha: HomeAssistant) -> AsyncIterator[None]:
    """HA's automations and scripts, from a configuration.yaml that includes pururu's files."""
    def included(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"automation pururu": generated(ha), "script pururu": generated_scripts(ha)}

    with patch("homeassistant.config.load_yaml_config_file", side_effect=included):
        assert await async_setup_component(ha, "script", {"script pururu": generated_scripts(ha)})
        assert await async_setup_component(ha, "automation",
                                           {"automation pururu": generated(ha)})
        yield


def script_state(ha: HomeAssistant, entity_id: str = CLEAN) -> str:
    state = ha.states.get(entity_id)
    assert state is not None, f"no {entity_id}"
    return state.state


async def test_the_automation_starts_the_programs_script(ha: HomeAssistant) -> None:
    assert await setup(ha, pool())
    assert generated(ha)[0]["actions"] == module("reactions").actions(CLEAN)


async def test_the_reaction_starts_its_program(ha: HomeAssistant, both: None) -> None:
    await fake(ha, DOOR, "off")
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, pool())
    calls = capture(ha, "call_service")
    await fake(ha, DOOR, "on")
    await settle()
    assert script_state(ha) == "on"
    assert [e.data["service"] for e in calls
            if REAL_PUMP in cv.ensure_list(e.data["service_data"].get("entity_id"))] == ["turn_on"]


async def test_a_trigger_while_the_program_runs_does_nothing(ha: HomeAssistant,
                                                             both: None) -> None:
    await fake(ha, DOOR, "off")
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, pool())
    triggered = capture(ha, "automation_triggered")
    started = capture(ha, "script_started")
    await fake(ha, DOOR, "on")
    await fake(ha, DOOR, "off")
    await fake(ha, DOOR, "on")
    await settle()
    assert len(triggered) == 2
    assert len(started) == 1
    assert script_state(ha) == "on"


async def test_a_program_not_generated_drops_its_reaction(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(
        "script", "template", "someone_else", suggested_object_id="pururu_pool_program_clean")
    night = {"name": "Noite", "at": "22:00"}
    assert await setup(ha, pool(clean={**DOOR_OPENS, "then": "clean"}, night=night))
    assert [a["id"] for a in generated(ha)] == ["pururu_pool_reaction_night"]
    assert ("automation.pururu_pool_reaction_clean runs script.pururu_pool_program_clean, "
            "which is not generated; not generating it") in caplog.text


async def disable(hass: HomeAssistant, entity_id: str, disabled: bool = True) -> None:
    er.async_get(hass).async_update_entity(
        entity_id, disabled_by=er.RegistryEntryDisabler.USER if disabled else None)
    await hass.async_block_till_done()


async def test_a_held_program_holds_its_reaction(ha: HomeAssistant, freezer: Any,
                                                 both: None) -> None:
    """The pump disabled: the program and its reaction are held, the reaction's rename kept."""
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, pool())
    registry = er.async_get(ha)
    registry.async_update_entity("automation.pururu_pool_reaction_clean",
                                 new_entity_id="automation.porta_limpa")
    await ha.async_block_till_done()
    await disable(ha, PUMP)
    await tick(ha, freezer, 31)
    await ha.async_block_till_done()
    assert generated(ha) == []
    assert registry.async_get("automation.porta_limpa") is not None
    await disable(ha, PUMP, disabled=False)
    await tick(ha, freezer, 31)
    await ha.async_block_till_done()
    assert [a["id"] for a in generated(ha)] == ["pururu_pool_reaction_clean"]
    assert registry.async_get("automation.porta_limpa") is not None


async def test_it_follows_the_script_renamed(ha: HomeAssistant, both: None) -> None:
    """At once, as `when` follows a pururu entity: the old ID would never be off, and it would never start."""
    await fake(ha, REAL_PUMP, "off")
    await fake(ha, DOOR, "off")
    assert await setup(ha, pool())
    er.async_get(ha).async_update_entity(CLEAN, new_entity_id="script.limpar_piscina")
    await ha.async_block_till_done()
    assert generated(ha)[0]["actions"] == module("reactions").actions("script.limpar_piscina")
    started = capture(ha, "script_started")
    await fake(ha, DOOR, "on")
    await settle()
    assert len(started) == 1


async def test_renaming_a_script_no_reaction_starts_reloads_nothing(ha: HomeAssistant) -> None:
    config = pool(night={"name": "Noite", "at": "22:00"})
    assert await setup(ha, config)
    with patch.object(ha.config_entries, "async_schedule_reload") as reloading:
        er.async_get(ha).async_update_entity(CLEAN, new_entity_id="script.limpar_piscina")
        await ha.async_block_till_done()
    reloading.assert_not_called()


async def test_a_reaction_on_another_device_starts_its_own_program(ha: HomeAssistant) -> None:
    config = pool(power={"name": "Potência", "device": WASHER, "when": "appliance_power",
                         "above": 10, "then": "clean"})
    config[WASHER] = {"name": "Washer", "appliance": APPLIANCE}
    assert await setup(ha, config)
    assert generated(ha)[0]["actions"] == module("reactions").actions(CLEAN)


async def test_a_script_not_written_drops_its_reaction(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """The scripts' file can't be written: the new program isn't in HA, so its reaction isn't generated."""
    files = module("files")
    real = files.write_utf8_file_atomic

    def only_automations(path: str, content: str) -> None:
        if path.endswith("programs.yaml"):
            raise WriteError("disk full")
        real(path, content)

    night = {"name": "Noite", "at": "22:00"}
    before = pool(night=night)
    del before[POOL]["programs"]
    assert await setup(ha, before)
    after = pool(night=night, clean={**DOOR_OPENS, "then": "clean"})
    with patch.object(files, "write_utf8_file_atomic", side_effect=only_automations):
        await reload(ha, after)
        assert [a["id"] for a in generated(ha)] == ["pururu_pool_reaction_night"]
        # Failing again: the script, tracked since, still isn't in the file
        await reload(ha, after)
        assert [a["id"] for a in generated(ha)] == ["pururu_pool_reaction_night"]
    assert ("automation.pururu_pool_reaction_clean runs script.pururu_pool_program_clean, "
            "which is not generated; not generating it") in caplog.text


# --- statistics --------------------------------------------------------------------

TRIGGERED = "sensor.pururu_pool_reaction_clean_triggered_total"


def count(ha: HomeAssistant, entity_id: str = TRIGGERED) -> str:
    state = ha.states.get(entity_id)
    assert state is not None, f"no {entity_id}"
    return state.state


async def test_every_trigger_counts_even_one_its_program_skips(ha: HomeAssistant,
                                                              both: None) -> None:
    await fake(ha, DOOR, "off")
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, pool())
    assert count(ha) == "0"
    await fake(ha, DOOR, "on")
    await fake(ha, DOOR, "off")
    await fake(ha, DOOR, "on")
    await settle()
    assert count(ha) == "2"
    assert count(ha, "sensor.pururu_pool_program_clean_cycles_total") == "0"


async def test_a_reaction_without_then_counts_too(ha: HomeAssistant, freezer: Any,
                                                 automations: None) -> None:
    assert await setup(ha, devices(soon={"name": "Logo", "at": "10:05"}))
    await tick(ha, freezer, 300)
    assert count(ha, "sensor.pururu_lights_reaction_soon_triggered_total") == "1"


async def test_its_meters_are_asked_for(ha: HomeAssistant) -> None:
    assert await setup(ha, pool(clean={**DOOR_OPENS, "then": "clean",
                                       "statistics": {"triggered": ["month"]}}))
    assert ha.states.get("sensor.pururu_pool_reaction_clean_triggered_month") is not None
    assert ha.states.get("sensor.pururu_pool_reaction_clean_triggered_today") is None


async def test_a_reaction_on_its_own_counter_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    it = {"name": "Eu", "when": "reaction_it_triggered_total", "above": 3}
    assert not await setup(ha, devices(it=it))
    assert "reactions: it: reaction_it_triggered_total is its own statistic" in caplog.text


async def test_a_reaction_on_a_programs_statistic(ha: HomeAssistant) -> None:
    done = {"name": "Limpou", "when": "program_clean_last_cycle_end", "to": "unknown"}
    assert await setup(ha, pool(done=done))
    trigger = generated(ha)[0]["triggers"][0]
    assert trigger["entity_id"] == "sensor.pururu_pool_program_clean_last_cycle_end"
