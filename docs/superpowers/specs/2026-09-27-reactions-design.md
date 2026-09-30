# Reactions — design

Version: the one after the last release merged (0.1.9 if nothing else merges first; `feat/alert-notify` also asks for 0.1.8). Branch: `worktree-feat+automations`, on `main` after #16 (programs, 0.1.8). Builds on alerts' entity keys (`when`) and `_creatable`.

## Goal

A device **listens** to events and **reacts** to them. This spec is the listening half: a device declares **reactions**, each with one source (an entity of the device, an entity of another pururu device, a real entity, a time of day, the sun), and pururu turns each reaction into a real **Home Assistant automation**. The automation fires on the source, shows up in HA's automation list with its traces and on/off toggle, and has **no actions yet**. What a reaction does (`then:`) is a later spec; it will become the automation's `actions`, and the natural first action is running one of the device's own [programs](../../concepts/programs.mdx) (`button.press` on `button.pururu_<device>_program_<key>`), which programs' spec already defers to "pururu's own triggers and automations".

```yaml
pururu:
  devices:
    clothes_washer:
      name: Tanquinho
      appliance: {power: sensor.washer_plug_power, running: {threshold: 4}}
      alerts:
        overload: {name: Sobrecarga, when: appliance_power, above: 2500}
    laundry_lights:
      name: Luzes da despensa
      lights:
        teto: {entity: light.despensa_teto, name: Teto}
      reactions:
        teto_on:     {name: Teto acendeu, when: light_teto, to: "on"}
        washer_done: {name: Lavadora terminou, device: clothes_washer, when: appliance_running, from: "on", to: "off"}
        overload:    {name: Sobrecarga, device: clothes_washer, when: alert_overload, to: "on"}
        door:        {name: Porta abriu, entity: binary_sensor.porta_despensa, to: "on", for: {minutes: 5}}
        night:       {name: Noite, at: "22:00"}
        dusk:        {name: Anoitecer, sun: sunset, offset: {minutes: -30}}
# → automation.pururu_laundry_lights_reaction_washer_done   "Luzes da despensa Lavadora terminou"
# → one automation per other reaction, in pururu/automations/reactions.yaml
```

```yaml
# configuration.yaml, once
automation pururu: !include_dir_merge_list pururu/automations
```

## Decisions

