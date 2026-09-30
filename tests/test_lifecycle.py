"""The entry's life: the steps after the platforms, their guard, the listener."""

from typing import Any
from unittest.mock import patch

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest

from helpers import DOMAIN, module, reload, setup

SWITCH = {"name": "Piscina", "switches": {"pump": {"entity": "switch.pool_pump", "name": "Bomba"}}}
LIGHT = {"name": "Luzes", "lights": {"teto": {"entity": "light.teto", "name": "Teto"}}}


async def test_the_steps_run_in_order(ha: HomeAssistant) -> None:
    """Events, devices, the generated files, Alert2, the alert lights, the dashboard: as the spec's flow says."""
    names = [name for name, _ in module("setup.lifecycle").STEPS]
    assert names == ["events", "devices", "generate", "alert2", "alert lights", "dashboard"]


async def test_the_steps_read_the_builders_and_one_index(ha: HomeAssistant) -> None:
    """Built carries every device's targets and the builders: no step builds them again."""
    seen: list[Any] = []

    async def step(hass: HomeAssistant, entry: Any, built: Any, targets: set[str]) -> None:
        seen.append(built)

    lifecycle = module("setup.lifecycle")
    with patch.object(lifecycle, "STEPS", (("spy", step),)):
        assert await setup(ha, {"pool": SWITCH, "lights": LIGHT})
    [built] = seen
    assert set(built.index) == {"pool", "lights"}
    assert built.index["pool"]["switch_pump"].builder == "switches"
    assert built.builders == module("setup.catalogue").builders()


async def test_a_step_that_raises_leaves_the_entry_loaded(
    ha: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """The dashboard raising doesn't fail the setup: logged, the entry loaded, a reload loads it again."""
    with patch.object(module("outputs.dashboard"), "async_setup", side_effect=RuntimeError("boom")):
        assert await setup(ha, {"pool": SWITCH})
        [entry] = ha.config_entries.async_entries(DOMAIN)
        assert entry.state is ConfigEntryState.LOADED
        assert ha.states.get("switch.pururu_pool_switch_pump") is not None
        assert "Step dashboard failed" in caplog.text
        await ha.config_entries.async_reload(entry.entry_id)
        await ha.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
    caplog.clear()  # expected: the autouse fixture would fail on it


async def test_a_failing_first_step_leaves_the_others_and_the_listener(
    ha: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """The events failing first: the generated scripts, the dashboard and the rename rule still come."""
    clean = {"name": "Limpar", "sequence": [{"turn_on": "switch_pump"}]}
    with patch.object(module("outputs.events"), "async_setup", side_effect=RuntimeError("boom")):
        assert await setup(ha, {"pool": {**SWITCH, "programs": {"clean": clean}}})
    assert "Step events failed" in caplog.text
    caplog.clear()  # expected: the autouse fixture would fail on it
    [entry] = ha.config_entries.async_entries(DOMAIN)
    assert entry.data["scripts"] == ["pururu_pool_program_clean"]
    assert "pururu" in ha.data[LOVELACE_DATA].dashboards
    with patch.object(ha.config_entries, "async_schedule_reload") as reloading:
        er.async_get(ha).async_update_entity(
            "script.pururu_pool_program_clean", new_entity_id="script.limpar"
        )
        await ha.async_block_till_done()
    reloading.assert_called_once()


async def test_a_failing_listener_leaves_the_entry_loaded(
    ha: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """The rename listener raising doesn't fail the setup: logged, the entry loaded with its entities."""
    with patch.object(module("setup.listener"), "async_listen", side_effect=RuntimeError("boom")):
        assert await setup(ha, {"pool": SWITCH})
    [entry] = ha.config_entries.async_entries(DOMAIN)
    assert entry.state is ConfigEntryState.LOADED
    assert ha.states.get("switch.pururu_pool_switch_pump") is not None
    assert "Listener failed" in caplog.text
    caplog.clear()  # expected: the autouse fixture would fail on it


async def test_a_setup_failing_after_its_platforms_recovers_on_reload(
    ha: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Built raising once the platforms are set up: they're unloaded, so a reload, the cause fixed, applies the configuration."""
    pump = "switch.pururu_pool_switch_pump"
    with patch.object(module("setup.lifecycle"), "Built", side_effect=RuntimeError("boom")):
        assert await setup(ha, {"pool": SWITCH})
    [entry] = ha.config_entries.async_entries(DOMAIN)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert "Error setting up entry Pururu for pururu" in caplog.text
    removed = ha.states.get(pump)
    assert removed is not None
    assert removed.attributes["restored"]  # HA's placeholder: the entity is gone
    switches = {**SWITCH["switches"], "filter": {"entity": "switch.pool_filter", "name": "Filtro"}}
    await reload(ha, {"pool": {**SWITCH, "switches": switches}})
    assert entry.state is ConfigEntryState.LOADED
    for entity_id in (pump, "switch.pururu_pool_switch_filter"):
        added = ha.states.get(entity_id)
        assert added is not None, entity_id
        assert not added.attributes.get("restored"), entity_id
    assert "has already been setup" not in caplog.text


async def test_a_failing_unload_of_a_failed_setup_keeps_its_error(
    ha: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Unloading the platforms raising too: logged, and the setup's own error is the one HA reports."""
    lifecycle = module("setup.lifecycle")
    with (
        patch.object(lifecycle, "Built", side_effect=RuntimeError("boom")),
        patch.object(ha.config_entries, "async_unload_platforms", side_effect=ValueError("stuck")),
    ):
        assert await setup(ha, {"pool": SWITCH})
    [entry] = ha.config_entries.async_entries(DOMAIN)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    [unloading] = [r for r in caplog.records if r.name.endswith(".lifecycle")]
    assert unloading.getMessage() == "Unloading the platforms of a failed setup failed"
    assert unloading.exc_info is not None
    assert isinstance(unloading.exc_info[1], ValueError)
    [failed] = [r for r in caplog.records if r.getMessage().startswith("Error setting up entry")]
    assert failed.exc_info is not None
    assert isinstance(failed.exc_info[1], RuntimeError)


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
