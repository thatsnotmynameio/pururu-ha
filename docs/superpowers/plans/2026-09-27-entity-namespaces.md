# Entity Namespaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every feature puts its entity keys in a namespace of its own, so every entity ID is `<platform>.pururu_<device key>_<namespace>_<entity key>` and two features can never give two entities one ID.

**Architecture:** `Feature` gains a required `namespace`, and `Device` gains a required `namespace` plus `qualified(entity_key)`, which `object_id`, `entity_id`, `current_entity_id` and the translation key go through. The core (`_build`) gives each feature's `build()` a `Device` in that feature's namespace, and resolves `<capability>_from` with a `Device` in the provider's namespace. Features keep writing local entity keys. The per-device check of alike entity keys goes away; the check between devices stays.

**Tech Stack:** Home Assistant 2026.9.3 custom integration, voluptuous, pytest with `pytest-homeassistant-custom-component`, docs.page MDX.

**Spec:** `docs/superpowers/specs/2026-09-27-entity-namespaces-design.md`

## Global Constraints

- Entity ID: `<platform>.pururu_<device key>_<namespace>_<entity key>`; an entity key equal to its namespace is written once (`sensor.pururu_washer_phase`). Unique ID is the part after the platform.
- Namespaces: `appliance` → `appliance`, `phases` → `phase`, `switches` → `switch`.
- Translation and icon keys are the qualified key (`appliance_running`); `phase` stays `phase`.
- The YAML doesn't change. Every configuration valid today stays valid.
- No migration: old entities are removed by stale removal.
- Version: `custom_components/pururu/manifest.json` `version` becomes `0.1.5`.
- Run everything from the worktree root with `uv`. Single test file: `uv run pytest tests/<file>.py -n 0 -q` (never `-p no:xdist`). Never leave the shell's cwd inside `.venv/.../homeassistant/helpers/`.
- ruff and mypy (strict) run on `custom_components/pururu` only, through `tests/test_code.py`; tests aren't linted. Match the surrounding code: short docstrings saying what and why, comments only where the code can't speak.
- Docs: `{` and `<` outside code are JSX in MDX; keep them in backticks. Check with `npx --yes @docs.page/cli check`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Upgrading from 0.1.4, with entities under the old IDs in the registry — a person expects the old ones removed, the namespaced ones created, and no "already taken" error. Test in Task 1 (`test_entities_from_before_namespaces_go_at_set_up`).
2. A translation or icon left under its old local key (`running`) — a person expects "Running", not a name made up from the entity ID. Tests in Task 1 (`test_every_translated_entity_key_is_created`, plus the existing `friendly_name` assertions in `test_appliance.py` and `test_phases.py`).
3. `phases` taking its cycle from `appliance` across two namespaces, also after `running` is renamed in the UI — a person expects the phase to follow. Tests in Task 1 (`test_phases.py::test_follows_a_renamed_cycle`, and `test_init.py::test_a_capability_reaches_the_feature_that_requires_it`, whose `echo` also pins the key-equals-namespace rule).
4. A switch keyed like an `appliance` entity key (`power`, `running`, `runtime_month`) — a person expects it accepted now, next to the appliance's. Test in Task 1 (`test_a_key_of_another_feature_is_accepted`).
5. A device key ending in a namespace (`greenhouse_switch`) next to a device whose switch key starts with it (`greenhouse` + `switch_sprinkler`) — a person expects a configuration error naming both, not one entity silently missing. Test in Task 1 (`test_two_devices_giving_one_entity_id_are_refused`).

---

### Task 1: A namespace per feature

**Files:**
- Modify: `custom_components/pururu/feature.py` (new `qualified()`, `Device`, `Feature`)
- Modify: `custom_components/pururu/entity.py` (`PururuEntity._identify`)
- Modify: `custom_components/pururu/__init__.py` (`_device`, `_entity_ids_distinct`, `async_setup_entry`, `_build`, `_creatable`)
- Modify: `custom_components/pururu/const.py` (comment on `ENTITY_PREFIX`)
- Modify: `custom_components/pururu/features/appliance/__init__.py`, `features/phases.py`, `features/switches.py` (`namespace=`)
- Modify: `custom_components/pururu/translations/en.json`, `translations/pt-BR.json`, `icons.json` (appliance keys renamed)
- Test: `tests/test_features.py`, `tests/test_init.py`, `tests/test_switches.py`, `tests/test_appliance.py`, `tests/test_phases.py`

