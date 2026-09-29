# A reaction's retry — design

Builds on reactions (0.1.10) and reactions run programs (0.1.17). The first of a few conveniences for reactions; this one is resilience of a **time** trigger.

## Goal

A reaction at a time of day (`at`) or on the sun (`sun`) fires once. If it didn't run then (Home Assistant was restarting or down, the automation was off, its program was already running), nothing tries again until tomorrow. `retry` gives it more chances: the same occurrence, tried again a few times at an interval, each try skipped once the occurrence has run.

```yaml
pururu:
  devices:
    garden:
      name: Jardim
      switches:
        valve: {entity: switch.garden_valve, name: Válvula}
      programs:
        water:
          name: Regar
          sequence: [{turn_on: switch_valve}, {delay: {minutes: 20}}, {turn_off: switch_valve}]
      reactions:
        afternoon:
          name: Tarde
          at: "13:00"
          then: water
          retry: {times: 3, every: {hours: 1}}
# → automation.pururu_garden_reaction_afternoon triggers at 13:00, and at 14:00, 15:00, 16:00
#   only while water hasn't started since 13:00
```

## Decisions

| Question | Decision |
|---|---|
| Which sources | `at` and `sun` only. Their occurrence has a time that comes whether or not HA was running, so a later try recovers a missed one. A state reaction (`when`, `entity`) is an event: HA down while it happens never sees it, and a retry hanging off it misses it too; it could only cover a busy program, with the state still holding (the same trigger with a growing `for`), lost at a restart. Left for later, with a "recovery" of state reactions (pururu remembering the last real state across a gap). `retry` on a state reaction is a configuration error. |
| What "ran" means | With `then`: **its program started** (its script's `last_triggered`), from this reaction or anywhere else. Without `then`: **the automation fired** (its own `last_triggered`). A program started covers a trigger that didn't fire, and also one that fired while the program was running (the `if` not taken). Rejected: a state to reach (`until: switch_valve on`), which is a program's resilience, not a trigger's. |
| Since when | Since the occurrence: a try `k × every` after it looks for a run in the last `k × every`, plus a minute of slack (a trigger's run is recorded a few milliseconds after its time; the slack keeps the occurrence's own run inside the window). |
| How a try is skipped | A **condition** of the automation, not an action: a skipped try isn't a trigger (HA counts one only once its conditions pass), so `triggered_total` counts the occurrence and the tries that ran, never the skipped ones. The trace shows the condition failing. The occurrence's own trigger always passes. |
| Where the memory lives | In HA: `last_triggered` of the automation and of the script, which HA restores at a restart. pururu adds no entity and keeps no state. A try after a restart (HA down from 12:59 to 13:30) sees no run since 13:00 and runs. Accepted: HA saves restored states every 15 minutes and at a clean stop, so an abrupt stop within 15 minutes of a run forgets it, and a try runs again. A new reaction (or a program that never ran) has no run: its first try after it's added runs, the same day. |
| How long a chain may be | `times × every` at most 12 hours, and `every` at least a minute, in whole seconds (a try's time is HH:MM:SS; HA's time trigger refuses a fraction). A chain can't reach the next day's occurrence (whose window would then see the previous chain's last try, or the other way round), and a sun event drifts a few minutes a day. |
| Past midnight | Allowed: `at: "23:00"` with three tries every hour tries at 00:00, 01:00, 02:00. The window is relative to the try, not to the day. |
| Daylight saving | Accepted: tries are clock times. A try at a time the clock skips doesn't run that day; going back an hour, HA fires a repeated time twice (the occurrence's too, as any automation's), and a try's window can miss the occurrence's run and run once more. |
| The time trigger's seconds | Kept: `at: "13:00:30"`, every hour → `14:00:30`. |

## Configuration

`reactions.<key>` gains one optional key:

| Key | Type | What |
|---|---|---|
| `retry.times` | integer, at least 1 | How many more tries after the occurrence. |
| `retry.every` | time period, at least a minute | The interval: the occurrence, then `every` after it, `2 × every`, … |

Both are required inside `retry`, a schema of its own (`vol.Schema`) so unknown keys are refused.

Refused (`_consistent`):
- `retry` on a reaction on `when` or `entity`: `a reaction's retry goes with at or sun`.
- `times × every` over 12 hours: `a reaction's retries must end within 12 hours`.
- `every` under a minute: by the schema.

## The generated automation

Without `retry`, the automation is exactly as today: no `conditions`.

With `retry`, each try is the occurrence's trigger again, later:
- `at`: a `time` trigger at `at + k × every` (modulo a day), `HH:MM:SS`.
- `sun`: a `sun` trigger on the same event, offset by `offset + k × every`.

Each try has `id: retry_<k>` and a trigger variable `since`, the window in seconds (`k × every` plus 60). One template condition lets the occurrence through and a try only without a run in its window:

```yaml
- id: pururu_garden_reaction_afternoon
  alias: Jardim Tarde
  description: "pururu: garden, afternoon"
  triggers:
    - {trigger: time, at: "13:00:00"}
    - {trigger: time, at: "14:00:00", id: retry_1, variables: {since: 3660}}
    - {trigger: time, at: "15:00:00", id: retry_2, variables: {since: 7260}}
    - {trigger: time, at: "16:00:00", id: retry_3, variables: {since: 10860}}
  conditions:
    - condition: template
      value_template: "{{ since is not defined or as_timestamp(state_attr('script.pururu_garden_program_water', 'last_triggered'), 0) < now().timestamp() - since }}"
  actions:
    - if: [{condition: state, entity_id: script.pururu_garden_program_water, state: "off"}]
      then: [{action: script.turn_on, target: {entity_id: script.pururu_garden_program_water}}]
```

- Timestamps, not `as_datetime`: HA gives `last_triggered` as a `datetime`, which `as_datetime` refuses; `as_timestamp(…, 0)` takes it, and a script or automation that never ran (`none`) is 0.
- With `then`, `last` is the script's `last_triggered`, by its **current** entity ID (a rename is followed, as the action's).
- Without `then`, `last` is the automation's own: `this.attributes.last_triggered` (`this` is its state before this run).
- The actions are unchanged: a try that passes starts the program unless it's running, as the occurrence does.

## Behaviour

| When | What happens |
|---|---|
| The occurrence runs | Every try is skipped: the trace shows the condition failing, `triggered_total` counts one |
| HA was down at 13:00, up at 13:30 | 14:00 runs; 15:00 and 16:00 are skipped |
| The automation was off at 13:00, turned on at 14:30 | 15:00 runs; 16:00 is skipped |
| With `then`, the program was running at 13:00 (started at 12:30) | 13:00 fires, the `if` isn't taken; 14:00 sees no start since 13:00 and starts it (unless it still runs, then 15:00 tries) |
| With `then`, the program was started by hand at 13:20 | Every try is skipped: it started since the occurrence |
| Without `then`, the automation was run by hand at 13:20 | Every try is skipped: HA's manual run sets `last_triggered` |
| Every try missed | Nothing more until the next occurrence |

## Units

- **`reactions.py`**: `retry` in `REACTION`, its checks in `_consistent`; `triggers` returns the tries after the occurrence; a new `conditions(reaction, script, automation)` returns the condition (none without `retry`); `automation` adds `conditions` only when there are some. The automation's entity ID for `this` isn't needed (`this` is the automation itself).
- Nothing else: the file, the `Kind`, dropping and holding are unchanged.

## Docs

- `concepts/reactions.mdx`: `retry.times` and `retry.every` in Settings; a section "Trying again" with the generated YAML, what "ran" means with and without `then`, the behaviour table, the 12-hour limit, daylight saving; the statistics section says a skipped try isn't a trigger.
- `reference/configuration.mdx`: the new keys.
- `CLAUDE.md`: in step 6, a reaction on `at` or `sun` can retry, skipped by a condition on `last_triggered`.

## Tests

- **Schema:** `retry` on `at` and on `sun` accepted; refused on `when` and `entity`, with `times: 0`, `every` under a minute, over 12 hours, an unknown key inside `retry`, a missing `times` or `every`.
- **Generated YAML:** the triggers of `at` (seconds kept, past midnight wrapped) and of `sun` (with and without `offset`, a negative one), their ids and `since`; the condition with `then` (the script's current ID) and without (`this`); no `conditions` without `retry`, so the existing automations are unchanged.
- **In HA** (the `automations` fixtures, real automations and scripts): with frozen time,
  - the occurrence runs and the tries are skipped (`triggered_total` 1);
  - the occurrence missed (the automation off at 13:00, on after), the first try runs, the next skipped;
  - with `then`, the program running at the occurrence, the next try starts it;
  - a restart between the occurrence and a try: the restored `last_triggered` still skips it;
  - `sun`: a try fires `every` after the event.

## Release

The next free version after main and open PRs (0.1.22 unless notifications ships first). Not breaking: every configuration without `retry` generates the same file.

## Left open

- Retry and "recovery" for state reactions.
- More conveniences for reactions, each its own spec.
