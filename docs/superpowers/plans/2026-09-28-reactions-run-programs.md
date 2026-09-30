# Reactions run programs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reaction's `then: <program>` makes its automation start that program's script, when the program isn't already running.

**Architecture:** `reactions.py` gains `then` in its schema and an `if` action in `automation()`. `__init__.py` validates `then` against the device's `programs`, syncs the programs' scripts before the reactions' automations, and makes a reaction follow its program (dropped → dropped, held → held). `generated.async_sync` returns the IDs it generated so the reactions know which scripts exist.

**Tech Stack:** Home Assistant 2026.9 custom integration, voluptuous, pytest-homeassistant-custom-component, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-28-reactions-run-programs-design.md`

## Global Constraints

- Version `0.1.17` in `custom_components/pururu/manifest.json`.
- `then` is optional; a reaction without it generates exactly the automation it does in 0.1.16 (`"actions": []`).
- `then` is one slug, a key of the **same device's** `programs`; refused otherwise with `reactions: <reaction key>: <then> is not a program of this device`.
- The action is `{"if": [{"condition": "state", "entity_id": <script>, "state": "off"}], "then": [{"action": "script.turn_on", "target": {"entity_id": <script>}}]}`, `<script>` the script's **current** entity ID from the registry.
- A reaction whose program's script isn't generated: dropped, logged `automation.<id> runs script.<id>, which is not generated; not generating it`; held when the program is held.
- Scripts are synced before automations in `async_setup_entry`.
- Run everything with `uv run`; ruff, mypy strict and hassfest run in `uv run pytest` (`tests/test_code.py`).

## Review Focus

- A program key that's also a reaction key (`clean` in both blocks): they're separate maps; `then: clean` means the program. Covered by the end-to-end test using the same key for both.
- A reaction with `then` on another device (`device: washer`): runs its own device's program, not the washer's. Covered in Task 2's accepted cases.
- The reaction held while its program is held, then the target enabled: the automation comes back with its registry entry (a user rename kept). Task 3.
- A script renamed in the UI: followed at pururu's next reload. Task 3.
- Two triggers while the program runs: the automation fires twice, the script is started once. Task 3.

---

### Task 1: `then` in the schema and the automation's action

**Files:**
- Modify: `custom_components/pururu/reactions.py`
- Test: `tests/test_reactions.py`

**Interfaces:**
- Produces: `reactions.REACTION` accepts `then: cv.slug`; `reactions.automation(device_key, device_name, reaction_key, reaction, entity_id, script=None) -> dict` — with `script` (an entity ID), `actions` is the `if` above.

- [ ] **Step 1: Write the failing tests** (after `test_the_automation_of_a_reaction`)

```python
def test_then_starts_its_program_unless_it_runs(ha: HomeAssistant) -> None:
    reactions = module("reactions")
    reaction = reactions.REACTION({**DOOR_OPENS, "then": "clean"})
    script = "script.pururu_lights_program_clean"
    assert reactions.automation(LIGHTS, "Luzes", "door", reaction, DOOR, script)["actions"] == [{
        "if": [{"condition": "state", "entity_id": script, "state": "off"}],
        "then": [{"action": "script.turn_on", "target": {"entity_id": script}}],
    }]


@pytest.mark.parametrize("then", [["clean"], "script.pururu_lights_program_clean", ""])
def test_then_is_a_slug(ha: HomeAssistant, then: Any) -> None:
    with pytest.raises(vol.Invalid):
        module("reactions").REACTION({**DOOR_OPENS, "then": then})
```

Add `import voluptuous as vol` to the test's imports.

- [ ] **Step 2: Run them, expect FAIL**

Run: `uv run pytest tests/test_reactions.py -n 0 -q -k "then"`
Expected: FAIL (`extra keys not allowed @ data['then']`, and `automation()` takes no `script`).

- [ ] **Step 3: Implement** in `reactions.py`

In `REACTION`'s schema, after `offset`:

```python
            # A program of this device, started when the reaction fires
            vol.Optional("then"): cv.slug,
```

Replace `automation`:

```python
def actions(script: str | None) -> list[dict[str, Any]]:
    """Start the program's script unless it runs; nothing without one.

    The check is an action, not a condition: HA counts a trigger only once its
    conditions pass, and a trigger skipped because the program runs still is one.
    """
    if script is None:
        return []
    return [
        {
            "if": [{"condition": "state", "entity_id": script, "state": STATE_OFF}],
            "then": [{"action": "script.turn_on", "target": {"entity_id": script}}],
        }
    ]


