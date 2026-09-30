"""The rules over the whole house (schema.CHECKS): each refuses with its words and says where."""

from typing import Any

from homeassistant.core import HomeAssistant
import pytest
import voluptuous as vol

from helpers import DOMAIN, module

APPLIANCE: dict[str, Any] = {
    "power": "sensor.washer_power",
    "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}
SPRINKLER = {"sprinkler": {"entity": "switch.greenhouse_sprinkler", "name": "Irrigador"}}


def washer(**blocks: Any) -> dict[str, Any]:
    return {"name": "Washer", "appliance": APPLIANCE, **blocks}


@pytest.mark.parametrize(("house", "path", "message"), [
    pytest.param(
        {"devices": {"washer": washer(alerts={"x": {"name": "X", "when": "appliance_nothing", "is": "on"}})}},
        ["devices", "washer", "alerts"],
        "alerts: appliance_nothing is not an entity key of another feature of this device",
        id="an alert's when"),
    pytest.param(
        {"devices": {"washer": washer(alerts={"x": {"name": "X", "when": "appliance_alert_offline",
                                                    "is": "on"}},
                                      appliance={**APPLIANCE, "alerts": {"offline": None}})}},
        ["devices", "washer", "alerts"],
        "alerts: appliance_alert_offline is an alert: an alert can't watch another",
        id="an alert watching an alert"),
    pytest.param(
        {"devices": {"washer": washer(reactions={"it": {"name": "X", "when": "appliance_nothing",
                                                        "to": "on"}})}},
        ["devices", "washer", "reactions", "it"],
        "reactions: it: appliance_nothing is not an entity key of this device",
        id="a reaction's when"),
    pytest.param(
        {"devices": {"washer": washer(reactions={"it": {"name": "X", "device": "dryer",
                                                        "when": "appliance_running", "to": "on"}})}},
        ["devices", "washer", "reactions", "it"],
        "device washer: reactions: it: device dryer is not in devices",
        id="a reaction's device"),
    pytest.param(
        {"devices": {"greenhouse": {"name": "Greenhouse", "switches": SPRINKLER, "programs": {
            "clean": {"name": "Clean", "sequence": [{"turn_on": "switch_nope"}]}}}}},
        ["devices", "greenhouse", "programs", "clean"],
        "programs: switch_nope is not an entity key of another feature of this device",
        id="a program's step"),
    pytest.param(
        {"devices": {"greenhouse": {"name": "Greenhouse", "switches": SPRINKLER, "lights": {
            "sprinkler": {"entity": "switch.greenhouse_sprinkler", "name": "Irrigador"}}}}},
        ["devices", "greenhouse", "switches"],
        "switches: switch.greenhouse_sprinkler is already in lights",
        id="a real entity twice"),
    pytest.param(
        {"devices": {"greenhouse": {"name": "Greenhouse", "switches": {"switch_sprinkler": SPRINKLER["sprinkler"]}},
                     "greenhouse_switch": {"name": "Greenhouse", "switches": {"sprinkler": {"entity": "switch.other",
                                                                          "name": "Other"}}}}},
        ["devices", "greenhouse_switch"],
        "device greenhouse_switch: pururu_greenhouse_switch_switch_sprinkler is already an entity of device greenhouse",
        id="two devices' IDs"),
    pytest.param(
        {"devices": {"washer": washer(alerts={"x": {"name": "X", "when": "appliance_running", "is": "on",
                                                    "lights": "porch"}})}},
        ["devices", "washer", "alerts", "x"],
        "device washer: alerts: x: porch is not a group of config.alerts.lights.groups",
        id="an alert's missing group"),
    pytest.param(
        {"devices": {"washer": washer(appliance={**APPLIANCE, "alerts": {"offline": {"lights": True}}})}},
        ["devices", "washer", "appliance", "alerts", "offline"],
        "device washer: appliance: alerts: offline: there is no default group in config.alerts.lights.groups",
        id="a ready-made alert's missing default group"),
    pytest.param(
        {"devices": {"greenhouse": {"name": "Greenhouse", "switches": SPRINKLER}},
         "config": {"alerts": {"lights": {"groups": {"porch": {"garagem": ["x"]}}}}}},
        ["config", "alerts", "lights", "groups", "porch"],
        "config.alerts.lights.groups: porch: device garagem is not in devices",
        id="a light group"),
])
def test_a_check_says_where(ha: HomeAssistant, house: dict[str, Any], path: list[str], message: str) -> None:
    schema = module("setup.schema").CONFIG_SCHEMA
    with pytest.raises(vol.Invalid) as refused:
        schema({DOMAIN: house})
    assert refused.value.msg == message
    assert refused.value.path == [DOMAIN, *path]


def test_every_refusal_is_told_at_once(ha: HomeAssistant) -> None:
    """Two devices each refused by a check: both errors come back, not only the first."""
    bad = {"x": {"name": "X", "when": "appliance_nothing", "is": "on"}}
    house = {"devices": {"washer": washer(alerts=bad), "dryer": washer(alerts=bad)}}
    schema = module("setup.schema").CONFIG_SCHEMA
    with pytest.raises(vol.MultipleInvalid) as refused:
        schema({DOMAIN: house})
    assert sorted(error.path for error in refused.value.errors) == [
        [DOMAIN, "devices", "dryer", "alerts"], [DOMAIN, "devices", "washer", "alerts"]]


@pytest.mark.parametrize(("when", "message"), [
    pytest.param("alert_other",
                 "alerts: alert_other is not an entity key of another feature of this device",
                 id="its own block's alert (checks.references)"),
    pytest.param("appliance_alert_offline",
                 "alerts: appliance_alert_offline is an alert: an alert can't watch another",
                 id="a ready-made alert (alerts.check)"),
])
def test_an_alert_watching_an_alert_is_refused_once(
        ha: HomeAssistant, when: str, message: str) -> None:
    """Each check refuses what the other doesn't: one refusal per reference, never two."""
    other = {"name": "Other", "when": "appliance_running", "is": "on"}
    house = {"devices": {"washer": washer(
        alerts={"x": {"name": "X", "when": when, "is": "on"}, "other": other},
        appliance={**APPLIANCE, "alerts": {"offline": None}})}}
    schema = module("setup.schema").CONFIG_SCHEMA
    with pytest.raises(vol.MultipleInvalid) as refused:
        schema({DOMAIN: house})
    assert [(error.msg, error.path) for error in refused.value.errors] == [
        (message, [DOMAIN, "devices", "washer", "alerts"])]
