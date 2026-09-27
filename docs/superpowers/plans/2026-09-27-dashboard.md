# Pururu dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** pururu shows a read-only dashboard at `/pururu`. It has a total for each of dashboards, floors, areas and devices it manages, and a table (ID | Name | Type) of all of them.

**Architecture:**
- A new module, `custom_components/pururu/dashboard.py`, is the only code that touches lovelace's private API.
- It stores a `LovelaceConfig` subclass in `hass.data[LOVELACE_DATA].dashboards["pururu"]` and registers a `lovelace` built-in panel in `yaml` mode.
- The config is built at every fetch from `entry.data` and the registries, using native markdown cards.
- A registry change fires `lovelace_updated`, so an open page refetches.
- `async_setup_entry` calls it last. The panel and the dashboard go away through `entry.async_on_unload`.

**Tech Stack:** Home Assistant 2026.9.3 (lovelace, frontend, floor/area/device registries, translations), pytest with `pytest-homeassistant-custom-component` (`hass_ws_client`).

**Spec:** `docs/superpowers/specs/2026-09-27-dashboard-design.md`

## Global Constraints

- **Location and access:** URL path `pururu`, sidebar title `Pururu`, icon `mdi:home-group`, `require_admin=True`, panel config `{"mode": "yaml"}`.
- **Columns:** the table columns are ID | Name | Type. Rows go dashboard, floors, areas, devices, each type sorted by ID.
- **What is managed:**
  - the dashboard itself, `(pururu, Pururu)`;
  - floors and areas: the IDs in `entry.data["floors"]` / `["areas"]` that exist in their registry, with the registry's name;
  - devices: the entry's devices in the device registry, ID = the key of their `(pururu, <key>)` identifier, name = `name_by_user` or `name`.
- **Labels:** from `common` in `translations/<lang>.json`, in `hass.config.language`, with English as the fallback. pt-BR values: Dashboards / Andares / Áreas / Dispositivos; ID / Nome / Tipo; Dashboard / Andar / Área / Dispositivo.
- **Escaping:** each ID and name is escaped for the markdown card. `&<>|{}[]\`*_~` become `&#N;` entities, and a newline becomes a space.
- **Never fatal:** nothing in the dashboard fails the entry's setup. Every problem is a logged error, the same policy as taken entity IDs.
- **Manifest:** `dependencies` gains `lovelace`, `after_dependencies: ["frontend"]` is added, and `version` becomes `0.1.3`. `frontend` must NOT go in `dependencies`, because `hass_frontend` is not installed in the test venv.
- **Checks:** lint and type checks run on `custom_components/pururu` only, with core's ruff/mypy (strict) settings. Every function has a docstring, as in the rest of the package.
- **Commands:** run them from the worktree root with `uv run …`. Never leave the shell's cwd inside `.venv/.../homeassistant/helpers/`.
- **Commit messages:** end every one with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A page left open while pururu reloads.** The panel is removed and registered again. The page should come back showing the new content, not stay on a "not found" screen. This is manual: see Task 3, Step 7.
2. **A rename in the UI while the page is open.** The page should refresh by itself. The double `lovelace_updated` works around the frontend ignoring the event that follows each yaml-mode fetch. Manual: Task 3, Step 7. Task 2 tests that both events are fired.
3. **HA in a language pururu has no translation for (e.g. `de`).** The labels should be English, not a crash (`KeyError`). Task 1 tests it.
4. **A user trying to create a dashboard at `/pururu` from Settings.** HA should refuse it (the URL is taken), and pururu's dashboard should stay. Task 2 tests it.
5. **A device the user renamed in the UI.** The table should show the user's name, not the YAML one. Task 2 tests it.

---

## File Structure

| File | Responsibility |
|---|---|
| `custom_components/pururu/dashboard.py` (new) | Everything about the dashboard: what is managed, the Lovelace config, the `LovelaceConfig` subclass, registering and removing the panel, refreshing on registry changes. |
| `custom_components/pururu/__init__.py` | Calls `dashboard.async_setup(hass, entry)` at the end of `async_setup_entry`. |
| `custom_components/pururu/manifest.json` | `lovelace` dependency, `frontend` after-dependency, version. |
| `custom_components/pururu/translations/en.json`, `pt-BR.json` | The `common` labels. `tests/test_features.py::test_translation_files_match` already checks that both files have the same keys. |
| `custom_components/pururu/quality_scale.yaml` | The `dependency-transparency` comment names lovelace. |
| `tests/test_dashboard.py` (new) | The dashboard's tests, over the websocket. |
| `README.md`, `CLAUDE.md` | A Dashboard section, and an architecture bullet. |

