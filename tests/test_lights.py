"""Feature `lights`: a made-up living room's ceiling and lamp, standing for real lights."""

from typing import Any

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest

from helpers import capture, fake, held, reload, restart, settle, setup

KEY = "sala"
REAL_TETO = "light.sala_teto"
REAL_ABAJUR = "light.sala_abajur"
TETO = "light.pururu_sala_light_teto"
ABAJUR = "light.pururu_sala_light_abajur"
LIGHTS: dict[str, Any] = {"teto": {"entity": REAL_TETO, "name": "Teto"},
                          "abajur": {"entity": REAL_ABAJUR, "name": "Abajur"}}
DEVICES = {KEY: {"name": "Sala", "lights": LIGHTS}}
# A colour bulb: hs colour (so brightness), two effects, EFFECT | FLASH | TRANSITION
BULB = {"supported_color_modes": ["hs"], "color_mode": "hs", "brightness": 128,
        "hs_color": [30.0, 50.0], "effect_list": ["rainbow", "strobe"], "effect": "rainbow",
        "supported_features": 44}
ONOFF = {"supported_color_modes": ["onoff"], "color_mode": "onoff"}
REAL_ARANDELA = "switch.sonoff_arandela"
ARANDELA = "light.pururu_sala_light_arandela"
ARANDELA_BLOCK = {"entity": REAL_ARANDELA, "name": "Arandela"}


def state(hass: HomeAssistant, entity_id: str) -> str:
    return hass.states.get(entity_id).state


def attributes(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    return dict(hass.states.get(entity_id).attributes)


@pytest.fixture
async def sala(ha: HomeAssistant) -> HomeAssistant:
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
    pytest.param({"teto": {"entity": "sensor.sala_teto", "name": "Teto"}}, id="another domain"),
    pytest.param({"teto": {"entity": REAL_TETO}}, id="no name"),
    pytest.param({"teto": {"entity": REAL_TETO, "name": ""}}, id="empty name"),
    pytest.param({"teto": {"entity": REAL_TETO, "name": "  "}}, id="blank name"),
    pytest.param({"teto": REAL_TETO}, id="just the entity"),
    pytest.param({"teto": {"entity": [REAL_TETO, REAL_ABAJUR], "name": "Teto"}}, id="a list"),
    pytest.param({"teto": {"entity": REAL_TETO, "name": "Teto", "icon": "mdi:lamp"}},
                 id="unknown key"),
    pytest.param({}, id="no light"),
    pytest.param({"Teto": {"entity": REAL_TETO, "name": "Teto"}}, id="key not a slug"),
    pytest.param({"teto": {"entity": TETO, "name": "Teto"}}, id="a pururu light"),
    pytest.param({"teto": {"entity": "switch.pururu_pool_switch_pump", "name": "Teto"}},
                 id="a pururu switch"),
])
async def test_invalid_block_is_refused(ha: HomeAssistant, block: dict[str, Any]) -> None:
    assert not await setup(ha, {KEY: {"name": "Sala", "lights": block}})


async def test_a_light_keyed_light_repeats_it(ha: HomeAssistant) -> None:
    """No exception to the pattern: the namespace, then the key, even when they are alike."""
    await fake(ha, REAL_TETO, "on", ONOFF)
    assert await setup(ha, {KEY: {"name": "Sala", "lights": {"light": LIGHTS["teto"]}}})
    assert held(ha, KEY) == {"light.pururu_sala_light_light"}


async def test_a_switch_and_a_light_can_share_a_key(ha: HomeAssistant) -> None:
    """switch_pump and light_pump: each feature's keys are in its own namespace."""
    await fake(ha, REAL_TETO, "on", ONOFF)
    await fake(ha, "switch.sala_pump", "off")
    assert await setup(ha, {KEY: {
        "name": "Sala",
        "lights": {"pump": LIGHTS["teto"]},
        "switches": {"pump": {"entity": "switch.sala_pump", "name": "Bomba"}},
    }})
    assert held(ha, KEY) == {"light.pururu_sala_light_pump", "switch.pururu_sala_switch_pump"}


# --- the device ----------------------------------------------------------------


async def test_a_device_with_only_lights(sala: HomeAssistant) -> None:
    assert held(sala, KEY) == {TETO, ABAJUR}


async def test_one_real_light_twice_in_a_device(ha: HomeAssistant) -> None:
    await fake(ha, REAL_TETO, "on", ONOFF)
    assert await setup(ha, {KEY: {"name": "Sala", "lights": {
        "teto": LIGHTS["teto"], "teto_2": {"entity": REAL_TETO, "name": "Teto 2"}}}})
    assert state(ha, TETO) == "on"
    assert state(ha, "light.pururu_sala_light_teto_2") == "on"


async def test_names_come_from_the_configuration(sala: HomeAssistant) -> None:
    """LightGroup's own translation key ("light") doesn't leak into pururu's."""
    assert sala.states.get(TETO).attributes["friendly_name"] == "Sala Teto"
    entry = er.async_get(sala).async_get(TETO)
    assert entry is not None
    assert entry.unique_id == "pururu_sala_light_teto"
    assert entry.translation_key is None


