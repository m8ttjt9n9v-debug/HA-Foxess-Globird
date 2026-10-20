"""Read an explicitly mapped native Solis cached frame; never call its API.

Compatibility: hultenvp/solis-sensor 4.0.x SolisCloud InverterService. Its HA
power entity writes only when power changes, so HA report age cannot prove
whether a constant value is current. Read AC power AND measurement time from
the same already-fetched frame, bound to the native entity/entry/device.
Unsupported or partial caches fail closed; no name discovery or clock fallback.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from types import MappingProxyType
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .telemetry import TelemetrySource

FRAME_FIELDS = ("serial", "pacUnit", "acPower", "timestampUpdate", "state")


@dataclass(frozen=True, slots=True)
class _NativeBinding:
    state: Any
    serial: str
    service: Any
    api: Any
    identity: tuple


def _native_binding(hass, entity_id, report) -> _NativeBinding | None:
    """The unchanged explicit entity/entry/device qualification boundary."""
    state = hass.states.get(entity_id)
    registry = er.async_get(hass).async_get(entity_id)
    report("entity_or_registry_unqualified")
    if (
        state is None
        or state.attributes.get("restored", False)
        or registry is None
        or registry.platform != "solis"
    ):
        return None
    entry_id = registry.config_entry_id
    entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
    report("native_entry_unqualified")
    if entry is None or entry.domain != "solis" or entry.state != ConfigEntryState.LOADED:
        return None
    serial = state.attributes.get("Inverter serial")
    report("native_provider_identity_unqualified")
    if (
        not isinstance(serial, str)
        or not serial
        or state.attributes.get("API Name") != "SolisCloud"
    ):
        return None
    name = entry.data.get("name")
    report("native_entity_identity_mismatch")
    if not isinstance(
        name, str
    ) or registry.unique_id != f"{serial}{name} AC Output Total Power".replace(" ", "_"):
        return None
    device = dr.async_get(hass).async_get(registry.device_id) if registry.device_id else None
    report("native_device_binding_mismatch")
    if (
        device is None
        or entry_id not in device.config_entries
        or ("solis", f"{serial}_SolisCloud") not in device.identifiers
    ):
        return None
    runtime = hass.data.get("solis", {})
    service = runtime.get(entry_id) if isinstance(runtime, Mapping) else None
    api = getattr(service, "_api", None)
    report(
        "native_cache_unavailable",
        runtime_is_mapping=isinstance(runtime, Mapping),
        service_present=service is not None,
        api_present=api is not None,
        cache_is_mapping=isinstance(getattr(api, "_data", None), Mapping),
    )
    if service is None or api is None:
        return None
    return _NativeBinding(
        state,
        serial,
        service,
        api,
        (entity_id, entry_id, registry.unique_id, registry.device_id, serial),
    )


class _FrameListener:
    """Native InverterService subscriber; receives one inverter's publication."""

    entity_type = "sensor"

    def __init__(self, owner, binding):
        self.owner, self.binding = owner, binding

    def data_updated(self, value, _last_updated):
        # The native service dispatches a complete GinlongData synchronously;
        # its serial publication precedes the next inverter fetch. Never use
        # the service's poll clock to freshen the provider's measurement time.
        if self.owner._listener is not self:
            return
        self.owner._frame = None
        cache = getattr(self.binding.api, "_data", None)
        if (
            value != self.binding.serial
            or not isinstance(cache, Mapping)
            or cache.get("serial") != value
            or getattr(self.binding.service, "_api", None) is not self.binding.api
        ):
            return
        self.owner._frame = MappingProxyType(
            {
                key: cache[key] if type(cache[key]) in (str, int, float, bool, type(None)) else None
                for key in FRAME_FIELDS
                if key in cache
            }
        )


class SolisPublishedFrames:
    """Own one read-only native subscription, never an API request or timer."""

    def __init__(self, hass):
        self.hass = hass
        self._listener: _FrameListener | None = None
        self._frame: Mapping | None = None

    def close(self):
        listener, self._listener = self._listener, None
        self._frame = None
        if listener is not None:
            subscriptions = getattr(listener.binding.service, "_subscriptions", {})
            group = (
                subscriptions.get(listener.binding.serial, {})
                if isinstance(subscriptions, Mapping)
                else {}
            )
            listeners = group.get("serial", []) if isinstance(group, Mapping) else []
            if isinstance(listeners, list) and listener in listeners:
                listeners.remove(listener)  # Remove only this entry's observer.

    def ensure_source(self, entity_id):
        if not entity_id:
            self.close()
            return
        binding = _native_binding(self.hass, entity_id, lambda *_args, **_kwargs: None)
        old = self._listener.binding if self._listener else None
        if binding is None or binding.service is None or binding.api is None:
            self.close()
            return
        if (
            old is not None
            and old.identity == binding.identity
            and old.service is binding.service
            and old.api is binding.api
        ):
            return
        self.close()
        subscribe = getattr(binding.service, "subscribe", None)
        subscriptions = getattr(binding.service, "_subscriptions", None)
        if not callable(subscribe) or not isinstance(subscriptions, Mapping):
            return  # Unsupported publishers cannot supply a guessed frame.
        listener = _FrameListener(self, binding)
        self._listener = listener
        try:
            subscribe(listener, binding.serial, "serial")
            # A matching current complete native cache may seed startup. An
            # account's other inverter can NEVER seed the selected source.
            listener.data_updated(binding.serial, None)
        except Exception:
            self.close()

    def current_frame(self):
        if self._listener is None:
            return None
        old = self._listener.binding
        current = _native_binding(self.hass, old.identity[0], lambda *_args, **_kwargs: None)
        if (
            current is None
            or current.identity != old.identity
            or current.service is not old.service
            or current.api is not old.api
        ):
            return None
        return self._frame


def capture_solis_solar(
    hass: HomeAssistant,
    entity_id: str | None,
    *,
    cached_frame,
    diagnostics: dict[str, object] | None = None,
) -> TelemetrySource | None:
    """Synchronous immutable snapshot: no await, I/O, credentials or requests."""

    def report(reason: str, **values: object) -> None:
        if diagnostics is not None:
            diagnostics.update(reason=reason, capture_accepted=False, **values)

    report("not_configured")
    if not entity_id:
        return None
    missing = TelemetrySource(entity_id, None, None, None)
    binding = _native_binding(hass, entity_id, report)
    if binding is None:
        return missing
    state, serial = binding.state, binding.serial
    cache = cached_frame
    if diagnostics is not None:
        diagnostics["frame_origin"] = "selected_inverter_publication"
    report("native_cache_unavailable")
    if not isinstance(cache, Mapping):
        return missing
    frame = dict(cache)  # Provider can replace its cache between updates, not during this snapshot.
    if diagnostics is not None:
        # Never expose arbitrary keys/values, IDs, serials, URLs or credentials.
        diagnostics["frame_fields"] = {
            key: {
                "present": key in frame,
                "type": (
                    type(frame[key]).__name__
                    if key in frame and type(frame[key]) in (str, int, float, bool, type(None))
                    else "other"
                ),
            }
            for key in FRAME_FIELDS
        }
        diagnostics["frame_serial_matches"] = frame.get("serial") == serial
        diagnostics["frame_unit"] = (
            frame.get("pacUnit")
            if frame.get("pacUnit") in ("W", "kW")
            else "missing"
            if "pacUnit" not in frame
            else "unsupported"
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
