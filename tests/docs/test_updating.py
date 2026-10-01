"""The Guide's "Updating to 0.2.2": each step shows both versions, each a part of its whole example, the whole after sets up, and each old form, as the page writes it, is refused with what the page quotes."""

from copy import deepcopy
from pathlib import Path
import re
from typing import Any

from homeassistant.config import humanize_error
from homeassistant.core import HomeAssistant
import pytest
import voluptuous as vol
import yaml

from helpers import module, setup

PAGE = Path(__file__).resolve().parents[2] / "docs/getting-started/updating-to-0.2.2.mdx"
BEFORE = "0.2.1"
AFTER = "0.2.2"
WHOLE = ": configuration.yaml"


class _Loader(yaml.SafeLoader):
    """configuration.yaml's own tags (!include_dir_…) read as nothing: only pururu: is checked."""


_Loader.add_multi_constructor("!", lambda *_: None)


def titles() -> list[str]:
    """The titles of the page's YAML blocks, in order."""
    return re.findall(r'```yaml title="([^"]*)"', PAGE.read_text())


def blocks(title: str) -> list[Any]:
    """The page's YAML blocks titled exactly `title`, in order."""
    found = re.findall(rf'```yaml title="{re.escape(title)}"\n(.*?)```', PAGE.read_text(), re.DOTALL)
    return [yaml.load(block, Loader=_Loader) for block in found]


def whole(version: str) -> Any:
    """The whole example's configuration.yaml, as `version` reads it."""
    [found] = blocks(version + WHOLE)
    return found


def test_each_step_shows_both_versions() -> None:
    """The steps' blocks go 0.2.1, then 0.2.2, pair by pair; the two whole examples apart."""
    steps = [title for title in titles() if not title.endswith(WHOLE)]
    assert steps
    assert steps == [BEFORE, AFTER] * (len(steps) // 2)
    assert sorted(title for title in titles() if title.endswith(WHOLE)) == [BEFORE + WHOLE, AFTER + WHOLE]


def _within(part: Any, at: Any) -> bool:
    """Whether `part` is `at`, or, for a map, its keys are some of `at`'s, each within."""
    if isinstance(part, dict):
        return isinstance(at, dict) and all(key in at and _within(value, at[key]) for key, value in part.items())
    return bool(part == at)


def _maps(at: Any) -> list[dict[str, Any]]:
    """Every map in `at`, `at` included."""
    if isinstance(at, dict):
        return [at, *(found for value in at.values() for found in _maps(value))]
    if isinstance(at, list):
        return [found for value in at for found in _maps(value)]
    return []


@pytest.mark.parametrize("version", [BEFORE, AFTER])
def test_each_step_is_part_of_the_whole_example(version: str) -> None:
    """A step's block, as the page writes it, is in the whole example of its version."""
    house = whole(version)
    for block in blocks(version):
        assert any(_within(block, at) for at in _maps(house)), block


async def test_the_whole_example_sets_up(ha: HomeAssistant) -> None:
    """Every 0.2.2 form of the steps, in one block: valid, and pururu sets it up."""
    house = whole(AFTER)["pururu"]
    assert await setup(ha, house["devices"], config=house["config"])


def test_the_whole_example_before_is_refused(ha: HomeAssistant) -> None:
    """0.2.1's whole block, unchanged, is refused: an old reference is never read as a new one."""
    schema = module("setup.schema").CONFIG_SCHEMA
    config = {"pururu": whole(BEFORE)["pururu"]}
    with pytest.raises(vol.Invalid) as refused:
        schema(config)
    assert "is not a path: write it from its block, <block>.<key>" in humanize_error(
        ha, refused.value, "pururu", config, None)


WAS = whole(BEFORE)["pururu"]
WASHER = ["devices", "clothes_washer"]
STUCK = [*WASHER, "alerts", "stuck"]
MORNING = ["devices", "greenhouse", "reactions", "morning"]
REACTION = ["devices", "biblioteca", "reactions", "washer_done"]
GROUPS = ["config", "alerts", "lights", "groups"]
NOT_A_PATH = "{} is not a path: write it from its block, <block>.<key>"


def was(*path: str) -> Any:
    """The value at `path` of 0.2.1's whole block, as the page writes it."""
    at: Any = WAS
    for step in path:
        at = at[step]
    return deepcopy(at)


def where(*path: str) -> str:
    """A refusal's place, as Home Assistant writes it."""
    return "->".join(("pururu", *path))


def value(message: str, *path: str) -> str:
    """A value a validator refuses, at its place."""
    return f"{message} for dictionary value '{where(*path)}'"


def check(message: str, *path: str) -> str:
    """A refusal at its place, as Home Assistant writes one a rule over the house or a list's item gives."""
    return f"{message} '{where(*path)}'"


def old(why: str, path: list[str], key: str, form: Any, refusal: str, quote: str | None = None) -> Any:
    """An old form: `form` at `key` of `path`, refused with `refusal`, of which the page quotes `quote`."""
    return pytest.param(path, key, form, refusal, quote, id=f"{why}, as before 0.2.2")


OWN = "alerts: device.clothes_washer.appliance.running_program.phase_current is this device's: " \
    "write appliance.running_program.phase_current"
OTHER = "reactions: washer_done: clothes_washer.appliance_running: clothes_washer is not a block of this device"
MEMBER = "biblioteca.light_teto needs its device: device.<device>.lights.<key>"
THEN = "then is its program's key alone: clean"

OLDS = [
    old("an entity key in an alert's when", STUCK, "when", was(*STUCK, "when"),
        value(NOT_A_PATH.format("appliance_phase_current"), *STUCK, "when"),
        NOT_A_PATH.format("appliance_phase_current")),
    old("another device's entity key", REACTION, "when", was(*REACTION, "when"),
        check(OTHER, *REACTION, "when"), OTHER),
    old("a light group's member", GROUPS, "default", was(*GROUPS, "default"),
        check(MEMBER, *GROUPS, "default", "0"), MEMBER),
    old("a device naming itself", STUCK, "when", "device.clothes_washer.appliance.running_program.phase_current",
        check(OWN, *STUCK, "when"), OWN),
    old("a then as a path", MORNING, "then", "programs.executable.clean", value(THEN, *MORNING, "then"), THEN),
]


def test_the_table_gives_an_old_reference_its_path() -> None:
    """The washer's alert while it runs: appliance_running is appliance.running_program."""
    assert "| `appliance_running` | `appliance.running_program` |" in PAGE.read_text()


@pytest.mark.parametrize(("path", "key", "form", "refusal", "quote"), OLDS)
def test_the_whole_example_is_refused_with_any_old_form(
    ha: HomeAssistant, path: list[str], key: str, form: Any, refusal: str, quote: str | None
) -> None:
    """Each 0.2.1 form the steps rewrite, put back in the whole example, is refused at its place, as the page quotes it."""
    house = deepcopy(whole(AFTER)["pururu"])
    at = house
    for step in path:
        at = at[step]
    at[key] = form
    config = {"pururu": house}
    schema = module("setup.schema").CONFIG_SCHEMA
    with pytest.raises(vol.Invalid) as refused:
        schema(config)
    assert refusal in humanize_error(ha, refused.value, "pururu", config, None)
    assert quote is None or (quote in refusal and quote in PAGE.read_text())