---

### Task 1: The dashboard, registered, with its content

**Files:**
- Create: `custom_components/pururu/dashboard.py`
- Modify: `custom_components/pururu/__init__.py` (the `from . import places` import, and the end of `async_setup_entry`)
- Modify: `custom_components/pururu/manifest.json`
- Modify: `custom_components/pururu/translations/en.json`, `custom_components/pururu/translations/pt-BR.json`
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `CONF_FLOORS`, `CONF_AREAS`, `DOMAIN` from `const.py`. `entry.data` is `{"floors": [...], "areas": [...]}` (written by `places.async_sync` in `async_setup_entry`).
- Produces (in `dashboard.py`):
  - `URL_PATH: Final = "pururu"`, `TITLE: Final = "Pururu"`, `ICON: Final = "mdi:home-group"`, `KINDS: Final = ("dashboard", "floor", "area", "device")`
  - `escape(text: str) -> str`
  - `managed(hass: HomeAssistant, entry: ConfigEntry[Any]) -> dict[str, list[tuple[str, str]]]`
  - `build(items: Mapping[str, list[tuple[str, str]]], labels: Mapping[str, str]) -> dict[str, Any]`
  - `class PururuDashboard(LovelaceConfig)` with `__init__(hass, entry)`
  - `async_setup(hass: HomeAssistant, entry: ConfigEntry[Any]) -> None` (a `@callback`). Task 2 rewrites its body.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dashboard.py`:

```python
"""pururu's dashboard: what the entry manages, read-only, at /pururu."""

import html
from typing import Any

from homeassistant.components import frontend
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    floor_registry as fr,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from helpers import DOMAIN, module, reload, setup

URL = "pururu"
FLOORS = {"terreo": {"name": "Térreo"}, "superior": {"name": "Superior"}}
AREAS = {"cozinha": {"name": "Cozinha", "floor": "terreo"}, "quintal": {"name": "Quintal"}}


@pytest.fixture
def appliance(ha: HomeAssistant) -> dict[str, Any]:
    """A valid `appliance:` block, for devices."""
    return module("features").FEATURES["appliance"].example


def devices(appliance: dict[str, Any], **names: str) -> dict[str, Any]:
    """A `devices:` block: key -> name, each an appliance."""
    return {key: {"name": name, "appliance": appliance} for key, name in names.items()}


async def fetch(hass: HomeAssistant, ws: WebSocketGenerator) -> dict[str, Any]:
    """The dashboard's config, as the frontend fetches it."""
    client = await ws(hass)
    await client.send_json_auto_id({"type": "lovelace/config", "url_path": URL})
    msg = await client.receive_json()
    assert msg["success"], msg
    result: dict[str, Any] = msg["result"]
    return result


def cards(config: dict[str, Any]) -> list[dict[str, Any]]:
    return config["views"][0]["sections"][0]["cards"]


def totals(config: dict[str, Any]) -> list[str]:
    """The content of the four total cards."""
    return [card["content"] for card in cards(config)[:4]]


def table(config: dict[str, Any]) -> list[list[str]]:
    """The table's header, then its rows, as shown (entities decoded)."""
    lines = cards(config)[4]["content"].splitlines()
    return [[html.unescape(cell) for cell in line.strip("| ").split(" | ")]
            for index, line in enumerate(lines) if index != 1]


async def test_totals_and_table_of_what_pururu_manages(
        ha: HomeAssistant, hass_ws_client: WebSocketGenerator, appliance: dict[str, Any]) -> None:
    assert await setup(ha, devices(appliance, washer="Washer", dryer="Dryer"),
                       floors=FLOORS, areas=AREAS)
    config = await fetch(ha, hass_ws_client)
    assert totals(config) == ["# 1\nDashboards", "# 2\nFloors", "# 2\nAreas", "# 2\nDevices"]
    assert table(config) == [
        ["ID", "Name", "Type"],
        ["pururu", "Pururu", "Dashboard"],
        ["superior", "Superior", "Floor"],
        ["terreo", "Térreo", "Floor"],
        ["cozinha", "Cozinha", "Area"],
        ["quintal", "Quintal", "Area"],
        ["dryer", "Dryer", "Device"],
        ["washer", "Washer", "Device"],
    ]


