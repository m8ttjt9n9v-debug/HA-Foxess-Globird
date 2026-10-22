"""Read-only, explicitly commissioned local EV connection evidence.

An ordinary mapped binary sensor owns its report clock. Native Tesla Wall
Connector entities may remain unchanged across local HTTP publications, so a
small lifecycle-owned subscriber timestamps only genuine new native payloads.
It never reads the charger, seeds an old cache, wakes a vehicle or writes state.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

DOMAIN = "tesla_wall_connector"


@dataclass(frozen=True, slots=True)
class LocalEvConnectionObservation:
    """Connection evidence only, never independent export/charging authority."""

    status: str
    source: str
    observed_at: datetime | None = None
    reason: str = ""
    contactor_open: bool = False
    connected_since: datetime | None = None

    @property
    def connected_idle(self) -> bool:
        """Only a qualified native publication can prove a connected open contactor."""
        return self.status == "connected" and self.contactor_open

    @property
    def disconnected(self) -> bool:
        """Return true only for affirmative qualified disconnection."""
        return self.status == "disconnected"

    @property
    def available(self) -> bool:
        """Return whether the connection has a qualified binary observation."""
        return self.status in {"connected", "disconnected"}


@dataclass(frozen=True, slots=True)
class _Binding:
    identity: tuple
    provider: object


def _native_binding(hass, entity_id: str) -> _Binding | None:
    row = er.async_get(hass).async_get(entity_id)
    if (
        row is None or row.platform != DOMAIN or row.disabled_by is not None
        or not row.config_entry_id or not row.device_id
    ):
        return None
    entry = hass.config_entries.async_get_entry(row.config_entry_id)
    device = dr.async_get(hass).async_get(row.device_id)
    if (
        entry is None or entry.domain != DOMAIN or entry.state != ConfigEntryState.LOADED
        or device is None or entry.entry_id not in device.config_entries
    ):
        return None
    runtime = getattr(entry, "runtime_data", None)
    serial = getattr(runtime, "serial_number", None)
    serials = {value for domain, value in device.identifiers if domain == DOMAIN}
    provider = getattr(runtime, "update_coordinator", None)
    if (
        not isinstance(serial, str) or not serial or serials != {serial}
        or row.unique_id != f"{serial}-vehicle_connected" or provider is None
        or getattr(provider, "config_entry", None) is not entry
        or not callable(getattr(provider, "async_add_listener", None))
    ):
        return None
    return _Binding((entity_id, entry.entry_id, device.id, row.unique_id, serial), provider)


def _fresh(stamp, now, maximum_age) -> bool:
    if (
        not isinstance(stamp, datetime) or type(maximum_age) not in (int, float)
        or not isfinite(maximum_age) or maximum_age < 0
    ):
        return False
    try:
        return 0 <= (now - stamp).total_seconds() <= maximum_age
    except (TypeError, ValueError, OverflowError):
        return False


def _vitals(provider) -> tuple[bool, bool] | None:
    data = getattr(provider, "data", None)
    vitals = data.get("vitals") if isinstance(data, Mapping) else None
    connected = getattr(vitals, "vehicle_connected", None)
    contactor = getattr(vitals, "contactor_closed", None)
    if type(connected) is not bool or type(contactor) is not bool:
        return None
    return connected, contactor


class LocalEvConnectionObserver:
    """Observe an existing publisher; close on controller unload/rebinding."""

    def __init__(self, hass):
        self.hass = hass
        self._binding: _Binding | None = None
        self._remove_listener: Callable[[], None] | None = None
        self._frame: tuple[bool, bool, datetime] | None = None
        self._published_data: object | None = None
        self._entity_id: str | None = None
        self._native_source = False
        self._connection_state: bool | None = None
        self._connected_since: datetime | None = None

    def close(self):
        """Discard all evidence and remove only our native subscription."""
        remove, self._remove_listener = self._remove_listener, None
        self._binding = None
        self._frame = None
        self._published_data = None
        self._connection_state = None
        self._connected_since = None
        if remove is not None:
            try:
                remove()
            except Exception:
                # A provider may already have torn down its listener table.
                # Evidence is discarded first; stale callbacks cannot revive it.
                pass

    def ensure_source(self, entity_id: str | None):
        """Rebind only to the explicitly selected, currently loaded source."""
        row = er.async_get(self.hass).async_get(entity_id) if entity_id else None
        if entity_id != self._entity_id:
            self._entity_id = entity_id
            self._native_source = False
        if row is not None and row.platform == DOMAIN:
            self._native_source = True
        binding = _native_binding(self.hass, entity_id) if row and row.platform == DOMAIN else None
        old = self._binding
        if (
            old is not None and binding is not None and old.identity == binding.identity
            and old.provider is binding.provider
        ):
            return
        self.close()
        if binding is None:
            return
        # Adding the first native coordinator listener would start polling.
        # A commissioned live entity already has its own subscription; never
        # become the reason this optional provider starts requesting data.
        listeners = getattr(binding.provider, "_listeners", None)
        if not isinstance(listeners, Mapping) or not listeners:
            return
        self._binding = binding
        self._published_data = getattr(binding.provider, "data", None)

        def published():
            if self._binding is not binding:
                return
            current = _native_binding(self.hass, binding.identity[0])
            if (
                current is None or current.identity != binding.identity
                or current.provider is not binding.provider
            ):
                self.close()
                return
            provider = binding.provider
            if getattr(provider, "last_update_success", False) is not True:
                self._frame = None
                return
            data = getattr(provider, "data", None)
            if data is self._published_data:
                return  # A repeated callback/cache cannot renew its clock.
            self._published_data = data
            self._frame = None
            values = _vitals(provider)
            if values is not None:
                at = dt_util.utcnow()
                if self._connection_state is False and values[0]:
                    self._connected_since = at
                elif not values[0]:
                    self._connected_since = None
                self._connection_state = values[0]
                self._frame = (*values, at)

        try:
            self._remove_listener = binding.provider.async_add_listener(published)
        except Exception:
            self.close()

    def capture(self, entity_id: str | None, *, now, max_age_seconds):
        """Capture connection evidence; no command, request or retained lease."""
        self.ensure_source(entity_id)
        if not entity_id:
            return LocalEvConnectionObservation("unmapped", "unmapped", reason="unmapped")
        state = self.hass.states.get(entity_id)
        row = er.async_get(self.hass).async_get(entity_id)
        native = self._native_source
        source = DOMAIN if native else "entity_report"

        def unknown(reason):
            return LocalEvConnectionObservation("unknown", source, reason=reason)

        if (
            not entity_id.startswith("binary_sensor.") or state is None
            or state.state not in {"on", "off"} or state.attributes.get("restored") is True
            or row is not None and row.disabled_by is not None
        ):
            return unknown("invalid_entity")
        stamp = getattr(state, "last_reported", state.last_updated)
        try:
            if not isinstance(stamp, datetime) or stamp > now:
                return unknown("invalid_entity_clock")
        except TypeError:
            return unknown("invalid_entity_clock")
        if native:
            binding, frame = self._binding, self._frame
            if (
                binding is None
                or getattr(binding.provider, "last_update_success", False) is not True
            ):
                self._frame = None
                return unknown("native_unavailable")
            current = _vitals(binding.provider)
            if current is None or (state.state == "on") != current[0]:
                self._frame = None
                return unknown("native_mismatch")
            if current[1]:
                self._frame = None
                if current[0]:
                    return LocalEvConnectionObservation(
                        "connected", source, reason="native_connected"
                    )
                return unknown("native_contactor_closed")
            if getattr(binding.provider, "data", None) is not self._published_data:
                self._frame = None
                if current[0]:
                    return LocalEvConnectionObservation(
                        "connected", source, reason="native_connected"
                    )
                return unknown("awaiting_native_publication")
            if frame is None or current != frame[:2]:
                if current[0]:
                    return LocalEvConnectionObservation(
                        "connected", source, reason="native_connected"
                    )
                return unknown("awaiting_native_publication")
            stamp = frame[2]
            if not _fresh(stamp, now, max_age_seconds):
                return unknown("native_publication_expired")
            return LocalEvConnectionObservation(
                "connected" if current[0] else "disconnected", source, stamp,
                "native_connected_stopped" if current[0] else "native_disconnected",
                contactor_open=True,
                connected_since=self._connected_since,
            )
        if row is not None and row.config_entry_id:
            entry = self.hass.config_entries.async_get_entry(row.config_entry_id)
            if entry is None or entry.state != ConfigEntryState.LOADED:
                return unknown("source_unloaded")
        if not _fresh(stamp, now, max_age_seconds):
            return unknown("entity_report_expired")
        status = "connected" if state.state == "on" else "disconnected"
        return LocalEvConnectionObservation(status, source, stamp, status)
