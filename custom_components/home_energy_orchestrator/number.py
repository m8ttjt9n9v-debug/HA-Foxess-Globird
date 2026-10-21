"""Editable inputs for the explicit FoxESS diagnostics tab."""

from __future__ import annotations

from math import isfinite

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EnergyConfigEntry
from .aemo_monitor_controls import AemoThresholdNumber
from .const import (
    CONF_EV_BEFORE_EXPORT_SOC_BUFFER,
    CONF_EV_BEFORE_EXPORT_SOC_TARGET,
    CONF_EV_MORNING_SOLAR_RESERVE_SOC,
    CONF_EV_SOLAR_SOAK_ADJUSTMENT_MINUTES,
    CONF_EV_SOLAR_SOAK_AVERAGE_MINUTES,
    CONF_EV_SOLAR_SOAK_BATTERY_SOC,
    DEFAULT_EV_SOLAR_SOAK_ADJUSTMENT_MINUTES,
    DEFAULT_EV_SOLAR_SOAK_AVERAGE_MINUTES,
    DEFAULT_EV_SOLAR_SOAK_BATTERY_SOC,
)
from .coordinator import EnergyCoordinator
from .entity_catalogue import (
    AEMO_THRESHOLD_DESCRIPTIONS,
    EV_BEFORE_EXPORT_BUFFER_DESCRIPTION,
    EV_BEFORE_EXPORT_TARGET_DESCRIPTION,
    EV_MORNING_SOLAR_RESERVE_DESCRIPTION,
    EV_SOLAR_SOAK_DESCRIPTIONS,
)
from .entity_catalogue import (
    NUMBER_DESCRIPTIONS as DESCRIPTIONS,
)
from .trip_entities import TripMarginNumber


