"""Characterizes today's meters: entity IDs, translated names and icons, and refusals.

Six builders build per-period `Meter` entities through the statistics aspect
(aspects/statistics.py): appliance, door, window, modes, programs, reactions.
This file pins what each shows today - the full list of IDs, a few names in
`en` and `pt-BR`, a few icons, and the schema's refusal texts - so a change to
the aspect can't move any of them unnoticed.
"""

from collections.abc import AsyncIterator
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
import pytest

from helpers import generated_scripts, setup

INTEGRATION = Path(__file__).resolve().parents[1] / "custom_components/pururu"
ICONS = json.loads((INTEGRATION / "icons.json").read_text())

# Every period a feature's statistics can ask for
PERIODS = ("today", "week", "month", "year")


def icon_of(hass: HomeAssistant, entity_id: str) -> str:
    """The icon icons.json gives the entity's translation key: what the UI shows for it."""
    entry = er.async_get(hass).async_get(entity_id)
    assert entry is not None, entity_id
    platform = entity_id.split(".", 1)[0]
    # HA puts no translated icon in the state: resolve to the *icon*, not just the key,
    # so pinning what's shown survives Task 2 renaming the translation keys.
    return str(ICONS["entity"][platform][entry.translation_key]["default"])


def assert_meter(hass: HomeAssistant, entity_id: str) -> None:
    """The meter exists, and its unique ID is the pururu pattern (entity ID without its platform)."""
    assert hass.states.get(entity_id) is not None, entity_id
    entry = er.async_get(hass).async_get(entity_id)
    assert entry is not None, entity_id
    assert entry.unique_id == entity_id.split(".", 1)[1]


def friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return str(state.attributes["friendly_name"])


# --- appliance -----------------------------------------------------------------------

APPLIANCE_KEY = "demo_washer"
APPLIANCE_NAME = "Demo washer"
APPLIANCE_COUNTERS = ("runtime", "cycles", "idle_energy")
APPLIANCE_ICONS = {
    "runtime_today": "mdi:timer-sand",
    "cycles_week": "mdi:counter",
    "idle_energy_month": "mdi:power-sleep",
}
APPLIANCE_NAMES = {
    "en": {
        "runtime_today": "Runtime today",
        "cycles_week": "Cycles this week",
        "idle_energy_month": "Idle energy this month",
    },
    "pt-BR": {
        "runtime_today": "Tempo ligado hoje",
        "cycles_week": "Ciclos na semana",
        "idle_energy_month": "Energia parado no mês",
    },
}


def appliance_sensor(suffix: str) -> str:
    return f"sensor.pururu_{APPLIANCE_KEY}_appliance_{suffix}"


@pytest.mark.parametrize("language", ["en", "pt-BR"])
async def test_appliance_meters(ha: HomeAssistant, language: str) -> None:
    ha.config.language = language
    block = {
        "power": "sensor.demo_plug_power",
        "energy": "sensor.demo_plug_energy",
        "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
        "statistics": {counter: list(PERIODS) for counter in APPLIANCE_COUNTERS},
    }
    assert await setup(ha, {APPLIANCE_KEY: {"name": APPLIANCE_NAME, "appliance": block}})
    for counter in APPLIANCE_COUNTERS:
        for period in PERIODS:
            assert_meter(ha, appliance_sensor(f"{counter}_{period}"))
    for suffix, icon in APPLIANCE_ICONS.items():
        assert icon_of(ha, appliance_sensor(suffix)) == icon
    for suffix, expected in APPLIANCE_NAMES[language].items():
        assert friendly_name(ha, appliance_sensor(suffix)) == f"{APPLIANCE_NAME} {expected}"


# --- door and window -------------------------------------------------------------------

OPENING_KEY = "clausura_frente"
OPENING_NAME = "Clausura frente"
OPENING_CONTACT = "binary_sensor.clausura_frente"
OPENING_COUNTERS = ("openings", "open_time")
OPENING_ICONS = {"openings_today": "mdi:counter", "open_time_week": "mdi:timer-sand"}
OPENING_NAMES = {
    "en": {"openings_today": "Openings today", "open_time_week": "Time open this week"},
    "pt-BR": {"openings_today": "Aberturas hoje", "open_time_week": "Tempo aberta na semana"},
}


@pytest.fixture(params=["door", "window"])
def kind(request: pytest.FixtureRequest) -> str:
    """Both features: one code, two namespaces."""
    return str(request.param)


def opening_sensor(kind: str, suffix: str) -> str:
    return f"sensor.pururu_{OPENING_KEY}_{kind}_{suffix}"


@pytest.mark.parametrize("language", ["en", "pt-BR"])
async def test_opening_meters(ha: HomeAssistant, kind: str, language: str) -> None:
    ha.config.language = language
    block = {
        "contact": OPENING_CONTACT,
        "statistics": {counter: list(PERIODS) for counter in OPENING_COUNTERS},
    }
    assert await setup(ha, {OPENING_KEY: {"name": OPENING_NAME, kind: block}})
    for counter in OPENING_COUNTERS:
        for period in PERIODS:
            assert_meter(ha, opening_sensor(kind, f"{counter}_{period}"))
    for suffix, icon in OPENING_ICONS.items():
        assert icon_of(ha, opening_sensor(kind, suffix)) == icon
    for suffix, expected in OPENING_NAMES[language].items():
        assert friendly_name(ha, opening_sensor(kind, suffix)) == f"{OPENING_NAME} {expected}"


