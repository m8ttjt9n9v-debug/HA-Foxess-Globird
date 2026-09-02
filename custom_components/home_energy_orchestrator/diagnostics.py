"""Redacted diagnostics for safe support requests."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import EnergyConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EnergyConfigEntry
) -> dict[str, Any]:
    """Return calculated values only; entity IDs are deliberately omitted."""
    coordinator = entry.runtime_data
    ledger = coordinator.data
    learning = coordinator.learning_result
    return {
        "entry": {"version": entry.version, "options": {"mode": "observe"}},
        "ledger": {
            "reason": ledger.reason,
            "battery_energy_kwh": ledger.battery_energy_kwh,
            "available_after_reserve_kwh": ledger.available_after_reserve_kwh,
            "grid_import_kw": ledger.grid_import_kw,
            "grid_export_kw": ledger.grid_export_kw,
        },
        "learning": {
            "model": learning.model,
            "cycle_budget_kwh": learning.cycle_budget_kwh,
            "sample_count": learning.sample_count,
            "retained_sample_count": len(coordinator.demand_history.samples),
        },
    }
