"""Alert lights: a made-up house's alerts borrowing the pool's LED and the porch's relay."""

import asyncio
from datetime import timedelta
from pathlib import Path
import re
from typing import Any

from homeassistant.core import Context, Event, HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
import yaml

from helpers import capture, fake, module, reload, restart, settle, setup, tick

HOUSE = "casa"
REAL_LED = "light.led_piscina"
LED = "light.pururu_pool_light_led"
REAL_RELAY = "switch.varanda_rele"
RELAY = "light.pururu_varanda_light_rele"
# The LED as Zigbee2MQTT shows it: hs colour, breathe among its effects,
# EFFECT | FLASH | TRANSITION
BULB = {"supported_color_modes": ["hs"], "color_mode": "hs", "brightness": 255,
        "hs_color": [240.0, 100.0], "effect_list": ["blink", "breathe"],
        "supported_features": 44}
# The house's switches: turning one on raises the alert watching it
REAL = {name: f"switch.casa_{name}" for name in ("gate", "smoke", "mail", "leak")}
GROUPS = {"default": {"pool": ["led"]}, "porch": {"varanda": ["rele"]},
          "both": {"pool": ["led"], "varanda": ["rele"]}}
CONFIG = {"alerts": {"lights": {"groups": GROUPS}}}
RED = {"color_name": "red", "brightness_pct": 100, "effect": "breathe"}
ORANGE = {"color_name": "orange", "brightness_pct": 100, "effect": "breathe"}
BLUE = {"color_name": "blue", "brightness_pct": 100, "effect": "breathe"}
GREEN = {"color_name": "green", "brightness_pct": 50}
APPLIANCE: dict[str, Any] = {
    "power": "sensor.lavadora_power",
    "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}


def alert(name: str) -> str:
    return f"binary_sensor.pururu_{HOUSE}_alert_{name}"


def raised(name: str, priority: str, lights: Any = True) -> dict[str, Any]:
    """An alert on while the house's switch `name` is on; lights None: no lights key."""
    block: dict[str, Any] = {"name": name.title(), "when": f"switch_{name}", "is": "on",
                             "priority": priority}
    if lights is not None:
        block["lights"] = lights
    return block


def devices(**alerts: dict[str, Any]) -> dict[str, Any]:
    house: dict[str, Any] = {
        "name": "Casa",
        "switches": {name: {"entity": real, "name": name.title()} for name, real in REAL.items()},
    }
    if alerts:
        house["alerts"] = alerts
    return {
        "pool": {"name": "Piscina", "lights": {"led": {"entity": REAL_LED, "name": "LED"}}},
        "varanda": {"name": "Varanda",
                    "lights": {"rele": {"entity": REAL_RELAY, "name": "Relé"}}},
        HOUSE: house,
    }


def calls(events: list[Event], entity_id: str) -> list[tuple[str, dict[str, Any]]]:
    """The light services called on `entity_id`, and their data without it."""
    return [(event.data["service"],
             {k: v for k, v in event.data["service_data"].items() if k != "entity_id"})
            for event in events
            if event.data["domain"] == "light"
            and event.data["service_data"].get("entity_id") in (entity_id, [entity_id])]


def attributes(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    return dict(hass.states.get(entity_id).attributes)


def errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]


@pytest.fixture
async def house(ha: HomeAssistant) -> HomeAssistant:
    """The real lights and switches, all off, before pururu sets up."""
    await fake(ha, REAL_LED, "off", BULB)
    await fake(ha, REAL_RELAY, "off")
    for real in REAL.values():
        await fake(ha, real, "off")
    return ha


async def turn(hass: HomeAssistant, name: str, state: str) -> None:
    """Turn the house's real switch `name` on or off; its alert and the lights follow."""
    await fake(hass, REAL[name], state)
    await hass.async_block_till_done()


# --- configuration ------------------------------------------------------------------------


async def test_without_config_every_default_applies(house: HomeAssistant) -> None:
    assert await setup(house, devices())
    assert module("alert_lights").SCHEMA({}) == {
        "groups": {},
        "high": {"turn_on": RED, "repeat": timedelta(seconds=15)},
        "medium": {"turn_on": ORANGE, "repeat": timedelta(seconds=15)},
        "low": {"turn_on": BLUE, "repeat": timedelta(seconds=15)},
        "resolved": {"turn_on": GREEN, "for": timedelta(seconds=120)},
    }


async def test_a_priority_written_replaces_its_default_whole(house: HomeAssistant) -> None:
    """No breathe nor repeat left over from the default."""
    assert await setup(house, devices())
    settings = module("alert_lights").SCHEMA({"high": {"turn_on": {"color_name": "purple"}}})
    assert settings["high"] == {"turn_on": {"color_name": "purple"}}
    assert settings["medium"]["turn_on"] == ORANGE


@pytest.mark.parametrize("lights", [
    pytest.param({}, id="empty"),
    pytest.param({"groups": GROUPS}, id="groups"),
    pytest.param({"high": {"turn_on": {"rgb_color": [255, 0, 0], "flash": "long"}}},
                 id="rgb and flash"),
    pytest.param({"low": {"turn_on": {}}}, id="just on"),
    pytest.param({"resolved": {"turn_on": {"color_name": "dark green"}, "for": {"seconds": 5}}},
                 id="resolved"),
])
async def test_valid_alert_lights_are_accepted(house: HomeAssistant, lights: Any) -> None:
    assert await setup(house, devices(), config={"alerts": {"lights": lights}})


def lights_block(**block: Any) -> dict[str, Any]:
    return {"alerts": {"lights": block}}


@pytest.mark.parametrize(("config", "reason"), [
    pytest.param({"nothing": 1}, "'nothing' is an invalid option", id="unknown key in config"),
    pytest.param({"alerts": {"nothing": 1}}, "'nothing' is an invalid option",
                 id="unknown key in alerts"),
    pytest.param(lights_block(colours={}), "'colours' is an invalid option",
                 id="unknown key in lights"),
    pytest.param(lights_block(groups={"Porch": {"varanda": ["rele"]}}), "invalid slug Porch",
                 id="group not a slug"),
    pytest.param(lights_block(groups={"porch": {}}), "length of value must be at least 1",
                 id="empty group"),
    pytest.param(lights_block(groups={"porch": {"varanda": []}}),
                 "length of value must be at least 1", id="no light"),
    pytest.param(lights_block(groups={"porch": {"varanda": ["rele", "rele"]}}),
                 "a light is listed twice", id="a light twice"),
    pytest.param(lights_block(groups={"porch": {"varanda": "rele"}}), "expected a list",
                 id="not a list"),
    pytest.param(lights_block(groups={"porch": {"garagem": ["rele"]}}),
                 "config.alerts.lights.groups: porch: device garagem is not in devices",
                 id="unknown device"),
    pytest.param(lights_block(groups={"porch": {"varanda": ["teto"]}}),
                 "config.alerts.lights.groups: porch: device varanda has no light teto",
                 id="unknown light"),
    pytest.param(lights_block(groups={"porch": {"casa": ["gate"]}}),
                 "config.alerts.lights.groups: porch: device casa has no light gate",
                 id="a switch, not a light"),
    pytest.param(lights_block(high={"turn_on": {"entity_id": LED}}),
                 "'entity_id' is an invalid option", id="entity_id in turn_on"),
    pytest.param(lights_block(high={"turn_on": {"color_name": "reed"}}),
                 "reed is not a colour name Home Assistant knows", id="unknown colour"),
    pytest.param(lights_block(high={"repeat": {"seconds": 15}}),
                 "required key 'turn_on' not provided", id="no turn_on"),
    pytest.param(lights_block(high={"turn_on": {}, "repeat": {"minutes": 1}}),
                 "'minutes' is an invalid option", id="repeat in minutes"),
    pytest.param(lights_block(high={"turn_on": {}, "repeat": {"seconds": 0}}),
                 "value must be at least 1", id="repeat zero"),
    pytest.param(lights_block(high={"turn_on": {}, "repeat": {"seconds": 1.5}}),
                 "expected int", id="repeat not whole"),
    pytest.param(lights_block(high={"turn_on": {}, "for": {"seconds": 5}}),
                 "'for' is an invalid option", id="for on a priority"),
    pytest.param(lights_block(resolved={"turn_on": {}}),
                 "required key 'for' not provided", id="resolved without for"),
    pytest.param(lights_block(resolved={"turn_on": {}, "for": {"seconds": 5},
                                        "repeat": {"seconds": 5}}),
                 "'repeat' is an invalid option", id="repeat on resolved"),
])
async def test_invalid_alert_lights_are_refused(
        house: HomeAssistant, caplog: pytest.LogCaptureFixture, config: dict[str, Any],
        reason: str) -> None:
    """Refused, and for its own reason: a typo in the test would be refused for another one."""
    assert not await setup(house, devices(), config=config)
    assert any(reason in message for message in errors(caplog)), errors(caplog)


# --- an alert's lights ------------------------------------------------------------------------


@pytest.mark.parametrize(("lights", "group"), [
    pytest.param(True, "default", id="true"),
    pytest.param("porch", "porch", id="a group"),
])
async def test_an_alerts_group_is_an_attribute(
        house: HomeAssistant, lights: Any, group: str) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium", lights)), config=CONFIG)
    assert attributes(house, alert("gate"))["lights"] == group


@pytest.mark.parametrize("lights", [pytest.param(None, id="no key"),
                                    pytest.param(False, id="false")])
async def test_an_alert_without_lights_has_no_group(house: HomeAssistant, lights: Any) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium", lights)), config=CONFIG)
    assert "lights" not in attributes(house, alert("gate"))


NO_DEFAULT = ("device casa: alerts: gate: there is no default group in "
              "config.alerts.lights.groups")


@pytest.mark.parametrize(("config", "lights", "reason"), [
    pytest.param(lights_block(groups={"porch": {"varanda": ["rele"]}}), True, NO_DEFAULT,
                 id="no default group"),
    pytest.param(None, True, NO_DEFAULT, id="no config"),
    pytest.param(CONFIG, "outside",
                 "device casa: alerts: gate: outside is not a group of "
                 "config.alerts.lights.groups", id="unknown group"),
    pytest.param(CONFIG, "Porch", "invalid slug Porch", id="group not a slug"),
])
async def test_an_alerts_lights_must_name_a_group(
        house: HomeAssistant, caplog: pytest.LogCaptureFixture, config: Any, lights: Any,
        reason: str) -> None:
    assert not await setup(house, devices(gate=raised("gate", "medium", lights)), config=config)
    assert any(reason in message for message in errors(caplog)), errors(caplog)


async def test_a_ready_made_alerts_lights_must_name_a_group(
        house: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    washer = {"name": "Lavadora",
              "appliance": {**APPLIANCE, "alerts": {"offline": {"lights": "outside"}}}}
    assert not await setup(house, {**devices(), "lavadora": washer}, config=CONFIG)
    reason = ("device lavadora: appliance: alerts: offline: outside is not a group of "
              "config.alerts.lights.groups")
    assert any(reason in message for message in errors(caplog)), errors(caplog)


async def test_a_ready_made_alerts_group_is_an_attribute(house: HomeAssistant) -> None:
    washer = {"name": "Lavadora", "appliance": {**APPLIANCE, "alerts": {"offline": {"lights": True}}}}
    assert await setup(house, {**devices(), "lavadora": washer}, config=CONFIG)
    offline = "binary_sensor.pururu_lavadora_appliance_alert_offline"
    assert attributes(house, offline)["lights"] == "default"


# --- lending the lights -------------------------------------------------------------------


async def test_an_alert_with_lights_borrows_its_group(house: HomeAssistant) -> None:
    events = capture(house, "call_service")
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    assert calls(events, LED) == []
    await turn(house, "gate", "on")
    assert calls(events, LED) == [("turn_on", ORANGE)]
    assert attributes(house, LED)["alert"] == "medium"
    assert attributes(house, LED)["alerts"] == [alert("gate")]
    assert calls(events, RELAY) == []


async def test_an_alert_without_lights_borrows_nothing(house: HomeAssistant) -> None:
    events = capture(house, "call_service")
    assert await setup(house, devices(gate=raised("gate", "high", None)), config=CONFIG)
    await turn(house, "gate", "on")
    assert calls(events, LED) == []
    assert "alert" not in attributes(house, LED)


async def test_the_priority_is_sent_again_every_15_seconds(
        house: HomeAssistant, freezer: Any) -> None:
    """breathe is a one-shot effect."""
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    await tick(house, freezer, 14)
    assert calls(events, LED) == []
    await tick(house, freezer, 1)
    assert calls(events, LED) == [("turn_on", ORANGE)]
    await tick(house, freezer, 15)
    assert calls(events, LED) == [("turn_on", ORANGE)] * 2


async def test_the_highest_priority_wins_and_gives_way(house: HomeAssistant) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium"),
                                      smoke=raised("smoke", "high")), config=CONFIG)
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    await turn(house, "smoke", "on")
    assert calls(events, LED) == [("turn_on", RED)]
    assert attributes(house, LED)["alerts"] == [alert("gate"), alert("smoke")]
    await turn(house, "smoke", "off")
    assert calls(events, LED) == [("turn_on", RED), ("turn_on", ORANGE)]
    assert attributes(house, LED)["alert"] == "medium"
    assert attributes(house, LED)["alerts"] == [alert("gate")]


