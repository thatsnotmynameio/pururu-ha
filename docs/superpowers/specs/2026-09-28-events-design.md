# pururu's events — design

Version: 0.1.19.

## Goal

Send what pururu's entities do to an outside system (the owner's: n8n, through a webhook), generically. pururu doesn't speak HTTP: it fires **its own events on HA's bus**, one per state change of an entity it created, carrying the change and a snapshot of its device. Whatever consumes HA events takes them from there: for a webhook, the user's automation calling a `rest_command` of their own.

```yaml
pururu:
  events: [state_changed, reading]   # either, both, or none (the default)
  devices: ...

rest_command:
  n8n_pururu:
    url: !secret n8n_pururu_url
    method: post
    headers:
      X-Pururu-Token: !secret n8n_pururu_token
    content_type: application/json
    payload: "{{ event | tojson }}"

automation:
  - alias: pururu → n8n
    mode: queued
    max: 1000
    triggers:
      - trigger: event
        event_type: [pururu_state_changed, pururu_reading]
    actions:
      - action: rest_command.n8n_pururu
        data:
          event: "{{ trigger.event.data }}"
```

## Decisions

| Question | Decision |
|---|---|
| Events or states | States. Every fact pururu knows is some entity's state (a cycle's end is `last_cycle_end`, who opened a door `last_opened_by`, an alert its binary sensor), so a second, "domain" event would duplicate them. What a domain event would add, a fact in one piece, comes from the snapshot: `last_cycle_end` is written last, so when it changes the snapshot already holds that cycle's start, duration and energy. |
| Who sends | HA. pururu fires bus events; a `rest_command` in the user's automation posts them. Rejected: pururu posting itself (`webhook.py`: an HTTP client, URL and secrets, a queue, failure logging, all things HA already has), and pururu generating that automation and `rest_command` (`rest_command` takes no `rest_command pururu:` key, so the user would hand pururu their whole `rest_command:` block, with secrets inside a generated file). The bus events also serve any other consumer (Node-RED, an automation, the event developer tool), and "filters, later" is a condition in the user's automation. |
| Two classes | `pururu_state_changed` for entities with no `state_class` (facts: binary sensors, switches, lights, modes, timestamps, who opened), `pururu_reading` for those with one (series: power and energy mirrors, phases, totals, meters). HA's own line between what goes to long-term statistics and what doesn't, so no list of entity keys to maintain. `cycles_total` is a counter, so a reading; the cycle's end still comes as a change (`last_cycle_end`), `cycles_total` already updated in its snapshot. |
| Opt-in | Off by default: every bus event is recorded by the recorder, and readings change every few seconds. Each class is enabled on its own, and a class not enabled is never fired. |
| `event_id` | A new ULID per change (`homeassistant.util.ulid.ulid_now`), made when the change happens: unique, ordered by time, for deduplication downstream. Not the state's `context.id`: one context covers several changes (a cycle's end writes four sensors in one). |
| `event_name` | `<device>.<key>` (`washer.appliance_last_cycle_end`): stable across UI renames, one field to route on. |
| `event_class` | The class in the data too (`state_changed`, `reading`): the `rest_command` posts `trigger.event.data`, so the event type doesn't reach the webhook, and one webhook can take both. |

## The events

Event types `pururu_state_changed` and `pururu_reading`, the same data:

```json
{
  "event_id": "01J8Z3K4QW6N5V2XK0M7T9R8YB",
  "event_name": "washer.appliance_last_cycle_end",
  "event_class": "state_changed",
  "entity_id": "sensor.pururu_washer_appliance_last_cycle_end",
  "device": "washer",
  "device_name": "Lavadora",
  "key": "appliance_last_cycle_end",
  "old": "2026-09-27T20:10:00+00:00",
  "new": "2026-09-28T09:52:00+00:00",
  "time": "2026-09-28T09:52:00.123456+00:00",
  "attributes": {"device_class": "timestamp", "friendly_name": "Lavadora Last cycle end"},
  "states": {
    "appliance_running": "off",
    "appliance_last_cycle_start": "2026-09-28T09:00:00+00:00",
    "appliance_last_cycle_duration": "52.0",
    "appliance_last_cycle_energy": "0.42",
    "appliance_last_cycle_end": "2026-09-28T09:52:00+00:00"
  }
}
```