async def test_what_pururu_does_not_manage_is_not_listed(
        ha: HomeAssistant, hass_ws_client: WebSocketGenerator, appliance: dict[str, Any]) -> None:
    fr.async_get(ha).async_create("Sótão")
    ar.async_get(ha).async_create("Garagem")
    other = MockConfigEntry(domain="other")
    other.add_to_hass(ha)
    dr.async_get(ha).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("other", "tv")}, name="TV")
    assert await setup(ha, devices(appliance, washer="Washer"),
                       floors={"terreo": FLOORS["terreo"]}, areas={"quintal": AREAS["quintal"]})
    config = await fetch(ha, hass_ws_client)
    assert totals(config) == ["# 1\nDashboards", "# 1\nFloors", "# 1\nAreas", "# 1\nDevices"]
    assert [row[0] for row in table(config)[1:]] == ["pururu", "terreo", "quintal", "washer"]


async def test_a_reload_that_drops_items_drops_them_from_the_dashboard(
        ha: HomeAssistant, hass_ws_client: WebSocketGenerator, appliance: dict[str, Any]) -> None:
    assert await setup(ha, devices(appliance, washer="Washer", dryer="Dryer"),
                       floors=FLOORS, areas=AREAS)
    await reload(ha, devices(appliance, washer="Washer"),
                 floors={"terreo": FLOORS["terreo"]}, areas={"cozinha": AREAS["cozinha"]})
    config = await fetch(ha, hass_ws_client)
    assert totals(config) == ["# 1\nDashboards", "# 1\nFloors", "# 1\nAreas", "# 1\nDevices"]
    assert [row[0] for row in table(config)[1:]] == ["pururu", "terreo", "cozinha", "washer"]


async def test_a_read_only_lovelace_panel_for_admins(
        ha: HomeAssistant, hass_ws_client: WebSocketGenerator, appliance: dict[str, Any]) -> None:
    assert await setup(ha, devices(appliance, washer="Washer"))
    panel = ha.data[frontend.DATA_PANELS][URL]
    assert (panel.component_name, panel.config, panel.require_admin,
            panel.sidebar_title, panel.sidebar_icon) == (
        "lovelace", {"mode": "yaml"}, True, "Pururu", "mdi:home-group")
    client = await hass_ws_client(ha)
    await client.send_json_auto_id({"type": "lovelace/dashboards/list"})
    listed = (await client.receive_json())["result"]
    assert {"url_path": URL, "mode": "yaml", "title": "Pururu"}.items() <= next(
        d for d in listed if d["url_path"] == URL).items()
    await client.send_json_auto_id(
        {"type": "lovelace/config/save", "url_path": URL, "config": {"views": []}})
    assert not (await client.receive_json())["success"]


async def test_unloading_the_entry_takes_the_dashboard_away(
        ha: HomeAssistant, hass_ws_client: WebSocketGenerator, appliance: dict[str, Any]) -> None:
    assert await setup(ha, devices(appliance, washer="Washer"))
    [entry] = ha.config_entries.async_entries(DOMAIN)
    assert await ha.config_entries.async_unload(entry.entry_id)
    assert URL not in ha.data[frontend.DATA_PANELS]
    client = await hass_ws_client(ha)
    await client.send_json_auto_id({"type": "lovelace/config", "url_path": URL})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "config_not_found", msg


async def test_names_are_shown_as_written(
        ha: HomeAssistant, hass_ws_client: WebSocketGenerator, appliance: dict[str, Any]) -> None:
    """A name is neither markdown, HTML, a template, nor a table cell border."""
    name = "A | {{ 1 + 1 }} <b>*x*</b> & [y]"
    assert await setup(ha, devices(appliance, washer=name))
    config = await fetch(ha, hass_ws_client)
    raw = cards(config)[4]["content"].splitlines()[-1]
    for written in ("{{", "<b>", "*x*", "[y]", " A | "):
        assert written not in raw, raw
    assert table(config)[-1] == ["washer", name, "Device"]


async def test_labels_in_hass_language(
        ha: HomeAssistant, hass_ws_client: WebSocketGenerator, appliance: dict[str, Any]) -> None:
    assert await setup(ha, devices(appliance, washer="Washer"), floors=FLOORS, areas=AREAS)
    ha.config.language = "pt-BR"
    config = await fetch(ha, hass_ws_client)
    assert totals(config) == ["# 1\nDashboards", "# 2\nAndares", "# 2\nÁreas",
                              "# 1\nDispositivos"]
    assert table(config)[0] == ["ID", "Nome", "Tipo"]
    assert [row[2] for row in table(config)[1:]] == [
        "Dashboard", "Andar", "Andar", "Área", "Área", "Dispositivo"]


