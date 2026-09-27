"""pururu: floors, areas and devices configured in YAML, which the integration creates.

`pururu: floors:` and `areas:` map an ID to a floor or an area (places.py).
`pururu: devices:` maps a device key to its name and features (features/).
From the real entities and settings in a feature's block, the feature creates
the device's entities. One config entry owns every floor, area, device and entity.
"""

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_RESTORED, CONF_NAME, SERVICE_RELOAD, Platform
from homeassistant.core import (
    Event,
    HomeAssistant,
    ServiceCall,
    callback,
    split_entity_id,
)
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.reload import async_integration_yaml_config
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from . import places
from .const import CONF_AREAS, CONF_DEVICES, CONF_FLOORS, DATA_CONFIG, DOMAIN, PLATFORMS
from .entity import PururuEntity
from .feature import Device
from .features import FEATURES

_LOGGER = logging.getLogger(__name__)

type PururuConfigEntry = ConfigEntry[dict[Platform, list[Entity]]]


def _device(value: Any) -> dict[str, Any]:
    """A device: a name, at least one feature, and every <capability>_from resolved."""
    schema: dict[Any, Any] = {
        vol.Required(CONF_NAME): cv.string,
        **{vol.Optional(name): feature.schema for name, feature in FEATURES.items()},
    }
    device: dict[str, Any] = vol.Schema(schema)(value)
    names = [name for name in FEATURES if name in device]
    if not names:
        raise vol.Invalid(
            f"a device needs at least one feature ({', '.join(FEATURES)})"
        )
    for name in names:
        for capability in FEATURES[name].requires:
            source = device[name][f"{capability}_from"]
            if source not in names or capability not in FEATURES[source].provides:
                raise vol.Invalid(
                    f"{name}: {capability}_from must name a feature of this device "
                    f"that provides {capability}"
                )
    return device


# The features are read when a configuration is validated, not at import
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(
            {
                # Schemas of their own: ALLOW_EXTRA would skip a key that isn't a slug
                vol.Optional(CONF_FLOORS, default={}): vol.Schema(
                    {cv.slug: places.FLOOR_SCHEMA}
                ),
                vol.Optional(CONF_AREAS, default={}): vol.Schema(
                    {cv.slug: places.AREA_SCHEMA}
                ),
                vol.Optional(CONF_DEVICES, default={}): {cv.slug: _device},
            },
            places.floors_exist,
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Keep the configuration for the entry, and apply it again on reload."""

    async def reload(call: ServiceCall) -> None:
        reloaded = await async_integration_yaml_config(hass, DOMAIN)
        if reloaded is None:  # invalid: HA logged why; keep the running devices
            return
        await _async_apply(hass, reloaded, reloading=True)

    async_register_admin_service(hass, DOMAIN, SERVICE_RELOAD, reload)
    await _async_apply(hass, config, reloading=False)
    return True


async def _async_apply(
    hass: HomeAssistant, config: ConfigType, *, reloading: bool
) -> None:
    """Keep the configuration; set the entry up again, or create it the first time.

    On a reload, an existing entry is always set up again, whatever its current
    state (e.g. after a SETUP_ERROR), unless the user disabled it. At start-up,
    only an already loaded entry is reloaded; HA sets a fresh one up itself.
    """
    hass.data[DATA_CONFIG] = config.get(DOMAIN, {})
    entries = hass.config_entries.async_entries(DOMAIN)
    if entries:
        entry = entries[0]
        if reloading:
            if not entry.disabled_by:
                await hass.config_entries.async_reload(entry.entry_id)
        elif entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_reload(entry.entry_id)
    elif any(
        hass.data[DATA_CONFIG].get(key)
        for key in (CONF_FLOORS, CONF_AREAS, CONF_DEVICES)
    ):
        # Not awaited at start-up: HA sets the entry up once the flow creates it
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data={}
            )
        )


async def async_setup_entry(hass: HomeAssistant, entry: PururuConfigEntry) -> bool:
    """Make floors and areas follow the configuration, then build every device.

    Floors and areas come first: devices will be placed in them.
    """
    configured = hass.data.get(DATA_CONFIG, {})
    managed = places.async_sync(
        hass,
        configured.get(CONF_FLOORS, {}),
        configured.get(CONF_AREAS, {}),
        entry.data,
    )
    hass.config_entries.async_update_entry(entry, data=managed)
    registry = er.async_get(hass)
    devices = configured.get(CONF_DEVICES, {})
    built: dict[Platform, list[Entity]] = {platform: [] for platform in PLATFORMS}
    for key, config in devices.items():
        device = Device(key=key, name=config[CONF_NAME])
        for entity in _creatable(hass, registry, device, _build(hass, device, config)):
            built[Platform(split_entity_id(entity.entity_id)[0])].append(entity)
    entry.runtime_data = built
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _remove_stale(hass, entry, set(devices))

    @callback
    def renamed(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        """One of the entry's entities got a new ID: build again, following it."""
        data = event.data
        if data["action"] != "update" or "entity_id" not in data["changes"]:
            return
        registered = registry.async_get(data["entity_id"])
        if registered is not None and registered.config_entry_id == entry.entry_id:
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, renamed)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PururuConfigEntry) -> bool:
    """Remove the entities; a reload builds them again."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: PururuConfigEntry) -> None:
    """Delete the floors and areas the entry managed."""
    places.async_remove(hass, entry.data)


def _build(
    hass: HomeAssistant, device: Device, config: dict[str, Any]
) -> list[tuple[PururuEntity, set[str]]]:
    """Every entity of the device's features, with the metrics of the device it follows."""
    built: list[tuple[PururuEntity, set[str]]] = []
    for name, feature in FEATURES.items():
        if name not in config:
            continue
        inputs: dict[str, str] = {}
        required: set[str] = set()
        for capability in feature.requires:
            source = FEATURES[config[name][f"{capability}_from"]]
            metric = source.provides[capability]
            inputs[capability] = device.current_entity_id(
                hass, source.metrics[metric], metric
            )
            required.add(metric)
        built.extend(
            (entity, {*entity.sources, *required})
            for entity in feature.build(hass, device, config[name], inputs)
        )
    return built


