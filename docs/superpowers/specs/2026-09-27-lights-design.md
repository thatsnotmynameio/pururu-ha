# Lights — design

Version: pururu 0.1.7. Branch: `feat/lights`. Follows #13, which put every feature's entity keys in a namespace. The switches spec (0.1.4) named `lights:` as the next feature.

## Goal

A device can have several lights. Each one is keyed and named in YAML and stands for a real entity. The real entity is a light, or a switch that turns a light on and off, such as a relay. The pururu light shows the real entity's state, offers what the real entity offers, and passes on what is asked of it.

```yaml
pururu:
  devices:
    sala:
      name: Sala
      area: sala
      lights:
        teto: {entity: light.sala_teto, name: Teto}          # a smart bulb
        abajur: {entity: switch.sonoff_abajur, name: Abajur} # a relay
# → light.pururu_sala_light_teto    "Sala Teto"    what the bulb offers: brightness, colour…
# → light.pururu_sala_light_abajur  "Sala Abajur"  on and off
```

## Why an entity of its own

The pururu light is a new entity. The real one stays as it is. pururu doesn't own the real entity, so it can't move it into its device, give it a `pururu_…` ID, name it, or remove it with the configuration. An entity of its own belongs to the pururu device and its area, has the name from the YAML, and keeps a stable ID. Replacing the bulb or the relay means changing `entity:` alone. `light.pururu_sala_light_teto` keeps its ID, name and area, and the automations and dashboards that use it go on working.

## Decisions

| Question | Decision |
|---|---|
| Which real entities | `light.*` and `switch.*`. A relay that drives a lamp is common, and it should be a light for voice assistants and area actions. |
| Rejected: HA's `switch_as_x` helper (its config entries, or its `LightSwitch` class) | `LightSwitch` moves the entity into the real switch's device, takes the switch's name, copies its Assist exposure and unexposes the real switch. Creating `switch_as_x` config entries would mean managing another integration's entries. |
| What a light offers | What the real entity exposes, read at run time and not listed in pururu's code. A `light.*` gives its colour modes, brightness, colours, colour temperature and its range, effects and supported features. When they change (a firmware update), the pururu light follows. A `switch.*` exposes only on and off, so its light is `ColorMode.ONOFF`. |
| One real entity or several | One, always: `entity:` is singular, in `lights` as in `switches`. Several bulbs as one light will be a group of pururu lights, a feature of its own (see "Later: `groups:`"), and not a list in `entity:`. |
| Rejected: `entity:` taking a list later, or `entities:` in an item | A key that is a string or a list makes every rule handle both. Groups of pururu lights keep each bulb controllable on its own, as HA's groups do. |
| The same real switch as a switch and as a light | Refused **within one device**: a real entity appears in one `configured` feature of a device at most. The rule is generic, so it covers future `fans:` and `covers:`, which may take `switch.*` too. Across devices it's allowed: a relay can be a light in `sala` and a switch in `piscina`. |
| The same real entity twice in one feature | Allowed, as in `switches` today, in one device or across devices. |
| An entity standing for a pururu entity | Refused. `light.pururu_…` would call itself forever, and `switch.pururu_…` already stands for a real switch. A pururu entity renamed in the UI gets past the prefix: `build()` checks the entity registry, logs the error and skips that light. A light (or switch) renamed in the UI to the entity its own `entity:` names is kept standing for nothing (a group with no member: `unavailable`, never passing a command on to itself, found in the PR review), with the log `<entity> is this light itself: name the real one`. Skipping it would delete its registry entry, and the next reload would bring it back, flip-flopping (found in the final review). |
| Code shared with `switches` | A module of functions, `features/standing.py`, not a base class. The entity classes already inherit from HA's group classes. What `switches` and `lights` share is the configuration rules and the registry check, not entity behaviour. Each feature keeps its own `build()` loop, readable without opening another file. |
| Rejected: copying `switches.py` | The registry check came out of a PR review. Copies of it would drift apart, and `fans:`, `covers:`, `locks:` and `valves:` are planned. |
| Rejected: a `Feature` factory (`standing_for(platform, classes)`) | Too abstract for two cases. Each domain has its own details, such as a switch as a light. |

## Configuration

`lights:` is a feature (a key of `FEATURES`) with `namespace="light"`, `configured=Platform.LIGHT` and `entity_keys={}`. A device can have `lights:` alone.

- A key is a slug and becomes the entity key: `teto` → `light.pururu_sala_light_teto`. There's no exception: a key `light` gives `light.pururu_sala_light_light`.
- `entity` is required. It's a `light.*` or `switch.*` entity, and not `light.pururu_…` or `switch.pururu_…`.
- `name` is required and not blank. It's shown after the device's name, in every language.
- Unknown keys inside a light are refused, and so is an empty `lights: {}`.
- `switches: pump` and `lights: pump` in one device are accepted: their IDs differ by namespace (`switch_pump` and `light_pump`).

### One configured feature per real entity, in a device

`_device` (in `__init__.py`) goes through the device's `configured` blocks and refuses a real entity found in two of them:

