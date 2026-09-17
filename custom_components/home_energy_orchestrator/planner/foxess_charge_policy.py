"""Pure eligibility evaluation for automatic FoxESS free-window charging."""

from __future__ import annotations

from dataclasses import dataclass

from .charge_session import ChargeSessionState

_LATCHED_PHASES = frozenset({"starting", "active", "recovering", "stopping"})


@dataclass(frozen=True, slots=True)
class FoxessChargePolicyContext:
    """Primitive inputs used before advancing the retained charge session."""

    requested_enabled: bool
    schedule_confirmed: bool
    window_active: bool
    configured_max_kw: float
    observed_max_kw: float
    source_capability_available: bool
    mode: str
    battery_soc: float | None
    target_soc_percent: float
    free_energy_remaining_kwh: float | None
    session: ChargeSessionState


@dataclass(frozen=True, slots=True)
class FoxessChargePolicyResult:
    """Derived charge eligibility without persistence or hardware effects."""

    enabled: bool
    charge_max_kw: float
    source_available: bool
    allowance_available: bool
    eligible_to_start: bool
    latched: bool
    charge_power_target_kw: float | None
    terminal_reason: str | None
    owns_tick: bool
    should_advance: bool
    session_window_active: bool
    finish_requested: bool


def evaluate_foxess_charge_policy(
    context: FoxessChargePolicyContext,
) -> FoxessChargePolicyResult:
    """Evaluate the retained controller's pre-session charge policy exactly."""
    enabled = context.requested_enabled and context.schedule_confirmed
    charge_max_kw = min(
        max(context.configured_max_kw, 0.0),
        context.observed_max_kw,
    )
    source_available = context.source_capability_available and charge_max_kw > 0
    latched = context.session.phase != "idle"
    charge_power_target_kw = (
        context.session.requested_power_kw
        if source_available and context.session.phase in _LATCHED_PHASES
        else (0.0 if source_available else None)
    )
    allowance_available = (
        context.free_energy_remaining_kwh is not None
        and float(context.free_energy_remaining_kwh) > 0
    )
    eligible_to_start = (
        context.battery_soc is not None
        and 0 <= float(context.battery_soc) < context.target_soc_percent
        and charge_max_kw > 0
        and allowance_available
    )

    terminal_reason: str | None = None
    if context.requested_enabled and not context.schedule_confirmed and not latched:
        terminal_reason = "charge_schedule_unconfirmed"
    elif (
        not latched
        and enabled
        and context.window_active
        and eligible_to_start
        and context.mode != "Self Use"
    ):
        terminal_reason = "charge_start_mode_not_self_use"
    elif not latched and enabled and context.window_active and not allowance_available:
        terminal_reason = (
            "charge_allowance_exhausted"
            if context.free_energy_remaining_kwh is not None
            else "charge_allowance_unavailable"
        )

    should_advance = terminal_reason is None and (
        latched or (enabled and context.window_active and eligible_to_start)
    )
    owns_tick = terminal_reason is not None or should_advance
    session_window_active = enabled and context.window_active and allowance_available
    finish_requested = (
        not enabled or not context.window_active or not allowance_available
    )
    return FoxessChargePolicyResult(
        enabled=enabled,
        charge_max_kw=charge_max_kw,
        source_available=source_available,
        allowance_available=allowance_available,
        eligible_to_start=eligible_to_start,
        latched=latched,
        charge_power_target_kw=charge_power_target_kw,
        terminal_reason=terminal_reason,
        owns_tick=owns_tick,
        should_advance=should_advance,
        session_window_active=session_window_active,
        finish_requested=finish_requested,
    )