async def test_low_is_blue(house: HomeAssistant) -> None:
    events = capture(house, "call_service")
    assert await setup(house, devices(leak=raised("leak", "low")), config=CONFIG)
    await turn(house, "leak", "on")
    assert calls(events, LED) == [("turn_on", BLUE)]


async def test_another_alert_of_the_same_priority_only_joins(house: HomeAssistant) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium"),
                                      mail=raised("mail", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    await turn(house, "mail", "on")
    assert calls(events, LED) == []
    assert attributes(house, LED)["alerts"] == [alert("gate"), alert("mail")]
    await turn(house, "gate", "off")
    assert calls(events, LED) == []
    assert attributes(house, LED)["alerts"] == [alert("mail")]


async def test_the_last_alert_ending_shows_resolved_then_hands_the_light_back(
        house: HomeAssistant, freezer: Any) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    released = capture(house, "pururu_alert_lights_released")
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    await turn(house, "gate", "off")
    assert calls(events, LED) == [("turn_on", GREEN)]
    assert attributes(house, LED)["alert"] == "resolved"
    assert attributes(house, LED)["alerts"] == []
    await tick(house, freezer, 119)
    assert calls(events, LED) == [("turn_on", GREEN)]
    assert released == []
    await tick(house, freezer, 1)
    assert calls(events, LED) == [("turn_on", GREEN), ("turn_off", {})]
    assert [event.data for event in released] == [{"entity_id": LED}]
    assert "alert" not in attributes(house, LED)


async def test_an_alert_during_resolved_takes_the_light_again(
        house: HomeAssistant, freezer: Any) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    released = capture(house, "pururu_alert_lights_released")
    await turn(house, "gate", "on")
    await turn(house, "gate", "off")
    await tick(house, freezer, 60)
    events = capture(house, "call_service")
    await turn(house, "gate", "on")
    assert calls(events, LED) == [("turn_on", ORANGE)]
    await tick(house, freezer, 61)
    assert "turn_off" not in [service for service, _ in calls(events, LED)]
    assert released == []
    assert attributes(house, LED)["alert"] == "medium"


async def test_an_alert_of_another_group_does_not_hold_the_light(
        house: HomeAssistant, freezer: Any) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium"),
                                      mail=raised("mail", "low", "porch")), config=CONFIG)
    released = capture(house, "pururu_alert_lights_released")
    await turn(house, "gate", "on")
    await turn(house, "mail", "on")
    events = capture(house, "call_service")
    await turn(house, "gate", "off")
    assert calls(events, LED) == [("turn_on", GREEN)]
    assert calls(events, RELAY) == []
    await tick(house, freezer, 120)
    assert calls(events, LED) == [("turn_on", GREEN), ("turn_off", {})]
    assert [event.data for event in released] == [{"entity_id": LED}]
    assert attributes(house, RELAY)["alert"] == "low"


