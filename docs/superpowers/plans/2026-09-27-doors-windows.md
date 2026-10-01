# Doors and windows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two features, `door` and `window`: a contact sensor opens and closes them, each opening is a cycle (last opening, totals, per-period meters), and optional `event.*` entities, mapped by the user, say who opened, how and which way, and record denied attempts and rings.

**Architecture:** One package, `features/opening/`, builds both features with one function (`_opening(namespace, device_class)`). `open.py` is the `open` binary sensor: it follows the contact, sends each finished opening as a `Cycle` on `features/cycle/`'s signals (so `LastCycleValue`, `CyclesTotal`, `RuntimeTotal` and `Meter` are reused), and matches `opening` events to openings by time. `events.py` holds the event vocabulary, the schema of an event, reading an event entity's change, and the entities events give (the last opening's fields, the last denied attempt, the last ring).

**Tech Stack:** Python 3.13, Home Assistant 2026.9.3 (`pytest-homeassistant-custom-component`), voluptuous, pytest with freezer, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-27-doors-windows-design.md`

## Global Constraints

- Entity IDs: `<platform>.pururu_<device key>_<namespace>_<entity key>`, namespaces `door` and `window`: `binary_sensor.pururu_cercado_frente_door_open`.
- Entity keys (both namespaces): `open` (binary_sensor); sensors `last_opened`, `last_closed`, `last_open_duration`, `openings_total`, `open_time_total`, `openings_<period>`, `open_time_<period>` (periods `today`, `week`, `month`, `year`), `last_opened_by`, `last_opened_via`, `last_direction`, `last_denied`, `last_ring`.
- `open`'s device class is `door` for `door`, `window` for `window`, whatever the contact's.
- `last_open_duration` is in seconds (`UnitOfTime.SECONDS`), a whole number.
- Meanings: `opening`, `denied`, `ring`. Fields: `who` → `last_opened_by`, `how` → `last_opened_via`, `direction` → `last_direction`.
- `match` defaults to 5 seconds.
- Log message, quoted by the docs: `<contact> is a pururu binary sensor: name the real contact; <open entity ID> stands for nothing`.
- Schema message for a pururu contact (from `standing.real_entity`): `<contact> is a pururu binary_sensor: name the real one`; for another domain: `<contact> is not a binary_sensor`.
- Version `0.1.12` in `custom_components/pururu/manifest.json`.
- Run commands from the repo root with `uv`. One file: `uv run pytest tests/test_opening.py -n 0 -q`. Everything (tests, ruff, ruff format, mypy strict, hassfest): `uv run pytest`.
- Tests are not linted; `custom_components/pururu` is (ruff, mypy strict with core's settings).
- Never leave the shell's cwd inside `.venv/.../homeassistant/helpers/`.

## Review Focus

- An event entity whose state isn't a time (a broken integration writes `garbage`): ignored, never a crash. Test in Task 2 (`test_a_state_that_is_not_a_time_is_ignored`).
- An attribute that isn't text (`actor: 42`): shown as `"42"`. Test in Task 2 (`test_a_field_that_is_not_text_is_text`).
- A door opened again within seconds of closing, with one event for the first opening: the second is not described by it. Test in Task 2 (`test_a_quick_reopening_without_event_is_unknown`).
- A contact already open when pururu is first set up: an opening starts then, and closing counts it. Test in Task 1 (`test_a_contact_open_at_set_up_is_an_opening`).
- A doorbell ring during an opening: it records `last_ring` and never describes the opening. Test in Task 2 (`test_a_ring_never_describes_an_opening`).

---

### Task 1: `door` and `window` from the contact

**Files:**
- Modify: `custom_components/pururu/features/cycle/totals.py` (`CyclesTotal.__init__`, `RuntimeTotal.__init__`)
- Create: `custom_components/pururu/features/opening/__init__.py`
- Create: `custom_components/pururu/features/opening/open.py`
- Modify: `custom_components/pururu/features/__init__.py`
- Modify: `custom_components/pururu/translations/en.json`, `custom_components/pururu/translations/pt-BR.json`, `custom_components/pururu/icons.json`
- Test: `tests/test_opening.py` (create)

**Interfaces:**
- Consumes: `features/cycle`: `Cycle`, `CycleStart`, `cycle_signal(device)`, `end_signal(device)`; `features/cycle/last.py`: `LastCycleDescription`, `LastCycleValue(device, description, *, source)`; `features/cycle/statistics.py`: `PERIOD_LIST`, `PERIODS`, `Meter(device, entity_key, total, source, period)`; `features/standing.py`: `real_entity(*domains)`, `is_pururu(hass, entity_id)`; `feature.py`: `Build`, `Device`, `Feature`.
- Produces:
  - `CyclesTotal(device, *, source, item=None, entity_key="cycles_total")`, `RuntimeTotal(device, watched, state, *, source, item=None, entity_key="runtime_total")`.
  - `features/opening/open.py`: `class Open(PururuEntity, BinarySensorEntity, RestoreEntity)`, `Open(device, device_class, *, contact: str | None)`, its method `_opening_starts(now: datetime) -> None` (a no-op here; Task 2 fills it).
  - `features/opening/__init__.py`: `DOOR: Feature`, `WINDOW: Feature`, `SCHEMA`, `ENTITY_KEYS: dict[str, Platform]`, `LAST_OPENING`, `COUNTERS = ("openings", "open_time")`, `_opening(namespace, device_class) -> Feature`, `_builder(device_class) -> Build`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_opening.py`:

```python
"""Features `door` and `window`: an enclosure's two doors and an access controller's events."""

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest

from helpers import fake, held, reload, restart, setup, tick

KEY = "cercado_frente"
NAME = "Cercado frente"
CONTACT = "binary_sensor.cercado_frente"


@pytest.fixture(params=["door", "window"])
def kind(request: pytest.FixtureRequest) -> str:
    """Both features: one code, two namespaces."""
    return str(request.param)


def devices(kind: str, **block: Any) -> dict[str, Any]:
    return {KEY: {"name": NAME, kind: {"contact": CONTACT, **block}}}


def entity(kind: str, entity_key: str, platform: str = "sensor") -> str:
    return f"{platform}.pururu_{KEY}_{kind}_{entity_key}"


def opened(hass: HomeAssistant, kind: str) -> str:
    return hass.states.get(entity(kind, "open", "binary_sensor")).state


def value(hass: HomeAssistant, kind: str, entity_key: str) -> str:
    return hass.states.get(entity(kind, entity_key)).state


def seconds_from(hass: HomeAssistant, kind: str, entity_key: str) -> float:
    """How far a timestamp sensor is from now, in seconds."""
    moment = dt_util.parse_datetime(value(hass, kind, entity_key))
    assert moment is not None
    return abs((moment - dt_util.utcnow()).total_seconds())


async def contact(hass: HomeAssistant, state: str) -> None:
    await fake(hass, CONTACT, state, {"device_class": "door"})


async def opening(hass: HomeAssistant, freezer: Any, seconds: float) -> None:
    """The contact open for `seconds`, then closed."""
    await contact(hass, "on")
    await tick(hass, freezer, seconds)
    await contact(hass, "off")


@pytest.fixture
async def door(ha: HomeAssistant, kind: str) -> HomeAssistant:
    """A closed door (or window) with no extras."""
    await contact(ha, "off")
    assert await setup(ha, devices(kind))
    return ha


# --- schema ----------------------------------------------------------------------


@pytest.mark.parametrize("block", [
    pytest.param({}, id="no contact"),
    pytest.param({"contact": "sensor.cercado_frente"}, id="not a binary sensor"),
    pytest.param({"contact": "binary_sensor.pururu_outra_door_open"}, id="a pururu binary sensor"),
    pytest.param({"contact": CONTACT, "statistics": {"openings": ["today", "today"]}},
                 id="repeated period"),
    pytest.param({"contact": CONTACT, "statistics": {"open_time": ["daily"]}}, id="unknown period"),
    pytest.param({"contact": CONTACT, "statistics": {"closings": ["today"]}},
                 id="unknown counter"),
    pytest.param({"contact": CONTACT, "sensor": CONTACT}, id="unknown key"),
])
async def test_invalid_block_is_refused(ha: HomeAssistant, kind: str,
                                        block: dict[str, Any]) -> None:
    assert not await setup(ha, {KEY: {"name": NAME, kind: block}})


@pytest.mark.parametrize(("contact_id", "message"), [
    pytest.param("sensor.cercado_frente", "sensor.cercado_frente is not a binary_sensor",
                 id="another domain"),
    pytest.param("binary_sensor.pururu_outra_door_open",
                 "binary_sensor.pururu_outra_door_open is a pururu binary_sensor: name the real one",
                 id="a pururu binary sensor"),
])
async def test_the_error_names_what_is_wrong(ha: HomeAssistant, kind: str,
                                             caplog: pytest.LogCaptureFixture,
                                             contact_id: str, message: str) -> None:
    """The messages the docs quote (troubleshooting)."""
    assert not await setup(ha, {KEY: {"name": NAME, kind: {"contact": contact_id}}})
    assert message in caplog.text


async def test_a_door_and_a_window_in_one_device(ha: HomeAssistant) -> None:
    """Their IDs differ by namespace."""
    assert await setup(ha, {KEY: {"name": NAME, "door": {"contact": CONTACT},
                                  "window": {"contact": "binary_sensor.janela"}}})
    assert ha.states.get(entity("door", "open", "binary_sensor")) is not None
    assert ha.states.get(entity("window", "open", "binary_sensor")) is not None


# --- open --------------------------------------------------------------------------


async def test_follows_the_contact(door: HomeAssistant, kind: str) -> None:
    assert opened(door, kind) == "off"
    await contact(door, "on")
    assert opened(door, kind) == "on"
    await contact(door, "off")
    assert opened(door, kind) == "off"


async def test_the_device_class_is_the_feature_s(door: HomeAssistant, kind: str) -> None:
    """A contact of class `opening` still gives a door (a window)."""
    await fake(door, CONTACT, "on", {"device_class": "opening"})
    state = door.states.get(entity(kind, "open", "binary_sensor"))
    assert state.attributes["device_class"] == kind


@pytest.mark.parametrize("gone", ["unavailable", "unknown"])
async def test_holds_while_the_contact_has_no_state(door: HomeAssistant, kind: str,
                                                    freezer: Any, gone: str) -> None:
    await contact(door, "on")
    await fake(door, CONTACT, gone)
    await tick(door, freezer, 600)
    assert opened(door, kind) == "on"
    await contact(door, "off")
    assert opened(door, kind) == "off"
    assert value(door, kind, "openings_total") == "1"


async def test_a_contact_open_at_set_up_is_an_opening(ha: HomeAssistant, kind: str,
                                                     freezer: Any) -> None:
    await contact(ha, "on")
    assert await setup(ha, devices(kind))
    assert opened(ha, kind) == "on"
    await tick(ha, freezer, 4)
    await contact(ha, "off")
    assert value(ha, kind, "openings_total") == "1"
    assert float(value(ha, kind, "last_open_duration")) == 4


async def test_the_device_holds_the_door(door: HomeAssistant, kind: str) -> None:
    assert {entity(kind, "open", "binary_sensor"), entity(kind, "last_opened"),
            entity(kind, "last_closed"), entity(kind, "last_open_duration"),
            entity(kind, "openings_total"), entity(kind, "open_time_total")} <= held(door, KEY)


async def test_without_statistics_there_are_no_meters(door: HomeAssistant, kind: str) -> None:
    for counter in ("openings", "open_time"):
        assert door.states.get(entity(kind, f"{counter}_today")) is None


async def test_names_come_from_the_translations(door: HomeAssistant, kind: str) -> None:
    state = door.states.get(entity(kind, "open", "binary_sensor"))
    assert state.attributes["friendly_name"] == f"{NAME} Open"
    total = door.states.get(entity(kind, "openings_total"))
    assert total.attributes["friendly_name"] == f"{NAME} Openings"
    assert total.attributes["unit_of_measurement"] == "openings"


async def test_names_in_portuguese(ha: HomeAssistant, kind: str) -> None:
    ha.config.language = "pt-BR"
    assert await setup(ha, devices(kind))
    state = ha.states.get(entity(kind, "open", "binary_sensor"))
    assert state.attributes["friendly_name"] == f"{NAME} Aberta"
    total = ha.states.get(entity(kind, "openings_total"))
    assert total.attributes["friendly_name"] == f"{NAME} Aberturas"
    assert total.attributes["unit_of_measurement"] == "aberturas"


# --- the last opening and the totals ------------------------------------------------


async def test_before_the_first_opening_everything_is_unknown(door: HomeAssistant,
                                                              kind: str) -> None:
    for entity_key in ("last_opened", "last_closed", "last_open_duration"):
        assert value(door, kind, entity_key) == "unknown", entity_key
    assert value(door, kind, "openings_total") == "0"


async def test_an_opening_is_recorded(door: HomeAssistant, kind: str, freezer: Any) -> None:
    """Entry by the front door: open for about 6 s."""
    await opening(door, freezer, 6)
    assert seconds_from(door, kind, "last_opened") == pytest.approx(6, abs=1)
    assert seconds_from(door, kind, "last_closed") < 1
    assert float(value(door, kind, "last_open_duration")) == 6
    assert door.states.get(entity(kind, "last_open_duration")).attributes[
        "unit_of_measurement"] == "s"
    assert value(door, kind, "openings_total") == "1"


async def test_open_time_adds_the_time_open(door: HomeAssistant, kind: str,
                                            freezer: Any) -> None:
    await opening(door, freezer, 6)
    await tick(door, freezer, 60)
    await opening(door, freezer, 54)
    assert float(value(door, kind, "open_time_total")) == pytest.approx(60 / 3600, abs=1e-3)
    assert value(door, kind, "openings_total") == "2"


async def test_meters_count_their_totals(ha: HomeAssistant, kind: str, freezer: Any) -> None:
    await contact(ha, "off")
    assert await setup(ha, devices(kind, statistics={"openings": ["today"],
                                                     "open_time": ["today"]}))
    await opening(ha, freezer, 6)
    await tick(ha, freezer, 60)
    await opening(ha, freezer, 54)
    await tick(ha, freezer, 60)
    assert float(value(ha, kind, "openings_today")) == 2
    assert float(value(ha, kind, "open_time_today")) == pytest.approx(
        float(value(ha, kind, "open_time_total")), abs=1e-3)
    assert ha.states.get(entity(kind, "openings_week")) is None


# --- restarts and reloads -------------------------------------------------------------


def saved_open(kind: str, seconds_ago: float) -> tuple[State, dict[str, Any]]:
    """`open` as .storage holds it, open since `seconds_ago`."""
    since = (dt_util.utcnow() - timedelta(seconds=seconds_ago)).isoformat()
    return (State(entity(kind, "open", "binary_sensor"), "on"),
            {"since": since, "since_energy": None})


async def test_restart_with_the_contact_closed_ends_the_opening(ha: HomeAssistant,
                                                                kind: str) -> None:
    """Saved open 30 s ago; the contact is closed once HA has started."""
    ha.states.async_set(CONTACT, "off")
    await restart(ha, devices(kind), saved_open(kind, 30))
    assert opened(ha, kind) == "off"
    assert value(ha, kind, "openings_total") == "1"
    assert float(value(ha, kind, "last_open_duration")) == 30


async def test_restart_with_the_contact_open_keeps_the_opening(ha: HomeAssistant, kind: str,
                                                               freezer: Any) -> None:
    ha.states.async_set(CONTACT, "on")
    await restart(ha, devices(kind), saved_open(kind, 30))
    assert opened(ha, kind) == "on"
    await tick(ha, freezer, 10)
    await contact(ha, "off")
    assert value(ha, kind, "openings_total") == "1"
    assert float(value(ha, kind, "last_open_duration")) == 40


async def test_restart_before_the_contact_has_a_state_holds(ha: HomeAssistant, kind: str,
                                                            freezer: Any) -> None:
    await restart(ha, devices(kind), saved_open(kind, 30))
    assert opened(ha, kind) == "on"
    await tick(ha, freezer, 5)
    await contact(ha, "off")
    assert float(value(ha, kind, "last_open_duration")) == 35


async def test_reload_mid_opening_counts_one(door: HomeAssistant, kind: str,
                                             freezer: Any) -> None:
    await contact(door, "on")
    await tick(door, freezer, 10)
    await reload(door, devices(kind))
    await tick(door, freezer, 10)
    assert opened(door, kind) == "on"
    await contact(door, "off")
    assert value(door, kind, "openings_total") == "1"
    assert float(value(door, kind, "last_open_duration")) == 20


async def test_the_last_opening_restores(ha: HomeAssistant, kind: str) -> None:
    await restart(ha, devices(kind),
                  (State(entity(kind, "last_open_duration"), "7"),
                   {"native_value": 7, "native_unit_of_measurement": "s"}),
                  (State(entity(kind, "openings_total"), "12"),
                   {"native_value": 12, "native_unit_of_measurement": None}))
    assert float(value(ha, kind, "last_open_duration")) == 7
    assert value(ha, kind, "openings_total") == "12"


# --- a pururu contact, and what builds on the door -----------------------------------

WASHER = {"name": "Lavadora", "appliance": {
    "power": "sensor.lavadora_power",
    "running": {"threshold": 4, "on_delay": {"minutes": 1}, "off_delay": {"minutes": 2}},
}}


async def test_a_renamed_pururu_contact_stands_for_nothing(
        ha: HomeAssistant, kind: str, caplog: pytest.LogCaptureFixture) -> None:
    """Renamed in the UI, a pururu binary sensor gets past the schema: the registry knows it."""
    config = {"lavadora": WASHER,
              KEY: {"name": NAME, kind: {"contact": "binary_sensor.lavadora_rodando"}}}
    assert await setup(ha, config)
    er.async_get(ha).async_update_entity("binary_sensor.pururu_lavadora_appliance_running",
                                         new_entity_id="binary_sensor.lavadora_rodando")
    await ha.async_block_till_done()
    caplog.clear()
    await reload(ha, config)
    assert opened(ha, kind) == "unavailable"
    assert value(ha, kind, "openings_total") == "0"
    assert ("binary_sensor.lavadora_rodando is a pururu binary sensor: name the real contact; "
            f"{entity(kind, 'open', 'binary_sensor')} stands for nothing") in caplog.text


async def test_the_openings_are_a_cycle_for_phases(ha: HomeAssistant, kind: str) -> None:
    """`cycle_from: door` (window): a phase runs while it's open."""
    await contact(ha, "off")
    phases = {"cycle_from": kind, "sensor": "sensor.vento",
              "defaults": {"stopped": "parada", "running": "aberta"},
              "bands": {"ventania": {"above": 50}}}
    assert await setup(ha, {KEY: {"name": NAME, kind: {"contact": CONTACT}, "phases": phases}})
    await fake(ha, "sensor.vento", "10")
    phase = f"sensor.pururu_{KEY}_phase_current"
    assert ha.states.get(phase).state == "parada"
    await contact(ha, "on")
    assert ha.states.get(phase).state == "aberta"
    await contact(ha, "off")
    assert ha.states.get(phase).state == "parada"
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_opening.py -n 0 -q`
Expected: FAIL. Setups with `door:`/`window:` are refused (`extra keys not allowed @ data['pururu']['devices']['cercado_frente']['door']`), so most tests fail on `assert await setup(...)` or on a missing state. The schema tests may pass already, since an unknown feature key is refused too.

- [ ] **Step 3: Let the totals take an entity key**

In `custom_components/pururu/features/cycle/totals.py`, replace `CyclesTotal.__init__` with:

```python
    def __init__(
        self,
        device: Device,
        *,
        source: str,
        item: Item | None = None,
        entity_key: str = "cycles_total",
    ) -> None:
        """Count the cycles (of `item`) that `source` sends, as `entity_key` (a door's openings)."""
        self.sources = (source,)
        self._identify(device, Platform.SENSOR, entity_key, item=item)
        self._signal = cycle_signal(device, item)
        self._cycles = 0
```

and `RuntimeTotal.__init__` with:

```python
    def __init__(
        self,
        device: Device,
        watched: str,
        state: str,
        *,
        source: str,
        item: Item | None = None,
        entity_key: str = "runtime_total",
    ) -> None:
        """Add up the time `watched`, the entity of `source`, is in `state`, as `entity_key`."""
        self.sources = (source,)
        self._identify(device, Platform.SENSOR, entity_key, item=item)
        self._watched = watched
        self._state = state
        self._hours = 0.0
        # Up to when the time in the state is already added; None while not in it
        self._counted_until: datetime | None = None
```

- [ ] **Step 4: Write `open.py`**

Create `custom_components/pururu/features/opening/open.py`:

```python
"""Whether the door is open: its contact, held while the contact has no state; the source of its openings."""

from datetime import datetime
from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import STATE_OFF, STATE_ON, Platform
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from ...entity import PururuEntity
from ...feature import Device
from ..cycle import Cycle, CycleStart, cycle_signal, end_signal


class Open(PururuEntity, BinarySensorEntity, RestoreEntity):
    """On while the contact is open; holds while it has no state. Each opening is a cycle."""

    def __init__(
        self,
        device: Device,
        device_class: BinarySensorDeviceClass,
        *,
        contact: str | None,
    ) -> None:
        """Follow `contact`; None: stand for nothing, unavailable."""
        self._identify(device, Platform.BINARY_SENSOR, "open")
        self._attr_device_class = device_class
        self._attr_available = contact is not None
        self._attr_is_on = False
        self._contact = contact
        self._signals = (cycle_signal(device), end_signal(device))
        self._data = CycleStart()
        # False until HA has started: every entity of the door listens by then
        self._following = False

    @property
    @override
    def extra_restore_state_data(self) -> CycleStart:
        """The current opening's start."""
        return self._data

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the state and the opening; follow the contact once HA has started.

        Nothing opens or closes before: the door's other entities may not listen
        yet. Once HA has started, a restored opening whose contact is closed ends.
        """
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == STATE_ON
        if (extra := await self.async_get_last_extra_data()) is not None:
            self._data = CycleStart.from_dict(extra.as_dict())
        if self._contact is None:
            return
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._contact, self._contact_changed
            )
        )
        self.async_on_remove(async_at_started(self.hass, self._started))

    @callback
    def _started(self, _hass: HomeAssistant) -> None:
        """Every entity of the door listens now: follow the contact as it is."""
        self._following = True
        if self._contact is not None:
            self._follow(self.hass.states.get(self._contact))

    @callback
    def _contact_changed(self, event: Event[EventStateChangedData]) -> None:
        if self._following:
            self._follow(event.data["new_state"])

    @callback
    def _follow(self, state: State | None) -> None:
        """Open or close as the contact says; hold while it says neither."""
        if state is None or state.state not in (STATE_ON, STATE_OFF):
            return
        is_open = state.state == STATE_ON
        if is_open == self._attr_is_on:
            return
        now = dt_util.utcnow()
        self._attr_is_on = is_open
        if is_open:
            self._data = CycleStart(since=now)
            self.async_write_ha_state()
            self._opening_starts(now)
            return
        cycle = Cycle(start=self._data.since, end=now, energy_kwh=None)
        self._data = CycleStart()
        self.async_write_ha_state()
        for signal in self._signals:  # the end's own signal last
            async_dispatcher_send(self.hass, signal, cycle)

    @callback
    def _opening_starts(self, now: datetime) -> None:
        """An opening starts at `now`: nothing describes it yet."""
```

- [ ] **Step 5: Write the feature**

Create `custom_components/pururu/features/opening/__init__.py`:

```python
"""A door or a window: its contact opens and closes it, and each opening is a cycle.

`door` and `window` are one feature under two namespaces: they differ only in
their `open`'s device class and their texts. The contact is required; what
describes the openings (events.py) is optional.
"""

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import STATE_ON, Platform, UnitOfTime
from homeassistant.core import HomeAssistant

from ...entity import PururuEntity
from ...feature import Build, Device, Feature
from .. import standing
from ..cycle.last import LastCycleDescription, LastCycleValue
from ..cycle.statistics import PERIOD_LIST, PERIODS, Meter
from ..cycle.totals import CyclesTotal, RuntimeTotal
from .open import Open

_LOGGER = logging.getLogger(__name__)

# A counter in statistics -> its total is <counter>_total, its meters <counter>_<period>
COUNTERS = ("openings", "open_time")

SCHEMA = vol.Schema(
    {
        vol.Required("contact"): standing.real_entity(Platform.BINARY_SENSOR),
        vol.Optional("statistics", default={}): vol.Schema(
            {vol.Optional(counter, default=[]): PERIOD_LIST for counter in COUNTERS}
        ),
    }
)

# The last opening, as the appliance's last cycle: a door opens for seconds, not minutes
LAST_OPENING: tuple[LastCycleDescription, ...] = (
    LastCycleDescription(
        key="last_opened",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda cycle: cycle.start,
    ),
    LastCycleDescription(
        key="last_open_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value=lambda cycle: (
            None
            if cycle.start is None
            else round((cycle.end - cycle.start).total_seconds())
        ),
    ),
    LastCycleDescription(
        key="last_closed",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda cycle: cycle.end,
        written_last=True,
    ),
)

ENTITY_KEYS: dict[str, Platform] = {
    "open": Platform.BINARY_SENSOR,
    **{description.key: Platform.SENSOR for description in LAST_OPENING},
    **{f"{counter}_total": Platform.SENSOR for counter in COUNTERS},
    **{
        f"{counter}_{period}": Platform.SENSOR
        for counter in COUNTERS
        for period in PERIODS
    },
}


def _builder(device_class: BinarySensorDeviceClass) -> Build:
    """The build of a door (window), whose `open` has `device_class`."""

    def build(
        hass: HomeAssistant,
        device: Device,
        config: dict[str, Any],
        inputs: Mapping[str, str],
    ) -> list[PururuEntity]:
        """The door's entities; with a contact that is pururu's own, `open` stands for nothing.

        The configuration refuses binary_sensor.pururu_…; one renamed in the UI
        gets past that, and only the registry still knows it is ours. Its
        entities are kept, so every reload gives the same.
        """
        watched = device.current_entity_id(hass, Platform.BINARY_SENSOR, "open")
        contact: str = config["contact"]
        real: str | None = contact
        if standing.is_pururu(hass, contact):
            _LOGGER.error(
                "%s is a pururu binary sensor: name the real contact; %s stands for nothing",
                contact,
                watched,
            )
            real = None
        entities: list[PururuEntity] = [
            Open(device, device_class, contact=real),
            *(
                LastCycleValue(device, description, source="open")
                for description in LAST_OPENING
            ),
            CyclesTotal(device, source="open", entity_key="openings_total"),
            RuntimeTotal(
                device, watched, STATE_ON, source="open", entity_key="open_time_total"
            ),
        ]
        for counter in COUNTERS:
            total = f"{counter}_total"
            source = device.current_entity_id(hass, Platform.SENSOR, total)
            entities.extend(
                Meter(device, f"{counter}_{period}", total, source, period)
                for period in config["statistics"][counter]
            )
        return entities

    return build


def _opening(namespace: str, device_class: BinarySensorDeviceClass) -> Feature:
    """The feature of a door or a window: one code, its own namespace and device class."""
    return Feature(
        schema=SCHEMA,
        entity_keys=ENTITY_KEYS,
        build=_builder(device_class),
        example={"contact": f"binary_sensor.dummy_{namespace}_contact"},
        namespace=namespace,
        provides={"cycle": "open"},
    )


DOOR = _opening("door", BinarySensorDeviceClass.DOOR)
WINDOW = _opening("window", BinarySensorDeviceClass.WINDOW)
```

- [ ] **Step 6: Register the features**

Replace `custom_components/pururu/features/__init__.py` with:

```python
"""Every feature a device can have, by its key in the device's configuration."""

from ..feature import Feature
from .alerts import ALERTS
from .appliance import APPLIANCE
from .lights import LIGHTS
from .modes import MODES
from .opening import DOOR, WINDOW
from .phases import PHASES
from .programs import PROGRAMS
from .switches import SWITCHES

FEATURES: dict[str, Feature] = {
    "appliance": APPLIANCE,
    "door": DOOR,
    "window": WINDOW,
    "lights": LIGHTS,
    "phases": PHASES,
    "modes": MODES,
    "switches": SWITCHES,
    "alerts": ALERTS,
    "programs": PROGRAMS,
}
```

- [ ] **Step 7: Name the entities and give them icons**

In `custom_components/pururu/translations/en.json`, under `entity.binary_sensor`, add:

```json
      "door_open": {"name": "Open"},
      "window_open": {"name": "Open"}
```

Under `entity.sensor` in the same file, add:

```json
      "door_last_opened": {"name": "Last opened"},
      "door_last_closed": {"name": "Last closed"},
      "door_last_open_duration": {"name": "Last open duration"},
      "door_openings_total": {"name": "Openings", "unit_of_measurement": "openings"},
      "door_open_time_total": {"name": "Time open"},
      "door_openings_today": {"name": "Openings today"},
      "door_openings_week": {"name": "Openings this week"},
      "door_openings_month": {"name": "Openings this month"},
      "door_openings_year": {"name": "Openings this year"},
      "door_open_time_today": {"name": "Time open today"},
      "door_open_time_week": {"name": "Time open this week"},
      "door_open_time_month": {"name": "Time open this month"},
      "door_open_time_year": {"name": "Time open this year"},
      "window_last_opened": {"name": "Last opened"},
      "window_last_closed": {"name": "Last closed"},
      "window_last_open_duration": {"name": "Last open duration"},
      "window_openings_total": {"name": "Openings", "unit_of_measurement": "openings"},
      "window_open_time_total": {"name": "Time open"},
      "window_openings_today": {"name": "Openings today"},
      "window_openings_week": {"name": "Openings this week"},
      "window_openings_month": {"name": "Openings this month"},
      "window_openings_year": {"name": "Openings this year"},
      "window_open_time_today": {"name": "Time open today"},
      "window_open_time_week": {"name": "Time open this week"},
      "window_open_time_month": {"name": "Time open this month"},
      "window_open_time_year": {"name": "Time open this year"}
```

In `custom_components/pururu/translations/pt-BR.json`, under `entity.binary_sensor`, add:

```json
      "door_open": {"name": "Aberta"},
      "window_open": {"name": "Aberta"}
```

Under `entity.sensor` in the same file, add:

```json
      "door_last_opened": {"name": "Última abertura"},
      "door_last_closed": {"name": "Último fechamento"},
      "door_last_open_duration": {"name": "Duração da última abertura"},
      "door_openings_total": {"name": "Aberturas", "unit_of_measurement": "aberturas"},
      "door_open_time_total": {"name": "Tempo aberta"},
      "door_openings_today": {"name": "Aberturas hoje"},
      "door_openings_week": {"name": "Aberturas na semana"},
      "door_openings_month": {"name": "Aberturas no mês"},
      "door_openings_year": {"name": "Aberturas no ano"},
      "door_open_time_today": {"name": "Tempo aberta hoje"},
      "door_open_time_week": {"name": "Tempo aberta na semana"},
      "door_open_time_month": {"name": "Tempo aberta no mês"},
      "door_open_time_year": {"name": "Tempo aberta no ano"},
      "window_last_opened": {"name": "Última abertura"},
      "window_last_closed": {"name": "Último fechamento"},
      "window_last_open_duration": {"name": "Duração da última abertura"},
      "window_openings_total": {"name": "Aberturas", "unit_of_measurement": "aberturas"},
      "window_open_time_total": {"name": "Tempo aberta"},
      "window_openings_today": {"name": "Aberturas hoje"},
      "window_openings_week": {"name": "Aberturas na semana"},
      "window_openings_month": {"name": "Aberturas no mês"},
      "window_openings_year": {"name": "Aberturas no ano"},
      "window_open_time_today": {"name": "Tempo aberta hoje"},
      "window_open_time_week": {"name": "Tempo aberta na semana"},
      "window_open_time_month": {"name": "Tempo aberta no mês"},
      "window_open_time_year": {"name": "Tempo aberta no ano"}
```

Keep each file's existing indentation (match the surrounding entries' style: the translation files write one key per line with nested objects expanded; expand these the same way). Keep `→` and other escapes in `en.json` as they are: edit the files by hand, don't rewrite them with `json.dump`.