| Question | Decision |
|---|---|
| Publish events first (a device announcing its moments) | No. Every pururu entity already publishes its state changes, with a predictable ID; alerts already are named moments. A layer of published events to listen to afterwards buys nothing today. A feature with a truly momentary thing (a button press) creates its own `event` entity when one appears. |
| Where a reaction lives | In the device that **reacts**. It listens to anything (its own entities, another device's, real entities, time, sun); the later actions act on its own entities. The source device doesn't know who listens. |
| Name | `reactions`, namespace `reaction`. Rejected: `triggers` (only the listening half), `automations` (clashes with HA's own), `behaviours` (two spellings for a YAML key; too broad, `alerts` and `phases` are behaviour too). "How a device behaves" stays the idea in the docs. |
| What a reaction produces | A real HA automation, which the user asked for: listed with the others, traces, on/off toggle, and HA's whole action syntax for the later `then:`. Rejected: pururu listening by itself with its own event helpers, plus a diagnostic `event` entity as the trace (no traces, no toggle, not in the list, and that entity would become public interface by accident). |
| How HA gets the automations | A file pururu writes, `pururu/automations/reactions.yaml`, whose folder the user includes once with `automation pururu: !include_dir_merge_list pururu/automations`. HA reads automations only from its configuration: `automation.reload` removes every automation entity not in it, and that reload runs whenever an automation is saved in the UI, so injecting entities through the private `EntityComponent` is out. Writing into `automations.yaml` (the UI editor's file) or adding the include to `configuration.yaml` by itself is out too: the first fights the editor, the second edits the user's main file. The user already edits `configuration.yaml` for `pururu:`, so the include is one more line at install. |
| Include form | `!include_dir_merge_list pururu/automations`, not `!include pururu/automations.yaml`: a plain include of a missing file stops HA from loading its configuration, while a missing folder loads as an empty list. |
| Vocabulary | pururu's own, flat, as `alerts`, translated to HA triggers. Rejected: HA's native trigger syntax inside a reaction (verbose, errors only at setup since trigger validation is async, entity keys resolvable only in known fields). A native escape hatch can be added later without changing any YAML written for this one. |
| Sources | Five: an entity key of the device (`when`), of another device (`device` + `when`), a real entity (`entity`), a time (`at`), the sun (`sun`, `offset`). One source per reaction. Deferred: weekdays for `at`, several sources in one reaction, HA events, zones, time patterns, templates. |
| `device.when` in one string | No: `clothes_washer.appliance_running` reads as an entity ID, and a device may be keyed `light`. `device`, `when` and `entity` are separate keys, and `when` means exactly what it means in `alerts`. |
| `unavailable` in between | HA's rules, since the automation is HA's. With `to` and no `from`, pururu adds `not_from: [unavailable, unknown]`, so a plug reconnecting (`unavailable → off`) never fires. A transition passing through `unavailable` (`on → unavailable → off`) isn't seen. Documented. |
| The automation's entity ID | `automation.pururu_<device key>_reaction_<reaction key>`, the pururu pattern. HA derives it from the alias, so pururu pre-registers the entity with the public registry API before HA loads the file. A rename in the UI is kept. |
| Is `reactions` a `Feature` | No. The `Feature` contract is about creating pururu entities (`entity_keys`, `build()`, translations, icons), and reactions create none. It's a device key, as `area`, in its own module. It doesn't count as a feature: a device still needs one. Programs' spec rejected a special device key because it would be a second path around `_creatable`, renames and stale removal; reactions have no entities of their own for those to handle, and they read `_creatable`'s result rather than going around it. |

## Configuration

`reactions:` is an optional key of a device: a map of **reaction key → reaction**, with at least one reaction. The key is a slug; it ends the automation's `id` and entity ID after the namespace `reaction`.

| Key | Required | What it is |
|---|---|---|
| `name` | yes | Shown after the device's name, as the automation's alias. Not empty. Not translated. |
| `when` | one source | An entity key of a feature of the device (or of `device`), as in its ID: `appliance_running`, `alert_overload`, `light_teto`. |
| `device` | no, only with `when` | The key of another device under `devices:` whose entity `when` names. Naming the reaction's own device is the same as leaving it out. |
| `entity` | one source | A real entity ID, of any domain. |
| `to` | with a state source: `to` or `above`/`below` | The state that fires, reached from another state. YAML's `on`/`off` without quotes (booleans) become `"on"`/`"off"`; anything else is text (`to: 1` is `"1"`), as HA compares states. |
| `from` | no, only with `to` | The state it must come from. |
| `above`, `below` | with a state source: `to` or `above`/`below` | Fires when a number enters the range: strictly above `above`, strictly below `below`. At least one; `above` lower than `below`. |
| `for` | no, only with a state source | How long the new state must hold before it fires. A time period; default 0. |
| `at` | one source | A time of day, `"22:00"` or `"22:00:30"`. |
| `sun` | one source | `sunrise` or `sunset`. |
| `offset` | no, only with `sun` | A time period, negative for before: `{minutes: -30}`. |

"One source" means exactly one of `when`, `entity`, `at`, `sun`.

Configuration errors added, checked in this order (the docs quote them):

- `a reaction needs one source: when, entity, at or sun` (none, or two);
- `a reaction's device goes with when`;
- `a reaction's offset goes with sun`;
- `a reaction on at or sun takes no to, from, above, below or for`;
- `a reaction on a state needs to, or above and/or below, not both`;
- `a reaction's from goes with to`;
- `a reaction's above must be lower than its below`;
- `reactions: <reaction>: <when> is not an entity key of this device` (a `when` without `device`), checked in `_device`;
- `device <key>: reactions: <reaction>: device <other> is not in devices` and `device <key>: reactions: <reaction>: <when> is not an entity key of device <other>`, checked by a new top-level validator next to `_entity_ids_distinct`, since it needs every device.

Every entity key a device's features **can** create counts, as for alerts: `when: appliance_runtime_month` is valid without `statistics`, and the reaction simply isn't generated (see Generation). Reactions have no entity keys, so a reaction can't listen to a reaction.

## The generated automation

One per reaction, in the order of `devices:` then `reactions:`:

```yaml
- id: pururu_laundry_lights_reaction_washer_done
  alias: Luzes da despensa Lavadora terminou
  description: "pururu: laundry_lights, washer_done"
  triggers:
    - trigger: state
      entity_id: binary_sensor.pururu_clothes_washer_appliance_running
      from: "on"
      to: "off"
  actions: []
```

Translation:

| Reaction | Trigger |
|---|---|
| `when`/`entity` + `to` (+ `from`) (+ `for`) | `state` with `entity_id`, `to`, `from`, `for`; without `from`, `not_from: [unavailable, unknown]` |
| `when`/`entity` + `above`/`below` (+ `for`) | `numeric_state` with `entity_id`, `above`, `below`, `for` |
| `at` | `time` with `at` |
| `sun` (+ `offset`) | `sun` with `event` and `offset` |

- `entity_id` for `when` is the watched entity's **current** ID (`current_entity_id`): a rename reloads the entry, which regenerates the file.
- `for` is written as `HH:MM:SS`, `offset` as `[-]HH:MM:SS`, with the fraction of a second when there is one (`00:00:01.900000`): a reaction never fires earlier than configured.
- `actions` is an empty list, which HA accepts: the automation fires and does nothing; its trace shows when and why.
- As for every HA automation, a pending `for` is lost on restart.

## Generation

`async_setup_entry` generates the automations after "remove stale entities and devices" and before the dashboard, since it needs to know what was created.

- **Skipped reactions:** a reaction whose `when` entity isn't created (its ID is taken, it follows something not created, or the device's settings don't build it) isn't generated, with a logged error in the same form as for entities: `automation.pururu_<…>_reaction_<…> follows <entity ID>, which is not created; not generating it`. A real `entity` is never checked: it may appear later, as for `lights`.
- **The file:** `<config>/pururu/automations/reactions.yaml`, a header comment (`# Generated by pururu from its configuration. Don't edit: it is rewritten on every reload.`) and the list, `[]` when there is none. pururu builds the content on every setup and **writes only when it changed**, atomically (`write_utf8_file_atomic`, in the executor), creating `pururu/automations/` if needed.
- **Pre-registration:** for each generated reaction, `er.async_get_or_create("automation", "automation", <id>, suggested_object_id=<id>)` before the file is loaded. If `automation.<id>` is already held by another registry entry (a user's automation, say), the reaction isn't generated and the log says who holds it, as for entities: never a `_2`. An entry that already exists for this unique ID is this reaction's only if the entry manages the ID (`entry.data["automations"]`; one renamed by the user is left alone); otherwise it's the user's own automation with the same `id`, which pururu never takes over. Two reactions whose IDs would be equal (`lights`'s `b_reaction_c`, `lights_reaction_b`'s `c`) are a configuration error, checked next to `_entity_ids_distinct`.
- **Reload:** once HA has started, pururu calls `automation.reload` when the file changed, and also when HA doesn't run what the file holds (a reload that failed, or the include added since), so a reload that didn't take is retried at pururu's next reload. At boot with an unchanged file, HA has already loaded it and nothing is called. This runs in a task of the entry, which its unload waits for: two pururu reloads never overlap. `manifest.json` gets `after_dependencies: ["automation"]`.
- **Stale:** the IDs pururu has registered are kept in `entry.data["automations"]`, as floors and areas are (the floors-and-areas update keeps that key). An ID no longer generated has its registry entry removed once HA no longer runs it (a restored placeholder doesn't count); until then it stays tracked.
- **The include is missing:** after the reload (or at start when nothing changed), and again at every `automation_reloaded` event (the user adding the include and reloading automations), if a generated ID has no running `automation.*` state (not a restored placeholder) whose `id` attribute is it, pururu raises a Repairs issue (`automations_not_included`, not fixable, severity warning) whose text gives the `automation pururu: !include_dir_merge_list pururu/automations` line, and logs a warning. The issue is deleted as soon as every generated automation is loaded, and when nothing is generated. After a failed write, the file is the previous one: only the IDs it holds are checked, so a write error never reads as a missing include.
- **Never a failed setup:** a failed write or reload is a logged error; the devices and their entities keep working.
- **Removal:** `async_remove_entry` writes `[]`, reloads automations if HA is running, removes the pre-registered entries HA no longer runs and deletes the Repairs issue. If the file can't be written, its automations keep running and keep their IDs.

## Code

- **`reactions.py`** (new), next to `places.py` and `dashboard.py`:
  - `SCHEMA`: one reaction's validation, and the map.
  - `triggers(reaction, entity_id) -> list[dict[str, Any]]`: the pure translation, testable without HA.
  - `async_sync(hass, entry, automations)`: pre-register, write if changed, reload, remove stale, raise or delete the Repairs issue; returns the IDs for `entry.data`.
  - `async_remove(hass, entry)`: for `async_remove_entry`.
- **Shared state parsing:** `alerts.py`'s `_state` (booleans to `on`/`off`) moves to a module both use; reactions keep numbers as text, alerts as numbers, so the shared part is the boolean and text handling.
- **`__init__.py`:**
  - `_device` validates `reactions` (a `when` without `device` against `_entity_keys` of the device).
  - A new top-level validator checks `device` and its `when`.
  - `async_setup_entry` resolves each reaction's `when` against what `_creatable` kept (`_referable` of the named device, `current_entity_id`), builds the automations and calls `reactions.async_sync`; `entry.data` keeps floors, areas and automations.
- **`strings.json`/translations:** the Repairs issue (`issues.automations_not_included`), English and Portuguese.

## Testing

`tests/test_reactions.py`:

- **Schema**, parametrized: each valid source; each error above, with its message.
- **Translation:** each source gives exactly its triggers, including the automatic `not_from` and a negative `offset`.
- **End to end**, with the `automation` component set up and including the generated file:
  - the file is written, and not rewritten (nor automations reloaded) when nothing changed;
  - the automation is `automation.pururu_<device>_reaction_<key>`, with its alias;
  - it fires: `fake` changes the source, `tick` passes `for` and the time of day, and `last_triggered` is checked; a `sun` reaction fires at the offset sunset;
  - `unavailable → off` doesn't fire;
  - renaming the watched pururu entity regenerates the file with its new ID;
  - a reaction removed from the YAML leaves the file and the registry;
  - a reaction on an entity not created isn't generated, and the log says why;
  - an `automation.<id>` held by another automation: not generated, logged, no `_2`;
  - without the include, the Repairs issue appears; once included, it's gone;
  - a failed write is logged, and the setup succeeds;
  - `async_remove_entry` leaves `[]` and no registry entries.
- `uv run pytest`: ruff, mypy, hassfest, quality scale.

## Docs

Same PR:

- `docs/concepts/reactions.mdx` (new, in the sidebar): "Reactions: how a device behaves". The model, the five sources and their conditions, the include, the generated automation and its ID, the `unavailable` rule, and that in this version a reaction fires and does nothing yet.
- `getting-started/install.mdx`: the include line.
- `reference/configuration.mdx`: the `reactions` keys.
- `reference/troubleshooting.mdx`: the Repairs issue, and "a reaction isn't generated".
- `concepts/devices-and-features.mdx`: `reactions` as a device key that isn't a feature.
- `index.mdx`: "never acts on its own" still holds; it mentions reactions.
- `develop/architecture.mdx`: the new setup step and `reactions.py`.

## Release

`version` in `manifest.json`: the patch after the latest release on `main` when the PR is opened (0.1.9 today); `python3 release.py check`.
