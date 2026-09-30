"""The statistics aspect: a total's growth per period, HA's utility meter inside the device.

Every builder with Counters builds its totals (<counter>_total) at each of
its places (Counted: its block, each item, a running program, each phase);
`statistics:` there asks for their meters by period.
"""

from collections.abc import Iterator, Mapping
from datetime import timedelta
from functools import partial
from typing import Any, override

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
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from ..const import DOMAIN
from ..core.entity import PururuEntity
from ..core.feature import Aspect, Device, Feature, Item, Place, item_key, walk
from ..core.roles import Counted, Counters

# The key, at each place a builder counts (Counted)
KEY = "statistics"

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
        translation: str,
        *,
        item: Item | None = None,
    ) -> None:
        """Meter `source`, the entity of `total`, over `period` as `entity_key` (of `item`), named `translation`."""
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
        self._identify(
            device, Platform.SENSOR, entity_key, item=item, translation=translation
        )

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


def _counters(builder: Feature) -> Counters:
    """The builder's counters: it offers statistics only with them."""
    counters = builder.role(Counters)
    assert counters is not None  # ASPECT.offered checked it
    return counters


def _schema(counted: Counted) -> vol.Schema:
    """`statistics:` at a place: counter -> its periods; a schema of its own, so an unknown counter is refused."""
    return vol.Schema(
        {vol.Optional(counter, default=[]): PERIOD_LIST for counter in counted.needs}
    )


def _named(counted: Counted, key: str) -> str:
    """The translation key `key` (`<counter>_<period>`) is named under, once for every builder.

    `key` itself for the builder's own, `item_<key>` (with the `{item}`
    placeholder) for an item's, `<named>_<key>` for a place named on its own
    (other's).
    """
    if counted.named is not None:
        return f"{counted.named}_{key}"
    return key if counted.item is None else f"item_{key}"


def _example(counted: Counted) -> dict[str, list[str]]:
    """A period for each counter needing no setting: a builder's example has only what it requires."""
    return {
        counter: [next(iter(PERIODS))]
        for counter, setting in counted.needs.items()
        if setting is None
    }


def _check(
    counted: Counted, block: Mapping[str, Any], container: Mapping[str, Any]
) -> None:
    """Refuse a counter with periods whose setting (Counted.needs) isn't in the builder's block.

    The whole block, not the container: a phase's energy needs the appliance's.
    """
    for counter, setting in counted.needs.items():
        if setting is not None and container[KEY][counter] and setting not in block:
            raise vol.Invalid(f"{KEY}.{counter} needs {setting}")


def _place(counted: Counted) -> Place:
    """Where `statistics:` sits for these counters, and every meter it can add there: <counter>_<period>."""
    return Place(
        path=counted.at,
        schema=_schema(counted),
        keys={
            f"{counter}_{period}": Platform.SENSOR
            for counter in counted.needs
            for period in PERIODS
        },
        named=partial(_named, counted),
        example=_example(counted),
        item=counted.item,
        check=partial(_check, counted),
    )


def _places(builder: Feature, _name: str) -> tuple[Place, ...]:
    """One place per Counted of the builder.

    Statistics doesn't need the builder's key in the device (`_name`): it names
    nothing to a person, unlike the ready-made notifications' messages.
    """
    return tuple(_place(counted) for counted in _counters(builder).places)


def _meters(
    hass: HomeAssistant,
    device: Device,
    counted: Counted,
    asked: Mapping[str, list[str]],
    item: Item | None,
) -> Iterator[Meter]:
    """The meters `asked` names (counter -> periods), each metering its total's current entity ID."""
    for counter, periods in asked.items():
        total = f"{counter}_total"
        source = device.current_entity_id(hass, Platform.SENSOR, item_key(total, item))
        for period in periods:
            key = f"{counter}_{period}"
            yield Meter(
                device, key, total, source, period, _named(counted, key), item=item
            )


def _build(
    hass: HomeAssistant, device: Device, builder: Feature, block: Any, *_: Any
) -> list[PururuEntity]:
    """The meters asked for at each place, an item's for a container that is one.

    AspectBuild's `texts` (the common texts a ready-made alert's messages
    need) has nothing to build meters from; `*_` takes it without naming it.
    """
    return [
        meter
        for counted in _counters(builder).places
        for path, container in walk(block, counted.at)
        for meter in _meters(
            hass,
            device,
            counted,
            container[KEY],
            None if counted.item is None else counted.item(path[-1], container),
        )
    ]


ASPECT = Aspect(
    key=KEY,
    offered=lambda builder: builder.role(Counters) is not None,
    places=_places,
    build=_build,
)