async def test_a_language_pururu_is_not_translated_in_falls_back_to_english(
        ha: HomeAssistant, hass_ws_client: WebSocketGenerator, appliance: dict[str, Any]) -> None:
    assert await setup(ha, devices(appliance, washer="Washer"))
    ha.config.language = "de"
    config = await fetch(ha, hass_ws_client)
    assert totals(config)[3] == "# 1\nDevices"
    assert table(config)[0] == ["ID", "Name", "Type"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_dashboard.py -n 0 -q`
Expected: every test FAILS. `lovelace/config` for `pururu` returns `config_not_found`, and `ha.data[frontend.DATA_PANELS]` has no `pururu` (`KeyError`).

- [ ] **Step 3: Add the translations**

In `custom_components/pururu/translations/en.json`, add a top-level `"common"` block. It goes after `"services"`, before `"entity"`:

```json
  "common": {
    "dashboards": "Dashboards",
    "floors": "Floors",
    "areas": "Areas",
    "devices": "Devices",
    "dashboard": "Dashboard",
    "floor": "Floor",
    "area": "Area",
    "device": "Device",
    "id": "ID",
    "name": "Name",
    "type": "Type"
  },
```

In `custom_components/pururu/translations/pt-BR.json`, add it at the same place:

```json
  "common": {
    "dashboards": "Dashboards",
    "floors": "Andares",
    "areas": "Áreas",
    "devices": "Dispositivos",
    "dashboard": "Dashboard",
    "floor": "Andar",
    "area": "Área",
    "device": "Dispositivo",
    "id": "ID",
    "name": "Nome",
    "type": "Tipo"
  },
```

- [ ] **Step 4: Update the manifest**

`custom_components/pururu/manifest.json`. hassfest wants `domain` and `name` first and the other keys sorted, and the lists sorted:

```json
{
  "domain": "pururu",
  "name": "Pururu",
  "after_dependencies": ["frontend"],
  "codeowners": [],
  "config_flow": true,
  "dependencies": ["group", "lovelace", "utility_meter"],
  "documentation": "https://github.com/thatsnotmynameio/pururu-ha",
  "iot_class": "calculated",
  "issue_tracker": "https://github.com/thatsnotmynameio/pururu-ha/issues",
  "single_config_entry": true,
  "version": "0.1.2"
}
```

(The version changes in Task 3.)

- [ ] **Step 5: Write `dashboard.py`**

Create `custom_components/pururu/dashboard.py`:

```python
"""pururu's dashboard: what the entry manages, read-only, at /pururu.

HA has no public API for an integration's dashboard. As lovelace does for a
YAML dashboard, a LovelaceConfig goes in lovelace's dashboards, and a
`lovelace` panel in `yaml` mode shows it: the UI offers no editing. Its config
is built at every fetch, from the entry and the registries, and never saved.
"""

from collections.abc import Mapping
import logging
from typing import Any, Final

from homeassistant.components import frontend
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_YAML
from homeassistant.components.lovelace.dashboard import LovelaceConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    floor_registry as fr,
)
from homeassistant.helpers.json import json_bytes, json_fragment
from homeassistant.helpers.translation import async_get_translations

from .const import CONF_AREAS, CONF_FLOORS, DOMAIN

_LOGGER = logging.getLogger(__name__)

URL_PATH: Final = DOMAIN
TITLE: Final = "Pururu"
ICON: Final = "mdi:home-group"
# The table's types, in its order. Each is a key of `common` in the
# translations, and so is its plural, the label of its total
KINDS: Final = ("dashboard", "floor", "area", "device")
# The markdown card renders markdown and HTML, and evaluates a template: in an
# ID or a name, these become entities, shown as written
_ESCAPES: Final = str.maketrans(
    {**{char: f"&#{ord(char)};" for char in "&<>|{}[]\\`*_~"}, "\n": " ", "\r": " "}
)


def escape(text: str) -> str:
    """`text` as markdown card content that shows it as written."""
    return text.translate(_ESCAPES)


def managed(
    hass: HomeAssistant, entry: ConfigEntry[Any]
) -> dict[str, list[tuple[str, str]]]:
    """For each of KINDS, the (ID, name) of what the entry manages, sorted by ID."""
    floors = fr.async_get(hass)
    areas = ar.async_get(hass)
    devices = dr.async_get(hass)
    return {
        "dashboard": [(URL_PATH, TITLE)],
        "floor": sorted(
            (floor.floor_id, floor.name)
            for floor_id in entry.data.get(CONF_FLOORS, [])
            if (floor := floors.async_get_floor(floor_id)) is not None
        ),
        "area": sorted(
            (area.id, area.name)
            for area_id in entry.data.get(CONF_AREAS, [])
            if (area := areas.async_get_area(area_id)) is not None
        ),
        "device": sorted(
            (key, device.name_by_user or device.name or key)
            for device in dr.async_entries_for_config_entry(devices, entry.entry_id)
            for domain, key in device.identifiers
            if domain == DOMAIN
        ),
    }


