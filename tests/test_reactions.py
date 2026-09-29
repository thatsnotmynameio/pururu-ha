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
from pytest_homeassistant_custom_component.common import mock_restore_cache
import pytest
from pytest_homeassistant_custom_component.common import async_mock_service
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
    pytest.param({"name": "Tarde", "at": "13:00", "retry": {"times": 3, "every": {"hours": 1}}},
                 id="retry on a time"),
    pytest.param({"name": "Anoitecer", "sun": "sunset", "offset": {"minutes": -30},
                  "retry": {"times": 1, "every": {"minutes": 1}}}, id="retry on the sun"),
    pytest.param({"name": "Tarde", "at": "13:00", "retry": {"times": 12, "every": {"hours": 1}}},
                 id="retries ending at 12 hours"),
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
    pytest.param({**DOOR_OPENS, "retry": {"times": 1, "every": {"hours": 1}}},
                 "a reaction's retry goes with at or sun", id="retry on an entity"),
    pytest.param({"name": "X", "when": "light_teto", "to": "on",
                  "retry": {"times": 1, "every": {"hours": 1}}},
                 "a reaction's retry goes with at or sun", id="retry on when"),
    pytest.param({"name": "X", "at": "13:00", "retry": {"times": 0, "every": {"hours": 1}}},
                 "value must be at least 1", id="no retry"),
    pytest.param({"name": "X", "at": "13:00", "retry": {"times": 1, "every": {"seconds": 59}}},
                 "value must be at least 0:01:00", id="retry every under a minute"),
    pytest.param({"name": "X", "at": "13:00", "retry": {"times": 13, "every": {"hours": 1}}},
                 "a reaction's retries must end within 12 hours", id="retries over 12 hours"),
    pytest.param({"name": "X", "at": "13:00", "retry": {"every": {"hours": 1}}},
                 "required key 'times' not provided", id="retry without times"),
    pytest.param({"name": "X", "at": "13:00", "retry": {"times": 1}},
                 "required key 'every' not provided", id="retry without every"),
    pytest.param({"name": "X", "at": "13:00",
                  "retry": {"times": 1, "every": {"hours": 1}, "until": "on"}},
                 f"'until' is an invalid option for 'pururu', check: {PATH[1:]}->retry->until",
                 id="unknown key in retry"),
    pytest.param({"name": "X", "at": "13:00", "retry": {"times": 1, "every": {"seconds": 90.5}}},
                 "a reaction's retry every must be whole seconds", id="retry every fractional"),
    pytest.param({"name": "X", "at": "13:00", "retry": {"times": 2.9, "every": {"hours": 1}}},
                 "a reaction's retry times must be a whole number", id="retry times fractional"),
    pytest.param({"name": "X", "at": "13:00", "retry": {"times": True, "every": {"hours": 1}}},
                 "a reaction's retry times must be a whole number", id="retry times a boolean"),
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


PHONE = "notify.phone"
TOLD = {**DOOR_OPENS, "message": "A porta abriu."}


@pytest.mark.parametrize(("reaction", "config"), [
    pytest.param(TOLD, {"notify": PHONE}, id="the default"),
    pytest.param({**TOLD, "notify": PHONE}, None, id="its own"),
    pytest.param({**TOLD, "notify": [PHONE, "notify.tablet"]}, {"notify": "notify.x"}, id="its own list"),
])
async def test_a_message_that_goes_somewhere_is_accepted(
        ha: HomeAssistant, reaction: dict[str, Any], config: dict[str, Any] | None) -> None:
    assert await setup(ha, devices(it=reaction), config=config)


