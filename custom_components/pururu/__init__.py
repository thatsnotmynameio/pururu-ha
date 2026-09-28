"""pururu: floors, areas and devices configured in YAML, which the integration creates.

`pururu: floors:` and `areas:` map an ID to a floor or an area (places.py).
`pururu: devices:` maps a device key to its name and features (features/).
From the real entities and settings in a feature's block, the feature creates
the device's entities. One config entry owns every floor, area, device and entity.
"""

from collections import ChainMap
from collections.abc import Collection, Iterator, Mapping
from functools import partial
import logging
from typing import Any, Literal

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigEntryState
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
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.reload import async_integration_yaml_config
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from . import alert2_alerts, dashboard, generated, places, programs, reactions
from .const import (
    CONF_ALERTS,
    CONF_AREA,
    CONF_AREAS,
    CONF_DEVICES,
    CONF_FLOORS,
    CONF_PROGRAMS,
    CONF_REACTIONS,
    DATA_CONFIG,
    DOMAIN,
    PLATFORMS,
)
from .device_keys import DEVICE_KEYS
from .entity import PururuEntity
from .feature import Device, Feature, preset_keys, qualified
from .features import FEATURES, presets
from .features.alerts import ProblemAlert

_LOGGER = logging.getLogger(__name__)

type PururuConfigEntry = ConfigEntry[dict[Platform, list[Entity]]]

# Everything that builds entities of a device: its features, then the device keys
# creating some (their statistics). Only FEATURES count as a device's feature. A
# view, not a copy: it iterates FEATURES first (a ChainMap iterates its last map
# first), and sees any feature added to it
BUILDERS: ChainMap[str, Feature] = ChainMap(DEVICE_KEYS, FEATURES)


def _device(value: Any) -> dict[str, Any]:
    """A device: a name, maybe an area, at least one feature, every reference resolved.

    Every <capability>_from names a feature of this device that provides it,
    every entity key a feature refers to is another feature's, a program's step
    acts on another feature's entity key that takes the action, and a real
    entity is in one configured feature of the device at most.
    """
    schema: dict[Any, Any] = {
        vol.Required(CONF_NAME): cv.string,
        vol.Optional(CONF_AREA): cv.slug,
        vol.Optional(CONF_REACTIONS): reactions.SCHEMA,
        vol.Optional(CONF_PROGRAMS): programs.SCHEMA,
        **{
            vol.Optional(name): partial(presets.validate, feature)
            for name, feature in FEATURES.items()
        },
    }
    device: dict[str, Any] = vol.Schema(schema)(value)
    names = [name for name in FEATURES if name in device]
    if not names:
        raise vol.Invalid(
            f"a device needs at least one feature ({', '.join(FEATURES)})"
        )
    _capabilities_provided(device, names)
    _references_resolved(device, names)
    _no_alert_watches_an_alert(device, names)
    _real_entities_distinct(device, names)
    _reactions_on_this_device(device)
    _programs_on_this_device(device)
    return device


def _capabilities_provided(device: dict[str, Any], names: list[str]) -> None:
    """Refuse a <capability>_from that names no feature of the device providing it."""
    for name in names:
        for capability in FEATURES[name].requires:
            source = device[name][f"{capability}_from"]
            if source not in names or capability not in FEATURES[source].provides:
                raise vol.Invalid(
                    f"{name}: {capability}_from must name a feature of this device "
                    f"that provides {capability}"
                )


def _real_entities_distinct(device: dict[str, Any], names: list[str]) -> None:
    """Refuse a real entity in two configured features: a relay is a switch or a light."""
    owners: dict[str, str] = {}  # real entity -> the configured feature that has it
    for name in names:
        if FEATURES[name].configured is None:
            continue
        for item in device[name].values():
            # A configured key need not stand for a real entity (an alert)
            if (entity := item.get("entity")) is None:
                continue
            if owners.setdefault(entity, name) != name:
                raise vol.Invalid(f"{name}: {entity} is already in {owners[entity]}")


