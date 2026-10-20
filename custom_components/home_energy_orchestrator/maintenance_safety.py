"""Read-only, host-wide admission evidence for deliberate HA maintenance.

These checks do not stop controllers, clear ownership, or change any policy.
Callers must drain the returned locks, recheck admission at every disruptive
boundary, and prevent new writes while maintenance is in progress. An empty
result describes the captured evidence; it cannot exclude an external writer.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from math import isfinite
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CoreState
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EV_TELEMETRY_MAX_AGE_SECONDS,
    DEFAULT_EV_TELEMETRY_MAX_AGE_SECONDS,
    DOMAIN,
)
from .ev_observation_adapter import capture_ev_feedback, ev_observation_entity_map
from .foxess_adapter import FoxessEntityMap
from .foxess_observation_adapter import capture_foxess_feedback
from .telemetry_adapter import state_reported_at

_SAFE_STORAGE = frozenset({"valid", "missing"})
_SAFE_EV_RESTORE = frozenset({"restored", "missing"})
_VERIFICATION_BLOCKERS = frozenset({
    "home_assistant_not_running", "heo_runtime_unavailable", "heo_storage_untrusted",
    "battery_telemetry_unavailable", "battery_mode_feedback_unavailable",
    "ev_feedback_unavailable", "ev_full_feedback_unavailable",
})


def runtime_verification_blockers(hass: Any, coordinators: list) -> tuple[str, ...]:
    """Report startup health, not the stricter admission requirement to be idle.

    Preserved enabled policies may legitimately resume after a maintenance
    restart. Their active sessions/targets/modes are not a verification fault;
    missing runtime, untrusted journals and invalid/stale evidence still are.
    """
    return tuple(code for code in maintenance_blockers(hass, coordinators)
                 if code in _VERIFICATION_BLOCKERS)


def maintenance_locks(coordinators: list) -> list[asyncio.Lock]:
    """Return existing battery/EV locks in stable host-wide acquisition order.

    Never fabricate a lock for a missing controller: admission separately
    rejects missing capabilities. Callers must release these before HA unload;
    the battery unload lifecycle itself drains its reconciliation lock.
    """
    locks: list[asyncio.Lock] = []
    for coordinator in sorted(coordinators, key=lambda item: str(getattr(item, "entry_id", ""))):
        active = getattr(coordinator, "active_controller", None)
        ev = getattr(coordinator, "ev_controller", None)
        for lock in (getattr(active, "_reconcile_lock", None), getattr(ev, "_lock", None)):
            if isinstance(lock, asyncio.Lock) and all(lock is not value for value in locks):
                locks.append(lock)
    return locks


def maintenance_blockers(hass: Any, coordinators: list) -> tuple[str, ...]:
    """Capture conservative blockers across every HEO entry on this HA host.

    Codes contain no entity IDs, private names, or credentials. A configured
    but unloaded entry, unknown telemetry or missing capability fails closed.
    Ordinary keepalive charging is still charging; no historical one-off
    maintenance approval is generalized into an exemption here.
    """
    blockers: set[str] = set()
    if hass.state is not CoreState.running:
        blockers.add("home_assistant_not_running")
    if not coordinators:
        blockers.add("heo_runtime_unavailable")
    entries = hass.config_entries.async_entries(DOMAIN)
    loaded_ids = {getattr(value, "entry_id", None) for value in coordinators}
    if any(entry.state is not ConfigEntryState.LOADED or entry.entry_id not in loaded_ids
           for entry in entries):
        blockers.add("heo_runtime_unavailable")
    now = dt_util.utcnow()
    for coordinator in coordinators:
        try:
            _entry_blockers(hass, coordinator, now, blockers)
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            # An old/incomplete runtime is not permission to restart the host.
            blockers.add("heo_runtime_unavailable")
    return tuple(sorted(blockers))


def _entry_blockers(hass: Any, coordinator: Any, now: datetime, blockers: set[str]) -> None:
    runtime = coordinator.runtime_config
    active = coordinator.active_controller
    ev = coordinator.ev_controller
    trip = coordinator.trip_charge
    diagnostic = coordinator.manual_test
    if (
        coordinator.last_update_success is not True
        or coordinator.snapshot is None
        or coordinator.data is None
        or active._reconcile_stopped
        or ev._unsub_interval is None
        or not isinstance(active._reconcile_lock, asyncio.Lock)
        or not isinstance(ev._lock, asyncio.Lock)
    ):
        blockers.add("heo_runtime_unavailable")
    if (
        active._charge_storage_status not in _SAFE_STORAGE
        or active._export_storage_status not in _SAFE_STORAGE
        or diagnostic.storage_status not in _SAFE_STORAGE
        or ev._repository.last_restore_status not in _SAFE_EV_RESTORE
        or not trip._loaded
        or trip._invalid_storage
        or trip._storage_error
        or trip._dirty
    ):
        blockers.add("heo_storage_untrusted")
    if active.charge_session.phase not in {"idle", "completed"}:
        blockers.add("battery_charge_session_active")
    if active.export_session.phase != "idle":
        blockers.add("battery_export_session_active")
    if diagnostic.is_active or diagnostic.phase != "idle":
        blockers.add("battery_diagnostic_active")
    manual = active.manual
    if not manual._loaded or not manual._trusted or manual._storage_fault:
        blockers.add("heo_storage_untrusted")
    if manual.is_active and not (
        manual.target == "self_use" and manual._phase == "held"
        and manual._command_confirmed and manual._durable_generation == manual.generation
    ):
        blockers.add("battery_manual_control_active")
    if trip.owns_full or trip._state.cleanup_pending:
        blockers.add("trip_charge_active")
    if (
        runtime.ev_preferences.charge_to_full_enabled
        or ev.charge_to_full_started_at is not None
    ):
        blockers.add("ev_full_charge_active")
    _battery_feedback(hass, coordinator, now, blockers)
    disconnected_idle = False
    if runtime.ev_connection.configured:
        disconnected_idle = _ev_feedback(hass, runtime, now, blockers)
    _ev_runtime(ev, blockers, disconnected_idle=disconnected_idle)


def _battery_feedback(hass: Any, coordinator: Any, now: datetime, blockers: set[str]) -> None:
    runtime = coordinator.runtime_config
    max_age = runtime.telemetry.max_age_seconds
    telemetry = coordinator._normalized_telemetry(now)
    if any(not sample.valid or not sample.fresh or sample.value is None
           or _accepted_source_restored(hass, sample)
           for sample in (telemetry.grid_power, telemetry.battery_power)):
        blockers.add("battery_telemetry_unavailable")
    soc_id = runtime.battery.soc_entity
    soc = hass.states.get(soc_id) if soc_id else None
    # SoC is a stable level, not a fast polling clock. Native force-power
    # numbers are retained configuration targets, not continuously polled
    # hardware measurements. Their ages do not indicate a source outage.
    if _restored(soc) or _number(soc.state if soc else None) is None:
        blockers.add("battery_telemetry_unavailable")
    elif not 0 <= float(soc.state) <= 100:
        blockers.add("battery_telemetry_unavailable")
    mapping = runtime.inverter
    ids = (mapping.work_mode_entity, mapping.force_charge_power_entity,
           mapping.force_discharge_power_entity)
    if (
        not mapping.actuator_mapping_complete
        or not _fresh(hass.states.get(ids[0]), now, max_age)
        or any(_restored(hass.states.get(entity_id)) for entity_id in ids[1:])
    ):
        blockers.add("battery_mode_feedback_unavailable")
        return
    feedback = capture_foxess_feedback(hass, FoxessEntityMap(*ids))
    if feedback.observation is None:
        blockers.add("battery_mode_feedback_unavailable")
    elif feedback.mode != "Self Use":
        blockers.add("battery_not_self_use")
    elif feedback.charge_power_kw != 0 or feedback.discharge_power_kw != 0:
        blockers.add("battery_force_target_not_clear")


def _ev_runtime(ev: Any, blockers: set[str], *, disconnected_idle: bool = False) -> None:
    if (
        ev.pre_free_session.active or ev.daily_backfill_active
        or ev.daily_backfill_stop_pending or ev.outside_control_active
    ):
        blockers.add("ev_session_active")
    if ev.reconciliation.phase not in {"idle", "confirmed"}:
        blockers.add("ev_reconciliation_pending")
    if ev.smart_recovery.phase != "idle" or ev.smart_stage_started_at is not None:
        blockers.add("ev_recovery_pending")
    # Disconnected cleanup retains the previous displayed current and the
    # pre-free baseline. Those are not charging intent once fresh mapped
    # feedback positively proves unplugged, switch off and zero actual current.
    # A pending session/reconciliation/recovery above still blocks, and invalid
    # retained numbers are never excused by a physical disconnection.
    if any(value is not None and (
        (number := _number(value)) is None or number < 0
        or number > 0 and not disconnected_idle
    ) for value in (ev.target_current_a, ev.reconciliation.target_current_a,
                    ev.pre_free_current_a, ev.smart_stage_target_a)):
        blockers.add("ev_charging_target_active")


def _ev_feedback(hass: Any, runtime: Any, now: datetime, blockers: set[str]) -> bool:
    feedback = capture_ev_feedback(hass, ev_observation_entity_map(runtime))
    max_age = runtime.ev_numbers.value(
        CONF_EV_TELEMETRY_MAX_AGE_SECONDS, DEFAULT_EV_TELEMETRY_MAX_AGE_SECONDS
    )
    physical = feedback.physical_observation(now=now, max_age_seconds=max_age)
    if not physical.available:
        blockers.add("ev_feedback_unavailable")
        return False
    if physical.charging_activity:
        blockers.add("ev_physically_charging")
    if physical.charge_switch_on:
        blockers.add("ev_charge_switch_on")
    legacy = runtime.ev_preferences.legacy_charge_to_full_entity
    if legacy:
        state = hass.states.get(legacy)
        if not _fresh(state, now, max_age) or state.state not in {"on", "off"}:
            blockers.add("ev_full_feedback_unavailable")
        elif state.state == "on":
            blockers.add("ev_full_charge_active")
    return physical.disconnected_idle


def _restored(state: Any) -> bool:
    return state is not None and state.attributes.get("restored") is True


def _accepted_source_restored(hass: Any, sample: Any) -> bool:
    """Reject placeholders, not provenance already rejected by normalization."""
    sources = sample.sources
    if sample.reason in {"signed_fallback_pair_stale", "signed_fallback_pair_incoherent"}:
        sources = sources[-1:]
    return any(_restored(hass.states.get(source.entity_id)) for source in sources)


def _fresh(state: Any, now: datetime, max_age: float) -> bool:
    if state is None or _restored(state) or not isfinite(max_age) or max_age < 0:
        return False
    age = (now - state_reported_at(state)).total_seconds()
    return 0 <= age <= max_age


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None
