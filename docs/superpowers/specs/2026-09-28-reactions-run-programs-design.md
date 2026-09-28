# Reactions run programs — design

Version: 0.1.17. Builds on reactions (0.1.10), whose automations have no actions yet, and programs as scripts (0.1.15).

## Goal

A reaction listens; a program is what its device knows how to do. Both exist, and neither reaches the other: a reaction's automation fires and does nothing, and a program runs only when someone outside starts it. This joins them: a reaction names one of its device's programs in `then`, and its automation starts that program's script. The reaction decides **when**, the program **what**.

```yaml
pururu:
  devices:
    pool:
      name: Piscina
      switches:
        pump: {entity: switch.pool_pump, name: Bomba}
      programs:
        clean:
          name: Limpar
          sequence:
            - turn_on: switch_pump
            - delay: {hours: 2}
            - turn_off: switch_pump
      reactions:
        morning: {name: Manhã, at: "08:00", then: clean}
# → automation.pururu_pool_reaction_morning starts script.pururu_pool_program_clean
```

## Decisions

| Question | Decision |
|---|---|
| What `then` is | The key of **one program of the reaction's own device**. Rejected: a program's steps written inline in the reaction (two places for what a device does, and no script with its traces, state and `script.turn_off`); HA's own actions (`notify`, any `action:`), which break the device boundary both specs kept, and alerts' `notify` already covers notifying. An inline program can come later without changing any YAML written for this. |
| Whose program | The reaction's device's, always. A reaction on another device (`device: laundry_washer`) runs its **own** program: it lives in the device that reacts, as reactions' spec set, and acts on that device only. |
| How many | One. A reaction wanting two things runs a program doing both. |
| Is `then` required | No. Without it a reaction fires and does nothing, as today: every configuration written for 0.1.16 stays valid and generates the same automation. |
| How the automation starts it | `script.turn_on` on the script, inside an `if` that the script is `off`. The run ends at once; a program already running is left alone, and the trace shows the `if` taken or not. Rejected: calling the script as an action (`action: script.pururu_…`), which waits for it to end, so the automation runs for hours and a trigger meanwhile is logged as `Already running`; the check as the automation's `conditions`, which would hide the trigger itself: HA counts an automation as triggered (`automation_triggered`, `last_triggered`) only once its conditions pass, and the programs' statistics (0.1.18) count a reaction's triggers apart from its program's runs. |
| Execution modes | Not now. The script stays `single`, and the `if` is how a reaction honours it. `parallel`, `queued` and `restart` come later, per program; the `if` then goes or changes, with no YAML change. |
| A program not generated | Its reactions with `then` aren't either: an automation starting a missing script fails at every trigger. Dropped (a target not created, the script's ID taken) → dropped, logged. Held (a target disabled) → held, as the program: out of the file, its registry entry and what the user set kept, back when the target is enabled again. |
| A script the user disabled | Not pururu's business: the reaction is generated, the script has no state, the `if` isn't taken, and the trace says so. |

## Configuration

`reactions.<key>` gains one optional key:

| Key | Type | What |
|---|---|---|
| `then` | slug | A key of this device's `programs`. |

Refused, with the device's other checks (`_reactions_on_this_device`): `then` naming no program of the device — `reactions: morning: clean is not a program of this device`. A program's key only; a script's entity ID, another device's program, or a list is refused by the schema (a slug) or by that check.

## The generated automation

```yaml
- id: pururu_pool_reaction_morning
  alias: Piscina Manhã
  description: "pururu: pool, morning"
  triggers:
    - trigger: time
      at: "08:00:00"
  actions:
    - if:
        - condition: state
          entity_id: script.pururu_pool_program_clean
          state: "off"
      then:
        - action: script.turn_on
          target: {entity_id: script.pururu_pool_program_clean}
```

- The script's **current** entity ID, read from the registry by its unique ID (`script`, `script`, `pururu_pool_program_clean`): renamed in the UI, the reaction follows it at once, as `when` follows a pururu entity. The registry listener reloads the entry on the rename of a script some reaction starts: with the old ID, the `if` would never be true and the program would never start.
- Without `then`, `actions: []`, as today.

