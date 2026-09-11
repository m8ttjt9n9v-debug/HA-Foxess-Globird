"""Observer entities for the public, compact v0.1 surface."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import EnergyConfigEntry
from .const import (
    CONF_AUTOMATIC_CHARGE_ENABLED,
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_AUTOMATIC_EXPORT_ENABLED,
    CONF_EV_AUTOMATIC_CONTROL_ENABLED,
    CONF_FOXESS_CONTROL_OWNER,
    CONF_FREE_CHARGE_SCHEDULE_CONFIRMED,
    CONF_REHEARSAL_MODE,
    CONF_SIGN_CONVENTIONS_VERIFIED,
    CONF_ZERO_IMPORT_THRESHOLD_KW,
    DEFAULT_AUTOMATIC_CHARGE_ENABLED,
    DEFAULT_FOXESS_CONTROL_OWNER,
    DEFAULT_SIGN_CONVENTIONS_VERIFIED,
    DEFAULT_ZERO_IMPORT_THRESHOLD_KW,
    DOMAIN,
    FOXESS_CONTROL_OWNER_CLOUD,
)
from .coordinator import EnergyCoordinator
from .ev_adapter import ev_control_gate_status
from .planner.ev import DIRECT_EVSE_MAX_ATTEMPTS

DESCRIPTIONS = (
    SensorEntityDescription(key="status", name="Status", icon="mdi:eye-outline"),
    SensorEntityDescription(
        key="battery_soc",
        name="Battery State of Charge",
        native_unit_of_measurement="%",
        device_class="battery",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="battery_potential_capacity",
        name="Battery Potential Capacity",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="battery_energy",
        name="Current Battery Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="available_energy",
        name="Available Battery Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="grid_power",
        name="Grid Power (Import Positive)",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="grid_import",
        name="Grid Import",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="grid_export",
        name="Grid Export",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="battery_power",
        name="Battery Power (Charge Positive)",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="house_load",
        name="House Load",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="solar_power",
        name="Solar Generation",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="site_grid_current",
        name="Site Grid Current (Import Positive)",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_soc",
        name="EV State of Charge",
        native_unit_of_measurement="%",
        device_class="battery",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_max_power",
        name="EV Maximum Configured Power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(key="ev_control_status", name="EV Control Status"),
    SensorEntityDescription(
        key="ev_current_target",
        name="EV Current Target",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_requested_current",
        name="EV Requested Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_actual_current",
        name="EV Actual Charging Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_charge_limit_target",
        name="EV Charge Limit Target",
        native_unit_of_measurement="%",
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="ev_applied_charge_limit",
        name="EV Applied Charge Limit",
        native_unit_of_measurement="%",
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="ev_grid_current_average",
        name="EV Controller Grid Current Average",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_actual_current_average",
        name="EV Actual Current Average",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_reconciliation_attempts",
        name="EV Reconciliation Attempts",
        state_class="measurement",
    ),
    SensorEntityDescription(
        key="ev_smart_socket_recovery_status",
        name="EV Smart Socket Recovery Status",
    ),
    SensorEntityDescription(key="ev_solar_spill_status", name="EV Solar Spill Status"),
    SensorEntityDescription(
        key="ev_solar_spill_current_target",
        name="EV Solar Spill Current Target",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_solar_spill_surplus",
        name="EV Reconstructed Solar Spill",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(key="ev_pre_free_status", name="EV Pre-Free Status"),
    SensorEntityDescription(
        key="ev_pre_free_planned_energy",
        name="EV Pre-Free Planned Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_pre_free_planned_start",
        name="EV Pre-Free Planned Start",
        device_class="timestamp",
    ),
    SensorEntityDescription(
        key="ev_pre_free_current_target",
        name="EV Pre-Free Current Target",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_daily_backfill_status", name="EV Daily Ready-By Backfill Status"
    ),
    SensorEntityDescription(
        key="ev_daily_backfill_remaining",
        name="EV Daily Backfill Allocation Remaining",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_daily_backfill_delivered",
        name="EV Daily Backfill Delivered",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_daily_backfill_planned_energy",
        name="EV Daily Backfill Planned Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_daily_backfill_shortfall",
        name="EV Daily Backfill Allocation Shortfall",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_daily_backfill_planned_start",
        name="EV Daily Backfill Planned Start",
        device_class="timestamp",
    ),
    SensorEntityDescription(
        key="ev_daily_backfill_current_target",
        name="EV Daily Backfill Current Target",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class="current",
        state_class="measurement",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_daily_driving_energy",
        name="EV Daily Driving Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_driving_p85",
        name="EV Driving P85",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_driving_learning_samples",
        name="EV Driving Learning Samples",
        state_class="measurement",
    ),
    SensorEntityDescription(
        key="ev_usable_capacity",
        name="EV Estimated Usable Capacity",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="ev_free_window_soc_gain",
        name="EV Free Window State of Charge Gain",
        native_unit_of_measurement="%",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="ev_learned_charge_limit",
        name="EV Learned General Charge Limit",
        native_unit_of_measurement="%",
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="ev_driving_learning_status",
        name="EV Driving Learning Status",
    ),
    SensorEntityDescription(
        key="free_energy_remaining",
        name="Free Energy Remaining Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="daily_import",
        name="Grid Import Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        state_class="total_increasing",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="free_window_import",
        name="Free Window Import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        state_class="total_increasing",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="estimated_energy_cost",
        name="Estimated Energy Cost Today",
        icon="mdi:cash",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="free_charge_allowed",
        name="Free Charge Allowance Remaining",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="free_charge_power_target",
        name="Free-Window Battery Charge Power Target",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class="power",
        state_class="measurement",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="free_charge_completion",
        name="Free-Window Battery Charge Status",
        icon="mdi:battery-clock",
    ),
    SensorEntityDescription(
        key="bonus_zero_import_allowed",
        name="ZEROHERO Telemetry Guard Qualified",
        icon="mdi:cash-check",
    ),
    SensorEntityDescription(
        key="zerohero_import_window",
        name="ZEROHERO Import This Window",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        state_class="total_increasing",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(key="tariff_status", name="Tariff Guard Status"),
    SensorEntityDescription(
        key="zerohero_export_window",
        name="ZEROHERO Export This Window",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        state_class="total_increasing",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="zerohero_sellable_energy",
        name="ZEROHERO Sellable Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="zerohero_planned_export_energy",
        name="ZEROHERO Planned Export Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="zerohero_planned_duration",
        name="ZEROHERO Planned Duration",
        native_unit_of_measurement="min",
        device_class="duration",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="zerohero_planned_start",
        name="ZEROHERO Planned Start",
        device_class="timestamp",
    ),
    SensorEntityDescription(key="zerohero_export_status", name="ZEROHERO Export Status"),
    SensorEntityDescription(
        key="ev_before_export_status",
        name="EV Before Export Status",
        icon="mdi:car-arrow-right",
    ),
    SensorEntityDescription(
        key="learned_house_energy",
        name="Protected House Energy Budget",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="learned_base_house_energy",
        name="Learned Base House Energy P80",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="learned_heater_energy",
        name="Learned Heater Energy P80",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="remaining_house_energy",
        name="Remaining House Energy Budget",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class="energy",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="learning_samples",
        name="House Learning Samples",
        state_class="measurement",
    ),
    SensorEntityDescription(key="learning_status", name="House Learning Status"),
    SensorEntityDescription(
        key="heater_learning_samples",
        name="Heater Learning Samples",
        state_class="measurement",
    ),
    SensorEntityDescription(
        key="house_occupancy_state",
        name="House Energy Occupancy State",
        icon="mdi:home-account",
    ),
    SensorEntityDescription(
        key="test_charge_estimated_cost",
        name="Test Charge Estimated Cost",
        icon="mdi:cash-minus",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="test_charge_import_rate",
        name="Test Charge Import Rate",
        native_unit_of_measurement="$/kWh",
        icon="mdi:cash-minus",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="test_discharge_estimated_earning",
        name="Test Discharge Estimated Earning",
        icon="mdi:cash-plus",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="test_discharge_export_rate",
        name="Test Discharge Export Rate",
        native_unit_of_measurement="$/kWh",
        icon="mdi:cash-plus",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(key="test_status", name="Test Status"),
    SensorEntityDescription(
        key="test_remaining_minutes",
        name="Test Remaining",
        native_unit_of_measurement="min",
        suggested_display_precision=2,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: EnergyConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add observer entities."""
    registry = er.async_get(hass)
    for description in DESCRIPTIONS:
        unique_id = f"{entry.entry_id}_{description.key}"
        current_entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        stable_entity_id = f"sensor.home_energy_{description.key}"
        if current_entity_id and current_entity_id != stable_entity_id:
            if registry.async_get(stable_entity_id) is None:
                registry.async_update_entity(current_entity_id, new_entity_id=stable_entity_id)
    async_add_entities(
        EnergySensor(entry.runtime_data, entry, description) for description in DESCRIPTIONS
    )