def automation(
    device_key: str,
    device_name: str,
    reaction_key: str,
    reaction: Mapping[str, Any],
    entity_id: str | None,
    script: str | None = None,
) -> dict[str, Any]:
    """The automation of a reaction; `script` is the current entity ID of its program's."""
    return {
        "id": automation_id(device_key, reaction_key),
        "alias": f"{device_name} {reaction[CONF_NAME]}",
        "description": f"pururu: {device_key}, {reaction_key}",
        "triggers": triggers(reaction, entity_id),
        "actions": actions(script),
    }
```

Import `STATE_OFF` from `homeassistant.const`. Module docstring's last sentence becomes: `It starts one of its device's programs (then), or does nothing: it fires, and its trace shows when and why.`

- [ ] **Step 4: Run, expect PASS**

Run: `uv run pytest tests/test_reactions.py -n 0 -q`
Expected: all pass, `test_the_automation_of_a_reaction` unchanged.

- [ ] **Step 5: Commit**

```bash
git add custom_components/pururu/reactions.py tests/test_reactions.py
git commit -m "reactions: then, its program's script started unless it runs"
```

### Task 2: `then` names a program of the device

**Files:**
- Modify: `custom_components/pururu/__init__.py` (`_reactions_on_this_device`)
- Test: `tests/test_reactions.py`

**Interfaces:**
- Consumes: `then` in `REACTION` (Task 1).

- [ ] **Step 1: Write the failing tests**

In `test_reactions.py`, a device with a program:

```python
CLEAN_PROGRAM = {"name": "Limpar", "sequence": [{"turn_on": "light_teto"}]}


def with_program(**reactions: dict[str, Any]) -> dict[str, Any]:
    config = devices(**reactions)
    config[LIGHTS]["programs"] = {"clean": CLEAN_PROGRAM}
    return config


@pytest.mark.parametrize("reaction", [
    pytest.param({**DOOR_OPENS, "then": "clean"}, id="real entity"),
    pytest.param({**OVERLOAD, "then": "clean"}, id="another device's entity, its own program"),
])
async def test_then_a_program_of_the_device_is_accepted(ha: HomeAssistant,
                                                        reaction: dict[str, Any]) -> None:
    assert await setup(ha, with_program(it=reaction))


@pytest.mark.parametrize("config", [
    pytest.param(with_program(it={**DOOR_OPENS, "then": "wash"}), id="no such program"),
    pytest.param(devices(it={**DOOR_OPENS, "then": "clean"}), id="the device has no programs"),
])
async def test_then_not_a_program_of_the_device_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, config: dict[str, Any]) -> None:
    then = config[LIGHTS]["reactions"]["it"]["then"]
    assert not await setup(ha, config)
    assert f"reactions: it: {then} is not a program of this device" in caplog.text


async def test_then_another_devices_program_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """The washer's program isn't the lights': a reaction runs its own device's."""
    config = devices(it={**OVERLOAD, "then": "clean"})
    config[WASHER]["programs"] = {"clean": {"name": "X", "sequence": [{"delay": 1}]}}
    config[WASHER]["switches"] = {"x": {"entity": "switch.dummy_x", "name": "X"}}
    assert not await setup(ha, config)
    assert "reactions: it: clean is not a program of this device" in caplog.text
```

- [ ] **Step 2: Run, expect FAIL**

Run: `uv run pytest tests/test_reactions.py -n 0 -q -k "then"`
Expected: the refusal tests FAIL (setup succeeds).

- [ ] **Step 3: Implement** in `_reactions_on_this_device`

```python
def _reactions_on_this_device(device: dict[str, Any]) -> None:
    """Refuse a reaction's `when` without `device` that isn't an entity key of the device, or `then` that isn't one of its programs."""
    keys = {
        qualified(FEATURES[name].namespace, entity_key)
        for name, entity_key, _ in _entity_keys(device)
    }
    for key, reaction in device.get(CONF_REACTIONS, {}).items():
        then = reaction.get("then")
        if then is not None and then not in device.get(CONF_PROGRAMS, {}):
            raise vol.Invalid(
                f"reactions: {key}: {then} is not a program of this device"
            )
        if "device" in reaction or (when := reaction.get("when")) is None:
            continue
        if when not in keys:
            raise vol.Invalid(
                f"reactions: {key}: {when} is not an entity key of this device"
            )
```

