"""The rules over the whole house (schema.CHECKS): each refuses with its words and says where."""

from typing import Any

from homeassistant.core import HomeAssistant
import pytest
import voluptuous as vol

from helpers import DOMAIN, module

APPLIANCE: dict[str, Any] = {
    "power": "sensor.washer_power",
    "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}
PUMP = {"pump": {"entity": "switch.pool_pump", "name": "Bomba"}}


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
        {"devices": {"pool": {"name": "Pool", "switches": PUMP, "programs": {
            "clean": {"name": "Clean", "sequence": [{"turn_on": "switch_nope"}]}}}}},
        ["devices", "pool", "programs", "clean"],
        "programs: switch_nope is not an entity key of another feature of this device",
        id="a program's step"),
    pytest.param(
        {"devices": {"pool": {"name": "Pool", "switches": PUMP, "lights": {
            "pump": {"entity": "switch.pool_pump", "name": "Bomba"}}}}},
        ["devices", "pool", "switches"],
        "switches: switch.pool_pump is already in lights",
        id="a real entity twice"),
    pytest.param(
        {"devices": {"pool": {"name": "Pool", "switches": {"switch_pump": PUMP["pump"]}},
                     "pool_switch": {"name": "Pool", "switches": {"pump": {"entity": "switch.other",
                                                                          "name": "Other"}}}}},
        ["devices", "pool_switch"],
        "device pool_switch: pururu_pool_switch_switch_pump is already an entity of device pool",
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
        {"devices": {"pool": {"name": "Pool", "switches": PUMP}},
         "config": {"alerts": {"lights": {"groups": {"porch": {"garagem": ["x"]}}}}}},
        ["config", "alerts", "lights", "groups", "porch"],
        "config.alerts.lights.groups: porch: device garagem is not in devices",
        id="a light group"),
])
def test_a_check_says_where(ha: HomeAssistant, house: dict[str, Any], path: list[str], message: str) -> None:
    with pytest.raises(vol.Invalid) as refused:
        module("setup.schema").CONFIG_SCHEMA({DOMAIN: house})
    assert refused.value.msg == message
    assert refused.value.path == [DOMAIN, *path]


def test_every_refusal_is_told_at_once(ha: HomeAssistant) -> None:
    """Two devices each refused by a check: both errors come back, not only the first."""
    bad = {"x": {"name": "X", "when": "appliance_nothing", "is": "on"}}
    house = {"devices": {"washer": washer(alerts=bad), "dryer": washer(alerts=bad)}}
    with pytest.raises(vol.MultipleInvalid) as refused:
        module("setup.schema").CONFIG_SCHEMA({DOMAIN: house})
    assert sorted(error.path for error in refused.value.errors) == [
        [DOMAIN, "devices", "dryer", "alerts"], [DOMAIN, "devices", "washer", "alerts"]]
