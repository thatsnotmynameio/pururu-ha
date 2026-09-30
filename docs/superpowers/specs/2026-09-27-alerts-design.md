# Alerts — design

Version: pururu 0.1.6. Branch: `feat/alerts`. Builds on #13 (entity namespaces, 0.1.5).

## Goal

A device can declare **alerts**: conditions on its own entities that mean something is wrong. Each alert is a native `binary_sensor` with device class `problem`, inside the device: `on` while the problem lasts, `off` when it's fine.

This is **detection only**. Telling someone (notifications, reminders, acknowledging, messages) is a later, separate piece of work. Until then, whatever delivers alerts today (Alert2, HA's `alert`, an automation) reads these entities; pururu depends on none of them.

```yaml
pururu:
  devices:
    clothes_washer:
      name: Tanquinho
      appliance: {...}
      alerts:
        long_cycle: {name: Ciclo longo, when: appliance_running, is: "on", for: {hours: 3}, priority: medium}
        overload: {name: Sobrecarga, when: appliance_power, above: 2500, for: {minutes: 1}, priority: high}
        plug_offline: {name: Tomada offline, when: appliance_power, is: unavailable, for: {minutes: 10}}
# → binary_sensor.pururu_clothes_washer_alert_long_cycle   "Tanquinho Ciclo longo"
# → binary_sensor.pururu_clothes_washer_alert_overload
# → binary_sensor.pururu_clothes_washer_alert_plug_offline
```

## Decisions

| Question | Decision |
|---|---|
| Detection and delivery | Split. This spec is detection. Delivery (who is told, how often, acknowledging, message texts) is its own spec later. |
| Depend on Alert2 | No. Alert2 is a HACS integration whose only public API for other integrations covers event alerts; its condition alerts can be created only through internal code. Its entities (`alert2.*`) have no device or area either. pururu's alerts are plain binary sensors, and one Alert2 `generator` block (or HA's `alert:`) can consume all of them. |
| Reuse HA's condition engine or triggers | No. Conditions (`helpers/condition.py`) only answer when asked and never call back; `numeric_state` has no `for`, and `unavailable` evaluates to false. Triggers fire only on a transition (a value already above a limit at start never fires) and lose `for` on restart. pururu already tracks a value with `for` in `phases` and `running`. |
| How expressive a condition is | One condition per alert: `when` + `is`, or `above`/`below`, + optional `for`. It's Alert2's model as well. Several conditions ANDed (`all: [...]`) can be added later without changing any YAML written for this one; `when`, `is`, `above`, `below` and `for` keep their meaning inside such a list. |
| What `when` names | An entity key of **the same device**, as it appears in the entity ID (`appliance_running`, `switch_sprinkler`, `phase_current`), not an entity ID. pururu checks it at configuration time and follows renames. An alert can't watch another alert. |
| The watched entity has no reading (`unknown`, `unavailable`, not a number) | The alert **keeps its state**, and a pending `for` is cancelled, as `running` and `phases` do. Rejected: turning off (the alert would clear just when the plug disappears) and going `unknown` (a third state every consumer must handle). `is: unavailable` still works, for an offline alert. |
| Priority | Part of detection: how bad the problem is. `priority: low | medium | high`, default `low`, as an attribute. Delivery decides what to do with it. |
| Messages (`message`, `done_message`) | Not here: they are notification text, which is delivery. |
| Restart | The alert comes back with its restored state. A pending `for` starts over, as in `phases`. |
| Deferred | Several conditions per alert; hysteresis; a minimum time back to normal before clearing (`delay_off`); a per-device "any problem" sensor; a feature for real binary sensors (doors, windows) so their alerts can live in pururu. |

## Configuration

`alerts:` is a feature: a map of **alert key → alert**, with at least one alert. The key is a slug and ends the entity ID after the namespace `alert`.

| Key | Required | What it is |
|---|---|---|
| `name` | yes | The name shown after the device's name. Not empty. Not translated. |
| `when` | yes | An entity key of another feature of this device, as in its ID. |
| `is` | one of `is` or `above`/`below` | The state that is a problem: `"on"`, `wringing`, `unavailable`… YAML's `on`/`off` without quotes (booleans) become `"on"`/`"off"`. |
| `above`, `below` | one of `is` or `above`/`below` | A number is a problem when strictly above `above` and strictly below `below`. At least one; `above` lower than `below`. |
| `for` | no | How long the condition must hold before the alert turns on. A time period; default 0. |
| `priority` | no | `low`, `medium` or `high`. Default `low`. |

`is` together with `above` or `below` is a configuration error.

Configuration errors added:

- `alerts: <key> is not an entity key of another feature of this device`, where `<key>` is the `when` (the check lives in the core, for any feature that refers to entity keys).
- The usual schema errors (a missing `name`, `is` with `above`, `above` not lower than `below`, an unknown `priority`).