Keep the docstring under ruff's line length (wrap it as a summary line plus a sentence if E501 fires).

- [ ] **Step 4: Run, expect PASS**

Run: `uv run pytest tests/test_reactions.py -n 0 -q`

- [ ] **Step 5: Commit**

```bash
git add custom_components/pururu/__init__.py tests/test_reactions.py
git commit -m "reactions: then names a program of the reaction's device"
```

### Task 3: the automation starts the script; the reaction follows its program

**Files:**
- Modify: `custom_components/pururu/generated.py` (`async_sync` returns its IDs)
- Modify: `custom_components/pururu/__init__.py` (`async_setup_entry` order, `_automations`)
- Test: `tests/test_reactions.py`, `tests/test_generated.py`

**Interfaces:**
- Consumes: `reactions.automation(..., script)` (Task 1).
- Produces: `generated.async_sync(...) -> list[str]` (the generated unique IDs, after `_free`); `_automations(hass, devices, created, scripts: Collection[str], held_scripts: Collection[str]) -> tuple[list[generated.Item], set[str]]` (the automations, and the IDs of reactions held).

- [ ] **Step 1: Write the failing tests** in `tests/test_reactions.py` (end of file)

```python
# --- then: its program ------------------------------------------------------------------

GREENHOUSE = "greenhouse"
REAL_SPRINKLER = "switch.greenhouse_sprinkler"
SPRINKLER = "switch.pururu_greenhouse_switch_sprinkler"
CLEAN = "script.pururu_greenhouse_program_clean"
CLEANING: dict[str, Any] = {"name": "Limpar", "sequence": [
    {"turn_on": "switch_sprinkler"}, {"delay": {"hours": 2}}, {"turn_off": "switch_sprinkler"}]}


def greenhouse(**reactions: dict[str, Any]) -> dict[str, Any]:
    """The greenhouse: its sprinkler, its cleaning, and reactions to the door; `clean` also a reaction key."""
    return {GREENHOUSE: {"name": "Estufa",
                   "switches": {"sprinkler": {"entity": REAL_SPRINKLER, "name": "Irrigador"}},
                   "programs": {"clean": CLEANING},
                   "reactions": reactions or {"clean": {**DOOR_OPENS, "then": "clean"}}}}


@pytest.fixture
async def both(ha: HomeAssistant) -> AsyncIterator[None]:
    """HA's automations and scripts, from a configuration.yaml that includes pururu's files."""
    def included(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"automation pururu": generated(ha), "script pururu": generated_scripts(ha)}

    with patch("homeassistant.config.load_yaml_config_file", side_effect=included):
        assert await async_setup_component(ha, "script", {"script pururu": generated_scripts(ha)})
        assert await async_setup_component(ha, "automation",
                                           {"automation pururu": generated(ha)})
        yield


async def test_the_automation_starts_the_programs_script(ha: HomeAssistant) -> None:
    assert await setup(ha, greenhouse())
    assert generated(ha)[0]["actions"] == module("reactions").actions(CLEAN)


async def test_the_reaction_starts_its_program(ha: HomeAssistant, freezer: Any,
                                               both: None) -> None:
    await fake(ha, DOOR, "off")
    await fake(ha, REAL_SPRINKLER, "off")
    assert await setup(ha, greenhouse())
    calls = capture(ha, "call_service")
    await fake(ha, DOOR, "on")
    await settle()
    assert ha.states.get(CLEAN).state == "on"
    assert [e.data["service"] for e in calls
            if e.data["service_data"].get("entity_id") == REAL_SPRINKLER] == ["turn_on"]


async def test_a_trigger_while_the_program_runs_does_nothing(ha: HomeAssistant, freezer: Any,
                                                             both: None) -> None:
    await fake(ha, DOOR, "off")
    await fake(ha, REAL_SPRINKLER, "off")
    assert await setup(ha, greenhouse())
    triggered = capture(ha, "automation_triggered")
    started = capture(ha, "script_started")
    await fake(ha, DOOR, "on")
    await fake(ha, DOOR, "off")
    await fake(ha, DOOR, "on")
    await settle()
    assert len(triggered) == 2
    assert len(started) == 1
    assert ha.states.get(CLEAN).state == "on"


async def test_a_program_not_generated_drops_its_reaction(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    er.async_get(ha).async_get_or_create(
        "script", "template", "someone_else", suggested_object_id="pururu_greenhouse_program_clean")
    night = {"name": "Noite", "at": "22:00"}
    assert await setup(ha, greenhouse(clean={**DOOR_OPENS, "then": "clean"}, night=night))
    assert [a["id"] for a in generated(ha)] == ["pururu_greenhouse_reaction_night"]
    assert ("automation.pururu_greenhouse_reaction_clean runs script.pururu_greenhouse_program_clean, "
            "which is not generated; not generating it") in caplog.text


async def disable(hass: HomeAssistant, entity_id: str, disabled: bool = True) -> None:
    er.async_get(hass).async_update_entity(
        entity_id, disabled_by=er.RegistryEntryDisabler.USER if disabled else None)
    await hass.async_block_till_done()


async def test_a_held_program_holds_its_reaction(ha: HomeAssistant, freezer: Any,
                                                 both: None) -> None:
    """The sprinkler disabled: the program and its reaction are held, the reaction's rename kept."""
    await fake(ha, REAL_SPRINKLER, "off")
    assert await setup(ha, greenhouse())
    registry = er.async_get(ha)
    registry.async_update_entity("automation.pururu_greenhouse_reaction_clean",
                                 new_entity_id="automation.porta_limpa")
    await ha.async_block_till_done()
    await disable(ha, SPRINKLER)
    await tick(ha, freezer, 31)
    await ha.async_block_till_done()
    assert generated(ha) == []
    assert registry.async_get("automation.porta_limpa") is not None
    await disable(ha, SPRINKLER, disabled=False)
    await tick(ha, freezer, 31)
    await ha.async_block_till_done()
    assert [a["id"] for a in generated(ha)] == ["pururu_greenhouse_reaction_clean"]
    assert registry.async_get("automation.porta_limpa") is not None


async def test_it_follows_the_script_renamed(ha: HomeAssistant, both: None) -> None:
    await fake(ha, REAL_SPRINKLER, "off")
    assert await setup(ha, greenhouse())
    er.async_get(ha).async_update_entity(CLEAN, new_entity_id="script.limpar_estufa")
    await ha.async_block_till_done()
    await reload(ha, greenhouse())
    assert generated(ha)[0]["actions"] == module("reactions").actions("script.limpar_estufa")
```

