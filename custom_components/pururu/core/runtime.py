"""What an entry of pururu carries at runtime: the entities each platform adds, and what its steps read."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

type PururuConfigEntry = ConfigEntry[dict[Platform, list[Entity]]]


@dataclass(frozen=True, kw_only=True)
class Built:
    """What the prelude built, before the steps: every step reads it, none changes it."""

    # The validated pururu: block
    house: Mapping[str, Any]
    # The translations' common texts
    texts: Mapping[str, str]
    # What the platforms added, by platform
    entities: Mapping[Platform, tuple[Entity, ...]]
    # Each device's created entities: an entity's key comes from the device that built it
    by_device: Mapping[str, tuple[Entity, ...]]
    # Their unique IDs
    created: frozenset[str]


# An output after the platforms; it adds to `targets` the entity IDs whose disabling
# rebuilds the entry, as soon as it knows them: a later failure keeps them
type Step = Callable[
    [HomeAssistant, PururuConfigEntry, Built, set[str]], Awaitable[None]
]
