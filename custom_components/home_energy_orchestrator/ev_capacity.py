"""Read-only, explicitly selected EV planning-capacity observations.

Tessie access is limited to the already-loaded coordinator for the mapped car.
This module never fetches data, reads credentials, or owns a polling timer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .normalise import energy_to_kwh
from .planner.ev_learning import estimate_usable_ev_capacity_kwh

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .configuration import EvCapacitySettings

_MAX_AGE = timedelta(hours=24)
_MAX_CAPACITY_KWH = 1000.0
_SOC_KEY = "charge_state_usable_battery_level"


@dataclass(frozen=True, slots=True)
class CapacityObservation:
    """Capacity with its actual authority and age, not a hardware-write gate."""

    value_kwh: float | None
    source: str
    basis: str
    observed_at: datetime | None
    reason: str


def _capacity(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (OverflowError, ValueError):
        return None
    if not isfinite(value) or not 0 < value <= _MAX_CAPACITY_KWH:
        return None
    return value


def _timestamp_reason(value: object, now: datetime) -> tuple[datetime | None, str | None]:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None, "timestamp_invalid"
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return None, "clock_invalid"
    value = value.astimezone(UTC)
    age = now.astimezone(UTC) - value
    if age < timedelta(0):
        return None, "timestamp_future"
    if age > _MAX_AGE:
        return None, "timestamp_stale"
    return value, None


def _missing(source: str, basis: str, reason: str) -> CapacityObservation:
    return CapacityObservation(None, source, basis, None, reason)


def _mapped_capacity(hass: HomeAssistant, entity_id: str | None, now: datetime):
    source, basis = "mapped_entity", "mapped_capacity"
    state = hass.states.get(entity_id) if entity_id else None
    if state is None or state.state in {"unknown", "unavailable", ""}:
        return _missing(source, basis, "mapped_entity_unavailable")
    if state.attributes.get("restored") is True:
        return _missing(source, basis, "mapped_entity_unavailable")
    unit = state.attributes.get("unit_of_measurement")
    if unit not in {"Wh", "kWh"}:
        return _missing(source, basis, "mapped_entity_unit_unsupported")
    try:
        raw = None if isinstance(state.state, bool) else float(state.state)
        value = _capacity(energy_to_kwh(raw, unit)) if raw is not None else None
    except (TypeError, ValueError, OverflowError):
        value = None
    if value is None:
        return _missing(source, basis, "mapped_entity_value_invalid")
    observed_at, reason = _timestamp_reason(getattr(state, "last_reported", None), now)
    if reason:
        return _missing(source, basis, f"mapped_entity_{reason}")
    return CapacityObservation(value, source, basis, observed_at, "ok")


def _tessie_capacity(hass: HomeAssistant, soc_entity: str | None, now: datetime):
    source, basis = "tessie", "nominal_full_pack"

    def missing(reason: str) -> CapacityObservation:
        return _missing(source, basis, f"tessie_{reason}")

    if not soc_entity:
        return missing("soc_unmapped")
    registry_entry = er.async_get(hass).async_get(soc_entity)
    if registry_entry is None or getattr(registry_entry, "platform", None) != "tessie":
        return missing("soc_not_tessie")
    entry_id = getattr(registry_entry, "config_entry_id", None)
    entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
    if entry is None or getattr(entry, "domain", None) != "tessie":
        return missing("entry_unavailable")
    if getattr(entry, "state", None) != ConfigEntryState.LOADED:
        return missing("entry_not_loaded")
    device_id = getattr(registry_entry, "device_id", None)
    device = dr.async_get(hass).async_get(device_id) if device_id else None
    if device is None or entry_id not in getattr(device, "config_entries", ()):
        return missing("device_unavailable")
    identifiers = getattr(device, "identifiers", ())
    if not isinstance(identifiers, (set, frozenset, list, tuple)):
        return missing("device_ambiguous")
    vins = {
        identifier[1]
        for identifier in identifiers
        if isinstance(identifier, tuple)
        and len(identifier) == 2
        and identifier[0] == "tessie"
        and isinstance(identifier[1], str)
        and identifier[1]
    }
    if len(vins) != 1:
        return missing("device_ambiguous")
    vin = next(iter(vins))
    if getattr(registry_entry, "unique_id", None) != f"{vin}-{_SOC_KEY}":
        return missing("vehicle_mismatch")
    runtime = getattr(entry, "runtime_data", None)
    vehicles = getattr(runtime, "vehicles", None)
    if isinstance(vehicles, Mapping):
        vehicles = vehicles.values()
    elif not isinstance(vehicles, (list, tuple)):
        return missing("runtime_unsupported")
    matches = [vehicle for vehicle in vehicles if getattr(vehicle, "vin", None) == vin]
    if len(matches) != 1:
        return missing("vehicle_ambiguous")
    coordinator = getattr(matches[0], "data_coordinator", None)
    if coordinator is None or getattr(coordinator, "last_update_success", False) is not True:
        return missing("provider_unavailable")
    provider_entry = getattr(coordinator, "config_entry", None)
    if provider_entry is not None and getattr(provider_entry, "entry_id", None) != entry_id:
        return missing("vehicle_mismatch")
    data = getattr(coordinator, "data", None)
    if not isinstance(data, Mapping):
        return missing("runtime_unsupported")
    value = _capacity(data.get("charge_state_nominal_full_pack_energy"))
    if value is None:
        return missing("value_invalid")
    timestamp = data.get("charge_state_timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return missing("timestamp_invalid")
    try:
        observed_at = datetime.fromtimestamp(timestamp / 1000, UTC) if isfinite(timestamp) else None
    except (OverflowError, OSError, ValueError):
        observed_at = None
    observed_at, reason = _timestamp_reason(observed_at, now)
    if reason:
        return missing(reason)
    return CapacityObservation(value, source, basis, observed_at, "ok")


def resolve_ev_capacity(
    hass: HomeAssistant,
    settings: EvCapacitySettings,
    *,
    soc_entity: str | None,
    stored_energy_kwh: float | None,
    soc_percent: float | None,
    now: datetime,
) -> CapacityObservation:
    """Resolve the selected source, never silently re-enter legacy estimation."""
    source = getattr(settings, "source", "legacy_ratio")
    if source == "legacy_ratio":
        try:
            value = estimate_usable_ev_capacity_kwh(
                stored_energy_kwh=stored_energy_kwh, soc_percent=soc_percent
            )
        except (TypeError, ValueError, OverflowError):
            value = None
        # Preserve the old primitive's rounding and unbounded upper range.
        if value is None or not isfinite(value):
            return _missing(source, "legacy_ratio", "legacy_ratio_unavailable")
        return CapacityObservation(value, source, "legacy_ratio", None, "ok")
    fallback = _capacity(getattr(settings, "fallback_kwh", None))
    if source == "configured":
        return (
            CapacityObservation(fallback, source, "configured", None, "ok")
            if fallback
            else (_missing(source, "configured", "configured_capacity_invalid"))
        )
    if source == "mapped_entity":
        observation = _mapped_capacity(hass, getattr(settings, "entity_id", None), now)
    elif source == "tessie":
        observation = _tessie_capacity(hass, soc_entity, now)
    else:
        return _missing(str(source), "unavailable", "capacity_source_unsupported")
    if observation.value_kwh is None and fallback is not None:
        return CapacityObservation(
            fallback, "configured_fallback", "configured", None, observation.reason
        )
    return observation