@pytest.mark.parametrize(("reaction", "reason"), [
    pytest.param({**DOOR_OPENS, "message": " "}, "length of value must be at least 1", id="blank message"),
    pytest.param({**DOOR_OPENS, "notify": PHONE}, "a reaction's notify goes with message",
                 id="notify without message"),
    pytest.param({**TOLD, "notify": "phone"}, "a notify action is notify.<name>", id="not a notify action"),
    pytest.param(TOLD, "device lights: reactions: it: message needs notify, here or in config.notify",
                 id="nowhere to go"),
])
async def test_a_message_that_cant_go_is_refused(ha: HomeAssistant, caplog: pytest.LogCaptureFixture,
                                                 reaction: dict[str, Any], reason: str) -> None:
    assert not await setup(ha, devices(it=reaction))
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(reason in message for message in errors), errors


async def test_config_notify_is_a_notify_action(ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    assert not await setup(ha, devices(it=TOLD), config={"notify": "phone"})
    assert "a notify action is notify.<name>" in caplog.text


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
    reactions = module("device_keys.reactions")
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


RETRY = {"times": 3, "every": {"hours": 1}}


def test_retries_are_the_time_again(ha: HomeAssistant) -> None:
    assert translated(ha, {"name": "Tarde", "at": "13:00:30", "retry": RETRY}) == [
        {"trigger": "time", "at": "13:00:30"},
        {"trigger": "time", "at": "14:00:30", "id": "retry_1", "variables": {"since": 3660}},
        {"trigger": "time", "at": "15:00:30", "id": "retry_2", "variables": {"since": 7260}},
        {"trigger": "time", "at": "16:00:30", "id": "retry_3", "variables": {"since": 10860}},
    ]


def test_retries_wrap_past_midnight(ha: HomeAssistant) -> None:
    triggers = translated(ha, {"name": "Noite", "at": "23:30",
                               "retry": {"times": 2, "every": {"minutes": 45}}})
    assert [t["at"] for t in triggers] == ["23:30:00", "00:15:00", "01:00:00"]


def test_retries_of_the_sun_add_to_its_offset(ha: HomeAssistant) -> None:
    assert translated(ha, {"name": "X", "sun": "sunset", "offset": {"minutes": -30},
                           "retry": {"times": 2, "every": {"minutes": 20}}}) == [
        {"trigger": "sun", "event": "sunset", "offset": "-00:30:00"},
        {"trigger": "sun", "event": "sunset", "offset": "-00:10:00", "id": "retry_1",
         "variables": {"since": 1260}},
        {"trigger": "sun", "event": "sunset", "offset": "00:10:00", "id": "retry_2",
         "variables": {"since": 2460}},
    ]


def test_retries_of_the_sun_without_offset(ha: HomeAssistant) -> None:
    assert translated(ha, {"name": "X", "sun": "sunrise",
                           "retry": {"times": 1, "every": {"hours": 1}}}) == [
        {"trigger": "sun", "event": "sunrise"},
        {"trigger": "sun", "event": "sunrise", "offset": "01:00:00", "id": "retry_1",
         "variables": {"since": 3660}},
    ]


RAN = "{{{{ since is not defined or as_timestamp({}, 0) < now().timestamp() - since }}}}"


def test_a_try_without_then_looks_at_the_automation(ha: HomeAssistant) -> None:
    reactions = module("device_keys.reactions")
    reaction = reactions.REACTION({"name": "Tarde", "at": "13:00", "retry": RETRY})
    assert reactions.automation(LIGHTS, "Luzes", "afternoon", reaction, None)["conditions"] == [
        {"condition": "template",
         "value_template": RAN.format("this.attributes.last_triggered")}]


def test_a_try_with_then_looks_at_the_program(ha: HomeAssistant) -> None:
    reactions = module("device_keys.reactions")
    reaction = reactions.REACTION({"name": "Tarde", "at": "13:00", "retry": RETRY,
                                   "then": "clean"})
    script = "script.pururu_lights_program_clean"
    assert reactions.automation(LIGHTS, "Luzes", "afternoon", reaction, None,
                                script)["conditions"] == [
        {"condition": "template",
         "value_template": RAN.format(f"state_attr('{script}', 'last_triggered')")}]


def test_without_retry_there_are_no_conditions(ha: HomeAssistant) -> None:
    """Every file written before retry is written again the same."""
    reactions = module("device_keys.reactions")
    reaction = reactions.REACTION({"name": "Noite", "at": "22:00", "then": "clean"})
    written = reactions.automation(LIGHTS, "Luzes", "night", reaction, None,
                                   "script.pururu_lights_program_clean")
    assert list(written) == ["id", "alias", "description", "triggers", "actions"]


def test_conditions_come_before_actions(ha: HomeAssistant) -> None:
    reactions = module("device_keys.reactions")
    reaction = reactions.REACTION({"name": "Tarde", "at": "13:00", "retry": RETRY})
    assert list(reactions.automation(LIGHTS, "Luzes", "afternoon", reaction, None)) == [
        "id", "alias", "description", "triggers", "conditions", "actions"]


def test_the_automation_of_a_reaction(ha: HomeAssistant) -> None:
    reactions = module("device_keys.reactions")
    assert reactions.automation(LIGHTS, "Luzes", "door", reactions.REACTION(DOOR_OPENS),
                                DOOR) == {
        "id": "pururu_lights_reaction_door",
        "alias": "Luzes Porta abriu",
        "description": "pururu: lights, door",
        "triggers": translated(ha, DOOR_OPENS, DOOR),
        "actions": [],
    }


def test_then_starts_its_program_unless_it_runs(ha: HomeAssistant) -> None:
    reactions = module("device_keys.reactions")
    reaction = reactions.REACTION({**DOOR_OPENS, "then": "clean"})
    script = "script.pururu_lights_program_clean"
    assert reactions.automation(LIGHTS, "Luzes", "door", reaction, DOOR, script)["actions"] == [{
        "if": [{"condition": "state", "entity_id": script, "state": "off"}],
        "then": [{"action": "script.turn_on", "target": {"entity_id": script}}],
    }]


def test_a_message_is_told_after_its_program_starts(ha: HomeAssistant) -> None:
    reactions = module("device_keys.reactions")
    reaction = reactions.REACTION({**TOLD, "then": "clean"})
    script = "script.pururu_lights_program_clean"
    actions = reactions.automation(LIGHTS, "Luzes", "door", reaction, DOOR, script,
                                   ["notify.a", "notify.b"])["actions"]
    assert actions[0]["then"] == [{"action": "script.turn_on", "target": {"entity_id": script}}]
    assert actions[1:] == [{"parallel": [
        {"action": target, "data": {"title": "Luzes", "message": "A porta abriu."}, "continue_on_error": True}
        for target in ("notify.a", "notify.b")
    ]}]


def test_without_a_message_nobody_is_told(ha: HomeAssistant) -> None:
    reactions = module("device_keys.reactions")
    reaction = reactions.REACTION(DOOR_OPENS)
    assert reactions.automation(LIGHTS, "Luzes", "door", reaction, DOOR, None, ["notify.a"])["actions"] == []


@pytest.mark.parametrize("then", [["clean"], "script.pururu_lights_program_clean"])
def test_then_is_a_slug(ha: HomeAssistant, then: Any) -> None:
    reaction = module("device_keys.reactions").REACTION
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


async def test_the_default_or_its_own_notify(ha: HomeAssistant) -> None:
    assert await setup(ha, devices(door=TOLD, mine={**TOLD, "notify": "notify.tablet"}),
                       config={"notify": [PHONE]})
    told = {a["id"]: [action["action"] for action in a["actions"][0]["parallel"]] for a in generated(ha)}
    assert told == {"pururu_lights_reaction_door": [PHONE],
                    "pururu_lights_reaction_mine": ["notify.tablet"]}


async def test_a_message_is_text(ha: HomeAssistant, automations: None) -> None:
    """Through HA's own automation: the phone gets the message as written."""
    calls = async_mock_service(ha, "notify", "phone")
    await fake(ha, DOOR, "off")
    assert await setup(ha, devices(door={**TOLD, "message": "Porta {{ aberta }} {% raw %}"}),
                       config={"notify": PHONE})
    await fake(ha, DOOR, "on")
    await ha.async_block_till_done()
    assert [call.data for call in calls] == [{"title": "Luzes", "message": "Porta {{ aberta }} {% raw %}"}]


async def test_a_phone_gone_does_not_keep_the_next_from_being_told(ha: HomeAssistant,
                                                                   automations: None) -> None:
    """An unpaired phone's notify action doesn't exist: HA stops a sequence on it, whatever continue_on_error."""
    calls = async_mock_service(ha, "notify", "phone")
    await fake(ha, DOOR, "off")
    assert await setup(ha, devices(door=TOLD), config={"notify": ["notify.gone", PHONE]})
    await fake(ha, DOOR, "on")
    await ha.async_block_till_done()
    assert [call.data for call in calls] == [{"title": "Luzes", "message": "A porta abriu."}]


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
    assert generated(ha)[0]["actions"] == module("device_keys.reactions").actions(CLEAN)


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


async def test_a_missing_notify_action_does_not_keep_the_program_from_starting(
        ha: HomeAssistant, both: None) -> None:
    await fake(ha, DOOR, "off")
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, pool(clean={**DOOR_OPENS, "then": "clean", "message": "Limpando",
                                       "notify": "notify.nobody"}))
    await fake(ha, DOOR, "on")
    await settle()
    assert script_state(ha) == "on"


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
    assert generated(ha)[0]["actions"] == module("device_keys.reactions").actions("script.limpar_piscina")
    started = capture(ha, "script_started")
    await fake(ha, DOOR, "on")
    await settle()
    assert len(started) == 1


