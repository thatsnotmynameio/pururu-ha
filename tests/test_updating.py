"""The Guide's "Updating to 0.2.1": each step shows both versions, the whole example sets up, and each old form is refused with what the page quotes."""

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


class _Loader(yaml.SafeLoader):
    """configuration.yaml's own tags (!include_dir_…) read as nothing: only pururu: is checked."""


_Loader.add_multi_constructor("!", lambda *_: None)


def blocks(version: str) -> list[Any]:
    """The page's YAML blocks titled `version`, in order."""
    found = re.findall(rf'```yaml title="{re.escape(version)}[^"]*"\n(.*?)```', PAGE.read_text(), re.DOTALL)
    return [yaml.load(block, Loader=_Loader) for block in found]


def test_each_step_shows_both_versions() -> None:
    assert len(blocks("0.1.23")) == len(blocks("0.2.1")) - 1  # the whole example has no "before"


async def test_the_whole_example_sets_up(ha: HomeAssistant) -> None:
    """Every 0.2.1 key of the steps, in one block: valid, and pururu sets it up."""
    [whole] = blocks("0.2.1: configuration.yaml")
    house = whole["pururu"]
    assert await setup(ha, house["devices"], config=house["config"])


STUCK = ["devices", "clothes_washer", "alerts", "stuck"]
WASHER = ["devices", "clothes_washer"]
REACTION = ["devices", "biblioteca", "reactions", "washer_done"]
GROUPS = ["config", "alerts", "lights", "groups"]
INVALID = "is an invalid option for 'pururu', check: pururu->"


def old(why: str, path: list[str], key: str, value: Any, refusal: str, *, quoted: bool = False) -> Any:
    """An old form: `value` at `key` of `path`, refused with `refusal` (as the page quotes it, when `quoted`)."""
    return pytest.param(path, key, value, refusal, quoted, id=f"{why}, as before 0.2.1")


OLDS = [
    old("an alert's is", STUCK, "is", "wringing",
        f"'is' {INVALID}devices->clothes_washer->alerts->stuck->is", quoted=True),
    old("an alert's notify", STUCK, "notify", {"message": "m", "done_message": "d"}, f"'notify' {INVALID}"),
    old("lights: true", STUCK, "lights", True,
        "lights names a group of config.alerts.lights.groups, such as default; absent, the alert "
        "borrows none", quoted=True),
    old("a number in state", STUCK, "state", 1,
        'state: YAML reads it as the number 1: compare a reading with above or below, or quote the '
        'state as the entity shows it ("1.0")', quoted=True),
    old("when: phase_current", STUCK, "when", "phase_current",
        "alerts: phase_current is not an entity key of another feature of this device"),
    old("a reaction's device", REACTION, "device", "clothes_washer", f"'device' {INVALID}"),
    old("a reaction's when as an entity ID", REACTION, "when",
        "binary_sensor.pururu_clothes_washer_appliance_running",
        "device binary_sensor is not in devices (binary_sensor.pururu_clothes_washer_appliance_running "
        "is an entity ID: write clothes_washer.appliance_running)", quoted=True),
    old("a door's events", ["devices", "porta_frente", "door"], "events",
        [{"entity": "event.x", "types": {"ring": "ring"}}], f"'events' {INVALID}devices->porta_frente"),
    old("the appliance's running", WASHER + ["appliance"], "running", {"threshold": 4}, f"'running' {INVALID}"),
    old("modes", WASHER, "modes", {"modes": {"resfriar": {"name": "Resfriar", "above": 4}}},
        f"'modes' {INVALID}"),
    old("a phase keyed other_…", WASHER + ["appliance", "running_program", "phases"], "other_spin",
        {"name": "Spin", "above": 4},
        "other_spin is reserved for the built-in phase other (other, other_…): name the phase otherwise",
        quoted=True),
    old("a device's programs", ["devices", "greenhouse"], "programs",
        {"clean": {"name": "Limpar", "sequence": [{"turn_on": "switch_sprinkler"}]}},
        "a device's programs sit under executable: (programs: executable: <key>: …)", quoted=True),
    old("when: program_<key>_…", ["devices", "greenhouse"], "alerts",
        {"stalled": {"name": "Parada", "when": "program_clean_cycles_total", "above": 9}},
        "alerts: program_clean_cycles_total is not an entity key of another feature of this device",
        quoted=True),
    old("a top-level events", [], "events", ["reading"], f"'events' {INVALID}events", quoted=True),
    old("resolved's for", ["config", "alerts", "lights", "resolved"], "for", {"seconds": 120},
        f"'for' {INVALID}"),
    old("a light group as a map", GROUPS, "default", {"biblioteca": ["teto"]}, "expected a list"),
    old("a light group's member that isn't a light", GROUPS, "default", ["greenhouse.switch_sprinkler"],
        "config.alerts.lights.groups: default: greenhouse.switch_sprinkler is not a light", quoted=True),
    old("a light group's member as an entity ID", GROUPS, "default", ["light.pururu_biblioteca_light_teto"],
        "device light is not in devices (light.pururu_biblioteca_light_teto is an entity ID: write "
        "biblioteca.light_teto)", quoted=True),
]


@pytest.mark.parametrize(("path", "key", "value", "refusal", "quoted"), OLDS)
def test_the_whole_example_is_refused_with_any_old_form(
    ha: HomeAssistant, path: list[str], key: str, value: Any, refusal: str, quoted: bool
) -> None:
    """Each 0.1.23 form the steps rewrite, put back in the whole example, is refused, as the page quotes it."""
    [whole] = blocks("0.2.1: configuration.yaml")
    house = yaml.load(yaml.dump(whole["pururu"]), Loader=_Loader)
    at = house
    for step in path:
        at = at[step]
    at[key] = value
    config = {"pururu": house}
    with pytest.raises(vol.Invalid) as refused:
        module("setup.schema").CONFIG_SCHEMA(config)
    assert refusal in humanize_error(ha, refused.value, "pururu", config, None)
    assert not quoted or refusal in PAGE.read_text()