def _references_resolved(device: dict[str, Any], names: list[str]) -> None:
    """Refuse a reference that isn't another feature's entity key."""
    # Every entity key the device can create, in its namespace -> its feature
    owners = {
        qualified(BUILDERS[name].namespace, entity_key): name
        for name, entity_key, _ in _entity_keys(device)
    }
    for name in names:
        feature = FEATURES[name]
        if feature.refers is None:
            continue
        for key in feature.refers(device[name]):
            if owners.get(key, name) == name:
                raise vol.Invalid(
                    f"{name}: {key} is not an entity key of another feature "
                    "of this device"
                )


def _no_alert_watches_an_alert(device: dict[str, Any], names: list[str]) -> None:
    """Refuse a hand-written alert whose `when` is another feature's ready-made alert."""
    alerts_feature = FEATURES[CONF_ALERTS]
    if CONF_ALERTS not in names or alerts_feature.refers is None:
        return
    ready_made = {
        qualified(FEATURES[name].namespace, alert)
        for name in names
        for alert in preset_keys(FEATURES[name].alerts)
    }
    for key in alerts_feature.refers(device[CONF_ALERTS]):
        if key in ready_made:
            raise vol.Invalid(
                f"{CONF_ALERTS}: {key} is an alert: an alert can't watch another"
            )


def _reactions_on_this_device(device: dict[str, Any]) -> None:
    """Refuse a reaction's `when` or `then` that isn't the device's own.

    `when` without `device` names an entity key of the device, and `then` one of
    its programs.
    """
    keys = {
        qualified(BUILDERS[name].namespace, entity_key)
        for name, entity_key, _ in _entity_keys(device)
    }
    for key, reaction in device.get(CONF_REACTIONS, {}).items():
        then = reaction.get("then")
        if then is not None and then not in device.get(CONF_PROGRAMS, {}):
            raise vol.Invalid(
                f"reactions: {key}: {then} is not a program of this device"
            )
        if "device" in reaction or (when := reaction.get("when")) is None:
            continue
        if when not in keys:
            raise vol.Invalid(
                f"reactions: {key}: {when} is not an entity key of this device"
            )


def _programs_on_this_device(device: dict[str, Any]) -> None:
    """Refuse a step on what isn't a feature's entity key of the device taking its action."""
    owners = {
        qualified(BUILDERS[name].namespace, entity_key): name
        for name, entity_key, _ in _entity_keys(device)
    }
    for program in device.get(CONF_PROGRAMS, {}).values():
        for action, key in programs.targets(program):
            if key not in owners:
                raise vol.Invalid(
                    f"programs: {key} is not an entity key of another feature "
                    "of this device"
                )
            if action not in BUILDERS[owners[key]].actions:
                raise vol.Invalid(f"programs: {key} does not take {action}")


def _entity_keys(device: dict[str, Any]) -> Iterator[tuple[str, str, Platform]]:
    """(builder, entity key, platform) of every entity the device's features and device keys can create."""
    for name, feature in BUILDERS.items():
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