def build(
    items: Mapping[str, list[tuple[str, str]]], labels: Mapping[str, str]
) -> dict[str, Any]:
    """The dashboard's config: a total per kind, then the table of every item."""
    totals = [
        {
            "type": "markdown",
            "grid_options": {"columns": 3},
            "content": f"# {len(items[kind])}\n{labels[f'{kind}s']}",
        }
        for kind in KINDS
    ]
    rows = [
        f"| {escape(item_id)} | {escape(name)} | {labels[kind]} |"
        for kind in KINDS
        for item_id, name in items[kind]
    ]
    table = "\n".join(
        (
            f"| {labels['id']} | {labels['name']} | {labels['type']} |",
            "|---|---|---|",
            *rows,
        )
    )
    return {
        "title": TITLE,
        "views": [
            {
                "type": "sections",
                "path": URL_PATH,
                "title": TITLE,
                "sections": [
                    {
                        "type": "grid",
                        "column_span": 4,
                        "cards": [
                            *totals,
                            {
                                "type": "markdown",
                                "grid_options": {"columns": "full"},
                                "content": table,
                            },
                        ],
                    }
                ],
            }
        ],
    }


class PururuDashboard(LovelaceConfig):
    """The dashboard, built at every fetch; the UI can't save nor delete it."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry[Any]) -> None:
        """The dashboard of `entry`, as Settings → Dashboards lists it."""
        super().__init__(
            hass,
            URL_PATH,
            {
                "id": URL_PATH,
                "title": TITLE,
                "icon": ICON,
                "mode": MODE_YAML,
                "require_admin": True,
                "show_in_sidebar": True,
            },
        )
        self._entry = entry

    @property
    def mode(self) -> str:
        """Read-only, as a YAML dashboard."""
        return MODE_YAML

    async def async_get_info(self) -> dict[str, Any]:
        """No mode: lovelace's system health would report `yaml` because of pururu."""
        return {"views": 1}

    async def async_load(self, force: bool) -> dict[str, Any]:
        """The config, from what the entry manages now, in HA's language."""
        prefix = f"component.{DOMAIN}.common."
        translations = await async_get_translations(
            self.hass, self.hass.config.language, "common", {DOMAIN}
        )
        labels = {
            key.removeprefix(prefix): label
            for key, label in translations.items()
            if key.startswith(prefix)
        }
        return build(managed(self.hass, self._entry), labels)

    async def async_json(self, force: bool) -> json_fragment:
        """The config, as the websocket sends it."""
        return json_fragment(json_bytes(await self.async_load(force)))


@callback
def async_setup(hass: HomeAssistant, entry: ConfigEntry[Any]) -> None:
    """Show the entry's dashboard at /pururu until the entry unloads."""
    dashboards = hass.data[LOVELACE_DATA].dashboards
    frontend.async_register_built_in_panel(
        hass,
        "lovelace",
        sidebar_title=TITLE,
        sidebar_icon=ICON,
        frontend_url_path=URL_PATH,
        config={"mode": MODE_YAML},
        require_admin=True,
    )
    dashboards[URL_PATH] = PururuDashboard(hass, entry)

    @callback
    def remove() -> None:
        """Take the dashboard and its panel away."""
        dashboards.pop(URL_PATH, None)
        frontend.async_remove_panel(hass, URL_PATH, warn_if_unknown=False)

    entry.async_on_unload(remove)
```

- [ ] **Step 6: Call it from the entry's setup**

In `custom_components/pururu/__init__.py`, change the import `from . import places` to:

```python
from . import dashboard, places
```

At the end of `async_setup_entry`, add the call right after `_remove_stale(hass, entry, set(devices))`:

```python
    _place(hass, entry, devices)
    _remove_stale(hass, entry, set(devices))
    dashboard.async_setup(hass, entry)