async def test_the_condition_follows_the_script_renamed(ha: HomeAssistant) -> None:
    """With the old ID, last_triggered would be none and every try would run."""
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, pool(clean={"name": "Tarde", "at": "13:00", "then": "clean",
                                       "retry": {"times": 1, "every": {"hours": 1}}}))
    er.async_get(ha).async_update_entity(CLEAN, new_entity_id="script.limpar_piscina")
    await ha.async_block_till_done()
    assert generated(ha)[0]["conditions"] == module("device_keys.reactions").conditions(
        {"retry": {"times": 1, "every": timedelta(hours=1)}}, "script.limpar_piscina")
    assert "script.limpar_piscina" in generated(ha)[0]["conditions"][0]["value_template"]


async def test_renaming_a_script_no_reaction_starts_still_reloads(ha: HomeAssistant) -> None:
    """Its statistics watch it: they follow the new ID."""
    assert await setup(ha, pool(night={"name": "Noite", "at": "22:00"}))
    with patch.object(ha.config_entries, "async_schedule_reload") as reloading:
        er.async_get(ha).async_update_entity(CLEAN, new_entity_id="script.limpar_piscina")
        await ha.async_block_till_done()
    reloading.assert_called_once()


async def test_renaming_ones_own_script_reloads_nothing(ha: HomeAssistant) -> None:
    er.async_get(ha).async_get_or_create("script", "script", "mine", suggested_object_id="mine")
    assert await setup(ha, pool())
    with patch.object(ha.config_entries, "async_schedule_reload") as reloading:
        er.async_get(ha).async_update_entity("script.mine", new_entity_id="script.minha")
        await ha.async_block_till_done()
    reloading.assert_not_called()