| Field | What |
|---|---|
| `event_id` | ULID, new per event. |
| `event_name` | `<device>.<key>`. |
| `event_class` | `state_changed` or `reading`: the class, as in `events`, since a webhook receives the data without HA's event type. |
| `entity_id` | The entity's current ID (a UI rename is followed). |
| `device` | The device's key in the YAML. |
| `device_name` | The device's `name`. |
| `key` | The entity key in its namespace, as its unique ID after `pururu_<device>_` (and its translation key): `appliance_last_cycle_end`, `mode_heating_cycles_total`. |
| `old`, `new` | The states, as HA's strings. |
| `time` | The new state's `last_changed` (ISO 8601): when it changed, not when it was fired. |
| `attributes` | The new state's attributes. |
| `states` | Every created entity of the device with a state, by `key`, as HA's strings, read when the event is fired. |

The event is fired with the new state's `context`, so the logbook and traces link it to what caused the change.

## What fires

For each enabled class, a state change of an entity **the entry created** (in `entry.runtime_data`; one not created, its ID held by another integration, isn't pururu's), classed by whether its new state has a `state_class` attribute (a capability attribute: present even while unavailable). Not fired, as no real change:

- the entity appearing or going (old or new state `None`), as at every reload;
- the old state being the restored placeholder (`restored: true`) that HA shows at start-up until pururu loads: without this, every restart would say `last_cycle_end` changed, with no cycle;
- a change of attributes alone (same state string).

`unavailable` and `unknown` are fired: they are real states.

## Configuration

`events`, optional, at the top of the `pururu` block: a list of `state_changed` and `reading`, each once. A schema of its own (`ALLOW_EXTRA` would let a typo through); an unknown value is refused. Absent or empty: no event is fired and nothing listens. `pururu.reload` applies a change. `events` alone doesn't create the entry: with no device there is nothing to fire.

## Code

- **`events.py`**, new: `CONF_EVENTS`, the `SCHEMA`, the two event types, and `async_setup(hass, entry, classes, devices)`, where `devices` gives, per device key, its name and its created entities (current entity ID → key). It tracks those entity IDs with `async_track_state_change_event`, filters, builds the data and fires. Its unsubscription goes to `entry.async_on_unload`. Nothing when `classes` is empty.
- **`__init__.py`**: `events` in `CONFIG_SCHEMA`; `async_setup_entry` calls `events.async_setup` after the platforms are set up (the entities have their current IDs), from what it built: the key is the unique ID after `pururu_<device>_`.
- A reload rebuilds the tracked list, so a UI rename (which reloads the entry) is followed.

## Tests

`tests/test_events.py`, with `async_capture_events`:

- off by default, and with each class alone: the other class is never fired;
- the data, exactly, for a change and for a reading, `event_class` naming each; `event_id` a ULID, different per event; the event's context is the state's;
- the snapshot at a cycle's end holds that cycle's duration and energy;
- classing: a mirror of a power sensor is a reading, `running` a change;
- not fired: at setup, at a reload, at a restart (restored placeholder), on a change of attributes alone, for an entity not created (its ID held by another integration);
- fired for `unavailable`;
- a UI rename: the event carries the new `entity_id`, the same `key` and `event_name`;
- the schema refuses an unknown class and a repeated one; `pururu.reload` turns a class on and off.

## Docs

- `docs/concepts/events.mdx`, new, in the Concepts sidebar: what fires and what doesn't, the two classes, the data, the recipe above (`rest_command` + automation), the n8n side (a Webhook node with Header Auth, a Switch on `event_class` or `event_name`, `states` for the cycle's values), and the recorder: `recorder: exclude: event_types: [pururu_reading]` (or both), since the values are already recorded as the entities' states.
- `docs/reference/configuration.mdx`: `events`.
- README: one line linking to the page.

## Out of scope

Filters (by device, key or class beyond the two), pururu posting HTTP itself, retries and failure logging (the `rest_command`'s, the automation's).
