"""Every builder of a device, and the entity keys they can create."""

from collections.abc import Iterator
from typing import Any

from homeassistant.const import CONF_NAME, Platform

from ..core.feature import ALERTS_KEY, Device, Feature, preset_keys, presets_of
from ..core.resolve import Index, Target
from ..core.roles import Actions, Configured, Items
from ..device_keys import DEVICE_KEYS
from ..features import FEATURES


def builders() -> dict[str, Feature]:
    """Everything that builds entities of a device: its features, then the device keys.

    Read at every call, so a feature added to FEATURES is seen. Only FEATURES
    count as a device's features.
    """
    return {**FEATURES, **DEVICE_KEYS}


def keys(
    device: dict[str, Any],
) -> Iterator[tuple[str, str, Platform, str | None, str | None]]:
    """(builder, local entity key, platform, by, item) of every entity the device's builders can create.

    `by` is "alerts" for a ready-made alert's key; `item` the item owning an Items key.
    """
    for name, feature in builders().items():
        if name not in device:
            continue
        ready_made = preset_keys(presets_of(feature))
        yield from (
            (
                name,
                entity_key,
                platform,
                ALERTS_KEY if entity_key in ready_made else None,
                None,
            )
            for entity_key, platform in feature.entity_keys.items()
        )
        if (configured := feature.role(Configured)) is not None:
            yield from (
                (name, entity_key, configured.platform, None, None)
                for entity_key in device[name]
            )
        if (items := feature.role(Items)) is not None:
            yield from (
                (name, item.key(suffix), platform, None, item.slug)
                for item in items.of(device[name])
                for suffix, platform in items.keys.items()
            )


def targets(key: str, config: dict[str, Any]) -> dict[str, Target]:
    """Every entity key device `key` can create, qualified, and what it is."""
    found: dict[str, Target] = {}
    for name, entity_key, platform, by, item in keys(config):
        feature = builders()[name]
        device = Device(key=key, name=config[CONF_NAME], namespace=feature.namespace)
        actions = feature.role(Actions)
        found[device.qualified(entity_key)] = Target(
            device=device,
            key=device.qualified(entity_key),
            platform=platform,
            builder=name,
            by=by,
            item=item,
            actions=actions.services if actions else (),
        )
    return found


def index(devices: dict[str, dict[str, Any]]) -> Index:
    """Every device's targets, by device key."""
    return {key: targets(key, config) for key, config in devices.items()}