**Interfaces:**
- Produces:
  - `feature.qualified(namespace: str, entity_key: str) -> str`: `namespace` when `entity_key == namespace`, else `f"{namespace}_{entity_key}"`.
  - `Device(key: str, name: str, namespace: str)` (all keyword, all required); `Device.qualified(entity_key: str) -> str`; `Device.object_id(entity_key)` is `f"pururu_{key}_{qualified(entity_key)}"`; `entity_id` and `current_entity_id` unchanged in signature.
  - `Feature.namespace: str`, required keyword field.
  - `PururuEntity._identify(...)`: without `name`, `_attr_translation_key = device.qualified(entity_key)`.
  - `_build(hass: HomeAssistant, key: str, config: dict[str, Any]) -> list[tuple[PururuEntity, set[str]]]`: the set holds **unique IDs** (object IDs) the entity follows.
  - `_creatable(hass: HomeAssistant, registry: er.EntityRegistry, built: list[tuple[PururuEntity, set[str]]]) -> list[PururuEntity]` (no `device` parameter).

- [ ] **Step 1: Update the contract test**

In `tests/test_features.py`, add the import next to the others:

```python
from homeassistant.helpers import config_validation as cv
```

Replace `test_no_entity_key_in_two_features` and `test_every_entity_key_is_named_and_has_an_icon` with:

```python
def test_namespaces_are_distinct_slugs(features: dict[str, Any]) -> None:
    """Every feature's entity keys are in its own namespace: no two features' entity IDs meet."""
    for name, feature in features.items():
        assert cv.slug(feature.namespace) == feature.namespace, name
        for other, theirs in features.items():
            if other != name:
                assert feature.namespace != theirs.namespace, f"{name} and {other}"
                assert not theirs.namespace.startswith(f"{feature.namespace}_"), f"{name} and {other}"


def test_every_entity_key_is_named_and_has_an_icon(features: dict[str, Any]) -> None:
    qualified = module("feature").qualified
    en, pt, icons = load("translations/en.json"), load("translations/pt-BR.json"), load("icons.json")
    for feature in features.values():
        for entity_key, platform in feature.entity_keys.items():
            key = qualified(feature.namespace, entity_key)
            for translations in (en, pt):
                assert translations["entity"][platform][key]["name"], key
            assert icons["entity"][platform][key]["default"].startswith("mdi:"), key


def test_every_translated_entity_key_is_created(features: dict[str, Any]) -> None:
    """A name or an icon under a key no feature creates is left over, as from before namespaces."""
    qualified = module("feature").qualified
    created = {(str(platform), qualified(feature.namespace, entity_key))
               for feature in features.values()
               for entity_key, platform in feature.entity_keys.items()}
    for name in ("translations/en.json", "icons.json"):
        listed = {(platform, key) for platform, keys in load(name)["entity"].items() for key in keys}
        assert listed <= created, f"{name}: {sorted(listed - created)}"
```

- [ ] **Step 2: Update `tests/test_init.py`**

