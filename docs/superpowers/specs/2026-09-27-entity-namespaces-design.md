# Entity namespaces — design

Version: pururu 0.1.5. Branch: `feat/entity-namespaces`. Comes before alerts, which will be a feature named in this format from its first day.

## Goal

Every feature puts its entity keys in a namespace of its own, so an entity ID tells which feature made it, and two features can never give two entities one ID.

```
<platform>.pururu_<device key>_<namespace>_<entity key>
```

When an entity key is its feature's namespace, it isn't repeated: `phases` has the namespace `phase` and one entity key, `phase`, so its entity is `sensor.pururu_washer_phase`.

| Feature | Namespace | Before | After |
|---|---|---|---|
| appliance | `appliance` | `binary_sensor.pururu_washer_running` | `binary_sensor.pururu_washer_appliance_running` |
| | | `sensor.pururu_washer_runtime_month` | `sensor.pururu_washer_appliance_runtime_month` |
| phases | `phase` | `sensor.pururu_washer_phase` | unchanged |
| switches | `switch` | `switch.pururu_pool_pump` | `switch.pururu_pool_switch_pump` |

The YAML doesn't change: `switches:` keys stay `pump`, `cycle_from:` names a feature, and real entity IDs aren't pururu's. Every configuration valid today stays valid. The one difference is a relaxation: a switch may now be called `power` or `running` in a device with `appliance`.

## Why

- **A new feature can't collide with an old one.** Today an entity key must differ from every other feature's (`test_no_entity_key_in_two_features`), and a switch's key must not be any entity key of another feature of the device. Every feature to come (`alerts`, `lights`, `covers`…) would need names nobody else uses, such as `power` or `running`, forever. With namespaces, uniqueness comes from how the ID is built, and no check between features is needed.
- **The ID says what the entity is.** `binary_sensor.pururu_washer_running` and a future `binary_sensor.pururu_washer_long_cycle` alert are indistinguishable; `…_appliance_running` and `…_alert_long_cycle` are not.

## Decisions

| Question | Decision |
|---|---|
| Which features get a namespace | All of them. Rejected: none for features standing for a domain (`switches`, later `lights`), whose platform already says what they are. One rule everywhere keeps the code and the docs simpler, and it makes `switch_pump` and `light_pump` distinct keys of one device. |
| An entity key equal to its namespace | Written once: `phase`, not `phase_phase`. |
| Translation and icon keys | The qualified key (`appliance_running`). Translations are per platform and shared by the whole integration, so two features' `power` would otherwise share one name. |
| Migrating existing entities | None. Their unique IDs change: stale removal deletes the old entities and the new ones are created. Their history, and any rename made in the UI, is lost. Only the author uses pururu today, and that is accepted. |
| Version | 0.1.5, not 0.2.0 (only the author uses pururu today). The PR's title and description and the docs say that the IDs of `appliance` and `switches` change. |

## Contract

- `Feature.namespace: str`, required. The contract test checks that every namespace is a slug, that no two are equal, and that none is another's prefix followed by `_` (`switch` and `switch_x`).
- `Device.namespace: str`, required, so that no ID is built without a namespace by mistake. `Device.qualified(entity_key)` is `namespace` when the key equals it, else `<namespace>_<entity_key>`. `object_id`, `entity_id` and `current_entity_id` qualify the key they are given.
- `Device.info` stays keyed by the device key alone: every feature's entities stay in one Home Assistant device.
- A feature keeps writing local entity keys (`"running"`, `sources = ("running",)`, `provides={"cycle": "running"}`, `entity_keys`). The only change to `appliance`, `phases` and `switches` is `namespace=` in their `Feature`.

## Core (`__init__.py`)

- `_build` gives each feature's `build()` a `Device` in that feature's namespace (`dataclasses.replace(device, namespace=feature.namespace)`).
- A `<capability>_from` is resolved with the providing feature's `Device`, so its current entity ID is the provider's.
- `_build` returns, with each entity, the unique IDs it follows, qualified by the right feature (its own `sources`, the providers of its capabilities). `_creatable` compares those directly and knows nothing about namespaces.
- `_entity_keys` yields qualified keys, and `_entity_ids_distinct` keeps checking IDs between devices with them (`pool` + `pump_heater` and `pool_pump` + `heater`).
- `_device` loses its check of an entity key used twice in one device: it can't happen any more.

## Entities (`entity.py`)

`_identify` sets the translation key to `device.qualified(entity_key)`. A configured entity (a switch) is still named by its `name:`.

## Translations and icons

`translations/en.json`, `translations/pt-BR.json` and `icons.json` rename their entity keys to the qualified ones (`running` → `appliance_running`, `runtime_month` → `appliance_runtime_month`, …). `phase` stays.

## Tests

- **Contract (`tests/test_features.py`):** `test_no_entity_key_in_two_features` is replaced by the namespace checks. Translations and icons are looked up by qualified key.
- **Every test that names an ID** is updated to the new format.
- **New tests:**
  - A switch keyed `power` or `running` in a device with `appliance` is accepted, and both entities are created.
  - A configuration set up with the old IDs, then reloaded, has its old entities removed and the new ones created.
  - A rename in the UI still works with namespaced keys: `phases` follows a renamed `appliance_running`.
  - `_entity_ids_distinct` still refuses two devices giving an entity one ID, with namespaced keys.

## Docs

- Every page that shows an ID gets the new format: `index`, `getting-started/first-device`, `concepts/devices-and-features`, `features/appliance`, `features/switches`, `reference/configuration`, `reference/troubleshooting`, `develop/architecture`, `develop/testing`, and the README.
- `concepts/entity-ids`: the pattern gains the namespace, with each feature's namespace and the rule that an entity key equal to its namespace is written once.
- `features/switches`: the paragraph forbidding a switch key that is another feature's entity key is removed.
- `develop/writing-a-feature`: `namespace` joins the contract; the rules that an entity key must be unique across features, and that the device schema refuses a configured key used by another feature, are removed; the contract test table is updated.
- `CLAUDE.md`: the entity ID format, and the line on `_device` refusing alike entity keys.

## Release

`manifest.json` goes to `0.1.5`. The release notes are generated from the PR (`--generate-notes`), so the PR's title names the change of IDs, and its description says that the old entities of `appliance` and `switches` are removed along with their history.