```

In the `async_setup_entry` docstring, change the second paragraph to:

```python
    """Make floors and areas follow the configuration, then build every device.

    Floors and areas come first: devices will be placed in them. The dashboard
    comes last: it shows them all.
    """
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_dashboard.py -n 0 -q`
Expected: 8 passed.

If `test_labels_in_hass_language` fails with stale English labels, the translation cache is keyed per language, so this should not happen. If it does, check that `async_get_translations` is called at each `async_load` with `self.hass.config.language`, and not once at construction.

- [ ] **Step 8: Run the full suite (lint, types, hassfest included)**

Run: `uv run pytest -q`
Expected: all pass, including `tests/test_code.py` (ruff, format, mypy, hassfest) and `tests/test_features.py::test_translation_files_match`.

If ruff format fails, run `uv run ruff format custom_components/pururu` and re-run. If mypy complains about `ConfigEntry[Any]` or the `LovelaceConfig` overrides, fix the annotation; do not add `# type: ignore`.

- [ ] **Step 9: Commit**

```bash
git add custom_components/pururu/dashboard.py custom_components/pururu/__init__.py \
        custom_components/pururu/manifest.json custom_components/pururu/translations \
        tests/test_dashboard.py
git commit -m "pururu: a read-only dashboard of what the entry manages

A lovelace panel in yaml mode at /pururu, admins only: a total of
dashboards, floors, areas and devices, then a table (ID | Name | Type).
Its config is built at every fetch from the entry and the registries.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Live updates, and never failing the setup

**Files:**
- Modify: `custom_components/pururu/dashboard.py` (the imports, and `async_setup`)
- Test: `tests/test_dashboard.py` (append)

**Interfaces:**
- Consumes: from Task 1, `URL_PATH`, `TITLE`, `ICON`, `PururuDashboard(hass, entry)`, `async_setup(hass, entry)`; and in the test file, `URL`, `appliance`, `devices`, `fetch`, `table`.
- Produces: `async_setup(hass: HomeAssistant, entry: ConfigEntry[Any]) -> None` (same signature, now guarded and listening), and `_async_refresh(hass: HomeAssistant) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dashboard.py`. Add `capture`, `device_of` to the `from helpers import …` line. Add these imports at the top:

```python
from unittest.mock import patch

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.setup import async_setup_component
```

Then append:

```python
def errors(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(r.getMessage() for r in caplog.records if r.levelname == "ERROR")


async def test_a_rename_shows_and_refreshes_an_open_page(
        ha: HomeAssistant, hass_ws_client: WebSocketGenerator, appliance: dict[str, Any]) -> None:
    """Renaming a floor, an area or a device in the UI: an open page fetches again."""
    assert await setup(ha, devices(appliance, washer="Washer"),
                       floors={"terreo": FLOORS["terreo"]}, areas={"quintal": AREAS["quintal"]})
    updated = capture(ha, "lovelace_updated")
    fr.async_get(ha).async_update("terreo", name="Ground")
    ar.async_get(ha).async_update("quintal", name="Garden")
    device = device_of(ha, "washer")
    assert device is not None
    dr.async_get(ha).async_update_device(device.id, name_by_user="My washer")
    await ha.async_block_till_done()
    assert len(updated) >= 6, updated  # two per change
    assert {event.data["url_path"] for event in updated} == {URL}
    assert [row[1] for row in table(await fetch(ha, hass_ws_client))[1:]] == [
        "Pururu", "Ground", "Garden", "My washer"]


async def test_a_url_already_taken_is_an_error_and_left_alone(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, appliance: dict[str, Any]) -> None:
    frontend.async_register_built_in_panel(ha, "iframe", frontend_url_path=URL,
                                           config={"url": "https://example.com"})
    assert await setup(ha, devices(appliance, washer="Washer"))
    assert "/pururu is already taken" in errors(caplog)
    assert ha.data[frontend.DATA_PANELS][URL].component_name == "iframe"
    assert URL not in ha.data[LOVELACE_DATA].dashboards
    assert device_of(ha, "washer") is not None
    [entry] = ha.config_entries.async_entries(DOMAIN)
    assert await ha.config_entries.async_unload(entry.entry_id)
    assert ha.data[frontend.DATA_PANELS][URL].component_name == "iframe"


async def test_a_user_dashboard_at_pururu_is_refused(
        ha: HomeAssistant, hass_ws_client: WebSocketGenerator, appliance: dict[str, Any]) -> None:
    assert await setup(ha, devices(appliance, washer="Washer"))
    client = await hass_ws_client(ha)
    await client.send_json_auto_id({"type": "lovelace/dashboards/create", "url_path": URL,
                                    "title": "Mine", "allow_single_word": True})
    assert not (await client.receive_json())["success"]
    assert table(await fetch(ha, hass_ws_client))[1] == ["pururu", "Pururu", "Dashboard"]


async def test_without_lovelace_data_an_error_and_no_dashboard(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, appliance: dict[str, Any]) -> None:
    assert await async_setup_component(ha, "lovelace", {})
    ha.data.pop(LOVELACE_DATA)
    assert await setup(ha, devices(appliance, washer="Washer"))
    assert "The dashboard is not created" in errors(caplog)
    assert URL not in ha.data.get(frontend.DATA_PANELS, {})
    assert device_of(ha, "washer") is not None


async def test_a_changed_lovelace_api_is_an_error_and_no_dashboard(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, appliance: dict[str, Any]) -> None:
    with patch.object(frontend, "async_register_built_in_panel",
                      side_effect=TypeError("unexpected keyword argument")):
        assert await setup(ha, devices(appliance, washer="Washer"))
    assert "unexpected keyword argument" in errors(caplog)
    assert URL not in ha.data[LOVELACE_DATA].dashboards
    assert device_of(ha, "washer") is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_dashboard.py -n 0 -q`
Expected, per test:
- `test_a_rename_shows_and_refreshes_an_open_page` FAILS: no `lovelace_updated` events.
- `test_a_url_already_taken_is_an_error_and_left_alone` FAILS: `ValueError: Overwriting panel pururu`.
- `test_without_lovelace_data_an_error_and_no_dashboard` FAILS: `KeyError` on `LOVELACE_DATA`.
- `test_a_changed_lovelace_api_is_an_error_and_no_dashboard` FAILS: the `TypeError` propagates and the setup fails.
- `test_a_user_dashboard_at_pururu_is_refused` may already pass (HA refuses a url_path held by a panel). Keep it: it pins that behaviour.
- The 8 tests from Task 1 still pass.

- [ ] **Step 3: Rewrite `async_setup`, and add `_async_refresh`**

In `custom_components/pururu/dashboard.py`, change the imports:

```python
from homeassistant.const import EVENT_LOVELACE_UPDATED
from homeassistant.core import Event, HomeAssistant, callback
```

Update the module docstring's last sentence:

```python
"""pururu's dashboard: what the entry manages, read-only, at /pururu.

HA has no public API for an integration's dashboard. As lovelace does for a
YAML dashboard, a LovelaceConfig goes in lovelace's dashboards, and a
`lovelace` panel in `yaml` mode shows it: the UI offers no editing. Its config
is built at every fetch, from the entry and the registries, and never saved;
a change in the registries makes an open page fetch it again.
"""
```

Replace `async_setup` (the whole function) with:

```python
@callback
def async_setup(hass: HomeAssistant, entry: ConfigEntry[Any]) -> None:
    """Show the entry's dashboard at /pururu until the entry unloads.

    What keeps it from being created is a logged error, never a failed setup:
    lovelace not set up, /pururu already taken (as a taken entity ID), or
    lovelace's or frontend's private API no longer the one pururu knows.
    """
    if (lovelace := hass.data.get(LOVELACE_DATA)) is None:
        _LOGGER.error("The dashboard is not created: lovelace is not set up")
        return
    try:
        dashboards = lovelace.dashboards
        if URL_PATH in dashboards or frontend.async_panel_exists(hass, URL_PATH):
            _LOGGER.error(
                "The dashboard is not created: /%s is already taken", URL_PATH
            )
            return
        frontend.async_register_built_in_panel(
            hass,
            "lovelace",
            sidebar_title=TITLE,
            sidebar_icon=ICON,
            frontend_url_path=URL_PATH,
            config={"mode": MODE_YAML},
            require_admin=True,
        )
    except (AttributeError, TypeError) as err:
        _LOGGER.error("The dashboard is not created: %s", err)
        return
    dashboards[URL_PATH] = PururuDashboard(hass, entry)

    @callback
    def remove() -> None:
        """Take the dashboard and its panel away."""
        dashboards.pop(URL_PATH, None)
        frontend.async_remove_panel(hass, URL_PATH, warn_if_unknown=False)

    @callback
    def changed(event: Event[Any]) -> None:
        """A floor, an area or a device changed: an open page fetches again."""
        _async_refresh(hass)

    entry.async_on_unload(remove)
    entry.async_on_unload(
        hass.bus.async_listen(fr.EVENT_FLOOR_REGISTRY_UPDATED, changed)
    )
    entry.async_on_unload(
        hass.bus.async_listen(ar.EVENT_AREA_REGISTRY_UPDATED, changed)
    )
    entry.async_on_unload(
        hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, changed)
    )
    _async_refresh(hass)