def _creatable(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    device: Device,
    built: list[tuple[PururuEntity, set[str]]],
) -> list[PururuEntity]:
    """The entities whose ID is free and whose sources are created too; the rest logged."""
    missing: dict[str, str] = {}  # unique ID -> entity ID, of what isn't created
    kept: list[tuple[PururuEntity, set[str]]] = []
    for entity, sources in built:
        if (holder := _holder(hass, registry, entity)) is None:
            kept.append((entity, {device.object_id(metric) for metric in sources}))
            continue
        _LOGGER.error(
            "%s is already taken by %s; not creating it", entity.entity_id, holder
        )
        missing[str(entity.unique_id)] = entity.entity_id
    lost = True
    while lost:  # until nothing left follows what isn't created
        lost = False
        for entity, sources in list(kept):
            if gone := sorted(
                missing[source] for source in sources if source in missing
            ):
                _LOGGER.error(
                    "%s follows %s, which is not created; not creating it",
                    entity.entity_id,
                    ", ".join(gone),
                )
                missing[str(entity.unique_id)] = entity.entity_id
                kept.remove((entity, sources))
                lost = True
    return [entity for entity, _ in kept]


def _holder(
    hass: HomeAssistant, registry: er.EntityRegistry, entity: Entity
) -> str | None:
    """Who else has this entity's ID; None when it is free or already this entity's.

    Checked by unique ID first: a renamed entity is still ours wherever the
    user moved it to, even if another integration since took its old ID.
    """
    domain = split_entity_id(entity.entity_id)[0]
    if entity.unique_id is not None:
        if registry.async_get_entity_id(domain, DOMAIN, entity.unique_id) is not None:
            return None
    registered = registry.async_get(entity.entity_id)
    if registered is not None:
        return f"the {registered.platform} integration"
    state = hass.states.get(entity.entity_id)
    if state is not None and not state.attributes.get(ATTR_RESTORED):
        return "an entity without a unique ID"
    return None


def _remove_stale(
    hass: HomeAssistant, entry: PururuConfigEntry, keys: set[str]
) -> None:
    """Remove what the entry has and the configuration no longer creates."""
    registry = er.async_get(hass)
    wanted = {
        entity.unique_id
        for entities in entry.runtime_data.values()
        for entity in entities
    }
    for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registered.unique_id not in wanted:
            registry.async_remove(registered.entity_id)
    devices = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        if not any(
            domain == DOMAIN and key in keys for domain, key in device.identifiers
        ):
            devices.async_remove_device(device.id)