async def async_setup_entry(
    hass: HomeAssistant, entry: EnergyConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add the three local-only diagnostic inputs."""
    async_add_entities(
        (
            TripMarginNumber(entry.runtime_data, entry),
            *(TestNumber(entry.runtime_data, entry, description) for description in DESCRIPTIONS),
            *(
                AemoThresholdNumber(entry.runtime_data, entry, description)
                for description in AEMO_THRESHOLD_DESCRIPTIONS
            ),
            EvBeforeExportTargetNumber(
                entry.runtime_data,
                entry,
                EV_BEFORE_EXPORT_TARGET_DESCRIPTION,
            ),
            EvBeforeExportBufferNumber(
                entry.runtime_data, entry, EV_BEFORE_EXPORT_BUFFER_DESCRIPTION,
            ),
            EvMorningSolarReserveNumber(
                entry.runtime_data,
                entry,
                EV_MORNING_SOLAR_RESERVE_DESCRIPTION,
            ),
            *(
                EvSolarSoakNumber(entry.runtime_data, entry, description)
                for description in EV_SOLAR_SOAK_DESCRIPTIONS
            ),
        )
    )


class EvSolarSoakNumber(CoordinatorEntity[EnergyCoordinator], NumberEntity):
    """Edit the same solar-soak setting used by the configuration wizard."""

    _SETTINGS = {
        "ev_solar_soak_battery_soc": (
            CONF_EV_SOLAR_SOAK_BATTERY_SOC, DEFAULT_EV_SOLAR_SOAK_BATTERY_SOC
        ),
        "ev_solar_soak_average_minutes": (
            CONF_EV_SOLAR_SOAK_AVERAGE_MINUTES, DEFAULT_EV_SOLAR_SOAK_AVERAGE_MINUTES
        ),
        "ev_solar_soak_adjustment_minutes": (
            CONF_EV_SOLAR_SOAK_ADJUSTMENT_MINUTES, DEFAULT_EV_SOLAR_SOAK_ADJUSTMENT_MINUTES
        ),
    }

    def __init__(self, coordinator, entry, description) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = f"number.home_energy_{description.key}"
        self._attr_has_entity_name = True

    @property
    def available(self) -> bool:
        # Operator configuration remains editable during a telemetry outage;
        # reconciliation still enforces the normal evidence and write gates.
        return True

    @property
    def native_value(self) -> float:
        key, default = self._SETTINGS[self.entity_description.key]
        return self.coordinator.runtime_config.ev_numbers.value(key, default)

    async def async_set_native_value(self, value: float) -> None:
        description = self.entity_description
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise HomeAssistantError("Use a finite whole-number solar-soak setting") from error
        if (
            isinstance(value, bool)
            or not isfinite(numeric)
            or not numeric.is_integer()
            or not description.native_min_value <= numeric <= description.native_max_value
        ):
            raise HomeAssistantError(
                "Use a finite whole-number solar-soak setting within its limits"
            )
        key, _default = self._SETTINGS[description.key]
        self.hass.config_entries.async_update_entry(
            self._entry,
            data={**self._entry.data, key: numeric},
            options={name: item for name, item in self._entry.options.items() if name != key},
        )
        # Constant-key writes are deliberately explicit so the persisted-key
        # usage audit can account for each managed configuration boundary.
        if key == CONF_EV_SOLAR_SOAK_BATTERY_SOC:
            self.coordinator.update_config_value(CONF_EV_SOLAR_SOAK_BATTERY_SOC, numeric)
        elif key == CONF_EV_SOLAR_SOAK_AVERAGE_MINUTES:
            self.coordinator.update_config_value(CONF_EV_SOLAR_SOAK_AVERAGE_MINUTES, numeric)
        else:
            self.coordinator.update_config_value(CONF_EV_SOLAR_SOAK_ADJUSTMENT_MINUTES, numeric)
        self.async_write_ha_state()
        controller = self.coordinator.ev_controller
        if controller is not None:
            await controller.async_reconcile()
        self.coordinator.async_update_listeners()


class EvBeforeExportTargetNumber(CoordinatorEntity[EnergyCoordinator], NumberEntity):
    """Persist the user-adjustable EV threshold without an external helper."""

    entity_description: NumberEntityDescription

    def __init__(
        self,
        coordinator: EnergyCoordinator,
        entry: ConfigEntry,
        description: NumberEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = "number.home_energy_ev_before_export_soc_target"
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> float:
        return self.coordinator.runtime_config.ev_preferences.before_export_soc_target

    async def async_set_native_value(self, value: float) -> None:
        target = min(max(float(value), 0.0), 100.0)
        config = {**self._entry.data, CONF_EV_BEFORE_EXPORT_SOC_TARGET: target}
        self.hass.config_entries.async_update_entry(self._entry, data=config)
        self.coordinator.update_config_value(CONF_EV_BEFORE_EXPORT_SOC_TARGET, target)
        self.async_write_ha_state()
        controller = self.coordinator.active_controller
        if controller is not None:
            await controller.async_reconcile()
        self.coordinator.async_update_listeners()


class EvBeforeExportBufferNumber(EvBeforeExportTargetNumber):
    """Dashboard and wizard edit one persisted percentage-point buffer."""

    def __init__(self, coordinator, entry, description):
        super().__init__(coordinator, entry, description)
        self.entity_id = 'number.home_energy_ev_before_export_soc_buffer'

    @property
    def available(self):
        return True

    @property
    def native_value(self):
        return self.coordinator.runtime_config.ev_preferences.before_export_soc_buffer

    async def async_set_native_value(self, value):
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise HomeAssistantError('Use a whole-number buffer from 0 to 100') from error
        if (isinstance(value, bool) or not isfinite(numeric) or not numeric.is_integer()
                or not 0 <= numeric <= 100):
            raise HomeAssistantError('Use a whole-number buffer from 0 to 100')
        self.hass.config_entries.async_update_entry(
            self._entry, data={**self._entry.data, CONF_EV_BEFORE_EXPORT_SOC_BUFFER: numeric},
            options={k:v for k,v in self._entry.options.items()
                     if k != CONF_EV_BEFORE_EXPORT_SOC_BUFFER},
        )
        self.coordinator.update_config_value(CONF_EV_BEFORE_EXPORT_SOC_BUFFER, numeric)
        self.async_write_ha_state()
        if self.coordinator.ev_controller is not None:
            await self.coordinator.ev_controller.async_reconcile()
        if self.coordinator.active_controller is not None:
            await self.coordinator.active_controller.async_reconcile()
        self.coordinator.async_update_listeners()


class EvMorningSolarReserveNumber(CoordinatorEntity[EnergyCoordinator], NumberEntity):
    """Persist the independent house-battery reserve for morning solar EV use."""

    entity_description: NumberEntityDescription

    def __init__(
        self,
        coordinator: EnergyCoordinator,
        entry: ConfigEntry,
        description: NumberEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = "number.home_energy_ev_morning_solar_reserve_soc"
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> float:
        return self.coordinator.runtime_config.ev_numbers.value(
            CONF_EV_MORNING_SOLAR_RESERVE_SOC,
            20.0,
        )

    async def async_set_native_value(self, value: float) -> None:
        reserve = min(max(float(value), 0.0), 100.0)
        config = {**self._entry.data, CONF_EV_MORNING_SOLAR_RESERVE_SOC: reserve}
        self.hass.config_entries.async_update_entry(self._entry, data=config)
        self.coordinator.update_config_value(CONF_EV_MORNING_SOLAR_RESERVE_SOC, reserve)
        self.async_write_ha_state()
        controller = self.coordinator.ev_controller
        if controller is not None:
            await controller.async_reconcile()
        self.coordinator.async_update_listeners()


class TestNumber(CoordinatorEntity[EnergyCoordinator], NumberEntity):
    """An editable, non-actuating commissioning input."""

    entity_description: NumberEntityDescription

    def __init__(
        self,
        coordinator: EnergyCoordinator,
        entry: ConfigEntry,
        description: NumberEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = f"number.home_energy_{description.key}"
        self._attr_has_entity_name = True
        self._attr_native_value = self._get_value()
        self._attr_native_max_value = self._max_value()

    @property
    def native_value(self) -> float:
        return self._get_value()

    async def async_set_native_value(self, value: float) -> None:
        value = float(value)
        if self.entity_description.key == "test_charge_power":
            self.coordinator.manual_test.charge_power_kw = value
        elif self.entity_description.key == "test_discharge_power":
            self.coordinator.manual_test.discharge_power_kw = value
        elif self.entity_description.key == "test_duration":
            self.coordinator.manual_test.duration_minutes = value
        self._attr_native_value = value
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()

    def _get_value(self) -> float:
        test = self.coordinator.manual_test
        return {
            "test_charge_power": test.charge_power_kw,
            "test_discharge_power": test.discharge_power_kw,
            "test_duration": test.duration_minutes,
        }[self.entity_description.key]

    def _max_value(self) -> float:
        if self.entity_description.key == "test_charge_power":
            return max(self.coordinator.runtime_config.inverter.charge_limit_kw, 0.1)
        if self.entity_description.key == "test_discharge_power":
            return max(self.coordinator.runtime_config.inverter.discharge_limit_kw, 0.1)
        return float(self.entity_description.native_max_value)
