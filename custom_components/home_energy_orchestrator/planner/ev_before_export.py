"""Minimal opt-in EV-before-export arbitration.

Export permission and protected top-up planning share the existing opt-in.
Neither function writes devices or alters the saved export request.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .ev import EvCurrentDecision
from .ev_outside_window import PreFreeCurrentInputs, plan_pre_free_current


@dataclass(frozen=True, slots=True)
class EvBeforeExportRecovery:
    """A bound top-up obligation, not new energy or device authority."""

    pending: bool = False
    binding: tuple[str, ...] = ()
    valid: bool = True


@dataclass(frozen=True, slots=True)
class EvBeforeExportImport:
    """Bound economic-import confirmation; never an electrical safety lease."""

    since: datetime | None = None
    binding: tuple[str, ...] = ()
    valid: bool = True


def confirm_before_export_import(
    state: EvBeforeExportImport, *, binding: tuple[str, ...], now: datetime,
    source_at: datetime, importing: bool, retain_existing: bool, seconds: float,
) -> tuple[EvBeforeExportImport, bool]:
    """Only retain an existing target until the ORIGINAL import deadline.

    A clear reading rearms. Settings/source rebinding inside an import episode,
    malformed restored state or an expired deadline cannot renew the interval.
    The caller separately enforces every fresh electrical/energy/ownership gate.
    """
    if not importing:
        return EvBeforeExportImport(binding=binding), True
    if (not retain_existing or not state.valid or not math.isfinite(seconds)
            or not 0 < seconds <= 300 or source_at > now):
        return state, False
    if state.since is not None and state.binding != binding:
        return EvBeforeExportImport(state.since, state.binding, False), False
    since = state.since or source_at
    elapsed = (now - since).total_seconds()
    next_state = EvBeforeExportImport(since, binding)
    return next_state, 0 <= elapsed < seconds


def before_export_recovery_target(minimum: float, buffer: float, soft_limit: float) -> float:
    """Normal SoC limits cap buffering, without lowering the export minimum."""
    if not all(math.isfinite(v) and 0 <= v <= 100 for v in (minimum, buffer, soft_limit)):
        return math.nan
    return min(minimum + buffer, 100, max(minimum, soft_limit))


def advance_before_export_recovery(
    state: EvBeforeExportRecovery, *, binding: tuple[str, ...], soc: float,
    minimum: float, release: float, connected: bool,
) -> EvBeforeExportRecovery:
    """Arm below minimum; release at the buffered boundary, retaining outages."""
    if not math.isfinite(soc) or not 0 <= soc <= 100 or not math.isfinite(release):
        return state
    if soc >= release:
        return EvBeforeExportRecovery(binding=binding)
    if soc < minimum and connected:
        return EvBeforeExportRecovery(True, binding)
    if not state.valid:
        return state  # Corruption is not proof of completion within the band.
    return state if state.binding == binding else EvBeforeExportRecovery(binding=binding)


def plan_ev_before_export_current(
    *, sellable_kwh: float, vehicle_room_kwh: float, baseline_a: float,
    current_ceiling_a: float, charger_minimum_a: float, voltage_v: float,
    phase_count: int, current_step_a: float, vehicle_soc: float, target_soc: float,
) -> EvCurrentDecision:
    """Offer protected spare energy now, within the normal decision horizon.

    Reuse the existing battery-energy/current conversion rather than inventing
    another pacing algorithm. Live authority is rechecked every control tick;
    three minutes of funding bounds a small budget between normal decisions.
    """
    if not all(math.isfinite(v) and v >= 0 for v in (sellable_kwh, vehicle_room_kwh)):
        raise ValueError("EV-before-export energy must be finite and non-negative")
    decision = plan_pre_free_current(PreFreeCurrentInputs(
        session_active=True,
        planned_energy_kwh=min(sellable_kwh, vehicle_room_kwh),
        hours_until_free=3 / 60,
        voltage_v=voltage_v, phase_count=phase_count, current_step_a=current_step_a,
        baseline_a=baseline_a, current_ceiling_a=current_ceiling_a,
        vehicle_soc_percent=vehicle_soc, vehicle_soft_limit_percent=target_soc,
    ))
    if decision.current_a <= baseline_a or decision.current_a < charger_minimum_a:
        return EvCurrentDecision(baseline_a, "ev_before_export_insufficient_energy")
    return EvCurrentDecision(decision.current_a, "ev_before_export_charging")


@dataclass(frozen=True, slots=True)
class EvBeforeExportDecision:
    """Whether the ZEROHERO export policy may act this tick."""

    export_allowed: bool
    reason: str


def protected_keepalive_requires_evidence(
    *,
    ev_configured: bool,
    control_commissioned: bool,
    protected_baseline_a: float,
) -> bool:
    """Return whether mapped connection evidence can affect the reservation."""
    return ev_configured and control_commissioned and protected_baseline_a > 0


def calculate_protected_keepalive_energy_kwh(
    *,
    ev_configured: bool,
    control_commissioned: bool,
    protected_baseline_a: float,
    home_state: str | None,
    cable_state: str | None,
    hours_until_free: float,
    voltage_v: float,
    phase_count: int,
) -> float | None:
    """Return mandatory connected-EV energy or fail closed without evidence."""
    if not protected_keepalive_requires_evidence(
        ev_configured=ev_configured,
        control_commissioned=control_commissioned,
        protected_baseline_a=protected_baseline_a,
    ):
        return 0.0
    if home_state is None or cable_state is None:
        return None
    if home_state not in {"home", "on"} or cable_state != "on":
        return 0.0
    return round(
        max(hours_until_free, 0.0)
        * protected_baseline_a
        * voltage_v
        * phase_count
        / 1000,
        3,
    )


def compose_protected_ev_energy_kwh(
    *,
    keepalive_kwh: float | None,
    daily_backfill_kwh: float | None,
) -> float | None:
    """Add cycle-scoped EV protection without weakening missing evidence."""
    if keepalive_kwh is None:
        return None
    return keepalive_kwh + (daily_backfill_kwh or 0.0)


def decide_ev_before_export(
    *,
    enabled: bool,
    ev_soc_percent: float | None,
    target_soc_percent: float,
    recovery_target_soc_percent: float | None = None,
) -> EvBeforeExportDecision:
    """Withhold export below the configured EV target when explicitly enabled."""
    if not enabled:
        return EvBeforeExportDecision(True, "disabled")
    if not math.isfinite(target_soc_percent) or not 0 <= target_soc_percent <= 100:
        return EvBeforeExportDecision(False, "target_invalid")
    if ev_soc_percent is None or not math.isfinite(ev_soc_percent):
        return EvBeforeExportDecision(False, "ev_soc_unavailable")
    if not 0 <= ev_soc_percent <= 100:
        return EvBeforeExportDecision(False, "ev_soc_invalid")
    if recovery_target_soc_percent is not None and (
        not math.isfinite(recovery_target_soc_percent)
        or not target_soc_percent <= recovery_target_soc_percent <= 100
    ):
        return EvBeforeExportDecision(False, "target_invalid")
    if ev_soc_percent < target_soc_percent:
        return EvBeforeExportDecision(False, "ev_below_target")
    if recovery_target_soc_percent is not None and ev_soc_percent < recovery_target_soc_percent:
        return EvBeforeExportDecision(False, "ev_buffer_topup")
    return EvBeforeExportDecision(True, "target_met")
