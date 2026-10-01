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


def alert(when: str, **more: Any) -> dict[str, Any]:
    return {"x": {"name": "X", "when": when, "state": "on", **more}}


def reaction(when: str, **more: Any) -> dict[str, Any]:
    return {"it": {"name": "X", "when": when, "to": "on", **more}}


def greenhouse(**blocks: Any) -> dict[str, Any]:
    return {"name": "Greenhouse", "switches": SPRINKLER, **blocks}


def clean(*sequence: Any) -> dict[str, Any]:
    return {"executable": {"clean": {"name": "Clean", "sequence": list(sequence)}}}


WHEN = ["devices", "washer", "alerts", "x", "when"]
REACTION = ["devices", "washer", "reactions", "it"]
STEP = ["devices", "greenhouse", "programs", "executable", "clean", "sequence", 0, "turn_on"]
TETO = {"teto": {"entity": "light.dummy_teto", "name": "Teto"}}
LIBRARY = {"name": "Library", "lights": TETO}
GROUP = ["config", "alerts", "lights", "groups", "porch", 0]


def group(*members: str) -> dict[str, Any]:
    return {"alerts": {"lights": {"groups": {"porch": list(members)}}}}


@pytest.mark.parametrize(("house", "path", "message"), [
    pytest.param(
        {"devices": {"washer": washer(alerts=alert("appliance.nothing"))}}, WHEN,
        "alerts: appliance.nothing is not an entity of this device",
        id="an alert's when"),
    pytest.param(
        {"devices": {"washer": washer(alerts=alert("appliance.alerts.offline"),
                                      appliance={**APPLIANCE, "alerts": {"offline": None}})}}, WHEN,
        "alerts: appliance.alerts.offline is an alert: an alert can't watch another",
        id="an alert watching an alert"),
    pytest.param(
        {"devices": {"washer": washer(alerts=alert("appliance_running"))}}, WHEN,
        "appliance_running is not a path: write it from its block, <block>.<key>",
        id="an alert's when as before 0.2.2"),
    pytest.param(
        {"devices": {"washer": washer(alerts=alert("device.washer.appliance.running_program"))}}, WHEN,
        "alerts: device.washer.appliance.running_program is this device's: write appliance.running_program",
        id="an alert naming its own device"),
    pytest.param(
        {"devices": {"washer": washer(alerts=alert("device.library.lights.teto")), "library": LIBRARY}}, WHEN,
        "alerts: device.library.lights.teto is not of this device",
        id="an alert on another device"),
    pytest.param(
        {"devices": {"washer": washer(alerts=alert("homeassistant.sensor.washer_power"))}}, WHEN,
        "alerts: homeassistant.sensor.washer_power is not of this device",
        id="an alert on Home Assistant's"),
    pytest.param(
        {"devices": {"washer": washer(alerts=alert("clothes_washer.appliance_running"))}}, WHEN,
        "alerts: clothes_washer.appliance_running: clothes_washer is not a block of this device",
        id="another device as before 0.2.2"),
    pytest.param(
        {"devices": {"washer": washer(alerts=alert("name.x"))}}, WHEN,
        "alerts: name.x: name is not a block of this device",
        id="a device's name"),
    pytest.param(
        {"devices": {"washer": washer(alerts=alert("door.open"))}}, WHEN,
        "alerts: door.open: door is not a block of this device",
        id="a block the device lacks"),
    pytest.param(
        {"devices": {"washer": washer(alerts=alert("appliance.running_program.above"))}}, WHEN,
        "alerts: appliance.running_program.above is not an entity of this device",
        id="a setting"),
    pytest.param(
        {"devices": {"washer": washer(alerts=alert("appliance.running_program.statistics"))}}, WHEN,
        "alerts: appliance.running_program.statistics is not an entity of this device",
        id="a container"),
    pytest.param(
        {"devices": {"washer": washer(alerts=alert("appliance.programs.detected"))}}, WHEN,
        "alerts: appliance.programs.detected is not an entity of this device",
        id="a structure word"),
    pytest.param(
        {"devices": {"washer": washer(alerts=alert("switches.sprinkler.entity"), switches=SPRINKLER)}}, WHEN,
        "alerts: switches.sprinkler.entity is not an entity of this device",
        id="a configured key's setting"),
    pytest.param(
        {"devices": {"washer": washer(alerts=alert("appliance.running_program", lights="groups.default"))}},
        [*WHEN[:-1], "lights"], "lights is its group's key alone: default",
        id="an alert's lights as a path"),
    pytest.param(
        {"devices": {"washer": washer(reactions=reaction("appliance.nothing"))}}, [*REACTION, "when"],
        "reactions: it: appliance.nothing is not an entity of this device",
        id="a reaction's when"),
    pytest.param(
        {"devices": {"washer": washer(reactions=reaction("device.dryer.appliance.running_program"))}},
        [*REACTION, "when"],
        "reactions: it: device.dryer.appliance.running_program: device dryer is not in devices",
        id="a reaction's other device"),
    pytest.param(
        {"devices": {"washer": washer(reactions=reaction("device.library.lights.nothing")), "library": LIBRARY}},
        [*REACTION, "when"],
        "reactions: it: device.library.lights.nothing is not an entity of device library",
        id="a reaction's other device's path"),
    pytest.param(
        {"devices": {"washer": washer(reactions=reaction("dryer.appliance_running"))}}, [*REACTION, "when"],
        "reactions: it: dryer.appliance_running: dryer is not a block of this device",
        id="a reaction's other device as before 0.2.2"),
    pytest.param(
        {"devices": {"washer": washer(reactions=reaction("homeassistant.binary_sensor.door"))}}, [*REACTION, "when"],
        "reactions: it: homeassistant.binary_sensor.door is Home Assistant's: watch it with entity: "
        "binary_sensor.door",
        id="a reaction on Home Assistant's, until its when takes it"),
    pytest.param(
        {"devices": {"washer": washer(reactions=reaction("device.washer.appliance.running_program"))}},
        [*REACTION, "when"],
        "reactions: it: device.washer.appliance.running_program is this device's: write appliance.running_program",
        id="a reaction naming its own device"),
    pytest.param(
        {"devices": {"washer": washer(reactions={**reaction("reactions.other"),
                                                 "other": {"name": "Other", "at": "07:00"}})}},
        [*REACTION, "when"],
        "reactions: it: reactions.other is a reaction: watch reactions.other.triggered_total",
        id="a reaction on a reaction"),
    pytest.param(
        {"devices": {"washer": washer(reactions=reaction("reactions.it.triggered_total"))}}, [*REACTION, "when"],
        "reactions: it: reactions.it.triggered_total is its own statistic",
        id="a reaction on its own statistic"),
    pytest.param(
        {"devices": {"washer": washer(reactions=reaction("appliance.running_program", then="regar"))}},
        [*REACTION, "then"],
        "reactions: it: regar is not an executable program of this device",
        id="a reaction's then"),
    pytest.param(
        {"devices": {"washer": washer(reactions=reaction("appliance.running_program",
                                                         then="programs.executable.blink"))}},
        [*REACTION, "then"], "then is its program's key alone: blink",
        id="a reaction's then as a path"),
    pytest.param(
        {"devices": {"greenhouse": greenhouse(programs=clean({"turn_on": "switches.nope"}))}}, STEP,
        "programs: switches.nope is not an entity of this device",
        id="a program's step"),
    pytest.param(
        {"devices": {"greenhouse": greenhouse(programs=clean({"turn_on": "appliance.power"}), appliance=APPLIANCE)}},
        STEP, "programs: appliance.power does not take turn_on",
        id="a program's step its target doesn't take"),
    pytest.param(
        {"devices": {"greenhouse": greenhouse(programs=clean({"turn_on": "device.library.lights.teto"})),
                     "library": LIBRARY}},
        STEP, "programs: device.library.lights.teto is not of this device",
        id="a program's step on another device"),
    pytest.param(
        {"devices": {"greenhouse": greenhouse(programs=clean({"turn_on": "device.greenhouse.switches.sprinkler"}))}},
        STEP, "programs: device.greenhouse.switches.sprinkler is this device's: write switches.sprinkler",
        id="a program's step naming its own device"),
    pytest.param(
        {"devices": {"greenhouse": {"name": "Greenhouse", "switches": SPRINKLER, "buttons": {
            "clean": {"entity": "sensor.remote_action", "state": "1_single", "name": "Clean",
                      "program": "regar"}}}}},
        ["devices", "greenhouse", "buttons", "clean", "program"],
        "buttons: clean: regar is not an executable program of this device",
        id="a button's program"),
    pytest.param(
        {"devices": {"greenhouse": {"name": "Greenhouse", "switches": SPRINKLER, "buttons": {
            "clean": {"entity": "sensor.remote_action", "state": "1_single", "name": "Clean",
                      "program": "programs.executable.clean"}}}}},
        ["devices", "greenhouse", "buttons", "clean", "program"], "program is its program's key alone: clean",
        id="a button's program as a path"),
    pytest.param(
        {"devices": {"greenhouse": {**greenhouse(), "area": "areas.despensa"}}},
        ["devices", "greenhouse", "area"], "area is its area's key alone: despensa",
        id="a device's area as a path"),
    pytest.param(
        {"devices": {"greenhouse": greenhouse()}, "areas": {"despensa": {"name": "Despensa", "floor": "floors.terreo"}}},
        ["areas", "despensa", "floor"], "floor is its floor's key alone: terreo",
        id="an area's floor as a path"),
    pytest.param(
        {"devices": {"greenhouse": {"name": "Greenhouse", "buttons": {
            "clean": {"entity": "sensor.remote_action", "state": "1_single", "name": "Clean"},
            "wash": {"entity": "sensor.remote_action", "state": "1_single", "name": "Wash"}}}}},
        ["devices", "greenhouse", "buttons", "wash"],
        "buttons: wash: sensor.remote_action at 1_single is already button clean",
        id="two buttons on one value"),
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
        {"devices": {"washer": washer(appliance={**APPLIANCE, "running_program": {
            **APPLIANCE["running_program"],
            "phases": {"resfriar": {"name": "Resfriar", "above": 40},
                       "resfriar_cycles_today": {"name": "Hoje", "above": 300}}}})}},
        ["devices", "washer"],
        "device washer: pururu_washer_appliance_phase_resfriar_cycles_today would be two entities",
        id="two entities of one device"),
    pytest.param(
        {"devices": {"washer": washer(alerts=alert("appliance.running_program", lights="porch"))}},
        ["devices", "washer", "alerts", "x"],
        "device washer: alerts: x: porch is not a group of config.alerts.lights.groups",
        id="an alert's missing group"),
    pytest.param(
        {"devices": {"washer": washer(appliance={**APPLIANCE, "alerts": {"offline": {"lights": "default"}}})}},
        ["devices", "washer", "appliance", "alerts", "offline"],
        "device washer: appliance: alerts: offline: there is no default group in config.alerts.lights.groups",
        id="a ready-made alert's missing default group"),
    pytest.param(
        {"devices": {"greenhouse": greenhouse()}, "config": group("device.garagem.lights.x")}, GROUP,
        "config.alerts.lights.groups: porch: device.garagem.lights.x: device garagem is not in devices",
        id="a light group"),
    pytest.param(
        {"devices": {"garagem": {"name": "Garagem", "lights": {"x": {"entity": "light.dummy_x", "name": "X"}}}},
         "config": group("device.garagem.lights.x", "device.garagem.lights.y")}, [*GROUP[:-1], 1],
        "config.alerts.lights.groups: porch: device.garagem.lights.y is not a light",
        id="a light group's second member"),
    pytest.param(
        {"devices": {"greenhouse": greenhouse()}, "config": group("device.greenhouse.switches.sprinkler")}, GROUP,
        "config.alerts.lights.groups: porch: device.greenhouse.switches.sprinkler is not a light",
        id="a light group's member that isn't a light"),
    pytest.param(
        {"devices": {"library": LIBRARY}, "config": group("lights.teto")}, GROUP,
        "lights.teto needs its device: device.<device>.lights.<key>",
        id="a light group's member without its device"),
    pytest.param(
        {"devices": {"library": LIBRARY}, "config": group("library.light_teto")}, GROUP,
        "library.light_teto needs its device: device.<device>.lights.<key>",
        id="a light group's member as before 0.2.2"),
    pytest.param(
        {"devices": {"library": LIBRARY}, "config": group("homeassistant.light.teto")}, GROUP,
        "homeassistant.light.teto needs its device: device.<device>.lights.<key>",
        id="a light group's member of Home Assistant's"),
])
def test_a_check_says_where(ha: HomeAssistant, house: dict[str, Any], path: list[str], message: str) -> None:
    schema = module("setup.schema").CONFIG_SCHEMA
    with pytest.raises(vol.Invalid) as refused:
        schema({DOMAIN: house})
    assert refused.value.msg == message
    assert refused.value.path == [DOMAIN, *path]