In `custom_components/pururu/icons.json`, under `entity.binary_sensor`, add:

```json
      "door_open": {"default": "mdi:door-closed", "state": {"on": "mdi:door-open"}},
      "window_open": {"default": "mdi:window-closed", "state": {"on": "mdi:window-open"}}
```

Under `entity.sensor`, add:

```json
      "door_last_opened": {"default": "mdi:clock-start"},
      "door_last_closed": {"default": "mdi:clock-end"},
      "door_last_open_duration": {"default": "mdi:timer-outline"},
      "door_openings_total": {"default": "mdi:counter"},
      "door_open_time_total": {"default": "mdi:timer-sand"},
      "door_openings_today": {"default": "mdi:counter"},
      "door_openings_week": {"default": "mdi:counter"},
      "door_openings_month": {"default": "mdi:counter"},
      "door_openings_year": {"default": "mdi:counter"},
      "door_open_time_today": {"default": "mdi:timer-sand"},
      "door_open_time_week": {"default": "mdi:timer-sand"},
      "door_open_time_month": {"default": "mdi:timer-sand"},
      "door_open_time_year": {"default": "mdi:timer-sand"},
      "window_last_opened": {"default": "mdi:clock-start"},
      "window_last_closed": {"default": "mdi:clock-end"},
      "window_last_open_duration": {"default": "mdi:timer-outline"},
      "window_openings_total": {"default": "mdi:counter"},
      "window_open_time_total": {"default": "mdi:timer-sand"},
      "window_openings_today": {"default": "mdi:counter"},
      "window_openings_week": {"default": "mdi:counter"},
      "window_openings_month": {"default": "mdi:counter"},
      "window_openings_year": {"default": "mdi:counter"},
      "window_open_time_today": {"default": "mdi:timer-sand"},
      "window_open_time_week": {"default": "mdi:timer-sand"},
      "window_open_time_month": {"default": "mdi:timer-sand"},
      "window_open_time_year": {"default": "mdi:timer-sand"}
```

