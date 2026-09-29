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