async def test_a_light_in_two_groups_shows_the_highest_of_both(house: HomeAssistant) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium"),
                                      smoke=raised("smoke", "high", "both")), config=CONFIG)
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    await turn(house, "smoke", "on")
    assert calls(events, LED) == [("turn_on", RED)]
    assert calls(events, RELAY) == [("turn_on", RED)]
    await turn(house, "smoke", "off")
    assert calls(events, LED) == [("turn_on", RED), ("turn_on", ORANGE)]
    assert calls(events, RELAY) == [("turn_on", RED), ("turn_on", GREEN)]
    await turn(house, "gate", "off")
    assert calls(events, LED)[-1] == ("turn_on", GREEN)


async def test_a_priority_without_repeat_is_sent_once(house: HomeAssistant, freezer: Any) -> None:
    config = {"alerts": {"lights": {"groups": GROUPS,
                                    "high": {"turn_on": {"color_name": "purple"}}}}}
    assert await setup(house, devices(smoke=raised("smoke", "high")), config=config)
    events = capture(house, "call_service")
    await turn(house, "smoke", "on")
    await tick(house, freezer, 60)
    assert calls(events, LED) == [("turn_on", {"color_name": "purple"})]


async def test_a_relay_only_turns_on_and_off(house: HomeAssistant, freezer: Any) -> None:
    """HA drops the colour, brightness and effect a relay can't take."""
    assert await setup(house, devices(mail=raised("mail", "low", "porch")), config=CONFIG)
    events = capture(house, "call_service")
    await turn(house, "mail", "on")
    await turn(house, "mail", "off")
    await tick(house, freezer, 120)
    assert calls(events, RELAY) == [("turn_on", BLUE), ("turn_on", GREEN), ("turn_off", {})]
    relay = [(event.data["service"],
              {k: v for k, v in event.data["service_data"].items() if k != "entity_id"})
             for event in events
             if event.data["domain"] == "switch"
             and event.data["service_data"].get("entity_id") == [REAL_RELAY]]
    assert relay == [("turn_on", {}), ("turn_on", {}), ("turn_off", {})]


