"""The pages that state what the code does: each says what the code holds."""

from pathlib import Path
import re
from typing import Any

from homeassistant.core import HomeAssistant
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


# --- docs/concepts/devices-and-features.mdx ----------------------------------------------

FEATURES_PAGES = PROJECT / "docs/features"
DEVICES_PAGE = PROJECT / "docs/concepts/devices-and-features.mdx"
KINDS = {"feature": "features", "device key": "device_keys"}


def differs(what: str, documented: set[str], code: set[str]) -> str:
    """Names what the code has and the docs don't, and the other way round."""
    return (f"{what}: not documented {sorted(code - documented)}, "
            f"documented but not in the code {sorted(documented - code)}")


def aspects_table() -> dict[str, tuple[str, set[str]]]:
    """The Aspects section's table: each row's key → (its kind, the aspects marked ✓)."""
    lines = [line for line in section(DEVICES_PAGE, "Aspects").splitlines() if line.startswith("|")]
    assert lines, "no table in the Aspects section"
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    assert header[:2] == ["Key", "Kind"], header
    aspects = [cell.strip("`") for cell in header[2:]]
    rows: dict[str, tuple[str, set[str]]] = {}
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        key = re.search(r"`(\w+)`", cells[0])
        assert key is not None, line
        rows[key[1]] = (cells[1], {aspect for aspect, cell in zip(aspects, cells[2:], strict=True)
                                   if cell == "✓"})
    return rows


def test_every_feature_has_its_page(ha: HomeAssistant) -> None:
    """AE6: a feature without a page under docs/features/ fails, named."""
    pages = {page.stem for page in FEATURES_PAGES.glob("*.mdx")}
    assert pages == set(module("features").FEATURES), differs(
        "features with a page", pages, set(module("features").FEATURES))


def test_the_aspects_table_lists_every_feature_and_device_key(ha: HomeAssistant) -> None:
    table = aspects_table()
    for kind, package in KINDS.items():
        listed = {key for key, (its, _) in table.items() if its == kind}
        code = set(getattr(module(package), package.upper()))
        assert listed == code, differs(f"rows of kind {kind}", listed, code)
    assert {kind for kind, _ in table.values()} <= set(KINDS), table


def test_the_aspects_table_marks_the_aspects_each_offers(ha: HomeAssistant) -> None:
    catalogue = module("setup.catalogue")
    for key, (_, marked) in aspects_table().items():
        offered = {aspect.key for aspect in catalogue.aspects_of(catalogue.builders()[key])}
        assert marked == offered, differs(f"aspects of {key}", marked, offered)


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