Extend the helpers import: `from helpers import capture, fake, generated, generated_scripts, module, reload, settle, setup, tick`.

In `tests/test_generated.py`, next to its other `async_sync` tests, a direct test of the return value. Read the file's existing fixtures first and reuse its way of building an entry and items (it already calls the machinery for both kinds); the assertion is:

```python
    ids = await generated.async_sync(hass, entry, kind, [free_item, taken_item])
    assert ids == [free_item.unique_id]
```

with `taken_item`'s ID pre-registered by another platform (`async_get_or_create(kind.domain, "template", "x", suggested_object_id=taken_item.unique_id)`).

- [ ] **Step 2: Run, expect FAIL**

Run: `uv run pytest tests/test_reactions.py tests/test_generated.py -n 0 -q`
Expected: the new tests FAIL (`actions` is `[]`, `async_sync` returns None).

- [ ] **Step 3: Implement**

`generated.py`, `async_sync`: signature `-> list[str]`, docstring gains `Returns the IDs generated: the items' whose IDs are free.`, and `return ids` at the end.

`__init__.py`, `async_setup_entry`, replacing the two `generated.async_sync` calls:

```python
    scripts, held, targets = _scripts(hass, devices, created)
    generated_scripts = await generated.async_sync(
        hass, entry, programs.KIND, scripts, held
    )
    automations, held_automations = _automations(
        hass, devices, created, generated_scripts, held
    )
    await generated.async_sync(
        hass, entry, reactions.KIND, automations, held_automations
    )
```

Its docstring: `The programs' scripts come before the reactions' automations: a reaction starts one.`

`_automations`:

