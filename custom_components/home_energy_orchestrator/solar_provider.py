"""Read an explicitly mapped native Solis cached frame; never call its API.

Compatibility: hultenvp/solis-sensor 4.0.x SolisCloud InverterService. Its HA
power entity writes only when power changes, so HA report age cannot prove
whether a constant value is current. Read AC power AND measurement time from
the same already-fetched frame, bound to the native entity/entry/device.
Unsupported or partial caches fail closed; no name discovery or clock fallback.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from math import isfinite

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .telemetry import TelemetrySource


def capture_solis_solar(
    hass: HomeAssistant, entity_id: str | None,
    *, diagnostics: dict[str, object] | None = None,
) -> TelemetrySource | None:
    """Synchronous immutable snapshot: no await, I/O, credentials or requests."""
    def report(reason: str, **values: object) -> None:
        if diagnostics is not None:
            diagnostics.update(reason=reason, capture_accepted=False, **values)

    report("not_configured")
    if not entity_id:
        return None
    missing = TelemetrySource(entity_id, None, None, None)
    state = hass.states.get(entity_id)
    registry = er.async_get(hass).async_get(entity_id)
    report("entity_or_registry_unqualified")
    if (
        state is None
        or state.attributes.get("restored", False)
        or registry is None
        or registry.platform != "solis"
    ):
        return missing
    entry_id = registry.config_entry_id
    entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
    report("native_entry_unqualified")
    if entry is None or entry.domain != "solis" or entry.state != ConfigEntryState.LOADED:
        return missing
    serial = state.attributes.get("Inverter serial")
    report("native_provider_identity_unqualified")
    if (
        not isinstance(serial, str)
        or not serial
        or state.attributes.get("API Name") != "SolisCloud"
    ):
        return missing
    name = entry.data.get("name")
    report("native_entity_identity_mismatch")
    if not isinstance(name, str) or registry.unique_id != (
        f"{serial}{name} AC Output Total Power".replace(" ", "_")
    ):
        return missing
    device = dr.async_get(hass).async_get(registry.device_id) if registry.device_id else None
    report("native_device_binding_mismatch")
    if (
        device is None
        or entry_id not in device.config_entries
        or ("solis", f"{serial}_SolisCloud") not in device.identifiers
    ):
        return missing
    runtime = hass.data.get("solis", {})
    service = runtime.get(entry_id) if isinstance(runtime, Mapping) else None
    api = getattr(service, "_api", None)
    cache = getattr(api, "_data", None)
    report(
        "native_cache_unavailable",
        runtime_is_mapping=isinstance(runtime, Mapping),
        service_present=service is not None,
        api_present=api is not None,
        cache_is_mapping=isinstance(cache, Mapping),
    )
    if not isinstance(cache, Mapping):
        return missing
    frame = dict(cache)  # Provider can replace its cache between updates, not during this snapshot.
    if diagnostics is not None:
        # Never expose arbitrary keys/values, IDs, serials, URLs or credentials.
        diagnostics["frame_fields"] = {
            key: {"present": key in frame, "type": (
                type(frame[key]).__name__
                if key in frame and type(frame[key]) in (str, int, float, bool, type(None))
                else "other"
            )}
            for key in ("serial", "pacUnit", "acPower", "timestampUpdate", "state")
        }
        diagnostics["frame_serial_matches"] = frame.get("serial") == serial
        diagnostics["frame_unit"] = (
            frame.get("pacUnit") if frame.get("pacUnit") in ("W", "kW")
            else "missing" if "pacUnit" not in frame else "unsupported"
        )
    report("native_frame_identity_or_unit_mismatch")
    if frame.get("serial") != serial or frame.get("pacUnit") != "W":
        return missing
    power, timestamp = frame.get("acPower"), frame.get("timestampUpdate")
    report("native_frame_value_types_invalid")
    if (
        isinstance(power, bool)
        or not isinstance(power, (int, float))
        or not isfinite(power)
        or isinstance(timestamp, bool)
        or not isinstance(timestamp, (int, float))
        or not isfinite(timestamp)
        or type(frame.get("state")) is not int
    ):
        return missing
    # Native HA may display zero for an offline inverter with retained nonzero
    # power. That display override is not a measured zero: require an actual
    # matching AC value from this frame, even when the inverter is offline.
    try:
        observed = float(state.state)
        measured_at = datetime.fromtimestamp(
            timestamp, UTC
        )  # Postprocessed seconds, never guessed ms.
    except (TypeError, ValueError, OverflowError, OSError):
        report("native_frame_value_or_timestamp_invalid")
        return missing
    if diagnostics is not None:
        diagnostics["frame_power_w"] = power
        diagnostics["measurement_at"] = measured_at.isoformat()
        diagnostics["entity_power_finite"] = isfinite(observed)
        diagnostics["entity_power_matches"] = observed == power
        diagnostics["entity_unit_is_watts"] = state.attributes.get("unit_of_measurement") == "W"
    report("native_entity_value_or_unit_mismatch")
    if (
        state.attributes.get("unit_of_measurement") != "W"
        or not isfinite(observed)
        or observed != power
    ):
        return missing
    if diagnostics is not None:
        diagnostics.update(reason="accepted_frame", capture_accepted=True)
    return TelemetrySource(entity_id, power, "W", measured_at)
