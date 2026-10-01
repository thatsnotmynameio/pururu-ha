"""A door's (window's) ready-made alerts: its openings."""

from homeassistant.const import STATE_OFF, STATE_ON

from ...core.feature import Elapsed, Preset

PRESETS: dict[str, Preset] = {
    # Open since its opening started, kept across restarts
    "long_opening": Preset(
        watches="open",
        kind=Elapsed(state=STATE_ON, since_attribute="cycle_start"),
        priority="medium",
        hold=None,
    ),
    # Closed since its last closing, or since the alert's creation before any
    "no_opening": Preset(
        watches="open",
        kind=Elapsed(state=STATE_OFF, since_key="last_closed", or_since_created=True),
        priority="medium",
        hold=None,
    ),
}
