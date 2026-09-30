# Alert2 config, written by pururu — design

Version: 0.1.12 (the one after 0.1.11, modes). Branch: `worktree-bridge-cse_01FrS5sRKjmtWV5pHdNBS5pB`, on `main` at #19. Builds on [alerts](2026-09-27-alerts-design.md), [alert notify](2026-09-27-alert-notify-design.md) and the file-and-reload machinery of [reactions](2026-09-27-reactions-design.md).

## Goal

Today an alert with `notify` is delivered by Alert2 only after the user pastes a **generator** (a dozen lines of Jinja) into Alert2's configuration, and reloads Alert2 whenever `notify` is added to or removed from an existing alert. The user shouldn't write Alert2's rules: pururu offers alerts, so their delivery must come ready.

pururu writes Alert2's alerts itself, as it writes the reactions' automations: one file, one include line pasted once, a reload when the file changes, a Repairs issue while the include is missing. The generator goes away.

This is the first of two parts. The second, **alerts a feature offers ready-made** (an appliance's `offline`, `long_cycle`, `no_power`, `finished`, enabled with one key in the feature's block, with `notify` out of the box), is a later spec on top of this one.

```yaml
pururu:
  devices:
    clothes_washer:
      name: Tanquinho
      appliance: {power: sensor.washer_plug_power, running: {threshold: 4, on_delay: {minutes: 1}, off_delay: {minutes: 2}}}
      alerts:
        long_cycle:
          name: Ciclo longo
          when: appliance_running
          is: "on"
          for: {hours: 3}
          priority: medium
          notify: {message: A máquina passou de 3 horas ligada!, done_message: A máquina terminou.}

alert2:
  defaults:
    notifier: mobile_app_phone          # still the user's: who is told, reminders
  alerts: !include_dir_merge_list pururu/alert2
```

## What Alert2 offers (v1.21, read from its source)

- Condition alerts come **only from YAML**, under the single `alert2:` block (`alerts:` list). `alert2.reload` re-reads `configuration.yaml` through HA's loader (`async_prepare_reload`), so `!include` works and a reload picks up a rewritten file.
- No API declares a condition alert: `declareEventMulti()` is for event alerts only. UI-made alerts live in `.storage/alert2.storage`, private: not used.
- An alert's entity is `alert2.<domain>_<name>`, unique ID `d=<domain>-n=<name>`. The generator's alerts had domain `pururu` and name `<device>_alert_<key>`: the written ones keep both, so the same entity (and its history) carries over.
- A reload unloads **every** Alert2 alert and declares them again; Alert2 removes the registry entries of alerts gone from its config by itself.
- Two declarations of one domain/name: Alert2 reports `Duplicate declaration of alert for domain=pururu name=…` and keeps the first.

`automation` accepts several blocks (`automation pururu:`); `alert2` doesn't. So the include goes **inside** the user's `alert2:` block, as its `alerts:`. A list can't be both inline and an include, so the user's own condition alerts move to Alert2's UI. Not into `pururu/alert2`: pururu owns that folder, and the include loads every file in it. The docs say so.

## The file

`pururu/alert2/alerts.yaml`, next to `configuration.yaml`, always written (`[]` without any alert with `notify`), with the reactions' header (generated, don't edit). A folder include, as for reactions: a missing folder loads as `[]`, a missing file would stop HA's configuration.

One condition alert per alert **with `notify`**, in device then alert order:

```yaml
- domain: pururu
  name: clothes_washer_alert_long_cycle
  friendly_name: Tanquinho Ciclo longo
  condition_on: "{{ is_state('binary_sensor.pururu_clothes_washer_alert_long_cycle', 'on') }}"
  condition_off: "{{ is_state('binary_sensor.pururu_clothes_washer_alert_long_cycle', 'off') }}"
  priority: medium
  message: A máquina passou de 3 horas ligada!
  done_message: A máquina terminou.
```

