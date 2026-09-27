# Alert notify — design

Version: pururu 0.1.9 (0.1.8 went to programs, #16). Branch: `feat/alert-notify`. Builds on alerts (0.1.6, #14): the second step, delivery.

## Goal

An alert can say **what** to tell when it fires and when it's resolved, next to the alert in the device's YAML. [Alert2](https://github.com/redstone99/hass-alert2) does the telling (phones, reminders, acknowledging, lights) with **one** `generator` block the user writes once, which reads every pururu alert that has something to tell. A new alert in pururu reaches the phone without touching the Alert2 configuration.

```yaml
pururu:
  devices:
    laundry_washer:
      alerts:
        long_cycle:
          name: Ciclo longo
          when: appliance_running
          is: "on"
          for: {hours: 3}
          priority: medium
          notify:
            message: A máquina está rodando há mais de 3h!
            done_message: A máquina terminou.
```

```yaml
# Alert2 (the user's own configuration), once
alert2:
  alerts:
    - generator_name: pururu
      generator: "{{ states.binary_sensor | selectattr('attributes.message', 'defined') | entity_regex('binary_sensor[.]pururu_(.+_alert_.+)$') | list }}"
      domain: pururu
      name: "{{ genGroups[0] }}"
      condition_on: "{{ is_state(genEntityId, 'on') }}"
      condition_off: "{{ is_state(genEntityId, 'off') }}"
      friendly_name: "{{ state_attr(genEntityId, 'friendly_name') }}"
      priority: "{{ state_attr(genEntityId, 'priority') }}"
      message: "{{ state_attr(genEntityId, 'message') }}"
      done_message: "{{ state_attr(genEntityId, 'done_message') }}"
```

## Decisions

| Question | Decision |
|---|---|
| Who delivers | Alert2, kept. pururu doesn't send notifications, reminders or acknowledgements. Rejected: pururu replacing the user's alertmanager (a notification subsystem to own), and a first small step with pururu sending one notification. |
| How pururu reaches Alert2 | Attributes on the alert entity, read by one Alert2 `generator` block the user writes once (Alert2's public YAML). Rejected: pururu creating Alert2's alerts in code (Alert2's internal, undocumented `declareCondition`, which can break at any Alert2 release); Alert2's public Python API (`declareEventMulti`/`report`), which only makes event alerts: no on/off state, so no reminders while a problem lasts and no resolved message. |
| What an alert says | `notify: {message, done_message}`, both required. Every alert of the user's alertmanager has both; the generator always has text to read. Someone who wants no resolved notification turns it off in Alert2 (`done_notifier: false`). Rejected: an optional `done_message` (Alert2's default, English text), and `notifier`/`title` per alert (no alert needs them). |
| What stays in Alert2 | What is the same for every alert: notifiers, reminder frequencies, acknowledging, the title from the priority, data (the Ignore button), the lights. Alert2 can't template reminder frequencies or acknowledgement per alert anyway (`reminder_frequency_mins`, `ack_required`, `ack_reminders_only` aren't templates). |
| Which alerts Alert2 delivers | Those with `notify:`, which alone have a `message` attribute: the generator filters on it. An alert without `notify:` is left to automations or HA's `alert:`. |
| When pururu complains about Alert2 | Only for an alert with `notify:`, once Home Assistant has started, when Alert2 isn't set up (`alert2` not in `hass.config.components`): an error in the log naming the alert. Nothing else is affected. Rejected: complaining whenever alerts exist (alerts used with automations alone would log an error at every start). |
| Where that check lives | In the alert entity (`features/alerts.py`), at the start it already waits for. The core knows nothing of Alert2. |
| Alert2 as a dependency in the manifest | None: checking after start finds Alert2 whatever the load order, and a manifest dependency would make Alert2 required. |

## Configuration

An alert gains:

| Key | Required | What it is |
|---|---|---|
| `notify` | no | What to tell. A block of its own; unknown keys are refused. |
| `notify.message` | yes, in `notify` | The text when the alert fires. Not empty. |
| `notify.done_message` | yes, in `notify` | The text when the alert is resolved. Not empty. |

Errors are the schema's own: a missing `message` or `done_message`, an empty one, an unknown key in `notify`.

## Entity

An alert with `notify:` gains the attributes `message` and `done_message`. An alert without it has neither. Everything else is as in 0.1.6 (`priority`, `watches`).

## The Alert2 check

When Home Assistant has started (where the alert already begins to watch its entity), an alert with `notify:` checks `"alert2" in hass.config.components`. When it isn't:

```
binary_sensor.pururu_laundry_washer_alert_long_cycle has notify, but Alert2 isn't set up to deliver it
```

logged as an error, once per alert and setup. Detection goes on as without `notify:`.

## Tests (`tests/test_alerts.py`)

- **Refused `notify` blocks**, each checked for its own message: no `message`, no `done_message`, an empty `message`, an unknown key.
- **Attributes:** with `notify:`, `message` and `done_message` are the configured texts. Without it, neither attribute exists.
- **The check:**
  - With `notify:` and no Alert2, the error is logged once, naming the alert.
  - With `notify:` and Alert2 set up (the test adds `alert2` to `hass.config.components`), there is no error.
  - Without `notify:` and no Alert2, there is no error.
  - A restart checks after the start, not before.

## Docs

- `features/alerts.mdx`:
  - The `notify` property.
  - The entity's attributes.
  - **Getting notified** rewritten: with `notify:`, the Alert2 generator above, in full, with what stays in Alert2's defaults (notifier, reminders, acknowledging). Without `notify:`, an automation or HA's `alert:`.
  - The new log line.
- `reference/configuration.mdx`: `notify` in the example.
- `reference/troubleshooting.mdx`: the new error, and its fix (install and set up Alert2, or drop `notify:`).

## Outside this repository

After the release, the user's `packages/alertmanager/alerts.yaml` (ha-config) gains the pururu generator. That's a separate change, in that repository, on the user's request.

## Release

`manifest.json` goes to `0.1.9`.
