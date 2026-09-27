# Switches — design

Version: pururu 0.1.4. Branch: `feat/switch`. Follows #9, which renamed "metric" to "entity key".

## Goal

A device can have several switches, each one keyed and named in YAML, each one standing for a real switch: it shows the real switch's state and passes on to it what is asked of it.

```yaml
pururu:
  devices:
    pool:
      name: Piscina
      area: piscina
      switches:
        pump: {entity: switch.pool_pump, name: Bomba}
        heater: {entity: switch.pool_heater, name: Aquecedor}
# → switch.pururu_pool_pump    "Piscina Bomba"
# → switch.pururu_pool_heater  "Piscina Aquecedor"
```

## Decisions

| Question | Decision |
|---|---|
| One switch or several per device | Several, under `switches:`, each keyed by its entity key. |
| Where a switch's name comes from | `name:`, required. Entity keys chosen in YAML have no translation. |
| Which real entities | Only `switch.*`. One feature per domain, each built on HA's group entity of that domain with a single member (`SwitchGroup` here, as `Mirror` is a `SensorGroup`). A pururu entity has the real one's domain, so it keeps everything that domain offers. |
| Rejected: any on/off entity as a switch | A light, fan or cover exposed as `switch.*` loses brightness, colour, speed or position, shows as a toggle, and Assist doesn't treat it as its domain ("dim the pool light", "turn off the lights in Piscina"). |
| Later, not in this PR | `lights:` (a `LightGroup` of one, with brightness and colour passed through), in its own PR (0.1.5). Then maybe `fans:`, `covers:`, `locks:`, `valves:`: HA has a group entity for each. Each is one more feature with `configured` set to its platform. |
| How `Feature` declares entity keys that come from YAML | A new optional field, `configured: Platform \| None`. Rejected: `entity_keys` as a function of the configuration (rewrites every feature and the contract test for one case); `switches:` as a special device key like `area:` (a second path around `_creatable`, stale removal and renames). |
| Two entity keys alike in one device | A configuration error, even across platforms: `switch.pururu_pool_power` and `sensor.pururu_pool_power` would share the unique ID `pururu_pool_power`, and `_creatable` and `_remove_stale` compare unique IDs only. |
| Two devices giving an entity one ID | A configuration error (added after the final review): with keys chosen in YAML, device `pool` + `pump_heater` and device `pool_pump` + `heater` both give `pururu_pool_pump_heater`. |
| A reload moving an entity key to another platform | The old entity is removed: stale removal compares platform and unique ID (added after the final review). |
| "pururu controls nothing" in the docs | Rewritten: pururu never acts on its own. A switch passes on what a person, an automation or a voice assistant asks of it, and nothing else. |

## Configuration

`switches:` is a feature (a key of `FEATURES`), so it counts as the feature a device needs, alone or with others.

```python
SWITCH = vol.Schema(
    {
        vol.Required("entity"): cv.entity_domain(Platform.SWITCH),
        vol.Required("name"): cv.string,
    }
)
SCHEMA = vol.All(vol.Schema({cv.slug: SWITCH}), vol.Length(min=1))
```

- A key is a slug and becomes the entity key: `pump` → `switch.pururu_pool_pump`.
- `entity` must be of the `switch` domain; `light.pool_light` is refused. It must not be a pururu switch (`switch.pururu_…`): a switch standing for itself would call itself forever, and one standing for another pururu switch is pointless.
- `name` is required. It is shown after the device's name, in every language.
- Unknown keys inside a switch are refused, and so is an empty `switches: {}`.

### Distinct entity keys in a device

`_device` (in `__init__.py`) collects, for the features present in the device, every fixed entity key (`entity_keys`, all of them, including those that only exist with some settings, such as `runtime_month`) and every key of a `configured` feature's block. They must all differ:

```
switches: power is already an entity key of appliance
```

Checking against every fixed entity key, not only those the settings create, means turning a statistic on later never invalidates an existing switch.

## Feature contract

```python
# Its entity keys are the keys of its block, all on this platform, named by
# the block's `name`; None: its entity keys are entity_keys, named by the translations
configured: Platform | None = None
```

