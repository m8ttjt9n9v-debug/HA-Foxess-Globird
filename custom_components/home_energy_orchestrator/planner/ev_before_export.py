"""Minimal opt-in EV-before-export arbitration.

Export permission and protected top-up planning share the existing opt-in.
Neither function writes devices or alters the saved export request.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .ev import EvCurrentDecision
from .ev_outside_window import PreFreeCurrentInputs, plan_pre_free_current


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
    if ev_soc_percent < target_soc_percent:
        return EvBeforeExportDecision(False, "ev_below_target")
    return EvBeforeExportDecision(True, "target_met")