def _areas_exist(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse a device in an area the configuration doesn't declare."""
    for key, device in config[CONF_DEVICES].items():
        area_id = device.get(CONF_AREA)
        if area_id is not None and area_id not in config[CONF_AREAS]:
            raise vol.Invalid(f"device {key}: area {area_id} is not in areas")
    return config


def _entity_ids_distinct(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse two devices whose entities would share an ID.

    Device `pool` with the switch `switch_pump` and device `pool_switch` with
    the switch `pump` would both have pururu_pool_switch_switch_pump.
    """
    owners: dict[str, str] = {}  # object ID -> the device that has it
    for key, device in config[CONF_DEVICES].items():
        for name, entity_key, _ in _entity_keys(device):
            identity = Device(
                key=key, name=device[CONF_NAME], namespace=BUILDERS[name].namespace
            )
            object_id = identity.object_id(entity_key)
            if object_id in owners:
                raise vol.Invalid(
                    f"device {key}: {object_id} is already an entity of device "
                    f"{owners[object_id]}"
                )
            owners[object_id] = key
    return config


def _generated_ids_distinct(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse two reactions, or two programs, whose automations or scripts would share an ID.

    Device `lights` with the reaction `b_reaction_c` and device `lights_reaction_b`
    with the reaction `c` would both have pururu_lights_reaction_b_reaction_c.
    """
    blocks = (
        (CONF_REACTIONS, reactions.KIND, reactions.automation_id, "reaction"),
        (CONF_PROGRAMS, programs.KIND, programs.script_id, "program"),
    )
    for block, kind, id_of, what in blocks:
        owners: dict[str, str] = {}  # ID -> the device that has it
        for key, device in config[CONF_DEVICES].items():
            for item_key in device.get(block, {}):
                unique_id = id_of(key, item_key)
                if unique_id in owners:
                    raise vol.Invalid(
                        f"device {key}: {kind.domain}.{unique_id} is already a {what} "
                        f"of device {owners[unique_id]}"
                    )
                owners[unique_id] = key
    return config


def _reactions_resolved(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse a reaction's `device` that isn't a device, or its `when` that isn't that device's."""
    devices = config[CONF_DEVICES]
    for key, device in devices.items():
        for reaction_key, reaction in device.get(CONF_REACTIONS, {}).items():
            if (other := reaction.get("device")) is None:
                continue
            where = f"device {key}: reactions: {reaction_key}"
            if other not in devices:
                raise vol.Invalid(f"{where}: device {other} is not in devices")
            if reaction["when"] not in _referable(other, devices[other]):
                raise vol.Invalid(
                    f"{where}: {reaction['when']} is not an entity key of device {other}"
                )
    return config


def _referable(
    key: str, config: dict[str, Any]
) -> dict[str, tuple[Device, str, Platform]]:
    """Every entity key the device's features can create, in its namespace.

    Each maps to the device as its feature sees it, the entity key there and its
    platform: enough for its current entity ID and its unique ID.
    """
    return {
        qualified(BUILDERS[name].namespace, entity_key): (
            Device(key=key, name=config[CONF_NAME], namespace=BUILDERS[name].namespace),
            entity_key,
            platform,
        )
        for name, entity_key, platform in _entity_keys(config)
    }


# The features are read when a configuration is validated, not at import
CONFIG_SCHEMA = vol.Schema(
    {
        # A schema of its own: ALLOW_EXTRA would let a typo (`floor:`) through,
        # and so delete every floor the entry manages
        DOMAIN: vol.All(
            vol.Schema(
                {
                    # Schemas of their own: ALLOW_EXTRA would skip a key that isn't a slug
                    vol.Optional(CONF_FLOORS, default={}): vol.Schema(
                        {cv.slug: places.FLOOR_SCHEMA}
                    ),
                    vol.Optional(CONF_AREAS, default={}): vol.Schema(
                        {cv.slug: places.AREA_SCHEMA}
                    ),
                    vol.Optional(CONF_DEVICES, default={}): {cv.slug: _device},
                }
            ),
            places.floors_exist,
            _areas_exist,
            _generated_ids_distinct,
            _entity_ids_distinct,
            _reactions_resolved,
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

    Floors and areas come first: devices will be placed in them. The reactions'
    automations, the programs' scripts and Alert2's alerts come after the
    entities: they watch and act on the ones created. The programs' scripts come
    before the reactions' automations: a reaction starts one. The dashboard comes last:
    it shows them all.
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
    texts = await presets.async_texts(hass)
    for key, config in devices.items():
        for entity in _creatable(hass, registry, *_build(hass, key, config, texts)):
            built[Platform(split_entity_id(entity.entity_id)[0])].append(entity)
    entry.runtime_data = built
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _place(hass, entry, devices)
    _remove_stale(hass, entry, set(devices))
    created = {str(entity.unique_id) for each in built.values() for entity in each}
    scripts, held, targets = _scripts(hass, devices, created)
    generated_scripts = await generated.async_sync(
        hass, entry, programs.KIND, scripts, held
    )
    automations, held_automations = _automations(
        hass, devices, created, generated_scripts, held
    )
    await generated.async_sync(
        hass, entry, reactions.KIND, automations, held_automations
    )
    started = _started_scripts(devices)
    await alert2_alerts.async_sync(hass, entry, _alert2_alerts(hass, built))
    dashboard.async_setup(hass, entry)

    # Whether a reload is already scheduled: a burst of disables reloads once
    reloading = False

    @callback
    def changed(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        """One of the entry's entities or a started script got a new ID, or a program's target was disabled: build again.

        A rename is followed: of a pururu entity, or of a program's script a
        reaction starts (it would check and start an ID that no longer is). A
        program acting on an entity just disabled is dropped (`_acted_on`), once
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
            entry.entry_id, registered, data["changes"], started, targets
        )
        if why is None or (why == "disabled" and reloading):
            return
        reloading = True
        hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, changed)
    )
    return True


