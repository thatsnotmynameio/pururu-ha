"""An appliance on a power-measuring plug: when it runs, its cycles, their statistics and the energy between them.

Its required `running_program` is a detected program (features/cycle/program)
read from the plug's power: the appliance running at all, and its phases.
"""

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_NAME, STATE_OFF, STATE_ON, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from ...core.entity import PururuEntity
from ...core.feature import Device, Feature
from ...core.roles import Counted, Counters, Derived, Happenings, Presets, Programs
from ..cycle import program
from ..cycle.last import LAST_CYCLE, LastCycleValue
from ..cycle.totals import CyclesTotal, IdleEnergyTotal, RuntimeTotal
from .alerts import PRESETS
from .mirrors import Mirror
from .notifications import HAPPENINGS

# The appliance running at all: a detected program with a fixed key
RUNNING_PROGRAM = "running_program"
# Its carrier's entity key: appliance_running, as before running_program
CARRIER = "running"


def _unnamed(block: Any) -> Any:
    """Refuse a name: running_program is the appliance running, named by the appliance."""
    if isinstance(block, dict) and CONF_NAME in block:
        raise vol.Invalid(
            f"{RUNNING_PROGRAM} takes no name: it is the appliance running"
        )
    return block


SCHEMA = vol.Schema(
    {
        vol.Required("power"): cv.entity_id,
        vol.Optional("energy"): cv.entity_id,
        vol.Required(RUNNING_PROGRAM): vol.All(_unnamed, program.SCHEMA),
    }
)

ENTITY_KEYS: dict[str, Platform] = {
    "power": Platform.SENSOR,
    "energy_total": Platform.SENSOR,
    CARRIER: Platform.BINARY_SENSOR,
    "last_cycle_start": Platform.SENSOR,
    "last_cycle_end": Platform.SENSOR,
    "last_cycle_duration": Platform.SENSOR,
    "last_cycle_energy": Platform.SENSOR,
    "cycles_total": Platform.SENSOR,
    "runtime_total": Platform.SENSOR,
    "idle_energy_total": Platform.SENSOR,
}


def build(
    hass: HomeAssistant,
    device: Device,
    config: dict[str, Any],
    inputs: Mapping[str, str],
) -> list[PururuEntity]:
    """The plug's mirrors, the running program (its carrier first, then its phases'), and its cycles.

    The program's own cycle entities are the appliance's (D1 ruling 13): they
    follow the carrier, `running`.
    """
    energy: str | None = config.get("energy")
    running = device.current_entity_id(hass, Platform.BINARY_SENSOR, CARRIER)
    entities: list[PururuEntity] = [
        Mirror(hass, device, "power", config["power"]),
        *program.build(
            hass,
            device,
            program.program_of(config[RUNNING_PROGRAM]),
            key=CARRIER,
            reading=config["power"],
            energy=energy,
        ),
        *(
            LastCycleValue(device, description, source=CARRIER)
            for description in LAST_CYCLE
            if energy is not None or description.key != "last_cycle_energy"
        ),
        CyclesTotal(device, source=CARRIER),
        RuntimeTotal(device, running, STATE_ON, source=CARRIER),
    ]
    if energy is not None:
        entities.append(Mirror(hass, device, "energy_total", energy))
        entities.append(
            IdleEnergyTotal(device, running, STATE_OFF, energy, source=CARRIER)
        )
    return entities


APPLIANCE = Feature(
    schema=SCHEMA,
    entity_keys=ENTITY_KEYS,
    build=build,
    example={
        "power": "sensor.dummy_plug_power",
        # One phase and other: the contract test reaches every derived key
        RUNNING_PROGRAM: {
            "above": 4,
            "on_delay": {"minutes": 1},
            "off_delay": {"minutes": 2},
            "phases": {"warming": {"name": "Warming", "above": 1000}},
            "other": {},
        },
    },
    namespace="appliance",
    roles=(
        # Its running program's phases' keys (none without phases)
        Derived(lambda config: program.keys_of(config[RUNNING_PROGRAM])),
        # More detected programs of its power, in `programs: detected:` (the programs aspect)
        Programs("power", "energy"),
        # Metered by the statistics aspect: idle energy in the block (it needs
        # the plug's energy), the rest in running_program, each phase and
        # other, and each detected program
        Counters(
            (
                Counted(needs={"idle_energy": "energy"}),
                *program.counted((RUNNING_PROGRAM,)),
                *program.counted_each(program.DETECTED_AT),
            )
        ),
        # Enabled in its block's `alerts`: the alerts aspect
        Presets(PRESETS),
        Happenings(HAPPENINGS),
    ),
)
