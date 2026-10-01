"""Feature `lights`: a made-up living room's ceiling and lamp, standing for real lights."""

from typing import Any

from homeassistant.components.light.const import DATA_COMPONENT
from homeassistant.core import Context, CoreState, HomeAssistant, State
from homeassistant.helpers import entity_registry as er
import pytest

from helpers import capture, fake, held, reload, restart, settle, setup

KEY = "biblioteca"
REAL_TETO = "light.biblioteca_teto"
REAL_ABAJUR = "light.biblioteca_abajur"
TETO = "light.pururu_biblioteca_light_teto"
ABAJUR = "light.pururu_biblioteca_light_abajur"
LIGHTS: dict[str, Any] = {"teto": {"entity": f"homeassistant.{REAL_TETO}", "name": "Teto"},
                          "abajur": {"entity": f"homeassistant.{REAL_ABAJUR}", "name": "Abajur"}}
DEVICES = {KEY: {"name": "Biblioteca", "lights": LIGHTS}}
# A colour bulb: hs colour (so brightness), two effects, EFFECT | FLASH | TRANSITION
BULB = {"supported_color_modes": ["hs"], "color_mode": "hs", "brightness": 128,
        "hs_color": [30.0, 50.0], "effect_list": ["rainbow", "strobe"], "effect": "rainbow",
        "supported_features": 44}
ONOFF = {"supported_color_modes": ["onoff"], "color_mode": "onoff"}
REAL_ARANDELA = "switch.sonoff_arandela"
ARANDELA = "light.pururu_biblioteca_light_arandela"
ARANDELA_BLOCK = {"entity": f"homeassistant.{REAL_ARANDELA}", "name": "Arandela"}


def state(hass: HomeAssistant, entity_id: str) -> str:
    return hass.states.get(entity_id).state


