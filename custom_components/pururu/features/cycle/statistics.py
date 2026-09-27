"""A total's growth per period: HA's utility meter, inside the device."""

from datetime import timedelta
from typing import override

import voluptuous as vol

from homeassistant.components.utility_meter.const import (
    DAILY,
    DATA_TARIFF_SENSORS,
    DATA_UTILITY,
    MONTHLY,
    WEEKLY,
    YEARLY,
)
from homeassistant.components.utility_meter.sensor import UtilityMeterSensor
from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv

from ...const import DOMAIN
from ...entity import PururuEntity
from ...feature import Device, Item, item_key

# A period's name in the configuration and in entity IDs -> utility_meter's cycle
PERIODS: dict[str, str] = {
    "today": DAILY,
    "week": WEEKLY,
    "month": MONTHLY,
    "year": YEARLY,
}


def _distinct(periods: list[str]) -> list[str]:
    if len(set(periods)) != len(periods):
        raise vol.Invalid(f"a period is repeated: {periods}")
    return periods


# A list of periods in a feature's statistics, each at most once
PERIOD_LIST = vol.All(cv.ensure_list, [vol.In(PERIODS)], _distinct)


class Meter(PururuEntity, UtilityMeterSensor):
    """How much a total grew in the current period; utility_meter resets it."""

    def __init__(
        self,
        device: Device,
        entity_key: str,
        total: str,
        source: str,
        period: str,
        *,
        item: Item | None = None,
    ) -> None:
        """Meter `source`, the entity of `total`, over `period` as `entity_key` (of `item`)."""
        self.sources = (item_key(total, item),)
        # Where utility_meter looks itself up; ':' keeps it apart from YAML meter names
        self._meter = f"{DOMAIN}:{device.object_id(item_key(entity_key, item))}"
        UtilityMeterSensor.__init__(  # type: ignore[no-untyped-call]  # core leaves it unannotated
            self,
            cron_pattern=None,
            delta_values=False,
            meter_offset=timedelta(0),
            meter_type=PERIODS[period],
            name=entity_key,
            net_consumption=False,
            parent_meter=self._meter,
            periodically_resetting=False,
            source_entity=source,
            tariff_entity=None,
            tariff=None,
            unique_id=None,
            sensor_always_available=False,
        )
        del self._attr_name  # the name comes from the entity key's translation
        self._identify(device, Platform.SENSOR, entity_key, item=item)

    @override
    async def async_added_to_hass(self) -> None:
        """Register where utility_meter looks for its meters, then meter.

        Core's utility_meter only starts a fresh meter from the source's *next* state
        change (`async_track_state_change_event`, not the value already there): a source
        that stays put after the meter is added (our finite counters, most of the time)
        would leave it `unknown` forever. Seed it from the source's current reading when
        one is already there and nothing was restored.
        """
        self.hass.data[DATA_UTILITY][self._meter] = {DATA_TARIFF_SENSORS: [self]}
        await super().async_added_to_hass()
        if (
            self.native_value is None
            and (state := self.hass.states.get(self._sensor_source_id)) is not None
            and self._validate_state(state) is not None
        ):
            self.start(state.attributes)

    @override
    async def async_will_remove_from_hass(self) -> None:
        """Stop metering and leave utility_meter's list."""
        await super().async_will_remove_from_hass()
        self.hass.data[DATA_UTILITY].pop(self._meter, None)
