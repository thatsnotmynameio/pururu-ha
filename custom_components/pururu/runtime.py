"""What an entry of pururu carries at runtime: the entities each platform adds."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.helpers.entity import Entity

type PururuConfigEntry = ConfigEntry[dict[Platform, list[Entity]]]
