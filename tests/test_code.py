"""custom_components/pururu passes core's own tools at the pinned HA."""

import ast
import os
from pathlib import Path
import re
import subprocess
import sys

import fetch_hassfest
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


# The core (L0), core/: contracts and shared helpers, importing nothing but each other and const
CORE = "core"
PLATFORMS = {"sensor", "binary_sensor", "switch", "light"}


def imports_of(path: Path) -> set[str]:
    """The integration's modules a file imports, dotted from the package root (features.alerts)."""
    package = path.relative_to(PROJECT / CODE).with_suffix("").parts[:-1]
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        base = package[:len(package) - (node.level - 1)]
        if node.module:
            found.add(".".join([*base, *node.module.split(".")]))
        else:
            found.update(".".join([*base, alias.name]) for alias in node.names)
    return found


def test_the_core_imports_only_the_core() -> None:
    for path in (PROJECT / CODE / CORE).rglob("*.py"):
        imported = imports_of(path)
        assert all(name == "const" or name.startswith(f"{CORE}.") or name == CORE
                   for name in imported), (path.name, imported)


# Each folder never imports these, until B enforces the whole layer table
NEVER = {
    "features": {"aspects", "device_keys", "outputs", "setup"},
    "aspects": {"device_keys", "outputs", "setup"},
    "device_keys": {"outputs", "setup"},
    "outputs": {"device_keys", "setup"},
}


def test_each_folder_imports_no_later_layer() -> None:
    for folder, forbidden in NEVER.items():
        for path in (PROJECT / CODE / folder).rglob("*.py"):
            wrong = {name for name in imports_of(path) if name.split(".")[0] in forbidden}
            assert not wrong, (str(path.relative_to(PROJECT / CODE)), wrong)


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


def test_the_platforms_import_only_runtime() -> None:
    for name in PLATFORMS:
        assert imports_of(PROJECT / CODE / f"{name}.py") <= {f"{CORE}.runtime"}, name


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
