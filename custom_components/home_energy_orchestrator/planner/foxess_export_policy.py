"""Pure planning evaluation for automatic FoxESS ZEROHERO export."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .ev_before_export import EvBeforeExportDecision, decide_ev_before_export
from .export import ExportPlan, calculate_export_plan, calculate_export_start
from .export_session import ExportSessionState


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


def evaluate_foxess_export_policy(
    context: FoxessExportPolicyContext,
) -> FoxessExportPolicyResult:
    """Evaluate the retained controller's export derivation exactly."""
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
    requested_power_kw = discharge_max_kw
    automatic_remaining_kwh = context.previous_automatic_remaining_kwh
    protected_ev_kwh = context.previous_protected_ev_kwh
    export_plan: ExportPlan | None = None
    planned_start: datetime | None = None
    eligible = False
    try:
        automatic_remaining_kwh = (
            max(
                context.automatic_limit_kwh - float(context.exported_kwh),
                0.0,
            )
            if context.exported_kwh is not None
            else None
        )
        protected_ev_kwh = context.protected_ev_kwh
        if (
            context.available_after_reserve_kwh is not None
            and context.protected_house_kwh is not None
            and protected_ev_kwh is not None
            and automatic_remaining_kwh is not None
            and discharge_max_kw > 0
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
                requested_power_kw,
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
                and within_session_window
            )
    except (TypeError, ValueError):
        export_plan = None

    latched = context.session.phase != "idle"
    should_advance = latched or (effective_enabled and eligible)
    return FoxessExportPolicyResult(
        before_export_decision=decision,
        effective_enabled=effective_enabled,
        within_session_window=within_session_window,
        source_available=context.source_capability_available,
        discharge_max_kw=discharge_max_kw,
        requested_power_kw=requested_power_kw,
        automatic_remaining_kwh=automatic_remaining_kwh,
        protected_ev_kwh=protected_ev_kwh,
        export_plan=export_plan,
        planned_start=planned_start,
        eligible=eligible,
        latched=latched,
        should_advance=should_advance,
        session_window_active=effective_enabled and within_session_window,
        finish_requested=(not effective_enabled or context.now >= context.finish_at),
    )
