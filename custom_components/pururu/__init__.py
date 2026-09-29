"""pururu: floors, areas and devices configured in YAML, which the integration creates.

`pururu: floors:` and `areas:` map an ID to a floor or an area (places.py).
`pururu: devices:` maps a device key to its name and features (features/).
From the real entities and settings in a feature's block, the feature creates
the device's entities. One config entry owns every floor, area, device and entity.
"""

from collections.abc import Collection, Mapping, Sequence
import logging
from typing import Any, Literal

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntryState
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    ATTR_RESTORED,
    CONF_NAME,
    SERVICE_RELOAD,
    Platform,
)
from homeassistant.core import (
    Event,
    HomeAssistant,
    ServiceCall,
    callback,
    split_entity_id,
)
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.reload import async_integration_yaml_config
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from . import (
    alert2_alerts,
    alert_lights,
    catalogue,
    dashboard,
    events,
    generated,
    notifications,
    places,
    programs,
    reactions,
)
from .catalogue import builders
from .const import (
    CONF_AREA,
    CONF_AREAS,
    CONF_CONFIG,
    CONF_DEVICES,
    CONF_FLOORS,
    CONF_NOTIFY,
    CONF_PROGRAMS,
    CONF_REACTIONS,
    DATA_CONFIG,
    DOMAIN,
    ENTITY_PREFIX,
    PLATFORMS,
)
from .device_keys import DEVICE_KEYS
from .entity import PururuEntity
from .feature import Device
from .features import FEATURES, presets
from .features.alerts import ProblemAlert
from .features.lights import Borrowable
from .runtime import PururuConfigEntry
from .schema import CONFIG_SCHEMA as CONFIG_SCHEMA
from .texts import Texts, async_texts

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
    owned = _owned(hass, entry, devices)
    for key, config in devices.items():
        for entity in _creatable(
            hass, registry, *_build(hass, key, config, texts, owned)
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
        _event_devices(devices, created_by),
    )
    _place(hass, entry, devices)
    _remove_stale(hass, entry, set(devices))
    created = {str(entity.unique_id) for each in built.values() for entity in each}
    scripts, held, targets = _scripts(hass, devices, created)
    generated_scripts = await generated.async_sync(
        hass, entry, programs.KIND, scripts, held
    )
    # Where a message goes without a notify of its own
    notify = configured.get(CONF_CONFIG, {}).get(CONF_NOTIFY, [])
    automations, held_automations = _automations(
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
    watched = _watched_items(devices)
    await alert2_alerts.async_sync(hass, entry, _alert2_alerts(hass, built))
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


def _owned(
    hass: HomeAssistant, entry: PururuConfigEntry, devices: dict[str, dict[str, Any]]
) -> dict[str, str]:
    """The current entity IDs of the scripts and automations the entry generates, by ID."""
    items = _watched_items(devices)
    return {
        unique_id: entity_id
        for kind in (programs.KIND, reactions.KIND)
        for unique_id, entity_id in generated.owned(
            hass,
            entry,
            kind,
            (unique_id for domain, unique_id in items if domain == kind.domain),
        ).items()
    }


def _watched_items(devices: dict[str, dict[str, Any]]) -> set[tuple[str, str]]:
    """(domain, ID) of every script and automation the entry generates.

    Renamed, what watches it follows: a reaction's action, the statistics.
    """
    return {
        *(
            (programs.KIND.domain, programs.script_id(key, program))
            for key, config in devices.items()
            for program in config.get(CONF_PROGRAMS, {})
        ),
        *(
            (reactions.KIND.domain, reactions.automation_id(key, reaction))
            for key, config in devices.items()
            for reaction in config.get(CONF_REACTIONS, {})
        ),
    }


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


def _event_devices(
    devices: dict[str, dict[str, Any]], created_by: Mapping[str, list[Entity]]
) -> list[events.Watched]:
    """Each device with its created entities: current entity ID → key, its unique ID after pururu_<device>_."""
    return [
        events.Watched(
            key=key,
            name=devices[key][CONF_NAME],
            entities={
                entity.entity_id: str(entity.unique_id).removeprefix(
                    f"{ENTITY_PREFIX}_{key}_"
                )
                for entity in created
            },
        )
        for key, created in created_by.items()
    ]


def _build(
    hass: HomeAssistant,
    key: str,
    config: dict[str, Any],
    texts: Texts,
    owned: Mapping[str, str],
) -> tuple[list[tuple[PururuEntity, set[str]]], dict[str, str]]:
    """Every entity of the device's features, with the unique IDs of the device's entities it follows.

    Each feature sees the device in its own namespace; what it takes through
    <capability>_from, or refers to, is in the owning feature's. Also the
    entity ID of each entity some entity watches (`follows`), by unique ID: the
    settings may never build it, and then only this names it. `owned` are the
    entity IDs of the scripts and automations the entry generates, by ID.
    """
    referable = catalogue.referable(key, config)
    built: list[tuple[PururuEntity, set[str]]] = []
    watched: dict[str, str] = {}
    for name, feature in builders().items():
        if name not in config:
            continue
        device = Device(key=key, name=config[CONF_NAME], namespace=feature.namespace)
        inputs, required = _inputs(hass, key, config, name, referable, owned)
        # Only a feature offering ready-made alerts has them: a program or a
        # reaction may be keyed `alerts`
        ready_made = (
            presets.build(hass, device, feature, config[name], texts)
            if feature.alerts
            else []
        )
        for entity in (*feature.build(hass, device, config[name], inputs), *ready_made):
            follows = set()
            for reference in entity.follows:
                owner, entity_key, platform = referable[reference]
                follows.add(unique_id := owner.object_id(entity_key))
                watched[unique_id] = owner.current_entity_id(hass, platform, entity_key)
            built.append(
                (entity, {*map(device.object_id, entity.sources), *required, *follows})
            )
    return built, watched


def _inputs(
    hass: HomeAssistant,
    key: str,
    config: dict[str, Any],
    name: str,
    referable: dict[str, tuple[Device, str, Platform]],
    owned: Mapping[str, str],
) -> tuple[dict[str, str], set[str]]:
    """What builder `name` gets in `inputs`, and the unique IDs of what it requires.

    A feature: the current entity IDs of what it takes through <capability>_from
    and of what it refers to. A device key (DEVICE_KEYS): the entity IDs of the
    scripts and automations the entry generates, by ID: its statistics never
    watch one it doesn't.
    """
    if name in DEVICE_KEYS:
        return dict(owned), set()
    feature = FEATURES[name]
    inputs: dict[str, str] = {}
    required: set[str] = set()
    for capability in feature.requires:
        source = FEATURES[config[name][f"{capability}_from"]]
        provider = Device(key=key, name=config[CONF_NAME], namespace=source.namespace)
        entity_key = source.provides[capability]
        inputs[capability] = provider.current_entity_id(
            hass, source.entity_keys[entity_key], entity_key
        )
        required.add(provider.object_id(entity_key))
    for reference in feature.refers(config[name]) if feature.refers else ():
        owner, entity_key, platform = referable[reference]
        inputs[reference] = owner.current_entity_id(hass, platform, entity_key)
    return inputs, required


def _creatable(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    built: list[tuple[PururuEntity, set[str]]],
    watched: dict[str, str],
) -> list[PururuEntity]:
    """The entities whose ID is free and whose sources are created too; the rest logged.

    A source the settings don't build (an entity key a feature can create, but
    not with this device's settings) can only be watched: `watched` names it.
    """
    built_ids = {str(entity.unique_id) for entity, _ in built}
    missing: dict[str, str] = {}  # unique ID -> entity ID, of what isn't created
    kept: list[tuple[PururuEntity, set[str]]] = []
    for entity, sources in built:
        if unbuilt := sorted(
            watched.get(source, source) for source in sources if source not in built_ids
        ):
            _LOGGER.error(
                "%s watches %s, which this device's settings don't create "
                "(turn it on, or watch another entity); not creating it",
                entity.entity_id,
                ", ".join(unbuilt),
            )
            missing[str(entity.unique_id)] = entity.entity_id
            continue
        if (holder := _holder(hass, registry, entity)) is None:
            kept.append((entity, sources))
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


def _place(
    hass: HomeAssistant, entry: PururuConfigEntry, devices: dict[str, dict[str, Any]]
) -> None:
    """Put each created device in its area; an area HA refused is logged.

    The configuration wins over an area picked in the UI; a device without
    `area`, or whose area is not created, keeps the one it has.
    """
    areas = ar.async_get(hass)
    registry = dr.async_get(hass)
    for key, config in devices.items():
        if (area_id := config.get(CONF_AREA)) is None:
            continue
        device = registry.async_get_device_by_identifier((DOMAIN, key), entry.entry_id)
        if device is None:  # none of its entities is created
            continue
        if areas.async_get_area(area_id) is None:
            _LOGGER.error(
                "Device %s is not placed: its area %s is not created", key, area_id
            )
        elif device.area_id != area_id:
            registry.async_update_device(device.id, area_id=area_id)


def _remove_stale(
    hass: HomeAssistant, entry: PururuConfigEntry, keys: set[str]
) -> None:
    """Remove what the entry has and the configuration no longer creates."""
    registry = er.async_get(hass)
    # With its platform: an entity key that moved to another platform keeps its unique ID
    wanted = {
        (platform, entity.unique_id)
        for platform, entities in entry.runtime_data.items()
        for entity in entities
    }
    for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (registered.domain, registered.unique_id) not in wanted:
            registry.async_remove(registered.entity_id)
    devices = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        if not any(
            domain == DOMAIN and key in keys for domain, key in device.identifiers
        ):
            devices.async_remove_device(device.id)


def _automations(
    hass: HomeAssistant,
    devices: dict[str, dict[str, Any]],
    created: set[str],
    scripts: Collection[str],
    held_scripts: Collection[str],
    notify: Sequence[str],
) -> tuple[list[generated.Item], set[str]]:
    """An automation per reaction of every device; one that can't work is logged.

    One watching an entity not created, or starting a program whose script
    isn't generated, isn't generated. Also the IDs of those held with their
    program. `notify` is config's: where a message without its own goes.
    """
    registry = er.async_get(hass)
    automations: list[generated.Item] = []
    held: set[str] = set()
    for key, config in devices.items():
        for reaction_key, reaction in config.get(CONF_REACTIONS, {}).items():
            automation_id = reactions.automation_id(key, reaction_key)
            watched, entity_id = _watched(
                hass, devices, key, automation_id, reaction, created
            )
            if not watched:
                continue
            startable, script = _started(
                registry, key, automation_id, reaction, scripts
            )
            if not startable:
                if programs.script_id(key, reaction["then"]) in held_scripts:
                    held.add(automation_id)
                continue
            automations.append(
                generated.Item(
                    unique_id=automation_id,
                    config=reactions.automation(
                        key,
                        config[CONF_NAME],
                        reaction_key,
                        reaction,
                        entity_id,
                        script,
                        reaction.get(CONF_NOTIFY, notify),
                    ),
                )
            )
    return automations, held


def _watched(
    hass: HomeAssistant,
    devices: dict[str, dict[str, Any]],
    key: str,
    automation_id: str,
    reaction: dict[str, Any],
    created: set[str],
) -> tuple[bool, str | None]:
    """Whether the reaction can watch what it names, and the entity ID it watches.

    A pururu entity not created can't be, logged; `at` and `sun` watch none.
    """
    if (when := reaction.get("when")) is None:
        return True, reaction.get("entity")
    owner_key = reaction.get("device", key)
    owner, entity_key, platform = catalogue.referable(owner_key, devices[owner_key])[
        when
    ]
    if owner.object_id(entity_key) not in created:
        _LOGGER.error(
            "automation.%s follows %s, which is not created; not generating it",
            automation_id,
            owner.entity_id(platform, entity_key),
        )
        return False, None
    return True, owner.current_entity_id(hass, platform, entity_key)


def _started(
    registry: er.EntityRegistry,
    key: str,
    automation_id: str,
    reaction: dict[str, Any],
    scripts: Collection[str],
) -> tuple[bool, str | None]:
    """Whether the reaction can start its program, and its script's current entity ID.

    A script not generated can't be started, logged; without `then`, none is.
    """
    if (then := reaction.get("then")) is None:
        return True, None
    script_id = programs.script_id(key, then)
    if script_id not in scripts:
        _LOGGER.error(
            "automation.%s runs script.%s, which is not generated; not generating it",
            automation_id,
            script_id,
        )
        return False, None
    # Registered by the scripts' sync
    return True, registry.async_get_entity_id(
        programs.KIND.domain, programs.KIND.domain, script_id
    )


def _scripts(
    hass: HomeAssistant, devices: dict[str, dict[str, Any]], created: set[str]
) -> tuple[list[generated.Item], set[str], set[str]]:
    """A script per program of every device, in the device's area; one that can't act is logged.

    Also the IDs of the scripts held while an entity they act on is disabled
    (their registry entries stay, as the user set them), and the entity IDs the
    generated scripts act on.
    """
    registry = er.async_get(hass)
    scripts: list[generated.Item] = []
    held: set[str] = set()
    targets: set[str] = set()
    for key, config in devices.items():
        referable = catalogue.referable(key, config)
        for program_key, program in config.get(CONF_PROGRAMS, {}).items():
            script_id = programs.script_id(key, program_key)
            entity_ids = _acted_on(
                hass, registry, referable, script_id, program, created
            )
            if entity_ids == "held":
                held.add(script_id)
                continue
            if entity_ids is None:
                continue
            targets.update(entity_ids.values())
            scripts.append(
                generated.Item(
                    unique_id=script_id,
                    config=programs.script(
                        key, config[CONF_NAME], program_key, program, entity_ids
                    ),
                    area=config.get(CONF_AREA),
                )
            )
    return scripts, held, targets


def _acted_on(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    referable: dict[str, tuple[Device, str, Platform]],
    script_id: str,
    program: dict[str, Any],
    created: set[str],
) -> dict[str, str] | Literal["held"] | None:
    """Each entity key the program acts on -> its current entity ID.

    None, logged, when one isn't created: the program is dropped. "held",
    logged, when all are created but one is disabled: the program is held, to
    come back as the user set it once the entity is enabled again. The entry is
    reloaded when an entity a generated script acts on is disabled (pururu's
    registry listener, `changed`), and when a disabled one is enabled again
    (HA's own).
    """
    entity_ids: dict[str, str] = {}
    for _, key in programs.targets(program):
        owner, entity_key, platform = referable[key]
        entity_id = owner.current_entity_id(hass, platform, entity_key)
        if owner.object_id(entity_key) not in created:
            _LOGGER.error(
                "script.%s follows %s, which is not created; not generating it",
                script_id,
                entity_id,
            )
            return None
        entity_ids[key] = entity_id
    for entity_id in entity_ids.values():
        if (registered := registry.async_get(entity_id)) is not None and (
            registered.disabled
        ):
            _LOGGER.error(
                "script.%s acts on %s, which is disabled; not generating it",
                script_id,
                entity_id,
            )
            return "held"
    return entity_ids


def _alert2_alerts(
    hass: HomeAssistant, built: dict[Platform, list[Entity]]
) -> list[dict[str, Any]]:
    """An Alert2 alert per created alert with notify, hand-written or ready-made.

    Named as HA shows it: its device's name and its own, translated or not.
    """
    alerts: list[dict[str, Any]] = []
    for entity in built[Platform.BINARY_SENSOR]:
        if not isinstance(entity, ProblemAlert) or entity.notify is None:
            continue
        state = hass.states.get(entity.entity_id)
        name = state.attributes.get(ATTR_FRIENDLY_NAME) if state else None
        alerts.append(
            alert2_alerts.alert(
                str(entity.unique_id),
                entity.entity_id,
                str(name or entity.entity_id),
                entity.priority,
                entity.notify,
            )
        )
    return alerts
