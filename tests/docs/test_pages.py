"""The pages that state what the code does: each says what the code holds."""

from pathlib import Path
import re
from typing import Any

from homeassistant.core import HomeAssistant
import yaml

from helpers import module, setup

PROJECT = Path(__file__).resolve().parents[2]
CODE = "custom_components/pururu"


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
    page = NOTIFICATIONS_PAGE.read_text(encoding="utf-8")
    section = re.search(r"## Ready-made notifications\n(.*?)\n## ", page, re.DOTALL)
    assert section is not None, "no Ready-made notifications section"
    for name, feature in module("features").FEATURES.items():
        for notification in module("core.feature").happenings_of(feature):
            assert f"`{name}: notifications: {notification}`" in section[1], notification


# --- docs/features/door.mdx --------------------------------------------------------------

DOOR_PAGE = PROJECT / "docs/features/door.mdx"


def test_the_door_page_lists_every_ready_made_alert(ha: HomeAssistant) -> None:
    """The window page points to the door's: one list for both."""
    page = DOOR_PAGE.read_text(encoding="utf-8")
    section = re.search(r"## Ready-made alerts\n(.*?)\n## ", page, re.DOTALL)
    assert section is not None, "no Ready-made alerts section"
    features = module("features").FEATURES
    for name in module("core.feature").presets_of(features["door"]):
        assert f"`{name}`" in section[1], name
    assert set(module("core.feature").presets_of(features["window"])) == set(
        module("core.feature").presets_of(features["door"]))


# --- docs/features/appliance.mdx ---------------------------------------------------------

APPLIANCE_PAGE = PROJECT / "docs/features/appliance.mdx"


def test_the_appliance_page_lists_every_ready_made_alert(ha: HomeAssistant) -> None:
    page = APPLIANCE_PAGE.read_text(encoding="utf-8")
    section = re.search(r"## Ready-made alerts\n(.*?)\n## ", page, re.DOTALL)
    assert section is not None, "no Ready-made alerts section"
    for name in module("core.feature").presets_of(module("features").FEATURES["appliance"]):
        assert f"`{name}`" in section[1], name
