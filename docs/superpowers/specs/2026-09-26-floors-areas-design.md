# Floors and areas from YAML — design

Version: pururu 0.1.1. Branch: `feat/floors`.

## Goal

pururu creates Home Assistant floors (`floor_registry`) and areas (`area_registry`) from `configuration.yaml`, with IDs the user chooses, so that devices can later be placed in them by ID. Placing devices in areas is **out of scope** here.

## Decisions

| Question | Decision |
|---|---|
| How to choose the ID (HA's `async_create` takes no ID; it slugifies the name) | Create with `name=<id>` so HA generates `<id>`, then `async_update(name=<display name>)`. Public API only. |
| A floor/area with the configured ID already exists | Adopt it: the YAML is the source of truth and every configured field is synced on each setup. |
| A floor/area leaves the YAML | Removed from HA. pururu records the IDs it manages. |
| YAML shape | `floors:` and `areas:` side by side; an area points to a floor with `floor:`. |
| Where it runs | In the config entry's setup, before the devices; managed IDs are kept in `entry.data`. |

## Configuration

```yaml
pururu:
  floors:
    terreo:                   # the floor_id (cv.slug)
      name: Térreo            # required
      level: 0                # optional int
      icon: mdi:home-floor-0  # optional
      aliases: [embaixo]      # optional list of strings
  areas:
    cozinha:                  # the area_id (cv.slug)
      name: Cozinha           # required
      floor: terreo           # optional; must be a key of floors:
      icon: mdi:stove         # optional
      aliases: [copa]         # optional list of strings
  devices: {}                 # unchanged
```

- `floors:` and `areas:` default to `{}`.
- An area's `floor:` that is not a key of `floors:` makes the configuration invalid (reported by HA's config check; a reload keeps the running setup, as for devices).
- An omitted optional field is cleared in HA (`level`/`icon`/`floor_id` → `None`, `aliases` → empty set): the YAML is the source of truth.
- Not supported (YAGNI): an area's `picture`, `labels`, `humidity_entity_id`, `temperature_entity_id`; a floor's order. pururu does not touch them on adopted areas.

## Behaviour

On every setup of the config entry (start and reload), in this order:

1. **Remove stale.** Every ID in `entry.data` (`floors`, `areas`) no longer in the YAML is deleted from its registry, if it still exists. Removal comes first so names are free again (swapping `terreo: Térreo` for `ground: Térreo` works). HA itself unsets a deleted floor on its areas, and a deleted area on devices and entities.
2. **Floors.** For each configured floor:
   - ID exists → `async_update` with the configured fields.
   - ID free → `async_create(name=<id>)`. If the generated ID is not `<id>`, delete the new floor and log an error. Otherwise `async_update(name=<name>, level, icon, aliases)`; if that fails, delete the new floor and log an error.
   - `ValueError` (name already used by a floor pururu does not manage) → logged error, floor skipped.
3. **Areas.** The same as floors, with `floor_id` set to the configured floor. An area whose floor was skipped in step 2 is skipped too, with a logged error ("… follows floor terreo, which is not created").
4. **Record.** `entry.data` becomes `{"floors": [...], "areas": [...]}`: every configured ID that exists in its registry after this run. A floor or area that exists but HA refused to update ("is not synced") stays recorded, so it is still deleted once the configuration drops it; an area whose floor exists follows it even if that floor could not be updated.
   An unknown key under `pururu:` is a configuration error (a typo such as `floor:` must not delete every managed floor).
5. **Devices**, as today.

Nothing in steps 1–4 fails the entry's setup: every problem is a logged error, and the rest is still created. This follows `_creatable` for entities.

When the entry is removed (the integration deleted in the UI), `async_remove_entry` deletes every floor and area recorded in `entry.data`.

The entry is created when the YAML declares at least one device, floor or area (today: device only).

## Components

- **`custom_components/pururu/places.py`** (new): floors and areas only, no device code.
  - `FLOOR_SCHEMA`, `AREA_SCHEMA`: the blocks' schemas.
  - `async_sync(hass, floors, areas, managed) -> managed`: steps 1–4 without the write to `entry.data`. Takes and returns `{"floors": list[str], "areas": list[str]}`.
  - `async_remove(hass, managed)`: deletes what `managed` lists, where it still exists.
- **`__init__.py`**
  - `CONFIG_SCHEMA` adds `floors:` and `areas:` and checks each area's `floor:`.
  - `_async_apply` stores the whole validated `pururu:` block and creates the entry when there are devices, floors or areas.
  - `async_setup_entry` calls `places.async_sync` before building the devices and stores the result with `hass.config_entries.async_update_entry(entry, data=...)`.
  - `async_remove_entry` (new) calls `places.async_remove(hass, entry.data)`.
- **`const.py`**: `DATA_DEVICES` becomes `DATA_CONFIG` (the validated `pururu:` block); adds `CONF_FLOORS`, `CONF_AREAS`, `CONF_FLOOR`, `CONF_LEVEL`.
- **`manifest.json`**: `version` → `0.1.1`.
- **`README.md`**: a **Floors and areas** section (keys, the ID rule, adoption, removal, the errors).

## Tests

`tests/test_places.py` (new), plus `tests/helpers.py` taking floors and areas in `setup`/`reload`:

- a floor and an area are created with the chosen ID and the display name;
- the area is on its floor;
- an existing floor/area with that ID is adopted and synced (name, level, icon, aliases, floor), including clearing omitted fields;
- a reload that drops a floor/area deletes it; one that keeps it keeps its ID;
- changing an ID while keeping the name (`terreo` → `ground`, both "Térreo") works;
- a name already used by a floor/area pururu does not manage: logged error, not created, its areas not created, the rest created;
- a key equal to the normalized name of a floor pururu does not manage (e.g. key `terreo`, an unmanaged floor named "Terreo"): `async_create(name="terreo")` raises, logged error, nothing left behind. (The generated-ID check in step 2 is a guard only: a `cv.slug` key slugifies to itself and a taken ID is adopted, so HA cannot suffix it.)
- an area's `floor:` not in `floors:` is refused by the configuration;
- floors/areas without devices create the entry;
- removing the entry deletes the managed floors and areas, and only those;
- the existing device tests still pass.

`uv run pytest` also runs ruff, ruff format, mypy, hassfest and the quality-scale check.
