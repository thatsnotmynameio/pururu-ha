# Reaction retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reaction on `at` or `sun` takes `retry: {times, every}`: its automation triggers again `every`, `2 × every`, … after the occurrence, each try skipped once the occurrence ran.

**Architecture:** All in `custom_components/pururu/reactions.py`. The schema gains `retry`; `triggers()` appends one trigger per try (`id: retry_<k>`, trigger variable `since`); a new `conditions()` returns one template condition reading `last_triggered` (the program's script with `then`, the automation's own `this` without); `automation()` adds `conditions` only with `retry`. HA keeps the memory (`last_triggered` is restored at a restart); pururu adds no entity.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3, voluptuous, pytest with `pytest-homeassistant-custom-component`, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-29-reaction-retry-design.md`

## Global Constraints

- Sources: `retry` only with `at` or `sun`; otherwise `a reaction's retry goes with at or sun`.
- `retry.times`: integer, at least 1. `retry.every`: time period, at least a minute. Both required, no other key.
- `times × every` at most 12 hours; otherwise `a reaction's retries must end within 12 hours`.
- Window of try `k`: `since = k × every + 60 s`, in whole seconds.
- A reaction without `retry` generates exactly today's automation: no `conditions` key.
- Commands from the worktree root with `uv`; `-n 0` for a single process. Never leave the shell inside `.venv/.../homeassistant/helpers/`.
- Tests aren't linted, but `custom_components/pururu` must pass `ruff check`, `ruff format` and strict `mypy` (`tests/test_code.py` runs them).
- Commits end with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_013KdDdcZMQ3rQftBV8pNTDf
  ```

## Review Focus

- A reaction without `retry` must generate byte-for-byte today's automation (every user's existing file) → Task 2, `test_without_retry_there_are_no_conditions`.
- A retry crossing midnight (`at: "23:30"`, every hour) must wrap to `00:30:00`, not fail → Task 2, `test_retries_wrap_past_midnight`.
- Running the automation by hand after a missed occurrence counts as run: the next try is skipped → Task 3, `test_a_run_by_hand_skips_the_tries`.
- The program's script renamed in the UI: the condition must read the new ID, or every try would pass → Task 2, `test_the_condition_follows_the_script_renamed`.
- A restart between the occurrence and a try: the restored `last_triggered` must still skip it → Task 3, `test_a_restart_keeps_the_occurrences_run`.

---

### Task 1: The `retry` setting

**Files:**
- Modify: `custom_components/pururu/reactions.py` (imports, constants, `_consistent`, `REACTION`)
- Test: `tests/test_reactions.py` (the configuration section)

**Interfaces:**
- Produces: `reactions.RETRY_LIMIT: timedelta` (12 h), `reactions.SLACK: timedelta` (1 min); a validated reaction's `reaction["retry"]` is `{"times": int, "every": timedelta}` when given.

- [ ] **Step 1: Write the failing tests**

In `tests/test_reactions.py`, add to the parameters of `test_valid_reaction_is_accepted`:

```python
    pytest.param({"name": "Tarde", "at": "13:00", "retry": {"times": 3, "every": {"hours": 1}}},
                 id="retry on a time"),
    pytest.param({"name": "Anoitecer", "sun": "sunset", "offset": {"minutes": -30},
                  "retry": {"times": 1, "every": {"minutes": 1}}}, id="retry on the sun"),
    pytest.param({"name": "Tarde", "at": "13:00", "retry": {"times": 12, "every": {"hours": 1}}},
                 id="retries ending at 12 hours"),
