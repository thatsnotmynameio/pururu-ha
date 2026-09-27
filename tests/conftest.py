"""The pururu integration in the HA test plugin's instance; hassfest cached first."""

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

import fetch_hassfest

PROJECT = Path(__file__).resolve().parents[1]
# Every test starts here, in HA's configured time zone: a Wednesday, mid-month, 10:00,
# so the few hours a test simulates never cross a day, week, month or year by accident
START = (2026, 9, 16, 10, 0)


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session: pytest.Session) -> None:
    """Cache hassfest before the HA plugin blocks sockets (main process only)."""
    if not hasattr(session.config, "workerinput"):
        fetch_hassfest.ensure()


@pytest.fixture
def expected_lingering_timers() -> bool:
    """Running's delays and phases' `for` timers may still be pending when a test ends."""
    return True


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
