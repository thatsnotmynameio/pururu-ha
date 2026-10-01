"""The pururu integration in the HA test plugin's instance; hassfest cached first."""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

import fetch_hassfest

PROJECT = Path(__file__).resolve().parents[1]
DOCS_TESTS = Path(__file__).resolve().parent / "docs"
# Every test starts here, in HA's configured time zone: a Wednesday, mid-month, 10:00,
# so the few hours a test simulates never cross a day, week, month or year by accident
START = (2026, 9, 16, 10, 0)


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session: pytest.Session) -> None:
    """Cache hassfest before the HA plugin blocks sockets (main process only)."""
    if not hasattr(session.config, "workerinput"):
        fetch_hassfest.ensure()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """The tests under tests/docs/ read the pages: marked docs, run by `pytest -m docs` alone."""
    for item in items:
        if item.path.resolve().is_relative_to(DOCS_TESTS):
            item.add_marker(pytest.mark.docs)


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The carrier's next delay (a detected program's on_delay/off_delay, its phases' too) may still be pending when a test ends."""
    return True


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    """A configuration folder per test: pururu writes pururu/automations/automations.yaml into it."""
    return hass_tmp_config_dir


@pytest.fixture
def ha(hass: HomeAssistant, enable_custom_integrations: None,
       monkeypatch: pytest.MonkeyPatch, freezer: Any) -> HomeAssistant:
    """`hass` at START, with custom_components/pururu where HA's loader looks.

    The plugin has already imported its own testing custom_components package,
    so the loader looks only there; the repo's folder is put in front of it.
    """
    freezer.move_to(datetime(*START, tzinfo=dt_util.get_time_zone(hass.config.time_zone)))
    import custom_components  # noqa: PLC0415 - the plugin's, already imported

    monkeypatch.setattr(custom_components, "__path__",
                        [str(PROJECT / "custom_components"), *custom_components.__path__])
    return hass


@pytest.fixture(autouse=True)
def no_step_failed(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Fail a test in which a setup step or the listener failed unexpectedly, in a fixture or the test (a test expecting it clears caplog)."""
    yield
    failed = [
        record.getMessage()
        for phase in ("setup", "call")
        for record in caplog.get_records(phase)
        if record.name.endswith(".lifecycle")
        and record.getMessage().startswith(("Step ", "Listener "))
    ]
    assert not failed, failed
