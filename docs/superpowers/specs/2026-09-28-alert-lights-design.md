# Alert lights — design

Version: 0.1.20 (planned as 0.1.19; the events took it first). Brings the alert lights of ha-config's `alertmanager` package (`pkg_alertmanager_lights`, the colour-lights channel and `light.pkg_home_lights_alert`) into pururu, driven by pururu's own alerts.

## Goal

While an alert is on, some lights show it: red, orange or blue breathing by priority. When the last alert that uses a light ends, the light turns green for a while, then off, and whoever used it before is told it is free. Today this is a YAML automation in ha-config that watches Alert2's package alerts; pururu's own device alerts never take the lights.

Here pururu does it for its alerts. An alert opts in (`lights: true` or a group's name); a light is borrowed only by the alerts that name it, and handed back only once none of them is on.

```yaml
pururu:
  config:
    alerts:
      lights:
        groups:
          default: {pool: [led]}
  devices:
    laundry_washer:
      name: Máquina de lavar
      appliance: {power: sensor.washer_plug_power, running: {threshold: 4}}
      alerts:
        long_cycle: {for: {hours: 3}, lights: true}
# long_cycle on → light.pururu_pool_light_led breathes orange (medium) every 15 s
# long_cycle off → green 50 % for 120 s → off → event pururu_alert_lights_released
```

## Decisions

| Question | Decision |
|---|---|
| Which alerts drive lights | pururu's alerts only (`binary_sensor.pururu_*_alert_*`, hand-written and ready-made), read from their own state and `priority`. Not Alert2's: the lights don't depend on Alert2. ha-config's package alerts (the doors) lose their light until they move to pururu. |
| Which of them | Opt-in per alert: `lights: true` (the `default` group) or `lights: <group>`. Without `lights`, nothing changes. Rejected: every alert (the washer's `no_cycle` would breathe for days), a priority threshold (mixes seriousness with "deserves a light"), opt-out (changes existing configurations). |
| How an alert names lights | Named groups under `config.alerts.lights.groups`, each a map of device key → keys of that device's `lights:`. `default` is the group of `lights: true`. Rejected: entity IDs in the alert (real entities outside feature blocks, no validation), a device → lights map in every alert (repeated). |
| What the manager does to a light | It calls the light's two methods, `turn_on(params)` and `turn_off()`: `light.turn_on` / `light.turn_off` on the pururu light. It never sets colour or brightness itself. |
| Capabilities | The light's job, not the caller's: it uses what it has and ignores the rest. HA's light service already drops brightness, colours, effect, flash and transition the light doesn't support; the pururu `Light` also drops an `effect` not in its `effect_list`; a `SwitchLight` (relay) ignores every parameter and turns on. Rejected: a signal per kind of bulb (much more YAML), light-specific "programs" (a second meaning for programs, which are scripts). |
| Colours and times | Global, in `config.alerts.lights`, one `turn_on` per priority and one for `resolved`, with today's behaviour as the defaults (low now blue). |
| `repeat` | Belongs to the priority, optional: it exists for one-shot effects such as Zigbee2MQTT's `breathe`. Without it, nothing is re-sent. |
| Durations | `repeat` and `for` take `{seconds: N}` only. |
| After `resolved` | `turn_off`, then the event `pururu_alert_lights_released` with the light: whoever used the light knows its rule and takes it back. Rejected: restoring the state from before the alert (pururu doesn't know the rule, only a snapshot). A reaction trigger on this event is a later version. |
| Someone else changes a borrowed light | During an alert it is put back at once; during `resolved` it is taken as a deliberate hand-back: released at once, not turned off. |
| How the manager knows a change is its own | The `Context` of its call: HA stamps the state changes a service call causes, the pururu light's and the real one's, with the call's context. Rejected: keeping the state the light settled in after each call and comparing (a settle window, a reapply limit, and Zigbee's colour drift). |
| Where it lives | Python in the integration (`alert_lights.py`), with the light's level shown as an attribute of the light. Rejected: a generated automation per light (the capability filter as Jinja, and it needs the automation include). |

## Configuration

### `pururu: config: alerts: lights:`

Optional, as is each key in it. `config` is a new top-level key of `pururu:`; `alerts.lights` is its only content for now. Each is a schema of its own (`ALLOW_EXTRA` propagates into plain dicts), so an unknown key is refused.

| Key | Type | Default |
|---|---|---|
| `groups` | map of group name (slug) → map of device key (slug) → list of keys of that device's `lights:` (at least one, no repeats) | none |
| `high` | priority | `turn_on: {color_name: red, brightness_pct: 100, effect: breathe}`, `repeat: {seconds: 15}` |
| `medium` | priority | `turn_on: {color_name: orange, brightness_pct: 100, effect: breathe}`, `repeat: {seconds: 15}` |
| `low` | priority | `turn_on: {color_name: blue, brightness_pct: 100, effect: breathe}`, `repeat: {seconds: 15}` |
| `resolved` | resolved | `turn_on: {color_name: green, brightness_pct: 50}`, `for: {seconds: 120}` |

- A priority is `{turn_on: <params>, repeat: {seconds: N}}`, `repeat` optional. `resolved` is `{turn_on: <params>, for: {seconds: N}}`, both required.
- `turn_on` is validated with HA's own `LIGHT_TURN_ON_SCHEMA` (`homeassistant.components.light`), so it takes `light.turn_on`'s data under its own names (`color_name`, `rgb_color`, `brightness_pct`, `effect`, `flash`, `transition`, …) and nothing else: no `entity_id`, no `target`. It may be empty (`turn_on: {}`: just on).
- `N` is a positive integer.
- A priority written replaces that priority's default as a whole, never merged key by key: writing `high: {turn_on: {color_name: purple}}` sends no `breathe` and has no `repeat`.
- `groups` may be empty or missing while no alert has `lights`.

### An alert's `lights`

`alerts.<key>.lights` and, for ready-made alerts, `alerts.<name>.lights` in the feature's block:

| Value | Lights |
|---|---|
| `true` | the group `default` |
| `<slug>` | that group |
| missing or `false` | none (today's behaviour) |

It is also the alert's attribute `lights` (the group's name), next to `priority`.

### Configuration errors

Checked with the device's other checks (`CONFIG_SCHEMA`), each a `vol.Invalid` naming where:

- `lights: true` without a `default` group: `device laundry_washer: alerts: long_cycle: there is no default group in config.alerts.lights.groups` (a ready-made alert: `device laundry_washer: appliance: alerts: offline: …`).
- `lights: <group>` naming no group: `device laundry_washer: alerts: long_cycle: outside is not a group of config.alerts.lights.groups`.
- In a group, a device that isn't under `devices:`: `config.alerts.lights.groups: outside: device pool is not in devices`; a key that isn't in that device's `lights:`: `config.alerts.lights.groups: outside: device pool has no light led`.
- A `color_name` HA doesn't know: `reed is not a colour name Home Assistant knows` (every call would fail).

### Resolved at setup

- A light of a group that isn't created (its ID is taken), or that the user disabled, is left out of the group; one not created is a warning: `light.pururu_pool_light_led is not created: the alert lights group outside goes without it`. The rest of the group goes on.
- An alert that isn't created (what it watches isn't) drives nothing.
- Lights and alerts are followed by their current entity IDs (`Device.current_entity_id`); a rename reloads the entry, as for any pururu entity.

A light may be in several groups; a group may hold lights of several devices; relays (`switch.*` in `lights:`) are accepted and only turn on and off.

## Behaviour

The manager keeps, per light of any group, only what can't be derived from the alerts: whether it is in `resolved` (with the `for` timer), and the `repeat` timer. Everything else is computed when needed.

- **Its alerts:** the created alerts whose `lights` group contains the light.
- **Its level:** the highest `priority` (`high` > `medium` > `low`) among its alerts that are `on`; none if none is. An alert that is neither `on` nor `off` (`unavailable` while it reloads, `unknown`) counts as it last was, so a reload never looks like an alert ending.
- **Borrowed:** it has a level, or it is in `resolved`.

### Transitions

| From | Event | Then |
|---|---|---|
| free | one of its alerts turns on | `turn_on` with that priority's parameters; `repeat` timer started |
| a level | its level changes (another alert on or off) | `turn_on` with the new priority's parameters; `repeat` restarted |
| a level | the last of its alerts turns off | `turn_on` with `resolved`'s parameters; `repeat` stopped; `for` started |
| `resolved` | one of its alerts turns on | `for` cancelled; `turn_on` with that priority's parameters |
| `resolved` | `for` ends | `turn_off`; free; `pururu_alert_lights_released` with `{"entity_id": <the light's entity ID>}` |
| a level | `repeat` fires | the same `turn_on` again |

Alerts that don't use a light never hold it: with one of its alerts on and an alert of another group on, only the first counts; the light is released once its own alerts are off, whatever else is on.

### Someone else changes the light

The manager follows every state change of each borrowed light:

- **The change carries a context of the manager's:** its own call caused it; ignored. The manager keeps its last few contexts per light, so a late report of an earlier call is still its own.
- **The light has no reading now** (`unavailable`, `unknown`): nobody took it; ignored.
- **Else, the light has a level:** `turn_on` with the current priority's parameters.
- **Else, the light is in `resolved` and the change has a `user_id` or a `parent_id`:** a person or an automation took it back on purpose, even as it comes back from no reading; `for` cancelled, free, `pururu_alert_lights_released`, no `turn_off` (PR review).
- **Else, the light is in `resolved` and its `for` ended while it had no reading:** `turn_off`, free, released.
- **Else, the light is in `resolved`** (back from no reading, the bulb's own report after the 5 s, a wall switch): `turn_on` with `resolved`'s parameters again, its `for` running on.
- **The light is free:** ignored, whoever changed it.

A light's commands run one at a time, in the order given; a command still waiting when a newer one is given is dropped. A slow `turn_off` of a release can't land after the next alert's `turn_on` (PR review).

A light without a reading is never called (HA would skip it and log a missing entity at every `repeat`): what it should show is sent once it's back. Resolved's `for` ending while it has no reading waits for it to be back to turn it off and release it (final review).

Disabling a followed light or alert reloads the entry (as for a program's target): a disabled alert has no state, so it counts as off and its lights go through `resolved`; a disabled light is left out (final review).

Each call gets a new `Context`. HA keeps a call's context on an entity for 5 s (`CONTEXT_RECENT_TIME_SECONDS`), so a change without a context of its own (a wall switch reported by Zigbee2MQTT) within 5 s of a call looks like the manager's and isn't put back until the next `repeat` or change. Accepted.

Turning a light off on purpose during an alert doesn't silence it: it comes back until the alert ends. Alert2's acknowledgement doesn't reach pururu.

### The light's attributes

Both light classes (`Light`, `SwitchLight`) gain:

| Attribute | Value |
|---|---|
| `alert` | `high`, `medium`, `low`, `resolved`, or absent when free |
| `alerts` | the entity IDs of its alerts that are on, absent when free |

The manager sets them and writes the light's state. `alert` is restored (below), from the extra restore data rather than the attribute: HA saves no attributes of an unavailable entity (final review).

### The method calls

- `light.turn_on` / `light.turn_off` on the pururu light, `blocking=True`, with the manager's new `Context`, so the logbook names pururu's alert lights.
- The pururu `Light` drops an `effect` its `effect_list` doesn't have before forwarding (HA's service only drops `effect` for a light without the effect feature).
- A call that fails (`HomeAssistantError`: the light unavailable, Zigbee2MQTT refusing) is a warning, `The alert lights couldn't call light.turn_on on light.pururu_pool_light_led: <error>`; the manager goes on, and the next `repeat` or change tries again. Never raised, never a failed setup.

## Start, reload and removal

- The manager starts once HA has started (`async_at_started`), as alerts follow what they watch only from then. It then evaluates every light and follows alerts and lights.
- `Light` and `SwitchLight` become `RestoreEntity`, for `alert` only. At start, per pururu light (every light of `lights:`, in a group or not):

| Restored `alert` | One of its alerts on now | Then |
|---|---|---|
| any | yes | `turn_on` with the current priority's parameters |
| a priority or `resolved` | no | `resolved` from the start: its `turn_on`, `for`, `turn_off`, released |
| absent | no | nothing |

  A restart during the green ends in a release (today it leaves the light green and unreleased); an alert that ended while HA was down hands the light back; a light that left every group (the YAML changed) while borrowed is handed back rather than left breathing. A light with a restored `alert` that is in no group now gets the same `resolved` run.
- **Entry reload:** unload cancels the timers and calls nothing. The next setup follows the table: an alert still on restores `on`, so the light isn't handed back nor flashed green.
- **Removing pururu** leaves the lights as they are.

## Code

- `custom_components/pururu/alert_lights.py` (new): the `config.alerts.lights` schema and defaults; resolving groups into current light entity IDs; the manager (per light: level, `resolved`, `repeat`, context check, start table, event). Started from `async_setup_entry` after the platforms, stopped on unload.
- `const.py`: `CONF_CONFIG`, the event name `EVENT_ALERT_LIGHTS_RELEASED = "pururu_alert_lights_released"`.
- `__init__.py`: `config` in `CONFIG_SCHEMA`; a cross check (`_alert_lights_resolved`) for the errors above; the created alerts with `lights` and the groups handed to the manager.
- `features/alerts.py`, `features/presets.py`: the optional `lights` key and attribute; `ProblemAlert` keeps it.
- `features/lights.py`: `RestoreEntity`, the `alert`/`alerts` attributes, `Light` dropping an unknown effect.

## Testing

`tests/test_alert_lights.py`, with the `ha` fixture and helpers (`setup`, `reload`, `restart`, `tick`, `fake`), recording `light.turn_on`/`turn_off` calls on the real lights:

- a medium alert breathes orange and re-sends every 15 s; high over medium, then back to medium when high ends; low is blue.
- two groups sharing a light: the highest of both; released only once both are off.
- an alert of another group on doesn't hold the light.
- last alert off: green 50 %, 120 s, off, `pururu_alert_lights_released` with the light; an alert during the green takes it again, no event.
- `repeat` missing: nothing re-sent.
- a change by someone else during an alert is put back; during `resolved` it releases at once without `turn_off`; the manager's own changes aren't put back; a free light is left alone.
- a relay light only turns on and off.
- an effect outside `effect_list` is dropped by the `Light`.
- a failing call is logged and the next `repeat` calls again.
- restart: alert on → level applied; restored `resolved` or priority with no alert on → `resolved` run and release; nothing restored → nothing.
- reload with an alert on: no green, no release; an alert `unavailable` for a moment doesn't release.
- a light of a group not created (ID taken) or disabled is left out, the rest works.
- a ready-made alert with `lights: true` drives the lights.
- configuration errors: no `default`, unknown group, unknown device or light in a group, unknown keys, `repeat`/`for` other than `{seconds: N}`, `turn_on` with `entity_id`.

`tests/test_features.py` keeps checking every feature's example.

## Docs

- `docs/concepts/alert-lights.mdx` (new, Concepts in the sidebar): the configuration, the defaults, the transitions, someone else changing a light, restart, the event.
- `docs/features/alerts.mdx`: `lights`, the attribute.
- `docs/features/lights.mdx`: `alert`/`alerts` attributes, the effect dropped, the light driven by alerts.
- `docs/reference/configuration.mdx`: `config`.
- `docs/reference/troubleshooting.mdx`: the new log messages.

## ha-config, after the release

Another PR there: remove `pkg_alertmanager_lights`, `sensor.pkg_alertmanager_channel_color_lights` and `light.pkg_home_lights_alert`; add `config.alerts.lights` (group `default: {pool: [led]}`) to `packages/pururu/pururu.yaml`; add `lights: true` to the washer alerts that should light up. `pkg_alertmanager_ack` stays. `pkg_alertmanager_lights_released` had no listener.