# --- modes -----------------------------------------------------------------------------

MODE_KEY = "demo_filter"
MODE_NAME = "Demo filter"
MODE_SLUG = "quente"
MODE_ITEM_NAME = "Água quente"
MODE_COUNTERS = ("runtime", "cycles", "energy")
MODE_ICONS = {
    "runtime_today": "mdi:timer-sand",
    "cycles_week": "mdi:counter",
    "energy_month": "mdi:lightning-bolt",
}
MODE_NAMES = {
    "en": {
        "runtime_today": f"{MODE_ITEM_NAME} runtime today",
        "cycles_week": f"{MODE_ITEM_NAME} cycles this week",
        "energy_month": f"{MODE_ITEM_NAME} energy this month",
    },
    "pt-BR": {
        "runtime_today": f"Tempo de {MODE_ITEM_NAME} hoje",
        "cycles_week": f"Ciclos de {MODE_ITEM_NAME} na semana",
        "energy_month": f"Energia de {MODE_ITEM_NAME} no mês",
    },
}


def mode_sensor(suffix: str) -> str:
    return f"sensor.pururu_{MODE_KEY}_mode_{MODE_SLUG}_{suffix}"


@pytest.mark.parametrize("language", ["en", "pt-BR"])
async def test_modes_meters(ha: HomeAssistant, language: str) -> None:
    ha.config.language = language
    power = "sensor.demo_plug_power"
    devices: dict[str, Any] = {
        MODE_KEY: {
            "name": MODE_NAME,
            "appliance": {
                "power": power,
                "running": {"threshold": 4, "on_delay": {"seconds": 20}, "off_delay": {"minutes": 2}},
            },
            "modes": {
                "cycle_from": "appliance",
                "sensor": power,
                "energy": "sensor.demo_plug_energy",
                "modes": {
                    MODE_SLUG: {
                        "name": MODE_ITEM_NAME,
                        "above": 300,
                        "on_delay": {"seconds": 10},
                        "off_delay": {"seconds": 30},
                    }
                },
                "statistics": {counter: list(PERIODS) for counter in MODE_COUNTERS},
            },
        }
    }
    assert await setup(ha, devices)
    for counter in MODE_COUNTERS:
        for period in PERIODS:
            assert_meter(ha, mode_sensor(f"{counter}_{period}"))
    for suffix, icon in MODE_ICONS.items():
        assert icon_of(ha, mode_sensor(suffix)) == icon
    for suffix, expected in MODE_NAMES[language].items():
        assert friendly_name(ha, mode_sensor(suffix)) == f"{MODE_NAME} {expected}"


# --- programs --------------------------------------------------------------------------

PROGRAM_KEY = "pool"
PROGRAM_NAME = "Piscina"
PROGRAM_SLUG = "clean"
PROGRAM_ITEM_NAME = "Limpar"
PROGRAM_COUNTERS = ("runtime", "cycles")
PROGRAM_ICONS = {"runtime_today": "mdi:timer-sand", "cycles_week": "mdi:counter"}
PROGRAM_NAMES = {
    "en": {
        "runtime_today": f"{PROGRAM_ITEM_NAME} runtime today",
        "cycles_week": f"{PROGRAM_ITEM_NAME} cycles this week",
    },
    "pt-BR": {
        "runtime_today": f"Tempo de {PROGRAM_ITEM_NAME} hoje",
        "cycles_week": f"Ciclos de {PROGRAM_ITEM_NAME} na semana",
    },
}


def program_sensor(suffix: str) -> str:
    return f"sensor.pururu_{PROGRAM_KEY}_program_{PROGRAM_SLUG}_{suffix}"


@pytest.fixture
async def scripts(ha: HomeAssistant) -> AsyncIterator[HomeAssistant]:
    """HA's scripts, from a configuration.yaml that includes pururu's file (empty at first)."""
    with patch(
        "homeassistant.config.load_yaml_config_file",
        side_effect=lambda *_args, **_kwargs: {"script pururu": generated_scripts(ha)},
    ):
        assert await async_setup_component(ha, "script", {"script pururu": generated_scripts(ha)})
        yield ha


@pytest.mark.parametrize("language", ["en", "pt-BR"])
async def test_programs_meters(scripts: HomeAssistant, language: str) -> None:
    scripts.config.language = language
    devices: dict[str, Any] = {
        PROGRAM_KEY: {
            "name": PROGRAM_NAME,
            "switches": {"pump": {"entity": "switch.pool_pump", "name": "Bomba"}},
            "programs": {
                PROGRAM_SLUG: {
                    "name": PROGRAM_ITEM_NAME,
                    "sequence": [{"turn_on": "switch_pump"}],
                    "statistics": {counter: list(PERIODS) for counter in PROGRAM_COUNTERS},
                }
            },
        }
    }
    assert await setup(scripts, devices)
    for counter in PROGRAM_COUNTERS:
        for period in PERIODS:
            assert_meter(scripts, program_sensor(f"{counter}_{period}"))
    for suffix, icon in PROGRAM_ICONS.items():
        assert icon_of(scripts, program_sensor(suffix)) == icon
    for suffix, expected in PROGRAM_NAMES[language].items():
        assert friendly_name(scripts, program_sensor(suffix)) == f"{PROGRAM_NAME} {expected}"


