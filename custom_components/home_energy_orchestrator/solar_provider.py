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


def capture_solis_solar(hass: HomeAssistant, entity_id: str | None) -> TelemetrySource | None:
    """Synchronous immutable snapshot: no await, I/O, credentials or requests."""
    if not entity_id:
        return None
    missing = TelemetrySource(entity_id, None, None, None)
    state = hass.states.get(entity_id)
    registry = er.async_get(hass).async_get(entity_id)
    if (
        state is None
        or state.attributes.get("restored", False)
        or registry is None
        or registry.platform != "solis"
    ):
        return missing
    entry_id = registry.config_entry_id
    entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
    if entry is None or entry.domain != "solis" or entry.state != ConfigEntryState.LOADED:
        return missing
    serial = state.attributes.get("Inverter serial")
    if (
        not isinstance(serial, str)
        or not serial
        or state.attributes.get("API Name") != "SolisCloud"
    ):
        return missing
    name = entry.data.get("name")
    if not isinstance(name, str) or registry.unique_id != (
        f"{serial}{name} AC Output Total Power".replace(" ", "_")
    ):
        return missing
    device = dr.async_get(hass).async_get(registry.device_id) if registry.device_id else None
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
    if not isinstance(cache, Mapping):
        return missing
    frame = dict(cache)  # Provider can replace its cache between updates, not during this snapshot.
    if frame.get("serial") != serial or frame.get("pacUnit") != "W":
        return missing
    power, timestamp = frame.get("acPower"), frame.get("timestampUpdate")
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
        return missing
    if (
        state.attributes.get("unit_of_measurement") != "W"
        or not isfinite(observed)
        or observed != power
    ):
        return missing
    return TelemetrySource(entity_id, power, "W", measured_at)
