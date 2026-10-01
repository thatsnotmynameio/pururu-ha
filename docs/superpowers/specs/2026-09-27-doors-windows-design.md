# Doors and windows — design

Version: pururu 0.1.14. Branch: `feat/doors`. Follows #22 (ready-made alerts, 0.1.13), #20 (Alert2's alerts, 0.1.12) and #19 (`modes`), whose cycle code in `features/cycle/` the openings reuse.

## Goal

A device can be a door or a window, as a device can be an appliance: `door` and `window` are pururu's own abstractions, not the real hardware. The contact sensor is required: it opens and closes the door, and each opening is a cycle. Other sources are optional extras that describe the openings: events now (who opened, how, which way; denied attempts; the doorbell), a lock and more later.

pururu knows nothing of any integration. The user names the entities, says what each event type means for the door and which attribute holds each field.

```yaml
pururu:
  devices:
    porta_frente:
      name: Porta da frente
      area: entrada
      door:
        contact: binary_sensor.porta_frente
        statistics:
          openings: [today, week, month]
          open_time: [today, week]
        events:
          - entity: event.porta_frente_access
            types: {access_granted: opening, access_denied: denied}
            fields: {who: actor, how: authentication, direction: direction}
          - entity: event.porta_frente_doorbell
            types: {ring: ring}
    janela_quarto:
      name: Janela do quarto
      window:
        contact: binary_sensor.janela_quarto_contact
# → binary_sensor.pururu_porta_frente_door_open        "Porta da frente Aberta"
# → sensor.pururu_porta_frente_door_last_opened_by     "Alex Doe"
# → binary_sensor.pururu_janela_quarto_window_open              "Janela do quarto Aberta"
```

## What such hardware shows

An example: two doors, each with a contact and an access controller's `event.*`:

| Situation | Contact | Event |
|---|---|---|
| Entry, front | opens | `access_granted`, `actor: Alex Doe`, `authentication: PIN_CODE`, `direction: entry`, about 0.9 s **after** the contact opens |
| Entry, back | opens | the same, about 0.5 s after |
| Exit, back (button → automation → relay) | opens | `actor: N/A`, `authentication: REX`, `direction: exit`, about 0.8 s after |
| Exit, front | opens | **no event** (the handle, from inside) |
| HA restart | no change | `event.*` comes back with the **same old timestamp** as its state: not a new event |

So an event is matched to an opening by time, in both directions. An opening without an event is normal. And an event is new only when its state (the timestamp) changes to a new value.

## Decisions

| Question | Decision |
|---|---|
| What a door is | A feature, like `appliance`: pururu's abstraction, with the real entities inside its block. Not a device `type:` (the device keeps no type) and not a `configured` feature of a room device (`doors: {frente: …}` in `biblioteca`), which would make a lock and a contact of one door hard to keep together. |
| Door and window | Two features, `door` and `window`, with one schema and one code. They differ only in namespace, `device_class` and texts. A window rarely has events, but nothing refuses them (a glass-break or vibration event would fit). |
| Rejected: one feature `opening` with `kind: door\|window` | The door is the abstraction; a `kind` makes it a detail. |
| Shared code | A package `features/opening/` with a function that builds a `Feature` for a namespace and a device class. `lights` refused a `Feature` factory because each domain had its own details; door and window have none by definition. |
| Required and optional | `contact` is required and makes the cycle. `statistics` and `events` are optional; a lock and other sources will be optional keys too. |
| Who and how | From `event.*` entities the user lists, with a fixed vocabulary pururu defines: meanings `opening`, `denied`, `ring`; fields `who`, `how`, `direction`. The user maps their `event_type`s to meanings and their attribute names to fields. |
| Rejected: free fields (`fields: {who: {attribute: actor, name: Quem}}`) | The door wouldn't know what a field is: no translations, no behaviour of its own, and `alerts`/`reactions` would refer to keys pururu can't document. |
| Rejected: copying every attribute of the event | Nothing to show in a dashboard or refer to from `alerts` and `reactions`. |
| Field values | The event's raw text (`PIN_CODE`, `entry`), not translated: pururu doesn't know the integration's values. |
| An opening is a cycle | Reuses `features/cycle/` (last cycle, totals, statistics); `door` and `window` provide `cycle`, so `phases` and `modes` can use `cycle_from: door`. |

## Configuration

`door:` and `window:` are features (keys of `FEATURES`) with `namespace="door"` and `namespace="window"`. A device can have either alone, or both (their IDs differ by namespace).