```python
def _automations(
    hass: HomeAssistant,
    devices: dict[str, dict[str, Any]],
    created: set[str],
    scripts: Collection[str],
    held_scripts: Collection[str],
) -> tuple[list[generated.Item], set[str]]:
    """An automation per reaction of every device; one that can't fire as written is logged.

    One watching an entity not created, or starting a program whose script isn't
    generated, isn't generated. Also the IDs of those held with their program.
    """
    registry = er.async_get(hass)
    automations: list[generated.Item] = []
    held: set[str] = set()
    for key, config in devices.items():
        for reaction_key, reaction in config.get(CONF_REACTIONS, {}).items():
            automation_id = reactions.automation_id(key, reaction_key)
            entity_id = reaction.get("entity")
            if (when := reaction.get("when")) is not None:
                owner_key = reaction.get("device", key)
                owner, entity_key, platform = _referable(owner_key, devices[owner_key])[
                    when
                ]
                if owner.object_id(entity_key) not in created:
                    _LOGGER.error(
                        "automation.%s follows %s, which is not created; "
                        "not generating it",
                        automation_id,
                        owner.entity_id(platform, entity_key),
                    )
                    continue
                entity_id = owner.current_entity_id(hass, platform, entity_key)
            script = None
            if (then := reaction.get("then")) is not None:
                script_id = programs.script_id(key, then)
                if script_id not in scripts:
                    _LOGGER.error(
                        "automation.%s runs script.%s, which is not generated; "
                        "not generating it",
                        automation_id,
                        script_id,
                    )
                    if script_id in held_scripts:
                        held.add(automation_id)
                    continue
                script = registry.async_get_entity_id(
                    programs.KIND.domain, programs.KIND.domain, script_id
                )
            automations.append(
                generated.Item(
                    unique_id=automation_id,
                    config=reactions.automation(
                        key, config[CONF_NAME], reaction_key, reaction, entity_id, script
                    ),
                )
            )
    return automations, held
```

`script` can't be None there: `async_sync` registered every ID it returns. mypy may still need it narrowed; if so, fall back to `f"script.{script_id}"` with `or`. Import `Collection` from `collections.abc` if not there.

- [ ] **Step 4: Run, expect PASS**

Run: `uv run pytest tests/test_reactions.py tests/test_generated.py tests/test_programs.py -n 0 -q`

- [ ] **Step 5: Run the whole suite** (ruff, mypy, hassfest included)

Run: `uv run pytest -q`

- [ ] **Step 6: Commit**

```bash
git add custom_components/pururu tests
git commit -m "reactions: start their program's script; follow it when dropped or held"
```

### Task 4: docs, CLAUDE.md, version

**Files:**
- Modify: `docs/concepts/reactions.mdx`, `docs/concepts/programs.mdx`, `docs/reference/configuration.mdx`, `docs/reference/troubleshooting.mdx`, `docs/develop/architecture.mdx`, `CLAUDE.md`, `custom_components/pururu/manifest.json`

- [ ] **Step 1: `docs/concepts/reactions.mdx`**
  - Remove the `<Info>` "fires and does nothing yet" block; the intro says a reaction can start one of its device's programs.
  - The example: add `programs:` to `laundry_lights` and `then:` on `washer_done`.
  - Settings: a `### What it does` section with `<Property name="then" type="program key" optional>`: a key of this device's `programs`; the reaction starts it unless it's running; without `then` it fires and does nothing.
  - A `## Starting a program` section: the generated `actions` YAML from the spec; the behaviour table from the spec.
  - The automation table: `Actions` → `starts the program's script with script.turn_on, unless it's running; none without then`.
  - Bullets: a program not generated → its reactions with `then` aren't either (the log line); held with its program.
- [ ] **Step 2: `docs/concepts/programs.mdx`**: "**No triggers.** Something outside starts it: you, an automation, a voice assistant." becomes "**No triggers of its own.** A [reaction](/concepts/reactions#starting-a-program)'s `then` starts it, or you, an automation, a voice assistant."
- [ ] **Step 3: `docs/reference/configuration.mdx`**: `then` in the example's reactions, one line in the reactions' property.
- [ ] **Step 4: `docs/reference/troubleshooting.mdx`**: a section `### `… runs script.…, which is not generated; not generating it`` with the log line and: the program's script isn't generated (an entity it acts on isn't created or is disabled, or its ID is taken; the log line before it says which); fix that and the reaction comes back.
- [ ] **Step 5: `docs/develop/architecture.mdx`** step 6: scripts before automations; a reaction's `then` follows its program. **`CLAUDE.md`** step 6: add "the programs' scripts first: a reaction's `then` starts one, and follows it (not generated → not generated, held → held)".
- [ ] **Step 6: `manifest.json`** version `0.1.17`; `python3 release.py check`.
- [ ] **Step 7: Check the docs**: `pnpm install` (once) then `pnpm docs:check`.
- [ ] **Step 8: Commit**

```bash
git add docs CLAUDE.md custom_components/pururu/manifest.json
git commit -m "docs: a reaction starts its device's program (0.1.17)"
```