@callback
def _async_refresh(hass: HomeAssistant) -> None:
    """Make an open dashboard fetch its config again.

    Twice: after each fetch of a yaml dashboard, the frontend ignores the next
    update (`_ignoreNextUpdateEvent` in ha-panel-lovelace.ts).
    """
    for _ in range(2):
        hass.bus.async_fire(EVENT_LOVELACE_UPDATED, {"url_path": URL_PATH})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_dashboard.py -n 0 -q`
Expected: 13 passed.

If mypy (next step) rejects `changed` typed `Event[Any]` for one of the three registry event types, type it with `Event[fr.EventFloorRegistryUpdatedData] | Event[ar.EventAreaRegistryUpdatedData] | Event[dr.EventDeviceRegistryUpdatedData]`. The alternative is three one-line callbacks, which is worse.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass (ruff, format, mypy, hassfest included).

- [ ] **Step 6: Commit**

```bash
git add custom_components/pururu/dashboard.py tests/test_dashboard.py
git commit -m "pururu: the dashboard follows the registries, and never fails the setup

A floor, area or device change makes an open page fetch again. /pururu
already taken, lovelace missing or its private API changed: a logged
error, no dashboard, everything else created.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Documentation, quality scale and the 0.1.3 release

**Files:**
- Modify: `README.md` (a new `## Dashboard` section between `## Features` and `## Entity IDs`)
- Modify: `CLAUDE.md` (the `## Architecture` list)
- Modify: `custom_components/pururu/quality_scale.yaml` (`dependency-transparency`)
- Modify: `custom_components/pururu/manifest.json` (`version`)