- `contact` is required: a `binary_sensor.*`, not `binary_sensor.pururu_…` (`standing.real_entity`). A pururu binary sensor renamed in the UI gets past that; `build()` checks the registry, logs `<contact> is a pururu binary sensor: name the real contact`, and `open` stands for nothing (`unavailable`), its other entities kept, so a reload never flip-flops.
- `statistics` is optional: `openings` and `open_time`, each a list of periods, as `appliance`'s `cycles` and `runtime` (`PERIOD_LIST`).
- `match` is optional, a time period, default `{seconds: 5}`: how far from the opening an `opening` event may be, before or after.
- `events` is optional, a list with at least one item. Each item:
  - `entity` is required: an `event.*`.
  - `types` is required, at least one: `event_type` → meaning, one of `opening`, `denied`, `ring`.
  - `fields` is optional: field → attribute name, fields among `who`, `how`, `direction`. The attribute name is any non-blank string.
- Unknown keys are refused at every level, and so are an empty `events: []` and an empty `types: {}`.

## Entities

Entity keys are local to the namespace: `door` below, `window` alike.

### Always, from the contact

| Entity key | Platform | Value |
|---|---|---|
| `open` | binary_sensor | Open or closed, `device_class` `door` (`window`) whatever the real sensor's. It starts and ends each opening. |
| `last_opened` | sensor, timestamp | The last opening's start |
| `last_closed` | sensor, timestamp | The last opening's end |
| `last_open_duration` | sensor, s | The last opening's duration, in seconds: a door opens for seconds, not minutes |
| `openings_total` | sensor | Openings ever |
| `open_time_total` | sensor, h | Time open ever |
| `openings_<period>`, `open_time_<period>` | sensor | The periods in `statistics` only |

`LastCycleValue` takes its keys from its descriptions already: the door defines its own (`last_opened`, `last_closed`, `last_open_duration`) and `features/cycle/last.py` doesn't change. `CyclesTotal` and `RuntimeTotal` take an optional `entity_key` (defaults `cycles_total`, `runtime_total`), for `openings_total` and `open_time_total`.

### With events

Created only when some event of the block gives that meaning or field:

| Entity key | When | Value |
|---|---|---|
| `last_opened_by` | an `opening` type and `fields.who` | who made the last opening |
| `last_opened_via` | an `opening` type and `fields.how` | how the last opening was made |
| `last_direction` | an `opening` type and `fields.direction` | which way the last opening went |
| `last_denied` | a `denied` type | the last denied attempt's time, with attributes `who`, `how`, `direction` for the mapped fields |
| `last_ring` | a `ring` type | the last ring's time |

- The fields are the **last opening's**. An opening with no event sets them to `unknown`. They never keep an earlier opening's values, so an exit by the front door doesn't show the last entry's PIN again.
- A mapped attribute missing from the event leaves its field `unknown`.
- All are restored after a restart.

## Behaviour

- **Contact `unavailable` or `unknown`:** `open` holds its last state and the opening goes on, as `Running` holds while the plug has no value. The next real value counts.
- **Restart during an opening:** the opening's start is restored (`CycleStart`). A contact read closed ends the opening once HA has started (`async_at_started`, as `modes`), when every entity of the door listens.
- **A contact already open at first set-up:** an opening starts then.
- **An event's time is its state** (an event entity's state is the time of its last event), not when pururu sees it. The same state again (attributes only), `unavailable`, `unknown` and anything not a time don't count. A restart replaying an old event is harmless: its time is far from any new opening, and `last_denied`/`last_ring` take only a time later than theirs.
- **A field's value** is the attribute as text (`42` → `"42"`); a missing attribute is `unknown`.
- **An `event_type` not in `types`:** ignored.
- **`opening` before the contact:** it waits up to `match`. The contact opening in that time takes it; otherwise it's dropped.
- **`opening` after the contact:** up to `match` after the opening's start, it fills the opening's fields, even if the contact has already closed. The first event wins; later ones are ignored for that opening.
- **`denied` and `ring`:** update their entities at once, without matching an opening.

## Testing

- `tests/test_features.py` covers `door` and `window` through `FEATURES` with no change: translations, icons, a valid example.
- `tests/test_opening.py`, parametrized over `door` and `window`:
  - openings, last values and totals; statistics;
  - the forced `device_class`;
  - hold on `unavailable`; restart during an opening;
  - an `opening` event before, after and outside `match`; the first of two wins; a short opening closed before its event;
  - an opening without an event setting the fields to `unknown`;
  - a restart repeating the `event.*` state; an `event_type` not in `types`; a missing attribute;
  - `denied` with its attributes; `ring`;
  - `cycle_from: door` feeding `phases`;
  - validation: every refused configuration above.
- The event scenarios replay the front door's sequences: entry by PIN 0.9 s after the contact, exit by REX, exit by the front door with no event.

## Docs and release

- `docs/features/door.mdx` and `docs/features/window.mdx`, the latter short and linking to the former for what they share, with sidebar entries in `docs.json`.
- Sonar suppressions only if a new platform appears (none: binary_sensor and sensor exist).
- `manifest.json` version `0.1.14`.

## Later

- `lock:` in `door`: a `lock.*`, its state and actions.
- Meanings and fields added to the vocabulary when a source needs them.
