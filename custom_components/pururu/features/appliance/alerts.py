"""The appliance's ready-made alerts: its plug, its cycles."""

from datetime import timedelta

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE

from ...feature import Condition, Elapsed, Preset

PRESETS: dict[str, Preset] = {
    # The plug has no reading
    "offline": Preset(
        watches="power",
        kind=Condition(state=STATE_UNAVAILABLE),
        priority="medium",
        hold=timedelta(minutes=10),
    ),
    # It draws nothing: for an appliance that always draws something
    "no_power": Preset(
        watches="power",
        kind=Condition(state=0.0),
        priority="medium",
        hold=timedelta(minutes=10),
    ),
    "long_cycle": Preset(
        watches="running",
        kind=Elapsed(state=STATE_ON, since_attribute="cycle_start"),
        priority="medium",
        hold=None,
    ),
    "no_cycle": Preset(
        watches="running",
        kind=Elapsed(
            state=STATE_OFF, since_key="last_cycle_end", or_since_created=True
        ),
        priority="medium",
        hold=None,
    ),
    "finished": Preset(
        watches="running",
        kind=Elapsed(state=STATE_OFF, since_key="last_cycle_end"),
        priority="low",
        hold=timedelta(0),
        lasts=timedelta(hours=1),
    ),
}
