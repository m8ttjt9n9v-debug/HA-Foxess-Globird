"""Minimal opt-in EV-before-export arbitration.

This layer changes only whether automatic export is currently permitted. It
does not start EV charging, alter the user's saved export request, or decide
where later EV charging energy should come from.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


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