async def test_a_reaction_on_another_device_starts_its_own_program(ha: HomeAssistant) -> None:
    config = pool(power={"name": "Potência", "device": WASHER, "when": "appliance_power",
                         "above": 10, "then": "clean"})
    config[WASHER] = {"name": "Washer", "appliance": APPLIANCE}
    assert await setup(ha, config)
    assert generated(ha)[0]["actions"] == module("device_keys.reactions").actions(CLEAN)


async def test_a_script_not_written_drops_its_reaction(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """The scripts' file can't be written: the new program isn't in HA, so its reaction isn't generated."""
    files = module("core.files")
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


@pytest.mark.parametrize("named", [{}, {"device": LIGHTS}], ids=["its device implied", "named"])
async def test_a_reaction_on_its_own_counter_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, named: dict[str, Any]) -> None:
    it = {"name": "Eu", "when": "reaction_it_triggered_total", "above": 3, **named}
    assert not await setup(ha, devices(it=it))
    assert "reactions: it: reaction_it_triggered_total is its own statistic" in caplog.text


async def test_a_reaction_on_a_programs_statistic(ha: HomeAssistant) -> None:
    done = {"name": "Limpou", "when": "program_clean_last_cycle_end", "to": "unknown"}
    assert await setup(ha, pool(done=done))
    trigger = generated(ha)[0]["triggers"][0]
    assert trigger["entity_id"] == "sensor.pururu_pool_program_clean_last_cycle_end"


