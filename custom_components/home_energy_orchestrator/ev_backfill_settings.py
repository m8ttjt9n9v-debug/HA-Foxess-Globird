"""One cross-field timing check shared by commissioning and native controls."""

from __future__ import annotations

from datetime import UTC, datetime, time

from .configuration import RuntimeConfiguration
from .const import (
    CONF_EV_OUTSIDE_INVERTER_PERCENT,
    EV_CHARGE_PATH_DIRECT,
    EV_PRE_FREE_BACKFILL_TIMING_CONSERVATIVE,
    EV_PRE_FREE_BACKFILL_TIMING_WHEN_CONNECTED,
    EV_PRE_FREE_BACKFILL_TIMINGS,
    FOXESS_CONTROL_OWNER_MODBUS,
)
from .planner.control_windows import (
    derive_force_discharge_finish,
    post_export_daily_planning_start,
)


def backfill_timing_error(config: RuntimeConfiguration) -> str | None:
    """Validate only timing-related settings; selection grants no enable intent."""
    policy = config.ev_policy
    choice = policy.pre_free_backfill_timing
    if choice not in EV_PRE_FREE_BACKFILL_TIMINGS:
        return "invalid_ev_backfill_timing"
    if (
        choice == EV_PRE_FREE_BACKFILL_TIMING_WHEN_CONNECTED
        and policy.charge_path != EV_CHARGE_PATH_DIRECT
    ):
        return "when_connected_requires_direct_evse"
    if not policy.pre_free_enabled:
        return None
    if config.automation.control_owner != FOXESS_CONTROL_OWNER_MODBUS:
        return "outside_ev_policy_requires_local_modbus"
    if choice == EV_PRE_FREE_BACKFILL_TIMING_CONSERVATIVE:
        return None
    ready = config.windows.ev_daily_ready
    free = config.windows.free_charge_start
    if (
        ready is None or free is None
        or not time(0) < ready < free
        or config.ev_numbers.value(CONF_EV_OUTSIDE_INVERTER_PERCENT, 0.0) <= 0
        or config.inverter.discharge_limit_kw <= 0
    ):
        return "invalid_ready_by_ev_backfill"
    if choice == EV_PRE_FREE_BACKFILL_TIMING_WHEN_CONNECTED:
        finish = derive_force_discharge_finish(
            bonus_end=config.windows.effective_bonus_end,
            offset_configured=config.export.force_discharge_offset_configured,
            offset_minutes=config.export.force_discharge_offset_minutes,
            legacy_finish=config.windows.effective_legacy_force_discharge_finish,
        )
        try:
            post_export_daily_planning_start(
                ready_at=datetime.combine(datetime(2000, 1, 2).date(), ready, tzinfo=UTC),
                next_free_start=datetime.combine(datetime(2000, 1, 2).date(), free, tzinfo=UTC),
                discharge_finish=finish,
            )
        except ValueError:
            return "invalid_when_connected_ev_backfill"
    return None
