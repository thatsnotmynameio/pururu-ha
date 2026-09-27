"""pururu's dashboard: what the entry manages, read-only, at /pururu."""

import html
from typing import Any
from unittest.mock import patch

from homeassistant.components import frontend
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    floor_registry as fr,
)
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from helpers import DOMAIN, capture, device_of, module, reload, setup

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
    assert await async_setup_component(ha, "lovelace", {})  # it registers panels too
    with patch.object(frontend, "async_register_built_in_panel",
                      side_effect=TypeError("unexpected keyword argument")):
        assert await setup(ha, devices(appliance, washer="Washer"))
    assert "unexpected keyword argument" in errors(caplog)
    assert URL not in ha.data[LOVELACE_DATA].dashboards
    assert device_of(ha, "washer") is not None