async def test_the_count_follows_its_automation_renamed(ha: HomeAssistant, both: None) -> None:
    await fake(ha, DOOR, "off")
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, pool())
    er.async_get(ha).async_update_entity("automation.pururu_pool_reaction_clean",
                                         new_entity_id="automation.porta_limpa")
    await ha.async_block_till_done()
    await fake(ha, DOOR, "on")
    await settle()
    assert count(ha) == "1"


async def test_a_run_its_reaction_started_is_counted_at_its_end(
        ha: HomeAssistant, freezer: Any, both: None) -> None:
    await fake(ha, DOOR, "off")
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, pool())
    await fake(ha, DOOR, "on")
    await settle()
    await tick(ha, freezer, 2 * 60 * 60)
    await ha.async_block_till_done()
    assert count(ha, "sensor.pururu_pool_program_clean_cycles_total") == "1"
    assert count(ha) == "1"


async def test_a_count_never_follows_an_automation_pururu_does_not_generate(
        ha: HomeAssistant) -> None:
    """Its ID taken by one of the user's automations: the reaction isn't generated, and that one isn't counted."""
    er.async_get(ha).async_get_or_create(
        "automation", "automation", "pururu_pool_reaction_clean", suggested_object_id="mine")
    assert await setup(ha, pool())
    ha.bus.async_fire("automation_triggered", {"entity_id": "automation.mine"})
    ha.bus.async_fire("automation_triggered",
                      {"entity_id": "automation.pururu_pool_reaction_clean"})
    await ha.async_block_till_done()
    assert count(ha) == "0"


# --- retry --------------------------------------------------------------------------------

SOON = {"name": "Logo", "at": "10:05", "retry": {"times": 2, "every": {"minutes": 10}}}
CLEANING_AUTOMATION = "automation.pururu_pool_reaction_clean"


def runs(events: list[Any], entity_id: str) -> int:
    """How many times the automation ran (its conditions passed)."""
    return sum(1 for e in events if e.data["entity_id"] == entity_id)


async def switch(ha: HomeAssistant, entity_id: str, on: bool) -> None:
    await ha.services.async_call("automation", "turn_on" if on else "turn_off",
                                 {"entity_id": entity_id}, blocking=True)


async def restarted(ha: HomeAssistant, *, scripts: bool = False) -> None:
    """HA's automations (and scripts) set up after pururu, from the restore cache seeded first.

    Seeded before pururu's setup: seeding it later replaces the data its
    entities registered in, and their removal at teardown fails.
    """
    def included(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"automation pururu": generated(ha), "script pururu": generated_scripts(ha)}

    with patch("homeassistant.config.load_yaml_config_file", side_effect=included):
        if scripts:
            assert await async_setup_component(ha, "script",
                                               {"script pururu": generated_scripts(ha)})
        assert await async_setup_component(ha, "automation",
                                           {"automation pururu": generated(ha)})
    await ha.async_block_till_done()


async def test_the_occurrence_run_skips_the_tries(ha: HomeAssistant, freezer: Any,
                                                  automations: None) -> None:
    assert await setup(ha, devices(soon=SOON))
    triggered = capture(ha, "automation_triggered")
    await tick(ha, freezer, 300)    # 10:05, the occurrence
    assert runs(triggered, automation("soon")) == 1
    await tick(ha, freezer, 600)    # 10:15
    await tick(ha, freezer, 600)    # 10:25
    assert runs(triggered, automation("soon")) == 1


