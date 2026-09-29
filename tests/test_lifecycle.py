"""The entry's life: the steps after the platforms, their guard, the listener."""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest

from helpers import DOMAIN, module, setup

SWITCH = {"name": "Piscina", "switches": {"pump": {"entity": "switch.pool_pump", "name": "Bomba"}}}


async def test_the_steps_run_in_order(ha: HomeAssistant) -> None:
    """Events, devices, the generated files, Alert2, the alert lights, the dashboard: as the spec's flow says."""
    names = [name for name, _ in module("lifecycle").STEPS]
    assert names == ["events", "devices", "generate", "alert2", "alert lights", "dashboard"]


async def test_a_step_that_raises_leaves_the_entry_loaded(
    ha: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """The dashboard raising doesn't fail the setup: logged, the entry loaded, a reload loads it again."""
    with patch.object(module("dashboard"), "async_setup", side_effect=RuntimeError("boom")):
        assert await setup(ha, {"pool": SWITCH})
        [entry] = ha.config_entries.async_entries(DOMAIN)
        assert entry.state is ConfigEntryState.LOADED
        assert ha.states.get("switch.pururu_pool_switch_pump") is not None
        assert "Step dashboard failed" in caplog.text
        await ha.config_entries.async_reload(entry.entry_id)
        await ha.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
    caplog.clear()  # expected: the autouse fixture would fail on it


async def test_renaming_a_ready_made_notification_reloads(ha: HomeAssistant) -> None:
    """Every generated item the entry tracks follows one rule: renamed, the entry builds again."""
    washer = {
        "name": "Washer",
        "appliance": {
            "power": "sensor.washer_power",
            "running": {"threshold": 4, "on_delay": 1, "off_delay": 1},
            "notifications": {"finished": None},
        },
    }
    assert await setup(ha, {"washer": washer}, config={"notify": "notify.phone"})
    registry = er.async_get(ha)
    with patch.object(ha.config_entries, "async_schedule_reload") as reloading:
        registry.async_update_entity(
            "automation.pururu_washer_appliance_notification_finished",
            new_entity_id="automation.roupa_pronta",
        )
        await ha.async_block_till_done()
    reloading.assert_called_once()