```
switches: switch.sonoff_abajur is already in lights
```

## Shared code: `features/standing.py`

"Standing for a real entity": functions only, with no class and no side effects.

```python
def real_entity(*domains: Platform) -> Callable[[Any], str]:
    """An entity ID of one of `domains`, not <domain>.pururu_…"""

def schema(*domains: Platform) -> Callable[[Any], Any]:
    """{slug: {entity: real_entity(*domains), name: not blank}}, at least one"""

def is_pururu(hass: HomeAssistant, entity: str) -> bool:
    """The registry says `entity` is pururu's (catches a pururu_… renamed in the UI)."""
```

- `switches.py` uses `standing.schema(Platform.SWITCH)` and `standing.is_pururu`. Its behaviour and log lines don't change, and `tests/test_switches.py` passes unedited. One configuration message changes: another domain reads `light.pool_light is not a switch` (a light: `sensor.x is not a light or switch`) instead of HA's `does not belong to domain`, which would print a list for two domains.
- Each feature logs its own message when `is_pururu` is true, so the predicate stays free of side effects.

## The entities (`features/lights.py`)

```python
KINDS = {Platform.LIGHT: Light, Platform.SWITCH: SwitchLight}
SCHEMA = standing.schema(*KINDS)
```

`build()` goes through the block. It skips (and logs) an entity that `standing.is_pururu` says is pururu's. Otherwise it picks the class by the real entity's domain (`split_entity_id`) and creates it standing for `entity`. The group classes take a list of members, and it holds that one entity. The domains the schema takes and the class of each come from one mapping.

### `Light(PururuEntity, LightGroup)`, for `light.*`

HA's light group with the real light as its only member.

- **State.** `on` and `off` are the real light's. `unknown` means the pururu light is available with an unknown state. `unavailable`, or a real light that doesn't exist, makes it unavailable.
- **What it offers.** The group reads these from the real light at every state change: `supported_color_modes`, `color_mode`, brightness, colours (hs, rgb, rgbw, rgbww, xy), colour temperature and its range, `effect_list`, `effect`, `supported_features` and `assumed_state`.
- **Commands.** `turn_on` forwards every attribute HA's light service gives an entity. That is brightness, colours, colour temperature, effect, flash, transition and white. HA converts `brightness_pct`, `kelvin`, `color_name` and `profile` before they reach the entity. `turn_off` forwards the transition. The calls are blocking and carry the caller's context, so the logbook names who did it.

### `SwitchLight(PururuEntity, GroupEntity, LightEntity)`, for `switch.*`

A light over a real switch, on HA's `GroupEntity` as `SwitchGroup` and `LightGroup` are.

- **State.** It follows the real switch: `on`, `off`, `unknown`, `unavailable` or missing, with the same outcomes as `Light`. `assumed_state` is the real switch's.
- **What it offers.** `ColorMode.ONOFF` and no features, which is everything a switch exposes.
- **Commands.** Turning it on or off calls `switch.turn_on` or `switch.turn_off` on the real switch, blocking, with the caller's context. Light arguments such as brightness are ignored, and the UI doesn't offer them, since the mode is ONOFF.

### Both

- The group's `entity_id: [<real entity>]` attribute stays, so the more-info dialog shows the real entity.
- There is no restored state: a light always shows its real entity.
- The icon is HA's default for a light.
- The name comes from `name:`. `_identify` with a `name` now also clears the translation key (`_attr_translation_key = None`). `LightGroup` sets it to `"light"`, which HA would otherwise look up in pururu's translations and icons.

### Renames and taken IDs

- Renaming the pururu light's entity ID in the UI is followed, as for every entity.
- Renaming the real entity needs the YAML updated. Until then the pururu light is unavailable.
- If another integration already holds the ID, that's a logged error, and only that light isn't created (existing `_creatable`).

## Platform, manifest, CI

- `Platform.LIGHT` joins `PLATFORMS` (`const.py`). `light.py` adds `entry.runtime_data[Platform.LIGHT]`, as `switch.py` does.
- `manifest.json` goes to `0.1.6`. `dependencies` don't change, because `group` is already one. `iot_class` stays `calculated`.
- `sonar-project.properties` gets the `light.py` pair (`python:S1172` unused `hass`, `python:S7503` async without await), with a comment, as `switch.py` has.
- The dashboard doesn't change: it lists devices, not entities.

## Testing

`tests/test_lights.py`, shaped like `tests/test_switches.py`:

- **State, for both kinds:**
  - The light follows `on` and `off`.
  - A real `unknown` gives an available light with no state.
  - A real `unavailable`, or a missing real entity, gives an unavailable light.
  - The light follows the real entity going away and coming back.
  - `assumed_state` follows the real entity's.
- **What it offers:**
  - An on/off-only `light.*` gives ONOFF.
  - A bulb with brightness and colour gives its `supported_color_modes`, `color_mode`, `brightness`, `hs_color` and `effect_list`.
  - A change in the real light's capabilities is followed.
  - A `switch.*` always gives ONOFF.