async def test_a_ready_made_alert_borrows_its_group(house: HomeAssistant) -> None:
    """offline (medium) is on at once: its plug has no reading."""
    washer = {"name": "Lavadora", "appliance": {
        **APPLIANCE, "alerts": {"offline": {"for": {"seconds": 0}, "lights": True}}}}
    events = capture(house, "call_service")
    assert await setup(house, {**devices(), "lavadora": washer}, config=CONFIG)
    assert calls(events, LED) == [("turn_on", ORANGE)]
    assert attributes(house, LED)["alerts"] == [
        "binary_sensor.pururu_lavadora_appliance_alert_offline"]


# --- someone else changing a borrowed light -------------------------------------------


async def test_a_change_by_someone_else_during_an_alert_is_put_back(house: HomeAssistant) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    await fake(house, REAL_LED, "on", {**BULB, "hs_color": [120.0, 100.0]})
    await house.async_block_till_done()
    assert calls(events, LED) == [("turn_on", ORANGE)]


def own_calls(events: list[Event]) -> list[Event]:
    return [event for event in events if event.data["domain"] == "light"
            and event.data["service_data"].get("entity_id") == LED]


async def test_the_managers_own_changes_are_not_put_back(house: HomeAssistant) -> None:
    """The real light reports what the manager asked, with the manager's context."""
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    events = capture(house, "call_service")
    await turn(house, "gate", "on")
    [call] = own_calls(events)
    house.states.async_set(REAL_LED, "on", {**BULB, "hs_color": [30.0, 100.0]},
                           context=call.context)
    await settle()
    await house.async_block_till_done()
    assert len(calls(events, LED)) == 1