def _started_scripts(devices: dict[str, dict[str, Any]]) -> set[str]:
    """The IDs of the programs' scripts a reaction starts: renamed, its automation must follow."""
    return {
        programs.script_id(key, reaction["then"])
        for key, config in devices.items()
        for reaction in config.get(CONF_REACTIONS, {}).values()
        if "then" in reaction
    }


def _rebuild_for(
    entry_id: str,
    registered: er.RegistryEntry,
    changes: Mapping[str, Any],
    started: set[str],
    targets: set[str],
) -> Literal["renamed", "disabled"] | None:
    """Why this registry update needs the entry built again, if it does.

    Renamed: one of the entry's entities, or a script a reaction starts.
    Disabled: an entity a generated script acts on, just now (the old value
    of `disabled_by` is None).
    """
    ours = registered.config_entry_id == entry_id
    if "entity_id" in changes:
        started_script = (
            registered.platform == programs.KIND.domain
            and registered.unique_id in started
        )
        return "renamed" if ours or started_script else None
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
    """Delete the floors and areas the entry managed, its reactions' automations, programs' scripts and Alert2 alerts."""
    places.async_remove(hass, entry.data)
    await generated.async_remove(hass, entry, reactions.KIND)
    await generated.async_remove(hass, entry, programs.KIND)
    await alert2_alerts.async_remove(hass)


def _build(
    hass: HomeAssistant, key: str, config: dict[str, Any], texts: presets.Texts
) -> tuple[list[tuple[PururuEntity, set[str]]], dict[str, str]]:
    """Every entity of the device's features, with the unique IDs of the device's entities it follows.

    Each feature sees the device in its own namespace; what it takes through
    <capability>_from, or refers to, is in the owning feature's. Also the
    entity ID of each entity some entity watches (`follows`), by unique ID: the
    settings may never build it, and then only this names it.
    """
    referable = _referable(key, config)
    built: list[tuple[PururuEntity, set[str]]] = []
    watched: dict[str, str] = {}
    for name, feature in BUILDERS.items():
        if name not in config:
            continue
        device = Device(key=key, name=config[CONF_NAME], namespace=feature.namespace)
        inputs: dict[str, str] = {}
        required: set[str] = set()
        for capability in feature.requires:
            source = FEATURES[config[name][f"{capability}_from"]]
            provider = Device(
                key=key, name=config[CONF_NAME], namespace=source.namespace
            )
            entity_key = source.provides[capability]
            inputs[capability] = provider.current_entity_id(
                hass, source.entity_keys[entity_key], entity_key
            )
            required.add(provider.object_id(entity_key))
        if feature.refers is not None:
            for reference in feature.refers(config[name]):
                owner, entity_key, platform = referable[reference]
                inputs[reference] = owner.current_entity_id(hass, platform, entity_key)
        for entity in (
            *feature.build(hass, device, config[name], inputs),
            *presets.build(hass, device, feature, config[name], texts),
        ):
            follows = set()
            for reference in entity.follows:
                owner, entity_key, platform = referable[reference]
                follows.add(unique_id := owner.object_id(entity_key))
                watched[unique_id] = owner.current_entity_id(hass, platform, entity_key)
            built.append(
                (entity, {*map(device.object_id, entity.sources), *required, *follows})
            )
    return built, watched


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
) -> tuple[list[generated.Item], set[str]]:
    """An automation per reaction of every device; one that can't work is logged.

    One watching an entity not created, or starting a program whose script
    isn't generated, isn't generated. Also the IDs of those held with their
    program.
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
    owner, entity_key, platform = _referable(owner_key, devices[owner_key])[when]
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
        referable = _referable(key, config)
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