- `SWITCHES = Feature(schema=SCHEMA, entity_keys={}, configured=Platform.SWITCH, build=build, example={"pump": {"entity": "switch.demo_pump", "name": "Pump"}})`.
- `provides` points to fixed entity keys only; a `configured` feature provides nothing.
- `_build` and `_creatable` don't change: `build()` returns entities that already carry their IDs.

`PururuEntity._identify(device, platform, entity_key, name=None)`: with a `name`, the entity is named by it and has no translation key; without one (`appliance`, `phases`), nothing changes.

## The entity

`Switch(PururuEntity, SwitchGroup)` in `features/switches.py`: HA's switch group with the real switch as its only member.

| The real switch | The pururu switch |
|---|---|
| `on` / `off` | the same |
| `unknown` | available, state unknown |
| `unavailable`, or doesn't exist | unavailable |

- Turning it on or off calls `switch.turn_on` / `switch.turn_off` on the real switch, blocking, with the caller's context, so the logbook names who did it.
- `assumed_state` follows the real switch's.
- No restored state: it always shows the real switch.
- The group's `entity_id: [switch.pool_pump]` attribute stays, as on `Mirror`: the more-info dialog shows the real switch.
- The icon is HA's default for a switch.

### Renames and taken IDs

- Renaming the pururu switch's entity ID in the UI is followed, as for every entity.
- Renaming the real switch needs the YAML updated; until then the pururu switch is unavailable, as `appliance`'s `power:` is.
- An ID already taken by another integration is a logged error and only that switch isn't created (existing `_creatable`).

## Platform and manifest

- `Platform.SWITCH` joins `PLATFORMS` (`const.py`); `switch.py` adds `entry.runtime_data[Platform.SWITCH]`, as `sensor.py` does.
- `manifest.json`: `0.1.4`. `iot_class` stays `calculated`, as for HA's `group`, which passes commands on too.
- The dashboard doesn't change: it lists devices, not entities.

## Testing

`tests/test_switches.py`:

- The pururu switch follows the real one: on, off, unknown, unavailable, missing.
- Turning it on and off calls the real switch's service, with the caller's context.
- Its name comes from `name:`, in English and in Portuguese.
- A device with only `switches:`.
- Refused: another domain, no `name`, an unknown key, an empty block, an entity key already in `appliance`.
- An ID already taken; the pururu switch renamed in the UI; a reload that drops a switch (its entity is removed); a restart.

`tests/test_features.py` (contract), for a `configured` feature: its platform is in `PLATFORMS`, its example is valid and an unknown key is refused, it provides nothing. Translations and icons are still required for `entity_keys` only.

## Documentation

- `docs/features/switches.mdx` (new): its settings (`<Property>`), the entity and its states, why only `switch.*` and that `lights:` comes next, the switch showing twice in an area when the real one's device is there too (as `appliance`'s `power` already does), renaming the real switch. Added to the `Features` group in `docs.json`.
- `docs/index.mdx`, "What pururu doesn't do": "It controls nothing" becomes "It never acts on its own. Its sensors only read the entities you point them to. A switch passes on to its real switch what you, an automation or a voice assistant ask of it, and nothing else. pururu never turns anything on or off by itself, and never talks to a device or a cloud service."
- `docs/concepts/devices-and-features.mdx`: a feature reads real entities "or, for `switches`, passes commands on to them"; `switches` in the features table and in Provides / Needs.
- `docs/concepts/entity-ids.mdx`: platform `switch`; a switch's name comes from `name:`.
- `docs/reference/configuration.mdx`: `switches:`, and the distinct entity keys rule.
- `docs/reference/troubleshooting.mdx`: only if a new log message appears.
- `docs/develop/architecture.mdx` and `docs/develop/writing-a-feature.mdx`: `configured`, `_identify`'s `name`, and the group-of-one pattern for a feature that stands for real entities of one domain.
- `CLAUDE.md`: `configured`, and `switch.py` next to `sensor.py` and `binary_sensor.py`.

## Risks

- `SwitchGroup` is HA's group integration, which `Mirror` already builds on through `SensorGroup`; `group` is already a dependency. A change to its constructor breaks at setup, and the tests catch it.
- The pururu switch and the real one are two entities for one thing. Voice and area-wide actions reach both; switching both is harmless, but "how many switches are on" counts two.
