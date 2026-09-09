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
