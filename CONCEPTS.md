# Concepts

> Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Buttons

### Button
A value of a real sensor turned into a pressable entity of a device: the sensor taking that value, or a person pressing it in Home Assistant, is one press of it.
*Avoid:* remote action, key

A button's state is the time of its last press, kept across restarts. It may start one of its own device's executable programs on each press, unless that program is already running. A disabled button follows no sensor and presses nothing.

### Press
One occurrence of a button: the sensor changing into the button's value from a real reading while Home Assistant runs, or a press made in Home Assistant.

A value written again, a value arriving while Home Assistant starts, the sensor coming back from unavailable, appearing or being restored is never a press: no press nobody made. Two presses at the same instant are still two presses, so presses are counted where they happen, not from the button's state.

## Statistics

### Counter
Something a device's builder counts, all time, at one place of its block: a door's openings, a program's cycles, a reaction's or a button's triggers.

### Total
A counter's all-time value, an entity of its own that only grows and survives restarts and reloads. Every counter has its total, with no setting.

### Meter
How much a total grew in the current period (today, this week, this month, this year), reset when the period turns over. A meter exists only when the block that has the counter asks for that period under its statistics.
