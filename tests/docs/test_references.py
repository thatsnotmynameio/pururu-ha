"""Every published page writes references as 0.2.2 reads them: each whole pururu: block is valid, and no 0.2.1 form is left in the text, but where a page shows one as before 0.2.2."""

from pathlib import Path
import re
from typing import Any

from homeassistant.config import humanize_error
from homeassistant.core import HomeAssistant
import pytest
import voluptuous as vol
import yaml

from helpers import module

PROJECT = Path(__file__).resolve().parents[2]
# What docs.page publishes, and the README that links to it
PAGES = sorted([*(PROJECT / "docs").rglob("*.mdx"), PROJECT / "README.md"])
UPDATING = PROJECT / "docs/getting-started/updating-to-0.2.2.mdx"
TROUBLESHOOTING = PROJECT / "docs/reference/troubleshooting.mdx"
YAML = re.compile(r'```yaml(?: title="([^"]*)")?\n(.*?)```', re.DOTALL)
# Home Assistant's domains, before a dot in an entity ID or an action
DOMAINS = r"(?:sensor|binary_sensor|switch|light|event|notify|script|automation|button)"
# A 0.2.1 entity key begins with its namespace
NAMESPACES = r"(?:appliance|door|window|switch|light|button|program|reaction|alert)_"
OLD_FORMS = {
    # power: sensor.washer_plug_power, entity: light.teto, notify: notify.phone
    "a Home Assistant entity without homeassistant.":
        re.compile(rf"\b(?:power|energy|contact|entity|notify)\s*:\s*\[?\s*{DOMAINS}\."),
    # when: door_open, turn_on: switch_sprinkler
    "an entity key for a path": re.compile(r"\b(?:when|turn_on|turn_off|toggle)\s*:\s*[a-z0-9_]+\s*(?:[,})\]#`]|$)",
                                           re.MULTILINE),
    # The running appliance as 0.2.1 named it; an entity ID holds it after an _
    "appliance_running for appliance.running_program": re.compile(r"(?<![\w.])appliance_running\b"),
    # clothes_washer.appliance_running, biblioteca.light_teto
    "another device's entity key": re.compile(rf"(?<![\w.])(?!{DOMAINS}\.)[a-z0-9_]+\.{NAMESPACES}[a-z0-9_]*"),
}


class _Loader(yaml.SafeLoader):
    """configuration.yaml's own tags (!include_dir_…, !secret) read as nothing: only pururu: is checked."""


_Loader.add_multi_constructor("!", lambda *_: None)


def shown_as_before(page: Path, line: str) -> bool:
    """Whether the line shows a 0.2.1 form on purpose: the Updating page, or a refusal troubleshooting quotes."""
    return page == UPDATING or (page == TROUBLESHOOTING and "0.2.2" in line)


def _guide(page: Path) -> bool:
    """A page for users; the Develop tab's may name a qualified entity key, as the code does."""
    return not page.is_relative_to(PROJECT / "docs/develop")


@pytest.mark.parametrize("page", PAGES, ids=lambda page: page.relative_to(PROJECT).as_posix())
def test_no_page_writes_a_0_2_1_form(page: Path) -> None:
    """appliance_running, <device>.<key>, a bare entity ID in a field or .light_ in a group: refused since 0.2.2."""
    found = [
        f"{page.name}:{number}: {why}: {match[0]}"
        for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1)
        if not shown_as_before(page, line)
        for why, form in OLD_FORMS.items()
        if why != "appliance_running for appliance.running_program" or _guide(page)
        for match in form.finditer(line)
    ]
    assert not found, "\n".join(found)


def whole_blocks() -> list[Any]:
    """Each Guide page's YAML block holding a whole pururu: block with devices.

    Not the Updating page's 0.2.1 ones, nor one that leaves a part out (`# ... as above`); the
    Develop tab's sketch a feature that doesn't exist.
    """
    found = []
    for page in filter(_guide, PAGES):
        for title, block in YAML.findall(page.read_text(encoding="utf-8")):
            if (page == UPDATING and title.startswith("0.2.1")) or "# ..." in block:
                continue
            loaded = yaml.load(block, Loader=_Loader)
            if isinstance(loaded, dict) and isinstance(loaded.get("pururu"), dict) and "devices" in loaded["pururu"]:
                found.append(pytest.param(loaded["pururu"], id=f"{page.relative_to(PROJECT).as_posix()}:{title}"))
    return found


@pytest.mark.parametrize("block", whole_blocks())
def test_each_whole_block_is_valid(ha: HomeAssistant, block: dict[str, Any]) -> None:
    """A page's whole pururu: block passes the schema and every rule over the house.

    An example may leave out the areas its devices are in: they're declared for it.
    """
    areas = {device["area"]: {"name": device["area"]} for device in block["devices"].values() if "area" in device}
    config = {"pururu": {**block, "areas": {**areas, **block.get("areas", {})}}}
    try:
        module("setup.schema").CONFIG_SCHEMA(config)
    except vol.Invalid as refused:
        pytest.fail(humanize_error(ha, refused, "pururu", config, None))
