"""Reactions: a made-up washer and the laundry's lights, which react to it, to a door, to time."""

from typing import Any

from homeassistant.core import HomeAssistant
import pytest

from helpers import setup

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
