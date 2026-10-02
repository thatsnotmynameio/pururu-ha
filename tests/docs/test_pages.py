"""The pages that state what the code does: each says what the code holds."""

from pathlib import Path
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
import yaml

from helpers import capture, fake, module, setup, tick

PROJECT = Path(__file__).resolve().parents[2]
CODE = "custom_components/pururu"


def section(page: Path, heading: str) -> str:
    """The text of a page's `## heading` section, up to the next one."""
    found = re.search(rf"## {heading}\n(.*?)\n## ", page.read_text(encoding="utf-8"), re.DOTALL)
    assert found is not None, f"no {heading} section"
    return found[1]


# --- docs/develop ------------------------------------------------------------------------

BLOCK = re.compile(r'```python title="([\w/]+\.py)"\n(.*?)```', re.DOTALL)
RELATIVE = re.compile(r"^from (\.+)([\w.]*) import ", re.MULTILINE)


def test_the_develop_docs_examples_import_what_exists() -> None:
    """A relative import in a titled example resolves to a module of the package, or to another example."""
    pages = sorted((PROJECT / "docs" / "develop").glob("*.mdx"))
    blocks = [match.groups() for page in pages for match in BLOCK.finditer(page.read_text())]
    examples = {title.removesuffix(".py").replace("/", ".") for title, _ in blocks}
    for title, code in blocks:
        package = title.removesuffix(".py").split("/")[:-1]
        for dots, name in RELATIVE.findall(code):
            base = package[:len(package) - (len(dots) - 1)]
            target = ".".join([*base, *name.split(".")]) if name else ".".join(base)
            path = PROJECT / CODE / target.replace(".", "/")
            assert (target in examples or path.with_suffix(".py").exists()
                    or (path / "__init__.py").exists()), f"{title}: from {dots}{name}"


# --- docs/concepts/alerts.mdx ------------------------------------------------------------

ALERTS_PAGE = PROJECT / "docs/concepts/alerts.mdx"


def test_the_documented_include_is_the_one_pururu_asks_for(ha: HomeAssistant) -> None:
    block = re.search(r"```yaml[^\n]*\n(alert2:\n.*?)```", ALERTS_PAGE.read_text(), re.DOTALL)
    assert block is not None, "no alert2: block on the alerts page"
    assert f"  {module('outputs.alert2_alerts').INCLUDE}\n" in block[1]
    assert "generator" not in block[1]


# --- docs/concepts/alert-lights.mdx ------------------------------------------------------

ALERT_LIGHTS_PAGE = PROJECT / "docs/concepts/alert-lights.mdx"


def yaml_blocks() -> list[Any]:
    return [yaml.safe_load(block)
            for block in re.findall(r"```yaml[^\n]*\n(.*?)```", ALERT_LIGHTS_PAGE.read_text(),
                                    re.DOTALL)]


async def test_the_pages_example_is_valid(ha: HomeAssistant) -> None:
    example = yaml_blocks()[0]["pururu"]
    assert await setup(ha, example["devices"], config=example["config"])


def test_the_documented_defaults_are_the_defaults(ha: HomeAssistant) -> None:
    [defaults] = [block["pururu"]["config"]["alerts"]["lights"] for block in yaml_blocks()
                  if "pururu" in block and "high" in block["pururu"]["config"]["alerts"]["lights"]]
    schema = module("outputs.alert_lights").SCHEMA
    assert schema(defaults) == schema({})


# --- docs/concepts/notifications.mdx -----------------------------------------------------

NOTIFICATIONS_PAGE = PROJECT / "docs/concepts/notifications.mdx"


def test_the_page_lists_every_ready_made_notification(ha: HomeAssistant) -> None:
    listed = section(NOTIFICATIONS_PAGE, "Ready-made notifications")
    for name, feature in module("features").FEATURES.items():
        for notification in module("core.feature").happenings_of(feature):
            assert f"`{name}: notifications: {notification}`" in listed, notification


# --- docs/features/door.mdx --------------------------------------------------------------

DOOR_PAGE = PROJECT / "docs/features/door.mdx"