async def test_names_are_the_same_in_portuguese(ha: HomeAssistant) -> None:
    ha.config.language = "pt-BR"
    assert await setup(ha, DEVICES)
    assert ha.states.get(ABAJUR).attributes["friendly_name"] == "Sala Abajur"


async def test_it_names_the_real_light(sala: HomeAssistant) -> None:
    assert sala.states.get(TETO).attributes["entity_id"] == [REAL_TETO]


# --- state -------------------------------------------------------------------------


@pytest.mark.parametrize(("real", "expected"), [
    ("on", "on"), ("off", "off"), ("unknown", "unknown"), ("unavailable", "unavailable"),
])
async def test_follows_the_real_light(sala: HomeAssistant, real: str, expected: str) -> None:
    await fake(sala, REAL_ABAJUR, real, ONOFF)
    assert state(sala, ABAJUR) == expected
    assert state(sala, TETO) == "on"


async def test_without_the_real_light_it_is_unavailable(ha: HomeAssistant) -> None:
    assert await setup(ha, DEVICES)
    assert state(ha, TETO) == "unavailable"


async def test_follows_the_real_light_going_and_coming_back(sala: HomeAssistant) -> None:
    sala.states.async_remove(REAL_ABAJUR)
    await settle()
    assert state(sala, ABAJUR) == "unavailable"
    await fake(sala, REAL_ABAJUR, "on", ONOFF)
    assert state(sala, ABAJUR) == "on"


async def test_assumed_state_follows_the_real_light(sala: HomeAssistant) -> None:
    await fake(sala, REAL_ABAJUR, "on", {**ONOFF, "assumed_state": True})
    assert sala.states.get(ABAJUR).attributes.get("assumed_state") is True


# --- what it offers ---------------------------------------------------------------------


async def test_it_offers_what_the_real_light_offers(sala: HomeAssistant) -> None:
    teto = attributes(sala, TETO)
    assert teto["supported_color_modes"] == ["hs"]
    assert teto["color_mode"] == "hs"
    assert teto["brightness"] == 128
    assert tuple(teto["hs_color"]) == (30.0, 50.0)
    assert teto["effect_list"] == ["rainbow", "strobe"]
    assert teto["effect"] == "rainbow"
    assert teto["supported_features"] == 44


async def test_an_on_off_light_offers_on_and_off(sala: HomeAssistant) -> None:
    await fake(sala, REAL_ABAJUR, "on", ONOFF)
    abajur = attributes(sala, ABAJUR)
    assert abajur["supported_color_modes"] == ["onoff"]
    assert abajur["color_mode"] == "onoff"
    assert abajur.get("brightness") is None
    assert abajur["supported_features"] == 0


async def test_what_it_offers_follows_the_real_light(sala: HomeAssistant) -> None:
    """A firmware update gives the lamp colour: no reload needed."""
    await fake(sala, REAL_ABAJUR, "on", ONOFF)
    assert attributes(sala, ABAJUR)["supported_color_modes"] == ["onoff"]
    await fake(sala, REAL_ABAJUR, "on", BULB)
    assert attributes(sala, ABAJUR)["supported_color_modes"] == ["hs"]
    assert attributes(sala, ABAJUR)["brightness"] == 128


# --- commands ------------------------------------------------------------------------


async def test_turning_it_on_passes_everything_on(sala: HomeAssistant) -> None:
    """With the caller's context, so the logbook names who did it."""
    context = Context()
    calls = await forwarded(sala, TETO, "turn_on",
                            {"brightness": 100, "hs_color": [200, 70], "transition": 2},
                            context, REAL_TETO)
    assert len(calls) == 1
    domain, service, data, context_id = calls[0]
    assert (domain, service, context_id) == ("light", "turn_on", context.id)
    assert data["brightness"] == 100
    assert tuple(data["hs_color"]) == (200.0, 70.0)
    assert data["transition"] == 2


async def test_turning_it_off_passes_the_transition_on(sala: HomeAssistant) -> None:
    context = Context()
    calls = await forwarded(sala, TETO, "turn_off", {"transition": 3}, context, REAL_TETO)
    assert calls == [("light", "turn_off", {"transition": 3}, context.id)]


async def test_turning_on_without_the_real_light_does_nothing(ha: HomeAssistant) -> None:
    assert await setup(ha, DEVICES)
    assert await forwarded(ha, TETO, "turn_on", {}, Context(), REAL_TETO) == []
    assert state(ha, TETO) == "unavailable"


# --- a real switch as a light ---------------------------------------------------------


@pytest.fixture
async def arandela(ha: HomeAssistant) -> HomeAssistant:
    await fake(ha, REAL_ARANDELA, "off")
    assert await setup(ha, {KEY: {"name": "Sala", "lights": {"arandela": ARANDELA_BLOCK}}})
    return ha


