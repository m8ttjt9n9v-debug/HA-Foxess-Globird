"""Deterministic Phase 6 ledger, forecast, learning and write trace replay."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from homeassistant.const import EVENT_CALL_SERVICE

from custom_components.home_energy_orchestrator.coordinator import EnergyCoordinator
from tests.test_setup import ENTRY_DATA

FIXTURE = Path(__file__).parent / "fixtures" / "phase6_recorded_day.json"


def _round(value):
    return None if value is None else round(float(value), 4)


async def test_recorded_day_replay_freezes_phase6_traces(hass, monkeypatch) -> None:
    scenario = json.loads(FIXTURE.read_text(encoding="utf-8"))
    current = [datetime.fromisoformat(scenario["start"])]
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.coordinator.dt_util.now",
        lambda: current[0],
    )
    coordinator = EnergyCoordinator(
        hass,
        {
            **ENTRY_DATA,
            "solar_configured": True,
            "solar_power_entity": "sensor.replay_solar",
            "battery_power_entity": "sensor.replay_battery_power",
            "sign_conventions_verified": True,
        },
        "phase6-recorded-day",
    )
    coordinator.shutdown()

    writes: Counter[str] = Counter()
    stores = {
        "daily_import": coordinator._daily_import_store,
        "daily_export": coordinator._daily_export_store,
        "standard_rate_export": coordinator._standard_rate_export_store,
        "free_window_import": coordinator._free_import_store,
        "peak_import": coordinator._peak_import_store,
        "zerohero_import": coordinator._zerohero_import_store,
        "zerohero_export": coordinator._zerohero_export_store,
        "demand": coordinator._demand_store,
        "forecast": coordinator._forecast_store,
    }
    for name, store in stores.items():
        async def record_save(_payload, *, _name=name) -> None:
            writes[_name] += 1

        store.async_save = record_save

    service_calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, service_calls.append)
    checkpoints = set(scenario["checkpoints"])
    trace = []
    end = datetime.fromisoformat(scenario["end"])
    step = timedelta(seconds=scenario["interval_seconds"])
    while current[0] <= end:
        segment = next(
            row
            for row in scenario["segments"]
            if datetime.fromisoformat(row["start"])
            <= current[0]
            < datetime.fromisoformat(row["end"])
        )
        timestamp = current[0].timestamp()
        hass.states.async_set(
            "sensor.test_grid_power",
            str(segment["grid_kw"]),
            {"unit_of_measurement": "kW"},
            timestamp=timestamp,
        )
        hass.states.async_set(
            "sensor.replay_solar",
            str(segment["solar_kw"]),
            {"unit_of_measurement": "kW"},
            timestamp=timestamp,
        )
        hass.states.async_set(
            "sensor.replay_battery_power",
            str(segment["battery_kw"]),
            {"unit_of_measurement": "kW"},
            timestamp=timestamp,
        )
        hass.states.async_set(
            "sensor.test_house_load",
            str(segment["house_kw"]),
            {"unit_of_measurement": "kW"},
            timestamp=timestamp,
        )
        hass.states.async_set(
            "sensor.test_battery_soc",
            str(segment["battery_soc"]),
            {"unit_of_measurement": "%"},
            timestamp=timestamp,
        )
        ledger = await coordinator._async_update_data()
        coordinator.data = ledger
        await coordinator.async_update_forecast(current[0])
        if current[0].isoformat() in checkpoints:
            trace.append(
                {
                    "at": current[0].isoformat(),
                    "daily_import_kwh": _round(ledger.daily_import_kwh),
                    "free_window_import_kwh": _round(
                        ledger.free_window_import_kwh
                    ),
                    "daily_export_kwh": _round(ledger.daily_export_kwh),
                    "standard_export_kwh": _round(
                        ledger.standard_window_export_kwh
                    ),
                    "boosted_export_kwh": _round(
                        ledger.boosted_window_export_kwh
                    ),
                    "gross_cost": _round(ledger.estimated_energy_cost),
                    "net_cost": _round(ledger.estimated_net_cost),
                    "forecast_cost": _round(
                        coordinator.optimistic_forecast.calibrated_net_cost
                        if coordinator.optimistic_forecast is not None
                        else None
                    ),
                    "learning_samples": len(coordinator.demand_history.samples),
                }
            )
        current[0] += step

    actual = {
        "trace": trace,
        "persistence_writes": dict(sorted(writes.items())),
        "hardware_service_calls": len(service_calls),
        "learning_history_kwh": [
            round(sample.energy_kwh, 4)
            for sample in coordinator.demand_history.samples
        ],
    }
    assert actual == scenario["expected"]
