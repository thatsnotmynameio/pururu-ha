# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Cache Home Assistant's hassfest, from the source of the HA version the tests pin.

Usage:
    uv run fetch_hassfest.py

tests/conftest.py calls ensure(); tests/test_code.py runs `python -m script.hassfest`
from the folder it returns. Only script/ and homeassistant/ of the source archive
are kept, in .hassfest/ (git-ignored).

VERSION is the homeassistant version pyproject.toml's
pytest-homeassistant-custom-component pins; change VERSION and SHA256 together
when upgrading HA (test_fetch_hassfest.py checks they match).
"""

import hashlib
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import urllib.request

VERSION = "2026.9.3"
SHA256 = "e2e3badd3476a19162e9de16c4e9a29205c05b26b119114c78d771ce069e3d20"
URL = f"https://github.com/home-assistant/core/archive/refs/tags/{VERSION}.tar.gz"
CACHE = Path(__file__).resolve().parent / ".hassfest"
KEEP = ("script/", "homeassistant/")


def ensure(cache: Path = CACHE, url: str = URL, sha256: str = SHA256) -> Path:
    """The cached folder holding script/hassfest, fetched first if this version isn't cached."""
    version = cache / "VERSION"
    if (
        (cache / "script" / "hassfest" / "__main__.py").is_file()
        and version.is_file()
        and version.read_text().strip() == VERSION
    ):
        return cache
    with tempfile.TemporaryDirectory() as work:
        archive_path = Path(work) / "core.tar.gz"
        with urllib.request.urlopen(url) as response, archive_path.open("wb") as out:
            shutil.copyfileobj(response, out)
        actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        if actual != sha256:
            raise ValueError(f"HA {VERSION} source sha256 is {actual}, expected {sha256}")
        top = f"core-{VERSION}/"
        staged = Path(work) / "cache"
        with tarfile.open(archive_path) as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.name.startswith(top) and member.name.removeprefix(top).startswith(KEEP)
            ]
            for member in members:
                member.name = member.name.removeprefix(top)
            archive.extractall(staged, members=members, filter="data")
        (staged / "VERSION").write_text(f"{VERSION}\n")
        shutil.rmtree(cache, ignore_errors=True)
        cache.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(staged, cache)
    return cache


def main() -> int:
    """Fetch it by hand."""
    print(f"hassfest of HA {VERSION} cached in {ensure()}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