async def test_a_missed_occurrence_is_tried_again_once(ha: HomeAssistant, freezer: Any,
                                                       automations: None) -> None:
    assert await setup(ha, devices(soon=SOON))
    triggered = capture(ha, "automation_triggered")
    await switch(ha, automation("soon"), on=False)
    await tick(ha, freezer, 360)    # 10:06, off at 10:05
    await switch(ha, automation("soon"), on=True)
    assert runs(triggered, automation("soon")) == 0
    await tick(ha, freezer, 540)    # 10:15, the first try runs
    assert runs(triggered, automation("soon")) == 1
    await tick(ha, freezer, 600)    # 10:25, skipped
    assert runs(triggered, automation("soon")) == 1


async def test_a_run_by_hand_skips_the_tries(ha: HomeAssistant, freezer: Any,
                                             automations: None) -> None:
    assert await setup(ha, devices(soon=SOON))
    triggered = capture(ha, "automation_triggered")
    await switch(ha, automation("soon"), on=False)
    await tick(ha, freezer, 360)    # 10:06, off at 10:05
    await switch(ha, automation("soon"), on=True)
    assert runs(triggered, automation("soon")) == 0
    await ha.services.async_call("automation", "trigger",
                                 {"entity_id": automation("soon")}, blocking=True)
    assert runs(triggered, automation("soon")) == 1
    await tick(ha, freezer, 540)    # 10:15
    await tick(ha, freezer, 600)    # 10:25
    assert runs(triggered, automation("soon")) == 1


def ran(minutes: float) -> dict[str, str]:
    """Restored attributes: last triggered `minutes` after now (the test's start, 10:00)."""
    return {"last_triggered": (dt_util.utcnow() + timedelta(minutes=minutes)).isoformat()}


async def test_a_restart_keeps_the_occurrences_run(ha: HomeAssistant, freezer: Any) -> None:
    """HA restores last_triggered: after a restart, a try still sees the occurrence's run."""
    mock_restore_cache(ha, [State(automation("soon"), "on", ran(5))])
    assert await setup(ha, devices(soon=SOON))
    await tick(ha, freezer, 360)    # 10:06: the occurrence ran at 10:05, then HA restarted
    await restarted(ha)
    triggered = capture(ha, "automation_triggered")
    await tick(ha, freezer, 540)    # 10:15
    await tick(ha, freezer, 600)    # 10:25
    assert runs(triggered, automation("soon")) == 0


async def test_a_restart_without_a_run_tries_again(ha: HomeAssistant, freezer: Any) -> None:
    """The counterpart: restored with no run since 10:05, the first try runs."""
    mock_restore_cache(ha, [State(automation("soon"), "on", ran(-24 * 60))])
    assert await setup(ha, devices(soon=SOON))
    await tick(ha, freezer, 360)    # 10:06: HA was down at 10:05
    await restarted(ha)
    triggered = capture(ha, "automation_triggered")
    await tick(ha, freezer, 540)    # 10:15
    await tick(ha, freezer, 600)    # 10:25
    assert runs(triggered, automation("soon")) == 1


async def test_a_restart_keeps_the_programs_start(ha: HomeAssistant, freezer: Any) -> None:
    """With then, the try reads the script's restored last_triggered, not the automation's."""
    await fake(ha, REAL_PUMP, "off")
    mock_restore_cache(ha, [State(CLEAN, "off", ran(5))])
    assert await setup(ha, pool(clean={"name": "Logo", "at": "10:05", "then": "clean",
                                       "retry": {"times": 2, "every": {"minutes": 10}}}))
    await tick(ha, freezer, 360)    # 10:06: the program started at 10:05, then HA restarted
    await restarted(ha, scripts=True)
    triggered = capture(ha, "automation_triggered")
    started = capture(ha, "script_started")
    await tick(ha, freezer, 540)    # 10:15
    await tick(ha, freezer, 600)    # 10:25
    assert (len(triggered), len(started)) == (0, 0)


