# Entity namespaces — design

Version: pururu 0.1.5. Branch: `feat/entity-namespaces`. Comes before alerts, which will be a feature named in this format from its first day.

## Goal

Every feature puts its entity keys in a namespace of its own, so an entity ID tells which feature made it, and two features can never give two entities one ID.

```
<platform>.pururu_<device key>_<namespace>_<entity key>
```

There's no exception, even when an entity key is the same word as its namespace: `phases` has the namespace `phase` and one entity key, `phase`, so its entity is `sensor.pururu_washer_phase_phase`, and a switch keyed `switch` is `switch.pururu_pool_switch_switch`.

| Feature | Namespace | Before | After |
|---|---|---|---|
| appliance | `appliance` | `binary_sensor.pururu_washer_running` | `binary_sensor.pururu_washer_appliance_running` |
| | | `sensor.pururu_washer_runtime_month` | `sensor.pururu_washer_appliance_runtime_month` |
| phases | `phase` | `sensor.pururu_washer_phase` | `sensor.pururu_washer_phase_phase` |
| switches | `switch` | `switch.pururu_pool_pump` | `switch.pururu_pool_switch_pump` |

The YAML doesn't change: `switches:` keys stay `pump`, `cycle_from:` names a feature, and real entity IDs aren't pururu's. Every configuration valid today stays valid. The one difference is a relaxation: a switch may now be called `power` or `running` in a device with `appliance`.

## Why

- **A new feature can't collide with an old one.** Today an entity key must differ from every other feature's (`test_no_entity_key_in_two_features`), and a switch's key must not be any entity key of another feature of the device. Every feature to come (`alerts`, `lights`, `covers`…) would need names nobody else uses, such as `power` or `running`, forever. With namespaces, uniqueness comes from how the ID is built, and no check between features is needed.
- **The ID says what the entity is.** `binary_sensor.pururu_washer_running` and a future `binary_sensor.pururu_washer_long_cycle` alert are indistinguishable; `…_appliance_running` and `…_alert_long_cycle` are not.

## Decisions

| Question | Decision |
|---|---|
| Which features get a namespace | All of them. Rejected: none for features standing for a domain (`switches`, later `lights`), whose platform already says what they are. One rule everywhere keeps the code and the docs simpler, and it makes `switch_pump` and `light_pump` distinct keys of one device. |
| An entity key equal to its namespace | Written twice, like any other: `phase_phase`, `switch_switch`. Rejected (decided after the first implementation): writing it once, an exception that a switch keyed `switch` would hit unexpectedly; and renaming phases' entity key (`phase_current`). |
| Translation and icon keys | The qualified key (`appliance_running`). Translations are per platform and shared by the whole integration, so two features' `power` would otherwise share one name. |
| Migrating existing entities | None. Their unique IDs change: stale removal deletes the old entities and the new ones are created. Their history, and any rename made in the UI, is lost. Only the author uses pururu today, and that is accepted. |
| Version | 0.1.5, not 0.2.0 (only the author uses pururu today). The PR's title and description and the docs say that the IDs of `appliance`, `phases` and `switches` change. |

## Contract

- `Feature.namespace: str`, required. The contract test checks that every namespace is a slug, that no two are equal, and that none is another's prefix followed by `_` (`switch` and `switch_x`).
- `Device.namespace: str`, required, so that no ID is built without a namespace by mistake. `Device.qualified(entity_key)` is `namespace` when the key equals it, else `<namespace>_<entity_key>`. `object_id`, `entity_id` and `current_entity_id` qualify the key they are given.
- `Device.info` stays keyed by the device key alone: every feature's entities stay in one Home Assistant device.
- A feature keeps writing local entity keys (`"running"`, `sources = ("running",)`, `provides={"cycle": "running"}`, `entity_keys`). The only change to `appliance`, `phases` and `switches` is `namespace=` in their `Feature`.

## Core (`__init__.py`)

- `_build` gives each feature's `build()` a `Device` in that feature's namespace (`dataclasses.replace(device, namespace=feature.namespace)`).
- A `<capability>_from` is resolved with the providing feature's `Device`, so its current entity ID is the provider's.
- `_build` returns, with each entity, the unique IDs it follows, qualified by the right feature (its own `sources`, the providers of its capabilities). `_creatable` compares those directly and knows nothing about namespaces.
- `_entity_keys` yields qualified keys, and `_entity_ids_distinct` keeps checking IDs between devices with them. Its current example no longer collides (`pool` + switch `pump_heater` is `pururu_pool_switch_pump_heater`, `pool_pump` + switch `heater` is `pururu_pool_pump_switch_heater`); a collision now needs a device key ending in a namespace, as `pool` + switch `switch_pump` and `pool_switch` + switch `pump`, both `pururu_pool_switch_switch_pump`. The docstring, the tests and the docs take that example.
- `_device` loses its check of an entity key used twice in one device: it can't happen any more.

