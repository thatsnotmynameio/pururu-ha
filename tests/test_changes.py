""".github/scripts/changes.py: the changed files decide which checks a pull request runs."""

import io
from pathlib import Path
import re

import pytest

import changes

ALL = {"build": True, "docs": True, "hacs": True, "tools": True}
NONE = {"build": False, "docs": False, "hacs": False, "tools": False}
DOCS = NONE | {"docs": True}
CODE = NONE | {"build": True, "docs": True}


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        pytest.param(["docs/features/door.mdx"], DOCS, id="a docs page"),
        pytest.param(["CLAUDE.md", "docs/plans/2026-10-01-x.md"], NONE, id="agent files only"),
        pytest.param(["docs/index.mdx", "noxfile.py"], ALL, id="a docs page and a file in no group"),
        pytest.param(["custom_components/pururu/features/buttons.py"], CODE, id="code"),
        pytest.param(["custom_components/pururu/manifest.json"], CODE | {"hacs": True},
                     id="manifest"),
        pytest.param(["tools/dispatcher/dispatcher.py", "tools/dispatcher/README.md"],
                     NONE | {"tools": True}, id="a tool"),
        pytest.param(["pyproject.toml"], CODE | {"tools": True}, id="pyproject.toml"),
        pytest.param(["uv.lock"], CODE | {"tools": True}, id="uv.lock"),
        pytest.param([".github/workflows/build.yml"], ALL, id="a workflow"),
        pytest.param(["docs.json", "package.json", "pnpm-lock.yaml"], DOCS,
                     id="the docs site's files"),
        pytest.param(["docs/notes.md"], ALL, id="a docs file that is no page"),
        pytest.param(["README.md"], NONE | {"hacs": True}, id="README"),
        pytest.param(["CONCEPTS.md", "STRATEGY.md", "docs/ideation/x.html",
                      ".compound-engineering/x.md", "docs/superpowers/x.mdx"], NONE,
                     id="planning files"),
        pytest.param([".github/scripts/changes.py"], ALL, id="the classifier itself"),
        pytest.param([".github/dependabot.yml"], ALL, id="dependabot"),
        pytest.param(["SECURITY.md"], ALL, id="SECURITY.md"),
        pytest.param(["tests/test_changes.py"], CODE, id="a test"),
        pytest.param([], ALL, id="no change"),
    ],
)
def test_needed(paths: list[str], expected: dict[str, bool]) -> None:
    assert changes.needed(paths) == expected


def test_main_runs_everything_off_a_pull_request(monkeypatch: pytest.MonkeyPatch,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("README.md\n"))
    assert changes.main(["changes.py", "push"]) == 0
    assert capsys.readouterr().out == "build=true\ndocs=true\nhacs=true\ntools=true\n"


def test_main_prints_one_line_per_check(monkeypatch: pytest.MonkeyPatch,
                                        capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("docs/index.mdx\n"))
    assert changes.main(["changes.py", "pull_request"]) == 0
    assert capsys.readouterr().out == "build=false\ndocs=true\nhacs=false\ntools=false\n"


def test_main_skips_blank_lines(monkeypatch: pytest.MonkeyPatch,
                                capsys: pytest.CaptureFixture[str]) -> None:
    """A blank line is no path: read as one, it would be in no group and run everything."""
    monkeypatch.setattr("sys.stdin", io.StringIO("\nCLAUDE.md\n\n  \n"))
    assert changes.main(["changes.py", "pull_request"]) == 0
    assert capsys.readouterr().out == "build=false\ndocs=false\nhacs=false\ntools=false\n"


def test_main_needs_an_event(capsys: pytest.CaptureFixture[str]) -> None:
    assert changes.main(["changes.py"]) == 2
    assert "Usage:" in capsys.readouterr().out


def test_ci_lists_every_check_when_the_classifier_changes() -> None:
    """ci.yml marks every check true without running changes.py when it changes: none may be left out."""
    ci = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text()
    [listed] = re.findall(r"printf '((?:\w+=true\\n)+)'", ci)
    assert [line.removesuffix("=true") for line in listed.split("\\n") if line] == list(changes.NEEDS)
