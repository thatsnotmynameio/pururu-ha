"""Home Assistant in process, with the repo's pururu where its loader looks, at a frozen start."""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest

from steps import Home

REPO = Path(__file__).resolve().parents[1]
# Every story starts here, in Home Assistant's time zone: a Wednesday, mid-month, 10:00
START = (2026, 9, 16, 10, 0)


@pytest.fixture
def expected_lingering_timers() -> bool:
    """A program's next delay may still be pending when a story ends."""
    return True


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    """A configuration folder per test: pururu writes its files into it."""
    return hass_tmp_config_dir


@pytest.fixture
def home(hass: HomeAssistant, enable_custom_integrations: None, hass_storage: dict[str, Any],
         monkeypatch: pytest.MonkeyPatch, freezer: Any) -> Iterator[Home]:
    """Home Assistant at START, pururu installed as a custom component.

    configuration.yaml is whatever the Home shows, for the whole test, so every
    reload Home Assistant makes reads the house and pururu's files. The test
    fails when an alert turned on or a notification went out that it didn't cause.
    """
    freezer.move_to(datetime(*START, tzinfo=dt_util.get_time_zone(hass.config.time_zone)))
    import custom_components  # noqa: PLC0415 - the repo's folder, through pythonpath

    monkeypatch.setattr(custom_components, "__path__",
                        [str(REPO / "custom_components"), *custom_components.__path__])
    found = Home(hass, freezer)
    monkeypatch.setattr("homeassistant.config.load_yaml_config_file",
                        lambda *_args, **_kwargs: found.configuration())
    yield found
    assert not found.calm.unexpected(), found.calm.unexpected()


@pytest.fixture
async def house(home: Home) -> Home:
    """The reference house, set up from its calm states."""
    await home.setup_house()
    return home


@pytest.fixture(autouse=True)
def no_step_failed(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Fail a test in which pururu logged that a setup step or its listener failed."""
    yield
    failed = [record.getMessage()
              for phase in ("setup", "call")
              for record in caplog.get_records(phase)
              if record.name.startswith("custom_components.pururu")
              and record.getMessage().startswith(("Step ", "Listener "))]
    assert not failed, failed
