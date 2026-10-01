# Concepts

> Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## References

### Reference
How the `pururu:` YAML names an entity, written by reading only that YAML: its first word says whose it is. A block of this device starts a path (`appliance.running_program`), `device.` another device's (`device.clothes_washer.appliance.running_program`), `homeassistant.` anything Home Assistant owns (`homeassistant.sensor.washer_plug_power`).
*Avoid:* entity key (for what the YAML writes), entity reference

A field that names one kind of thing (an area, a floor, a program to start, a group of alert lights) takes that thing's key alone instead, never a reference.

### Path
An entity's way down through its device's YAML, from the block key the author wrote under the device, every written level a segment, a dot between levels: `appliance.programs.detected.cotton.other.statistics.energy.month`. A declared thing's path is that thing's own entity (`switches.sprinkler`, `appliance.running_program`); what pururu creates unwritten sits under the node it is born under (`appliance.running_program.last_cycle_end`); a period is the last segment of its meter's.

### Entity key
The part of an entity ID after the device key and the namespace (`running`, `phase_warming_cycles_total`): how pururu names the entity in Home Assistant, not how the YAML writes it. Its path and its entity key differ wherever a YAML level isn't in the ID. Renaming an entity in the UI changes its ID, never its path.

### Inside and outside form
An entity's reference as its own device writes it (inside: the path, `appliance.running_program`) and as any other device writes it (outside: `device.clothes_washer.appliance.running_program`). Every entity shows both in its `reference` attribute; a bus event's `key` and `states` keys are the inside form, its `event_name` the outside form.

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

## Goals

### Goal
What a device must achieve in each calendar period, measured by something that accumulates: the pool filters 6 hours a day, tracked by its runtime total.
*Avoid:* debt, quota

A goal's target is a number in the tracked entity's unit. Its done is how much that entity grew since the period began, whoever caused it; what's left, met and at risk all derive from the two.