# --- reactions -------------------------------------------------------------------------

REACTION_KEY = "lights"
REACTION_NAME = "Luzes"
REACTION_SLUG = "trigger"
REACTION_ITEM_NAME = "Aviso"
REACTION_ICON = "mdi:gesture-tap"
REACTION_NAMES = {
    "en": {
        "triggered_today": f"{REACTION_ITEM_NAME} triggers today",
        "triggered_week": f"{REACTION_ITEM_NAME} triggers this week",
    },
    "pt-BR": {
        "triggered_today": f"Disparos de {REACTION_ITEM_NAME} hoje",
        "triggered_week": f"Disparos de {REACTION_ITEM_NAME} na semana",
    },
}


def reaction_sensor(suffix: str) -> str:
    return f"sensor.pururu_{REACTION_KEY}_reaction_{REACTION_SLUG}_{suffix}"


@pytest.mark.parametrize("language", ["en", "pt-BR"])
async def test_reactions_meters(ha: HomeAssistant, language: str) -> None:
    ha.config.language = language
    devices: dict[str, Any] = {
        REACTION_KEY: {
            "name": REACTION_NAME,
            "lights": {"teto": {"entity": "light.demo_teto", "name": "Teto"}},
            "reactions": {
                REACTION_SLUG: {
                    "name": REACTION_ITEM_NAME,
                    "entity": "binary_sensor.demo_door",
                    "to": "on",
                    "statistics": {"triggered": list(PERIODS)},
                }
            },
        }
    }
    assert await setup(ha, devices)
    for period in PERIODS:
        assert_meter(ha, reaction_sensor(f"triggered_{period}"))
    assert icon_of(ha, reaction_sensor("triggered_today")) == REACTION_ICON
    for suffix, expected in REACTION_NAMES[language].items():
        assert friendly_name(ha, reaction_sensor(suffix)) == f"{REACTION_NAME} {expected}"


# --- refusals ----------------------------------------------------------------------------

APPLIANCE_MINIMAL = {
    "power": "sensor.demo_plug_power",
    "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}
MODES_MINIMAL = {
    "cycle_from": "appliance",
    "sensor": "sensor.demo_plug_power",
    "modes": {
        MODE_SLUG: {
            "name": MODE_ITEM_NAME,
            "above": 300,
            "on_delay": {"seconds": 10},
            "off_delay": {"seconds": 30},
        }
    },
}


async def test_idle_energy_without_energy_is_refused(
    ha: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    block = {**APPLIANCE_MINIMAL, "statistics": {"idle_energy": ["today"]}}
    assert not await setup(ha, {APPLIANCE_KEY: {"name": APPLIANCE_NAME, "appliance": block}})
    assert "statistics.idle_energy needs energy" in caplog.text


async def test_mode_energy_without_energy_is_refused(
    ha: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    devices = {
        MODE_KEY: {
            "name": MODE_NAME,
            "appliance": APPLIANCE_MINIMAL,
            "modes": {**MODES_MINIMAL, "statistics": {"energy": ["today"]}},
        }
    }
    assert not await setup(ha, devices)
    assert "statistics.energy needs energy" in caplog.text


async def test_a_repeated_period_is_refused(
    ha: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    block = {**APPLIANCE_MINIMAL, "statistics": {"cycles": ["today", "today"]}}
    assert not await setup(ha, {APPLIANCE_KEY: {"name": APPLIANCE_NAME, "appliance": block}})
    # Verbatim up to the colon (pururu's words); the repeated period after it,
    # not the exact list-vs-tuple formatting of what follows.
    assert "a period is repeated:" in caplog.text
    assert "today" in caplog.text


async def test_an_unknown_period_is_refused(ha: HomeAssistant) -> None:
    block = {**APPLIANCE_MINIMAL, "statistics": {"cycles": ["daily"]}}
    assert not await setup(ha, {APPLIANCE_KEY: {"name": APPLIANCE_NAME, "appliance": block}})


async def test_an_unknown_counter_is_refused(ha: HomeAssistant) -> None:
    block = {**APPLIANCE_MINIMAL, "statistics": {"closings": ["today"]}}
    assert not await setup(ha, {APPLIANCE_KEY: {"name": APPLIANCE_NAME, "appliance": block}})


async def test_no_period_for_energy_without_energy_passes(ha: HomeAssistant) -> None:
    devices = {
        MODE_KEY: {
            "name": MODE_NAME,
            "appliance": APPLIANCE_MINIMAL,
            "modes": {**MODES_MINIMAL, "statistics": {"energy": []}},
        }
    }
    assert await setup(ha, devices)