def test_the_door_page_lists_every_ready_made_alert(ha: HomeAssistant) -> None:
    """The window page points to the door's: one list for both."""
    listed = section(DOOR_PAGE, "Ready-made alerts")
    features = module("features").FEATURES
    for name in module("core.feature").presets_of(features["door"]):
        assert f"`{name}`" in listed, name
    assert set(module("core.feature").presets_of(features["window"])) == set(
        module("core.feature").presets_of(features["door"]))


# --- docs/features/appliance.mdx ---------------------------------------------------------

APPLIANCE_PAGE = PROJECT / "docs/features/appliance.mdx"


def test_the_appliance_page_lists_every_ready_made_alert(ha: HomeAssistant) -> None:
    listed = section(APPLIANCE_PAGE, "Ready-made alerts")
    for name in module("core.feature").presets_of(module("features").FEATURES["appliance"]):
        assert f"`{name}`" in listed, name


# The events page's washer: its events name entities by path, its automation reads states with brackets
EVENT_TYPES = ("pururu_state_changed", "pururu_reading")
W = {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}
KWH = {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}
EVENTS_PAGE = PROJECT / "docs/concepts/events.mdx"
WASHER_END = "sensor.pururu_clothes_washer_appliance_last_cycle_end"


def documented(containing: str) -> dict[str, Any]:
    """The page's YAML block holding `containing`, as configuration.yaml reads it."""
    blocks = re.findall(r"```yaml[^\n]*\n(.*?)```", EVENTS_PAGE.read_text(encoding="utf-8"), re.DOTALL)
    [block] = [block for block in blocks if containing in block]
    return yaml.safe_load(block)


@pytest.fixture
async def clothes_washer(ha: HomeAssistant, freezer: Any) -> HomeAssistant:
    """The page's washer, idle long enough to count as not running."""
    block = documented("clothes_washer:")["pururu"]
    assert await setup(ha, block["devices"], events=block["config"]["events"])
    await fake(ha, "sensor.washer_plug_energy", "100.0", KWH)
    await fake(ha, "sensor.washer_plug_power", "1.4", W)
    await tick(ha, freezer, 125)
    return ha


async def washer_cycle(hass: HomeAssistant, freezer: Any) -> None:
    """One cycle of the page's washer, 0.42 kWh."""
    await fake(hass, "sensor.washer_plug_power", "120", W)
    await tick(hass, freezer, 65)
    await tick(hass, freezer, 30 * 60)
    await fake(hass, "sensor.washer_plug_energy", "100.42", KWH)
    await fake(hass, "sensor.washer_plug_power", "1.4", W)
    await tick(hass, freezer, 125)


async def test_a_cycle_end_is_named_by_its_path(clothes_washer: HomeAssistant, freezer: Any) -> None:
    """AE7: the event names the entity as another device's YAML writes it, and the sensor shows both forms."""
    captured = capture(clothes_washer, *EVENT_TYPES)
    await washer_cycle(clothes_washer, freezer)
    [event] = [event for event in captured if event.data["entity_id"] == WASHER_END]
    assert event.data["event_name"] == "device.clothes_washer.appliance.running_program.last_cycle_end"
    assert event.data["key"] == "appliance.running_program.last_cycle_end"
    assert event.data["states"]["appliance.running_program.last_cycle_end"] == event.data["new"]
    assert "reference" not in event.data["attributes"]
    assert clothes_washer.states.get(WASHER_END).attributes["reference"] == {
        "inside": "appliance.running_program.last_cycle_end",
        "outside": "device.clothes_washer.appliance.running_program.last_cycle_end",
    }


async def test_the_documented_automation_reads_states_with_brackets(
        clothes_washer: HomeAssistant, freezer: Any) -> None:
    """docs/concepts/events.mdx: matched on event_name, a value of states read by its whole path."""
    assert await async_setup_component(clothes_washer, "persistent_notification", {})
    assert await async_setup_component(clothes_washer, "automation", documented("Washer done"))
    calls = capture(clothes_washer, "call_service")
    await washer_cycle(clothes_washer, freezer)
    await clothes_washer.async_block_till_done()
    [call] = [event.data for event in calls if event.data["domain"] == "persistent_notification"]
    assert call["service_data"]["message"] == "Done: 0.42 kWh"


# --- docs/concepts/goals.mdx -------------------------------------------------------------