Constants at the top become (the made-up features get namespaces `gauge`, `echo`, `tags`; `echo`'s only entity key is its namespace, so it is written once):

```python
LEVEL = "sensor.pururu_dummy_gizmo_gauge_level"
ACTIVE = "binary_sensor.pururu_dummy_gizmo_gauge_active"
ECHO = "sensor.pururu_dummy_gizmo_echo"
GAUGE = {"source": "sensor.dummy_source"}
GIZMO = {"name": "Gizmo", "gauge": GAUGE}
PANEL = {"name": "Panel", "gauge": GAUGE}
FIRST = "sensor.pururu_dummy_gizmo_tags_first"
SECOND = "sensor.pururu_dummy_gizmo_tags_second"
TAGS = {"first": {"name": "First"}, "second": {"name": "Second"}}
```

In the `dummy` fixture, add `namespace=` to each made-up `Feature`, right after `schema=`:

```python
        "gauge": feature.Feature(
            schema=vol.Schema({vol.Required("source"): cv.entity_id}),
            namespace="gauge",
            ...
        "echo": feature.Feature(
            schema=vol.Schema({vol.Required("activity_from"): cv.slug}),
            namespace="echo",
            ...
        "tags": feature.Feature(
            schema=vol.All(vol.Schema({cv.slug: vol.Schema({vol.Required("name"): cv.string})}),
                           vol.Length(min=1)),
            namespace="tags",
            ...
```

In `test_device_holds_what_its_features_create`, the unique ID and translation key become:

```python
    assert entry.unique_id == "pururu_dummy_gizmo_gauge_level"
    assert entry.translation_key == "gauge_level"
```

In `test_invalid_device_is_refused`, delete the two parameters with ids `configured key of another feature` and `configured key of another feature on another platform`.

In `test_a_configured_feature_creates_an_entity_per_key`:

```python
    assert entry.unique_id == "pururu_dummy_gizmo_tags_first"
```

Replace `test_an_entity_key_used_twice_names_both_features` with:

```python
async def test_a_configured_key_may_be_another_features_entity_key(ha: HomeAssistant) -> None:
    """Each feature has its own namespace: tags' level is not gauge's."""
    assert await setup(ha, {"dummy_gizmo": {**GIZMO, "tags": {"level": {"name": "Level"},
                                                               "active": {"name": "Active"}}}})
    assert held(ha, "dummy_gizmo") == {LEVEL, ACTIVE, "sensor.pururu_dummy_gizmo_tags_level",
                                       "sensor.pururu_dummy_gizmo_tags_active"}
```

Every `suggested_object_id="pururu_dummy_gizmo_level"` becomes `suggested_object_id="pururu_dummy_gizmo_gauge_level"`, and every `suggested_object_id="pururu_dummy_gizmo_active"` becomes `suggested_object_id="pururu_dummy_gizmo_gauge_active"` (in `test_a_device_with_nothing_created_has_no_area_to_go_to`, `test_id_of_another_integration_is_an_error_not_a_suffix`, `test_a_renamed_entity_is_still_ours`, `test_what_follows_an_entity_not_created_is_not_created_either`).

In `test_reload_that_drops_a_device_removes_it`:

```python
    assert er.async_get(ha).async_get("sensor.pururu_dummy_panel_gauge_level") is None
```

In `test_reload_sets_up_a_failed_entry_again`, the replacement `Feature` keeps the namespace:

```python
    features["gauge"] = feature.Feature(
        schema=original.schema, namespace=original.namespace, entity_keys=original.entity_keys,
        build=flaky_build, example=original.example, provides=original.provides,
    )
```

Add, after `test_a_device_no_longer_configured_goes_at_set_up`:

```python
async def test_entities_from_before_namespaces_go_at_set_up(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """0.1.4's IDs had no namespace: those entities are stale, and the namespaced ones replace them."""
    entry = MockConfigEntry(domain=DOMAIN, title="Pururu")
    entry.add_to_hass(ha)
    old = er.async_get(ha).async_get_or_create(
        "sensor", DOMAIN, "pururu_dummy_gizmo_level", config_entry=entry,
        suggested_object_id="pururu_dummy_gizmo_level")
    assert await setup(ha, {"dummy_gizmo": GIZMO})
    assert er.async_get(ha).async_get(old.entity_id) is None
    assert held(ha, "dummy_gizmo") == {LEVEL, ACTIVE}
    assert not [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
```

- [ ] **Step 3: Update `tests/test_switches.py`**

Constants:

```python
SPRINKLER = "switch.pururu_greenhouse_switch_sprinkler"
HEATER = "switch.pururu_greenhouse_switch_heater"
```

Replace `test_a_key_of_another_feature_is_refused` with:

```python
@pytest.mark.parametrize("entity_key", ["power", "running", "runtime_month"])
async def test_a_key_of_another_feature_is_accepted(ha: HomeAssistant, entity_key: str) -> None:
    """The switch is in the switch namespace, the appliance's entities in theirs."""
    await fake(ha, REAL_SPRINKLER, "on")
    switches = {entity_key: {"entity": REAL_SPRINKLER, "name": "Irrigador"}}
    assert await setup(ha, {KEY: {"name": "Estufa", "appliance": APPLIANCE,
                                  "switches": switches}})
    assert state(ha, f"switch.pururu_greenhouse_switch_{entity_key}") == "on"
    assert "binary_sensor.pururu_greenhouse_appliance_running" in held(ha, KEY)
```

Replace `test_two_devices_giving_one_entity_id_are_refused` with:

```python
@pytest.mark.parametrize(("entity_key", "other"), [
    pytest.param("switch_sprinkler", {"switches": {"sprinkler": SWITCHES["sprinkler"]}}, id="the same platform"),
    pytest.param("appliance_power", {"appliance": APPLIANCE}, id="another platform"),
])
async def test_two_devices_giving_one_entity_id_are_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, entity_key: str,
        other: dict[str, Any]) -> None:
    """greenhouse + switch_sprinkler and greenhouse_switch + sprinkler are both pururu_greenhouse_switch_switch_sprinkler."""
    assert not await setup(ha, {
        KEY: {"name": "Estufa", "switches": {entity_key: SWITCHES["sprinkler"]}},
        "greenhouse_switch": {"name": "Irrigador", **other},
    })
    assert (f"device greenhouse_switch: pururu_greenhouse_switch_{entity_key} is already an entity of device greenhouse"
            in caplog.text)
```

In `test_switches_next_to_another_feature`:

```python
    assert {SPRINKLER, "binary_sensor.pururu_greenhouse_appliance_running"} <= held(ha, KEY)
```

In `test_two_devices_can_stand_for_one_real_switch`:

```python
    assert state(ha, "switch.pururu_orchard_switch_sprinkler") == "on"
```

In `test_names_come_from_the_configuration`:

```python
    assert entry.unique_id == "pururu_greenhouse_switch_sprinkler"
```

In `test_an_id_already_taken_is_an_error`: `suggested_object_id="pururu_greenhouse_switch_sprinkler"`.

Replace `test_reload_that_moves_an_entity_key_to_a_switch_removes_the_old_entity` with:

```python
async def test_reload_that_swaps_the_appliance_for_a_switch_removes_its_entities(
        ha: HomeAssistant) -> None:
    """A switch keyed like one of the appliance's entities is a new entity; the appliance's go."""
    assert await setup(ha, {KEY: {"name": "Estufa", "appliance": APPLIANCE}})
    assert er.async_get(ha).async_get("sensor.pururu_greenhouse_appliance_power") is not None
    await reload(ha, {KEY: {"name": "Estufa", "switches": {"power": SWITCHES["sprinkler"]}}})
    assert er.async_get(ha).async_get("sensor.pururu_greenhouse_appliance_power") is None
    assert held(ha, KEY) == {"switch.pururu_greenhouse_switch_power"}
```

- [ ] **Step 4: Update `tests/test_appliance.py` and `tests/test_phases.py`**

`tests/test_appliance.py`:

```python
RUNNING = "binary_sensor.pururu_dummy_washer_appliance_running"
```

```python
def sensor(entity_key: str) -> str:
    return f"sensor.pururu_{KEY}_appliance_{entity_key}"
```

and the three literal IDs of the second device become `sensor.pururu_dummy_other_appliance_cycles_total`, `sensor.pururu_dummy_other_appliance_last_cycle_end` and `sensor.pururu_dummy_other_appliance_cycles_today`.

`tests/test_phases.py`:

```python
RUNNING = "binary_sensor.pururu_dummy_washer_appliance_running"
PHASE = "sensor.pururu_dummy_washer_phase"
```

and in the taken-ID test: `suggested_object_id="pururu_dummy_washer_appliance_running"`, `sensor.pururu_dummy_washer_appliance_runtime_total`, `sensor.pururu_dummy_washer_appliance_power`.

Then check no old-format ID is left in the tests:

Run: `grep -nE "pururu_(dummy_washer|dummy_other|greenhouse|orchard|dummy_gizmo|dummy_panel)_(power|energy_total|running|last_cycle|cycles_|runtime_|sprinkler|heater|level|active|first|second)" tests/*.py`
Expected: no output.

- [ ] **Step 5: Run the tests to see them fail**

Run: `uv run pytest tests/test_features.py tests/test_init.py -n 0 -q`
Expected: FAIL (`Feature` has no `namespace`: `TypeError: Feature.__init__() got an unexpected keyword argument 'namespace'`, and `module 'custom_components.pururu.feature' has no attribute 'qualified'`).

- [ ] **Step 6: `feature.py`**

Add, after `finite_float`:

```python
def qualified(namespace: str, entity_key: str) -> str:
    """`entity_key` in `namespace`: the end of its entity ID, and its translation key.

    An entity key that is its namespace isn't repeated: phases' `phase`.
    """
    return namespace if entity_key == namespace else f"{namespace}_{entity_key}"
```

`Device` becomes:

```python
@dataclass(frozen=True, kw_only=True)
class Device:
    """A configured device as one of its features sees it: key, display name, that feature's namespace."""

    key: str
    name: str
    # The feature's namespace: every entity key it names is in it
    namespace: str

    @property
    def info(self) -> DeviceInfo:
        """The device every entity of this device belongs to, whatever its feature."""
        return DeviceInfo(identifiers={(DOMAIN, self.key)}, name=self.name)

    def qualified(self, entity_key: str) -> str:
        """`entity_key` in this feature's namespace."""
        return qualified(self.namespace, entity_key)

    def object_id(self, entity_key: str) -> str:
        """The entity ID of `entity_key` without its platform, which is also its unique ID."""
        return f"{ENTITY_PREFIX}_{self.key}_{self.qualified(entity_key)}"
```

(`entity_id` and `current_entity_id` stay as they are: they go through `object_id`.)

In `Feature`, add after `example`:

```python
    # Every entity key it creates is in it, so no two features' entity IDs meet
    namespace: str
```

- [ ] **Step 7: `entity.py`**

In `PururuEntity._identify`, the docstring's second paragraph and the translation key become:

```python
        """Take `device`'s entity ID, unique ID and device for `entity_key`, and a name.

        The name is `name` when given (an entity key from the configuration has
        no translation), else the translation of the key in its namespace.
        """
        self.entity_id = device.entity_id(platform, entity_key)
        self._attr_unique_id = device.object_id(entity_key)
        self._attr_device_info = device.info
        if name is None:
            self._attr_translation_key = device.qualified(entity_key)
        else:
            self._attr_name = name
```

- [ ] **Step 8: `__init__.py`**

`_device`: the docstring becomes `"""A device: a name, maybe an area, at least one feature, every <capability>_from resolved."""`, and the block from `# Unique IDs leave the platform out: two alike entity keys would share one` to the end of its `for` loop is deleted (`return device` stays).

`_entity_ids_distinct` becomes:

```python
def _entity_ids_distinct(config: dict[str, Any]) -> dict[str, Any]:
    """Refuse two devices whose entities would share an ID.

    Device `greenhouse` with the switch `switch_sprinkler` and device `greenhouse_switch` with
    the switch `sprinkler` would both have pururu_greenhouse_switch_switch_sprinkler.
    """
    owners: dict[str, str] = {}  # object ID -> the device that has it
    for key, device in config[CONF_DEVICES].items():
        for name, entity_key in _entity_keys(device):
            identity = Device(
                key=key, name=device[CONF_NAME], namespace=FEATURES[name].namespace
            )
            object_id = identity.object_id(entity_key)
            if object_id in owners:
                raise vol.Invalid(
                    f"device {key}: {object_id} is already an entity of device "
                    f"{owners[object_id]}"
                )
            owners[object_id] = key
    return config
```

In `async_setup_entry`, the device loop becomes:

```python
    for key, config in devices.items():
        for entity in _creatable(hass, registry, _build(hass, key, config)):
            built[Platform(split_entity_id(entity.entity_id)[0])].append(entity)
```

`_build` becomes:

```python
def _build(
    hass: HomeAssistant, key: str, config: dict[str, Any]
) -> list[tuple[PururuEntity, set[str]]]:
    """Every entity of the device's features, with the unique IDs of the device's entities it follows.

    Each feature sees the device in its own namespace; what it takes through
    <capability>_from is in the providing feature's.
    """
    built: list[tuple[PururuEntity, set[str]]] = []
    for name, feature in FEATURES.items():
        if name not in config:
            continue
        device = Device(key=key, name=config[CONF_NAME], namespace=feature.namespace)
        inputs: dict[str, str] = {}
        required: set[str] = set()
        for capability in feature.requires:
            source = FEATURES[config[name][f"{capability}_from"]]
            provider = Device(
                key=key, name=config[CONF_NAME], namespace=source.namespace
            )
            entity_key = source.provides[capability]
            inputs[capability] = provider.current_entity_id(
                hass, source.entity_keys[entity_key], entity_key
            )
            required.add(provider.object_id(entity_key))
        built.extend(
            (entity, {*map(device.object_id, entity.sources), *required})
            for entity in feature.build(hass, device, config[name], inputs)
        )
    return built
```

`_creatable` loses its `device` parameter and takes the unique IDs as they come:

```python
def _creatable(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    built: list[tuple[PururuEntity, set[str]]],
) -> list[PururuEntity]:
    """The entities whose ID is free and whose sources are created too; the rest logged."""
    missing: dict[str, str] = {}  # unique ID -> entity ID, of what isn't created
    kept: list[tuple[PururuEntity, set[str]]] = []
    for entity, sources in built:
        if (holder := _holder(hass, registry, entity)) is None:
            kept.append((entity, sources))
            continue
```

(the rest of `_creatable` is unchanged).

- [ ] **Step 9: `const.py` and the features**

`const.py`: the comment above `ENTITY_PREFIX` becomes `# Every entity ID is <platform>.pururu_<device key>_<namespace>_<entity key>`.

`features/appliance/__init__.py`, in `APPLIANCE = Feature(`: add `namespace="appliance",` after `example=...`.
`features/phases.py`, in `PHASES = Feature(`: add `namespace="phase",` after `example=...`.
`features/switches.py`, in `SWITCHES = Feature(`: add `namespace="switch",` after `example=...`.

- [ ] **Step 10: Rename the translation and icon keys**

Each of appliance's 17 entity keys appears exactly once as a key in each file, so a text rename keeps every file's layout (`icons.json` has one-line entries, which `json.dumps` would reformat). Run:

```bash
uv run python - <<'EOF'
import json
from pathlib import Path

KEYS = ["power", "energy_total", "running", "last_cycle_start", "last_cycle_end",
        "last_cycle_duration", "last_cycle_energy", "cycles_total", "runtime_total",
        "runtime_today", "runtime_week", "runtime_month", "runtime_year",
        "cycles_today", "cycles_week", "cycles_month", "cycles_year"]
root = Path("custom_components/pururu")
for name in ("translations/en.json", "translations/pt-BR.json", "icons.json"):
    path = root / name
    text = path.read_text()
    for key in KEYS:
        assert text.count(f'"{key}": {{') == 1, (name, key)
        text = text.replace(f'"{key}": {{', f'"appliance_{key}": {{')
    json.loads(text)  # still valid JSON
    path.write_text(text)
EOF
git diff --stat custom_components/pururu/translations custom_components/pururu/icons.json
```

Expected: the three files changed, 17 lines each; `phase` untouched. `KEYS` is `ENTITY_KEYS` of `features/appliance/__init__.py`; the contract tests of Step 1 fail if one is missed or left over.

- [ ] **Step 11: Run the tests**

Run: `uv run pytest tests/test_features.py tests/test_init.py tests/test_switches.py tests/test_appliance.py tests/test_phases.py -n 0 -q`
Expected: PASS.

Run: `uv run pytest`
Expected: PASS, including `tests/test_code.py` (ruff, ruff format, mypy, hassfest).

- [ ] **Step 12: Commit**

```bash
git add custom_components/pururu tests
git commit -m "pururu: a namespace per feature in entity IDs

Every entity is <platform>.pururu_<device>_<namespace>_<entity key>, so
two features never give two entities one ID. appliance's and switches'
entity IDs change.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The Guide docs and the README

**Files:**
- Modify: `docs/index.mdx`, `docs/getting-started/first-device.mdx`, `docs/concepts/entity-ids.mdx`, `docs/concepts/devices-and-features.mdx`, `docs/features/appliance.mdx`, `docs/features/switches.mdx`, `docs/reference/configuration.mdx`, `docs/reference/troubleshooting.mdx`, `docs/develop/testing.mdx`, `README.md`

**Interfaces:**
- Consumes: the ID format and the error messages of Task 1 (`device greenhouse_switch: pururu_greenhouse_switch_switch_sprinkler is already an entity of device greenhouse`).

- [ ] **Step 1: Rewrite appliance's IDs everywhere**

Run:

```bash
uv run python - <<'EOF'
import re
from pathlib import Path

KEYS = (r"power|energy_total|running|last_cycle_(?:start|end|duration|energy)"
        r"|cycles_(?:total|today|week|month|year|<period>)"
        r"|runtime_(?:total|today|week|month|year|<period>)")
PATTERN = re.compile(rf"(pururu_(?:clothes_washer|dishwasher|<key>)_)({KEYS})(?![a-z0-9_])")
FILES = ["docs/index.mdx", "docs/getting-started/first-device.mdx", "docs/concepts/entity-ids.mdx",
         "docs/concepts/devices-and-features.mdx", "docs/features/appliance.mdx",
         "docs/reference/troubleshooting.mdx", "docs/develop/testing.mdx", "README.md"]
for name in FILES:
    path = Path(name)
    text, count = PATTERN.subn(lambda m: f"{m[1]}appliance_{m[2]}", path.read_text())
    path.write_text(text)
    print(name, count)
EOF
```

Expected: a non-zero count for each file. Then:

Run: `grep -rnE "pururu_(clothes_washer|dishwasher|<key>)_(power|energy_total|running|last_cycle|cycles_|runtime_)" docs README.md --include=*.mdx --include=README.md`
Expected: no output.

- [ ] **Step 2: `concepts/entity-ids.mdx`, the pattern**

Replace the section from `## The pattern` down to (not including) `## Names` with:

````mdx
## The pattern

Every entity pururu creates has the ID

```
<platform>.pururu_<device key>_<namespace>_<entity key>
```

- **platform**: `sensor`, `binary_sensor` or `switch`.
- **device key**: the device's key under `devices:`.
- **namespace**: the feature that creates the entity. Each feature has its own, so two features never give two entities one ID.
- **entity key**: which of the feature's entities it is. Each feature's page lists its entity keys. An entity key counted per period ends with that period, as in `runtime_month`.

| Feature | Namespace | Example |
|---|---|---|
| [`appliance`](/features/appliance) | `appliance` | `binary_sensor.pururu_clothes_washer_appliance_running` |
| [`phases`](/features/phases) | `phase` | `sensor.pururu_clothes_washer_phase` |
| [`switches`](/features/switches) | `switch` | `switch.pururu_greenhouse_switch_sprinkler` |

An entity key that is its feature's namespace isn't written twice: the only entity of `phases`, `phase`, is `sensor.pururu_clothes_washer_phase`.

So the `running` entity of the device `clothes_washer` is always `binary_sensor.pururu_clothes_washer_appliance_running`. You can write automations and dashboards against it before the device even exists.

The entity's **unique ID** is the same text without the platform: `pururu_clothes_washer_appliance_running`. That's what Home Assistant uses to remember the entity's settings and history across restarts.

<Info>
  Before pururu 0.1.5, IDs had no namespace (`binary_sensor.pururu_clothes_washer_running`, `switch.pururu_greenhouse_sprinkler`). Updating removes those entities, with their history, and creates the new ones. Update the automations and dashboards that name them.
</Info>
````

- [ ] **Step 3: `features/switches.mdx`**

- `This creates `switch.pururu_greenhouse_sprinkler`, shown as **Estufa Irrigador**, and `switch.pururu_greenhouse_heater`, shown as **Estufa Aquecedor**.` → `This creates `switch.pururu_greenhouse_switch_sprinkler`, shown as **Estufa Irrigador**, and `switch.pururu_greenhouse_switch_heater`, shown as **Estufa Aquecedor**.`
- `The key is a slug, and it becomes the end of the entity ID: `sprinkler` → `switch.pururu_greenhouse_sprinkler`.` → `The key is a slug, and it ends the entity ID, after the namespace `switch`: `sprinkler` → `switch.pururu_greenhouse_switch_sprinkler`.`
- Replace the paragraph starting `A switch's key can't be an entity key of another feature of the same device.` with: `A switch's key can be one another feature uses, such as `power` next to `appliance`: each feature has its own [namespace](/concepts/entity-ids#the-pattern), so `switch.pururu_greenhouse_switch_power` and `sensor.pururu_greenhouse_appliance_power` are two entities.`
- The table header `| The real switch | `switch.pururu_<key>_<entity key>` |` → `| The real switch | `switch.pururu_<key>_switch_<entity key>` |`.

- [ ] **Step 4: `reference/configuration.mdx`**

Delete the rule starting `- In a device, every entity key is different:`. Replace the rule starting `- No two devices give an entity the same ID.` with:

```mdx
- No two devices give an entity the same ID. Device `greenhouse` with the switch `switch_sprinkler` and device `greenhouse_switch` with the switch `sprinkler` would both have `switch.pururu_greenhouse_switch_switch_sprinkler`, so that's a configuration error. It counts every entity key a feature can create, even one its settings don't: device `greenhouse` with the switch `appliance_energy_total` is refused next to a device `greenhouse_switch` with `appliance`, even without `energy:`, so turning a setting on later never breaks the configuration.
```

- [ ] **Step 5: `reference/troubleshooting.mdx`**

- Delete the line `- A switch whose key is already an entity key of another feature of the device: `switches: power is already an entity key of appliance`.`
- The next line becomes: `- Two devices that would give an entity the same ID: `device greenhouse_switch: pururu_greenhouse_switch_switch_sprinkler is already an entity of device greenhouse`. Rename a device key or a switch key.`
- In the code block under `### `… is a pururu switch: name the real one; not creating …``: `switch.aquecedor is a pururu switch: name the real one; not creating switch.pururu_greenhouse_switch_sprinkler`.

- [ ] **Step 6: Check nothing else is left**

Run: `grep -rnE "switch\.pururu_(greenhouse|orchard)_(sprinkler|heater|power)|pururu_clothes_washer_running|already an entity key of|pururu_greenhouse_sprinkler_heater|greenhouse_energy" docs README.md --include=*.mdx --include=README.md`
Expected: one line only, the `<Info>` note in `docs/concepts/entity-ids.mdx`, which names the IDs from before 0.1.5 on purpose (the `docs/superpowers` folder is `.md`, not matched).

Run: `npx --yes @docs.page/cli check`
Expected: no broken links.

- [ ] **Step 7: Commit**

```bash
git add docs README.md
git commit -m "Docs: entity IDs with their feature's namespace

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The Develop docs, CLAUDE.md and the release

**Files:**
- Modify: `docs/develop/architecture.mdx`, `docs/develop/writing-a-feature.mdx`, `CLAUDE.md`, `custom_components/pururu/manifest.json`

**Interfaces:**
- Consumes: `Feature.namespace`, `Device.qualified`, `feature.qualified`, the contract tests `test_namespaces_are_distinct_slugs` and `test_every_translated_entity_key_is_created` (Task 1).

- [ ] **Step 1: `develop/architecture.mdx`**

- In the `Feature` table, after the `example` row, add: `| `namespace` | Where its entity keys live in an entity ID: `appliance`, `phase`, `switch` |`
- Replace the paragraph starting `It also checks that every entity key of the device is different:` with:

```mdx
It doesn't compare entity keys between features. Each feature has its own `namespace`, and the entity keys it creates are in it (`appliance_power`, `switch_power`), so they can't meet. The contract test checks that namespaces are distinct slugs and that none is another's followed by `_`. Between devices, `_entity_ids_distinct` still refuses two that would give an entity one ID: `greenhouse` with the switch `switch_sprinkler` and `greenhouse_switch` with the switch `sprinkler`.
```

- Replace the paragraph starting `When a feature requires a capability, `_build` looks up` with:

```mdx
When a feature requires a capability, `_build` looks up the providing entity key's **current** entity ID with a `Device` in the providing feature's namespace (`Device.current_entity_id`, which follows renames), and passes it to `build()` in `inputs`. The provider's unique ID is also added to the entity's sources, so if the provider isn't created, neither is this entity.
```

- Under `## Entity IDs are the identity`, replace the first bullet with:

```mdx
- Every entity is `<platform>.pururu_<device key>_<namespace>_<entity key>`, and an entity key equal to its namespace is written once (`phase`). Its unique ID is the part after the platform: `Device.object_id(entity_key)`. `_build` gives each feature's `build()` a `Device` in that feature's namespace, so a feature only writes its own entity keys (`"running"`).
```

- In the `_identify` bullet, replace `Without a `name`, the translation key is the entity key and the name comes from `translations/*.json` → `entity.<platform>.<entity key>.name`.` with `Without a `name`, the translation key is the entity key in its namespace (`Device.qualified`, as `appliance_running`) and the name comes from `translations/*.json` → `entity.<platform>.<namespace>_<entity key>.name`.`

- [ ] **Step 2: `develop/writing-a-feature.mdx`**

- In the example module, `Openings.__init__` becomes:

```python
    def __init__(self, device: Device, sensor: str) -> None:
        """Count `sensor`'s openings as the device's total."""
        self._identify(device, Platform.SENSOR, "total")
```

- The `OPENINGS` block becomes:

```python
OPENINGS = Feature(
    schema=SCHEMA,
    entity_keys={"total": Platform.SENSOR},
    build=build,
    example={"sensor": "binary_sensor.dummy_contact"},
    namespace="openings",
)
```

- In "The pieces", the `entity_keys` bullet loses its last sentence (`An entity key must not be used by any other feature.`), and after the `example` bullet add:

```mdx
- **`namespace`** is where the feature's entity keys live in an entity ID: `total` becomes `sensor.pururu_front_door_openings_total`. It's a slug no other feature uses, and not another feature's namespace followed by `_`. An entity key equal to the namespace is written once, as `phases`' `phase`. `build()` gets a `device` already in this namespace, so the feature only ever writes its own entity keys.
```

- In `## 3. Names and icons`, the first sentence becomes: `For every entity key, add a name to **both** `translations/en.json` and `translations/pt-BR.json`, and an icon to `icons.json`, under the key in its namespace, `<namespace>_<entity key>`:` (the JSON examples keep `openings_total`, which is now that qualified key).
- In the paragraph `**On an entity of the same device:**`, `set `sources` on the entity to the entity keys it reads` → `set `sources` on the entity to the entity keys of its own feature it reads`.
- In `## 5. Entity keys from the configuration`, delete the bullet `- The device schema refuses a key that is an entity key of another feature of the device.`
- In the contract test table, replace the `test_no_entity_key_in_two_features` row with two rows:

```mdx
| `test_namespaces_are_distinct_slugs` | Every namespace is a slug, no two are equal, and none is another's followed by `_` |
| `test_every_translated_entity_key_is_created` | Every name and icon is under a key some feature creates |
```

and the `test_every_entity_key_is_named_and_has_an_icon` row becomes: `| `test_every_entity_key_is_named_and_has_an_icon` | A name in both languages and an `mdi:` icon for every entity key, under its key in its namespace |`

- [ ] **Step 3: `CLAUDE.md`**

- `A `Feature` has a `schema`, the `entity_keys` it can create` → `A `Feature` has a `schema`, a `namespace`, the `entity_keys` it can create`.
- Delete the sentence `` `_device` refuses two alike entity keys in one device: unique IDs leave the platform out.`` from the `configured` bullet.
- The bullet `Every entity is `<platform>.pururu_<device key>_<entity key>`, and its unique ID is the part after the platform (`Device.object_id`).` becomes:

```markdown
  - Every entity is `<platform>.pururu_<device key>_<namespace>_<entity key>` (an entity key equal to its feature's namespace is written once: `sensor.pururu_washer_phase`), and its unique ID is the part after the platform (`Device.object_id`). `_build` hands each feature a `Device` in its namespace, so features write local entity keys; the translation key is the key in its namespace (`appliance_running`).
```

- [ ] **Step 4: The version**

In `custom_components/pururu/manifest.json`, `"version": "0.1.4"` → `"version": "0.1.5"`.

Run: `python3 release.py check`
Expected: passes (0.1.5 is semver and not below the latest release).

- [ ] **Step 5: Verify everything**

Run: `uv run pytest`
Expected: PASS.

Run: `npx --yes @docs.page/cli check`
Expected: no broken links.

Run: `grep -rnE "entity key of another feature|test_no_entity_key_in_two_features|two alike entity keys" docs CLAUDE.md README.md custom_components --include=*.mdx --include=*.md --include=*.py | grep -v docs/superpowers`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add docs CLAUDE.md custom_components/pururu/manifest.json
git commit -m "Docs and release: namespaces for contributors (0.1.5)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

The PR's title names the change of IDs, as `pururu: a namespace per feature in entity IDs (0.1.5)`, and its description says that the old entities of `appliance` and `switches` are removed along with their history: the release notes are generated from it.
