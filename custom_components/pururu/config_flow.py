"""The one config entry that owns the configured devices, created from YAML."""

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class PururuFlow(ConfigFlow, domain=DOMAIN):
    """Import only: the devices live in YAML, there is nothing to ask."""

    VERSION = 1

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Create the entry the first time the configuration declares a device."""
        return self.async_create_entry(title="Pururu", data={})
