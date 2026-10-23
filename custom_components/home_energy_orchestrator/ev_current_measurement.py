"""Read-only, source-stamped EV current for shared measured-power consumers.

This boundary qualifies observations; it neither changes current nor decides
whether a controller may retain, increase or stop a charging request. Native
measurement time is not an acknowledgement that a commanded ramp has settled.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .ev_observation_adapter import EvFeedbackSnapshot
from .ev_source_feedback import before_export_item_measured_fresh

_CHARGE_STATES = frozenset(
    {"charging", "stopped", "complete", "disconnected", "no_power", "nopower"}
)


def _native_charge_anchors_match(registry, feedback, entry, device, vin):
    """Bind native fields by identity without borrowing their value clocks."""
    for item, field in (
        (feedback.soc, "charge_state_usable_battery_level"),
        (feedback.current_limit, "charge_state_charge_current_request"),
        (feedback.charge_limit, "charge_state_charge_limit_soc"),
        (feedback.actual_current, "charge_state_charger_actual_current"),
        (feedback.charging_state, "charge_state_charging_state"),
        (feedback.cable_connected, "charge_state_conn_charge_cable"),
        (feedback.charge_switch, "charge_state_charge_enable_request"),
    ):
        anchor = registry.async_get(item.entity_id) if item.entity_id else None
        if anchor is None or anchor.platform != "tessie":
            continue  # Explicit generic policy mappings have no native identity.
        if (
            anchor.disabled_by is not None
            or anchor.config_entry_id != entry.entry_id or anchor.device_id != device.id
            or anchor.unique_id != f"{vin}-{field}"
        ):
            return False
    return True


@dataclass(frozen=True, slots=True)
class EvPlanningSocObservation:
    """Qualified planning SoC; retained sleep evidence is not live authority."""

    value_percent: float | None
    source: str
    observed_at: datetime | None
    reason: str

    @property
    def valid(self) -> bool:
        return self.value_percent is not None


def _valid_age(value: object, *, positive: bool = False) -> bool:
    try:
        return (
            type(value) in (int, float) and isfinite(value)
            and (value > 0 if positive else value >= 0)
        )
    except OverflowError:
        return False


def _measure_soc_observation(
    hass: HomeAssistant,
    feedback: EvFeedbackSnapshot,
    *,
    now: datetime,
    max_age_seconds: float,
    sleeping_max_age_seconds: float | None = None,
) -> EvPlanningSocObservation:
    """Share the existing exact source qualification, not physical authority."""
    item = feedback.soc
    registry = er.async_get(hass)
    row = registry.async_get(item.entity_id) if item.entity_id else None
    native = row is not None and row.platform == "tessie"
    source = "tessie_charge_state" if native else "entity_report"

    def invalid(reason: str, observed_at: datetime | None = None) -> EvPlanningSocObservation:
        return EvPlanningSocObservation(None, source, observed_at, reason)

    if now.tzinfo is None or now.utcoffset() is None or not _valid_age(max_age_seconds):
        return invalid("measurement_clock_invalid")
    if (
        item.restored or item.available_state is None
        or type(item.number) not in (int, float) or not isfinite(item.number)
        or not 0 <= item.number <= 100
        or item.last_reported is None or item.last_reported.tzinfo is None
        or item.last_reported.utcoffset() is None or item.last_reported > now
    ):
        return invalid("soc_value_or_report_unavailable")
    if not native:
        return (
            EvPlanningSocObservation(
                float(item.number), source, item.last_reported, "fresh_reported",
            )
            if item.fresh(now, max_age_seconds)
            else invalid("reported_soc_expired", item.last_reported)
        )
    entry = hass.config_entries.async_get_entry(row.config_entry_id)
    device = dr.async_get(hass).async_get(row.device_id) if row.device_id else None
    if (
        row.disabled_by is not None or entry is None or entry.domain != "tessie"
        or entry.state != ConfigEntryState.LOADED or device is None
        or entry.entry_id not in device.config_entries
    ):
        return invalid("native_source_unavailable")
    vins = {value for domain, value in device.identifiers if domain == "tessie"}
    if len(vins) != 1:
        return invalid("native_vehicle_ambiguous")
    vin = next(iter(vins))
    if not _native_charge_anchors_match(registry, feedback, entry, device, vin):
        return invalid("native_policy_source_mismatch")
    vehicles = getattr(getattr(entry, "runtime_data", None), "vehicles", None)
    if isinstance(vehicles, Mapping):
        vehicles = vehicles.values()
    elif not isinstance(vehicles, (list, tuple)):
        return invalid("native_runtime_unavailable")
    matches = [vehicle for vehicle in vehicles if getattr(vehicle, "vin", None) == vin]
    if len(matches) != 1:
        return invalid("native_vehicle_ambiguous")
    provider = getattr(matches[0], "data_coordinator", None)
    if (
        provider is None or getattr(provider, "last_update_success", False) is not True
        or getattr(provider, "config_entry", None) is not entry
    ):
        return invalid("native_provider_unavailable")
    data = getattr(provider, "data", None)
    if not isinstance(data, Mapping) or data.get("state") not in {"online", "asleep"}:
        return invalid("native_state_unavailable")
    stamp = data.get("charge_state_timestamp")
    value = data.get("charge_state_usable_battery_level")
    if (
        not _valid_age(stamp) or not _valid_age(value) or value != item.number
    ):
        return invalid("native_measurement_unavailable")
    try:
        measured_at = datetime.fromtimestamp(stamp / 1000, UTC)
    except (OverflowError, OSError, ValueError):
        return invalid("native_measurement_unavailable")
    age = (now - measured_at).total_seconds()
    if age < 0:
        return invalid("native_soc_future", measured_at)
    asleep = data["state"] == "asleep"
    maximum = sleeping_max_age_seconds if asleep and sleeping_max_age_seconds is not None else (
        max_age_seconds
    )
    if age > maximum:
        return invalid("sleeping_soc_expired" if asleep else "native_soc_expired", measured_at)
    reason = (
        "bounded_asleep" if age > max_age_seconds
        else "fresh_asleep" if asleep else "fresh_online"
    )
    return EvPlanningSocObservation(float(value), source, measured_at, reason)


def measure_ev_soc(
    hass: HomeAssistant,
    feedback: EvFeedbackSnapshot,
    *,
    now: datetime,
    max_age_seconds: float,
) -> float | None:
    """Read independently measured SoC under the unchanged strict live bound.

    Actual current and actuator acknowledgements need not load; native mapped
    identities must nevertheless describe the same vehicle. This function
    never uses the longer sleeping-car reservation planning bound.
    """
    return _measure_soc_observation(
        hass, feedback, now=now, max_age_seconds=max_age_seconds,
    ).value_percent


def measure_ev_planning_soc(
    hass: HomeAssistant,
    feedback: EvFeedbackSnapshot,
    *,
    now: datetime,
    max_age_seconds: float,
    planning_max_age_seconds: float,
) -> EvPlanningSocObservation:
    """Read bounded SoC for reservation planning, never for positive EV writes.

    Only an explicitly asleep, healthy native same-vehicle provider may use
    the caller's separate planning ceiling. Online and generic observations
    retain the strict live age. Every call requalifies binding, health, value
    and the original charge-state timestamp: HA/fetch/drive clocks, repeated
    reads and restart cannot renew it. No cache, journal or poller is created.
    """
    if not _valid_age(planning_max_age_seconds, positive=True):
        return EvPlanningSocObservation(None, "unavailable", None, "planning_age_invalid")
    return _measure_soc_observation(
        hass, feedback, now=now, max_age_seconds=max_age_seconds,
        sleeping_max_age_seconds=planning_max_age_seconds,
    )


@dataclass(frozen=True, slots=True)
class EvCurrentMeasurement:
    """One immutable measured value and its source, never commanded power.

    ``current_a`` is usable only when ``valid`` is true. The native frame's
    optional request is diagnostic/transition context: a provider can update
    that cache optimistically, so it is not actual current or command proof.
    Strict generic sources use the older explicit entity report clock. The
    separately requested legacy value contract has no measurement timestamp
    and cannot establish freshness, alignment or post-command observation.
    """

    current_a: float
    valid: bool
    measured_at: datetime | None
    source: str
    reason: str
    requested_current_a: float | None = None
    binding: tuple[str, ...] = ()


def measure_ev_current(
    hass: HomeAssistant,
    feedback: EvFeedbackSnapshot,
    *,
    now: datetime,
    max_age_seconds: float,
    retain_generic_values: bool = False,
) -> EvCurrentMeasurement:
    """Qualify already-captured charging/current against their real publisher.

    Native Tessie fields must be from one commissioned vehicle and agree with
    its loaded provider's same charge-state frame. Unrelated policy values and
    optimistic current/limit acknowledgements cannot hide a real measurement.
    Explicit generic mappings retain their own bounded report-clock contract;
    a partially native pair cannot silently acquire that fallback contract.
    ``retain_generic_values`` preserves the canonical controller's existing
    generic value semantics only; native sources always require measurement
    provenance and their configured age bound.
    """
    source = "entity_report"
    binding = (
        feedback.actual_current.entity_id or "",
        feedback.charging_state.entity_id or "",
    )
    registry = er.async_get(hass)
    actual_row = (
        registry.async_get(feedback.actual_current.entity_id)
        if feedback.actual_current.entity_id else None
    )
    charging_row = (
        registry.async_get(feedback.charging_state.entity_id)
        if feedback.charging_state.entity_id else None
    )
    native = tuple(row is not None and row.platform == "tessie" for row in (
        actual_row, charging_row,
    ))
    if any(native):
        source = "tessie_charge_state"

    def invalid(reason: str) -> EvCurrentMeasurement:
        return EvCurrentMeasurement(0.0, False, None, source, reason, binding=binding)

    if (
        now.tzinfo is None
        or now.utcoffset() is None
        or type(max_age_seconds) not in (int, float)
        or not isfinite(max_age_seconds)
        or max_age_seconds < 0
    ):
        return invalid("measurement_clock_invalid")
    actual, charging = feedback.actual_current, feedback.charging_state
    if charging.available_state not in _CHARGE_STATES:
        return invalid("charging_state_unavailable")
    if not any(native) and retain_generic_values:
        source = "entity_value"
        if charging.restored:
            return invalid("retained_value_unavailable")
        charging_now = charging.available_state == "charging"
        # The canonical generic value projection qualifies an explicit stopped
        # state as zero before reading retained actual current. Restored Full
        # startup may therefore proceed without a current entity loading first.
        # This is NOT native physical proof or a stamped/fresh measurement.
        if charging_now and (
            actual.restored or actual.available_state is None
            or actual.current_a is None or not isfinite(actual.current_a) or actual.current_a < 0
        ):
            return invalid("retained_value_unavailable")
        return EvCurrentMeasurement(
            float(actual.current_a) if charging_now else 0.0, True, None, source,
            "retained_charging" if charging_now else "retained_stopped", binding=binding,
        )
    if actual.current_a is None or not isfinite(actual.current_a) or actual.current_a < 0:
        return invalid("actual_current_unavailable")
    if any(
        item.last_reported is None
        or item.last_reported.tzinfo is None
        or item.last_reported.utcoffset() is None
        for item in (actual, charging)
    ):
        return invalid("source_report_clock_invalid")
    if any(native):
        if not all(native) or (
            actual_row.config_entry_id != charging_row.config_entry_id
            or actual_row.device_id != charging_row.device_id
        ):
            return invalid("native_source_mismatch")
        # The existing per-field validator intentionally ignores unrelated
        # optimistic request/limit changes while retaining exact native field,
        # registry, provider, clock, unit and captured-value checks.
        if not all(before_export_item_measured_fresh(
            hass, item, now=now, max_age_seconds=max_age_seconds, cohort_valid=False,
        ) for item in (actual, charging)):
            return invalid("native_measurement_unavailable")
        entry = hass.config_entries.async_get_entry(actual_row.config_entry_id)
        device = dr.async_get(hass).async_get(actual_row.device_id)
        vins = {value for domain, value in device.identifiers if domain == "tessie"}
        # Both validators above have already proved this identity and provider.
        vin = next(iter(vins))
        if not _native_charge_anchors_match(registry, feedback, entry, device, vin):
            return invalid("native_policy_source_mismatch")
        # Policy anchors constrain identity only. Their unchanged/stale values
        # and optimistic command acknowledgements are not physical measurements
        # and must not suppress the independently measured actual-current pair.
        vehicles = entry.runtime_data.vehicles
        if isinstance(vehicles, Mapping):
            vehicles = vehicles.values()
        vehicle = next(vehicle for vehicle in vehicles if getattr(vehicle, "vin", None) == vin)
        frame = vehicle.data_coordinator.data
        measured_at = datetime.fromtimestamp(frame["charge_state_timestamp"] / 1000, UTC)
        binding = (*binding, entry.entry_id, device.id, vin)
        requested = frame.get("charge_state_charge_current_request")
        requested_current = (
            float(requested)
            if type(requested) in (int, float) and isfinite(requested) and requested >= 0
            else None
        )
    else:
        if not all(before_export_item_measured_fresh(
            hass, item, now=now, max_age_seconds=max_age_seconds, cohort_valid=False,
        ) for item in (actual, charging)):
            return invalid("reported_measurement_unavailable")
        measured_at = min(actual.last_reported, charging.last_reported)
        requested_current = None

    charging_now = charging.available_state == "charging"
    return EvCurrentMeasurement(
        current_a=float(actual.current_a) if charging_now else 0.0,
        valid=True,
        measured_at=measured_at,
        source=source,
        reason="measured_charging" if charging_now else "measured_stopped",
        requested_current_a=requested_current,
        binding=binding,
    )
