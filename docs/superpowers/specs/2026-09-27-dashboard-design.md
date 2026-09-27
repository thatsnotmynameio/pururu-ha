# Pururu dashboard — design

Version: pururu 0.1.3. Branch: `feat/dash`.

## Goal

pururu provides a read-only dashboard in the sidebar that shows what it manages: one card per total (dashboards, floors, areas, devices) and a table listing every item (ID | Name | Type). It is built in Python, needs nothing installed in the frontend, and is always current.

## Decisions

| Question | Decision |
|---|---|
| What "dashboards" counts | Only pururu's own dashboard: the total is 1. The card exists for later. |
| Editable or generated | Read-only, generated at every fetch. Changes come from YAML or the registries, never from the UI. |
| How the dashboard is provided (HA has no public API for it) | A `LovelaceConfig` subclass in `hass.data[LOVELACE_DATA].dashboards["pururu"]`, plus a `lovelace` built-in panel in `yaml` mode. Private lovelace API, isolated in `dashboard.py`. Dwains Dashboard and lovelace_codegen do the same. |
| Rejected | A custom JS panel (`panel_custom`): a JS bundle to ship, cache-bust and leave untested. A custom strategy: JS too, and still needs the dashboard registered; open frontend bug #53890 can lose it. A storage dashboard: the dashboards collection is a local variable of lovelace's setup, and the UI could edit it. Markdown templates: no template function lists a config entry's devices, and registry changes don't re-render. |
| Table columns | ID \| Name \| Type. |
| URL, title, icon, access | `/pururu`, "Pururu", `mdi:home-group`, admins only (`require_admin=True`). |

## What is managed

| Type | Items | ID | Name |
|---|---|---|---|
| Dashboard | pururu's own dashboard, while it is registered | `pururu` | `Pururu` |
| Floor | the IDs in `entry.data["floors"]` that exist in the floor registry | floor ID (its YAML key) | the registry's name |
| Area | the IDs in `entry.data["areas"]` that exist in the area registry | area ID (its YAML key) | the registry's name |
| Device | `dr.async_entries_for_config_entry(entry)` | the device key (its `(pururu, <key>)` identifier) | `name_by_user`, else `name` |

A floor, area or device created outside pururu is never shown.

## Content

The config returned by `lovelace/config`:

```yaml
title: Pururu
views:
  - type: sections
    path: pururu
    title: Pururu
    sections:
      - type: grid
        column_span: 4          # full width
        cards:
          - type: markdown
            grid_options: {columns: 3}
            content: "# 1\nDashboards"
          - type: markdown
            grid_options: {columns: 3}
            content: "# 3\nFloors"
          - type: markdown
            grid_options: {columns: 3}
            content: "# 5\nAreas"
          - type: markdown
            grid_options: {columns: 3}
            content: "# 2\nDevices"
          - type: markdown
            grid_options: {columns: full}
            content: |
              | ID | Name | Type |
              |---|---|---|
              | pururu | Pururu | Dashboard |
              | terreo | Térreo | Floor |
              ...
```

- **Order.** Rows go dashboard, then floors, areas and devices, and each type is sorted by ID.
- **Card width.** The four total cards sit side by side on a wide screen and wrap on a narrow one.
- **Labels.** They come from `common` in `translations/<lang>.json`, in `hass.config.language`, falling back to English. That covers the four total labels, the three column headers and the four type names. pt-BR: Dashboards / Andares / Áreas / Dispositivos; ID / Nome / Tipo; Dashboard / Andar / Área / Dispositivo.
- **Escaping.** Every ID and name is escaped before it goes into the markdown. The markdown card renders HTML and treats its content as a Jinja template, so `&`, `<`, `>`, `|`, `{` and `}` become HTML entities. A name with `{{` or `|` renders as written: it is not evaluated as a template and it does not break the table.

## Behaviour

### Setup

At the end of `async_setup_entry`, after `_place` and `_remove_stale`, `dashboard.async_setup(hass, entry)` runs:

