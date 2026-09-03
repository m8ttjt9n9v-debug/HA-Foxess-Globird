"""Typed, Home-Assistant-independent planner models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SiteSnapshot:
    """Normalised site measurements. Power is kW, energy kWh and SOC percent."""

    battery_soc: float | None
    battery_capacity_kwh: float
    battery_floor_percent: float
    reserve_kwh: float
    grid_power_kw: float | None
    house_load_kw: float | None
    ev_soc: float | None = None
    ev_min_current_a: float = 0.0
    ev_max_current_a: float = 0.0
    ev_voltage_v: float = 230.0
    ev_phase_count: int = 1
    site_phase_count: int = 1
    service_import_limit_a: float = 0.0
    export_limit_kw: float = 0.0
    inverter_charge_limit_kw: float = 0.0
    inverter_discharge_limit_kw: float = 0.0


@dataclass(frozen=True, slots=True)
class EnergyLedger:
    """A conservative, single-counted energy ledger."""

    battery_energy_kwh: float | None
    battery_potential_capacity_kwh: float | None
    floor_energy_kwh: float
    available_after_floor_kwh: float | None
    available_after_reserve_kwh: float | None
    grid_import_kw: float | None
    grid_export_kw: float | None
    house_load_kw: float | None
    ev_max_power_kw: float
    reason: str
    free_energy_remaining_kwh: float | None = None
    free_charge_allowed_kwh: float | None = None
    bonus_zero_import_allowed: bool | None = None
    tariff_reason: str = "daily_import_meter_unavailable"
    daily_import_kwh: float | None = None
    daily_import_source: str = "unavailable"
    free_window_import_kwh: float | None = None
    estimated_energy_cost: float | None = None
