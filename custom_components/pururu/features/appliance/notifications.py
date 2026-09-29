"""The appliance's ready-made notifications: its cycles."""

from homeassistant.const import STATE_OFF, STATE_ON

from ...feature import Happening

HAPPENINGS: dict[str, Happening] = {
    # A cycle ends exactly when running goes off; from on, so a plug
    # reconnecting (unavailable → off) or a reload tells nobody
    "finished": Happening(watches="running", from_=STATE_ON, to=STATE_OFF),
}
