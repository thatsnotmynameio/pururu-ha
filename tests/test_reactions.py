"""Reactions: a made-up washer and the laundry's lights, which react to it, to a door, to time."""

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import CoreState, HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.sun import get_astral_event_next
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.file import WriteError
from homeassistant.util.yaml import load_yaml_dict
import pytest

from helpers import AUTOMATIONS, capture, fake, generated, module, reload, restart, setup, tick

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
    text = Path(ha.config.path(AUTOMATIONS)).read_text(encoding="utf-8")
    assert text.startswith(
        "# Generated by pururu from its configuration. Don't edit: it is rewritten on every "
        "reload.\n")
    assert [a["id"] for a in generated(ha)] == ["pururu_lights_reaction_door",
                                                "pururu_lights_reaction_night"]


async def test_without_reactions_the_file_is_an_empty_list(ha: HomeAssistant) -> None:
    assert await setup(ha, devices())
    assert Path(ha.config.path(AUTOMATIONS)).is_file()
    assert generated(ha) == []


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


async def test_an_automation_id_already_taken_is_not_generated(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create("automation", "automation", "mine",
                                         suggested_object_id="pururu_lights_reaction_door")
    assert await setup(ha, devices(door=DOOR_OPENS))
    assert generated(ha) == []
    assert ("automation.pururu_lights_reaction_door is already taken by the automation "
            "integration; not generating it") in caplog.text
    assert er.async_get(ha).async_get(f"{automation('door')}_2") is None


async def test_an_automation_of_ones_own_with_the_same_id_is_not_adopted(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """An automation pururu never generated keeps its ID and its actions."""
    er.async_get(ha).async_get_or_create("automation", "automation",
                                         "pururu_lights_reaction_door", suggested_object_id="mine")
    assert await setup(ha, devices(door=DOOR_OPENS))
    assert generated(ha) == []
    assert ("automation.pururu_lights_reaction_door is already taken by automation.mine, an "
            "automation with the same ID; not generating it") in caplog.text


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


async def test_an_unchanged_file_is_neither_rewritten_nor_reloaded(ha: HomeAssistant,
                                                                   automations: None) -> None:
    assert await setup(ha, devices(door=DOOR_OPENS))
    path = Path(ha.config.path(AUTOMATIONS))
    before = path.stat().st_ino
    reloaded = capture(ha, "automation_reloaded")
    await reload(ha, devices(door=DOOR_OPENS))
    assert reloaded == []
    assert path.stat().st_ino == before


async def test_a_file_in_another_encoding_is_rewritten(ha: HomeAssistant) -> None:
    """A file the user saved as Latin-1 is no error: pururu writes its own UTF-8 over it."""
    path = Path(ha.config.path(AUTOMATIONS))
    path.parent.mkdir(parents=True)
    path.write_bytes("- alias: Máquina\n".encode("latin-1"))
    assert await setup(ha, devices(door=DOOR_OPENS))
    assert ha.config_entries.async_entries("pururu")[0].state is ConfigEntryState.LOADED
    assert [a["id"] for a in generated(ha)] == ["pururu_lights_reaction_door"]


async def test_a_changed_file_reloads_automations(ha: HomeAssistant, automations: None) -> None:
    assert await setup(ha, devices(door=DOOR_OPENS))
    reloaded = capture(ha, "automation_reloaded")
    await reload(ha, devices(door=DOOR_OPENS, night={"name": "Noite", "at": "22:00"}))
    assert len(reloaded) == 1
    assert ha.states.get(automation("night")) is not None


async def test_a_changed_reaction_raises_no_false_include_warning(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, automations: None) -> None:
    """A reload removes and re-adds the changed automation: no issue in between."""
    assert await setup(ha, devices(door=DOOR_OPENS))
    await reload(ha, devices(door={**DOOR_OPENS, "to": "off"}))
    assert not [r for r in caplog.records if "are not loaded: add" in r.getMessage()]
    assert issue(ha) is None


async def test_a_dropped_reaction_leaves_the_file_and_the_registry(
        ha: HomeAssistant, automations: None) -> None:
    assert await setup(ha, devices(door=DOOR_OPENS, night={"name": "Noite", "at": "22:00"}))
    await reload(ha, devices(night={"name": "Noite", "at": "22:00"}))
    assert [a["id"] for a in generated(ha)] == ["pururu_lights_reaction_night"]
    assert er.async_get(ha).async_get(automation("door")) is None
    assert ha.states.get(automation("door")) is None
    entry = ha.config_entries.async_entries("pururu")[0]
    assert entry.data["automations"] == ["pururu_lights_reaction_night"]


# --- the include, failures, removal --------------------------------------------------


def issue(ha: HomeAssistant) -> ir.IssueEntry | None:
    return ir.async_get(ha).async_get_issue("pururu", "automations_not_included")


INCLUDE = "automation pururu: !include_dir_merge_list pururu/automations"


async def test_the_include_tolerates_a_missing_folder_and_reads_the_file(
        ha: HomeAssistant) -> None:
    """Before pururu has written anything, HA still loads its configuration."""
    configuration = Path(ha.config.path("configuration.yaml"))
    configuration.write_text(f"{INCLUDE}\n", encoding="utf-8")
    assert not Path(ha.config.path("pururu/automations")).exists()
    assert load_yaml_dict(configuration) == {"automation pururu": []}
    assert await setup(ha, devices(door=DOOR_OPENS))
    assert load_yaml_dict(configuration) == {"automation pururu": generated(ha)}
    assert generated(ha) != []


async def test_without_the_include_an_issue_says_what_to_add(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    with patch("homeassistant.config.load_yaml_config_file",
               side_effect=lambda *_args, **_kwargs: {}):
        assert await async_setup_component(ha, "automation", {})
        assert await setup(ha, devices(door=DOOR_OPENS))
    found = issue(ha)
    assert found is not None
    assert found.severity == ir.IssueSeverity.WARNING
    assert not found.is_fixable
    assert found.translation_placeholders == {"include": INCLUDE, "file": AUTOMATIONS}
    assert (f'The automations of pururu\'s reactions are not loaded: add "{INCLUDE}" '
            "to configuration.yaml") in caplog.text


async def test_the_warning_is_logged_once_while_the_issue_is_open(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """The include is checked at every automation's state change: the log says it once."""
    with patch("homeassistant.config.load_yaml_config_file",
               side_effect=lambda *_args, **_kwargs: {}):
        assert await async_setup_component(ha, "automation", {})
        assert await setup(ha, devices(door=DOOR_OPENS))
    ha.states.async_set("automation.mine", "on")
    ha.states.async_set("automation.mine", "off")
    await ha.async_block_till_done()
    assert issue(ha) is not None
    warned = [r for r in caplog.records if "are not loaded: add" in r.getMessage()]
    assert len(warned) == 1


async def test_the_warning_is_logged_again_once_a_restored_issue_reopens(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """A restart restores a non-persistent issue as inactive: the warning must fire again."""
    ir.async_get(ha).issues[("pururu", "automations_not_included")] = ir.IssueEntry(
        active=False,
        breaks_in_ha_version=None,
        created=dt_util.utcnow(),
        data=None,
        dismissed_version=None,
        domain="pururu",
        is_fixable=None,
        is_persistent=False,
        issue_domain=None,
        issue_id="automations_not_included",
        learn_more_url=None,
        severity=None,
        translation_key=None,
        translation_placeholders=None,
    )
    with patch("homeassistant.config.load_yaml_config_file",
               side_effect=lambda *_args, **_kwargs: {}):
        assert await async_setup_component(ha, "automation", {})
        assert await setup(ha, devices(door=DOOR_OPENS))
    found = issue(ha)
    assert found is not None
    assert found.active
    warned = [r for r in caplog.records if "are not loaded: add" in r.getMessage()]
    assert len(warned) == 1


async def test_the_issue_goes_once_the_include_is_there(ha: HomeAssistant) -> None:
    with patch("homeassistant.config.load_yaml_config_file",
               side_effect=lambda *_args, **_kwargs: {}) as loader:
        assert await async_setup_component(ha, "automation", {})
        assert await setup(ha, devices(door=DOOR_OPENS))
        assert issue(ha) is not None
        loader.side_effect = lambda *_args, **_kwargs: {"automation pururu": generated(ha)}
        await ha.services.async_call("automation", "reload", blocking=True)
        await ha.async_block_till_done()
    assert issue(ha) is None
    assert ha.states.get(automation("door")) is not None


async def test_with_the_include_there_is_no_issue(ha: HomeAssistant, automations: None) -> None:
    assert await setup(ha, devices(door=DOOR_OPENS))
    assert issue(ha) is None


async def test_without_reactions_there_is_no_issue(ha: HomeAssistant) -> None:
    assert await setup(ha, devices())
    assert issue(ha) is None


async def test_a_disabled_automation_is_no_missing_include(ha: HomeAssistant,
                                                           automations: None) -> None:
    assert await setup(ha, devices(door=DOOR_OPENS))
    er.async_get(ha).async_update_entity(automation("door"),
                                         disabled_by=er.RegistryEntryDisabler.USER)
    await ha.async_block_till_done()
    await ha.services.async_call("automation", "reload", blocking=True)
    await ha.async_block_till_done()
    assert issue(ha) is None


async def test_a_failed_write_is_logged_and_the_setup_goes_on(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    generated = module("generated")
    with patch.object(generated, "write_utf8_file_atomic", side_effect=WriteError("disk full")):
        assert await setup(ha, devices(door=DOOR_OPENS))
    assert "The automations are not written to pururu/automations/reactions.yaml: disk full" in caplog.text
    assert ha.states.get("light.pururu_lights_light_teto") is not None


async def test_removing_the_entry_leaves_an_empty_file(ha: HomeAssistant,
                                                      automations: None) -> None:
    assert await setup(ha, devices(door=DOOR_OPENS))
    entry = ha.config_entries.async_entries("pururu")[0]
    await ha.config_entries.async_remove(entry.entry_id)
    await ha.async_block_till_done()
    assert generated(ha) == []
    assert er.async_get(ha).async_get(automation("door")) is None
    assert ha.states.get(automation("door")) is None
    assert issue(ha) is None


# --- controller rulings: a failed write drops nothing, before-start is tested ------------


async def test_a_failed_write_drops_nothing_stale(
        ha: HomeAssistant, automations: None) -> None:
    """A dropped reaction whose write failed keeps its registry entry and its entry data."""
    assert await setup(ha, devices(door=DOOR_OPENS, night={"name": "Noite", "at": "22:00"}))
    generated = module("generated")
    with patch.object(generated, "write_utf8_file_atomic", side_effect=WriteError("disk full")):
        await reload(ha, devices(night={"name": "Noite", "at": "22:00"}))
    assert er.async_get(ha).async_get(automation("door")) is not None
    entry = ha.config_entries.async_entries("pururu")[0]
    assert "pururu_lights_reaction_door" in entry.data["automations"]


async def test_at_first_start_the_new_file_is_reloaded_once_and_included(
        ha: HomeAssistant) -> None:
    """A file new at start-up is reloaded exactly once, once HA has started, and included."""
    with patch("homeassistant.config.load_yaml_config_file",
               side_effect=lambda *_args, **_kwargs: {"automation pururu": generated(ha)}):
        assert await async_setup_component(ha, "automation",
                                           {"automation pururu": generated(ha)})
        reloaded = capture(ha, "automation_reloaded")
        await restart(ha, devices(door=DOOR_OPENS))
    state = ha.states.get(automation("door"))
    assert state is not None
    assert state.state != STATE_UNAVAILABLE
    assert state.attributes.get("id") == "pururu_lights_reaction_door"
    assert len(reloaded) == 1
    assert issue(ha) is None


async def test_a_restart_with_an_unchanged_file_reloads_nothing(ha: HomeAssistant) -> None:
    """Every restart: HA loads the file it already holds, then pururu finds it unchanged."""
    assert await setup(ha, devices(door=DOOR_OPENS))
    entry = ha.config_entries.async_entries("pururu")[0]
    await ha.config_entries.async_unload(entry.entry_id)
    await ha.async_block_till_done()
    ha.set_state(CoreState.not_running)
    with patch("homeassistant.config.load_yaml_config_file",
               side_effect=lambda *_args, **_kwargs: {"automation pururu": generated(ha)}):
        assert await async_setup_component(ha, "automation",
                                           {"automation pururu": generated(ha)})
        reloaded = capture(ha, "automation_reloaded")
        assert await ha.config_entries.async_setup(entry.entry_id)
        await ha.async_start()
        await ha.async_block_till_done()
    assert reloaded == []
    state = ha.states.get(automation("door"))
    assert state is not None
    assert state.state != STATE_UNAVAILABLE
    assert state.attributes["id"] == "pururu_lights_reaction_door"
    assert issue(ha) is None


# --- review: reloads that don't take, and failures that must leave things as they were -----

NIGHT = {"name": "Noite", "at": "22:00"}


def loaded(ha: HomeAssistant, key: str) -> bool:
    """Whether HA's automation component has the reaction's automation, not a placeholder."""
    state = ha.states.get(automation(key))
    return (state is not None and not state.attributes.get("restored")
            and state.attributes.get("id") == f"pururu_lights_reaction_{key}")


async def test_automations_not_loaded_are_reloaded_at_the_next_reload(ha: HomeAssistant) -> None:
    """A reload that didn't take (no include yet, or it failed) is retried, though the file is the same."""
    with patch("homeassistant.config.load_yaml_config_file",
               side_effect=lambda *_args, **_kwargs: {}) as loader:
        assert await async_setup_component(ha, "automation", {})
        assert await setup(ha, devices(door=DOOR_OPENS))
        assert not loaded(ha, "door")
        loader.side_effect = lambda *_args, **_kwargs: {"automation pururu": generated(ha)}
        reloaded = capture(ha, "automation_reloaded")
        await reload(ha, devices(door=DOOR_OPENS))
    assert len(reloaded) == 1
    assert loaded(ha, "door")
    assert issue(ha) is None


async def test_a_failed_reload_keeps_what_is_still_loaded_and_is_retried(
        ha: HomeAssistant, automations: None, caplog: pytest.LogCaptureFixture) -> None:
    """A dropped reaction HA still runs keeps its pururu ID until a reload drops it."""
    assert await setup(ha, devices(door=DOOR_OPENS, night=NIGHT))
    with patch("homeassistant.components.automation._async_process_config",
               side_effect=HomeAssistantError("boom")):
        await reload(ha, devices(night=NIGHT))
    assert "The automations are not reloaded: boom" in caplog.text
    assert loaded(ha, "door")
    assert er.async_get(ha).async_get(automation("door")) is not None
    entry = ha.config_entries.async_entries("pururu")[0]
    assert "pururu_lights_reaction_door" in entry.data["automations"]
    await reload(ha, devices(night=NIGHT))
    assert not loaded(ha, "door")
    assert er.async_get(ha).async_get(automation("door")) is None
    assert entry.data["automations"] == ["pururu_lights_reaction_night"]


async def test_a_failed_write_raises_no_include_issue(ha: HomeAssistant,
                                                      automations: None) -> None:
    """A reaction that never reached the file says nothing about the include."""
    assert await setup(ha, devices(door=DOOR_OPENS))
    generated = module("generated")
    with patch.object(generated, "write_utf8_file_atomic", side_effect=WriteError("disk full")):
        await reload(ha, devices(door=DOOR_OPENS, night=NIGHT))
    assert issue(ha) is None


async def test_a_failed_removal_keeps_the_automations_ids(ha: HomeAssistant,
                                                          automations: None) -> None:
    """The file still holds them: HA loads them again with their pururu IDs."""
    assert await setup(ha, devices(door=DOOR_OPENS))
    entry = ha.config_entries.async_entries("pururu")[0]
    generated = module("generated")
    with patch.object(generated, "write_utf8_file_atomic", side_effect=WriteError("disk full")):
        await ha.config_entries.async_remove(entry.entry_id)
        await ha.async_block_till_done()
    assert er.async_get(ha).async_get(automation("door")) is not None
