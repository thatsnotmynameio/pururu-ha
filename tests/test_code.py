"""custom_components/pururu passes core's own tools at the pinned HA."""

import ast
import os
from pathlib import Path
import re
import subprocess
import sys

import fetch_hassfest
import pytest
import yaml

RULE = re.compile(r'Rule\("([a-z-]+)"')

PROJECT = Path(__file__).resolve().parents[1]
CODE = "custom_components/pururu"
BIN = Path(sys.executable).parent


def run(*args: str, cwd: Path = PROJECT) -> subprocess.CompletedProcess[str]:
    """A tool from this project's venv (on PATH too: hassfest calls ruff)."""
    env = {**os.environ, "PATH": f"{BIN}{os.pathsep}{os.environ.get('PATH', '')}"}
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, check=False)


def test_ruff_check() -> None:
    result = run(str(BIN / "ruff"), "check", "--config", str(PROJECT / "ruff.toml"), CODE)
    assert result.returncode == 0, result.stdout + result.stderr


def test_ruff_format() -> None:
    result = run(str(BIN / "ruff"), "format", "--check", "--config", str(PROJECT / "ruff.toml"),
                 CODE)
    assert result.returncode == 0, result.stdout + result.stderr


def test_mypy() -> None:
    result = run(str(BIN / "mypy"), "--config-file", str(PROJECT / "mypy.ini"), CODE)
    assert result.returncode == 0, result.stdout + result.stderr


def test_hassfest() -> None:
    """Manifest, services, translations (en.json), icons and config flow, as core validates them."""
    result = run(sys.executable, "-m", "script.hassfest", "--action", "validate",
                 "--integration-path", str(PROJECT / CODE), cwd=fetch_hassfest.ensure())
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Invalid integrations: 0" in output, output


def test_quality_scale_covers_every_rule() -> None:
    """Every rule of the pinned hassfest: done (a comment optional), or exempt/todo with the reason."""
    rules = set(RULE.findall(
        (fetch_hassfest.ensure() / "script/hassfest/quality_scale.py").read_text()))
    assert len(rules) > 40, rules
    ours = yaml.safe_load((PROJECT / CODE / "quality_scale.yaml").read_text())["rules"]
    assert set(ours) == rules, set(ours) ^ rules
    for rule, status in ours.items():
        if status == "done":
            continue
        assert isinstance(status, dict), rule
        assert status["status"] in ("done", "exempt", "todo"), rule
        assert status.get("comment"), f"{rule}: {status['status']} without a comment"


PLATFORMS = {"sensor", "binary_sensor", "button", "switch", "light"}


def imports_of(path: Path) -> set[str]:
    """The integration's modules a file imports, dotted from the package root (aspects.alerts).

    Each name imported counts: a module (`from ..core import generated`: core.generated),
    or else the module it's taken from (`from ..features import FEATURES`: features,
    the package's `__init__`).

    An absolute self-import (`from custom_components.pururu.outputs import dashboard`,
    `import custom_components.pururu.const`) counts the same, the prefix stripped;
    the package itself (`from custom_components import pururu`) is "", which no row allows.
    """
    package = path.relative_to(PROJECT / CODE).with_suffix("").parts[:-1]
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(module_of(name) for alias in node.names
                         if (name := own(alias.name)) is not None)
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            base = package[:len(package) - (node.level - 1)]
            source = [*base, *node.module.split(".")] if node.module else list(base)
            found.update(module_of(".".join([*source, alias.name])) for alias in node.names)
        else:
            # Each name joined to its module, so `from custom_components import pururu`
            # counts too, as the package itself
            found.update(module_of(name) for alias in node.names
                         if (name := own(f"{node.module}.{alias.name}")) is not None)
    return found


def own(module: str) -> str | None:
    """An absolute module name of the integration without its package prefix, else None."""
    prefix = CODE.replace("/", ".")
    if module == prefix:
        return ""
    return module.removeprefix(f"{prefix}.") if module.startswith(f"{prefix}.") else None


