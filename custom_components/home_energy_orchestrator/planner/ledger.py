"""Single-ledger calculation used by observer and future actuator layers."""

from __future__ import annotations

from ..const import REASON_MISSING_BATTERY_SOC, REASON_MISSING_GRID_POWER, REASON_OBSERVER_ONLY
from ..models import EnergyLedger, SiteSnapshot


def calculate_ledger(snapshot: SiteSnapshot) -> EnergyLedger:
    """Calculate available battery energy, subtracting floor and reserve once."""
    floor_energy = snapshot.battery_capacity_kwh * snapshot.battery_floor_percent / 100
    battery_energy = (
        snapshot.battery_capacity_kwh * snapshot.battery_soc / 100
        if snapshot.battery_soc is not None
        else None
    )
    after_floor = max(0.0, battery_energy - floor_energy) if battery_energy is not None else None
    after_reserve = (
        max(0.0, after_floor - snapshot.reserve_kwh) if after_floor is not None else None
    )
    grid_import = max(0.0, snapshot.grid_power_kw) if snapshot.grid_power_kw is not None else None
    grid_export = max(0.0, -snapshot.grid_power_kw) if snapshot.grid_power_kw is not None else None
    ev_max_power = (
        snapshot.ev_max_current_a * snapshot.ev_voltage_v * snapshot.ev_phase_count / 1000
    )
    if snapshot.battery_soc is None:
        reason = REASON_MISSING_BATTERY_SOC
    elif snapshot.grid_power_kw is None:
        reason = REASON_MISSING_GRID_POWER
    else:
        reason = REASON_OBSERVER_ONLY
    return EnergyLedger(
        battery_energy_kwh=battery_energy,
        battery_potential_capacity_kwh=snapshot.battery_capacity_kwh,
        floor_energy_kwh=floor_energy,
        available_after_floor_kwh=after_floor,
        available_after_reserve_kwh=after_reserve,
        grid_import_kw=grid_import,
        grid_export_kw=grid_export,
        house_load_kw=snapshot.house_load_kw,
        ev_max_power_kw=ev_max_power,
        reason=reason,
    )
