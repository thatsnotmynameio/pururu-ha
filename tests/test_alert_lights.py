"""Alert lights: a made-up house's alerts borrowing the pool's LED and the porch's relay."""

from datetime import timedelta
from typing import Any

from homeassistant.core import Event, HomeAssistant
import pytest

from helpers import fake, module, setup

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