async def test_a_busy_program_is_started_by_a_try(ha: HomeAssistant, freezer: Any,
                                                  both: None) -> None:
    """Started by hand at 10:00, it runs 2 hours: 10:05 and 11:05 find it running, 12:05 starts it."""
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, pool(clean={"name": "Logo", "at": "10:05", "then": "clean",
                                       "retry": {"times": 3, "every": {"hours": 1}}}))
    await ha.services.async_call("script", "turn_on", {"entity_id": CLEAN}, blocking=True)
    await settle()
    triggered = capture(ha, "automation_triggered")
    started = capture(ha, "script_started")
    await tick(ha, freezer, 300)    # 10:05, busy
    await tick(ha, freezer, 3600)   # 11:05, a try: nothing started since, still busy
    await settle()
    assert (len(triggered), len(started)) == (2, 0)
    await tick(ha, freezer, 3360)   # 12:01: the program ended at 12:00
    await settle()
    await tick(ha, freezer, 240)    # 12:05, a try
    await settle()
    assert (len(triggered), len(started)) == (3, 1)


async def test_a_busy_programs_message_is_told_once(ha: HomeAssistant, freezer: Any,
                                                    both: None) -> None:
    """Told at 10:05, when the program was busy; the tries that find it busy or start it don't tell it again."""
    calls = async_mock_service(ha, "notify", "phone")
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, pool(clean={"name": "Logo", "at": "10:05", "then": "clean",
                                       "message": "Limpando", "notify": PHONE,
                                       "retry": {"times": 3, "every": {"hours": 1}}}))
    await ha.services.async_call("script", "turn_on", {"entity_id": CLEAN}, blocking=True)
    await settle()
    started = capture(ha, "script_started")
    await tick(ha, freezer, 300)    # 10:05, busy: told
    await tick(ha, freezer, 3600)   # 11:05, a try, still busy
    await tick(ha, freezer, 3360)   # 12:01: the program ended at 12:00
    await settle()
    await tick(ha, freezer, 240)    # 12:05, a try starts it
    await settle()
    assert len(started) == 1
    assert [call.data for call in calls] == [{"title": "Piscina", "message": "Limpando"}]


async def test_a_program_started_after_the_occurrence_skips_the_tries(
        ha: HomeAssistant, freezer: Any, both: None) -> None:
    await fake(ha, REAL_PUMP, "off")
    assert await setup(ha, pool(clean={"name": "Logo", "at": "10:05", "then": "clean",
                                       "retry": {"times": 2, "every": {"hours": 3}}}))
    triggered = capture(ha, "automation_triggered")
    await switch(ha, CLEANING_AUTOMATION, on=False)
    await tick(ha, freezer, 360)    # 10:06, off at 10:05
    await switch(ha, CLEANING_AUTOMATION, on=True)
    await ha.services.async_call("script", "turn_on", {"entity_id": CLEAN}, blocking=True)
    await settle()                  # started by hand at 10:06, ends at 12:06
    await tick(ha, freezer, 3 * 3600)   # 13:05
    await tick(ha, freezer, 3 * 3600)   # 16:05
    assert len(triggered) == 0


async def test_the_sun_is_tried_again(ha: HomeAssistant, freezer: Any,
                                      automations: None) -> None:
    assert await setup(ha, devices(dusk={"name": "Anoitecer", "sun": "sunset",
                                         "retry": {"times": 1, "every": {"minutes": 10}}}))
    triggered = capture(ha, "automation_triggered")
    await switch(ha, automation("dusk"), on=False)
    sunset = get_astral_event_next(ha, "sunset")
    await tick(ha, freezer, (sunset - dt_util.utcnow()).total_seconds() + 60)
    await switch(ha, automation("dusk"), on=True)
    assert runs(triggered, automation("dusk")) == 0
    await tick(ha, freezer, 540)
    assert runs(triggered, automation("dusk")) == 1