async def test_a_late_report_of_an_earlier_call_is_still_the_managers(
        house: HomeAssistant, freezer: Any) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    events = capture(house, "call_service")
    await turn(house, "gate", "on")
    await tick(house, freezer, 15)
    first, _repeat = own_calls(events)
    house.states.async_set(REAL_LED, "on", {**BULB, "hs_color": [30.0, 100.0]},
                           context=first.context)
    await settle()
    await house.async_block_till_done()
    assert len(calls(events, LED)) == 2


@pytest.mark.parametrize("context", [
    pytest.param(Context(user_id="someone"), id="a person"),
    pytest.param(Context(parent_id="an automation's trigger"), id="an automation"),
])
async def test_a_change_during_resolved_hands_the_light_back_without_turning_it_off(
        house: HomeAssistant, freezer: Any, context: Context) -> None:
    """Whoever changed it took it back on purpose: the alert is over."""
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    await turn(house, "gate", "off")
    released = capture(house, "pururu_alert_lights_released")
    events = capture(house, "call_service")
    house.states.async_set(REAL_LED, "on", {**BULB, "hs_color": [240.0, 100.0]},
                           context=context)
    await settle()
    await house.async_block_till_done()
    assert [event.data for event in released] == [{"entity_id": LED}]
    assert "alert" not in attributes(house, LED)
    await tick(house, freezer, 120)
    assert calls(events, LED) == []


async def test_a_light_back_from_no_reading_during_resolved_shows_resolved_again(
        house: HomeAssistant, freezer: Any) -> None:
    """A bulb dropping off Zigbee isn't someone taking it back."""
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    await turn(house, "gate", "off")
    released = capture(house, "pururu_alert_lights_released")
    events = capture(house, "call_service")
    await fake(house, REAL_LED, "unavailable")
    await house.async_block_till_done()
    assert calls(events, LED) == []
    await fake(house, REAL_LED, "off", BULB)
    await house.async_block_till_done()
    assert calls(events, LED) == [("turn_on", GREEN)]
    assert released == []
    await tick(house, freezer, 120)
    assert calls(events, LED) == [("turn_on", GREEN), ("turn_off", {})]
    assert [event.data for event in released] == [{"entity_id": LED}]


async def test_a_light_gone_unavailable_is_left_until_it_comes_back(house: HomeAssistant) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    await fake(house, REAL_LED, "unavailable")
    await house.async_block_till_done()
    assert calls(events, LED) == []
    await fake(house, REAL_LED, "off", BULB)
    await house.async_block_till_done()
    assert calls(events, LED) == [("turn_on", ORANGE)]


async def test_a_free_light_is_left_alone(house: HomeAssistant) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    events = capture(house, "call_service")
    await fake(house, REAL_LED, "on", BULB)
    await house.async_block_till_done()
    assert calls(events, LED) == []


