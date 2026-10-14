"""Integration-owned controls for the one-off wrapper around HEO Full."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.components.number import NumberEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EnergyCoordinator
from .entity_catalogue import (
    TRIP_DATETIME_DESCRIPTION,
    TRIP_MARGIN_DESCRIPTION,
    TRIP_SWITCH_DESCRIPTION,
    TRIP_TARGET_DESCRIPTION,
)


class TripEntity(CoordinatorEntity[EnergyCoordinator]):
    """Preserve entry-scoped identity and expose state even while plans wait."""

    def __init__(
        self, coordinator: EnergyCoordinator, entry: ConfigEntry,
        platform: str, description: EntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = f"{platform}.home_energy_{description.key}"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def available(self) -> bool:
        return getattr(self.coordinator, "trip_charge", None) is not None

    @property
    def trip(self):
        return self.coordinator.trip_charge


class TripDepartureDateTime(TripEntity, DateTimeEntity):
    """Use HA's localized datetime editor without site-specific date formatting."""

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "datetime", TRIP_DATETIME_DESCRIPTION)

    @property
    def native_value(self) -> datetime | None:
        return self.trip.departure

    async def async_set_value(self, value: datetime) -> None:
        await self.trip.async_set_departure(value)
        self.async_write_ha_state()


class TripTargetSelect(TripEntity, SelectEntity):
    """Selected trip target, not a permanent vehicle charge ceiling."""

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "select", TRIP_TARGET_DESCRIPTION)

    @property
    def current_option(self) -> str:
        return f"{self.trip.target_soc}%"

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError("Choose an integer trip target from 1% to 100%")
        await self.trip.async_set_target_soc(int(option.removesuffix("%")))
        self.async_write_ha_state()


class TripScheduleSwitch(TripEntity, SwitchEntity):
    """Explicit operator arming; installation never schedules a trip."""

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "switch", TRIP_SWITCH_DESCRIPTION)

    @property
    def is_on(self) -> bool:
        return self.trip.armed

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.trip.async_set_armed(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.trip.async_set_armed(False)
        self.async_write_ha_state()


class TripMarginNumber(TripEntity, NumberEntity):
    """Optional timing margin; zero deliberately adds no early finishing buffer."""

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "number", TRIP_MARGIN_DESCRIPTION)

    @property
    def native_value(self) -> float:
        return self.trip.extra_minutes

    async def async_set_native_value(self, value: float) -> None:
        await self.trip.async_set_extra_minutes(value)
        self.async_write_ha_state()


class TripChargeSensor(TripEntity, SensorEntity):
    """Display the wrapper's plan without another device control path."""

    def __init__(self, coordinator, entry, description) -> None:
        super().__init__(coordinator, entry, "sensor", description)

    @property
    def native_value(self):
        return {
            "trip_charge_status": self.trip.status,
            "trip_charge_planned_start": self.trip.planned_start,
            "trip_charge_duration": self.trip.planned_hours,
        }[self.entity_description.key]

    @property
    def extra_state_attributes(self):
        return self.trip.attributes if self.entity_description.key == "trip_charge_status" else None