1. **Lovelace missing.** If `hass.data.get(LOVELACE_DATA)` is `None`, an error is logged and there is no dashboard. An `AttributeError` or `TypeError` raised by lovelace or frontend while registering (their private API changed) is logged the same way.
2. **URL taken.** If `"pururu"` is already a key of `LOVELACE_DATA.dashboards`, or `frontend.async_panel_exists(hass, "pururu")`, an error is logged and there is no dashboard. It is the same policy as for a taken entity ID.
3. **Register.** Otherwise pururu stores a `PururuDashboard` under `dashboards["pururu"]` and calls `frontend.async_register_built_in_panel(hass, "lovelace", sidebar_title="Pururu", sidebar_icon="mdi:home-group", frontend_url_path="pururu", config={"mode": "yaml"}, require_admin=True)`.
4. **Listen.** pururu listens to floor, area and device registry updates. On each one it fires `lovelace_updated` for `url_path: pururu`, so an open page refetches.
   - The event is fired twice. The frontend ignores the first `lovelace_updated` that follows each yaml-mode fetch (`_ignoreNextUpdateEvent` in `ha-panel-lovelace.ts`).
   - The events are also fired once after setup, so a reload shows at once.
5. **Never fails.** Nothing here fails the entry's setup.

### The config class

`PururuDashboard(LovelaceConfig)`:

- `mode` → `"yaml"`.
- `async_load(force)` builds the config above from `entry.data` and the registries at each call. Nothing is cached.
- `async_json(force)` → `json_fragment(json_bytes(await self.async_load(force)))`.
- `async_get_info()` → `{"views": <count>}`, without `mode`, so that lovelace's system health does not report `mode: yaml` because of pururu.
- `async_save` and `async_delete` are inherited: they raise "Not supported", which the websocket returns to the UI.
- Its `config`, which Settings → Dashboards lists: `{"id": "pururu", "url_path": "pururu", "title": "Pururu", "icon": "mdi:home-group", "mode": "yaml", "require_admin": True, "show_in_sidebar": True}`.

### Unload

`dashboard.async_unload(hass)` runs from `async_unload_entry`:

- It pops `dashboards["pururu"]` only when the entry there is a `PururuDashboard`.
- It then calls `frontend.async_remove_panel(hass, "pururu", warn_if_unknown=False)`.
- The registry listeners go through `entry.async_on_unload`.
- A reload removes the dashboard and registers it again.

### Manifest

`dependencies` gains `lovelace`, which hassfest requires for the import. `after_dependencies: ["frontend"]` is added. `frontend` cannot go in `dependencies`: `hass_frontend` is not installed in the test venv, and registering a panel works without frontend set up. The version becomes `0.1.3`.

## Testing

`tests/test_dashboard.py` sets up `lovelace` with `async_setup_component(hass, "lovelace", {})` and talks to it through `hass_ws_client`.

- **Content.** `lovelace/config` with `url_path: pururu` returns the four totals and the table for configured floors, areas and devices, ordered by type then ID.
- **Only pururu's.** A floor, area or device created outside pururu is not listed.
- **Reload.** Dropping a floor, area or device from the YAML removes it from the config.
- **Live.** Renaming a floor or a device in its registry shows in the next fetch and fires `lovelace_updated` for `pururu`.
- **Panel.** `hass.data[frontend.DATA_PANELS]["pururu"]` has component `lovelace`, `config.mode == "yaml"` and `require_admin`. It is gone after unload.
- **Read-only.** `lovelace/config/save` for `pururu` fails.
- **URL taken.** When a panel already holds `pururu`, an error is logged, that panel is untouched, and the devices are still created.
- **Escaping.** A name with `|`, `{{` and `<` comes out escaped.
- **Language.** With `hass.config.language = "pt-BR"`, the labels are the pt-BR ones.
- **Translations.** `common` has the same keys in `en.json` and `pt-BR.json`.

**Manual check in a browser:**
- the page refreshes after a rename (the double event);
- a reload with the page open;
- Edit is absent;
- the layout on a narrow screen.

## Documentation

- README: a **Dashboard** section covering where it is, what it shows, that it is read-only and admin-only, and the error when `/pururu` is taken.
- CLAUDE.md: one architecture bullet on `dashboard.py` and its use of private lovelace API.

## Risks

- **Private lovelace API.** It covers `LOVELACE_DATA`, `LovelaceConfig`, the `dashboards` dict and the panel's `config.mode`. It broke other integrations in 2026.2. The tests pin the behaviour at the pinned HA, and a mismatch at runtime is a logged error, not a failed setup.
- **Double `lovelace_updated`.** It works around a frontend detail and may become unnecessary. Firing twice is harmless.
- **Reload flash.** A reload removes and re-adds the panel, so an open page may flash.