def module_of(name: str) -> str:
    """The module a dotted name is: itself when a file or a package has it, else its parent."""
    path = PROJECT / CODE / name.replace(".", "/")
    if path.with_suffix(".py").exists() or (path / "__init__.py").exists():
        return name
    return name.rpartition(".")[0]


# The layer table (the spec's "Layers"): what each folder, or each module at the
# root, may import of the integration (homeassistant and the stdlib aside). A
# prefix ending in "." is a module inside that package, never the package itself:
# only setup/ reads a folder's __init__ (FEATURES, ASPECTS, DEVICE_KEYS).
ALLOWED: dict[str, tuple[str, ...]] = {
    "core": ("core.", "const"),
    # and its own package: features/<x>/, or itself for a module features/<x>.py
    "features": ("core.", "const", "features.cycle", "features.standing"),
    "aspects": ("core.", "const", "features.cycle", "aspects."),
    "device_keys": ("core.", "const", "features.cycle", "device_keys."),
    # Alert2's file and the alert lights read ProblemAlert; the alert lights lend Borrowable lights
    "outputs": ("core.", "const", "aspects.problem", "features.lights"),
    "setup": ("const", "core", "features", "aspects", "device_keys", "outputs", "setup"),
    "__init__": ("setup.", "const"),
    "config_flow": ("const",),
    "const": (),
    **{platform: ("core.runtime",) for platform in PLATFORMS},
}
# The table's named allowances for one module
ALSO: dict[str, tuple[str, ...]] = {
    "features/__init__": ("features.",),  # it lists FEATURES: every feature
    # the hand-written alerts' and the executable programs' device keys
    "device_keys/__init__": ("aspects.alerts", "aspects.programs"),
    # a reaction's then names an executable program (programs.executable) and starts its script (programs.script_id)
    "device_keys/reactions": ("aspects.programs",),
    # a button's program names an executable program and starts its script (programs.script_id)
    "features/buttons": ("aspects.programs",),
    # a goal's done is a meter (statistics.Meter) over the statistics aspect's periods
    "device_keys/goals": ("aspects.statistics",),
    # HA's entry points take the typed entry: hassfest's strict-typing check wants
    # it named *ConfigEntry, and PururuConfigEntry is core/runtime.py's, as for the platforms
    "__init__": ("core.runtime",),
}


def allows(prefix: str, name: str) -> bool:
    if prefix.endswith("."):
        return name.startswith(prefix)
    return name == prefix or name.startswith(f"{prefix}.")


def row_of(module: tuple[str, ...]) -> tuple[str, ...]:
    """What a module (its path's parts, no suffix) may import: its folder's row, or its own at the root."""
    allowed = ALLOWED[module[0]] + ALSO.get("/".join(module), ())
    if module[0] == "features" and len(module) > 1:
        allowed += (f"features.{module[1]}",)  # its own package
    return allowed


def test_each_module_imports_only_what_its_row_allows() -> None:
    wrong = []
    for path in sorted((PROJECT / CODE).rglob("*.py")):
        module = path.relative_to(PROJECT / CODE).with_suffix("").parts
        assert module[0] in ALLOWED, f"{'/'.join(module)}: no row in ALLOWED"
        allowed = row_of(module)
        wrong += [f"{'/'.join(module)}.py imports {name or 'the package itself'}"
                  for name in sorted(imports_of(path))
                  if not any(allows(prefix, name) for prefix in allowed)]
    assert not wrong, "\n".join(wrong)


UTILITY_METER = "homeassistant.components.utility_meter"


def absolute_imports_of(path: Path) -> set[str]:
    """The modules outside the integration a file imports, dotted (homeassistant.core)."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.add(node.module)
    return found


def test_only_the_statistics_aspect_imports_utility_meter() -> None:
    """The meters are written once: HA's utility meter is the statistics aspect's alone."""
    importing = {
        str(path.relative_to(PROJECT / CODE))
        for path in (PROJECT / CODE).rglob("*.py")
        if any(name == UTILITY_METER or name.startswith(f"{UTILITY_METER}.")
               for name in absolute_imports_of(path))
    }
    assert importing == {"aspects/statistics.py"}, importing


def test_the_root_holds_only_what_home_assistant_looks_up() -> None:
    """The entry points, the config flow, the constants and the platforms; the rest lives in a layer's folder."""
    root = {path.stem for path in (PROJECT / CODE).glob("*.py")}
    assert root == {"__init__", "config_flow", "const", *PLATFORMS}


