"""What HA's entry points do: apply the YAML, set the entry up, unload it, remove it."""

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntryState
from homeassistant.const import SERVICE_RELOAD, Platform
from homeassistant.core import HomeAssistant, ServiceCall, split_entity_id
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.reload import async_integration_yaml_config
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from . import (
    alert2_alerts,
    alert_lights,
    build,
    dashboard,
    devices as device_steps,
    events,
    generate,
    generated,
    listener,
    notifications,
    places,
    programs,
    reactions,
)
from .const import (
    CONF_AREAS,
    CONF_CONFIG,
    CONF_DEVICES,
    CONF_FLOORS,
    CONF_NOTIFY,
    DATA_CONFIG,
    DOMAIN,
    PLATFORMS,
)
from .features.alerts import ProblemAlert
from .features.lights import Borrowable
from .runtime import PururuConfigEntry
from .texts import async_texts


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Keep the configuration for the entry, and apply it again on reload."""

    async def reload(call: ServiceCall) -> None:
        reloaded = await async_integration_yaml_config(hass, DOMAIN)
        if reloaded is None:  # invalid: HA logged why; keep the running devices
            return
        await async_apply(hass, reloaded, reloading=True)

    async_register_admin_service(hass, DOMAIN, SERVICE_RELOAD, reload)
    await async_apply(hass, config, reloading=False)
    return True


async def async_apply(
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

    Floors and areas come first: devices will be placed in them. The reactions'
    and the ready-made notifications' automations, the programs' scripts and
    Alert2's alerts come after the entities: they watch and act on the ones
    created. The programs' scripts come
    before the reactions' automations: a reaction starts one. The alert lights start
    after them: their alerts and lights are created. The dashboard comes last:
    it shows them all. The events are set up once the entities are added: they
    fire their changes.
    """
    configured = hass.data.get(DATA_CONFIG, {})
    managed = places.async_sync(
        hass,
        configured.get(CONF_FLOORS, {}),
        configured.get(CONF_AREAS, {}),
        entry.data,
    )
    hass.config_entries.async_update_entry(entry, data={**entry.data, **managed})
    registry = er.async_get(hass)
    devices = configured.get(CONF_DEVICES, {})
    built: dict[Platform, list[Entity]] = {platform: [] for platform in PLATFORMS}
    # Each device's created entities: an entity's key comes from the device that built it
    created_by: dict[str, list[Entity]] = {key: [] for key in devices}
    texts = await async_texts(hass)
    owned = generate.owned(hass, entry, devices)
    for key, config in devices.items():
        for entity in build.creatable(
            hass, registry, *build.build(hass, key, config, texts, owned)
        ):
            built[Platform(split_entity_id(entity.entity_id)[0])].append(entity)
            created_by[key].append(entity)
    entry.runtime_data = built
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Once added, each entity has its current ID, renamed in the UI or not
    events.async_setup(
        hass,
        entry,
        configured.get(events.CONF_EVENTS, []),
        events.watched(devices, created_by),
    )
    device_steps.place(hass, entry, devices)
    device_steps.remove_stale(hass, entry, set(devices))
    created = {str(entity.unique_id) for each in built.values() for entity in each}
    scripts, held, targets = generate.scripts(hass, devices, created)
    generated_scripts = await generated.async_sync(
        hass, entry, programs.KIND, scripts, held
    )
    # Where a message goes without a notify of its own
    notify = configured.get(CONF_CONFIG, {}).get(CONF_NOTIFY, [])
    automations, held_automations = generate.automations(
        hass, devices, created, generated_scripts, held, notify
    )
    await generated.async_sync(
        hass, entry, reactions.KIND, automations, held_automations
    )
    await generated.async_sync(
        hass,
        entry,
        notifications.KIND,
        notifications.items(hass, devices, created, texts, notify),
    )
    watched = generate.watched_items(devices)
    await alert2_alerts.async_sync(hass, entry, alert2_alerts.items(hass, built))
    lights_settings = alert_lights.settings(configured)
    lent = alert_lights.async_setup(
        hass,
        entry,
        lights_settings,
        alert_lights.light_ids(lights_settings, devices),
        [
            entity
            for entity in built[Platform.BINARY_SENSOR]
            if isinstance(entity, ProblemAlert)
        ],
        [entity for entity in built[Platform.LIGHT] if isinstance(entity, Borrowable)],
    )
    dashboard.async_setup(hass, entry)
    listener.async_listen(hass, entry, watched, targets | lent)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PururuConfigEntry) -> bool:
    """Remove the entities; a reload builds them again."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: PururuConfigEntry) -> None:
    """Delete the floors and areas the entry managed, its reactions' and notifications' automations, programs' scripts and Alert2 alerts."""
    places.async_remove(hass, entry.data)
    await generated.async_remove(hass, entry, reactions.KIND)
    await generated.async_remove(hass, entry, notifications.KIND)
    await generated.async_remove(hass, entry, programs.KIND)
    await alert2_alerts.async_remove(hass)