- **`name`** is the alert's object ID without the `pururu_` prefix: `alert2.pururu_<device>_alert_<key>`, as with the generator, whatever the keys contain.
- **The conditions** use the binary sensor's **current** entity ID: a rename in the UI reloads the entry (as today), which rewrites the file. `condition_on`/`condition_off` rather than one `condition`, as the generator did: the Alert2 alert keeps its state while the pururu one is briefly `unavailable` (a pururu reload).
- **`friendly_name`** is the alert's name as HA shows it, `<device name> <alert name>`.
- **Text stays text.** Alert2 renders `friendly_name`, `message` and `done_message` as templates; the user wrote plain text, so one containing `{` (every Jinja delimiter starts with it) is wrapped in `{% raw %}…{% endraw %}`, and each `{%` inside leaves the block and is written as a string, as Alert2's own `jinja2Escape` does: a literal `{% endraw %}` can't end it. The generator's output was never rendered twice either.
- **Only alerts that are created.** An alert not created (its ID taken, its `when` not built, `_creatable`) isn't written: its condition would name nothing.
- Only alerts with `notify`: without it, Alert2 leaves the alert alone, as today.

The binary sensor is unchanged, still the source of truth, still working without Alert2. Its attributes `priority`, `watches`, `message`, `done_message` stay: the `alert:` integration and automations can use them.

## Applying it (`alert2_alerts.py`, alongside `reactions.py`)

Not `alert2.py`: a module named after another integration's domain reads as a platform of it.

Mirrors the reactions' flow, with what they share moved out of `reactions.py` rather than copied (`_write`, the atomic write that compares bytes, and the failed-write-is-`None` contract, go to `files.py`):

1. `async_setup_entry`, after the reactions: build the list from the created alerts, write it. A failed write is logged, never raised; the previous file stays.
2. Once HA has started, in an entry task the unload waits for: **reload Alert2** (`alert2.reload`, blocking) when the file changed, or when an alert the file holds isn't running in Alert2. A written file stays pending (in `hass.data`) until a reload succeeds, so a failed reload is retried at the next pururu setup, including after removing the entry, when the empty file is then unchanged.
3. **Running** means `alert2.pururu_<name>`'s state exists and isn't a restored placeholder (`ATTR_RESTORED`). The entity ID is looked up in the registry by Alert2's unique ID (`d=pururu-n=<name>`), falling back to `alert2.pururu_<name>`: the user may rename it.
4. **Checking the include**, after the reload (Alert2 fires no event; the check follows the service call) and at start: Alert2 set up, the file holding alerts, and one of them not running → a **Repairs** issue, `alert2_not_included`, with the line to add and a warning in the log; otherwise the issue is deleted.
5. **Alert2 not set up** and alerts with `notify`: the log error each alert already raises at start stays (`… has notify, but Alert2 isn't set up to deliver it`); no reload, no Repairs issue (the fix is installing Alert2, which the error says). The file is written anyway, so installing Alert2 later just works.
6. **Removing the entry** writes `[]` and reloads Alert2 if it runs, and deletes the issue.

No entity IDs to pre-register and nothing tracked in `entry.data`: Alert2 owns its entities and drops the ones gone from its config.

## Migration from the generator

The generator produces the same domain and names, so keeping it next to the include gives Alert2 duplicate declarations; the first one wins, the other is reported by Alert2. The docs say to **replace** the generator with the include line; the carry-over keeps the entity, its history and its acknowledgement. The release notes say the same.

## Docs

- `docs/features/alerts.mdx`, **Getting notified**: the generator block and the "reload Alert2 after changing notify" note go; the include line, what pururu writes (the example above), the Repairs issue, the migration from the generator, and that the user's own Alert2 alerts move out of the inline `alerts:` list.
- `docs/reference/troubleshooting.mdx`: the Repairs issue and its log line; the "has notify" fix becomes "install Alert2 and add the include"; duplicate declarations from a leftover generator.
- `docs/reference/configuration.mdx` and `docs/develop/architecture.mdx`: the second generated file.
- `CLAUDE.md`: `async_setup_entry`'s steps gain the Alert2 file.

## Tests (`tests/test_alert2.py`)

Alert2 isn't installed in the test environment: a fake `alert2.reload` service reads the written file and sets `alert2.pururu_<name>` states (or doesn't, for a missing include), with `alert2` added to `hass.config.components`.

- The file: one entry per created alert with `notify`, exactly as above; none without `notify`; `[]` without alerts; text with `{` wrapped; the renamed binary sensor's current ID; an alert not created isn't written.
- Reload: once when the file changed, not when it's the same; again at the next reload when an alert isn't running; not when Alert2 isn't set up; a failed write keeps the previous file and reloads nothing.
- Repairs: raised while an alert isn't running after the reload, deleted once it runs; never raised without Alert2 or without alerts.
- Removing the entry writes `[]` and reloads.
- The docs' include line is the one the Repairs issue gives (as `test_alerts.py` checks the generator block today, which it replaces).
