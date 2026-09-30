# Programs — design

Version: the one after the last release merged (alerts and lights both ask for 0.1.6). Branch: stacked on `feat/alerts`, rebased on `main` once alerts merges. Builds on alerts' `refers` and `follows`.

## Goal

A device can have **programs**: named sequences of actions on its own entities, which someone starts from outside. If a device is a class, its programs are its methods: the greenhouse's `clean` turns the sprinkler on, waits two hours and turns it off. A program acts only on entities of its own device.

```yaml
pururu:
  devices:
    greenhouse:
      name: Estufa
      switches:
        sprinkler: {entity: switch.greenhouse_sprinkler, name: Irrigador}
        heater: {entity: switch.greenhouse_heater, name: Aquecedor}
      programs:
        clean:
          name: Limpar
          sequence:
            - turn_on: switch_sprinkler
            - delay: {hours: 2}
            - turn_off: switch_sprinkler
# → button.pururu_greenhouse_program_clean  "Estufa Limpar"
```

## Decisions

| Question | Decision |
|---|---|
| The boundary | What a program touches and who starts it, not how much logic it has. It acts on and reads only its own device's entities, named by entity key, never by entity ID: no templates (a template reads any entity), no other device, no events, no arbitrary service. It never starts itself: no triggers, no `wait_for_trigger`; reacting to things is for automations, later. |
| How much logic, now | Actions and `delay`. Conditions on its own device's states (`if:`) fit the boundary and come later; the step schema is built to take them. |
| Its own syntax or HA's | Its own, minimal, translated to HA's and run by HA's `Script` helper. A whitelist of steps can't be escaped; HA's syntax restricted afterwards is a blacklist (templates, `area_id`, `device_id`, templated `data`, `choose`, `parallel`…) that every HA release may widen. HA's syntax would also need full entity IDs, which break when an entity is renamed in the UI. |
| Who runs it | HA's `homeassistant.helpers.script.Script`: sequence, `delay`, context (the logbook names who started it), mode, stopping on unload. No engine of pururu's own. |
| The entity | A `button`. HA's `script` is not an entity platform an integration can add to. Rejected: a `switch` that is `on` while running (it poses as a piece of equipment: "turn off everything in Estufa" would stop programs, "how many switches are on" counts them); a `button` plus a `binary_sensor` "running" (two entities per program from day one, still no way to stop). |
| Its name | `programs`: what a device knows how to do, as a washer's or an irrigation controller's programs. Rejected: `scripts` (suggests HA's syntax), `actions` (HA's "action", and `Feature.actions`), `routines` (suggests triggers), `methods` (jargon), `commands` (a single command). Home Connect and Miele call an appliance's own mode a "program"; the meaning is close enough. |
| Its steps' key | `sequence:`, as HA. With the block not named `scripts`, it doesn't suggest HA's syntax; an HA action pasted there is refused with a clear error. |
| How a step names an entity | As its entity ID ends after the device key (`switch_sprinkler`), as alerts' `when:`. Namespaces never contain `_`, so the first `_` splits it. Rejected: `switch.sprinkler` (reads as `self.switch.sprinkler`, but alerts, already written, uses `switch_sprinkler`, and it looks like an entity ID); `sprinkler` alone (ambiguous once `lights:` has the same key). |
| How programs see other features' entities | Alerts' `refers` for which entity, plus a new `Feature.actions` for what can be done to it. Rejected: `programs` as a special device key like `area:` (a second path around `_creatable`, renames and stale removal); resolving targets inside `build()` (circular import, a wrong target only found at build time). |
| Mode | `single`, fixed: a press while running is ignored with a warning. |
| A target disabled in the registry | The button is `unavailable` while any target is disabled, and available again when it is enabled (added after the PR review). Rejected: keeping it pressable, doing nothing (a button that looks usable and does nothing misleads); not creating the program (it would vanish from the device and its area). |
| Later, not in this PR | Seeing what is running; stopping a program; `mode:`; `if:` and other conditions on its device's states; pururu's own triggers and automations managing programs (for example, run `clean` when an alert turns on). |

## Configuration

`programs:` is a feature (a key of `FEATURES`, namespace `program`, `configured=Platform.BUTTON`): a map of **slug → program**, with at least one program.

- `name`: required, not blank, not translated (as `switches` and `alerts`).
- `sequence`: required, at least one step. A step is a mapping with **exactly one** key:
  - `delay:` a positive HA time period (`{hours: 2}`, `"00:30:00"`, `90`).
  - `turn_on:`, `turn_off:` or `toggle:` an entity key of the device, as its entity ID ends after the device key (`switch_sprinkler`): a slug.
  - Anything else is refused: `action:`, `service:`, `if:`, two keys in one step.

The schema's verbs are fixed (`turn_on`, `turn_off`, `toggle`): it can't read `FEATURES`, which imports it.

### Checked against the device

In `_device`, after `<capability>_from`:

1. Alerts' `refers` rule: every target is an entity key of **another** feature of the device, else `programs: <key> is not an entity key of another feature of this device`. This refuses a real entity ID (`switch_greenhouse_sprinkler`), another program, and a device with only `programs:`.
2. New: for each `(action, key)` of `acts`, the feature owning `key` has the action in its `actions`, else `programs: <key> does not take <action>` (for example `turn_on: appliance_power`).

The same target in several steps is fine: turn the sprinkler on, then off.

## Feature contract