def test_no_module_is_named_after_a_platform_ha_preloads() -> None:
    """HA imports <integration>.condition, .repairs… itself: a module by that name would be taken for one."""
    from homeassistant.loader import BASE_PRELOAD_PLATFORMS  # noqa: PLC0415
    root = PROJECT / CODE
    ours = {path.stem for path in root.glob("*.py")} | {
        path.parent.name for path in root.glob("*/__init__.py")}
    assert not (ours & set(BASE_PRELOAD_PLATFORMS)) - {"config_flow"}


TESTS = PROJECT / "tests"


# The modules outside tests/docs/ that may name docs/, from the tests folder: conftest.py
# marks tests/docs/, test_changes.py holds paths as data to classify and reads no file
DOCS_ALLOWED = {Path("conftest.py"), Path("test_changes.py")}
DOCSTRING_HOLDERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def docs_named_in(path: Path) -> list[str]:
    """The string constants of a file that are `docs` or start with `docs/`, its docstrings aside."""
    tree = ast.parse(path.read_text())
    docstrings = {
        id(node.body[0].value) for node in ast.walk(tree)
        if isinstance(node, DOCSTRING_HOLDERS) and node.body
        and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
    }
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings
            and (node.value == "docs" or node.value.startswith("docs/"))]


def reading_docs(folder: Path) -> list[str]:
    """Each module of a tests folder, outside its docs/, naming docs/: its path and what it names."""
    found = []
    for path in sorted(folder.rglob("*.py")):
        module = path.relative_to(folder)
        # test_code.py itself: the guard's own samples name docs/
        if module.parts[0] == "docs" or module in DOCS_ALLOWED or module == Path("test_code.py"):
            continue
        if named := docs_named_in(path):
            found.append(f"{module}: {', '.join(named)}")
    return found


def test_no_test_outside_tests_docs_reads_docs() -> None:
    """A test reading docs/ sits in tests/docs/, run by `pytest -m docs` and never by the default run."""
    found = reading_docs(TESTS)
    assert not found, "\n".join(found)


def guarded(folder: Path, modules: dict[str, str]) -> list[str]:
    """What the guard finds in a tests folder holding `modules` (path from the folder: code)."""
    for name, code in modules.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(code)
    return reading_docs(folder)


@pytest.mark.parametrize("code", [
    pytest.param('PAGE = PROJECT / "docs/features/door.mdx"\n', id="a page's path"),
    pytest.param('PAGES = PROJECT / "docs" / "develop"\n', id="a path built from segments"),
])
def test_the_guard_names_a_module_naming_docs(tmp_path: Path, code: str) -> None:
    [found] = guarded(tmp_path, {"test_door.py": code})
    assert found.startswith("test_door.py"), found


def test_the_guard_ignores_a_docstring(tmp_path: Path) -> None:
    """test_events.py names docs/concepts/events.mdx in a test's docstring only."""
    assert guarded(tmp_path, {"test_events.py": (TESTS / "test_events.py").read_text()}) == []


def test_the_guard_ignores_tests_docs(tmp_path: Path) -> None:
    assert guarded(tmp_path, {"docs/test_door.py": 'PAGE = "docs/features/door.mdx"\n'}) == []


def test_the_guard_allows_conftest_and_test_changes_alone(tmp_path: Path) -> None:
    """conftest.py marks tests/docs/; test_changes.py holds paths as data and reads no file."""
    paths = 'CHANGED = ["docs/features/door.mdx", "docs"]\n'
    assert guarded(tmp_path, {"conftest.py": (TESTS / "conftest.py").read_text(),
                              "test_changes.py": paths}) == []
    [found] = guarded(tmp_path, {"test_other.py": paths})
    assert found.startswith("test_other.py"), found
    assert DOCS_ALLOWED == {Path("conftest.py"), Path("test_changes.py")}
