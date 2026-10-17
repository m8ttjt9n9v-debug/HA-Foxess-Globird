"""Read-only Trip impact projection; never grants or changes charging intent."""

from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta
from math import isfinite

from homeassistant.util import dt as dt_util

from .const import DEFAULT_PEAK_WINDOW_END, DEFAULT_PEAK_WINDOW_START
from .planner.control_windows import control_window_bounds
from .planner.trip_charge import calculate_trip_charge_plan
from .planner.trip_impact import estimate_pre_free_impact


def _number(value):
    return value if type(value) in (int, float) and isfinite(value) else None


def _legacy_inputs(trip, current):
    """Read the published helper wrapper only; never adopt its Full ownership.

    The original wrapper itself uses these fixed interface IDs. A renamed or
    different helper package is unsupported rather than guessed from names.
    """
    states = trip.hass.states
    try:
        raw = states.get("sensor.heo_trip_charge_plan")
        if raw is None or len(raw.state) > 2048:
            return None
        plan = json.loads(raw.state)
        if not isinstance(plan, dict) or type(plan.get("v")) is not int or plan["v"] != 2:
            return None
        due = states.get("input_datetime.heo_trip_ready_by")
        target = states.get("input_select.heo_trip_target_soc")
        if due is None or target is None:
            return None
        due_ts = _number(due.attributes.get("timestamp"))
        selected = float(target.state.removesuffix("%"))
        if due_ts is None or target.state != f"{int(selected)}%":
            return None
        changes = {
            "departure": datetime.fromtimestamp(due_ts, UTC),
            "target_soc": int(selected),
        }
        for key, entity in (
            ("efficiency_percent", "input_number.heo_trip_charge_efficiency"),
            ("extra_minutes", "input_number.heo_trip_extra_minutes"),
            ("maximum_hours", "input_number.heo_trip_override_timeout"),
        ):
            state = states.get(entity)
            if state is None:
                return None
            changes[key] = float(state.state)
        inputs = {**current, **changes}
        expected = calculate_trip_charge_plan(**inputs)
        if expected is None:
            return None
        pairs = {
            "due": due_ts, "target": selected, "soc": inputs["soc"],
            "cap": inputs["capacity_kwh"], "kw": inputs["maximum_power_kw"],
            "eff": inputs["efficiency_percent"], "extra": inputs["extra_minutes"],
            "maximum": inputs["maximum_hours"],
        }
        if any(_number(plan.get(k)) != value for k, value in pairs.items()):
            return None
        if _number(plan.get("start")) is None or abs(
            plan["start"] - expected.planned_start.timestamp()
        ) > 0.001:
            return None
        return inputs, expected.planned_start
    except (TypeError, ValueError, OverflowError):
        return None


def _build_trip_energy_impact(trip) -> dict:
    """Use canonical budgets and the actual scheduler's remaining-energy plan."""
    unavailable = {
        "status": "unavailable", "reason": "trip_plan_unavailable",
        "scope": "before_next_free_window_only", "source": "native",
    }
    if getattr(trip, "status", None) == "paused":
        return {**unavailable, "reason": "trip_paused"}
    legacy_active = any(
        (state := trip.hass.states.get(entity)) is not None and state.state == "on"
        for entity in (
            "input_boolean.heo_trip_charge_scheduled", "input_boolean.heo_trip_charge_started",
        )
    )
    if legacy_active and not trip.armed and not trip.owns_full:
        legacy_status = trip.hass.states.get("input_select.heo_trip_charge_status")
        resume = trip.hass.states.get("input_text.heo_trip_resume_state")
        try:
            record = json.loads(resume.state) if resume is not None else {}
        except (TypeError, ValueError):
            record = {}
        if (
            legacy_status is not None and legacy_status.state == "Paused — car disconnected"
        ) or (isinstance(record, dict) and record.get("paused") is True):
            return {**unavailable, "source": "legacy", "reason": "trip_paused"}
    coordinator = trip.coordinator
    ledger = getattr(coordinator, "data", None)
    if ledger is None or getattr(coordinator, "ev_controller", None) is None:
        return {**unavailable, "reason": "energy_budget_unavailable"}
    if getattr(coordinator, "last_update_success", False) is not True:
        return {**unavailable, "reason": "energy_refresh_failed"}
    telemetry = getattr(coordinator, "telemetry", None)
    for name in ("grid_power", "battery_power", "house_load"):
        sample = getattr(telemetry, name, None)
        if sample is None or not sample.valid or not sample.fresh or sample.value is None:
            return {**unavailable, "reason": "energy_evidence_unavailable"}
    current = trip._current_plan_inputs()
    if legacy_active and not trip.armed and not trip.owns_full:
        unavailable["source"] = "legacy"
        legacy = _legacy_inputs(trip, current)
        if legacy is None:
            return unavailable
        inputs, planned_start = legacy
        source = "legacy"
    else:
        inputs, plan, source = current, trip._plan, "native"
        if plan is None or plan != calculate_trip_charge_plan(**inputs):
            return unavailable
        planned_start = plan.planned_start
    runtime = coordinator.runtime_config
    now = dt_util.now()
    legacy_owned = trip.hass.states.get("input_boolean.heo_trip_charge_started")
    owned = trip.owns_full if source == "native" else (
        legacy_owned is not None and legacy_owned.state == "on"
    )
    if inputs["departure"] <= now and not owned:
        return {**unavailable, "source": source, "reason": "departure_passed"}
    windows = runtime.windows
    free_start, free_end = control_window_bounds(
        now, start=windows.effective_free_charge_start, finish=windows.effective_free_charge_end,
    )
    if now >= free_end:
        free_start += timedelta(days=1)
        free_end += timedelta(days=1)
    tariff = runtime.nonnegative
    result = estimate_pre_free_impact(
        now=now, planned_start=planned_start,
        next_free_start=free_start, next_free_end=free_end,
        soc=inputs["soc"], target_soc=inputs["target_soc"],
        capacity_kwh=inputs["capacity_kwh"], maximum_power_kw=inputs["maximum_power_kw"],
        ev_efficiency_percent=inputs["efficiency_percent"],
        battery_after_floor_kwh=getattr(ledger, "available_after_floor_kwh", None),
        protected_house_kwh=coordinator.learning_remaining_kwh,
        discharge_efficiency_percent=runtime.export.discharge_efficiency_percent,
        peak_start=windows.peak_start or time.fromisoformat(DEFAULT_PEAK_WINDOW_START),
        peak_end=windows.peak_end or time.fromisoformat(DEFAULT_PEAK_WINDOW_END),
        peak_rate=tariff.peak_rate_per_kwh,
        shoulder_rate=tariff.shoulder_rate_per_kwh,
    )
    return {
        **result, "source": source,
        "budget_basis": "after_configured_floor_and_expected_house_use",
    }


def build_trip_energy_impact(trip) -> dict:
    """Optional display failures cannot change Trip intent or break its status."""
    try:
        return _build_trip_energy_impact(trip)
    except (ArithmeticError, TypeError, ValueError):
        return {
            "status": "unavailable", "reason": "invalid_estimate_inputs",
            "scope": "before_next_free_window_only", "source": "unavailable",
        }
