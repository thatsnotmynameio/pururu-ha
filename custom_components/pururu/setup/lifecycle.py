"""What HA's entry points do: apply the YAML, set the entry up, unload it, remove it."""

import logging

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntryState
from homeassistant.const import SERVICE_RELOAD, Platform
from homeassistant.core import HomeAssistant, ServiceCall, split_entity_id
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.reload import async_integration_yaml_config
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from ..const import (
    CONF_AREAS,
    CONF_DEVICES,
    CONF_FLOORS,
    DATA_CONFIG,
    DOMAIN,
    PLATFORMS,
)
from ..core import generated
from ..core.entity import PururuEntity
from ..core.runtime import Built, PururuConfigEntry, Step
from ..core.texts import async_texts
from ..device_keys import goals
from ..outputs import (
    alert2_alerts,
    alert_lights,
    dashboard,
    devices as device_steps,
    events,
    places,
)
from . import build, catalogue, generate, listener

_LOGGER = logging.getLogger(__name__)

# What to do when a failed setup's platforms weren't all taken back: HA's
# errors say whether anything was left
UNLOAD_RAISED = (
    "Unloading the platforms of a failed setup raised; if a reload then logs "
    "'has already been setup', restart Home Assistant"
)
NOT_UNLOADED = (
    "Unloading the platforms of a failed setup left some (see Home Assistant's "
    "errors above): after 'Config entry was never loaded!' nothing was left, and a "
    "reload sets the entry up; if a reload logs 'has already been setup', restart "
    "Home Assistant"
)

# The outputs after the platforms, in order: the events once the entities have their
# IDs; what the goals track, disabled, rebuilds the entry; the devices placed and
# what is stale removed; the scripts before the automations that start them; Alert2
# and the alert lights once their alerts and lights are created; the dashboard last,
# as it shows them all
STEPS: tuple[tuple[str, Step], ...] = (
    ("events", events.async_step),
    ("goals", goals.async_step),
    ("devices", device_steps.async_step),
    ("generate", generate.async_step),
    ("alert2", alert2_alerts.async_step),
    ("alert lights", alert_lights.async_step),
    ("dashboard", dashboard.async_step),
)


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
    fire their changes. The registry listener comes after the steps, guarded
    as one. Before the steps, a failure from the platforms on unloads them,
    then raises: the entry is SETUP_ERROR without them, and a reload sets it
    up again.
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
    entities: dict[Platform, list[Entity]] = {platform: [] for platform in PLATFORMS}
    # Each device's created entities: an entity's key comes from the device that built it
    created_by: dict[str, list[Entity]] = {key: [] for key in devices}
    texts = await async_texts(hass)
    owned = generate.owned(hass, entry, devices)
    index = catalogue.index(devices)
    # Every device built before any is created: an entity may follow another
    # device's
    built_all: list[tuple[PururuEntity, set[str]]] = []
    watched: dict[str, str] = {}
    for key, config in devices.items():
        device_built, device_watched = build.build(
            hass, key, config, index, texts, owned
        )
        built_all.extend(device_built)
        watched.update(device_watched)
    for entity in build.creatable(hass, registry, built_all, watched):
        entities[Platform(split_entity_id(entity.entity_id)[0])].append(entity)
        created_by[entity.device_key].append(entity)
    entry.runtime_data = entities
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        # Once added, each entity has its current ID, renamed in the UI or not
        built = Built(
            house=configured,
            builders=catalogue.builders(),
            index=index,
            texts=texts,
            entities={platform: tuple(each) for platform, each in entities.items()},
            by_device={key: tuple(each) for key, each in created_by.items()},
            created=frozenset(
                str(entity.unique_id) for each in entities.values() for entity in each
            ),
        )
        targets: set[str] = set()
        for name, step in STEPS:
            try:
                await step(hass, entry, built, targets)
            except Exception:
                # Guarded, not raised: the entry stays loaded with its entities
                _LOGGER.exception("Step %s failed", name)
        try:
            listener.async_listen(
                hass, entry, (generated.SCRIPTS, generated.AUTOMATIONS), targets
            )
        except Exception:
            # Guarded as a step
            _LOGGER.exception("Listener failed")
    except BaseException:
        # HA unloads a non-loaded entry without async_unload_entry: platforms
        # left set up would refuse the entry at every reload. What reaches here
        # after the forward: Built failing, or a cancellation, in a step too (a
        # reload called by an automation that stops; the steps guard Exception
        # only). The delivered cancel is used up, so the unload runs; the
        # original is re-raised
        await _async_unload_platforms(hass, entry)
        raise
    return True


async def _async_unload_platforms(
    hass: HomeAssistant, entry: PururuConfigEntry
) -> None:
    """Take back the platforms of a setup that failed after forwarding them; never raises.

    HA unloads each platform on its own, so a partial forward (a cancelled
    one) is fine: a platform HA never loaded counts as unloaded; one loaded
    but never given the entry is logged by HA (`Config entry was never
    loaded!`) and counts as not unloaded, though nothing of it is left.
    """
    try:
        unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    except Exception:
        _LOGGER.exception(UNLOAD_RAISED)
        return
    if not unloaded:
        _LOGGER.error(NOT_UNLOADED)


async def async_unload_entry(hass: HomeAssistant, entry: PururuConfigEntry) -> bool:
    """Remove the entities; a reload builds them again."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: PururuConfigEntry) -> None:
    """Delete the floors and areas the entry managed, its reactions' and notifications' automations, programs' scripts and Alert2 alerts."""
    places.async_remove(hass, entry.data)
    for kind in (generated.AUTOMATIONS, generated.SCRIPTS):
        await generated.async_remove(hass, entry, kind)
    await alert2_alerts.async_remove(hass)