def attributes(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    return dict(hass.states.get(entity_id).attributes)


@pytest.fixture
async def biblioteca(ha: HomeAssistant) -> HomeAssistant:
    await fake(ha, REAL_TETO, "on", BULB)
    await fake(ha, REAL_ABAJUR, "off", ONOFF)
    assert await setup(ha, DEVICES)
    return ha


async def forwarded(hass: HomeAssistant, entity_id: str, service: str, data: dict[str, Any],
                    context: Context, real: str) -> list[tuple[str, str, dict[str, Any], str]]:
    """Call light.`service` on a pururu light; the calls it passed on to `real`."""
    calls = capture(hass, "call_service")
    await hass.services.async_call("light", service, {"entity_id": entity_id, **data},
                                   blocking=True, context=context)
    await settle()
    return [(event.data["domain"], event.data["service"],
             {k: v for k, v in event.data["service_data"].items() if k != "entity_id"},
             event.context.id)
            for event in calls if event.data["service_data"].get("entity_id") == [real]]


# --- schema ------------------------------------------------------------------


@pytest.mark.parametrize("block", [
    pytest.param({"teto": {"entity": "homeassistant.sensor.biblioteca_teto", "name": "Teto"}}, id="another domain"),
    pytest.param({"teto": {"entity": f"homeassistant.{REAL_TETO}"}}, id="no name"),
    pytest.param({"teto": {"entity": f"homeassistant.{REAL_TETO}", "name": ""}}, id="empty name"),
    pytest.param({"teto": {"entity": f"homeassistant.{REAL_TETO}", "name": "  "}}, id="blank name"),
    pytest.param({"teto": REAL_TETO}, id="just the entity"),
    pytest.param({"teto": {"entity": [REAL_TETO, REAL_ABAJUR], "name": "Teto"}}, id="a list"),
    pytest.param({"teto": {"entity": f"homeassistant.{REAL_TETO}", "name": "Teto", "icon": "mdi:lamp"}},
                 id="unknown key"),
    pytest.param({}, id="no light"),
    pytest.param({"Teto": {"entity": f"homeassistant.{REAL_TETO}", "name": "Teto"}}, id="key not a slug"),
    pytest.param({"teto": {"entity": f"homeassistant.{TETO}", "name": "Teto"}}, id="a pururu light"),
    pytest.param({"teto": {"entity": "homeassistant.switch.pururu_greenhouse_switch_sprinkler", "name": "Teto"}},
                 id="a pururu switch"),
])
async def test_invalid_block_is_refused(ha: HomeAssistant, block: dict[str, Any]) -> None:
    assert not await setup(ha, {KEY: {"name": "Biblioteca", "lights": block}})


@pytest.mark.parametrize(("entity", "message"), [
    pytest.param("homeassistant.sensor.biblioteca_teto", "homeassistant.sensor.biblioteca_teto is not a light or switch",
                 id="another domain"),
    pytest.param(f"homeassistant.{TETO}", f"homeassistant.{TETO} is a pururu light: name the real one",
                 id="a pururu light"),
    pytest.param(REAL_TETO, f"{REAL_TETO} is not a Home Assistant entity: homeassistant.<domain>.<object_id>",
                 id="without homeassistant, as before 0.2.2"),
    pytest.param("homeassistant.switch.pururu_greenhouse_switch_sprinkler",
                 "homeassistant.switch.pururu_greenhouse_switch_sprinkler is a pururu switch: name the real one",
                 id="a pururu switch"),
])
async def test_the_error_names_what_is_wrong(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, entity: str, message: str) -> None:
    """The messages the docs quote (troubleshooting)."""
    assert not await setup(ha, {KEY: {"name": "Biblioteca", "lights": {
        "teto": {"entity": entity, "name": "Teto"}}}})
    assert message in caplog.text


async def test_a_light_keyed_light_repeats_it(ha: HomeAssistant) -> None:
    """No exception to the pattern: the namespace, then the key, even when they are alike."""
    await fake(ha, REAL_TETO, "on", ONOFF)
    assert await setup(ha, {KEY: {"name": "Biblioteca", "lights": {"light": LIGHTS["teto"]}}})
    assert held(ha, KEY) == {"light.pururu_biblioteca_light_light"}


async def test_a_switch_and_a_light_can_share_a_key(ha: HomeAssistant) -> None:
    """switch_sprinkler and light_sprinkler: each feature's keys are in its own namespace."""
    await fake(ha, REAL_TETO, "on", ONOFF)
    await fake(ha, "switch.biblioteca_sprinkler", "off")
    assert await setup(ha, {KEY: {
        "name": "Biblioteca",
        "lights": {"sprinkler": LIGHTS["teto"]},
        "switches": {"sprinkler": {"entity": "homeassistant.switch.biblioteca_sprinkler", "name": "Irrigador"}},
    }})
    assert held(ha, KEY) == {"light.pururu_biblioteca_light_sprinkler", "switch.pururu_biblioteca_switch_sprinkler"}


# --- the device ----------------------------------------------------------------


async def test_a_device_with_only_lights(biblioteca: HomeAssistant) -> None:
    assert held(biblioteca, KEY) == {TETO, ABAJUR}


async def test_one_real_light_twice_in_a_device(ha: HomeAssistant) -> None:
    await fake(ha, REAL_TETO, "on", ONOFF)
    assert await setup(ha, {KEY: {"name": "Biblioteca", "lights": {
        "teto": LIGHTS["teto"], "teto_2": {"entity": f"homeassistant.{REAL_TETO}", "name": "Teto 2"}}}})
    assert state(ha, TETO) == "on"
    assert state(ha, "light.pururu_biblioteca_light_teto_2") == "on"


async def test_names_come_from_the_configuration(biblioteca: HomeAssistant) -> None:
    """LightGroup's own translation key ("light") doesn't leak into pururu's."""
    assert biblioteca.states.get(TETO).attributes["friendly_name"] == "Biblioteca Teto"
    entry = er.async_get(biblioteca).async_get(TETO)
    assert entry is not None
    assert entry.unique_id == "pururu_biblioteca_light_teto"
    assert entry.translation_key is None


async def test_names_are_the_same_in_portuguese(ha: HomeAssistant) -> None:
    ha.config.language = "pt-BR"
    assert await setup(ha, DEVICES)
    assert ha.states.get(ABAJUR).attributes["friendly_name"] == "Biblioteca Abajur"


async def test_it_names_the_real_light(biblioteca: HomeAssistant) -> None:
    assert biblioteca.states.get(TETO).attributes["entity_id"] == [REAL_TETO]


# --- state -------------------------------------------------------------------------


@pytest.mark.parametrize(("real", "expected"), [
    ("on", "on"), ("off", "off"), ("unknown", "unknown"), ("unavailable", "unavailable"),
])
async def test_follows_the_real_light(biblioteca: HomeAssistant, real: str, expected: str) -> None:
    await fake(biblioteca, REAL_ABAJUR, real, ONOFF)
    assert state(biblioteca, ABAJUR) == expected
    assert state(biblioteca, TETO) == "on"


async def test_without_the_real_light_it_is_unavailable(ha: HomeAssistant) -> None:
    assert await setup(ha, DEVICES)
    assert state(ha, TETO) == "unavailable"


async def test_follows_the_real_light_going_and_coming_back(biblioteca: HomeAssistant) -> None:
    biblioteca.states.async_remove(REAL_ABAJUR)
    await settle()
    assert state(biblioteca, ABAJUR) == "unavailable"
    await fake(biblioteca, REAL_ABAJUR, "on", ONOFF)
    assert state(biblioteca, ABAJUR) == "on"


async def test_assumed_state_follows_the_real_light(biblioteca: HomeAssistant) -> None:
    await fake(biblioteca, REAL_ABAJUR, "on", {**ONOFF, "assumed_state": True})
    assert biblioteca.states.get(ABAJUR).attributes.get("assumed_state") is True


# --- what it offers ---------------------------------------------------------------------


async def test_it_offers_what_the_real_light_offers(biblioteca: HomeAssistant) -> None:
    teto = attributes(biblioteca, TETO)
    assert teto["supported_color_modes"] == ["hs"]
    assert teto["color_mode"] == "hs"
    assert teto["brightness"] == 128
    assert tuple(teto["hs_color"]) == (30.0, 50.0)
    assert teto["effect_list"] == ["rainbow", "strobe"]
    assert teto["effect"] == "rainbow"
    assert teto["supported_features"] == 44


async def test_an_on_off_light_offers_on_and_off(biblioteca: HomeAssistant) -> None:
    await fake(biblioteca, REAL_ABAJUR, "on", ONOFF)
    abajur = attributes(biblioteca, ABAJUR)
    assert abajur["supported_color_modes"] == ["onoff"]
    assert abajur["color_mode"] == "onoff"
    assert abajur.get("brightness") is None
    assert abajur["supported_features"] == 0


async def test_what_it_offers_follows_the_real_light(biblioteca: HomeAssistant) -> None:
    """A firmware update gives the lamp colour: no reload needed."""
    await fake(biblioteca, REAL_ABAJUR, "on", ONOFF)
    assert attributes(biblioteca, ABAJUR)["supported_color_modes"] == ["onoff"]
    await fake(biblioteca, REAL_ABAJUR, "on", BULB)
    assert attributes(biblioteca, ABAJUR)["supported_color_modes"] == ["hs"]
    assert attributes(biblioteca, ABAJUR)["brightness"] == 128


async def test_losing_colour_is_followed(biblioteca: HomeAssistant) -> None:
    """The real light now reports on and off only (its integration, or a simpler lamp)."""
    assert attributes(biblioteca, TETO)["supported_color_modes"] == ["hs"]
    await fake(biblioteca, REAL_TETO, "on", ONOFF)
    teto = attributes(biblioteca, TETO)
    assert teto["supported_color_modes"] == ["onoff"]
    assert teto["color_mode"] == "onoff"
    assert teto.get("brightness") is None
    assert teto.get("hs_color") is None
    assert teto.get("effect_list") is None
    assert teto["supported_features"] == 0


async def test_after_losing_colour_it_takes_no_colour(biblioteca: HomeAssistant) -> None:
    """HA drops what the light no longer offers: the real one is only turned on."""
    await fake(biblioteca, REAL_TETO, "on", ONOFF)
    context = Context()
    calls = await forwarded(biblioteca, TETO, "turn_on",
                            {"brightness": 100, "hs_color": [200, 70], "transition": 2},
                            context, REAL_TETO)
    assert calls == [("light", "turn_on", {}, context.id)]


# --- commands ------------------------------------------------------------------------


async def test_turning_it_on_passes_everything_on(biblioteca: HomeAssistant) -> None:
    """With the caller's context, so the logbook names who did it."""
    context = Context()
    calls = await forwarded(biblioteca, TETO, "turn_on",
                            {"brightness": 100, "hs_color": [200, 70], "transition": 2},
                            context, REAL_TETO)
    assert len(calls) == 1
    domain, service, data, context_id = calls[0]
    assert (domain, service, context_id) == ("light", "turn_on", context.id)
    assert data["brightness"] == 100
    assert tuple(data["hs_color"]) == (200.0, 70.0)
    assert data["transition"] == 2


async def test_turning_it_off_passes_the_transition_on(biblioteca: HomeAssistant) -> None:
    context = Context()
    calls = await forwarded(biblioteca, TETO, "turn_off", {"transition": 3}, context, REAL_TETO)
    assert calls == [("light", "turn_off", {"transition": 3}, context.id)]


async def test_turning_on_without_the_real_light_does_nothing(ha: HomeAssistant) -> None:
    assert await setup(ha, DEVICES)
    assert await forwarded(ha, TETO, "turn_on", {}, Context(), REAL_TETO) == []
    assert state(ha, TETO) == "unavailable"


# --- a real switch as a light ---------------------------------------------------------


@pytest.fixture
async def arandela(ha: HomeAssistant) -> HomeAssistant:
    await fake(ha, REAL_ARANDELA, "off")
    assert await setup(ha, {KEY: {"name": "Biblioteca", "lights": {"arandela": ARANDELA_BLOCK}}})
    return ha


async def test_a_real_switch_is_a_light(arandela: HomeAssistant) -> None:
    assert held(arandela, KEY) == {ARANDELA}
    assert arandela.states.get(ARANDELA).attributes["friendly_name"] == "Biblioteca Arandela"
    assert arandela.states.get(ARANDELA).attributes["entity_id"] == [REAL_ARANDELA]
    entry = er.async_get(arandela).async_get(ARANDELA)
    assert entry is not None
    assert entry.translation_key is None


@pytest.mark.parametrize(("real", "expected"), [
    ("on", "on"), ("off", "off"), ("unknown", "unknown"), ("unavailable", "unavailable"),
])
async def test_follows_the_real_switch(arandela: HomeAssistant, real: str, expected: str) -> None:
    await fake(arandela, REAL_ARANDELA, real)
    assert state(arandela, ARANDELA) == expected


async def test_without_the_real_switch_it_is_unavailable(ha: HomeAssistant) -> None:
    assert await setup(ha, {KEY: {"name": "Biblioteca", "lights": {"arandela": ARANDELA_BLOCK}}})
    assert state(ha, ARANDELA) == "unavailable"


async def test_follows_the_real_switch_going_and_coming_back(arandela: HomeAssistant) -> None:
    arandela.states.async_remove(REAL_ARANDELA)
    await settle()
    assert state(arandela, ARANDELA) == "unavailable"
    await fake(arandela, REAL_ARANDELA, "on")
    assert state(arandela, ARANDELA) == "on"


async def test_assumed_state_follows_the_real_switch(arandela: HomeAssistant) -> None:
    await fake(arandela, REAL_ARANDELA, "on", {"assumed_state": True})
    assert arandela.states.get(ARANDELA).attributes.get("assumed_state") is True


async def test_a_switch_offers_on_and_off(arandela: HomeAssistant) -> None:
    await fake(arandela, REAL_ARANDELA, "on")
    light = attributes(arandela, ARANDELA)
    assert light["supported_color_modes"] == ["onoff"]
    assert light["color_mode"] == "onoff"
    assert light.get("brightness") is None
    assert light["supported_features"] == 0


async def test_turning_it_on_and_off_switches_the_real_one(arandela: HomeAssistant) -> None:
    context = Context()
    assert await forwarded(arandela, ARANDELA, "turn_on", {}, context, REAL_ARANDELA) == [
        ("switch", "turn_on", {}, context.id)]
    assert await forwarded(arandela, ARANDELA, "turn_off", {}, context, REAL_ARANDELA) == [
        ("switch", "turn_off", {}, context.id)]


async def test_light_arguments_on_a_switch_turn_it_on(arandela: HomeAssistant) -> None:
    """HA drops what an on/off light can't take; the relay still turns on."""
    context = Context()
    calls = await forwarded(arandela, ARANDELA, "turn_on",
                            {"brightness_pct": 50, "transition": 2}, context, REAL_ARANDELA)
    assert calls == [("switch", "turn_on", {}, context.id)]


async def test_turning_on_without_the_real_switch_does_nothing(ha: HomeAssistant) -> None:
    assert await setup(ha, {KEY: {"name": "Biblioteca", "lights": {"arandela": ARANDELA_BLOCK}}})
    assert await forwarded(ha, ARANDELA, "turn_on", {}, Context(), REAL_ARANDELA) == []
    assert state(ha, ARANDELA) == "unavailable"


async def test_after_a_restart_it_shows_the_real_switch(ha: HomeAssistant) -> None:
    await fake(ha, REAL_ARANDELA, "on")
    await restart(ha, {KEY: {"name": "Biblioteca", "lights": {"arandela": ARANDELA_BLOCK}}})
    assert state(ha, ARANDELA) == "on"


@pytest.mark.parametrize("entity_key", ["teto", "arandela"])
async def test_until_home_assistant_starts_it_is_unavailable(
        ha: HomeAssistant, entity_key: str) -> None:
    """The group waits for the start to read its member: a bulb's or a relay's light alike."""
    ha.set_state(CoreState.not_running)
    assert await setup(ha, {KEY: {"name": "Biblioteca", "lights": {
        "teto": LIGHTS["teto"], "arandela": ARANDELA_BLOCK}}})
    assert state(ha, f"light.pururu_biblioteca_light_{entity_key}") == "unavailable"


async def test_bulbs_and_relays_in_one_device(ha: HomeAssistant) -> None:
    await fake(ha, REAL_TETO, "on", BULB)
    await fake(ha, REAL_ARANDELA, "on")
    assert await setup(ha, {KEY: {"name": "Biblioteca", "lights": {
        "teto": LIGHTS["teto"], "arandela": ARANDELA_BLOCK}}})
    assert attributes(ha, TETO)["supported_color_modes"] == ["hs"]
    assert attributes(ha, ARANDELA)["supported_color_modes"] == ["onoff"]


# --- one real entity, one kind per device ----------------------------------------------


@pytest.mark.parametrize("lights_first", [True, False], ids=["lights first", "switches first"])
async def test_one_real_entity_in_two_features_of_a_device_is_refused(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture, lights_first: bool) -> None:
    """A relay is a switch or a light of the device, not both; FEATURES order names them."""
    lights = ("lights", {"arandela": ARANDELA_BLOCK})
    switches = ("switches", {"arandela": ARANDELA_BLOCK})
    blocks = dict([lights, switches] if lights_first else [switches, lights])
    assert not await setup(ha, {KEY: {"name": "Biblioteca", **blocks}})
    assert f"switches: homeassistant.{REAL_ARANDELA} is already in lights" in caplog.text


async def test_one_real_switch_as_a_light_and_as_a_switch_in_two_devices(
        ha: HomeAssistant) -> None:
    await fake(ha, REAL_ARANDELA, "on")
    assert await setup(ha, {
        KEY: {"name": "Biblioteca", "lights": {"arandela": ARANDELA_BLOCK}},
        "varanda": {"name": "Varanda", "switches": {"arandela": ARANDELA_BLOCK}},
    })
    assert state(ha, ARANDELA) == "on"
    assert state(ha, "switch.pururu_varanda_switch_arandela") == "on"


# --- IDs, renames, reloads and restarts --------------------------------------------------


async def test_an_id_already_taken_is_an_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    other = er.async_get(ha).async_get_or_create(
        "light", "template", "someone_else", suggested_object_id="pururu_biblioteca_light_teto")
    assert other.entity_id == TETO
    assert await setup(ha, DEVICES)
    assert held(ha, KEY) == {ABAJUR}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(TETO in message and "template" in message for message in errors), errors


async def test_follows_its_own_rename(biblioteca: HomeAssistant) -> None:
    er.async_get(biblioteca).async_update_entity(ABAJUR, new_entity_id="light.biblioteca_luminaria")
    await biblioteca.async_block_till_done()
    await fake(biblioteca, REAL_ABAJUR, "on", ONOFF)
    assert state(biblioteca, "light.biblioteca_luminaria") == "on"
    assert held(biblioteca, KEY) == {TETO, "light.biblioteca_luminaria"}


@pytest.mark.parametrize(("renamed", "new_id"), [
    pytest.param(TETO, "light.teto", id="a pururu light"),
    pytest.param("switch.pururu_biblioteca_switch_sprinkler", "switch.irrigador", id="a pururu switch"),
])
async def test_a_renamed_pururu_entity_is_not_a_real_one(
        biblioteca: HomeAssistant, caplog: pytest.LogCaptureFixture, renamed: str, new_id: str) -> None:
    """Renamed in the UI, it no longer starts with pururu_: the registry still knows it."""
    extra = {}
    if renamed.startswith("switch."):
        extra = {"switches": {"sprinkler": {"entity": "homeassistant.switch.biblioteca_sprinkler", "name": "Irrigador"}}}
        await fake(biblioteca, "switch.biblioteca_sprinkler", "off")
        await reload(biblioteca, {KEY: {"name": "Biblioteca", "lights": LIGHTS, **extra}})
    er.async_get(biblioteca).async_update_entity(renamed, new_entity_id=new_id)
    await biblioteca.async_block_till_done()
    caplog.clear()
    domain = new_id.split(".")[0]
    await reload(biblioteca, {KEY: {"name": "Biblioteca", **extra, "lights": {
        "teto": LIGHTS["teto"],
        "abajur": {"entity": f"homeassistant.{new_id}", "name": "Abajur"},
    }}})
    assert biblioteca.states.get(ABAJUR) is None
    assert ABAJUR not in held(biblioteca, KEY)
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(f"{new_id} is a pururu {domain}: name the real one; not creating {ABAJUR}"
               in message for message in errors), errors


async def test_a_light_renamed_to_what_it_stands_for_stays_as_it_is(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """Renamed in the UI to its own entity: kept with its rename, unavailable, at every reload."""
    await fake(ha, REAL_TETO, "on", BULB)
    devices = {KEY: {"name": "Biblioteca", "lights": {
        "teto": LIGHTS["teto"], "abajur": {"entity": "homeassistant.light.biblioteca_luminaria", "name": "Abajur"}}}}
    assert await setup(ha, devices)
    er.async_get(ha).async_update_entity(ABAJUR, new_entity_id="light.biblioteca_luminaria")
    await ha.async_block_till_done()
    for _ in range(3):
        entry = er.async_get(ha).async_get("light.biblioteca_luminaria")
        assert entry is not None
        assert entry.unique_id == "pururu_biblioteca_light_abajur"
        assert state(ha, "light.biblioteca_luminaria") == "unavailable"
        assert held(ha, KEY) == {TETO, "light.biblioteca_luminaria"}
        assert "light.biblioteca_luminaria is this light itself: name the real one" in caplog.text
        caplog.clear()
        await reload(ha, devices)


async def test_a_light_standing_for_itself_passes_nothing_on(ha: HomeAssistant) -> None:
    """Its state set by hand (developer tools) makes it neither available nor calling itself."""
    devices = {KEY: {"name": "Biblioteca", "lights": {
        "abajur": {"entity": "homeassistant.light.biblioteca_luminaria", "name": "Abajur"}}}}
    assert await setup(ha, devices)
    er.async_get(ha).async_update_entity(ABAJUR, new_entity_id="light.biblioteca_luminaria")
    await ha.async_block_till_done()
    await fake(ha, "light.biblioteca_luminaria", "on", ONOFF)
    calls = await forwarded(ha, "light.biblioteca_luminaria", "turn_on", {}, Context(),
                            "light.biblioteca_luminaria")
    assert calls == []


async def test_reload_that_drops_a_light_removes_it(biblioteca: HomeAssistant) -> None:
    await reload(biblioteca, {KEY: {"name": "Biblioteca", "lights": {"teto": LIGHTS["teto"]}}})
    assert er.async_get(biblioteca).async_get(ABAJUR) is None
    assert biblioteca.states.get(ABAJUR) is None
    assert held(biblioteca, KEY) == {TETO}


async def test_after_a_restart_it_shows_the_real_light(ha: HomeAssistant) -> None:
    await fake(ha, REAL_TETO, "on", BULB)
    await fake(ha, REAL_ABAJUR, "off", ONOFF)
    await restart(ha, DEVICES)
    assert state(ha, TETO) == "on"
    assert attributes(ha, TETO)["brightness"] == 128
    assert state(ha, ABAJUR) == "off"


# --- the alert lights ------------------------------------------------------------------


def light_entity(hass: HomeAssistant, entity_id: str) -> Any:
    """The light entity itself, as the light component holds it."""
    return hass.data[DATA_COMPONENT].get_entity(entity_id)


async def test_an_effect_the_real_light_does_not_list_is_dropped(biblioteca: HomeAssistant) -> None:
    """The alert lights ask every light for breathe: a bulb without it takes the rest."""
    calls = await forwarded(biblioteca, TETO, "turn_on", {"effect": "breathe", "brightness": 100},
                            Context(), REAL_TETO)
    assert len(calls) == 1
    assert "effect" not in calls[0][2]
    assert calls[0][2]["brightness"] == 100


async def test_an_effect_the_real_light_lists_is_passed_on(biblioteca: HomeAssistant) -> None:
    calls = await forwarded(biblioteca, TETO, "turn_on", {"effect": "strobe"}, Context(), REAL_TETO)
    assert calls[0][2]["effect"] == "strobe"


@pytest.mark.parametrize(("entity_id", "real", "block"), [
    pytest.param(TETO, REAL_TETO, LIGHTS["teto"], id="a light"),
    pytest.param(ARANDELA, REAL_ARANDELA, ARANDELA_BLOCK, id="a relay"),
])
async def test_it_shows_what_the_alert_lights_use_it_for(
        ha: HomeAssistant, entity_id: str, real: str, block: dict[str, Any]) -> None:
    await fake(ha, real, "on", BULB if real == REAL_TETO else None)
    key = entity_id.rsplit("_", 1)[1]
    assert await setup(ha, {KEY: {"name": "Biblioteca", "lights": {key: block}}})
    context = Context()
    light_entity(ha, entity_id).async_show_alert("medium", ["binary_sensor.x"], context)
    shown = ha.states.get(entity_id)
    assert shown.attributes["alert"] == "medium"
    assert shown.attributes["alerts"] == ["binary_sensor.x"]
    assert shown.attributes["entity_id"] == [real]
    assert shown.context.id == context.id
    light_entity(ha, entity_id).async_show_alert(None, [], Context())
    free = ha.states.get(entity_id).attributes
    assert "alert" not in free
    assert "alerts" not in free
    assert free["entity_id"] == [real]


async def test_it_remembers_what_the_alert_lights_showed(ha: HomeAssistant) -> None:
    await fake(ha, REAL_TETO, "on", BULB)
    await restart(ha, DEVICES, (State(TETO, "on"), {"alert": "resolved"}))
    assert light_entity(ha, TETO).restored_alert == "resolved"
    assert light_entity(ha, ABAJUR).restored_alert is None