- [ ] **Step 8: Run the new tests and the contract**

Run: `uv run pytest tests/test_opening.py tests/test_features.py -n 0 -q`
Expected: PASS. `test_features.py` covers `door` and `window` unchanged (names, icons, example, capabilities, namespaces).

- [ ] **Step 9: Run everything**

Run: `uv run pytest`
Expected: PASS, including `tests/test_code.py` (ruff, ruff format, mypy, hassfest) and the appliance and modes tests (the totals' default keys are unchanged). Fix what ruff format rewrites with `uv run ruff format custom_components/pururu`.

- [ ] **Step 10: Commit**

```bash
git add custom_components/pururu tests/test_opening.py
git commit -m "pururu: doors and windows, their openings from a contact

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Events that describe the openings

**Files:**
- Create: `custom_components/pururu/features/opening/events.py`
- Modify: `custom_components/pururu/features/opening/open.py` (whole file below)
- Modify: `custom_components/pururu/features/opening/__init__.py` (schema, entity keys, build)
- Modify: `custom_components/pururu/translations/en.json`, `custom_components/pururu/translations/pt-BR.json`, `custom_components/pururu/icons.json`
- Test: `tests/test_opening.py` (append)

**Interfaces:**
- Consumes: from Task 1, `Open(device, device_class, *, contact)`, `_opening_starts(now)`, `SCHEMA`, `ENTITY_KEYS`, `_builder`; `features/opening/__init__.py`'s imports.
- Produces:
  - `features/opening/events.py`: `OPENING = "opening"`, `DENIED = "denied"`, `RING = "ring"`, `MEANINGS`, `FIELDS: dict[str, str]` (field → entity key), `LAST: dict[str, str]` (meaning → entity key), `ENTITY_KEYS: dict[str, Platform]`, `SCHEMA` (one event), `described_signal(device) -> SignalType[Mapping[str, str | None]]`, `@dataclass Fired(time: datetime, fields: dict[str, str | None])`, `@dataclass Source(entity: str, types: Mapping[str, str], fields: Mapping[str, str])` with `Source.of(config) -> Source`, `Source.means(meaning) -> bool`, `Source.fired(event, meaning) -> Fired | None`, `class LastOpeningField(device, field)`, `class LastEvent(device, meaning, sources)`, `entities(device, sources) -> list[PururuEntity]`.
  - `Open(device, device_class, *, contact, events: Sequence[Source] = (), match: timedelta = timedelta(0))`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_opening.py`:

```python
# --- events -------------------------------------------------------------------------

ACCESS = "event.cercado_frente_access"
DOORBELL = "event.cercado_frente_doorbell"
ACCESS_TYPES = {"access_granted": "opening", "access_denied": "denied"}
ACCESS_FIELDS = {"who": "actor", "how": "authentication", "direction": "direction"}
EVENTS = [
    {"entity": ACCESS, "types": ACCESS_TYPES, "fields": ACCESS_FIELDS},
    {"entity": DOORBELL, "types": {"ring": "ring"}},
]
# What an access controller sends
ENTRY = {"actor": "Alex Doe", "authentication": "PIN_CODE", "direction": "entry",
         "result": "ACCESS"}
EXIT = {"actor": "N/A", "authentication": "REX", "direction": "exit", "result": "ACCESS"}
FIELD_KEYS = ("last_opened_by", "last_opened_via", "last_direction")


async def access(hass: HomeAssistant, event_type: str = "access_granted", *,
                 at: str | None = None, **attributes: Any) -> None:
    """An access event: its state is the event's time, now unless `at`."""
    time = at or dt_util.utcnow().isoformat(timespec="milliseconds")
    await fake(hass, ACCESS, time, {"event_types": ["access_granted", "access_denied"],
                                    "event_type": event_type, **attributes})


async def ring(hass: HomeAssistant) -> None:
    await fake(hass, DOORBELL, dt_util.utcnow().isoformat(timespec="milliseconds"),
               {"event_types": ["ring"], "event_type": "ring", "device_class": "doorbell"})


def fields(hass: HomeAssistant, kind: str) -> tuple[str, str, str]:
    return tuple(value(hass, kind, entity_key) for entity_key in FIELD_KEYS)  # type: ignore[return-value]


@pytest.fixture
async def enclosure(ha: HomeAssistant, kind: str) -> HomeAssistant:
    """The front enclosure door with its access and doorbell events; the last access is old."""
    await contact(ha, "off")
    await access(ha, at="2026-09-15T10:00:00.000+00:00", **ENTRY)
    assert await setup(ha, devices(kind, events=EVENTS))
    return ha


@pytest.mark.parametrize("block", [
    pytest.param({"events": []}, id="no event"),
    pytest.param({"events": [{"entity": "sensor.x", "types": ACCESS_TYPES}]}, id="not an event"),
    pytest.param({"events": [{"entity": ACCESS, "types": {}}]}, id="no type"),
    pytest.param({"events": [{"entity": ACCESS, "types": {"access_granted": "opened"}}]},
                 id="unknown meaning"),
    pytest.param({"events": [{"entity": ACCESS, "types": ACCESS_TYPES,
                              "fields": {"user": "actor"}}]}, id="unknown field"),
    pytest.param({"events": [{"entity": ACCESS, "types": ACCESS_TYPES,
                              "fields": {"who": " "}}]}, id="blank attribute"),
    pytest.param({"events": [{"entity": ACCESS, "types": ACCESS_TYPES, "extra": 1}]},
                 id="unknown key"),
    pytest.param({"events": [{"types": ACCESS_TYPES}]}, id="no entity"),
    pytest.param({"match": "soon"}, id="match not a period"),
])
async def test_invalid_events_are_refused(ha: HomeAssistant, kind: str,
                                          block: dict[str, Any]) -> None:
    assert not await setup(ha, devices(kind, **block))


async def test_entry_by_pin_describes_the_opening(enclosure: HomeAssistant, kind: str,
                                                  freezer: Any) -> None:
    """The contact opens, the access event comes 0.9 s later."""
    await contact(enclosure, "on")
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")
    await tick(enclosure, freezer, 0.9)
    await access(enclosure, **ENTRY)
    assert fields(enclosure, kind) == ("Alex Doe", "PIN_CODE", "entry")
    await tick(enclosure, freezer, 6)
    await contact(enclosure, "off")
    assert fields(enclosure, kind) == ("Alex Doe", "PIN_CODE", "entry")


async def test_an_event_before_the_contact_describes_it(enclosure: HomeAssistant, kind: str,
                                                        freezer: Any) -> None:
    await access(enclosure, **EXIT)
    await tick(enclosure, freezer, 1)
    await contact(enclosure, "on")
    assert fields(enclosure, kind) == ("N/A", "REX", "exit")


@pytest.mark.parametrize("event_first", [True, False])
async def test_an_event_outside_match_is_dropped(enclosure: HomeAssistant, kind: str,
                                                 freezer: Any, event_first: bool) -> None:
    if event_first:
        await access(enclosure, **EXIT)
        await tick(enclosure, freezer, 6)
        await contact(enclosure, "on")
    else:
        await contact(enclosure, "on")
        await tick(enclosure, freezer, 6)
        await access(enclosure, **EXIT)
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")


async def test_match_can_be_set(ha: HomeAssistant, kind: str, freezer: Any) -> None:
    await contact(ha, "off")
    assert await setup(ha, devices(kind, events=EVENTS, match={"seconds": 10}))
    await contact(ha, "on")
    await tick(ha, freezer, 8)
    await access(ha, **ENTRY)
    assert fields(ha, kind) == ("Alex Doe", "PIN_CODE", "entry")


async def test_the_first_event_wins(enclosure: HomeAssistant, kind: str, freezer: Any) -> None:
    await contact(enclosure, "on")
    await access(enclosure, **ENTRY)
    await tick(enclosure, freezer, 1)
    await access(enclosure, **EXIT)
    assert fields(enclosure, kind) == ("Alex Doe", "PIN_CODE", "entry")


async def test_a_short_opening_closed_before_its_event(enclosure: HomeAssistant, kind: str,
                                                       freezer: Any) -> None:
    await opening(enclosure, freezer, 0.5)
    await tick(enclosure, freezer, 0.5)
    await access(enclosure, **ENTRY)
    assert fields(enclosure, kind) == ("Alex Doe", "PIN_CODE", "entry")


async def test_an_opening_without_event_forgets_the_last(enclosure: HomeAssistant, kind: str,
                                                         freezer: Any) -> None:
    """Leaving by the front door, from inside: no event, so not the last entry's PIN again."""
    await contact(enclosure, "on")
    await access(enclosure, **ENTRY)
    await tick(enclosure, freezer, 6)
    await contact(enclosure, "off")
    await tick(enclosure, freezer, 600)
    await contact(enclosure, "on")
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")


async def test_a_quick_reopening_without_event_is_unknown(enclosure: HomeAssistant, kind: str,
                                                          freezer: Any) -> None:
    await contact(enclosure, "on")
    await access(enclosure, **ENTRY)
    await tick(enclosure, freezer, 2)
    await contact(enclosure, "off")
    await tick(enclosure, freezer, 1)
    await contact(enclosure, "on")
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")


async def test_an_event_type_not_in_types_is_ignored(enclosure: HomeAssistant, kind: str) -> None:
    await contact(enclosure, "on")
    await access(enclosure, "access_unknown", **ENTRY)
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")
    assert value(enclosure, kind, "last_denied") == "unknown"


async def test_a_missing_attribute_is_unknown(enclosure: HomeAssistant, kind: str) -> None:
    await contact(enclosure, "on")
    await access(enclosure, actor="Alex Doe")
    assert fields(enclosure, kind) == ("Alex Doe", "unknown", "unknown")


async def test_a_field_that_is_not_text_is_text(enclosure: HomeAssistant, kind: str) -> None:
    await contact(enclosure, "on")
    await access(enclosure, **{**ENTRY, "actor": 42})
    assert value(enclosure, kind, "last_opened_by") == "42"


async def test_a_state_that_is_not_a_time_is_ignored(enclosure: HomeAssistant, kind: str) -> None:
    await contact(enclosure, "on")
    await access(enclosure, at="garbage", **ENTRY)
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")


async def test_the_same_state_again_is_no_new_event(enclosure: HomeAssistant, kind: str,
                                                    freezer: Any) -> None:
    """Attributes changing under the same state (the same time) are no new event."""
    at = dt_util.utcnow().isoformat(timespec="milliseconds")
    await access(enclosure, at=at, **ENTRY)
    await tick(enclosure, freezer, 600)
    await contact(enclosure, "on")
    await access(enclosure, at=at, **EXIT)
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")


async def test_a_restart_replaying_an_old_event_describes_nothing(ha: HomeAssistant, kind: str,
                                                                  freezer: Any) -> None:
    """After a restart the event entity comes back with its last, old, time."""
    old = (dt_util.utcnow() - timedelta(hours=1)).isoformat(timespec="milliseconds")
    ha.states.async_set(CONTACT, "off")
    await restart(ha, devices(kind, events=EVENTS))
    await fake(ha, ACCESS, "unavailable")
    await access(ha, at=old, **ENTRY)
    await tick(ha, freezer, 1)
    await contact(ha, "on")
    assert fields(ha, kind) == ("unknown", "unknown", "unknown")


async def test_denied_records_its_time_and_fields(enclosure: HomeAssistant, kind: str) -> None:
    await access(enclosure, "access_denied", actor="Estranho", authentication="NFC",
                 direction="entry", result="BLOCKED")
    assert seconds_from(enclosure, kind, "last_denied") < 1
    attributes = enclosure.states.get(entity(kind, "last_denied")).attributes
    assert (attributes["who"], attributes["how"], attributes["direction"]) == (
        "Estranho", "NFC", "entry")
    assert opened(enclosure, kind) == "off"
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")


async def test_denied_keeps_its_latest(ha: HomeAssistant, kind: str) -> None:
    """A replayed older denial, after a restart, doesn't replace the restored one."""
    last = dt_util.utcnow().replace(microsecond=0) - timedelta(minutes=5)
    await restart(ha, devices(kind, events=EVENTS),
                  (State(entity(kind, "last_denied"), last.isoformat(), {"who": "Estranho"}),
                   {"native_value": {"__type": "<class 'datetime.datetime'>",
                                     "isoformat": last.isoformat()},
                    "native_unit_of_measurement": None}))
    assert dt_util.parse_datetime(value(ha, kind, "last_denied")) == last
    assert ha.states.get(entity(kind, "last_denied")).attributes["who"] == "Estranho"
    await fake(ha, ACCESS, "unavailable")
    await access(ha, "access_denied", at=(last - timedelta(minutes=1)).isoformat(),
                 actor="Outro")
    assert dt_util.parse_datetime(value(ha, kind, "last_denied")) == last
    assert ha.states.get(entity(kind, "last_denied")).attributes["who"] == "Estranho"


async def test_a_ring_is_recorded(enclosure: HomeAssistant, kind: str) -> None:
    await ring(enclosure)
    assert seconds_from(enclosure, kind, "last_ring") < 1
    assert "who" not in enclosure.states.get(entity(kind, "last_ring")).attributes


async def test_a_ring_never_describes_an_opening(enclosure: HomeAssistant, kind: str) -> None:
    await contact(enclosure, "on")
    await ring(enclosure)
    assert fields(enclosure, kind) == ("unknown", "unknown", "unknown")
    assert value(enclosure, kind, "last_ring") != "unknown"


async def test_only_what_the_events_give_is_created(ha: HomeAssistant, kind: str) -> None:
    await contact(ha, "off")
    assert await setup(ha, devices(kind, events=[EVENTS[1]]))
    assert ha.states.get(entity(kind, "last_ring")) is not None
    for entity_key in (*FIELD_KEYS, "last_denied"):
        assert ha.states.get(entity(kind, entity_key)) is None, entity_key


async def test_without_events_nothing_of_theirs_is_created(door: HomeAssistant,
                                                           kind: str) -> None:
    for entity_key in (*FIELD_KEYS, "last_denied", "last_ring"):
        assert door.states.get(entity(kind, entity_key)) is None, entity_key


async def test_the_fields_restore(ha: HomeAssistant, kind: str) -> None:
    await restart(ha, devices(kind, events=EVENTS),
                  (State(entity(kind, "last_opened_by"), "Alex Doe"),
                   {"native_value": "Alex Doe", "native_unit_of_measurement": None}))
    assert value(ha, kind, "last_opened_by") == "Alex Doe"


async def test_the_fields_have_names(enclosure: HomeAssistant, kind: str) -> None:
    state = enclosure.states.get(entity(kind, "last_opened_by"))
    assert state.attributes["friendly_name"] == f"{NAME} Last opened by"
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_opening.py -n 0 -q`
Expected: the Task 1 tests pass; the new ones fail. `events:` and `match:` are refused (`extra keys not allowed`), so `setup` returns False, and `enclosure`-based tests fail on its `assert await setup(...)`. The invalid-events tests may pass already.

- [ ] **Step 3: Write `events.py`**

Create `custom_components/pururu/features/opening/events.py`:

```python
"""Events that describe a door's openings, in pururu's own words: what each means, and its fields.

pururu knows no integration: the configuration maps each event_type of an
event entity to a meaning, and each field to the attribute holding it. An
event entity's state is the time of its last event: that time, not when
pururu sees it, is the event's.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from functools import partial
from typing import Any, Self, override

import voluptuous as vol

from homeassistant.components.sensor import RestoreSensor, SensorDeviceClass
from homeassistant.const import Platform
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util
from homeassistant.util.signal_type import SignalType

from ...entity import PururuEntity
from ...feature import TEXT, Device

OPENING = "opening"
DENIED = "denied"
RING = "ring"
MEANINGS = (OPENING, DENIED, RING)

# A field -> the entity key of the last opening's value
FIELDS: dict[str, str] = {
    "who": "last_opened_by",
    "how": "last_opened_via",
    "direction": "last_direction",
}
# A meaning recorded on its own -> the entity key of its last time
LAST: dict[str, str] = {DENIED: "last_denied", RING: "last_ring"}

ENTITY_KEYS: dict[str, Platform] = {
    **{entity_key: Platform.SENSOR for entity_key in FIELDS.values()},
    **{entity_key: Platform.SENSOR for entity_key in LAST.values()},
}

# One event entity; schemas of their own, so unknown keys are refused
SCHEMA = vol.Schema(
    {
        vol.Required("entity"): cv.entity_domain("event"),
        vol.Required("types"): vol.All(
            vol.Schema({cv.string: vol.In(MEANINGS)}), vol.Length(min=1)
        ),
        vol.Optional("fields", default={}): vol.Schema({vol.In(FIELDS): TEXT}),
    }
)


def _text(value: Any) -> str | None:
    """An attribute as text (`42` → "42"); None when it isn't there."""
    return None if value is None else str(value)


def described_signal(device: Device) -> SignalType[Mapping[str, str | None]]:
    """The fields of the last opening, sent when it starts ({}) and when an event describes it."""
    return SignalType(device.object_id("described"))


@dataclass(frozen=True, kw_only=True)
class Fired:
    """An event: its time and its fields (None: the attribute isn't there)."""

    time: datetime
    fields: dict[str, str | None]


@dataclass(frozen=True, kw_only=True)
class Source:
    """An event entity of the configuration: its types' meanings, its fields' attributes."""

    entity: str
    types: Mapping[str, str]
    fields: Mapping[str, str]

    @classmethod
    def of(cls, config: Mapping[str, Any]) -> Self:
        """From a validated item of `events`."""
        return cls(
            entity=config["entity"], types=config["types"], fields=config["fields"]
        )

    def means(self, meaning: str) -> bool:
        """Whether some type of this entity means `meaning`."""
        return meaning in self.types.values()

    def fired(
        self, event: Event[EventStateChangedData], meaning: str
    ) -> Fired | None:
        """The event of `meaning` a change of the entity says, or None.

        The same state again (attributes only), unknown, unavailable, or
        anything not a time is no new event.
        """
        old, new = event.data["old_state"], event.data["new_state"]
        if new is None or (old is not None and old.state == new.state):
            return None
        time = dt_util.parse_datetime(new.state)
        event_type = str(new.attributes.get("event_type"))
        if time is None or self.types.get(event_type) != meaning:
            return None
        return Fired(
            time=time,
            fields={
                field: _text(new.attributes.get(attribute))
                for field, attribute in self.fields.items()
            },
        )


class LastOpeningField(PururuEntity, RestoreSensor):
    """One field of the last opening (who made it, how, which way); unknown when no event says."""

    def __init__(self, device: Device, field: str) -> None:
        """The value of `field` of the last opening of `device`."""
        self.sources = ("open",)
        self._identify(device, Platform.SENSOR, FIELDS[field])
        self._field = field
        self._signal = described_signal(device)

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the value, then wait for the next opening."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and isinstance(last.native_value, str):
            self._attr_native_value = last.native_value
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._signal, self._record)
        )

    @callback
    def _record(self, fields: Mapping[str, str | None]) -> None:
        self._attr_native_value = fields.get(self._field)
        self.async_write_ha_state()


class LastEvent(PururuEntity, RestoreSensor):
    """When the last event of a meaning came (a denied attempt, a ring), its fields as attributes."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, device: Device, meaning: str, sources: Sequence[Source]) -> None:
        """The last event meaning `meaning` among `sources`."""
        self._identify(device, Platform.SENSOR, LAST[meaning])
        self._meaning = meaning
        self._sources = sources
        self._attr_extra_state_attributes = {}

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the time and fields, then watch every source."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last.native_value
        if (state := await self.async_get_last_state()) is not None:
            self._attr_extra_state_attributes = {
                field: state.attributes[field]
                for field in FIELDS
                if field in state.attributes
            }
        for source in self._sources:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, source.entity, partial(self._changed, source)
                )
            )

    @callback
    def _changed(self, source: Source, event: Event[EventStateChangedData]) -> None:
        """A later event of the meaning replaces the last; an older one, replayed, doesn't."""
        if (fired := source.fired(event, self._meaning)) is None:
            return
        last = self._attr_native_value
        if isinstance(last, datetime) and fired.time <= last:
            return
        self._attr_native_value = fired.time
        self._attr_extra_state_attributes = dict(fired.fields)
        self.async_write_ha_state()


def entities(device: Device, sources: Sequence[Source]) -> list[PururuEntity]:
    """What the events give: each field an opening event maps, and the last denied and ring.

    A ring's attributes would say nothing about the door: it has none.
    """
    mapped = {field for source in sources if source.means(OPENING) for field in source.fields}
    built: list[PururuEntity] = [
        LastOpeningField(device, field) for field in FIELDS if field in mapped
    ]
    if denied := [source for source in sources if source.means(DENIED)]:
        built.append(LastEvent(device, DENIED, denied))
    if rings := [replace(source, fields={}) for source in sources if source.means(RING)]:
        built.append(LastEvent(device, RING, rings))
    return built
```

- [ ] **Step 4: Match events to openings in `open.py`**

Replace `custom_components/pururu/features/opening/open.py` with:

```python
"""Whether the door is open: its contact, held while the contact has no state; the source of its openings.

It also matches opening events to openings, by time: an event `match` apart
from an opening's start at most describes it, whichever comes first.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from functools import partial
from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import STATE_OFF, STATE_ON, Platform
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from ...entity import PururuEntity
from ...feature import Device
from ..cycle import Cycle, CycleStart, cycle_signal, end_signal
from .events import OPENING, Fired, Source, described_signal


class Open(PururuEntity, BinarySensorEntity, RestoreEntity):
    """On while the contact is open; holds while it has no state. Each opening is a cycle."""

    def __init__(
        self,
        device: Device,
        device_class: BinarySensorDeviceClass,
        *,
        contact: str | None,
        events: Sequence[Source] = (),
        match: timedelta = timedelta(0),
    ) -> None:
        """Follow `contact` (None: stand for nothing, unavailable); `events` describe openings."""
        self._identify(device, Platform.BINARY_SENSOR, "open")
        self._attr_device_class = device_class
        self._attr_available = contact is not None
        self._attr_is_on = False
        self._contact = contact
        self._events = events
        self._match = match
        self._signals = (cycle_signal(device), end_signal(device))
        self._described_signal = described_signal(device)
        self._data = CycleStart()
        # False until HA has started: every entity of the door listens by then
        self._following = False
        # The last opening's start, whether an event described it, an event waiting
        self._opened: datetime | None = None
        self._described = False
        self._pending: Fired | None = None

    @property
    @override
    def extra_restore_state_data(self) -> CycleStart:
        """The current opening's start."""
        return self._data

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the state and the opening; follow the contact once HA has started.

        Nothing opens or closes before: the door's other entities may not listen
        yet. Once HA has started, a restored opening whose contact is closed ends.
        """
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == STATE_ON
        if (extra := await self.async_get_last_extra_data()) is not None:
            self._data = CycleStart.from_dict(extra.as_dict())
        self._opened = self._data.since
        if self._contact is None:
            return
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._contact, self._contact_changed
            )
        )
        for source in self._events:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, source.entity, partial(self._event, source)
                )
            )
        self.async_on_remove(async_at_started(self.hass, self._started))

    @callback
    def _started(self, _hass: HomeAssistant) -> None:
        """Every entity of the door listens now: follow the contact as it is."""
        self._following = True
        if self._contact is not None:
            self._follow(self.hass.states.get(self._contact))

    @callback
    def _contact_changed(self, event: Event[EventStateChangedData]) -> None:
        if self._following:
            self._follow(event.data["new_state"])

    @callback
    def _follow(self, state: State | None) -> None:
        """Open or close as the contact says; hold while it says neither."""
        if state is None or state.state not in (STATE_ON, STATE_OFF):
            return
        is_open = state.state == STATE_ON
        if is_open == self._attr_is_on:
            return
        now = dt_util.utcnow()
        self._attr_is_on = is_open
        if is_open:
            self._data = CycleStart(since=now)
            self.async_write_ha_state()
            self._opening_starts(now)
            return
        cycle = Cycle(start=self._data.since, end=now, energy_kwh=None)
        self._data = CycleStart()
        self.async_write_ha_state()
        for signal in self._signals:  # the end's own signal last
            async_dispatcher_send(self.hass, signal, cycle)

    @callback
    def _opening_starts(self, now: datetime) -> None:
        """A new opening: an event waiting close enough describes it; else nothing does yet."""
        self._opened = now
        self._described = False
        pending, self._pending = self._pending, None
        if pending is not None and abs(now - pending.time) <= self._match:
            self._describe(pending.fields)
        else:
            async_dispatcher_send(self.hass, self._described_signal, {})

    @callback
    def _event(self, source: Source, event: Event[EventStateChangedData]) -> None:
        """An opening event describes the last opening near its start; else it waits for the next."""
        if not self._following or (fired := source.fired(event, OPENING)) is None:
            return
        if (
            self._opened is not None
            and not self._described
            and abs(fired.time - self._opened) <= self._match
        ):
            self._describe(fired.fields)
        else:
            self._pending = fired

    @callback
    def _describe(self, fields: Mapping[str, str | None]) -> None:
        """The first event near the opening wins: later ones don't describe it."""
        self._described = True
        async_dispatcher_send(self.hass, self._described_signal, fields)
```

- [ ] **Step 5: Take `events` and `match` in the feature**

In `custom_components/pururu/features/opening/__init__.py`:

Add these imports (keeping the import blocks sorted as ruff wants):

```python
from datetime import timedelta

from homeassistant.helpers import config_validation as cv

from . import events
```

Replace `SCHEMA` with:

```python
SCHEMA = vol.Schema(
    {
        vol.Required("contact"): standing.real_entity(Platform.BINARY_SENSOR),
        vol.Optional("statistics", default={}): vol.Schema(
            {vol.Optional(counter, default=[]): PERIOD_LIST for counter in COUNTERS}
        ),
        # How far from an opening's start an opening event may be, before or after
        vol.Optional("match", default=timedelta(seconds=5)): cv.positive_time_period,
        vol.Optional("events"): vol.All([events.SCHEMA], vol.Length(min=1)),
    }
)
```

Add `**events.ENTITY_KEYS,` as the last entry of `ENTITY_KEYS`:

```python
ENTITY_KEYS: dict[str, Platform] = {
    "open": Platform.BINARY_SENSOR,
    **{description.key: Platform.SENSOR for description in LAST_OPENING},
    **{f"{counter}_total": Platform.SENSOR for counter in COUNTERS},
    **{
        f"{counter}_{period}": Platform.SENSOR
        for counter in COUNTERS
        for period in PERIODS
    },
    **events.ENTITY_KEYS,
}
```

In `build`, replace the line `Open(device, device_class, contact=real),` with:

```python
            Open(
                device,
                device_class,
                contact=real,
                events=[source for source in sources if source.means(events.OPENING)],
                match=config["match"],
            ),
```

and add, on its own line right before `entities: list[PururuEntity] = [` (after the `if standing.is_pururu(...)` block):

```python
        sources = [events.Source.of(block) for block in config.get("events", [])]
```

and, right before `return entities`:

```python
        entities.extend(events.entities(device, sources))
```

Also update the module docstring's last sentence to: `The contact is required; events (events.py), optional, describe the openings.`

- [ ] **Step 6: Name the new entities and give them icons**

In `custom_components/pururu/translations/en.json`, under `entity.sensor`, add:

```json
      "door_last_opened_by": {"name": "Last opened by"},
      "door_last_opened_via": {"name": "Last opened via"},
      "door_last_direction": {"name": "Last direction"},
      "door_last_denied": {"name": "Last denied"},
      "door_last_ring": {"name": "Last ring"},
      "window_last_opened_by": {"name": "Last opened by"},
      "window_last_opened_via": {"name": "Last opened via"},
      "window_last_direction": {"name": "Last direction"},
      "window_last_denied": {"name": "Last denied"},
      "window_last_ring": {"name": "Last ring"}
```

In `custom_components/pururu/translations/pt-BR.json`, under `entity.sensor`, add:

```json
      "door_last_opened_by": {"name": "Última abertura por"},
      "door_last_opened_via": {"name": "Última abertura via"},
      "door_last_direction": {"name": "Sentido da última abertura"},
      "door_last_denied": {"name": "Última tentativa negada"},
      "door_last_ring": {"name": "Último toque"},
      "window_last_opened_by": {"name": "Última abertura por"},
      "window_last_opened_via": {"name": "Última abertura via"},
      "window_last_direction": {"name": "Sentido da última abertura"},
      "window_last_denied": {"name": "Última tentativa negada"},
      "window_last_ring": {"name": "Último toque"}
```

In `custom_components/pururu/icons.json`, under `entity.sensor`, add:

```json
      "door_last_opened_by": {"default": "mdi:account"},
      "door_last_opened_via": {"default": "mdi:key-variant"},
      "door_last_direction": {"default": "mdi:swap-horizontal"},
      "door_last_denied": {"default": "mdi:account-cancel"},
      "door_last_ring": {"default": "mdi:bell-ring"},
      "window_last_opened_by": {"default": "mdi:account"},
      "window_last_opened_via": {"default": "mdi:key-variant"},
      "window_last_direction": {"default": "mdi:swap-horizontal"},
      "window_last_denied": {"default": "mdi:account-cancel"},
      "window_last_ring": {"default": "mdi:bell-ring"}
```

Same file style rules as Task 1 Step 7.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_opening.py tests/test_features.py -n 0 -q`
Expected: PASS.

- [ ] **Step 8: Run everything**

Run: `uv run pytest`
Expected: PASS (ruff, ruff format, mypy strict, hassfest included). Fix what ruff format rewrites with `uv run ruff format custom_components/pururu`.

- [ ] **Step 9: Commit**

```bash
git add custom_components/pururu tests/test_opening.py
git commit -m "pururu: events that say who opened a door, how and which way

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Docs and release

**Files:**
- Create: `docs/features/door.mdx`, `docs/features/window.mdx`
- Modify: `docs.json`, `docs/concepts/devices-and-features.mdx`, `docs/concepts/entity-ids.mdx`, `docs/reference/configuration.mdx`, `docs/reference/troubleshooting.mdx`, `docs/develop/architecture.mdx`, `docs/develop/writing-a-feature.mdx`, `CLAUDE.md`, `custom_components/pururu/manifest.json`

**Interfaces:**
- Consumes: the entity keys, messages and settings of Tasks 1 and 2, exactly as in Global Constraints.
- Produces: nothing code depends on.

- [ ] **Step 1: Write `docs/features/door.mdx`**

```mdx
---
title: door
description: A door from its contact sensor. It records each opening, counts them, and, with events, says who opened it, how and which way.
---

`door` turns a contact sensor into a door. Each time the contact opens and closes is an **opening**: pururu records its start, end and duration, and counts openings and the time open. A door can also read **events** from other devices, such as an access controller or a doorbell, to say who opened it, how and which way, and when someone was denied or rang.

`door` is pururu's idea of a door, as [`appliance`](/features/appliance) is its idea of an appliance: you point it at the real entities, and it builds the door from them. The contact is required. Everything else is optional. A [window](/features/window) works the same way.

```yaml
pururu:
  devices:
    porta_cercado_frente:
      name: Cercado frente
      area: entrada
      door:
        contact: binary_sensor.cercado_frente
        statistics:
          openings: [today, week, month]
          open_time: [today, week]
        events:
          - entity: event.cercado_frente_access
            types: {access_granted: opening, access_denied: denied}
            fields: {who: actor, how: authentication, direction: direction}
          - entity: event.cercado_frente_doorbell
            types: {ring: ring}
```

This creates `binary_sensor.pururu_porta_cercado_frente_door_open`, shown as **Cercado frente Open**, and the entities below.

## Settings

<Property name="contact" type="entity ID" required>
  The door's contact sensor, a `binary_sensor.*`: `on` is open, `off` is closed. It can't be one of pururu's own binary sensors, even one you renamed in the UI.
</Property>

---

<Property name="statistics.openings" type="list of periods" optional>
  For each period, a sensor with the openings in the current period. The periods are `today`, `week`, `month` and `year`, each listed at most once.
</Property>

---

<Property name="statistics.open_time" type="list of periods" optional>
  For each period, a sensor with the hours open in the current period.
</Property>

---

<Property name="events" type="list" optional>
  Event entities (`event.*`) that tell pururu more about the door. pururu knows no integration, so you say what each event means for the door and where its details are. Each item has:

  - `entity`: required, the `event.*` entity.
  - `types`: required, at least one: each `event_type` of that entity you care about → what it means for the door. The meanings are `opening` (someone opened the door: the event describes an opening), `denied` (someone tried and was refused) and `ring` (someone rang). Other event types are ignored.
  - `fields`: optional, where the details are: `who`, `how` and `direction`, each → the name of the event's attribute that holds it.
</Property>

---

<Property name="match" type="time period" optional>
  How far from an opening's start an `opening` event may be, before or after, to describe it. Defaults to `{seconds: 5}`. A [time period](/features/appliance#settings).
</Property>

## Openings

- The door opens when the contact turns `on` and closes when it turns `off`. While the contact is `unavailable` or `unknown`, the door **keeps** its state: an opening in progress goes on.
- A contact already open when pururu is set up starts an opening then.
- A **restart or reload** in the middle of an opening doesn't lose it: its start is restored. If the contact is closed once Home Assistant has started, the opening ends then.

## Who, how and which way

An `opening` event describes the opening whose start is at most `match` from the event's time, whichever comes first. Access controllers usually report the event a second or so after the door opens.

- The **first** event near an opening wins. Later ones don't change it.
- An opening with **no** event near it has `unknown` fields. They never keep an earlier opening's values: leaving by the handle, from inside, doesn't show the last entry's PIN again.
- An event's time is the event entity's state (the time of its last event), not the moment pururu sees it. The same state again, `unavailable`, `unknown`, or a state that isn't a time is not a new event. So a restart, which brings the event entity back with its last, old, time, describes nothing.
- A field's value is the attribute as text, as the integration writes it (`PIN_CODE`, `entry`): pururu doesn't translate it. An attribute the event doesn't have leaves its field `unknown`.

## Entities

`<key>` is the device's key.

| Entity | Unit | What it is |
|---|---|---|
| `binary_sensor.pururu_<key>_door_open` | | Open or closed. Device class `door`, whatever the contact's. |
| `sensor.pururu_<key>_door_last_opened` | timestamp | When the last opening started |
| `sensor.pururu_<key>_door_last_closed` | timestamp | When it ended. **Written last**: trigger on it. |
| `sensor.pururu_<key>_door_last_open_duration` | s | How long it lasted |
| `sensor.pururu_<key>_door_openings_total` | openings | Openings, all time |
| `sensor.pururu_<key>_door_open_time_total` | h | Hours open, all time, brought up to date every minute |
| `sensor.pururu_<key>_door_<counter>_<period>` | | `openings` or `open_time` this period, one per entry of `statistics` |

With `events`, only what they give:

| Entity | Created when | What it is |
|---|---|---|
| `sensor.pururu_<key>_door_last_opened_by` | an `opening` type and `fields.who` | Who made the last opening |
| `sensor.pururu_<key>_door_last_opened_via` | an `opening` type and `fields.how` | How the last opening was made |
| `sensor.pururu_<key>_door_last_direction` | an `opening` type and `fields.direction` | Which way the last opening went |
| `sensor.pururu_<key>_door_last_denied` | a `denied` type | When the last denied attempt was, with attributes `who`, `how` and `direction` (those mapped) |
| `sensor.pururu_<key>_door_last_ring` | a `ring` type | When the door last rang |

- Every entity keeps its value across restarts. The totals are `total_increasing`, and the per-period sensors reset as [`appliance`'s](/features/appliance#per-period) do.
- `last_denied` and `last_ring` only move forward: an older event, replayed after a restart, doesn't replace them.

## Provides

`door` provides a **cycle**, carried by `open`: each opening is a cycle. [`phases`](/features/phases) and [`modes`](/features/modes) can take it with `cycle_from: door`, and [`alerts`](/features/alerts) can watch `door_open` (`when: door_open`, `is: "on"`, `for: {minutes: 10}`: a door left open).
```

- [ ] **Step 2: Write `docs/features/window.mdx`**

```mdx
---
title: window
description: A window from its contact sensor. It records each opening and counts them, as a door does.
---

`window` is [`door`](/features/door) for a window: the same settings, the same openings and the same entities, with `window` in their IDs and a `window` device class on `open`.

```yaml
pururu:
  devices:
    janela_quarto:
      name: Janela do quarto
      area: quarto
      window:
        contact: binary_sensor.janela_quarto_contact
        statistics:
          open_time: [today, week]
```

This creates `binary_sensor.pururu_janela_quarto_window_open`, shown as **Janela do quarto Open**, `sensor.pururu_janela_quarto_window_last_opened` and the rest of [a door's entities](/features/door#entities), each with `window` for `door`.

A window rarely has events, but it takes them as a door does: a glass-break or vibration sensor that fires an `event.*` fits. See [`door`](/features/door#settings) for every setting.

A device can be both a door and a window, such as a door with a window of its own: their entities differ by namespace (`door_open`, `window_open`).
```

- [ ] **Step 3: Update the sidebar and the lists**

In `docs.json`, in the `Features` group, after the `appliance` page, add:

```json
        { "title": "door", "href": "/features/door" },
        { "title": "window", "href": "/features/window" },
```

In `docs/concepts/devices-and-features.mdx`, in the first table, after the `appliance` row, add:

```markdown
| [`door`](/features/door) | A door from its contact sensor: each opening, their count and time open per period, and, with events, who opened it, how and which way |
| [`window`](/features/window) | A window from its contact sensor, as a door |
```

In the same file's second table (Provides/Needs), after the `appliance` row, add:

```markdown
| `door` | `cycle`, carried by `binary_sensor.pururu_<key>_door_open` | nothing |
| `window` | `cycle`, carried by `binary_sensor.pururu_<key>_window_open` | nothing |
```

In `docs/concepts/entity-ids.mdx`, in the table of features and namespaces (its `appliance` row is `| [\`appliance\`](/features/appliance) | \`appliance\` | \`binary_sensor.pururu_clothes_washer_appliance_running\` |`), add after that row:

```markdown
| [`door`](/features/door) | `door` | `binary_sensor.pururu_porta_cercado_frente_door_open` |
| [`window`](/features/window) | `window` | `binary_sensor.pururu_janela_quarto_window_open` |
```

In `docs/reference/configuration.mdx`, in the `<feature>` list, after the `appliance` item, add:

```markdown
  - [`door`](/features/door#settings): a door from its contact sensor.
  - [`window`](/features/window): a window from its contact sensor.
```

- [ ] **Step 4: Troubleshooting**

In `docs/reference/troubleshooting.mdx`, in the list of configuration errors that includes `A switch whose \`entity\` isn't a \`switch.*\` entity…`, add:

```markdown
- A door or window whose `contact` isn't a `binary_sensor.*` entity (`sensor.x is not a binary_sensor`) or is a pururu binary sensor (`binary_sensor.pururu_… is a pururu binary_sensor: name the real one`); an event whose `entity` isn't an `event.*` entity, whose `types` is empty or means something other than `opening`, `denied` or `ring`, or whose `fields` names something other than `who`, `how` or `direction`.
```

After the section `### … is this switch itself: name the real one (or light)`, add:

````markdown
### `… is a pururu binary sensor: name the real contact; … stands for nothing`

```
binary_sensor.lavadora_rodando is a pururu binary sensor: name the real contact; binary_sensor.pururu_cercado_frente_door_open stands for nothing
```

A door's or window's `contact:` names one of pururu's own binary sensors that you renamed in the UI, so it no longer starts with `binary_sensor.pururu_`. The door is kept, but its `open` is `unavailable` and it records no openings.

**Fix:** point `contact:` at the real contact sensor, then reload pururu.
````

Add, under `### An entity stays \`unknown\`` (at the end of that section):

```markdown
A door's `last_opened_by`, `last_opened_via` and `last_direction` are `unknown` after an opening no event described: no `opening` event came within `match` of it. Check the event's `types` name its `event_type` exactly, and widen `match` if your controller reports late.
```

- [ ] **Step 5: Developer docs and CLAUDE.md**

In `docs/develop/architecture.mdx`, replace the bullet that starts with `` - `running` keeps its state `` with:

```markdown
- `running` keeps its state and, as extra data, the running cycle's start and energy reading (`CycleStart`, `features/cycle/`); `modes`' `current` keeps the running mode and the same `CycleStart`; a door's (window's) `open` keeps its state and the opening's start in the same `CycleStart`.
```

In `docs/develop/writing-a-feature.mdx`, replace the sentence ``The cycle code `appliance` and `modes` share (the last cycle's sensors, the totals, the meters, a cycle's energy) is in `features/cycle/`, and takes `item`.`` with:

```markdown
The cycle code `appliance`, `modes`, `door` and `window` share (the last cycle's sensors, the totals, the meters, a cycle's energy) is in `features/cycle/`, and takes `item`. A feature with its own words for them passes its own `LastCycleDescription`s and an `entity_key` to `CyclesTotal` and `RuntimeTotal`, as `door` does (`last_opened`, `openings_total`).
```

In `CLAUDE.md`, replace ``The cycle code `appliance` and `modes` share (last cycle, totals, meters, energy) is in `features/cycle/`.`` with:

```markdown
The cycle code `appliance`, `modes`, `door` and `window` share (last cycle, totals, meters, energy) is in `features/cycle/`. `door` and `window` are one package, `features/opening/`, built by one function per namespace: a contact makes the openings (cycles), and user-mapped `event.*` entities describe them (who, how, direction), matched by the event's time (its state).
```

- [ ] **Step 6: The version**

In `custom_components/pururu/manifest.json`, change `"version": "0.1.11"` to `"version": "0.1.12"`.

- [ ] **Step 7: Check**

Run: `python3 release.py check`
Expected: passes (0.1.12 is semver and above the latest release).

Run: `pnpm install` (once) then `pnpm docs:check`
Expected: no broken links.

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add docs docs.json CLAUDE.md custom_components/pururu/manifest.json
git commit -m "pururu: doors and windows documented (0.1.12)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
