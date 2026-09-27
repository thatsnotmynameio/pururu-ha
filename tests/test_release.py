"""release.py: the manifest's semantic version decides what gets released."""

import json
from pathlib import Path

import pytest

import release

TAGS = ["v0.1.0", "v0.2.0", "v0.2.1", "not-a-version", "v1.0"]


@pytest.mark.parametrize("version", ["0.1.0", "1.0.0", "10.20.30"])
def test_parse_accepts_major_minor_patch(version: str) -> None:
    assert release.parse(version) == tuple(int(part) for part in version.split("."))


@pytest.mark.parametrize("version", ["1.0", "v1.0.0", "01.0.0", "1.0.0-beta", "1.0.0.0", ""])
def test_parse_refuses_anything_else(version: str) -> None:
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        release.parse(version)


def test_first_release() -> None:
    assert release.decide("0.1.0", []) == "v0.1.0"


def test_a_released_version_is_not_released_again() -> None:
    assert release.decide("0.2.1", TAGS) is None


def test_a_bump_is_released() -> None:
    assert release.decide("0.3.0", TAGS) == "v0.3.0"


def test_a_version_below_the_latest_release_is_refused() -> None:
    with pytest.raises(ValueError, match="below the latest release v0.2.1"):
        release.decide("0.1.5", TAGS)


def test_tags_that_are_not_versions_are_ignored() -> None:
    assert release.decide("0.2.2", ["v1.0", "latest", "v0.2.1"]) == "v0.2.2"


def test_manifest_version(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"domain": "pururu", "version": "0.4.0"}))
    assert release.manifest_version(manifest) == "0.4.0"


def test_the_integrations_version_is_semver() -> None:
    """What HACS and HA show is what gets tagged: it must parse."""
    release.parse(release.manifest_version())


def test_main_check_and_next(monkeypatch: pytest.MonkeyPatch,
                             capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(release, "manifest_version", lambda: "0.3.0")
    monkeypatch.setattr(release, "git_tags", lambda: TAGS)
    assert release.main(["release.py", "next"]) == 0
    assert capsys.readouterr().out.strip() == "v0.3.0"
    assert release.main(["release.py", "check"]) == 0
    assert "v0.3.0" in capsys.readouterr().out


def test_main_fails_on_a_lower_version(monkeypatch: pytest.MonkeyPatch,
                                      capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(release, "manifest_version", lambda: "0.1.5")
    monkeypatch.setattr(release, "git_tags", lambda: TAGS)
    assert release.main(["release.py", "check"]) == 1
    assert "below the latest release" in capsys.readouterr().out


def test_main_needs_a_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert release.main(["release.py"]) == 2
