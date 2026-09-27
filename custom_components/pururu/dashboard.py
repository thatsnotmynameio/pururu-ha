"""pururu's dashboard: what the entry manages, read-only, at /pururu.

HA has no public API for an integration's dashboard. As lovelace does for a
YAML dashboard, a LovelaceConfig goes in lovelace's dashboards, and a
`lovelace` panel in `yaml` mode shows it: the UI offers no editing. Its config
is built at every fetch, from the entry and the registries, and never saved.
"""

from collections.abc import Mapping
import logging
from typing import Any, Final, override

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
    @override
    def mode(self) -> str:
        """Read-only, as a YAML dashboard."""
        return MODE_YAML

    @override
    async def async_get_info(self) -> dict[str, Any]:
        """No mode: lovelace's system health would report `yaml` because of pururu."""
        return {"views": 1}

    @override
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

    @override
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
