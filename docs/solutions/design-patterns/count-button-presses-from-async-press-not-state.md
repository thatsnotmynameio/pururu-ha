---
title: Count a Home Assistant button's presses in async_press, never from its state
date: 2026-10-01
category: design-patterns
module: features/buttons
problem_type: design_pattern
component: service_layer
severity: medium
applies_when:
  - Counting presses or occurrences of a Home Assistant button entity
  - Counting occurrences of any entity whose state is the time of its last occurrence (button, event)
  - Adding a total, a meter or an alert that grows on each press
retire_when: "Home Assistant stops making ButtonEntity._async_press_action final, or adds a press event that fires on every press; check the button component in the pinned HA version"
tags: [buttons, home-assistant, button-entity, counting, totals, dispatcher, event-entity]
---

# Count a Home Assistant button's presses in async_press, never from its state

## Context

Each pururu button got a `<key>_triggered_total` sensor that counts its presses (PR #66, open as of this writing). The tempting design is a total that watches the button entity with `async_track_state_change_event` and adds one per state change: that's how every other pururu total reads its source. It is wrong for a button, and for any entity whose state is "when it last happened".

A Home Assistant button's state is the ISO time of its last press. `ButtonEntity._async_press_action` sets it to `dt_util.utcnow().isoformat()`, writes the state, then awaits `async_press()` (in Home Assistant's own package, `homeassistant/components/button/__init__.py`, lines 126-133 in HA 2026.9.3, installed under `.venv`). Two facts follow:

- **Two presses at the same instant are one state change.** HA writes no `state_changed` when the state and attributes are unchanged (it fires `state_reported` instead) (`same_state = old_state.state == new_state and not force_update` in HA's `core.py`). Under the test suite's frozen clock this always happens: three presses would count as one.
- **A restore is a state change nobody pressed.** On add, the button restores its last press time (`async_internal_added_to_hass`). After every restart or reload the state goes from `unavailable` (or from nothing, on a cold start) back to the time, which a state watcher would count.

## Guidance

Count where every press passes, not where its effect shows:

- `_async_press_action` is `@final`, so it can't be overridden. It always awaits `async_press`, for a press from the UI or `button.press`, and for pururu's own sensor-driven press (`entry.async_create_task(self.hass, self._async_press_action(), …)` in `Button._changed`).
- Send the press at the **top** of `Button.async_press`, before any early return (no program, program already running). A press that starts nothing is still a press.
- Send it on a dispatcher signal keyed by the button's item (`device.object_id(item.key("pressed"))`), and let the total listen. Don't hold a Python reference from the button to the total: a disabled total is never added to HA, and a disabled button never presses, so the signal makes both cases count nothing with no special code.

```python
# features/buttons.py (shape, not the full code)
async def async_press(self) -> None:
    async_dispatcher_send(self.hass, self._pressed)  # first: every press counts
    ...  # then start the program, or return early

class TriggeredTotal(CyclesTotal):  # restores, total_increasing, never decreases
    @override
    def _watch(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._pressed, self._press)
        )
```

Reuse `CyclesTotal` for the total (restore, `TOTAL_INCREASING`) and override `_watch`, as executable programs' `Runs` does. Don't send a fake `Cycle` on the cycle signal to reuse it unchanged: a press isn't a cycle, and other consumers read that signal.

## Why This Matters

A state-change counter passes a casual test with presses a second apart, then undercounts in production whenever two presses share a timestamp, and overcounts by one at every restart and reload. Totals are `total_increasing` and feed long-term statistics and per-period meters, so a wrong count can't be corrected afterwards.

## When to Apply

- Any counter, meter or alert over a pururu button's presses.
- The deferred `event.*` button sources: an `event` entity's state is also its last event's time, restored on add (HA's event component), with the same coalescing and restore traps. Count in the code path that receives the event, not from the entity's state.
- Not for entities whose state is the thing counted (a switch turning on, a door opening): their state changes are the events, and pururu's cycle totals already count those.

## Examples

Tests in `tests/test_buttons.py` that would fail with a state-change counter:

- `test_two_presses_at_one_instant_count_twice`: two `button.press` calls under the frozen clock make the total 2.
- `test_a_restart_keeps_the_total`: restored at 7, the total reads 7 after the restart (no phantom press), then 8 after one press.

And one that pins where the count sits, at the top of `async_press` before its early returns:

- `test_a_press_while_its_program_runs_still_counts`: a press that starts nothing still counts.

## Related

- `docs/plans/2026-10-01-0933-feat-button-statistics-plan.md`: KTD1 and KTD2.
- `docs/features/buttons.mdx`: the user-facing Statistics section.
