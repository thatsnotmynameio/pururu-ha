"""Every builder of a device, and the entity keys they can create."""

from collections.abc import Iterator
from typing import Any

from homeassistant.const import CONF_NAME, Platform

from ..core.feature import Device, Feature, qualified
from ..device_keys import DEVICE_KEYS
from ..features import FEATURES


def builders() -> dict[str, Feature]:
    """Everything that builds entities of a device: its features, then the device keys.

    Read at every call, so a feature added to FEATURES is seen. Only FEATURES
    count as a device's features.
    """
    return {**FEATURES, **DEVICE_KEYS}


def entity_keys(device: dict[str, Any]) -> Iterator[tuple[str, str, Platform]]:
    """(builder, entity key, platform) of every entity the device's features and device keys can create."""
    for name, feature in builders().items():
        if name not in device:
            continue
        yield from (
            (name, entity_key, platform)
            for entity_key, platform in feature.entity_keys.items()
        )
        if (configured := feature.configured) is not None:
            yield from ((name, entity_key, configured) for entity_key in device[name])
        if (items := feature.items) is not None:
            yield from (
                (name, item.key(suffix), platform)
                for item in items(device[name])
                for suffix, platform in feature.per_item.items()
            )


def referable(
    key: str, config: dict[str, Any]
) -> dict[str, tuple[Device, str, Platform]]:
    """Every entity key the device's features can create, in its namespace.

    Each maps to the device as its feature sees it, the entity key there and its
    platform: enough for its current entity ID and its unique ID.
    """
    return {
        qualified(builders()[name].namespace, entity_key): (
            Device(
                key=key, name=config[CONF_NAME], namespace=builders()[name].namespace
            ),
            entity_key,
            platform,
        )
        for name, entity_key, platform in entity_keys(config)
    }
