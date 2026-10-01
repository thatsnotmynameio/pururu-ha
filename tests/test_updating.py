"""The Guide's "Updating to 0.2.1": each step shows both versions, each a part of its whole example, the whole after sets up, and each old form, as the page writes it, is refused with what the page quotes."""

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

PAGE = Path(__file__).resolve().parents[1] / "docs/getting-started/updating-to-0.2.1.mdx"
BEFORE = "0.1.23"
AFTER = "0.2.1"
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
    """The steps' blocks go 0.1.23, then 0.2.1, pair by pair; the two whole examples apart."""
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
    """Every 0.2.1 key of the steps, in one block: valid, and pururu sets it up."""
    house = whole(AFTER)["pururu"]
    assert await setup(ha, house["devices"], config=house["config"])


def test_the_whole_example_before_is_refused(ha: HomeAssistant) -> None:
    """0.1.23's whole block, unchanged, is refused: an old key is never read as a new one."""
    schema = module("setup.schema").CONFIG_SCHEMA
    config = {"pururu": whole(BEFORE)["pururu"]}
    with pytest.raises(vol.Invalid) as refused:
        schema(config)
    assert "is an invalid option for 'pururu'" in humanize_error(ha, refused.value, "pururu", config, None)


WAS = whole(BEFORE)["pururu"]
WASHER = ["devices", "clothes_washer"]
STUCK = [*WASHER, "alerts", "stuck"]
LONG_CYCLE = [*WASHER, "appliance", "alerts", "long_cycle"]
RUNNING_PROGRAM = [*WASHER, "appliance", "running_program"]
PHASES = [*RUNNING_PROGRAM, "phases"]
BANDS = [*WASHER, "phases"]
WATER_STATION = ["devices", "water_station"]
DOOR = ["devices", "porta_frente", "door"]
GREENHOUSE = ["devices", "greenhouse"]
REACTION = ["devices", "biblioteca", "reactions", "washer_done"]
GROUPS = ["config", "alerts", "lights", "groups"]
RESOLVED = ["config", "alerts", "lights", "resolved"]
LIGHTS = "lights names a group of config.alerts.lights.groups, such as default; absent, the alert borrows none"
NUMBER = 'YAML reads it as the number {}: compare a reading with above or below, or quote the state as the entity shows it ("1.0")'
NOT_A_KEY = "alerts: {} is not an entity key of another feature of this device"


def was(*path: str) -> Any:
    """The value at `path` of 0.1.23's whole block, as the page writes it."""
    at: Any = WAS
    for step in path:
        at = at[step]
    return deepcopy(at)


def where(*path: str) -> str:
    """A refusal's place, as Home Assistant writes it."""
    return "->".join(("pururu", *path))


def invalid(path: list[str], key: str) -> str:
    """A key the schema doesn't know, refused at its place."""
    return f"'{key}' is an invalid option for 'pururu', check: {where(*path, key)}"


def value(message: str, *path: str) -> str:
    """A value a validator refuses, at its place."""
    return f"{message} for dictionary value '{where(*path)}'"


def check(message: str, *path: str) -> str:
    """A rule over the house's refusal, at its place."""
    return f"{message} '{where(*path)}'"


def old(why: str, path: list[str], key: str, form: Any, refusal: str, quote: str | None = None) -> Any:
    """An old form: `form` at `key` of `path`, refused with `refusal`, of which the page quotes `quote`."""
    return pytest.param(path, key, form, refusal, quote, id=f"{why}, as before 0.2.1")