def test_every_refusal_is_told_at_once(ha: HomeAssistant) -> None:
    """Two devices each refused by a check: both errors come back, not only the first."""
    bad = alert("appliance.nothing")
    house = {"devices": {"washer": washer(alerts=bad), "dryer": washer(alerts=bad)}}
    schema = module("setup.schema").CONFIG_SCHEMA
    with pytest.raises(vol.MultipleInvalid) as refused:
        schema({DOMAIN: house})
    assert sorted(error.path for error in refused.value.errors) == [
        [DOMAIN, "devices", "dryer", "alerts", "x", "when"], [DOMAIN, *WHEN]]


@pytest.mark.parametrize(("when", "message"), [
    pytest.param("alerts.other",
                 "alerts: alerts.other is not another block's entity",
                 id="its own block's alert (checks.references)"),
    pytest.param("appliance.alerts.offline",
                 "alerts: appliance.alerts.offline is an alert: an alert can't watch another",
                 id="a ready-made alert (alerts.check)"),
])
def test_an_alert_watching_an_alert_is_refused_once(
        ha: HomeAssistant, when: str, message: str) -> None:
    """Each check refuses what the other doesn't: one refusal per reference, never two."""
    other = {"name": "Other", "when": "appliance.running_program", "state": "on"}
    house = {"devices": {"washer": washer(
        alerts={"x": {"name": "X", "when": when, "state": "on"}, "other": other},
        appliance={**APPLIANCE, "alerts": {"offline": None}})}}
    schema = module("setup.schema").CONFIG_SCHEMA
    with pytest.raises(vol.MultipleInvalid) as refused:
        schema({DOMAIN: house})
    assert [(error.msg, error.path) for error in refused.value.errors] == [
        (message, [DOMAIN, *WHEN])]