GOALS_PAGE = PROJECT / "docs/concepts/goals.mdx"
TROUBLESHOOTING_PAGE = PROJECT / "docs/reference/troubleshooting.mdx"
POOL_RUNTIME_TOTAL = "sensor.pururu_pool_appliance_runtime_total"
# A goal's lines pururu logs: a whole line, as the code writes it
GOAL_LINE = re.compile(r"(?:[a-z_]+\.pururu_\w+_goal_\w+ follows [a-z_]+\.\w+, which is not created"
                       r"|\w+: goals: \w+: [\w.]+ doesn't accumulate \(state class \w+\)); not creating it")


def goals_example() -> dict[str, Any]:
    """The goals page's pururu: block."""
    [block] = re.findall(r"```yaml[^\n]*\n(.*?)```", GOALS_PAGE.read_text(encoding="utf-8"), re.DOTALL)
    return yaml.safe_load(block)["pururu"]


def doesnt_accumulate(hass: HomeAssistant, entity_id: str) -> None:
    """`entity_id` registered as a measurement, which goes up and down."""
    domain, object_id = entity_id.split(".")
    er.async_get(hass).async_get_or_create(
        domain, "plug", object_id, suggested_object_id=object_id,
        capabilities={"state_class": "measurement"})


def disabled(hass: HomeAssistant, entity_id: str) -> None:
    """pururu's `entity_id` disabled in the registry before pururu sets up."""
    domain, object_id = entity_id.split(".")
    er.async_get(hass).async_get_or_create(
        domain, "pururu", object_id, suggested_object_id=object_id,
        disabled_by=er.RegistryEntryDisabler.USER)


async def test_the_goals_example_creates_what_the_page_says(ha: HomeAssistant) -> None:
    """Every goal of the example is its two sensors, the first named as the page shows it."""
    devices = goals_example()["devices"]
    assert await setup(ha, devices)
    for key, device in devices.items():
        for goal in device["goals"]:
            for sensor in ("target", "done"):
                assert ha.states.get(f"sensor.pururu_{key}_goal_{goal}_{sensor}") is not None, (key, goal)
    target = ha.states.get("sensor.pururu_pool_goal_filtering_target")
    assert f"**{target.attributes['friendly_name']}**" in GOALS_PAGE.read_text(encoding="utf-8")
    assert float(target.state) == 6


async def test_the_goals_pages_log_lines_are_the_codes(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """The page's example, its heater's energy a measurement and the pool's runtime total disabled."""
    quoted = GOAL_LINE.findall(GOALS_PAGE.read_text(encoding="utf-8"))
    assert len(quoted) >= 2
    doesnt_accumulate(ha, "sensor.pool_heater_energy")
    disabled(ha, POOL_RUNTIME_TOTAL)
    assert await setup(ha, goals_example()["devices"])
    for line in quoted:
        assert line in caplog.text, line


def troubleshooting_goal_lines() -> list[str]:
    """The goals' lines troubleshooting shows in its code blocks."""
    blocks = re.findall(r"```\n(.*?)```", TROUBLESHOOTING_PAGE.read_text(encoding="utf-8"), re.DOTALL)
    return [line for block in blocks for line in block.splitlines() if "_goal_" in line or ": goals: " in line]


@pytest.mark.parametrize("line", troubleshooting_goal_lines())
async def test_troubleshootings_goal_lines_are_the_codes(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, line: str) -> None:
    """The pool's filtering goal, on a power reading or on its disabled runtime total, logs the line as shown."""
    assert GOAL_LINE.fullmatch(line), line
    filtering = {"name": "Filtragem", "target": 6, "period": "today",
                 "tracked_by": "appliance.running_program.runtime_total"}
    if "doesn't accumulate" in line:
        filtering["tracked_by"] = "homeassistant.sensor.pool_pump_power"
        doesnt_accumulate(ha, "sensor.pool_pump_power")
    else:
        disabled(ha, POOL_RUNTIME_TOTAL)
    appliance = {"power": "homeassistant.sensor.pool_pump_power",
                 "running_program": {"above": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}}}
    assert await setup(ha, {"pool": {"name": "Piscina", "appliance": appliance, "goals": {"filtering": filtering}}})
    assert line in caplog.text
