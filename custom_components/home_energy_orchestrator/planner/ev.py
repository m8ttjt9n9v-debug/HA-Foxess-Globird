"""Pure EV charge-to-target planning primitives.

The planner contains no Home Assistant calls. An eventual integration adapter
must map the returned commands to the explicitly commissioned EV number and
switch entities, then verify the resulting state.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class EvObservation:
    """Current vehicle connection, SoC, and charge-limit bounds."""

    soc_percent: float | None
    cable_connected: bool
    limit_min_percent: float | None
    limit_max_percent: float | None


@dataclass(frozen=True, slots=True)
class EvCommand:
    """One adapter-neutral EV command."""

    action: str
    value: float | None = None


@dataclass(frozen=True, slots=True)
class EvCommandPlan:
    """An ordered EV command sequence with an auditable reason."""

    commands: tuple[EvCommand, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class EvCurrentInputs:
    """Measured inputs and policy limits for a closed-loop EV current target.

    Currents are amps per charging phase. ``grid_average_a`` follows the
    project's convention: positive means import and negative means export.
    The two averages must cover the same observation interval; the planner
    does not infer a site load from a stale or missing source.
    """

    free_window_active: bool
    cable_connected: bool
    ceiling_a: float
    protected_baseline_a: float
    effective_minimum_a: float
    requested_current_a: float | None
    service_current_a: float
    headroom_a: float
    grid_average_a: float | None
    grid_coverage_ratio: float
    ev_average_a: float | None
    ev_current_now_a: float | None
    ev_feedback_source_valid: bool
    elapsed_free_window_minutes: float
    settle_minutes: float
    grid_import_target_a: float | None = None
    priority_ev: bool = False
    charge_to_full: bool = False
    step_a: float = 1.0
    minimum_statistics_coverage: float = 0.67
    deadband_a: float = 0.5
    load_following_active: bool = False
    bonus_window_active: bool = False
    inverter_capacity_kw: float | None = None
    bonus_load_following_percent: float = 20.0
    non_free_load_following_percent: float = 30.0
    load_following_override: bool = False
    ev_voltage_v: float = 230.0
    ev_phase_count: int = 1
    home_presence_known: bool = True
    at_home: bool = True
    solar_spill_active: bool = False
    solar_surplus_kw: float | None = None
    battery_soc_percent: float | None = None
    solar_spill_soc_threshold: float = 100.0
    pre_free_backfill_active: bool = False
    pre_free_backfill_current_a: float | None = None


@dataclass(frozen=True, slots=True)
class EvCurrentDecision:
    """A bounded EV current target and the reason it was selected."""

    target_current_a: float
    reason: str
    grid_target_a: float
    grid_error_a: float | None
    non_ev_service_current_a: float | None


@dataclass(frozen=True, slots=True)
class EvAllowanceInputs:
    """Inputs for sharing a finite free-window allowance with an EV.

    The imported-energy counter covers the whole site.  Current feedback is
    used only to remove the EV's present contribution from measured grid
    import, leaving battery and house demand without trying to predict either.
    """

    free_window_active: bool
    imported_kwh: float | None
    cutoff_kwh: float
    hours_remaining: float
    grid_import_kw: float | None
    ev_current_a: float | None
    ev_voltage_v: float
    ev_phase_count: int
    physical_ceiling_a: float
    effective_minimum_a: float
    step_a: float = 1.0
    service_current_a: float = 0.0
    site_phase_count: int = 1
    service_headroom_a: float = 1.0
    reserved_non_ev_kwh: float = 0.0


@dataclass(frozen=True, slots=True)
class EvAllowanceDecision:
    """Maximum EV current permitted by the remaining whole-site allowance."""

    session_allowed: bool
    ceiling_a: float
    remaining_kwh: float | None
    target_site_import_kw: float | None
    non_ev_import_kw: float | None
    ev_budget_remaining_kwh: float | None
    reason: str


def plan_ev_start(target_soc_percent: float, observation: EvObservation) -> EvCommandPlan:
    """Plan a guarded charge-to-target start.

    A disconnected vehicle, unknown SoC, malformed limits, or a target above
    the mapped entity's maximum produces a no-op. The number limit is written
    before the charge switch is turned on. A target below the entity minimum
    is allowed: the independent stop-at-target guard still enforces the
    requested target (for example, a 40% target with a 50% Tessie minimum).
    """

    _validate_target(target_soc_percent)
    soc = _finite_percent(observation.soc_percent, "soc_percent")
    minimum = _finite_percent(observation.limit_min_percent, "limit_min_percent")
    maximum = _finite_percent(observation.limit_max_percent, "limit_max_percent")
    if minimum is None or maximum is None:
        return EvCommandPlan((), "charge_limit_bounds_unknown")
    if minimum > maximum:
        return EvCommandPlan((), "charge_limit_bounds_invalid")
    if not observation.cable_connected:
        return EvCommandPlan((), "disconnected")
    if soc is None:
        return EvCommandPlan((), "soc_unknown")
    if soc >= target_soc_percent:
        return EvCommandPlan((), "target_reached")
    if target_soc_percent > maximum:
        return EvCommandPlan((), "target_exceeds_charge_limit")

    effective_limit = max(target_soc_percent, minimum)
    return EvCommandPlan(
        (
            EvCommand("set_charge_limit", round(effective_limit, 3)),
            EvCommand("turn_on_charge"),
        ),
        "ready",
    )


def plan_ev_stop(observation: EvObservation, *, reason: str = "manual_stop") -> EvCommandPlan:
    """Plan a safe stop; stopping remains valid even if the cable is removed."""

    _finite_percent(observation.soc_percent, "soc_percent")
    _finite_percent(observation.limit_min_percent, "limit_min_percent")
    _finite_percent(observation.limit_max_percent, "limit_max_percent")
    return EvCommandPlan((EvCommand("turn_off_charge"),), reason)


def ev_charge_should_stop(
    target_soc_percent: float,
    *,
    soc_percent: float | None,
    cable_connected: bool,
    armed: bool,
) -> bool:
    """Return whether an armed session must be stopped now."""

    _validate_target(target_soc_percent)
    if not armed or not cable_connected:
        return bool(armed and not cable_connected)
    soc = _finite_percent(soc_percent, "soc_percent")
    return soc is not None and soc >= target_soc_percent


def plan_ev_allowance(inputs: EvAllowanceInputs) -> EvAllowanceDecision:
    """Pace EV charging so all site loads remain below an energy cutoff.

    The EV budget is the remaining kWh after reserving forecast non-EV energy,
    spread over the remaining window hours. Measured non-EV import also bounds
    the commissioned service capacity. The result is stepped down to a
    supported whole-current setpoint. Missing live evidence fails closed.
    """

    _validate_allowance_inputs(inputs)
    if not inputs.free_window_active:
        return EvAllowanceDecision(
            True,
            round(inputs.physical_ceiling_a, 3),
            None,
            None,
            None,
            None,
            "outside_free_window",
        )
    if inputs.imported_kwh is None:
        return EvAllowanceDecision(
            False, 0.0, None, None, None, None, "allowance_meter_unavailable"
        )
    remaining = max(inputs.cutoff_kwh - inputs.imported_kwh, 0.0)
    if remaining <= 0:
        return EvAllowanceDecision(
            False, 0.0, 0.0, 0.0, None, 0.0, "free_allowance_cutoff_reached"
        )
    if inputs.hours_remaining <= 0:
        return EvAllowanceDecision(
            False, 0.0, round(remaining, 3), 0.0, None, 0.0, "charging_window_finished"
        )
    if inputs.grid_import_kw is None or inputs.ev_current_a is None:
        return EvAllowanceDecision(
            False,
            0.0,
            round(remaining, 3),
            None,
            None,
            None,
            "allowance_telemetry_unavailable",
        )

    ev_power_kw = (
        inputs.ev_current_a * inputs.ev_voltage_v * inputs.ev_phase_count / 1000
    )
    non_ev_import_kw = max(inputs.grid_import_kw - ev_power_kw, 0.0)
    ev_budget_remaining_kwh = max(remaining - inputs.reserved_non_ev_kwh, 0.0)
    ev_power_ceiling_kw = ev_budget_remaining_kwh / inputs.hours_remaining
    target_site_import_kw = non_ev_import_kw + ev_power_ceiling_kw
    allowance_current_ceiling = ev_power_ceiling_kw * 1000 / (
        inputs.ev_voltage_v * inputs.ev_phase_count
    )
    raw_current_ceiling = allowance_current_ceiling
    service_limited = False
    if inputs.service_current_a > 0:
        service_power_kw = (
            max(inputs.service_current_a - inputs.service_headroom_a, 0.0)
            * inputs.ev_voltage_v
            * inputs.site_phase_count
            / 1000
        )
        service_ev_power_kw = max(service_power_kw - non_ev_import_kw, 0.0)
        service_current_ceiling = service_ev_power_kw * 1000 / (
            inputs.ev_voltage_v * inputs.ev_phase_count
        )
        service_limited = service_current_ceiling < raw_current_ceiling
        raw_current_ceiling = min(raw_current_ceiling, service_current_ceiling)
    stepped_ceiling = (raw_current_ceiling // inputs.step_a) * inputs.step_a
    ceiling = min(inputs.physical_ceiling_a, max(stepped_ceiling, 0.0))
    allowed = ceiling >= inputs.effective_minimum_a and ceiling > 0
    if not allowed:
        reason = "allowance_below_minimum_current"
    elif service_limited and ceiling < inputs.physical_ceiling_a:
        reason = "service_limited"
    elif ceiling < inputs.physical_ceiling_a:
        reason = "allowance_limited"
    else:
        reason = "physical_ceiling"
    return EvAllowanceDecision(
        allowed,
        round(ceiling, 3),
        round(remaining, 3),
        round(target_site_import_kw, 3),
        round(non_ev_import_kw, 3),
        round(ev_budget_remaining_kwh, 3),
        reason,
    )


def plan_ev_current_target(inputs: EvCurrentInputs) -> EvCurrentDecision:
    """Choose a safe, stepped EV current from matched live measurements.

    This is the portable form of the proven household-aware Tesla controller.
    It treats the site service current as the constraint, not the EV's nominal
    power. During a free-charge window the measured three-minute EV current is
    aligned to ``service_current_a - headroom_a`` using the measured grid
    error. A transient rise in ovens, air-conditioning, or other house load
    therefore reduces the EV request instead of creating paid grid import.

    Outside an active charging window, when the cable is disconnected, or when
    the physical ceiling is unavailable, the protected baseline is returned.
    During a load-following session the requested current is additionally
    capped at a configured percentage of inverter capacity (20% in the bonus
    window and 30% at other times by default). The explicit override removes
    only that percentage cap; grid-feedback protection still runs.
    """

    _validate_current_inputs(inputs)
    if not inputs.home_presence_known:
        return EvCurrentDecision(0.0, "home_presence_unknown", 0.0, None, None)
    if not inputs.at_home:
        return EvCurrentDecision(0.0, "away", 0.0, None, None)
    window_active = (
        inputs.free_window_active
        or inputs.load_following_active
        or inputs.solar_spill_active
        or inputs.pre_free_backfill_active
    )
    ceiling = inputs.ceiling_a
    # The free window is governed by the tariff/import budget and may use the
    # inverter's full commissioned capacity.  The percentage ceilings apply
    # only to slower, load-following sessions (including solar spill and
    # pre-window backfill), where a transient household load needs margin.
    capped_session_active = (
        inputs.load_following_active
        or inputs.solar_spill_active
        or inputs.pre_free_backfill_active
    )
    if capped_session_active and not inputs.load_following_override:
        rate_percent = (
            inputs.bonus_load_following_percent
            if inputs.bonus_window_active
            else inputs.non_free_load_following_percent
        )
        if inputs.inverter_capacity_kw is not None and inputs.inverter_capacity_kw > 0:
            power_cap_kw = inputs.inverter_capacity_kw * rate_percent / 100
            current_cap_a = power_cap_kw * 1000 / (inputs.ev_voltage_v * inputs.ev_phase_count)
            ceiling = min(ceiling, current_cap_a)
    baseline = min(inputs.protected_baseline_a, ceiling)
    effective_min = min(max(inputs.effective_minimum_a, 0.0), ceiling)
    requested = (
        inputs.requested_current_a
        if inputs.requested_current_a is not None
        else baseline
    )
    requested = min(max(requested, baseline), ceiling)
    service_target = max(inputs.service_current_a - inputs.headroom_a, 0.0)
    grid_target = (
        service_target
        if inputs.grid_import_target_a is None
        else min(service_target, inputs.grid_import_target_a)
    )

    def decision(target: float, reason: str, error: float | None = None) -> EvCurrentDecision:
        return EvCurrentDecision(
            target_current_a=round(min(max(target, 0.0), ceiling), 3),
            reason=reason,
            grid_target_a=round(grid_target, 3),
            grid_error_a=None if error is None else round(error, 3),
            non_ev_service_current_a=(
                None
                if inputs.grid_average_a is None or inputs.ev_average_a is None
                else round(inputs.grid_average_a - inputs.ev_average_a, 3)
            ),
        )

    if ceiling <= 0:
        return decision(0.0, "ceiling_unavailable")
    if not window_active:
        return decision(baseline, "outside_free_window")
    if not inputs.cable_connected:
        return decision(baseline, "disconnected")

    if inputs.solar_spill_active:
        if (
            inputs.solar_surplus_kw is None
            or inputs.solar_surplus_kw <= 0
            or inputs.battery_soc_percent is None
            or inputs.battery_soc_percent < inputs.solar_spill_soc_threshold
        ):
            return decision(baseline, "solar_spill_inputs_unavailable")
        solar_current = inputs.solar_surplus_kw * 1000 / (
            inputs.ev_voltage_v * inputs.ev_phase_count
        )
        return decision(solar_current, "solar_spill")

    if inputs.pre_free_backfill_active:
        if inputs.pre_free_backfill_current_a is None:
            return decision(baseline, "pre_free_backfill_inputs_unavailable")
        return decision(inputs.pre_free_backfill_current_a, "pre_free_backfill")

    grid_valid = (
        inputs.grid_average_a is not None
        and inputs.grid_coverage_ratio >= inputs.minimum_statistics_coverage
    )
    ev_valid = (
        inputs.ev_average_a is not None
        and inputs.ev_current_now_a is not None
        and inputs.ev_current_now_a > 0
        and inputs.ev_feedback_source_valid
    )

    # A sustained grid-target overrun takes precedence over EV-priority policy.
    # This is the key protection for a 15 kW inverter at a busy site, and lets
    # a tariff import ceiling be stricter than the physical service rating.
    if (
        grid_valid
        and inputs.service_current_a > 0
        and inputs.grid_average_a > grid_target
    ):
        if not ev_valid:
            return decision(baseline, "service_limit_fallback")
        error = grid_target - inputs.grid_average_a
        aligned = inputs.ev_average_a + error
        stepped = (aligned // inputs.step_a) * inputs.step_a
        return decision(max(stepped, baseline), "service_limit_correction", error)

    if inputs.priority_ev or inputs.charge_to_full:
        return decision(ceiling, "ev_priority")
    if inputs.elapsed_free_window_minutes < inputs.settle_minutes:
        return decision(effective_min, "settling")
    if not grid_valid or inputs.service_current_a <= 0:
        return decision(effective_min, "grid_telemetry_fallback")
    if not ev_valid:
        return decision(max(requested, effective_min), "ev_feedback_hold")

    error = grid_target - inputs.grid_average_a
    if abs(error) <= inputs.deadband_a:
        return decision(max(requested, effective_min), "within_deadband", error)

    aligned = inputs.ev_average_a + error
    stepped = (aligned // inputs.step_a) * inputs.step_a
    return decision(max(stepped, effective_min), "house_battery_priority", error)


def _validate_current_inputs(inputs: EvCurrentInputs) -> None:
    """Reject malformed physical limits before any target is produced."""

    non_negative = (
        ("ceiling_a", inputs.ceiling_a),
        ("protected_baseline_a", inputs.protected_baseline_a),
        ("effective_minimum_a", inputs.effective_minimum_a),
        ("service_current_a", inputs.service_current_a),
        ("headroom_a", inputs.headroom_a),
        ("grid_import_target_a", inputs.grid_import_target_a),
        ("grid_coverage_ratio", inputs.grid_coverage_ratio),
        ("elapsed_free_window_minutes", inputs.elapsed_free_window_minutes),
        ("settle_minutes", inputs.settle_minutes),
        ("step_a", inputs.step_a),
        ("minimum_statistics_coverage", inputs.minimum_statistics_coverage),
        ("deadband_a", inputs.deadband_a),
        ("inverter_capacity_kw", inputs.inverter_capacity_kw),
        ("bonus_load_following_percent", inputs.bonus_load_following_percent),
        ("non_free_load_following_percent", inputs.non_free_load_following_percent),
        ("ev_voltage_v", inputs.ev_voltage_v),
        ("solar_surplus_kw", inputs.solar_surplus_kw),
        ("battery_soc_percent", inputs.battery_soc_percent),
        ("solar_spill_soc_threshold", inputs.solar_spill_soc_threshold),
        ("pre_free_backfill_current_a", inputs.pre_free_backfill_current_a),
    )
    for name, value in non_negative:
        if value is not None and (not isfinite(value) or value < 0):
            raise ValueError(f"{name} must be finite and non-negative")
    for name, value in (
        ("grid_average_a", inputs.grid_average_a),
        ("ev_average_a", inputs.ev_average_a),
        ("ev_current_now_a", inputs.ev_current_now_a),
        ("requested_current_a", inputs.requested_current_a),
    ):
        if value is not None and (not isfinite(value) or value < 0):
            raise ValueError(f"{name} must be finite and non-negative when provided")
    if inputs.protected_baseline_a > inputs.ceiling_a:
        raise ValueError("protected_baseline_a cannot exceed ceiling_a")
    if inputs.effective_minimum_a > inputs.ceiling_a:
        raise ValueError("effective_minimum_a cannot exceed ceiling_a")
    if inputs.step_a <= 0:
        raise ValueError("step_a must be greater than zero")
    if inputs.minimum_statistics_coverage > 1:
        raise ValueError("minimum_statistics_coverage cannot exceed 1")
    if inputs.bonus_load_following_percent > 100:
        raise ValueError("bonus_load_following_percent cannot exceed 100")
    if inputs.non_free_load_following_percent > 100:
        raise ValueError("non_free_load_following_percent cannot exceed 100")
    for name, value in (
        ("battery_soc_percent", inputs.battery_soc_percent),
        ("solar_spill_soc_threshold", inputs.solar_spill_soc_threshold),
    ):
        if value is not None and value > 100:
            raise ValueError(f"{name} cannot exceed 100")
    if inputs.ev_voltage_v <= 0:
        raise ValueError("ev_voltage_v must be greater than zero")
    if inputs.ev_phase_count not in (1, 3):
        raise ValueError("ev_phase_count must be 1 or 3")


def _validate_allowance_inputs(inputs: EvAllowanceInputs) -> None:
    """Reject malformed allowance and physical-limit inputs."""

    for name, value in (
        ("imported_kwh", inputs.imported_kwh),
        ("cutoff_kwh", inputs.cutoff_kwh),
        ("hours_remaining", inputs.hours_remaining),
        ("grid_import_kw", inputs.grid_import_kw),
        ("ev_current_a", inputs.ev_current_a),
        ("ev_voltage_v", inputs.ev_voltage_v),
        ("physical_ceiling_a", inputs.physical_ceiling_a),
        ("effective_minimum_a", inputs.effective_minimum_a),
        ("step_a", inputs.step_a),
        ("service_current_a", inputs.service_current_a),
        ("service_headroom_a", inputs.service_headroom_a),
        ("reserved_non_ev_kwh", inputs.reserved_non_ev_kwh),
    ):
        if value is not None and (not isfinite(value) or value < 0):
            raise ValueError(f"{name} must be finite and non-negative")
    if inputs.cutoff_kwh <= 0:
        raise ValueError("cutoff_kwh must be greater than zero")
    if inputs.ev_voltage_v <= 0:
        raise ValueError("ev_voltage_v must be greater than zero")
    if inputs.ev_phase_count not in (1, 3):
        raise ValueError("ev_phase_count must be 1 or 3")
    if inputs.site_phase_count not in (1, 3):
        raise ValueError("site_phase_count must be 1 or 3")
    if inputs.step_a <= 0:
        raise ValueError("step_a must be greater than zero")
    if inputs.effective_minimum_a > inputs.physical_ceiling_a:
        raise ValueError("effective_minimum_a cannot exceed physical_ceiling_a")


def _validate_target(value: float) -> None:
    if not isfinite(value) or not 0 <= value <= 100:
        raise ValueError("target_soc_percent must be finite and between 0 and 100")


def _finite_percent(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    if not isfinite(value) or not 0 <= value <= 100:
        raise ValueError(f"{name} must be finite and between 0 and 100")
    return value
