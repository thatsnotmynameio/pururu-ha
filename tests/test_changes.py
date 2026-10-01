"""changes.py: the changed files decide which checks a pull request runs."""

import io

import pytest

import changes

ALL = {"build": True, "docs": True, "hacs": True}
NONE = {"build": False, "docs": False, "hacs": False}


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        pytest.param(["docs/features/door.mdx"],
                     {"build": False, "docs": True, "hacs": False}, id="a docs page"),
        pytest.param(["CLAUDE.md", "docs/plans/2026-10-01-x.md"], NONE, id="agent files only"),
        pytest.param(["docs/index.mdx", "noxfile.py"], ALL, id="a docs page and a file in no group"),
        pytest.param(["custom_components/pururu/features/buttons.py"],
                     {"build": True, "docs": True, "hacs": False}, id="code"),
        pytest.param(["custom_components/pururu/manifest.json"], ALL, id="manifest"),
        pytest.param([".github/workflows/build.yml"], ALL, id="a workflow"),
        pytest.param(["README.md"], {"build": False, "docs": False, "hacs": True}, id="README"),
        pytest.param(["CONCEPTS.md", "STRATEGY.md", "docs/ideation/x.html",
                      ".compound-engineering/x.md", "docs/superpowers/x.mdx"], NONE,
                     id="planning files"),
        pytest.param(["changes.py"], ALL, id="changes.py"),
        pytest.param([".github/dependabot.yml"], ALL, id="dependabot"),
        pytest.param(["SECURITY.md"], ALL, id="SECURITY.md"),
        pytest.param(["tests/test_changes.py"],
                     {"build": True, "docs": True, "hacs": False}, id="a test"),
        pytest.param([], ALL, id="no change"),
    ],
)
def test_needed(paths: list[str], expected: dict[str, bool]) -> None:
    assert changes.needed(paths) == expected


def test_main_runs_everything_off_a_pull_request(monkeypatch: pytest.MonkeyPatch,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("README.md\n"))
    assert changes.main(["changes.py", "push"]) == 0
    assert capsys.readouterr().out == "build=true\ndocs=true\nhacs=true\n"


def test_main_prints_one_line_per_check(monkeypatch: pytest.MonkeyPatch,
                                        capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("docs/index.mdx\n"))
    assert changes.main(["changes.py", "pull_request"]) == 0
    assert capsys.readouterr().out == "build=false\ndocs=true\nhacs=false\n"


def test_main_skips_blank_lines(monkeypatch: pytest.MonkeyPatch,
                                capsys: pytest.CaptureFixture[str]) -> None:
    """A blank line is no path: read as one, it would be in no group and run everything."""
    monkeypatch.setattr("sys.stdin", io.StringIO("\nCLAUDE.md\n\n  \n"))
    assert changes.main(["changes.py", "pull_request"]) == 0
    assert capsys.readouterr().out == "build=false\ndocs=false\nhacs=false\n"


def test_main_needs_an_event(capsys: pytest.CaptureFixture[str]) -> None:
    assert changes.main(["changes.py"]) == 2
    assert "Usage:" in capsys.readouterr().out
