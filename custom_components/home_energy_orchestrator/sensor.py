"""Observer entities for the public, compact v0.1 surface."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import EnergyConfigEntry
from .const import DOMAIN
from .coordinator import EnergyCoordinator
from .entity_catalogue import SENSOR_DESCRIPTIONS as DESCRIPTIONS
from .ev_adapter import ev_control_gate_status
from .read_model import (
    build_site_read_model,
    control_mode,
    effective_export_plan,
    export_status,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: EnergyConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add observer entities."""
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
        return control_mode(self.coordinator)

    def _effective_export_plan(self):
        """Expose an export plan only while export is actually permitted."""
        return effective_export_plan(self.coordinator)

    def _export_status(self) -> str:
        """Explain whether export is disabled, withheld, or running."""
        return export_status(self.coordinator)

    def _fleet_summary_attributes(self) -> dict[str, object]:
        """Return one compact, read-only payload for a monitoring hub."""
        return build_site_read_model(self.coordinator).fleet_attributes(dt_util.now())

    @property
    def native_value(self):
        ledger = self.coordinator.data
        telemetry = self.coordinator.telemetry
        read_model = build_site_read_model(self.coordinator)
        values = {
            **read_model.sensor_values(),
            "battery_potential_capacity": ledger.battery_potential_capacity_kwh,
            "battery_energy": ledger.battery_energy_kwh,
            "available_energy": ledger.available_after_reserve_kwh,
            "grid_import": ledger.grid_import_kw,
            "grid_export": ledger.grid_export_kw,
            "site_grid_current": (None if telemetry is None else telemetry.site_grid_current.value),
            "free_energy_remaining": ledger.free_energy_remaining_kwh,
            "daily_import": ledger.daily_import_kwh,
            "free_window_import": ledger.free_window_import_kwh,
            "daily_export": ledger.daily_export_kwh,
            "standard_export_window": ledger.standard_window_export_kwh,
            "offpeak_export": ledger.offpeak_rate_export_kwh,
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
            "ev_before_export_status": (
                "unavailable"
                if self.coordinator.active_controller is None
                else self.coordinator.active_controller.ev_before_export_decision.reason
            ),
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
        if self.entity_description.key == "fleet_summary":
            return self._fleet_summary_attributes()
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
                "threshold_kwh_per_hour": (
                    self.coordinator.runtime_config.tariff.zero_import_threshold_kwh_per_hour
                ),
            }
        if self.entity_description.key == "estimated_export_revenue":
            ledger = self.coordinator.data
            tariff = self.coordinator.runtime_config.tariff
            standard_rate = tariff.peak_export_rate_per_kwh
            boost_rate = tariff.additional_export_rate_per_kwh
            offpeak_rate = tariff.offpeak_export_rate_per_kwh
            return {
                "standard_rate_export_kwh": ledger.standard_rate_export_kwh,
                "offpeak_rate_export_kwh": ledger.offpeak_rate_export_kwh,
                "standard_window_export_kwh": ledger.standard_window_export_kwh,
                "boosted_rate_export_kwh": ledger.boosted_rate_export_kwh,
                "boosted_window_export_kwh": ledger.boosted_window_export_kwh,
                "standard_rate_per_kwh": standard_rate,
                "offpeak_rate_per_kwh": offpeak_rate,
                "additional_boost_rate_per_kwh": boost_rate,
                "standard_export_revenue": (
                    None
                    if ledger.standard_rate_export_kwh is None
                    else round(ledger.standard_rate_export_kwh * standard_rate, 4)
                ),
                "offpeak_export_revenue": (
                    None
                    if ledger.offpeak_rate_export_kwh is None
                    else round(ledger.offpeak_rate_export_kwh * offpeak_rate, 4)
                ),
                "boosted_bonus_revenue": (
                    None
                    if ledger.boosted_rate_export_kwh is None
                    else round(ledger.boosted_rate_export_kwh * boost_rate, 4)
                ),
            }
        if self.entity_description.key == "estimated_net_cost":
            return build_site_read_model(self.coordinator).cost.sensor_attributes()
        if self.entity_description.key in {
            "forecast_yesterday_cost",
            "globird_yesterday_actual_cost",
            "forecast_error_yesterday",
            "forecast_scorecard_status",
        }:
            return build_site_read_model(self.coordinator).scorecard.sensor_attributes()
        if self.entity_description.key == "ev_control_status":
            return build_site_read_model(self.coordinator).ev.control_attributes()
        if self.entity_description.key == "house_occupancy_state":
            return build_site_read_model(self.coordinator).learning.occupancy_attributes()
        if self.entity_description.key != "status":
            return None
        read_model = build_site_read_model(self.coordinator)
        automation = self.coordinator.runtime_config.automation
        foxess_requested = automation.master_enabled
        charge_enabled = automation.battery_charge_enabled
        foxess_owner = automation.control_owner
        foxess_gate = (
            self.coordinator.active_controller.gate_status
            if self.coordinator.active_controller
            else "unavailable"
        )
        foxess_enabled = foxess_gate == "ready"
        export_enabled = automation.battery_export_enabled
        ev_requested = automation.ev_control_enabled
        ev_controller = self.coordinator.ev_controller
        ev_gate = (
            ev_controller.gate_status
            if ev_controller is not None
            else ev_control_gate_status(self.coordinator.runtime_config)
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
            "free_charge_schedule_confirmed": automation.free_charge_schedule_confirmed,
            "sign_conventions_verified": self.coordinator.runtime_config.electrical.verified,
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
                self.coordinator.active_controller.automatic_export_remaining_kwh
                if self.coordinator.active_controller
                else None
            ),
            # Preserve the legacy attribute above for dashboard compatibility.
            "automatic_export_remaining_kwh": (
                self.coordinator.active_controller.automatic_export_remaining_kwh
                if self.coordinator.active_controller
                else None
            ),
            "export_protected_ev_kwh": (
                self.coordinator.active_controller.export_protected_ev_kwh
                if self.coordinator.active_controller
                else None
            ),
            "rehearsal_mode": automation.safety_lock,
            "integration": DOMAIN,
            "learning_model": read_model.learning.model,
            "learning_samples": read_model.learning.sample_count,
            "heater_learning_samples": read_model.learning.heater_sample_count,
            "house_occupancy": read_model.learning.budget_occupancy,
            "house_occupancy_reason": read_model.learning.occupancy_reason,
            "learning_max_age_days": self.coordinator.demand_history.max_age_days,
            "learning_sample_limit": self.coordinator.demand_history.sample_limit,
            "learning_sampler_enabled": self.coordinator.demand_sampler is not None,
        }