**Interfaces:**
- Consumes: the behaviour from Tasks 1–2.
- Produces: nothing code depends on.

- [ ] **Step 1: README**

In `README.md`, insert this section right before `## Entity IDs`:

```markdown
## Dashboard

pururu adds **Pururu** to the sidebar (`/pururu`, administrators only): a read-only dashboard of what it manages.

- A total of dashboards (this one), floors, areas and devices.
- A table of each of them: ID, name and type. A floor's or an area's ID is its key; a device's is its key under `devices:`.

Only what pururu manages is shown; a floor, area or device made in the UI or by another integration is not. The dashboard is built each time it is opened and follows every start, reload and rename; the UI offers no editing. Its labels are in HA's language (English and Portuguese).

When `/pururu` is already taken, by another panel or a dashboard, the log says so and pururu adds no dashboard; everything else is still created.
```

- [ ] **Step 2: CLAUDE.md**

In `CLAUDE.md`, under `## Architecture`, in the `async_setup_entry` list, add a step 6 after `5. Remove stale entities and devices.`:

```markdown
    6. Show the dashboard (`dashboard.py`).
```

After the `**Floors and areas** (places.py)` bullet group, add:

```markdown
- **Dashboard** (`dashboard.py`):
  - HA has no public API for an integration's dashboard. A `LovelaceConfig` subclass goes in `hass.data[LOVELACE_DATA].dashboards["pururu"]`, and a `lovelace` panel in `yaml` mode (read-only in the UI) shows it. This is private lovelace API: keep every use of it in this module.
  - The config is built at every fetch from `entry.data` and the registries. A registry change fires `lovelace_updated` twice, because the frontend ignores the first one after a yaml fetch.
  - Anything that prevents it (`/pururu` taken, lovelace changed) is a logged error, never a failed setup.
```

- [ ] **Step 3: Quality scale**

In `custom_components/pururu/quality_scale.yaml`, change the `dependency-transparency` comment:

```yaml
  dependency-transparency:
    status: exempt
    comment: No requirements; it uses core's group, utility_meter and lovelace.
```

- [ ] **Step 4: Version**

In `custom_components/pururu/manifest.json`, set `"version": "0.1.3"`.

Run: `python3 release.py check`
Expected: exit 0 (semver, not below the latest release).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add README.md CLAUDE.md custom_components/pururu/quality_scale.yaml \
        custom_components/pururu/manifest.json
git commit -m "pururu: document the dashboard; version 0.1.3

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Manual check in a browser (hand to the human partner)**

No test harness can do this; ask the human partner to check on a real HA (2026.9) with this branch installed:

1. **Sidebar:** **Pururu** shows for an admin, not for a non-admin user.
2. **Layout:** the four totals sit side by side on a wide window and wrap on a phone-width one. The table lists ID | Name | Type.
3. **No editing:** the ⋮ menu has no "Edit dashboard", and there is no "Take control".
4. **Live rename:** with the page open, rename a pururu floor in Settings. The page updates without a manual refresh (the double `lovelace_updated`).
5. **Reload:** with the page open, run **Developer tools → YAML → Pururu**. The page comes back with the current content.
6. **Settings → Dashboards:** lists Pururu, and it cannot be deleted.
