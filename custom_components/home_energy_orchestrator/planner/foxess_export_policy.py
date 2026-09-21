"""Pure planning evaluation for automatic FoxESS ZEROHERO export."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .ev_before_export import EvBeforeExportDecision, decide_ev_before_export
from .export import ExportPlan, calculate_export_plan, calculate_export_start
from .export_session import ExportSessionState


@dataclass(frozen=True, slots=True)
class FoxessExportPolicyBaseContext:
    """Evidence available even when optional export planning fails."""

    requested_enabled: bool
    before_export_enabled: bool
    ev_soc_percent: float | None
    before_export_target_percent: float
    now: datetime
    start_at: datetime
    finish_at: datetime
    source_capability_available: bool
    configured_max_kw: float
    observed_max_kw: float
    session: ExportSessionState


@dataclass(frozen=True, slots=True)
class FoxessExportPolicyBaseResult:
    """Safe session inputs independent of optional energy-plan evidence."""

    before_export_decision: EvBeforeExportDecision
    effective_enabled: bool
    within_session_window: bool
    source_available: bool
    discharge_max_kw: float
    requested_power_kw: float
    latched: bool
    should_advance: bool
    session_window_active: bool
    finish_requested: bool


@dataclass(frozen=True, slots=True)
class FoxessExportPolicyContext:
    """Inputs used to derive one export candidate without side effects."""

    requested_enabled: bool
    before_export_enabled: bool
    ev_soc_percent: float | None
    before_export_target_percent: float
    now: datetime
    start_at: datetime
    finish_at: datetime
    source_capability_available: bool
    configured_max_kw: float
    observed_max_kw: float
    exported_kwh: object | None
    automatic_limit_kwh: float
    protected_house_kwh: object | None
    protected_ev_kwh: float | None
    available_after_reserve_kwh: object | None
    discharge_efficiency_percent: float
    session: ExportSessionState
    previous_automatic_remaining_kwh: float | None = None
    previous_protected_ev_kwh: float | None = None


@dataclass(frozen=True, slots=True)
class FoxessExportPolicyResult:
    """Derived export candidate and retained publication values."""

    before_export_decision: EvBeforeExportDecision
    effective_enabled: bool
    within_session_window: bool
    source_available: bool
    discharge_max_kw: float
    requested_power_kw: float
    automatic_remaining_kwh: float | None
    protected_ev_kwh: float | None
    export_plan: ExportPlan | None
    planned_start: datetime | None
    eligible: bool
    latched: bool
    should_advance: bool
    session_window_active: bool
    finish_requested: bool


@dataclass(frozen=True, slots=True)
class AutomaticExportRemainingEvaluation:
    """Parsed cap remainder plus whether later evidence may be evaluated."""

    remaining_kwh: float | None
    valid: bool


def evaluate_automatic_export_remaining(
    *,
    exported_kwh: object | None,
    automatic_limit_kwh: float,
    previous_remaining_kwh: float | None,
) -> AutomaticExportRemainingEvaluation:
    """Calculate the retained non-negative remainder without losing fallback."""
    if exported_kwh is None:
        return AutomaticExportRemainingEvaluation(None, True)
    try:
        remaining = max(automatic_limit_kwh - float(exported_kwh), 0.0)
    except (TypeError, ValueError):
        return AutomaticExportRemainingEvaluation(previous_remaining_kwh, False)
    return AutomaticExportRemainingEvaluation(remaining, True)


def evaluate_foxess_export_policy_base(
    context: FoxessExportPolicyBaseContext,
) -> FoxessExportPolicyBaseResult:
    """Derive session-safe export inputs without optional energy arithmetic."""
    decision = decide_ev_before_export(
        enabled=context.before_export_enabled,
        ev_soc_percent=context.ev_soc_percent,
        target_soc_percent=context.before_export_target_percent,
    )
    effective_enabled = context.requested_enabled and decision.export_allowed
    within_session_window = context.start_at <= context.now < context.finish_at
    discharge_max_kw = min(
        max(context.configured_max_kw, 0.0),
        context.observed_max_kw,
    )
    latched = context.session.phase != "idle"
    return FoxessExportPolicyBaseResult(
        before_export_decision=decision,
        effective_enabled=effective_enabled,
        within_session_window=within_session_window,
        source_available=context.source_capability_available,
        discharge_max_kw=discharge_max_kw,
        requested_power_kw=discharge_max_kw,
        latched=latched,
        should_advance=latched,
        session_window_active=effective_enabled and within_session_window,
        finish_requested=(
            not effective_enabled or context.now >= context.finish_at
        ),
    )


def evaluate_foxess_export_policy(
    context: FoxessExportPolicyContext,
) -> FoxessExportPolicyResult:
    """Evaluate the retained controller's export derivation exactly."""
    base = evaluate_foxess_export_policy_base(
        FoxessExportPolicyBaseContext(
            requested_enabled=context.requested_enabled,
            before_export_enabled=context.before_export_enabled,
            ev_soc_percent=context.ev_soc_percent,
            before_export_target_percent=context.before_export_target_percent,
            now=context.now,
            start_at=context.start_at,
            finish_at=context.finish_at,
            source_capability_available=context.source_capability_available,
            configured_max_kw=context.configured_max_kw,
            observed_max_kw=context.observed_max_kw,
            session=context.session,
        )
    )
    automatic_remaining_kwh = context.previous_automatic_remaining_kwh
    protected_ev_kwh = context.previous_protected_ev_kwh
    export_plan: ExportPlan | None = None
    planned_start: datetime | None = None
    eligible = False
    try:
        remaining = evaluate_automatic_export_remaining(
            exported_kwh=context.exported_kwh,
            automatic_limit_kwh=context.automatic_limit_kwh,
            previous_remaining_kwh=context.previous_automatic_remaining_kwh,
        )
        automatic_remaining_kwh = remaining.remaining_kwh
        if not remaining.valid:
            raise ValueError
        protected_ev_kwh = context.protected_ev_kwh
        if (
            context.available_after_reserve_kwh is not None
            and context.protected_house_kwh is not None
            and protected_ev_kwh is not None
            and automatic_remaining_kwh is not None
            and base.discharge_max_kw > 0
        ):
            efficiency = context.discharge_efficiency_percent / 100
            window_hours = (
                context.finish_at - context.start_at
            ).total_seconds() / 3600
            export_plan = calculate_export_plan(
                max(float(context.available_after_reserve_kwh), 0.0) * efficiency,
                context.protected_house_kwh,  # type: ignore[arg-type]
                protected_ev_kwh,  # type: ignore[arg-type]
                automatic_remaining_kwh,
                base.requested_power_kw,
                window_hours,
            )
            planned_start = calculate_export_start(
                context.start_at,
                context.finish_at,
                export_plan.planned_duration_h,
            )
            eligible = (
                planned_start is not None
                and context.now >= planned_start
                and base.within_session_window
            )
    except (TypeError, ValueError):
        export_plan = None

    should_advance = base.latched or (base.effective_enabled and eligible)
    return FoxessExportPolicyResult(
        before_export_decision=base.before_export_decision,
        effective_enabled=base.effective_enabled,
        within_session_window=base.within_session_window,
        source_available=base.source_available,
        discharge_max_kw=base.discharge_max_kw,
        requested_power_kw=base.requested_power_kw,
        automatic_remaining_kwh=automatic_remaining_kwh,
        protected_ev_kwh=protected_ev_kwh,
        export_plan=export_plan,
        planned_start=planned_start,
        eligible=eligible,
        latched=base.latched,
        should_advance=should_advance,
        session_window_active=base.session_window_active,
        finish_requested=base.finish_requested,
    )
