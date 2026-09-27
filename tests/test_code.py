"""custom_components/pururu passes core's own tools at the pinned HA."""

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
