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
from .const import DOMAIN, FOXESS_CONTROL_OWNER_CLOUD
from .coordinator import EnergyCoordinator
from .entity_catalogue import SENSOR_DESCRIPTIONS as DESCRIPTIONS
from .ev_adapter import ev_control_gate_status
from .planner.ev import DIRECT_EVSE_MAX_ATTEMPTS


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
        automation = self.coordinator.runtime_config.automation
        owner = automation.control_owner
        controller = self.coordinator.active_controller
        if (
            controller is not None
            and getattr(controller, "ownership_status", None) == "ownership_unknown"
        ):
            return "ownership_unknown"
        foxess_ready = controller is not None and controller.gate_status == "ready"
        charge_enabled = automation.battery_charge_enabled
        export_enabled = automation.battery_export_enabled
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
        if not self.coordinator.runtime_config.automation.battery_export_enabled:
            return "disabled"
        decision = controller.ev_before_export_decision
        if not decision.export_allowed:
            return f"withheld_{decision.reason}"
        return controller.export_session.phase

    def _fleet_summary_attributes(self) -> dict[str, object]:
        """Return one compact, read-only payload for a monitoring hub."""
        coordinator = self.coordinator
        ledger = coordinator.data
        snapshot = coordinator.snapshot
        telemetry = coordinator.telemetry
        controller = coordinator.active_controller
        ev_controller = coordinator.ev_controller
        forecast = coordinator.optimistic_forecast
        export_plan = self._effective_export_plan()
        candidate_export_plan = (
            controller.export_plan if controller is not None else None
        )
        scorecard = (
            coordinator.forecast_feedback.record_for(
                coordinator.forecast_scorecard_date
            )
            if coordinator.forecast_scorecard_date is not None
            else None
        )

        def rounded(value: float | None, digits: int = 3) -> float | None:
            return None if value is None else round(float(value), digits)

        return {
            "summary_schema_version": 1,
            "battery_soc": rounded(
                None if snapshot is None else snapshot.battery_soc, 2
            ),
            "battery_power_kw": rounded(
                None if telemetry is None else telemetry.battery_power.value
            ),
            "grid_power_kw": rounded(
                None if telemetry is None else telemetry.grid_power.value
            ),
            "solar_power_kw": rounded(
                None if telemetry is None else telemetry.solar_power.value
            ),
            "house_load_kw": rounded(
                None if snapshot is None else snapshot.house_load_kw
            ),
            "sellable_energy_kwh": rounded(
                None
                if candidate_export_plan is None
                else candidate_export_plan.sellable_energy_kwh
            ),
            "planned_export_kwh": rounded(
                None if export_plan is None else export_plan.planned_export_energy_kwh
            ),
            "orchestrator_status": self._control_mode(),
            "foxess_control_gate": (
                "unavailable" if controller is None else controller.gate_status
            ),
            "charging_status": (
                "unavailable" if controller is None else controller.charge_session.phase
            ),
            "export_status": self._export_status(),
            "ev_control_status": (
                "unavailable" if ev_controller is None else ev_controller.last_reason
            ),
            "forecast_cost": rounded(
                None if forecast is None else forecast.calibrated_net_cost, 2
            ),
            "measured_cost": rounded(ledger.estimated_net_cost, 2),
            "latest_actual_cost": rounded(
                None if scorecard is None else scorecard.retailer_actual_cost, 2
            ),
            "forecast_error": rounded(
                None if scorecard is None else scorecard.forecast_error, 2
            ),
            "zerohero_status": ledger.zerohero_credit_status,
            "latest_zerohero_status": (
                None if scorecard is None else scorecard.retailer_zerohero_status
            ),
            "forecast_scorecard_status": coordinator.forecast_scorecard_status,
            "house_learning_samples": coordinator.learning_result.sample_count,
            "ev_learning_samples": (
                0 if ev_controller is None else len(ev_controller.driving_history.samples)
            ),
            "ledger_status": ledger.reason,
            "tariff_status": ledger.tariff_reason,
            "last_update": dt_util.now().isoformat(),
        }

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
        forecast = self.coordinator.optimistic_forecast
        scorecard_record = (
            self.coordinator.forecast_feedback.record_for(
                self.coordinator.forecast_scorecard_date
            )
            if self.coordinator.forecast_scorecard_date is not None
            else None
        )
        export_plan = self._effective_export_plan()
        values = {
            "status": self._control_mode(),
            "fleet_summary": self._control_mode(),
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
            "daily_export": ledger.daily_export_kwh,
            "standard_export_window": ledger.standard_window_export_kwh,
            "offpeak_export": ledger.offpeak_rate_export_kwh,
            # Cost has no Home Assistant unit (it is site-currency specific),
            # so round the state itself rather than relying on display hints.
            "estimated_energy_cost": (
                None
                if ledger.estimated_energy_cost is None
                else round(ledger.estimated_energy_cost, 2)
            ),
            "estimated_import_energy_cost": (
                None
                if ledger.estimated_import_energy_cost is None
                else round(ledger.estimated_import_energy_cost, 2)
            ),
            "daily_supply_charge": (
                None
                if ledger.daily_supply_charge is None
                else round(ledger.daily_supply_charge, 2)
            ),
            "estimated_export_revenue": (
                None
                if ledger.estimated_export_revenue is None
                else round(ledger.estimated_export_revenue, 2)
            ),
            "zerohero_credit": (
                None if ledger.zerohero_credit is None else round(ledger.zerohero_credit, 2)
            ),
            "zerohero_credit_status": ledger.zerohero_credit_status,
            "estimated_net_cost": (
                None if forecast is None else round(forecast.calibrated_net_cost, 2)
            ),
            "measured_net_cost": (
                None
                if ledger.estimated_net_cost is None
                else round(ledger.estimated_net_cost, 2)
            ),
            "forecast_export_realisation": round(
                self.coordinator.forecast_feedback.export_realisation_fraction * 100,
                1,
            ),
            "forecast_yesterday_cost": (
                None
                if scorecard_record is None
                else scorecard_record.frozen_forecast_cost
            ),
            "globird_yesterday_actual_cost": (
                None
                if scorecard_record is None
                else scorecard_record.retailer_actual_cost
            ),
            "forecast_error_yesterday": (
                None if scorecard_record is None else scorecard_record.forecast_error
            ),
            "forecast_scorecard_status": self.coordinator.forecast_scorecard_status,
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
            ledger = self.coordinator.data
            forecast = self.coordinator.optimistic_forecast
            return {
                "gross_cost": ledger.estimated_energy_cost,
                "measured_export_revenue": ledger.estimated_export_revenue,
                "measured_zerohero_credit": ledger.zerohero_credit,
                "measured_net_cost": ledger.estimated_net_cost,
                "assumed_zerohero_credit": (
                    None if forecast is None else forecast.assumed_zerohero_credit
                ),
                "export_realisation_percent": (
                    None
                    if forecast is None
                    else round(forecast.export_realisation_fraction * 100, 1)
                ),
                "forecast_remaining_export_kwh": (
                    None if forecast is None else forecast.forecast_remaining_export_kwh
                ),
                "forecast_additional_export_revenue": (
                    None
                    if forecast is None
                    else forecast.forecast_additional_export_revenue
                ),
                "raw_optimistic_forecast": (
                    None if forecast is None else forecast.raw_net_cost
                ),
                "learned_cost_bias": (
                    None if forecast is None else forecast.learned_cost_bias
                ),
            }
        if self.entity_description.key in {
            "forecast_yesterday_cost",
            "globird_yesterday_actual_cost",
            "forecast_error_yesterday",
            "forecast_scorecard_status",
        }:
            result_date = self.coordinator.forecast_scorecard_date
            record = (
                self.coordinator.forecast_feedback.record_for(result_date)
                if result_date is not None
                else None
            )
            return {
                "result_date": None if result_date is None else result_date.isoformat(),
                "forecast_cost": (
                    None if record is None else record.frozen_forecast_cost
                ),
                "raw_forecast_cost": (
                    None if record is None else record.frozen_raw_forecast_cost
                ),
                "actual_cost": (
                    None if record is None else record.retailer_actual_cost
                ),
                "forecast_error": None if record is None else record.forecast_error,
                "zerohero_status": (
                    None if record is None else record.retailer_zerohero_status
                ),
                "planned_export_kwh": (
                    None if record is None else record.planned_export_kwh
                ),
                "realised_export_kwh": (
                    None if record is None else record.realised_export_kwh
                ),
                "export_realisation_ratio": (
                    None if record is None else record.export_realisation_ratio
                ),
                "forecast_feedback_applied": (
                    False if record is None else record.feedback_applied
                ),
                "learned_export_realisation_percent": round(
                    self.coordinator.forecast_feedback.export_realisation_fraction * 100,
                    1,
                ),
                "learned_cost_bias": self.coordinator.forecast_feedback.learned_cost_bias,
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
            "learning_model": learning.model,
            "learning_samples": learning.sample_count,
            "heater_learning_samples": learning.heater_sample_count,
            "house_occupancy": learning.occupancy,
            "house_occupancy_reason": self.coordinator.occupancy_result.reason,
            "learning_max_age_days": self.coordinator.demand_history.max_age_days,
            "learning_sample_limit": self.coordinator.demand_history.sample_limit,
            "learning_sampler_enabled": self.coordinator.demand_sampler is not None,
        }