```python
# Services its entities take, on their own platform (turn_on → switch.turn_on
# for a switch); a program can call them
actions: tuple[str, ...] = ()
# (action, entity key in its namespace) of every entity its validated block
# acts on; each entity key is in refers too, and its feature must take the action
acts: Callable[[Any], Iterable[tuple[str, str]]] | None = None
```

- `SWITCHES`: `actions=("turn_on", "turn_off", "toggle")`. When `lights` merges, `LIGHTS` declares its own, and programs act on lights with no other change.
- `PROGRAMS`: `refers` (every target of every step) and `acts` (the pairs).
- `_build` doesn't change: through `refers`, `build()` gets `inputs["switch_sprinkler"]`, the target's current entity ID (renamed or not).

### `build()`

For each program:

1. Translate its steps to HA's syntax: `turn_on: switch_sprinkler` → `{action: switch.turn_on, target: {entity_id: inputs["switch_sprinkler"]}}`, the domain taken from that entity ID; `delay` as it is.
2. Validate that with `cv.SCRIPT_SCHEMA`.
3. Create a `Program` whose `follows` is the program's targets. `_creatable` already drops a program whose target isn't created, and logs `button.pururu_greenhouse_program_clean follows switch.pururu_greenhouse_switch_sprinkler, which is not created; not creating it`.

## The entity

`Program(PururuEntity, ButtonEntity)` in `features/programs.py`, holding an HA `Script` with the translated sequence, `script_mode="single"`, pururu's logger, and the program's full name for the logs.

| Situation | Behaviour |
|---|---|
| Pressed | Starts the sequence and **returns at once**, as `script.turn_on`: an automation calling `button.press` doesn't wait two hours. The button's state becomes the time of the press. |
| Who pressed it | The press's context goes to the `Script`, so the logbook names who started what the program did. |
| Pressed while running | Ignored; HA logs `Estufa Limpar: Already running` as a warning. |
| A step fails | The program stops and HA logs the error, as for its own scripts. An `unavailable` switch is not a failure: HA skips it and the program goes on. |
| A target is disabled in the registry | The button is `unavailable`, so it can't be pressed; it follows the registry, and is available again once every target is enabled. |
| Reload (YAML, a rename in the UI) or unload | A running program is stopped (`async_stop`). What it already did stays: the sprinkler stays on. |
| HA restart | A running program is lost, as HA's scripts. The button comes back with the time of its last press (`ButtonEntity` restores it). |
| Name | `name:`, after the device's name: "Estufa Limpar". |
| Icon | HA's default for a button. |
| Attributes | None; the sequence isn't exposed. |

## Platform, manifest, Sonar

- `Platform.BUTTON` joins `PLATFORMS`; `button.py` adds `entry.runtime_data[Platform.BUTTON]`, as `switch.py`.
- `sonar-project.properties`: the S1172 and S7503 suppressions for `button.py`, as for the other platform modules.
- `manifest.json`: the version after the last release merged.
- The dashboard doesn't change: it lists devices, not entities.

## Testing

`tests/test_programs.py`:

- Pressing turns the sprinkler on, `tick` two hours, turns it off; `toggle` flips it.
- `button.press` with `blocking=True` returns before the delay ends.
- The call to the real switch carries the press's context.
- A second press during the delay is ignored, with the warning.
- A reload during the delay stops it: the sprinkler isn't turned off.
- The target switch renamed in the UI is followed; the button renamed in the UI still runs.
- Refused: an unknown step key (`action:`), two keys in a step, an empty `sequence`, a blank `name`, a missing target, another program as target, a real entity ID, an action the target's feature doesn't take (`turn_on: appliance_power`), a device with only `programs`.
- A target whose ID is taken: the program isn't created, with the `follows` log.
- Restart: the button comes back with its last press.

`tests/test_features.py` (contract): every action in a feature's `actions` is a service its platform registers; `PROGRAMS`' example is valid.

## Documentation

- `docs/concepts/programs.mdx` (new) and its sidebar entry in `docs.json`: the YAML, its settings (`<Property>`), the steps, the entity and what a press does, `single`, reload and restart, the boundary (only its own device, no triggers, no templates).
- `docs/index.mdx`, "What pururu doesn't do": it still never acts on its own; a program runs its steps when someone presses it, and nothing else.
- `docs/concepts/devices-and-features.mdx`: `programs` in the features table, and `actions`.
- `docs/concepts/entity-ids.mdx`: platform `button`, namespace `program`.
- `docs/reference/configuration.mdx`: `programs:` in the example.
- `docs/reference/troubleshooting.mdx`: the new messages (`does not take`, `Already running`), worded as the code logs them.
- `docs/develop/architecture.mdx` and `docs/develop/writing-a-feature.mdx`: `actions`, `acts`, and the contract test row.
- `CLAUDE.md`: `actions` and `acts` under Features, and `button.py` next to the other platform modules.

## Risks

- **Stopping halfway leaves the device between states.** A reload or a failed step leaves the sprinkler on; there is no undo, as with HA's scripts. Seeing what runs, and later pururu's own automations, is what makes it visible and manageable.
- **A rename in the UI of any pururu entity reloads the entry**, and so stops a running program. Rare; documented.
- **Stacked on alerts.** A change to `refers` or `follows` in alerts' review changes this branch; it is rebased then.
- `Script` is an HA helper integrations use (template entities, `trigger_template`); a change to its constructor breaks at setup, and the tests catch it.