## Behaviour

| When | What happens |
|---|---|
| The reaction fires, the program isn't running | The program starts; the automation's run ends at once |
| The reaction fires while the program runs | Nothing; the trace shows the `if` not taken |
| The program is started from elsewhere (UI, voice, another reaction) | Same program, same script: the `if` sees it running |
| A target of the program isn't created | The program and its reactions with `then` aren't generated; both logged |
| A target of the program is disabled | Both held; both back, as the user set them, once it's enabled again |
| The script's ID is taken by someone else | The program isn't generated (as today) and its reactions with `then` aren't either, logged |
| The script renamed in the UI | pururu reloads; the automation names its new ID |
| The automation turned off in the UI | HA's own: it doesn't fire |
| The script disabled in the UI | The reaction still fires; the `if` isn't taken |

The new log message: `automation.<id> runs script.<id>, which is not generated; not generating it`.

## Code

### `reactions.py`

- `REACTION` gains `vol.Optional("then"): cv.slug`.
- `automation(..., script: str | None)`: with a script's entity ID, `actions` is the `if` above; without, `[]`.
- The module docstring: a reaction starts one of its device's programs, or does nothing.

### `generated.py`

- `async_sync` returns the IDs it generated (after `_free`), so programs' results can decide reactions'.

### `__init__.py`

- `_reactions_on_this_device`: a `then` must be a key of the device's `programs`.
- `async_setup_entry`: programs' scripts are synced **before** reactions' automations. `_automations(hass, devices, created, scripts, held_scripts)` takes the generated script IDs and the held ones, and returns the automations and its own held IDs: a reaction whose program is held is held; one whose program isn't generated or held is dropped, logged.
- The registry listener already reloads the entry when a program's target is disabled, and the reaction follows its program. It also reloads it when a script a reaction starts is renamed.
- The docstrings of `async_setup_entry` (the order) and `_automations`.

## Testing

- `tests/test_reactions.py`:
  - Schema: `then` accepted; refused when it names no program of the device, another device's program, an entity ID, a list.
  - The automation: with `then`, the `if` on the script's entity ID, and HA's automation schema accepts it; without, `actions: []` as before.
  - End to end: the `at` fires, the script runs, the pump turns on; a second trigger during the `delay` changes nothing, and the program's `delay` goes on.
  - The program dropped (its target not created): the reaction isn't generated, logged.
  - The program held (its target disabled): the reaction held, its registry entry kept; the target enabled again, both back.
  - The script's ID taken by another integration: the reaction isn't generated, logged.
  - The script renamed in the UI, then pururu reloaded: the reaction's `if` and action name the new ID.
- `tests/test_generated.py`: `async_sync` returns the generated IDs, not the refused ones.

## Docs

- `docs/concepts/reactions.mdx`: the "does nothing yet" note goes; `then` under Settings; the generated automation; the behaviour table above; the automation's table row "Actions".
- `docs/concepts/programs.mdx`: "No triggers" becomes "a reaction can start it", with the example.
- `docs/reference/configuration.mdx`: `then`.
- `docs/reference/troubleshooting.mdx`: `… runs script.…, which is not generated; not generating it`.
- `CLAUDE.md`: step 6, a reaction's `then` and the order (scripts before automations).

## Release

0.1.17 in `manifest.json`. Nothing breaks: a reaction without `then` is the same automation as before.

## Later

- Execution modes per program (`parallel`, `queued`, `restart`).
- A program inline in `then`, several programs, another device's program.
- Programs' and reactions' statistics: 0.1.18, its own spec.
- One model for an appliance's native programs (`modes`) and pururu's: issue #25.

## Risks

- **Programs before reactions** reorders released code in `async_setup_entry`; the reactions' tests must pass unchanged for reactions without `then`.
- **A held reaction** reuses the held path built for programs; it must not drop the automation's registry entry while the program is held.