async def test_a_real_switch_is_a_light(arandela: HomeAssistant) -> None:
    assert held(arandela, KEY) == {ARANDELA}
    assert arandela.states.get(ARANDELA).attributes["friendly_name"] == "Sala Arandela"
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
    assert await setup(ha, {KEY: {"name": "Sala", "lights": {"arandela": ARANDELA_BLOCK}}})
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
    assert await setup(ha, {KEY: {"name": "Sala", "lights": {"arandela": ARANDELA_BLOCK}}})
    assert await forwarded(ha, ARANDELA, "turn_on", {}, Context(), REAL_ARANDELA) == []
    assert state(ha, ARANDELA) == "unavailable"


async def test_after_a_restart_it_shows_the_real_switch(ha: HomeAssistant) -> None:
    await fake(ha, REAL_ARANDELA, "on")
    await restart(ha, {KEY: {"name": "Sala", "lights": {"arandela": ARANDELA_BLOCK}}})
    assert state(ha, ARANDELA) == "on"


async def test_bulbs_and_relays_in_one_device(ha: HomeAssistant) -> None:
    await fake(ha, REAL_TETO, "on", BULB)
    await fake(ha, REAL_ARANDELA, "on")
    assert await setup(ha, {KEY: {"name": "Sala", "lights": {
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
    assert not await setup(ha, {KEY: {"name": "Sala", **blocks}})
    assert f"switches: {REAL_ARANDELA} is already in lights" in caplog.text


async def test_one_real_switch_as_a_light_and_as_a_switch_in_two_devices(
        ha: HomeAssistant) -> None:
    await fake(ha, REAL_ARANDELA, "on")
    assert await setup(ha, {
        KEY: {"name": "Sala", "lights": {"arandela": ARANDELA_BLOCK}},
        "varanda": {"name": "Varanda", "switches": {"arandela": ARANDELA_BLOCK}},
    })
    assert state(ha, ARANDELA) == "on"
    assert state(ha, "switch.pururu_varanda_switch_arandela") == "on"


# --- IDs, renames, reloads and restarts --------------------------------------------------


async def test_an_id_already_taken_is_an_error(
        ha: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    other = er.async_get(ha).async_get_or_create(
        "light", "template", "someone_else", suggested_object_id="pururu_sala_light_teto")
    assert other.entity_id == TETO
    assert await setup(ha, DEVICES)
    assert held(ha, KEY) == {ABAJUR}
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(TETO in message and "template" in message for message in errors), errors


async def test_follows_its_own_rename(sala: HomeAssistant) -> None:
    er.async_get(sala).async_update_entity(ABAJUR, new_entity_id="light.sala_luminaria")
    await sala.async_block_till_done()
    await fake(sala, REAL_ABAJUR, "on", ONOFF)
    assert state(sala, "light.sala_luminaria") == "on"
    assert held(sala, KEY) == {TETO, "light.sala_luminaria"}


@pytest.mark.parametrize(("renamed", "new_id"), [
    pytest.param(TETO, "light.teto", id="a pururu light"),
    pytest.param("switch.pururu_sala_switch_pump", "switch.bomba", id="a pururu switch"),
])
async def test_a_renamed_pururu_entity_is_not_a_real_one(
        sala: HomeAssistant, caplog: pytest.LogCaptureFixture, renamed: str, new_id: str) -> None:
    """Renamed in the UI, it no longer starts with pururu_: the registry still knows it."""
    extra = {}
    if renamed.startswith("switch."):
        extra = {"switches": {"pump": {"entity": "switch.sala_pump", "name": "Bomba"}}}
        await fake(sala, "switch.sala_pump", "off")
        await reload(sala, {KEY: {"name": "Sala", "lights": LIGHTS, **extra}})
    er.async_get(sala).async_update_entity(renamed, new_entity_id=new_id)
    await sala.async_block_till_done()
    caplog.clear()
    domain = new_id.split(".")[0]
    await reload(sala, {KEY: {"name": "Sala", **extra, "lights": {
        "teto": LIGHTS["teto"],
        "abajur": {"entity": new_id, "name": "Abajur"},
    }}})
    assert sala.states.get(ABAJUR) is None
    assert ABAJUR not in held(sala, KEY)
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(f"{new_id} is a pururu {domain}: name the real one; not creating {ABAJUR}"
               in message for message in errors), errors


async def test_reload_that_drops_a_light_removes_it(sala: HomeAssistant) -> None:
    await reload(sala, {KEY: {"name": "Sala", "lights": {"teto": LIGHTS["teto"]}}})
    assert er.async_get(sala).async_get(ABAJUR) is None
    assert sala.states.get(ABAJUR) is None
    assert held(sala, KEY) == {TETO}


async def test_after_a_restart_it_shows_the_real_light(ha: HomeAssistant) -> None:
    await fake(ha, REAL_TETO, "on", BULB)
    await fake(ha, REAL_ABAJUR, "off", ONOFF)
    await restart(ha, DEVICES)
    assert state(ha, TETO) == "on"
    assert attributes(ha, TETO)["brightness"] == 128
    assert state(ha, ABAJUR) == "off"
