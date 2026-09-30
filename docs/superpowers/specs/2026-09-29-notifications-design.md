# Notifications

> **Changed before release:** ready-made notifications are enabled in their feature's block, `appliance: notifications: finished`, as ready-made alerts are in `alerts`, not under a device key `notifications: appliance: finished`. What follows about the device key reads that way; the IDs, the file and the rest are as written.

## Goal

Alerts and notifications got mixed up. An **alert** is something the owner finds critical: a problem that lasts (a door open that shouldn't be, a plug offline), a binary sensor Alert2 delivers with reminders, acknowledging and a done message. A **notification** is simple news, told once: the washer finished. It has no state, no "resolved", no reminder.

The clearest case of the mix-up is the appliance's ready-made alert `finished`: a `problem` binary sensor on for `lasts` after a cycle ends, whose Alert2 "Done." only means the timer ran out.

This change:

1. lets a **reaction** send a message (the hand-written notification);
2. adds a device key **`notifications`**, the ready-made notifications its features offer, `finished` the first;
3. removes the ready-made alert `finished`, and `lasts` with it.

pururu still sends nothing itself: every notification is an automation it generates, which calls Home Assistant's `notify` actions.

```yaml
pururu:
  config:
    notify: notify.mobile_app_celular        # every message's default: one or a list
  devices:
    clothes_washer:
      name: Tanquinho
      appliance:
        power: sensor.washer_plug_power
        running: {threshold: 4, on_delay: {minutes: 1}, off_delay: {minutes: 2}}
        alerts:
          offline:
      notifications:
        appliance:
          finished:                           # its default text
          # finished: {message: Roupa pronta!, notify: notify.mobile_app_tablet}
      reactions:
        door_open:
          name: Porta aberta
          entity: binary_sensor.porta_despensa
          to: "on"
          message: A porta da despensa abriu.
          notify: [notify.mobile_app_celular, notify.mobile_app_tablet]
          then: blink
automation pururu: !include_dir_merge_list pururu/automations   # unchanged
```

| YAML | Automation | Alias | Sends |
|---|---|---|---|
| `notifications: appliance: finished` | `automation.pururu_clothes_washer_appliance_notification_finished` | Tanquinho Finished (translated: Terminou) | title "Tanquinho", "The cycle finished." (translated) |
| reaction `door_open` | `automation.pururu_clothes_washer_reaction_door_open` | Tanquinho Porta aberta | starts `blink`, then title "Tanquinho", "A porta da despensa abriu." to both phones |

## Where a message goes

- `pururu: config: notify` is the default: a `notify.<name>` action, or a list of them. Validated as `notify.` followed by a slug; whether the action exists is Home Assistant's to say when the automation runs (its trace and log show it).
- A reaction or a notification may give its own `notify`, same form, which **replaces** the default (not added to it).
- A message with no `notify` of its own and no default is a configuration error, naming where: `device clothes_washer: reactions: door_open: message needs notify, here or in config.notify`.

## A reaction's message

- A reaction takes `message` (text, not blank) and `notify` (only with `message`: `a reaction's notify goes with message`, as `a reaction's from goes with to`).
- Its automation's actions, in order:
  1. start its program, as today (`then`);
  2. for each `notify` action, `{action: notify.<name>, data: {title: <device name>, message: <message>}, continue_on_error: true}`, so one phone failing doesn't keep the next from being told.

  The program goes first: a notify action that doesn't exist fails the run whatever `continue_on_error` says, and must not keep the program from starting.
- The message and title are **text**: a `{` is shown as written, never rendered as a template. The raw-block escape of the Alert2 file (`alert2_alerts._text`) moves to `messages.escaped`, which both use.
- The title is always the device's name, even for a reaction on another device's or any entity.
- A reaction with neither `then` nor `message` stays valid, as today: its trace and statistics show when it fired.
- Nothing else changes: its triggers, its statistics, how it's dropped or held.

## Ready-made notifications

### What a feature offers

`Feature` gains `notifications: Mapping[str, Happening]`, by name, off until the device enables them. A `Happening`:

```python
@dataclass(frozen=True, kw_only=True)
class Happening:
    """A ready-made notification of a feature: what happens, as a reaction's trigger."""

    # The entity key, in the feature's namespace, it watches
    watches: str
    # The trigger, as a reaction's state keys: to, and from
    to: str
    from_: str | None = None
```

The appliance offers one:

| Name | Fires when | Default message (en / pt-BR) | Name (en / pt-BR) |
|---|---|---|---|
| `finished` | `appliance_running` goes from `on` to `off` | The cycle finished. / O ciclo terminou. | Finished / Terminou |

The explicit `from: "on"` keeps a plug reconnecting (`unavailable → off`) and a restart or reload (`on → unavailable → on`) from telling anyone; a cycle that really ends right after a restart (`on`, restored, → `off`) does. A cycle ends exactly when `running` goes off (the cycle end rule of 0.1.20).

Unlike `Feature.alerts`, a happening creates no entity of the feature: it adds nothing to `entity_keys`.

### The device's `notifications`

- A device key, next to `reactions` and `programs`, not a feature: a device still needs one feature.
- A map of **feature key → map of name → settings**; a null value is every default. At least one feature, each with at least one name; an empty map is refused.
- Settings: `message` (replaces the default text) and `notify` (replaces the default action). Anything else is refused.
- Schemas of their own (`vol.Schema`), so the top level's `ALLOW_EXTRA` doesn't let unknown keys through.
- Refused, with the path:
  - a key that isn't a feature: `notifications: nope is not a feature`;
  - a feature that offers none: `notifications: switches offers no ready-made notification`;
  - a name it doesn't offer: `notifications: appliance: nope is not a ready-made notification of appliance: finished`;
  - a feature the device doesn't have: `notifications: modes: the device has no modes`;
  - no `notify` anywhere: `device clothes_washer: notifications: appliance: finished needs notify, here or in config.notify`.

### Each one is an automation

- Built as a reaction on `when: <namespace>_<watches>` with the happening's `from`/`to`, through the same trigger and action code (`reactions.triggers`, the notify actions above), no `then`.
- ID, and object ID of its entity ID: `pururu_<device>_<namespace>_notification_<name>`, so `automation.pururu_clothes_washer_appliance_notification_finished`. Across devices it could meet a reaction's (device `a`'s reaction `appliance_notification_finished` and device `a_reaction`'s notification): `_generated_ids_distinct` checks every automation ID, reactions' and notifications', together.
- Alias `<device name> <name>`, the name translated from the translations' `common` block (`appliance_notification_finished_name`), as the default message (`appliance_notification_finished_message`), in HA's language with English for what it lacks (`presets.async_texts`). Description `pururu: <device>, <namespace> notification <name>`.
- Written to **`pururu/automations/notifications.yaml`**, a second `Kind` of domain `automation`: the same folder, so the same include line; its own file, its own key of `entry.data` (`notifications`), its own Repairs issue (`notifications_not_included`, with its translations, the same include line in its text). `generated.py` handles it as any kind, each kind tracking only the IDs in its own `entry.data` key; when both files change, automations may reload twice, accepted. The file is always written, an empty list without notifications, as the reactions' is.
- Its life is a reaction's: not generated when the entity it watches isn't created (the usual log line), its registry entry dropped once HA no longer runs it, `async_remove_entry` removes it. Never held: it starts no program. Renaming it needs nothing rebuilt: nothing watches it, and its registry entry is found by unique ID. A rename of the entity it watches is followed, as a reaction's (the entry reloads on any rename of its entities).
- No statistics sensors.

## `finished` leaves the alerts

- `appliance`'s ready-made alerts are `offline`, `no_power`, `long_cycle`, `no_cycle`.
- `appliance: alerts: finished` is refused with where it went: `finished is now a notification: notifications: appliance: finished`. Generic: a name the feature offers as a notification, given as an alert, gets that message, so the ready-made alerts' validator (`presets.settings_schema`) is given the feature's notifications too.
- The existing binary sensor `binary_sensor.pururu_<device>_appliance_alert_finished` is removed as any stale entity, and its Alert2 alert leaves the Alert2 file.
- `lasts` only served `finished`: it leaves `Preset`, `presets._settings`, `ElapsedAlert` (its window's end and the `_keep` that honours it) and the docs. `ElapsedAlert` is again "on while in its state for longer than `for` since the milestone".
- Its translations (entity name, message, done message) go; the notification's come.

## Units

- **`messages.py`** (new): the `notify` schema (`TARGETS`), the text escape (`escaped`, out of `alert2_alerts.py`) and the notify actions. `reactions.py`, `notifications.py` and `alert2_alerts.py` use it; it imports none of them.
- **`notifications.py`** (new): the device key's schema, the `Kind`, and each ready-made notification's automation (its triggers through `reactions.triggers`). It knows no feature by name: it reads `Feature.notifications`.
- **`reactions.py`**: `message`/`notify` in the schema, its actions from `messages.py` after the program's.
- **`feature.py`**: `Happening`, `Feature.notifications`; `Preset` without `lasts`.
- **`features/appliance/`**: `finished` moves from `PRESETS` to its happenings.
- **`features/presets.py`, `features/elapsed.py`**: without `lasts`; the moved-name message.
- **`__init__.py`**: `config: notify`, the device key, the whole-block validator, generating the second kind next to the reactions'.

## Validation across the configuration

A validator on the whole block (next to `_reactions_resolved`) checks what needs more than one device: a message with no `notify` anywhere (it needs `config: notify`), and the generated IDs, notifications included, distinct.

## Docs

- New `docs/concepts/notifications.mdx`: alert vs notification (critical and lasting vs simple and once), where a message goes (`config: notify`, `notify`), a reaction's message, ready-made notifications and the table of what each feature offers, the file and the include; sidebar entry.
- `concepts/reactions.mdx`: `message` and `notify`, the order of actions, text not template.
- `features/appliance.mdx`: `finished` out of the ready-made alerts; a "Ready-made notifications" section pointing at the concept page.
- `features/alerts.mdx`: an alert is for what's critical; simple news is a notification.
- `reference/configuration.mdx`: `config: notify`, the device key `notifications`, a reaction's `message`/`notify`.
- `reference/troubleshooting.mdx`: the new Repairs issue, and the `finished` error.
- `develop/writing-a-feature.mdx` and `develop/architecture.mdx`: `Feature.notifications`, the second automation kind.
- `CLAUDE.md`: the same, in its Architecture section.

## Tests

- **Contract** (`tests/test_features.py`): for every feature's `notifications`, `watches` is one of its entity keys, the name and message translations exist in every language pururu ships, and a device with the feature's example and every notification enabled validates and generates one automation per notification.
- **Reactions:** the automation of a reaction with `message` (default `notify`, its own, a list), with `message` and `then` (program first), the escape of `{`, the title; refused: blank message, `notify` without `message`, a message with no `notify` anywhere, a malformed `notify`.
- **Notifications:** the file's content and ID, the alias in English and in pt-BR, `message`/`notify` overrides, not generated when `appliance_running` isn't created, removed when dropped from the YAML, the Repairs issue while the file isn't loaded; refused: a feature the device lacks, an unknown name, extra settings, an empty block.
- **`finished`:** `appliance: alerts: finished` refused with its message; `ElapsedAlert` tests without `lasts`. The old binary sensor's removal is the stale-entity cleanup's, already tested.

## Release

Version 0.1.22. A breaking change for whoever enabled `finished`, which the error message and the docs cover.

## Left open

A shorter way to write more notifications per feature (a mode changed, a door opened by someone) is left for later: each is a new `Happening` of its feature, with no change to the mechanism.
