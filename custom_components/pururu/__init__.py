"""pururu: floors, areas and devices configured in YAML, which the integration creates.

`pururu: floors:` and `areas:` map an ID to a floor or an area (places.py).
`pururu: devices:` maps a device key to its name and features (features/).
From the real entities and settings in a feature's block, the feature creates
the device's entities. One config entry owns every floor, area, device and entity.
"""

from collections.abc import Mapping
import logging
from typing import Any, Literal

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntryState
from homeassistant.const import SERVICE_RELOAD, Platform
from homeassistant.core import (
    Event,
    HomeAssistant,
    ServiceCall,
    callback,
    split_entity_id,
)
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
from .schema import CONFIG_SCHEMA as CONFIG_SCHEMA
from .texts import async_texts

_LOGGER = logging.getLogger(__name__)


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

    # Whether a reload is already scheduled: a burst of disables reloads once
    reloading = False

    @callback
    def changed(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        """One of the entry's entities or generated items got a new ID, or a program's target was disabled: build again.

        A rename is followed: of a pururu entity, or of a script or automation
        it generates (a reaction's action and the statistics would watch an ID
        that no longer is). A program acting on an entity just disabled is dropped (`_acted_on`),
        and a light or alert the alert lights follow is left out, once
        for a burst of them: HA reloads the entry itself once an entity is
        enabled again, but not when one is disabled (config_entries.py leaves
        that to the entity, which merely clears its own state). No other
        disable or enable concerns what is built here (`_rebuild_for`).
        """
        nonlocal reloading
        data = event.data
        if data["action"] != "update":
            return
        registered = registry.async_get(data["entity_id"])
        if registered is None:
            return
        why = _rebuild_for(
            entry.entry_id, registered, data["changes"], watched, targets | lent
        )
        if why is None or (why == "disabled" and reloading):
            return
        reloading = True
        hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, changed)
    )
    return True


def _rebuild_for(
    entry_id: str,
    registered: er.RegistryEntry,
    changes: Mapping[str, Any],
    watched: set[tuple[str, str]],
    targets: set[str],
) -> Literal["renamed", "disabled"] | None:
    """Why this registry update needs the entry built again, if it does.

    Renamed: one of the entry's entities, or a script or automation it
    generates (a reaction starts one, the statistics watch them).
    Disabled: an entity a generated script acts on, or a light or an alert the
    alert lights follow, just now (the old value
    of `disabled_by` is None).
    """
    ours = registered.config_entry_id == entry_id
    if "entity_id" in changes:
        generated_item = (registered.platform, registered.unique_id) in watched
        return "renamed" if ours or generated_item else None
    if (
        ours
        and "disabled_by" in changes
        and changes["disabled_by"] is None
        and registered.disabled
        and registered.entity_id in targets
    ):
        return "disabled"
    return None


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