```

and to the parameters of `test_invalid_reaction_is_refused`:

```python
    pytest.param({**DOOR_OPENS, "retry": {"times": 1, "every": {"hours": 1}}},
                 "a reaction's retry goes with at or sun", id="retry on an entity"),
    pytest.param({"name": "X", "when": "light_teto", "to": "on",
                  "retry": {"times": 1, "every": {"hours": 1}}},
                 "a reaction's retry goes with at or sun", id="retry on when"),
    pytest.param({"name": "X", "at": "13:00", "retry": {"times": 0, "every": {"hours": 1}}},
                 "value must be at least 1", id="no retry"),
    pytest.param({"name": "X", "at": "13:00", "retry": {"times": 1, "every": {"seconds": 59}}},
                 "value must be at least 0:01:00", id="retry every under a minute"),
    pytest.param({"name": "X", "at": "13:00", "retry": {"times": 13, "every": {"hours": 1}}},
                 "a reaction's retries must end within 12 hours", id="retries over 12 hours"),
    pytest.param({"name": "X", "at": "13:00", "retry": {"every": {"hours": 1}}},
                 "required key 'times' not provided", id="retry without times"),
    pytest.param({"name": "X", "at": "13:00", "retry": {"times": 1}},
                 "required key 'every' not provided", id="retry without every"),
    pytest.param({"name": "X", "at": "13:00",
                  "retry": {"times": 1, "every": {"hours": 1}, "until": "on"}},
                 f"'until' is an invalid option for 'pururu', check: {PATH[1:]}->retry->until",
                 id="unknown key in retry"),
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_reactions.py -n 0 -q -k "accepted or refused"`
Expected: the three new accepted cases FAIL (`retry` is an extra key); the refused ones fail on their reason (refused for `'retry' is an invalid option`).

- [ ] **Step 3: Implement**

In `custom_components/pururu/reactions.py`, import `timedelta` (`from datetime import timedelta`), and add after `STATE_KEYS`:

```python
# How late a reaction's last try may be, after its occurrence: a chain never
# reaches the next day's occurrence, and a sun event drifts a few minutes a day
RETRY_LIMIT = timedelta(hours=12)
# Added to a try's window: the occurrence's run is recorded a moment after it
SLACK = timedelta(minutes=1)
RETRY = vol.Schema(
    {
        vol.Required("times"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Required("every"): vol.All(
            cv.positive_time_period, vol.Range(min=timedelta(minutes=1))
        ),
    }
)
```

In `_consistent`, right after the `offset` check:

```python
    if "retry" in reaction:
        if sources[0] not in ("at", "sun"):
            raise vol.Invalid("a reaction's retry goes with at or sun")
        retry = reaction["retry"]
        if retry["times"] * retry["every"] > RETRY_LIMIT:
            raise vol.Invalid("a reaction's retries must end within 12 hours")
```

In `REACTION`'s schema, after `offset`:

```python
            # More tries of an at or sun occurrence, each skipped once it ran
            vol.Optional("retry"): RETRY,
```

- [ ] **Step 4: Run them to see them pass**

Run: `uv run pytest tests/test_reactions.py -n 0 -q -k "accepted or refused"`
Expected: PASS. If a refused case fails on its wording only (voluptuous words `Range` for a timedelta as `value must be at least 0:01:00`), print the error list the test shows and fix the test's expected text to voluptuous's, not the code.

- [ ] **Step 5: Commit**

```bash
git add custom_components/pururu/reactions.py tests/test_reactions.py
git commit -m "pururu: a reaction's retry setting, on at and sun"
```

---

### Task 2: The tries and their condition in the generated automation

**Files:**
- Modify: `custom_components/pururu/reactions.py` (`triggers`, new `_occurrence`, `_retries`, `conditions`, `automation`)
- Test: `tests/test_reactions.py` (the translation and generation sections)

**Interfaces:**
- Consumes: `RETRY_LIMIT`, `SLACK`, `reaction["retry"]` from Task 1; `period` from `generated.py`.
- Produces: `reactions.triggers(reaction, entity_id) -> list[dict[str, Any]]` (occurrence first, then tries); `reactions.conditions(reaction, script: str | None) -> list[dict[str, Any]]`; `reactions.automation(...)` unchanged signature, with a `conditions` key between `triggers` and `actions` only when `retry` is set.

- [ ] **Step 1: Write the failing tests**

In `tests/test_reactions.py`, after `test_a_fraction_of_a_second_is_kept`:

```python
RETRY = {"times": 3, "every": {"hours": 1}}


def test_retries_are_the_time_again(ha: HomeAssistant) -> None:
    assert translated(ha, {"name": "Tarde", "at": "13:00:30", "retry": RETRY}) == [
        {"trigger": "time", "at": "13:00:30"},
        {"trigger": "time", "at": "14:00:30", "id": "retry_1", "variables": {"since": 3660}},
        {"trigger": "time", "at": "15:00:30", "id": "retry_2", "variables": {"since": 7260}},
        {"trigger": "time", "at": "16:00:30", "id": "retry_3", "variables": {"since": 10860}},
    ]


def test_retries_wrap_past_midnight(ha: HomeAssistant) -> None:
    triggers = translated(ha, {"name": "Noite", "at": "23:30",
                               "retry": {"times": 2, "every": {"minutes": 45}}})
    assert [t["at"] for t in triggers] == ["23:30:00", "00:15:00", "01:00:00"]


def test_retries_of_the_sun_add_to_its_offset(ha: HomeAssistant) -> None:
    assert translated(ha, {"name": "X", "sun": "sunset", "offset": {"minutes": -30},
                           "retry": {"times": 2, "every": {"minutes": 20}}}) == [
        {"trigger": "sun", "event": "sunset", "offset": "-00:30:00"},
        {"trigger": "sun", "event": "sunset", "offset": "-00:10:00", "id": "retry_1",
         "variables": {"since": 1260}},
        {"trigger": "sun", "event": "sunset", "offset": "00:10:00", "id": "retry_2",
         "variables": {"since": 2460}},
    ]


def test_retries_of_the_sun_without_offset(ha: HomeAssistant) -> None:
    assert translated(ha, {"name": "X", "sun": "sunrise",
                           "retry": {"times": 1, "every": {"hours": 1}}}) == [
        {"trigger": "sun", "event": "sunrise"},
        {"trigger": "sun", "event": "sunrise", "offset": "01:00:00", "id": "retry_1",
         "variables": {"since": 3660}},
    ]


RAN = ("{{% set last = {} %}}{{{{ since is not defined or last is none"
       " or as_datetime(last) < now() - timedelta(seconds=since) }}}}")


def test_a_try_without_then_looks_at_the_automation(ha: HomeAssistant) -> None:
    reactions = module("reactions")
    reaction = reactions.REACTION({"name": "Tarde", "at": "13:00", "retry": RETRY})
    assert reactions.automation(LIGHTS, "Luzes", "afternoon", reaction, None)["conditions"] == [
        {"condition": "template",
         "value_template": RAN.format("this.attributes.last_triggered")}]


def test_a_try_with_then_looks_at_the_program(ha: HomeAssistant) -> None:
    reactions = module("reactions")
    reaction = reactions.REACTION({"name": "Tarde", "at": "13:00", "retry": RETRY,
                                   "then": "clean"})
    script = "script.pururu_lights_program_clean"
    assert reactions.automation(LIGHTS, "Luzes", "afternoon", reaction, None,
                                script)["conditions"] == [
        {"condition": "template",
         "value_template": RAN.format(f"state_attr('{script}', 'last_triggered')")}]


def test_without_retry_there_are_no_conditions(ha: HomeAssistant) -> None:
    """Every file written before retry is written again the same."""
    reactions = module("reactions")
    reaction = reactions.REACTION({"name": "Noite", "at": "22:00", "then": "clean"})
    written = reactions.automation(LIGHTS, "Luzes", "night", reaction, None,
                                   "script.pururu_lights_program_clean")
    assert list(written) == ["id", "alias", "description", "triggers", "actions"]


def test_conditions_come_before_actions(ha: HomeAssistant) -> None:
    reactions = module("reactions")
    reaction = reactions.REACTION({"name": "Tarde", "at": "13:00", "retry": RETRY})
    assert list(reactions.automation(LIGHTS, "Luzes", "afternoon", reaction, None)) == [
        "id", "alias", "description", "triggers", "conditions", "actions"]
```

And in the `then` section, after `test_it_follows_the_script_renamed`:

```python
async def test_the_condition_follows_the_script_renamed(ha: HomeAssistant) -> None:
    """With the old ID, last_triggered would be none and every try would run."""
    await fake(ha, REAL_SPRINKLER, "off")
    assert await setup(ha, greenhouse(clean={"name": "Tarde", "at": "13:00", "then": "clean",
                                       "retry": {"times": 1, "every": {"hours": 1}}}))
    er.async_get(ha).async_update_entity(CLEAN, new_entity_id="script.limpar_estufa")
    await ha.async_block_till_done()
    assert generated(ha)[0]["conditions"] == module("reactions").conditions(
        {"retry": {"times": 1, "every": timedelta(hours=1)}}, "script.limpar_estufa")
    assert "script.limpar_estufa" in generated(ha)[0]["conditions"][0]["value_template"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_reactions.py -n 0 -q -k "retr or try or conditions"`
Expected: FAIL: the triggers have no tries, `conditions` is missing (`KeyError`), `reactions.conditions` doesn't exist.

- [ ] **Step 3: Implement**

In `custom_components/pururu/reactions.py`, change the import to `from datetime import date, datetime, timedelta`, and add after `SLACK`:

```python
# Whether a try may run: the occurrence always, a try without a run in its window
RAN = (
    "{{% set last = {last} %}}"
    "{{{{ since is not defined or last is none"
    " or as_datetime(last) < now() - timedelta(seconds=since) }}}}"
)
```

Replace the `at`/`sun` part of `triggers` with a call, and add the helpers before `triggers`:

```python
def _occurrence(reaction: Mapping[str, Any], later: timedelta) -> dict[str, Any]:
    """The trigger of an at or sun reaction, `later` after its time."""
    if "at" in reaction:
        at = datetime.combine(date.min, reaction["at"]) + later
        return {"trigger": "time", "at": at.time().isoformat()}
    sun: dict[str, Any] = {"trigger": "sun", "event": reaction["sun"]}
    if "offset" in reaction or later:
        sun["offset"] = period(reaction.get("offset", timedelta(0)) + later)
    return sun


def _retries(reaction: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Each try, `k × every` after the occurrence, with its window in seconds."""
    if "retry" not in reaction:
        return []
    every: timedelta = reaction["retry"]["every"]
    return [
        {
            **_occurrence(reaction, k * every),
            "id": f"retry_{k}",
            "variables": {"since": int((k * every + SLACK).total_seconds())},
        }
        for k in range(1, reaction["retry"]["times"] + 1)
    ]
```

`date.min` plus at most 12 h plus a day's time stays within `datetime`'s range (the year 1, day 2 at most).

In `triggers`, replace:

```python
    if "at" in reaction:
        return [{"trigger": "time", "at": reaction["at"].isoformat()}]
    if "sun" in reaction:
        sun: dict[str, Any] = {"trigger": "sun", "event": reaction["sun"]}
        if "offset" in reaction:
            sun["offset"] = period(reaction["offset"])
        return [sun]
```

with:

```python
    if "at" in reaction or "sun" in reaction:
        return [_occurrence(reaction, timedelta(0)), *_retries(reaction)]
```

and add to its docstring: `An at or sun reaction with retry also triggers at each try (retry_<k>).`

After `triggers`, add:

```python
def conditions(reaction: Mapping[str, Any], script: str | None) -> list[dict[str, Any]]:
    """With retry, a try runs only if nothing ran since the occurrence; none without.

    What ran: the program started (`script`, its current entity ID), from here
    or anywhere; without a program, the automation fired (`this`, its state
    before this run). HA restores both at a restart. A condition, not an
    action: a skipped try isn't a trigger.
    """
    if "retry" not in reaction:
        return []
    last = (
        "this.attributes.last_triggered"
        if script is None
        else f"state_attr('{script}', 'last_triggered')"
    )
    return [{"condition": "template", "value_template": RAN.format(last=last)}]
```

Replace the body of `automation` with:

```python
    written: dict[str, Any] = {
        "id": automation_id(device_key, reaction_key),
        "alias": f"{device_name} {reaction[CONF_NAME]}",
        "description": f"pururu: {device_key}, {reaction_key}",
        "triggers": triggers(reaction, entity_id),
    }
    if checks := conditions(reaction, script):
        written["conditions"] = checks
    written["actions"] = actions(script)
    return written
```

Update the module docstring's first paragraph: add `An at or sun reaction can retry: its automation triggers again, each try skipped once the occurrence ran.`

- [ ] **Step 4: Run them to see them pass, and the whole file**

Run: `uv run pytest tests/test_reactions.py -n 0 -q`
Expected: PASS, the existing tests included (no `conditions` without `retry`).

- [ ] **Step 5: Lint and types**

Run: `uv run ruff check --fix custom_components/pururu && uv run ruff format custom_components/pururu && uv run mypy custom_components/pururu`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add custom_components/pururu/reactions.py tests/test_reactions.py
git commit -m "pururu: a reaction's tries, each skipped once the occurrence ran"
```

---

### Task 3: The tries in Home Assistant

Real automations and scripts, from the generated files, with frozen time (the `ha` fixture starts on a Wednesday at 10:00). These tests prove the template: if one fails, fix `RAN` or `conditions` in `reactions.py` (and Task 2's expected strings), not the test's expectation of behaviour.

**Files:**
- Test: `tests/test_reactions.py` (a new section `# --- retry ---` at the end)
- Modify (only if a test fails): `custom_components/pururu/reactions.py`

**Interfaces:**
- Consumes: the fixtures `automations` and `both`, `capture`, `tick`, `fake`, `settle`, `setup`, `generated`, `greenhouse`, `CLEAN`, `REAL_SPRINKLER` from `tests/test_reactions.py` and `tests/helpers.py`.

- [ ] **Step 1: Write the tests**

Add at the top of `tests/test_reactions.py`, next to the other imports:

```python
from pytest_homeassistant_custom_component.common import mock_restore_cache
```

and at the end of the file:

```python
# --- retry --------------------------------------------------------------------------------

SOON = {"name": "Logo", "at": "10:05", "retry": {"times": 2, "every": {"minutes": 10}}}


def runs(events: list[Any], key: str) -> int:
    """How many times the reaction's automation ran (its conditions passed)."""
    return sum(1 for e in events if e.data["entity_id"] == automation(key))


async def switch(ha: HomeAssistant, key: str, on: bool) -> None:
    await ha.services.async_call("automation", "turn_on" if on else "turn_off",
                                 {"entity_id": automation(key)}, blocking=True)


async def test_the_occurrence_run_skips_the_tries(ha: HomeAssistant, freezer: Any,
                                                  automations: None) -> None:
    assert await setup(ha, devices(soon=SOON))
    triggered = capture(ha, "automation_triggered")
    await tick(ha, freezer, 300)    # 10:05, the occurrence
    assert runs(triggered, "soon") == 1
    await tick(ha, freezer, 600)    # 10:15
    await tick(ha, freezer, 600)    # 10:25
    assert runs(triggered, "soon") == 1


async def test_a_missed_occurrence_is_tried_again_once(ha: HomeAssistant, freezer: Any,
                                                       automations: None) -> None:
    assert await setup(ha, devices(soon=SOON))
    triggered = capture(ha, "automation_triggered")
    await switch(ha, "soon", on=False)
    await tick(ha, freezer, 300)    # 10:05, off
    await switch(ha, "soon", on=True)
    assert runs(triggered, "soon") == 0
    await tick(ha, freezer, 600)    # 10:15, the first try runs
    assert runs(triggered, "soon") == 1
    await tick(ha, freezer, 600)    # 10:25, skipped
    assert runs(triggered, "soon") == 1


async def test_a_run_by_hand_skips_the_tries(ha: HomeAssistant, freezer: Any,
                                             automations: None) -> None:
    assert await setup(ha, devices(soon=SOON))
    triggered = capture(ha, "automation_triggered")
    await switch(ha, "soon", on=False)
    await tick(ha, freezer, 300)    # 10:05, off
    await switch(ha, "soon", on=True)
    await tick(ha, freezer, 60)
    await ha.services.async_call("automation", "trigger",
                                 {"entity_id": automation("soon")}, blocking=True)
    assert runs(triggered, "soon") == 1
    await tick(ha, freezer, 540)    # 10:15
    await tick(ha, freezer, 600)    # 10:25
    assert runs(triggered, "soon") == 1


async def test_a_restart_keeps_the_occurrences_run(ha: HomeAssistant, freezer: Any) -> None:
    """HA restores last_triggered: after a restart, a try still sees the occurrence's run."""
    assert await setup(ha, devices(soon=SOON))
    await tick(ha, freezer, 360)    # 10:06: the occurrence ran at 10:05, then HA restarted
    ran = (dt_util.utcnow() - timedelta(minutes=1)).isoformat()
    mock_restore_cache(ha, [State(automation("soon"), "on", {"last_triggered": ran})])
    with patch("homeassistant.config.load_yaml_config_file",
               side_effect=lambda *_args, **_kwargs: {"automation pururu": generated(ha)}):
        assert await async_setup_component(ha, "automation",
                                           {"automation pururu": generated(ha)})
    await ha.async_block_till_done()
    triggered = capture(ha, "automation_triggered")
    await tick(ha, freezer, 540)    # 10:15
    await tick(ha, freezer, 600)    # 10:25
    assert runs(triggered, "soon") == 0


async def test_a_busy_program_is_started_by_a_try(ha: HomeAssistant, freezer: Any,
                                                  both: None) -> None:
    """Started by hand at 10:00, it runs 2 hours: 10:05 and 11:05 find it running, 12:05 starts it."""
    await fake(ha, REAL_SPRINKLER, "off")
    assert await setup(ha, greenhouse(clean={"name": "Logo", "at": "10:05", "then": "clean",
                                       "retry": {"times": 3, "every": {"hours": 1}}}))
    await ha.services.async_call("script", "turn_on", {"entity_id": CLEAN}, blocking=True)
    await settle()
    triggered = capture(ha, "automation_triggered")
    started = capture(ha, "script_started")
    await tick(ha, freezer, 300)    # 10:05, busy
    await tick(ha, freezer, 3600)   # 11:05, a try: nothing started since, still busy
    await settle()
    assert (len(triggered), len(started)) == (2, 0)
    await tick(ha, freezer, 3360)   # 12:01: the program ended at 12:00
    await settle()
    await tick(ha, freezer, 240)    # 12:05, a try
    await settle()
    assert (len(triggered), len(started)) == (3, 1)


async def test_a_program_started_after_the_occurrence_skips_the_tries(
        ha: HomeAssistant, freezer: Any, both: None) -> None:
    await fake(ha, REAL_SPRINKLER, "off")
    assert await setup(ha, greenhouse(clean={"name": "Logo", "at": "10:05", "then": "clean",
                                       "retry": {"times": 2, "every": {"hours": 3}}}))
    await ha.services.async_call("automation", "turn_off",
                                 {"entity_id": "automation.pururu_greenhouse_reaction_clean"},
                                 blocking=True)
    await tick(ha, freezer, 300)    # 10:05, off
    await ha.services.async_call("automation", "turn_on",
                                 {"entity_id": "automation.pururu_greenhouse_reaction_clean"},
                                 blocking=True)
    await ha.services.async_call("script", "turn_on", {"entity_id": CLEAN}, blocking=True)
    await settle()                  # started by hand at 10:05, ends at 12:05
    triggered = capture(ha, "automation_triggered")
    await tick(ha, freezer, 3 * 3600)   # 13:05
    await tick(ha, freezer, 3 * 3600)   # 16:05
    assert len(triggered) == 0


async def test_the_sun_is_tried_again(ha: HomeAssistant, freezer: Any,
                                      automations: None) -> None:
    assert await setup(ha, devices(dusk={"name": "Anoitecer", "sun": "sunset",
                                         "retry": {"times": 1, "every": {"minutes": 10}}}))
    triggered = capture(ha, "automation_triggered")
    await switch(ha, "dusk", on=False)
    sunset = get_astral_event_next(ha, "sunset")
    await tick(ha, freezer, (sunset - dt_util.utcnow()).total_seconds())
    await switch(ha, "dusk", on=True)
    assert runs(triggered, "dusk") == 0
    await tick(ha, freezer, 600)
    assert runs(triggered, "dusk") == 1
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/test_reactions.py -n 0 -q -k "occurrence or missed or by_hand or restart or busy or started_after or sun_is_tried"`
Expected: PASS. If one fails, read the automation's trace to see why:

```python
from homeassistant.components.trace import DATA_TRACE  # in a debug print only
```

or log the rendered template with `ha.states.get(automation("soon")).attributes`. Likely causes, in order: `as_datetime` given a `datetime` (HA's filter takes both; if not, use `last | as_datetime` or compare `last` directly), `since` not reaching the condition (trigger `variables` are merged into the run's variables; if not, read `trigger.id` and move the seconds into a map keyed by id in `RAN`), `this` being `None` (it is the automation's state; it exists once the automation is set up). Fix `reactions.py`, update Task 2's `RAN` expectations to match, and rerun the whole file.

- [ ] **Step 3: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS (it includes ruff, mypy, hassfest and the quality scale).

- [ ] **Step 4: Commit**

```bash
git add tests/test_reactions.py custom_components/pururu/reactions.py
git commit -m "pururu: reaction retries tried in Home Assistant"
```

---

### Task 4: Docs, CLAUDE.md, version

**Files:**
- Modify: `docs/concepts/reactions.mdx`
- Modify: `docs/reference/configuration.mdx:182-184`
- Modify: `CLAUDE.md` (Architecture, step 6)
- Modify: `custom_components/pururu/manifest.json` (`version`)

- [ ] **Step 1: `docs/concepts/reactions.mdx`**

In **Settings**, after the `offset` property (the end of "The sun"), add:

````mdx
### Trying again

<Property name="retry.times" type="integer" optional>
  How many more tries after the time or the sun event, at least 1. Only with `at` or `sun`.
</Property>

---

<Property name="retry.every" type="time period" optional>
  The interval between tries, at least a minute: the first try is `every` after the occurrence, the second `2 × every`, and so on. `times × every` can't go over 12 hours.
</Property>
````

Add a section after **Starting a program**:

````mdx
## Trying again

A reaction on a time or on the sun fires once a day. If it didn't run then (Home Assistant was restarting, the automation was off, its program was already running), `retry` tries again:

```yaml title="configuration.yaml"
reactions:
  afternoon:
    name: Tarde
    at: "13:00"
    then: water
    retry: {times: 3, every: {hours: 1}}
```

The automation triggers at 13:00, and again at 14:00, 15:00 and 16:00. A try runs only if **nothing ran since 13:00**:

- **With `then`**, running means the program started: from this reaction, the UI, a voice assistant, anything.
- **Without `then`**, it means the automation fired, including a run by hand.

```yaml title="pururu/automations/reactions.yaml"
- id: pururu_orchard_reaction_afternoon
  alias: Pomar Tarde
  triggers:
    - {trigger: time, at: "13:00:00"}
    - {trigger: time, at: "14:00:00", id: retry_1, variables: {since: 3660}}
    - {trigger: time, at: "15:00:00", id: retry_2, variables: {since: 7260}}
    - {trigger: time, at: "16:00:00", id: retry_3, variables: {since: 10860}}
  conditions:
    - condition: template
      value_template: >-
        {% set last = state_attr('script.pururu_orchard_program_water', 'last_triggered') %}
        {{ since is not defined or last is none or as_datetime(last) < now() - timedelta(seconds=since) }}
  actions: [...]
```

| When | What happens |
|---|---|
| It ran at 13:00 | Every try is skipped: its trace shows the condition failing |
| Home Assistant was down at 13:00, back at 13:30 | 14:00 runs; 15:00 and 16:00 are skipped |
| The automation was off at 13:00, turned on at 14:30 | 15:00 runs; 16:00 is skipped |
| With `then`, the program was already running at 13:00 | 14:00 starts it if it has ended by then, or 15:00 tries |
| With `then`, you started the program by hand at 13:20 | Every try is skipped |
| Every try missed | Nothing more until tomorrow |

- **A restart** doesn't lose it: Home Assistant keeps `last_triggered` of automations and scripts.
- **Past midnight** is fine: `at: "23:00"` with three tries every hour tries at 00:00, 01:00 and 02:00.
- **The sun:** a try is the same event with its offset moved: sunset, then sunset + 1 h, and so on.
- **Daylight saving:** a chain across the clock change can be an hour off, and going back an hour a try may run once more.
- **Only a time or the sun:** a reaction on an entity is an event; Home Assistant down when it happens never sees it, and a later try would miss it too. `retry` there is a configuration error: `a reaction's retry goes with at or sun`.
````

In **Statistics**, after "**Every trigger counts**…", add:

```mdx
- **A try skipped** (it ran already) isn't a trigger: its condition failed. A try that runs counts.
```

- [ ] **Step 2: `docs/reference/configuration.mdx`**

Change the `reactions` property's text to:

```mdx
  A map of **reaction key → reaction**, each one a Home Assistant automation. It isn't a feature. A reaction's `then` names one of the device's `programs`, started when it fires, and a reaction on `at` or `sun` can `retry`. See [Reactions](/concepts/reactions#settings).
```

- [ ] **Step 3: `CLAUDE.md`**

In Architecture, step 6, after `(… held → held)` in the first parenthesis's sentence about reactions, add to that parenthesis: `; a reaction on at or sun can retry: more triggers, retry_<k>, each skipped by a template condition on last_triggered (the program's script with then, the automation's own this without) once the occurrence ran`.

- [ ] **Step 4: Version**

Check main and the open PRs for the next free version (memory: two PRs bumping to the same version, the second never ships):

```bash
git fetch -q && git show origin/main:custom_components/pururu/manifest.json | grep version
gh pr list --state open --json number,title,headRefName
gh release list -L 1
```

Set `version` in `custom_components/pururu/manifest.json` to the next patch after the highest of main, releases and open PRs (0.1.22 if nothing else claims it), then:

Run: `python3 release.py check`
Expected: OK.

- [ ] **Step 5: Check the docs**

Run: `pnpm install && pnpm docs:check`
Expected: no broken links.

- [ ] **Step 6: Run everything**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add docs/concepts/reactions.mdx docs/reference/configuration.mdx CLAUDE.md custom_components/pururu/manifest.json
git commit -m "docs: a reaction's retry; release <version>"
```