class EnergySensor(CoordinatorEntity[EnergyCoordinator], SensorEntity):
    """Expose a single calculated ledger term."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: EnergyCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.entity_id = f"sensor.home_energy_{description.key}"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="FoxESS GloBird Tesla Energy Orchestrator",
            model="Energy Orchestrator",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _control_mode(self) -> str:
        """Return the commissioned control surface, not the ledger reason."""
        config = self.coordinator.config
        owner = config.get(CONF_FOXESS_CONTROL_OWNER, DEFAULT_FOXESS_CONTROL_OWNER)
        controller = self.coordinator.active_controller
        foxess_ready = controller is not None and controller.gate_status == "ready"
        charge_enabled = bool(
            config.get(
                CONF_AUTOMATIC_CHARGE_ENABLED,
                DEFAULT_AUTOMATIC_CHARGE_ENABLED,
            )
        )
        export_enabled = bool(config.get(CONF_AUTOMATIC_EXPORT_ENABLED, False))
        if owner == FOXESS_CONTROL_OWNER_CLOUD:
            return "foxcloud_scheduler"
        if foxess_ready and charge_enabled and export_enabled:
            return "local_modbus_charge_and_export"
        if foxess_ready and charge_enabled:
            return "local_modbus_free_charge"
        if foxess_ready and export_enabled:
            return "zerohero_export"
        if foxess_ready:
            return "local_modbus_ready"
        return "observe"

    def _effective_export_plan(self):
        """Expose an export plan only while export is actually permitted."""
        controller = self.coordinator.active_controller
        if (
            controller is None
            or not controller.export_effective_enabled
            or controller.export_plan is None
        ):
            return None
        return controller.export_plan

    def _export_status(self) -> str:
        """Explain whether export is disabled, withheld, or running."""
        controller = self.coordinator.active_controller
        if controller is None:
            return "unavailable"
        if not self.coordinator.config.get(CONF_AUTOMATIC_EXPORT_ENABLED, False):
            return "disabled"
        decision = controller.ev_before_export_decision
        if not decision.export_allowed:
            return f"withheld_{decision.reason}"
        return controller.export_session.phase

    @property
    def native_value(self):
        ledger = self.coordinator.data
        learning = self.coordinator.learning_result
        base_learning = self.coordinator.base_learning_result
        heater_learning = self.coordinator.heater_learning_result
        occupancy = self.coordinator.occupancy_result
        snapshot = self.coordinator.snapshot
        ev_controller = self.coordinator.ev_controller
        now = dt_util.now()
        ev_grid_average = (
            ev_controller.grid_average.result(now) if ev_controller is not None else None
        )
        ev_current_average = (
            ev_controller.ev_average.result(now) if ev_controller is not None else None
        )
        ev_learning = ev_controller.learned_charge_limit if ev_controller is not None else None
        telemetry = self.coordinator.telemetry
        export_plan = self._effective_export_plan()
        values = {
            "status": self._control_mode(),
            "battery_soc": None if snapshot is None else snapshot.battery_soc,
            "battery_potential_capacity": ledger.battery_potential_capacity_kwh,
            "battery_energy": ledger.battery_energy_kwh,
            "available_energy": ledger.available_after_reserve_kwh,
            "grid_power": None if telemetry is None else telemetry.grid_power.value,
            "grid_import": ledger.grid_import_kw,
            "grid_export": ledger.grid_export_kw,
            "battery_power": None if telemetry is None else telemetry.battery_power.value,
            "house_load": None if snapshot is None else snapshot.house_load_kw,
            "solar_power": None if telemetry is None else telemetry.solar_power.value,
            "site_grid_current": (None if telemetry is None else telemetry.site_grid_current.value),
            "ev_soc": None if snapshot is None else snapshot.ev_soc,
            "ev_max_power": ledger.ev_max_power_kw,
            "ev_control_status": (
                ev_controller.last_reason if ev_controller is not None else "unavailable"
            ),
            "ev_current_target": (
                ev_controller.target_current_a if ev_controller is not None else None
            ),
            "ev_requested_current": (
                ev_controller.requested_current_a if ev_controller is not None else None
            ),
            "ev_actual_current": (
                ev_controller.actual_current_a if ev_controller is not None else None
            ),
            "ev_charge_limit_target": (
                ev_controller.target_limit_percent if ev_controller is not None else None
            ),
            "ev_applied_charge_limit": (
                ev_controller.applied_limit_percent if ev_controller is not None else None
            ),
            "ev_grid_current_average": (
                ev_grid_average.value if ev_grid_average is not None else None
            ),
            "ev_actual_current_average": (
                ev_current_average.value if ev_current_average is not None else None
            ),
            "ev_reconciliation_attempts": (
                ev_controller.reconciliation.attempts if ev_controller is not None else 0
            ),
            "ev_smart_socket_recovery_status": (
                ev_controller.smart_recovery.phase if ev_controller is not None else "unavailable"
            ),
            "ev_solar_spill_status": (
                ev_controller.solar_spill.phase if ev_controller is not None else "unavailable"
            ),
            "ev_solar_spill_current_target": (
                ev_controller.solar_spill.current_a if ev_controller is not None else None
            ),
            "ev_solar_spill_surplus": (
                ev_controller.solar_spill.reconstructed_surplus_kw
                if ev_controller is not None
                else None
            ),
            "ev_pre_free_status": (
                ev_controller.pre_free_phase if ev_controller is not None else "unavailable"
            ),
            "ev_pre_free_planned_energy": (
                ev_controller.pre_free_plan.planned_energy_kwh
                if ev_controller is not None and ev_controller.pre_free_plan is not None
                else None
            ),
            "ev_pre_free_planned_start": (
                ev_controller.pre_free_plan.planned_start
                if ev_controller is not None and ev_controller.pre_free_plan is not None
                else None
            ),
            "ev_pre_free_current_target": (
                ev_controller.pre_free_current_a if ev_controller is not None else None
            ),
            "ev_daily_backfill_status": (
                "active"
                if ev_controller is not None and ev_controller.daily_backfill_active
                else ev_controller.daily_backfill_plan.phase
                if ev_controller is not None and ev_controller.daily_backfill_plan is not None
                else "disabled"
            ),
            "ev_daily_backfill_remaining": (
                ev_controller.daily_backfill_plan.remaining_allocation_kwh
                if ev_controller is not None and ev_controller.daily_backfill_plan is not None
                else None
            ),
            "ev_daily_backfill_delivered": (
                ev_controller.daily_backfill_delivered_kwh if ev_controller is not None else None
            ),
            "ev_daily_backfill_planned_energy": (
                ev_controller.daily_backfill_plan.planned_energy_kwh
                if ev_controller is not None and ev_controller.daily_backfill_plan is not None
                else None
            ),
            "ev_daily_backfill_shortfall": (
                ev_controller.daily_backfill_plan.allocation_shortfall_kwh
                if ev_controller is not None and ev_controller.daily_backfill_plan is not None
                else None
            ),
            "ev_daily_backfill_planned_start": (
                ev_controller.daily_backfill_frozen_start
                if ev_controller is not None and ev_controller.daily_backfill_active
                else ev_controller.daily_backfill_plan.planned_start
                if ev_controller is not None and ev_controller.daily_backfill_plan is not None
                else None
            ),
            "ev_daily_backfill_current_target": (
                ev_controller.daily_backfill_plan.current_ceiling_a
                if ev_controller is not None and ev_controller.daily_backfill_plan is not None
                else None
            ),
            "ev_daily_driving_energy": (
                ev_controller.daily_driving_energy_kwh if ev_controller is not None else None
            ),
            "ev_driving_p85": (
                ev_learning.p85_daily_energy_kwh if ev_learning is not None else None
            ),
            "ev_driving_learning_samples": (
                len(ev_controller.driving_history.samples) if ev_controller is not None else 0
            ),
            "ev_usable_capacity": (
                ev_learning.usable_capacity_kwh if ev_learning is not None else None
            ),
            "ev_free_window_soc_gain": (
                ev_learning.free_window_soc_gain_percent if ev_learning is not None else None
            ),
            "ev_learned_charge_limit": (
                ev_learning.limit_percent if ev_learning is not None else None
            ),
            "ev_driving_learning_status": (
                ev_learning.mode if ev_learning is not None else "unavailable"
            ),
            "free_energy_remaining": ledger.free_energy_remaining_kwh,
            "daily_import": ledger.daily_import_kwh,
            "free_window_import": ledger.free_window_import_kwh,
            # Cost has no Home Assistant unit (it is site-currency specific),
            # so round the state itself rather than relying on display hints.
            "estimated_energy_cost": (
                None
                if ledger.estimated_energy_cost is None
                else round(ledger.estimated_energy_cost, 2)
            ),
            "free_charge_allowed": ledger.free_charge_allowed_kwh,
            "free_charge_power_target": (
                None
                if self.coordinator.active_controller is None
                else self.coordinator.active_controller.charge_power_target_kw
            ),
            "free_charge_completion": (
                "unavailable"
                if self.coordinator.active_controller is None
                else self.coordinator.active_controller.charge_session.phase
            ),
            "bonus_zero_import_allowed": ledger.bonus_zero_import_allowed,
            "zerohero_import_window": (
                None
                if self.coordinator.zerohero_import.last_at is None
                else round(sum(self.coordinator.zerohero_import.hourly_import_kwh.values()), 3)
            ),
            "tariff_status": ledger.tariff_reason,
            "zerohero_export_window": round(self.coordinator.zerohero_export.imported_kwh, 3),
            "zerohero_sellable_energy": (
                None
                if self.coordinator.active_controller is None
                or self.coordinator.active_controller.export_plan is None
                else self.coordinator.active_controller.export_plan.sellable_energy_kwh
            ),
            "zerohero_planned_export_energy": (
                None if export_plan is None else export_plan.planned_export_energy_kwh
            ),
            "zerohero_planned_duration": (
                None if export_plan is None else round(export_plan.planned_duration_h * 60, 1)
            ),
            "zerohero_planned_start": (
                None
                if export_plan is None or self.coordinator.active_controller is None
                else self.coordinator.active_controller.export_planned_start
            ),
            "zerohero_export_status": self._export_status(),
            "ev_before_export_status": (
                "unavailable"
                if self.coordinator.active_controller is None
                else self.coordinator.active_controller.ev_before_export_decision.reason
            ),
            "learned_house_energy": learning.cycle_budget_kwh,
            "learned_base_house_energy": base_learning.cycle_budget_kwh,
            "learned_heater_energy": (
                None if heater_learning is None else heater_learning.cycle_budget_kwh
            ),
            "remaining_house_energy": self.coordinator.learning_remaining_kwh,
            "learning_samples": learning.sample_count,
            "learning_status": learning.model,
            "heater_learning_samples": learning.heater_sample_count,
            "house_occupancy_state": occupancy.state,
            "test_charge_estimated_cost": self.coordinator.manual_test.preview_charge().amount,
            "test_charge_import_rate": self.coordinator.manual_test.current_import_rate(),
            "test_discharge_estimated_earning": (
                self.coordinator.manual_test.preview_discharge().amount
            ),
            "test_discharge_export_rate": self.coordinator.manual_test.current_export_rate(),
            "test_status": self.coordinator.manual_test.status,
            "test_remaining_minutes": self.coordinator.manual_test.remaining_minutes,
        }
        return values[self.entity_description.key]

    @property
    def extra_state_attributes(self):
        telemetry_samples = (
            {
                "grid_power": self.coordinator.telemetry.grid_power,
                "battery_power": self.coordinator.telemetry.battery_power,
                "solar_power": self.coordinator.telemetry.solar_power,
                "house_load": self.coordinator.telemetry.house_load,
                "site_grid_current": self.coordinator.telemetry.site_grid_current,
            }
            if self.coordinator.telemetry is not None
            else {}
        )
        if sample := telemetry_samples.get(self.entity_description.key):
            return {
                "positive_direction": sample.positive_direction,
                "valid": sample.valid,
                "fresh": sample.fresh,
                "reason": sample.reason,
                "sources": [
                    {
                        "entity_id": source.entity_id,
                        "raw_value": source.raw_value,
                        "raw_unit": source.raw_unit,
                        "updated_at": (
                            source.updated_at.isoformat() if source.updated_at is not None else None
                        ),
                    }
                    for source in sample.sources
                ],
            }
        if self.entity_description.key == "zerohero_import_window":
            accumulator = self.coordinator.zerohero_import
            return {
                "hourly_import_kwh": {
                    bucket: round(value, 6)
                    for bucket, value in accumulator.hourly_import_kwh.items()
                },
                "accumulator_date": (
                    None if accumulator.local_date is None else accumulator.local_date.isoformat()
                ),
                "last_sample": (
                    None if accumulator.last_at is None else accumulator.last_at.isoformat()
                ),
                "threshold_kwh_per_hour": self.coordinator.config.get(
                    CONF_ZERO_IMPORT_THRESHOLD_KW, DEFAULT_ZERO_IMPORT_THRESHOLD_KW
                ),
            }
        if self.entity_description.key == "ev_control_status":
            controller = self.coordinator.ev_controller
            if controller is None:
                return {"gate": "unavailable"}
            now = dt_util.now()
            grid = controller.grid_average.result(now)
            actual = controller.ev_average.result(now)
            return {
                "gate": controller.gate_status,
                "decision_phase": controller.decision_phase,
                "allowance_phase": controller.allowance_phase,
                "allowance_house_load_kw": controller.allowance_house_load_kw,
                "allowance_ev_power_kw": controller.allowance_ev_power_kw,
                "target_current_a": controller.target_current_a,
                "target_limit_percent": controller.target_limit_percent,
                "requested_current_a": controller.requested_current_a,
                "actual_current_a": controller.actual_current_a,
                "applied_limit_percent": controller.applied_limit_percent,
                "charge_switch_on": controller.charge_switch_on,
                "reconciliation_phase": controller.reconciliation.phase,
                "reconciliation_attempts": controller.reconciliation.attempts,
                "maximum_reconciliation_attempts": DIRECT_EVSE_MAX_ATTEMPTS,
                "smart_socket_recovery_phase": controller.smart_recovery.phase,
                "smart_socket_recovery_attempted": controller.smart_recovery.attempted,
                "smart_socket_recovery_started_at": (controller.smart_recovery.phase_started_at),
                "smart_socket_recovery_current_a": (controller.smart_recovery.recovery_current_a),
                "grid_average_coverage": grid.age_coverage_ratio,
                "grid_source_valid": grid.source_value_valid,
                "ev_average_source_valid": actual.source_value_valid,
                "last_actions": controller.last_actions,
                "writes_performed": controller.writes_performed,
                "last_write_at": controller.last_write_at,
                "solar_spill_phase": controller.solar_spill.phase,
                "solar_spill_current_a": controller.solar_spill.current_a,
                "solar_spill_reconstructed_kw": (controller.solar_spill.reconstructed_surplus_kw),
                "pre_free_session_active": controller.pre_free_session.active,
                "pre_free_phase": controller.pre_free_phase,
                "pre_free_frozen_start": controller.pre_free_session.frozen_start,
                "pre_free_planned_energy_kwh": (
                    controller.pre_free_plan.planned_energy_kwh
                    if controller.pre_free_plan is not None
                    else None
                ),
                "pre_free_planned_start": (
                    controller.pre_free_plan.planned_start
                    if controller.pre_free_plan is not None
                    else None
                ),
                "pre_free_current_a": controller.pre_free_current_a,
                "outside_control_active": controller.outside_control_active,
                "daily_backfill_active": controller.daily_backfill_active,
                "daily_backfill_cycle_ready_at": (controller.daily_backfill_cycle_ready_at),
                "daily_backfill_delivered_kwh": (controller.daily_backfill_delivered_kwh),
                "daily_backfill_session_target_kwh": (controller.daily_backfill_session_target_kwh),
                "daily_backfill_frozen_start": controller.daily_backfill_frozen_start,
                "charge_to_full_started_at": controller.charge_to_full_started_at,
                "driving_learning_mode": (
                    controller.learned_charge_limit.mode
                    if controller.learned_charge_limit is not None
                    else "unavailable"
                ),
                "driving_learning_samples": len(controller.driving_history.samples),
                "driving_p85_kwh": (
                    controller.learned_charge_limit.p85_daily_energy_kwh
                    if controller.learned_charge_limit is not None
                    else None
                ),
                "learned_general_limit_percent": (
                    controller.learned_charge_limit.limit_percent
                    if controller.learned_charge_limit is not None
                    else None
                ),
            }
        if self.entity_description.key == "house_occupancy_state":
            occupancy = self.coordinator.occupancy_result
            return {
                "selected_mode": occupancy.selected_mode,
                "person_entities_found": occupancy.person_count,
                "people_home": occupancy.people_home,
                "all_people_away_for_hours": occupancy.all_people_away_for_hours,
                "reason": occupancy.reason,
            }
        if self.entity_description.key != "status":
            return None
        learning = self.coordinator.learning_result
        foxess_requested = bool(self.coordinator.config.get(CONF_AUTOMATIC_CONTROL_ENABLED, False))
        charge_enabled = bool(
            self.coordinator.config.get(
                CONF_AUTOMATIC_CHARGE_ENABLED,
                DEFAULT_AUTOMATIC_CHARGE_ENABLED,
            )
        )
        foxess_owner = self.coordinator.config.get(
            CONF_FOXESS_CONTROL_OWNER, DEFAULT_FOXESS_CONTROL_OWNER
        )
        foxess_gate = (
            self.coordinator.active_controller.gate_status
            if self.coordinator.active_controller
            else "unavailable"
        )
        foxess_enabled = foxess_gate == "ready"
        export_enabled = bool(self.coordinator.config.get(CONF_AUTOMATIC_EXPORT_ENABLED, False))
        ev_requested = bool(self.coordinator.config.get(CONF_EV_AUTOMATIC_CONTROL_ENABLED, False))
        ev_controller = self.coordinator.ev_controller
        ev_gate = (
            ev_controller.gate_status
            if ev_controller is not None
            else ev_control_gate_status(self.coordinator.config)
        )
        return {
            "mode": self._control_mode(),
            "ledger_status": self.coordinator.data.reason,
            "control_gate": foxess_gate,
            "last_control_reason": (
                self.coordinator.active_controller.last_reason
                if self.coordinator.active_controller
                else "unavailable"
            ),
            "last_control_actions": (
                self.coordinator.active_controller.last_actions
                if self.coordinator.active_controller
                else ()
            ),
            "writes_performed": (
                self.coordinator.active_controller.writes_performed
                if self.coordinator.active_controller
                else 0
            ),
            "automatic_control_enabled": foxess_requested,
            "automatic_charge_enabled": charge_enabled,
            "free_charge_schedule_confirmed": bool(
                self.coordinator.config.get(CONF_FREE_CHARGE_SCHEDULE_CONFIRMED, False)
            ),
            "sign_conventions_verified": bool(
                self.coordinator.config.get(
                    CONF_SIGN_CONVENTIONS_VERIFIED,
                    DEFAULT_SIGN_CONVENTIONS_VERIFIED,
                )
            ),
            "foxess_modbus_control_effective": foxess_enabled,
            "foxess_control_owner": foxess_owner,
            "automatic_export_enabled": export_enabled,
            "automatic_export_effective": (
                self.coordinator.active_controller.export_effective_enabled
                if self.coordinator.active_controller
                else False
            ),
            "ev_before_export_status": (
                self.coordinator.active_controller.ev_before_export_decision.reason
                if self.coordinator.active_controller
                else "unavailable"
            ),
            "ev_automatic_control_enabled": ev_requested,
            "ev_control_gate": ev_gate,
            "ev_writes_enabled": ev_gate == "ready",
            "ev_last_control_reason": (
                ev_controller.last_reason if ev_controller is not None else "unavailable"
            ),
            "ev_last_control_actions": (
                ev_controller.last_actions if ev_controller is not None else ()
            ),
            "ev_writes_performed": (
                ev_controller.writes_performed if ev_controller is not None else 0
            ),
            "ev_decision_phase": (
                ev_controller.decision_phase if ev_controller is not None else "unavailable"
            ),
            "ev_allowance_phase": (
                ev_controller.allowance_phase if ev_controller is not None else "unavailable"
            ),
            "ev_target_current_a": (
                ev_controller.target_current_a if ev_controller is not None else None
            ),
            "ev_target_limit_percent": (
                ev_controller.target_limit_percent if ev_controller is not None else None
            ),
            "ev_reconciliation_phase": (
                ev_controller.reconciliation.phase if ev_controller is not None else "unavailable"
            ),
            "ev_reconciliation_attempts": (
                ev_controller.reconciliation.attempts if ev_controller is not None else 0
            ),
            "ev_last_write_at": (
                ev_controller.last_write_at if ev_controller is not None else None
            ),
            "ev_driving_learning_mode": (
                ev_controller.learned_charge_limit.mode
                if ev_controller is not None and ev_controller.learned_charge_limit is not None
                else "unavailable"
            ),
            "ev_driving_learning_samples": (
                len(ev_controller.driving_history.samples) if ev_controller is not None else 0
            ),
            "ev_learned_general_limit_percent": (
                ev_controller.learned_charge_limit.limit_percent
                if ev_controller is not None and ev_controller.learned_charge_limit is not None
                else None
            ),
            "export_session_phase": (
                self.coordinator.active_controller.export_session.phase
                if self.coordinator.active_controller
                else "unavailable"
            ),
            "charge_session_phase": (
                self.coordinator.active_controller.charge_session.phase
                if self.coordinator.active_controller
                else "unavailable"
            ),
            "charge_power_target_kw": (
                self.coordinator.active_controller.charge_power_target_kw
                if self.coordinator.active_controller
                else None
            ),
            "export_allowance_remaining_kwh": (
                self.coordinator.active_controller.export_allowance_remaining_kwh
                if self.coordinator.active_controller
                else None
            ),
            "export_protected_ev_kwh": (
                self.coordinator.active_controller.export_protected_ev_kwh
                if self.coordinator.active_controller
                else None
            ),
            "rehearsal_mode": self.coordinator.config.get(CONF_REHEARSAL_MODE, True),
            "integration": DOMAIN,
            "learning_model": learning.model,
            "learning_samples": learning.sample_count,
            "heater_learning_samples": learning.heater_sample_count,
            "house_occupancy": learning.occupancy,
            "house_occupancy_reason": self.coordinator.occupancy_result.reason,
            "learning_max_age_days": self.coordinator.demand_history.max_age_days,
            "learning_sample_limit": self.coordinator.demand_history.sample_limit,
            "learning_sampler_enabled": self.coordinator.demand_sampler is not None,
        }
