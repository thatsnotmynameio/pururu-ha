"""fetch_hassfest.py, offline: a local archive stands in for GitHub."""

import hashlib
import io
from pathlib import Path
import tarfile

from homeassistant.const import __version__ as HA_VERSION
import pytest

import fetch_hassfest

TOP = f"core-{fetch_hassfest.VERSION}"


def archive(tmp_path: Path) -> tuple[str, str]:
    """A source-shaped archive; returns its file:// URL and sha256."""
    path = tmp_path / "core.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for name in (f"{TOP}/script/hassfest/__main__.py", f"{TOP}/homeassistant/const.py",
                     f"{TOP}/tests/conftest.py"):
            data = b"# x\n"
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path.as_uri(), hashlib.sha256(path.read_bytes()).hexdigest()


def test_keeps_only_script_and_homeassistant(tmp_path: Path) -> None:
    url, sha256 = archive(tmp_path)
    cache = tmp_path / "cache"
    assert fetch_hassfest.ensure(cache, url, sha256) == cache
    assert (cache / "script/hassfest/__main__.py").is_file()
    assert (cache / "homeassistant/const.py").is_file()
    assert not (cache / "tests").exists()
    assert (cache / "VERSION").read_text().strip() == fetch_hassfest.VERSION


def test_checksum_mismatch_leaves_no_cache(tmp_path: Path) -> None:
    url, _ = archive(tmp_path)
    cache = tmp_path / "cache"
    with pytest.raises(ValueError, match="sha256"):
        fetch_hassfest.ensure(cache, url, "0" * 64)
    assert not cache.exists()


def test_cached_version_is_not_fetched_again(tmp_path: Path) -> None:
    url, sha256 = archive(tmp_path)
    cache = tmp_path / "cache"
    fetch_hassfest.ensure(cache, url, sha256)
    fetch_hassfest.ensure(cache, (tmp_path / "gone.tar.gz").as_uri(), sha256)
    assert (cache / "script/hassfest/__main__.py").is_file()


def test_version_is_the_pinned_home_assistant() -> None:
    """hassfest validates against the same HA the tests run."""
    assert fetch_hassfest.VERSION == HA_VERSION