## Entities (`entity.py`)

`_identify` sets the translation key to `device.qualified(entity_key)`. A configured entity (a switch) is still named by its `name:`.

## Translations and icons

`translations/en.json`, `translations/pt-BR.json` and `icons.json` rename their entity keys to the qualified ones (`running` → `appliance_running`, `runtime_month` → `appliance_runtime_month`, …). `phase` becomes `phase_phase`.

## Tests

- **Contract (`tests/test_features.py`):** `test_no_entity_key_in_two_features` is replaced by the namespace checks. Translations and icons are looked up by qualified key.
- **Every test that names an ID** is updated to the new format.
- **New tests:**
  - A switch keyed `power` or `running` in a device with `appliance` is accepted, and both entities are created.
  - A configuration set up with the old IDs, then reloaded, has its old entities removed and the new ones created.
  - A rename in the UI still works with namespaced keys: `phases` follows a renamed `appliance_running`.
  - `_entity_ids_distinct` still refuses two devices giving an entity one ID, with namespaced keys.

## Docs

In the docs, "entity key" stays the key a feature's page lists (`running`); the end of the ID is `<namespace>_<entity key>`. The dashboard shows floors, areas and devices from the registries and is not affected.

**Guide**

- `index`: the table of the washer's entities.
- `getting-started/first-device`: the entity tables (steps 1 and 2), the pattern line, `phase`, and the "laundry is done" automation (`last_cycle_end`, `last_cycle_duration`, `last_cycle_energy`).
- `concepts/entity-ids`: the pattern becomes `<platform>.pururu_<device key>_<namespace>_<entity key>`, with a table of each feature's namespace and the rule that it has no exception (`phase_phase`, `switch_switch`); the `running` and unique ID examples; the taken-ID log line. Names are unchanged (`Máquina de lavar Running`).
- `concepts/devices-and-features`: the capability table (`binary_sensor.pururu_<key>_appliance_running`).
- `features/appliance`: the entity table.
- `features/phases`: `sensor.pururu_<key>_phase_phase`.
- `features/switches`: the created IDs (`switch.pururu_pool_switch_pump`, `…_switch_heater`), "`pump` → `switch.pururu_pool_switch_pump`", the entity table header; the paragraph forbidding a switch key that is another feature's entity key is removed.
- `reference/configuration`: the rule "every entity key is different in a device" is removed; the rule on two devices takes the new example, and its `pool_energy` + `total` example (no longer a collision) is replaced.
- `reference/troubleshooting`: the error `switches: power is already an entity key of appliance` is removed; the two-devices error takes the new example; the log lines of a taken ID, of a follower not created (`…_phase_phase follows binary_sensor.pururu_laundry_washer_appliance_running…`) and of a pururu switch (`…not creating switch.pururu_pool_switch_pump`) get the new IDs.
- `README.md`: `binary_sensor.pururu_dishwasher_appliance_running`.

**Develop**

- `develop/architecture`: the `Feature` table gains `namespace`; the paragraph on `_device` checking every entity key of a device is replaced by one on namespaces; the ID pattern and `Device.object_id`; `_identify`'s translation key is the qualified key (`entity.<platform>.<namespace>_<entity key>.name`).
- `develop/writing-a-feature`: the `OPENINGS` example gains `namespace="openings"` and its entity key becomes `total`, so its entity stays `sensor.pururu_<key>_openings_total`; `namespace` is described among the pieces; "An entity key must not be used by any other feature" is removed; the translation and icon examples use the qualified key; the configured-feature list loses "The device schema refuses a key that is an entity key of another feature"; the contract test table replaces `test_no_entity_key_in_two_features`.
- `develop/testing`: the example test's `binary_sensor.pururu_laundry_washer_appliance_running`.
- `CLAUDE.md`: the entity ID format; the `configured` line loses "`_device` refuses two alike entity keys in one device", and the `Feature` line gains `namespace`.

## Release

`manifest.json` goes to `0.1.5`. The release notes are generated from the PR (`--generate-notes`), so the PR's title names the change of IDs, and its description says that the old entities of `appliance`, `phases` and `switches` are removed along with their history.
