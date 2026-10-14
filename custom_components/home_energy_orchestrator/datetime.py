"""Departure date/time platform installed with HEO through HACS."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EnergyConfigEntry
from .trip_entities import TripDepartureDateTime


async def async_setup_entry(
    hass: HomeAssistant, entry: EnergyConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities((TripDepartureDateTime(entry.runtime_data, entry),))
