"""The suite's edges: it sees pururu only from outside, on the Home Assistant the root tests run."""

import ast
from pathlib import Path
import tomllib

from homeassistant.const import __version__ as HA_VERSION
import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
# What the suite must never import: pururu's own code and the root tests' helpers
FORBIDDEN = ("custom_components.pururu", "tests")


def forbidden_imports(source: str) -> list[str]:
    """The modules `source` imports from pururu or the root tests."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
        else:
            continue
        found += [name for name in names
                  if any(name == bad or name.startswith(f"{bad}.") for bad in FORBIDDEN)]
    return found


def pin_mismatch(lock: str, version: str) -> str | None:
    """Why `version` isn't the Home Assistant a uv.lock pins, or None when it is."""
    pinned = [package["version"] for package in tomllib.loads(lock)["package"]
              if package["name"] == "homeassistant"]
    if pinned == [version]:
        return None
    return f"the root project runs homeassistant {pinned}, acceptance runs {version}"


def test_no_module_imports_pururu_or_the_root_tests() -> None:
    found = {path.name: forbidden_imports(path.read_text(encoding="utf-8"))
             for path in sorted(HERE.glob("*.py"))}
    assert {name: imports for name, imports in found.items() if imports} == {}


@pytest.mark.parametrize(("source", "found"), [
    pytest.param("import custom_components.pururu", ["custom_components.pururu"], id="the package"),
    pytest.param("from custom_components.pururu.core import feature",
                 ["custom_components.pururu.core", "custom_components.pururu.core.feature"],
                 id="a module of it"),
    pytest.param("from custom_components import pururu", ["custom_components.pururu"], id="from its parent"),
    pytest.param("import tests.helpers", ["tests.helpers"], id="the root tests"),
    pytest.param("from tests import helpers", ["tests", "tests.helpers"], id="from the root tests"),
    pytest.param("import custom_components", [], id="the bare package"),
    pytest.param("import testsuite", [], id="a name that only starts alike"),
])
def test_the_import_guard(source: str, found: list[str]) -> None:
    assert forbidden_imports(source) == found


def test_the_same_home_assistant_as_the_root_project() -> None:
    assert pin_mismatch((REPO / "uv.lock").read_text(encoding="utf-8"), HA_VERSION) is None


def test_another_home_assistant_is_named() -> None:
    lock = '[[package]]\nname = "homeassistant"\nversion = "2099.1.0"\n'
    assert pin_mismatch(lock, "2026.9.3") == (
        "the root project runs homeassistant ['2099.1.0'], acceptance runs 2026.9.3")


def test_the_root_tests_do_not_collect_acceptance() -> None:
    root = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    paths = root["tool"]["pytest"]["ini_options"]["testpaths"]
    assert not [path for path in paths if Path(path).parts[:1] == ("acceptance",)]