Because a switch's entity keys come from its block, `when: switch_sprinkler` is valid only when the device has the switch `sprinkler`. Every entity key a feature *can* create counts, as for `_entity_ids_distinct`: `when: appliance_runtime_month` is valid even without `statistics`, and the alert simply isn't created (its entity isn't).

## Behaviour

- **Holds:** for `is`, the watched state equals it. For `above`/`below`, the watched state is a number (`reading()`) inside the range.
- **No reading:** the watched entity is missing, `unknown` or `unavailable`, or (for `above`/`below`) not a number. Then the alert keeps its state and cancels a pending `for`. Exception: `is: unavailable` and `is: unknown` both mean "no reading" and hold while the entity is `unavailable`, `unknown` or missing (decided after the first implementation: a plug reconnecting passes through `unknown`, which would otherwise clear the alert and restart `for`).
- **Holds, alert off:** it turns on after `for` (at once with no `for`). Stops holding before that: the pending `for` is cancelled.
- **Doesn't hold:** the alert turns off at once, and a pending `for` is cancelled.
- **Start and reload:** the alert restores its last state, then follows the watched entity once HA has started, and evaluates its current state. A condition already holding starts its `for` from now; with no reading, the restored state stays. A watched entity that isn't there yet, or whose state HA restored while it isn't loaded (`restored: true`), is no reading: at a start or reload they pass through `unavailable`, which must not raise an `is: unavailable` alert.
- **Follows renames:** the watched entity's current ID comes from the registry (`current_entity_id`), and a rename reloads the entry, as for every pururu entity.
- **Dependency:** when the watched entity isn't created (its ID is taken, or it follows something not created), the alert isn't created either, with the usual logged error (`… follows …, which is not created; not creating it`).

## Entity

| | |
|---|---|
| ID | `binary_sensor.pururu_<device key>_alert_<alert key>` |
| Name | `<device name> <name>` |
| Device class | `problem`: states "Problem"/"OK", HA's alert icons |
| Attributes | `priority`; `watches`: the watched entity's current ID (not `entity_id`, which HA reads as a group's members) |
| Restores | its state |

No entity category: an alert is a primary entity of its device.

## Contract changes

A feature can now watch entities of **other features of the same device**, named by their entity key in the YAML. Today that only happens through `<capability>_from`, which names a feature, not an entity.

- `Feature.refers: Callable[[Any], Iterable[str]] | None = None`: the entity keys of the device (qualified, `appliance_running`) that its validated block names. For `alerts`: every alert's `when`.
- **Validation (`_device`):** every key `refers` returns must be a qualified entity key of **another** feature of the device (fixed `entity_keys` and a configured feature's block keys, whatever the settings). Otherwise the error above.
- **Build (`_build`):** `inputs` also carries, for each key `refers` returns, the current entity ID of that key (`current_entity_id`, with the platform of the feature that owns it), keyed by the qualified key.
- `PururuEntity.follows: tuple[str, ...] = ()`: qualified entity keys of other features of its device that the entity reads. `_build` adds their unique IDs to what the entity follows, so it isn't created when they aren't. (`sources` stays: entity keys of its own feature.)
- A helper, shared by `_device` and `_build`, maps a device's qualified entity keys to their feature and platform.
- `_creatable` counts an entity the device's settings don't build (`appliance_runtime_month` without `statistics`) as not created, so whatever follows it isn't created either. Its own log line says why and names the entity ID (`_build` passes the entity IDs of what entities watch): `<alert> watches <entity>, which this device's settings don't create (turn it on, or watch another entity); not creating it`. Today every source is always built, so nothing else changes.

The alerts feature: `namespace="alert"`, `configured=Platform.BINARY_SENSOR`, `entity_keys={}`, `refers` as above, `features/alerts.py`, registered in `FEATURES`.

## Tests

- **Contract (`tests/test_features.py`):** runs over `alerts` unchanged (example valid, unknown keys refused, platform set up). A new check: `refers` of each feature's example returns keys as slugs.
- **Core (`tests/test_init.py`), with made-up features:** a feature that refers to another's entity key gets its current ID in `inputs`; a reference to an unknown key, or to the feature's own key, is refused; an entity whose `follows` isn't created isn't created, with the logged error; a rename of the referred entity reaches it.
- **Alerts (`tests/test_alerts.py`), on real `appliance` and `switches`:**
  - `is` with and without `for`; `above`, `below` and a range, strict at the limits; `for` cancelled when the condition stops holding.
  - No reading keeps `on` and keeps `off`, and cancels a pending `for`; `is: unavailable` with `for` turns on for a plug gone offline, and for a missing entity.
  - YAML `on` unquoted equals `"on"`.
  - Restart: restored `on` stays on while the condition holds; restored state stays with no reading; a holding condition starts `for` over.
  - Renaming the watched entity; the watched entity's ID taken → no alert, logged.
  - Refused blocks: no `name`, empty `name`, `is` with `above`, neither, `above` ≥ `below`, unknown `priority`, `when` naming an alert or an unknown key.
  - Entity: ID, name (and the same in Portuguese), device class, `priority` default and set, `watches` attribute.

## Docs

- New `docs/features/alerts.mdx`, in the `Features` group of `docs.json`: settings, behaviour, entity, and **Getting notified**, showing that delivery is outside pururu for now, with an Alert2 `generator` block over `binary_sensor.pururu_*_alert_*` (condition `{{ is_state(genEntityId, 'on') }}`, priority from the attribute) and HA's `alert:` pointed at one alert.
- `concepts/entity-ids`: `alerts` in the namespace table.
- `concepts/devices-and-features`: `alerts` in the table (needs: entities of other features, through `when`).
- `reference/configuration` and `reference/troubleshooting`: the new error.
- `develop/architecture` and `develop/writing-a-feature`: `refers`, `inputs` for referred keys, and `follows`.
- `CLAUDE.md`: features can refer to other features' entity keys (`refers`, `follows`).

## Release

`manifest.json` goes to `0.1.6`.
