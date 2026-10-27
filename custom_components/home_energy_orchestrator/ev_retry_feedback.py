"""Read-only native current evidence for direct-EVSE retry bookkeeping.

This is not charging or export authority. In particular, a cached requested
current can be optimistic even when the actual-current measurement is real.
The retry planner must separately require a strictly later vehicle measurement
than its completed command receipt before accepting physical convergence.
"""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from math import isfinite

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .ev_current_measurement import measure_ev_current
from .ev_observation_adapter import EvFeedbackSnapshot
from .ev_source_feedback import before_export_item_measured_fresh
from .planner.ev import DirectEvseCurrentFeedback


def capture_direct_evse_current_feedback(
    hass: HomeAssistant,
    feedback: EvFeedbackSnapshot,
    *,
    now: datetime,
    max_age_seconds: float,
) -> DirectEvseCurrentFeedback | None:
    """Capture one already-loaded, exact native Tessie current cohort.

    Reuse the shared measurement qualifier rather than introducing a provider
    reader, clock, poller or fallback to HA cache publication time. All required
    current and physical fields must be bound to one native vehicle. Charge-
    limit values are deliberately independent; their explicitly mapped actuator
    identity still participates in the opaque binding so rebinding invalidates
    an earlier current receipt. No raw vehicle identity is returned.

    A coherent connected stopped/off frame may bind the ordered current
    command before charge-start. Its state-qualified zero is not convergence:
    the planner must disarm while off and require later charging/on evidence.
    """
    try:
        measurement = measure_ev_current(
            hass, feedback, now=now, max_age_seconds=max_age_seconds,
        )
    except (OverflowError, TypeError, ValueError):
        # Malformed untrusted native values cannot create retry proof. Keep
        # the existing shared measurement and export contracts untouched.
        return None
    if (
        not measurement.valid or measurement.source != "tessie_charge_state"
        or measurement.measured_at is None
        or measurement.requested_current_a is None or len(measurement.binding) != 5
    ):
        return None
    registry = er.async_get(hass)
    entry_id, device_id, vin = measurement.binding[-3:]
    fields = (
        (feedback.current_limit, "charge_state_charge_current_request"),
        (feedback.actual_current, "charge_state_charger_actual_current"),
        (feedback.charging_state, "charge_state_charging_state"),
        (feedback.cable_connected, "charge_state_conn_charge_cable"),
        (feedback.charge_switch, "charge_state_charge_enable_request"),
    )
    for item, field in fields:
        row = registry.async_get(item.entity_id) if item.entity_id else None
        if (
            row is None or row.platform != "tessie" or row.disabled_by is not None
            or row.config_entry_id != entry_id or row.device_id != device_id
            or row.unique_id != f"{vin}-{field}" or item.restored
            or item.available_state is None or item.last_reported is None
            or item.last_reported.tzinfo is None or item.last_reported.utcoffset() is None
            or item.last_reported > now
        ):
            return None
    request = feedback.current_limit
    if (
        request.unit != "A" or type(request.raw_number) not in (int, float)
        or not isfinite(request.raw_number) or request.raw_number < 0
        or request.number != request.raw_number or request.current_a != request.raw_number
        or request.raw_number != measurement.requested_current_a
        or feedback.charging_state.available_state not in {
            "charging", "stopped", "complete", "no_power", "nopower",
        }
        or feedback.cable_connected.available_state != "on"
        or feedback.charge_switch.available_state != (
            "on" if feedback.charging_state.available_state == "charging" else "off"
        )
        or not all(before_export_item_measured_fresh(
            hass, item, now=now, max_age_seconds=max_age_seconds, cohort_valid=False,
        ) for item in (feedback.cable_connected, feedback.charge_switch))
    ):
        return None
    binding = sha256(json.dumps((
        *measurement.binding,
        feedback.current_limit.entity_id,
        feedback.charge_limit.entity_id,
        feedback.charge_switch.entity_id,
        feedback.cable_connected.entity_id,
    ), separators=(",", ":")).encode()).hexdigest()
    return DirectEvseCurrentFeedback(
        binding=binding,
        measured_at=measurement.measured_at,
        requested_current_a=measurement.requested_current_a,
        actual_current_a=measurement.current_a,
    )