async def test_a_failing_call_is_a_warning_and_the_repeat_tries_again(
        house: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse(self: Any, **kwargs: Any) -> None:
        raise HomeAssistantError("Zigbee2MQTT refused it")

    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    monkeypatch.setattr(module("features.lights").Light, "async_turn_on", refuse)
    events = capture(house, "call_service")
    await turn(house, "gate", "on")
    assert ("The alert lights couldn't call light.turn_on on light.pururu_pool_light_led: "
            "Zigbee2MQTT refused it") in caplog.text
    await tick(house, freezer, 15)
    assert calls(events, LED) == [("turn_on", ORANGE)] * 2


async def test_a_slow_turn_off_never_lands_after_the_next_alerts_turn_on(
        house: HomeAssistant, freezer: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Commands reach a light in the order they were given, even when one is slow."""
    lights = module("features.lights")
    done: list[str] = []
    gate = asyncio.Event()
    turn_on = lights.Light.async_turn_on

    async def slow_off(self: Any, **kwargs: Any) -> None:
        await gate.wait()
        done.append("off")

    async def on(self: Any, **kwargs: Any) -> None:
        await turn_on(self, **kwargs)
        done.append("on")

    config = {"alerts": {"lights": {"groups": GROUPS,
                                    "medium": {"turn_on": {"color_name": "orange"}}}}}
    assert await setup(house, devices(gate=raised("gate", "medium")), config=config)
    await turn(house, "gate", "on")
    await turn(house, "gate", "off")
    monkeypatch.setattr(lights.Light, "async_turn_off", slow_off)
    monkeypatch.setattr(lights.Light, "async_turn_on", on)
    done.clear()
    await tick(house, freezer, 120)
    # Not turn(): it would wait for the turn_off held here
    await fake(house, REAL["gate"], "on")
    gate.set()
    await house.async_block_till_done()
    assert done == ["off", "on"]
    assert attributes(house, LED)["alert"] == "medium"


def gated_turn_on(monkeypatch: pytest.MonkeyPatch, gate: asyncio.Event, done: list[str]) -> None:
    """Hold every Light turn_on until `gate` is set; `done` records the ones that ran."""
    lights = module("features.lights")
    turn_on = lights.Light.async_turn_on

    async def slow_on(self: Any, **kwargs: Any) -> None:
        await gate.wait()
        await turn_on(self, **kwargs)
        done.append("on")

    monkeypatch.setattr(lights.Light, "async_turn_on", slow_on)


async def test_a_take_back_drops_a_command_still_waiting(
        house: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    """The green waiting behind a slow orange never lands on a light a person took back."""
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    gate = asyncio.Event()
    done: list[str] = []
    gated_turn_on(monkeypatch, gate, done)
    # Not turn(): it would wait for the turn_on held here
    await fake(house, REAL["gate"], "on")
    await fake(house, REAL["gate"], "off")
    house.states.async_set(REAL_LED, "on", {**BULB, "hs_color": [240.0, 100.0]},
                           context=Context(user_id="someone"))
    await settle()
    gate.set()
    await house.async_block_till_done()
    assert done == ["on"]
    assert "alert" not in attributes(house, LED)


async def test_a_dropped_turn_off_announces_no_release(
        house: HomeAssistant, freezer: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Of two releases whose turn_offs queued behind a slow command, only the last speaks."""
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    gate = asyncio.Event()
    gated_turn_on(monkeypatch, gate, [])
    released = capture(house, "pururu_alert_lights_released")
    await fake(house, REAL["gate"], "off")
    await tick(house, freezer, 120)
    await fake(house, REAL["gate"], "on")
    await fake(house, REAL["gate"], "off")
    await tick(house, freezer, 120)
    gate.set()
    await house.async_block_till_done()
    assert [event.data for event in released] == [{"entity_id": LED}]


async def test_an_integration_bug_turning_it_off_still_releases_the_light(
        house: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """An error that isn't Home Assistant's is logged, and the light is still said free."""
    async def crash(self: Any, **kwargs: Any) -> None:
        raise RuntimeError("the integration's bug")

    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    await turn(house, "gate", "off")
    monkeypatch.setattr(module("features.lights").Light, "async_turn_off", crash)
    released = capture(house, "pururu_alert_lights_released")
    await tick(house, freezer, 120)
    await house.async_block_till_done()
    assert [event.data for event in released] == [{"entity_id": LED}]
    assert ("The alert lights couldn't call light.turn_off on light.pururu_pool_light_led"
            in caplog.text)
    assert "the integration's bug" in caplog.text


# --- start, restart, reload -------------------------------------------------------------


async def test_a_restart_with_an_alert_on_shows_it(house: HomeAssistant) -> None:
    await fake(house, REAL["gate"], "on")
    events = capture(house, "call_service")
    await restart(house, devices(gate=raised("gate", "medium")),
                  (State(alert("gate"), "on"), {}),
                  (State(LED, "on"), {"alert": "medium"}), config=CONFIG)
    assert calls(events, LED) == [("turn_on", ORANGE)]


async def test_a_restart_during_resolved_hands_the_light_back(
        house: HomeAssistant, freezer: Any) -> None:
    released = capture(house, "pururu_alert_lights_released")
    events = capture(house, "call_service")
    await restart(house, devices(gate=raised("gate", "medium")),
                  (State(alert("gate"), "off"), {}),
                  (State(LED, "on"), {"alert": "resolved"}), config=CONFIG)
    assert calls(events, LED) == [("turn_on", GREEN)]
    await tick(house, freezer, 120)
    assert calls(events, LED) == [("turn_on", GREEN), ("turn_off", {})]
    assert [event.data for event in released] == [{"entity_id": LED}]


async def test_a_restart_after_the_alert_ended_hands_the_light_back(house: HomeAssistant) -> None:
    events = capture(house, "call_service")
    await restart(house, devices(gate=raised("gate", "medium")),
                  (State(alert("gate"), "off"), {}),
                  (State(LED, "on"), {"alert": "medium"}), config=CONFIG)
    assert calls(events, LED) == [("turn_on", GREEN)]


async def test_a_restart_with_nothing_borrowed_calls_nothing(house: HomeAssistant) -> None:
    events = capture(house, "call_service")
    await restart(house, devices(gate=raised("gate", "medium")),
                  (State(alert("gate"), "off"), {}), (State(LED, "off"), {}), config=CONFIG)
    assert calls(events, LED) == []


async def test_a_light_out_of_every_group_is_handed_back(
        house: HomeAssistant, freezer: Any) -> None:
    """The YAML dropped it from its group while an alert had it."""
    released = capture(house, "pururu_alert_lights_released")
    events = capture(house, "call_service")
    await restart(house, devices(mail=raised("mail", "low", "porch")),
                  (State(LED, "on"), {"alert": "high"}),
                  config={"alerts": {"lights": {"groups": {"porch": {"varanda": ["rele"]}}}}})
    assert calls(events, LED) == [("turn_on", GREEN)]
    await tick(house, freezer, 120)
    assert [event.data for event in released] == [{"entity_id": LED}]


async def test_a_reload_with_an_alert_on_neither_greens_nor_releases(house: HomeAssistant) -> None:
    config = devices(gate=raised("gate", "medium"))
    assert await setup(house, config, config=CONFIG)
    await turn(house, "gate", "on")
    released = capture(house, "pururu_alert_lights_released")
    events = capture(house, "call_service")
    await reload(house, config, config=CONFIG)
    await house.async_block_till_done()
    assert ("turn_on", GREEN) not in calls(events, LED)
    assert "turn_off" not in [service for service, _ in calls(events, LED)]
    assert released == []
    assert attributes(house, LED)["alert"] == "medium"


async def test_an_alert_without_a_reading_for_a_moment_keeps_the_light(
        house: HomeAssistant) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    house.states.async_set(alert("gate"), "unavailable")
    await settle()
    house.states.async_set(alert("gate"), "on")
    await settle()
    await house.async_block_till_done()
    assert calls(events, LED) == []
    assert attributes(house, LED)["alert"] == "medium"


async def test_a_light_not_created_is_left_out_of_its_group(
        house: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(house).async_get_or_create(
        "light", "template", "someone_else", suggested_object_id="pururu_pool_light_led")
    events = capture(house, "call_service")
    assert await setup(house, devices(mail=raised("mail", "low", "both")), config=CONFIG)
    await turn(house, "mail", "on")
    assert calls(events, RELAY) == [("turn_on", BLUE)]
    assert calls(events, LED) == []
    assert ("light.pururu_pool_light_led is not created: the alert lights group both "
            "goes without it") in caplog.text


async def test_a_disabled_light_is_left_out_quietly(
        house: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(house).async_get_or_create(
        "light", "pururu", "pururu_pool_light_led", suggested_object_id="pururu_pool_light_led",
        disabled_by=er.RegistryEntryDisabler.USER)
    events = capture(house, "call_service")
    assert await setup(house, devices(mail=raised("mail", "low", "both")), config=CONFIG)
    await turn(house, "mail", "on")
    assert calls(events, RELAY) == [("turn_on", BLUE)]
    assert calls(events, LED) == []
    assert "goes without it" not in caplog.text


# --- offline, disabled, late -------------------------------------------------------------


async def test_a_late_report_during_resolved_shows_resolved_again(house: HomeAssistant) -> None:
    """A change no person nor automation made (the bulb's own report, after the
    manager's context expired) isn't a hand-back."""
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    await turn(house, "gate", "off")
    released = capture(house, "pururu_alert_lights_released")
    events = capture(house, "call_service")
    await fake(house, REAL_LED, "on", {**BULB, "hs_color": [120.0, 100.0]})
    await house.async_block_till_done()
    assert calls(events, LED) == [("turn_on", GREEN)]
    assert released == []
    assert attributes(house, LED)["alert"] == "resolved"


async def test_an_offline_light_is_not_called(
        house: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    """No call every repeat while it can't take one: it's put back once it returns."""
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    await fake(house, REAL_LED, "unavailable")
    await tick(house, freezer, 30)
    assert calls(events, LED) == []
    assert f"Referenced entities {LED} are missing" not in caplog.text
    await fake(house, REAL_LED, "off", BULB)
    await house.async_block_till_done()
    assert calls(events, LED) == [("turn_on", ORANGE)]


async def test_resolved_ending_while_the_light_is_offline_turns_it_off_once_back(
        house: HomeAssistant, freezer: Any) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    await turn(house, "gate", "off")
    released = capture(house, "pururu_alert_lights_released")
    events = capture(house, "call_service")
    await fake(house, REAL_LED, "unavailable")
    await tick(house, freezer, 120)
    assert calls(events, LED) == []
    assert released == []
    await fake(house, REAL_LED, "on", BULB)
    await house.async_block_till_done()
    assert calls(events, LED) == [("turn_off", {})]
    assert [event.data for event in released] == [{"entity_id": LED}]


@pytest.mark.parametrize("overdue", [pytest.param(False, id="during for"),
                                     pytest.param(True, id="after for")])
async def test_a_person_taking_back_a_light_that_returns_keeps_it(
        house: HomeAssistant, freezer: Any, overdue: bool) -> None:
    """Back from offline by someone's hand during resolved, or after its for ended: theirs."""
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    await turn(house, "gate", "off")
    released = capture(house, "pururu_alert_lights_released")
    events = capture(house, "call_service")
    await fake(house, REAL_LED, "unavailable")
    if overdue:
        await tick(house, freezer, 120)
    house.states.async_set(REAL_LED, "on", {**BULB, "hs_color": [240.0, 100.0]},
                           context=Context(user_id="someone"))
    await settle()
    await house.async_block_till_done()
    assert calls(events, LED) == []
    assert [event.data for event in released] == [{"entity_id": LED}]
    await tick(house, freezer, 120)
    assert calls(events, LED) == []


async def test_a_restart_with_the_light_offline_still_hands_it_back(
        house: HomeAssistant, freezer: Any) -> None:
    """HA saves no attributes of an unavailable entity: what was shown is kept apart."""
    await fake(house, REAL_LED, "unavailable")
    released = capture(house, "pururu_alert_lights_released")
    events = capture(house, "call_service")
    await restart(house, devices(gate=raised("gate", "medium")),
                  (State(alert("gate"), "off"), {}),
                  (State(LED, "unavailable"), {"alert": "resolved"}), config=CONFIG)
    await fake(house, REAL_LED, "on", BULB)
    await house.async_block_till_done()
    assert calls(events, LED) == [("turn_on", GREEN)]
    await tick(house, freezer, 120)
    assert calls(events, LED) == [("turn_on", GREEN), ("turn_off", {})]
    assert [event.data for event in released] == [{"entity_id": LED}]


async def test_a_reload_with_the_light_offline_still_hands_it_back(
        house: HomeAssistant, freezer: Any) -> None:
    config = devices(gate=raised("gate", "medium"))
    assert await setup(house, config, config=CONFIG)
    await turn(house, "gate", "on")
    await turn(house, "gate", "off")
    await fake(house, REAL_LED, "unavailable")
    released = capture(house, "pururu_alert_lights_released")
    events = capture(house, "call_service")
    await reload(house, config, config=CONFIG)
    await fake(house, REAL_LED, "on", BULB)
    await house.async_block_till_done()
    assert calls(events, LED) == [("turn_on", GREEN)]
    await tick(house, freezer, 120)
    assert calls(events, LED)[-1] == ("turn_off", {})
    assert [event.data for event in released] == [{"entity_id": LED}]


async def test_disabling_an_alert_hands_its_light_back(house: HomeAssistant, freezer: Any) -> None:
    """Disabling the alert is a way to silence it."""
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    released = capture(house, "pururu_alert_lights_released")
    events = capture(house, "call_service")
    er.async_get(house).async_update_entity(
        alert("gate"), disabled_by=er.RegistryEntryDisabler.USER)
    await house.async_block_till_done()
    # The reloaded light may show its state after the manager started: green is sent again
    sent = calls(events, LED)
    assert sent
    assert all(call == ("turn_on", GREEN) for call in sent)
    await tick(house, freezer, 120)
    assert calls(events, LED)[-1] == ("turn_off", {})
    assert [event.data for event in released] == [{"entity_id": LED}]


async def test_disabling_a_borrowed_light_leaves_it_alone(
        house: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture) -> None:
    assert await setup(house, devices(gate=raised("gate", "medium")), config=CONFIG)
    await turn(house, "gate", "on")
    events = capture(house, "call_service")
    er.async_get(house).async_update_entity(LED, disabled_by=er.RegistryEntryDisabler.USER)
    await house.async_block_till_done()
    await tick(house, freezer, 30)
    assert calls(events, LED) == []
    assert "while it is disabled" not in caplog.text


# --- the docs ----------------------------------------------------------------------------

PAGE = Path(__file__).resolve().parents[1] / "docs/concepts/alert-lights.mdx"


def yaml_blocks() -> list[Any]:
    return [yaml.safe_load(block)
            for block in re.findall(r"```yaml[^\n]*\n(.*?)```", PAGE.read_text(), re.DOTALL)]


async def test_the_pages_example_is_valid(ha: HomeAssistant) -> None:
    example = yaml_blocks()[0]["pururu"]
    assert await setup(ha, example["devices"], config=example["config"])


def test_the_documented_defaults_are_the_defaults(ha: HomeAssistant) -> None:
    [defaults] = [block["pururu"]["config"]["alerts"]["lights"] for block in yaml_blocks()
                  if "pururu" in block and "high" in block["pururu"]["config"]["alerts"]["lights"]]
    schema = module("alert_lights").SCHEMA
    assert schema(defaults) == schema({})