- **Commands:**
  - `light.turn_on` with brightness, colour and transition reaches the real light with them.
  - `light.turn_off` with a transition does too.
  - A switch-backed light calls `switch.turn_on` and `switch.turn_off`.
  - Every call carries the caller's context.
  - Turning on without the real entity does nothing.
- **Names and IDs:**
  - The name is `name:`, the same in pt-BR.
  - There is no translation key.
  - The ID is `light.pururu_<key>_light_<entity key>`.
- **Refused:**
  - another domain;
  - `light.pururu_…` or `switch.pururu_…`;
  - no `name`, or an empty or blank one;
  - an unknown key;
  - an empty block;
  - a key that isn't a slug;
  - the same real entity in `switches:` and `lights:` of one device, in either order in the YAML (the message names the features in `FEATURES` order).
- **Accepted:**
  - the same real switch as a light in one device and a switch in another;
  - `switches: pump` next to `lights: pump`;
  - a device with only `lights:`.
- **Lifecycle:**
  - an ID already taken;
  - the pururu light renamed in the UI;
  - a renamed pururu entity used as `entity:` (skipped and logged);
  - a reload that drops a light (its entity is removed);
  - a restart.

The `features/standing.py` extraction is checked by `tests/test_switches.py` passing unedited. The contract test (`tests/test_features.py`) covers `lights` unchanged: its namespace, its platform in `PLATFORMS`, its example, and that it provides nothing.

## Documentation

- `docs/features/lights.mdx` (new), in the `Features` group of `docs.json`. It covers:
  - its settings (`<Property>`);
  - `light.*` against `switch.*`, and what each offers;
  - replacing the bulb or relay without changing the ID;
  - one configured feature per real entity in a device;
  - the light showing twice in an area when the real entity's device is there too;
  - renaming the real entity.
- `docs/features/switches.mdx`: "`lights` comes next" becomes a link. A relay that is a light goes in `lights:`, and the one-feature-per-device rule is stated.
- `docs/concepts/entity-ids.mdx`: the platform `light`, and the namespace `light` in the table.
- `docs/concepts/devices-and-features.mdx`: `lights` in the features table and in Provides / Needs (nothing / nothing). A feature "passes commands on" for `switches` and `lights`.
- `docs/index.mdx`: "It never acts on its own" names lights too.
- `docs/reference/configuration.mdx`: `lights:` in the example and the features list, and the one-configured-feature rule.
- `docs/reference/troubleshooting.mdx`:
  - the error `switches: switch.x is already in lights`;
  - the log line `… is a pururu light: name the real one; not creating …` next to the switch one (both `is a pururu <domain>`);
  - a new section, "A light is `unavailable`".
- `docs/develop/architecture.mdx`, `docs/develop/index.mdx` and `docs/develop/writing-a-feature.mdx`:
  - `light.py` and `features/standing.py`;
  - a class per domain of the real entity (`KINDS`);
  - `_identify` clearing the translation key.
- `docs/develop/testing.mdx`: `test_lights.py` in the table.
- `CLAUDE.md`: `light.py` next to `switch.py`, `lights` next to `switches`, and `features/standing.py`.
- Checked with `pnpm docs:check`.

## Later: `groups:`

Not in this PR. It gets its own spec and PR. It's written down here so that nothing in `lights` gets in its way.

```yaml
sala:
  name: Sala
  lights:
    teto: {entity: light.sala_teto, name: Teto}
    lustre_1: {entity: light.lustre_1, name: Lustre 1}
    lustre_2: {entity: light.lustre_2, name: Lustre 2}
  groups:
    lustre:
      name: Lustre
      lights: [lustre_1, lustre_2]
# → light.pururu_sala_light_lustre_1, light.pururu_sala_light_lustre_2
# → light.pururu_sala_group_lustre: a LightGroup of the two above
```

- A group gathers pururu entities of its own device by their keys, not real entity IDs. Each bulb stays a light of its own, and the group turns them together. A group has a type (light, switch…), which sets its platform and what it may gather. How the YAML states it is decided in its spec: the key inside the group (`lights:`) is one way.
- The namespace is `group`, not `light_group`: the contract test refuses a namespace that is another one followed by `_`.
- The core needs something new. Today a feature takes from another only through `<capability>_from`, and only fixed entity keys. A group takes the configured entity keys of `lights`, in another namespace. `_build` and `_creatable` will resolve them: the current entity ID (renames followed), and no group when a member isn't created.
- A light that goes from one bulb (`lights: lustre`) to several (`groups: lustre`) changes its ID, from `light_lustre` to `group_lustre`. It's a different thing, and the docs will say so.

## Risks

- `LightGroup`, `SwitchGroup` and `GroupEntity` are classes of HA's `group` integration, with no promise of a stable API. The project already accepts this for `Mirror` and `Switch`. `group` is in `dependencies`, and the tests catch a break when HA is updated. Reimplementing state following and command forwarding would be much more code, and more bugs.
- The pururu light and the real entity are two entities for one thing. Voice and area-wide actions reach both. Switching both is harmless, but "how many lights are on" counts two, and a real light and its pururu light in one area both answer "turn off the lights in Sala".