OLDS = [
    old("an alert's is", STUCK, "is", was(*STUCK, "is"), invalid(STUCK, "is"), invalid(STUCK, "is")),
    old("an alert's notify", STUCK, "notify", was(*STUCK, "notify"), invalid(STUCK, "notify")),
    old("a ready-made alert's notify", LONG_CYCLE, "notify", was(*LONG_CYCLE, "notify"),
        invalid(LONG_CYCLE, "notify")),
    old("lights: true", STUCK, "lights", was(*STUCK, "lights"), value(LIGHTS, *STUCK, "lights"), LIGHTS),
    old("lights: false", STUCK, "lights", False, value(LIGHTS, *STUCK, "lights"), LIGHTS),
    old("a number in an alert's state", STUCK, "state", 1,
        value("state: " + NUMBER.format(1), *STUCK, "state"), "state: " + NUMBER.format(1)),
    old("a number in a reaction's to", REACTION, "to", 1, value("to: " + NUMBER.format(1), *REACTION, "to")),
    old("a number in a reaction's from", REACTION, "from", 0,
        value("from: " + NUMBER.format(0), *REACTION, "from")),
    old("when: phase_current", STUCK, "when", was(*STUCK, "when"),
        check(NOT_A_KEY.format("phase_current"), *WASHER, "alerts")),
    old("when: mode_current", STUCK, "when", "mode_current",
        check(NOT_A_KEY.format("mode_current"), *WASHER, "alerts")),
    old("a reaction's device", REACTION, "device", was(*REACTION, "device"), invalid(REACTION, "device")),
    old("a reaction's when as an entity ID", REACTION, "when",
        "binary_sensor.pururu_clothes_washer_appliance_running",
        check("device biblioteca: reactions: washer_done: device binary_sensor is not in devices "
              "(binary_sensor.pururu_clothes_washer_appliance_running is an entity ID: write "
              "clothes_washer.appliance_running)", *REACTION),
        "device binary_sensor is not in devices (binary_sensor.pururu_clothes_washer_appliance_running is an "
        "entity ID: write clothes_washer.appliance_running)"),
    old("a door's events", DOOR, "events", was(*DOOR, "events"), invalid(DOOR, "events")),
    old("the appliance's running", [*WASHER, "appliance"], "running", was(*WASHER, "appliance", "running"),
        invalid([*WASHER, "appliance"], "running")),
    old("threshold in running_program", RUNNING_PROGRAM, "threshold",
        was(*WASHER, "appliance", "running", "threshold"), invalid(RUNNING_PROGRAM, "threshold")),
    old("modes", WATER_STATION, "modes", was(*WATER_STATION, "modes"), invalid(WATER_STATION, "modes")),
    old("phases", WASHER, "phases", was(*BANDS), invalid(WASHER, "phases")),
    old("a phase's for", [*PHASES, "wringing"], "for", was(*BANDS, "bands", "wringing", "for"),
        invalid([*PHASES, "wringing"], "for")),
    old("a phase's sensor", [*PHASES, "wringing"], "sensor", was(*BANDS, "sensor"),
        invalid([*PHASES, "wringing"], "sensor")),
    old("a phase keyed idle", PHASES, "idle", {"name": "Parada", "above": 5},
        check("idle is a reserved phase key: name the phase otherwise", *PHASES, "idle")),
    old("a phase keyed current", PHASES, "current", {"name": "Atual", "above": 5},
        value("phase current would create phase_current, the detector's", *PHASES)),
    old("a phase keyed last", PHASES, "last", {"name": "Última", "above": 5},
        value("phase last would create phase_last, the detector's", *PHASES)),
    old("a phase keyed other_…", PHASES, "other_spin", {"name": "Spin", "above": 4},
        check("other_spin is reserved for the built-in phase other (other, other_…): name the phase otherwise",
              *PHASES, "other_spin"),
        "other_spin is reserved for the built-in phase other (other, other_…): name the phase otherwise"),
    old("a device's programs", GREENHOUSE, "programs", was(*GREENHOUSE, "programs"),
        value("a device's programs sit under executable: (programs: executable: <key>: …)", *GREENHOUSE, "programs"),
        "a device's programs sit under executable: (programs: executable: <key>: …)"),
    old("when: program_<key>_…", GREENHOUSE, "alerts",
        {"stalled": {"name": "Parada", "when": "program_clean_cycles_total", "above": 9}},
        check(NOT_A_KEY.format("program_clean_cycles_total"), *GREENHOUSE, "alerts"),
        NOT_A_KEY.format("program_clean_cycles_total")),
    old("a top-level events", [], "events", was("events"), invalid([], "events"), invalid([], "events")),
    old("resolved's for", RESOLVED, "for", was(*RESOLVED, "for"), invalid(RESOLVED, "for")),
    old("a light group as a map", GROUPS, "default", was(*GROUPS, "default"),
        value("expected a list", *GROUPS, "default")),
    old("a light group's member that isn't a light", GROUPS, "default", ["greenhouse.switch_sprinkler"],
        check("config.alerts.lights.groups: default: greenhouse.switch_sprinkler is not a light",
              *GROUPS, "default", "0"),
        "config.alerts.lights.groups: default: greenhouse.switch_sprinkler is not a light"),
    old("a light group's member as an entity ID", GROUPS, "default", ["light.pururu_biblioteca_light_teto"],
        check("config.alerts.lights.groups: default: device light is not in devices "
              "(light.pururu_biblioteca_light_teto is an entity ID: write biblioteca.light_teto)",
              *GROUPS, "default", "0"),
        "device light is not in devices (light.pururu_biblioteca_light_teto is an entity ID: write "
        "biblioteca.light_teto)"),
    old("an empty name", WASHER, "name", "", value("length of value must be at least 1", *WASHER, "name")),
]


@pytest.mark.parametrize(("path", "key", "form", "refusal", "quote"), OLDS)
def test_the_whole_example_is_refused_with_any_old_form(
    ha: HomeAssistant, path: list[str], key: str, form: Any, refusal: str, quote: str | None
) -> None:
    """Each 0.1.23 form the steps rewrite, put back in the whole example, is refused at its place, as the page quotes it."""
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
