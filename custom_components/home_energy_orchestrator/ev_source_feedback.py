"""Bounded native source clocks for the EV-before-export extension only.

An unchanged HA entity is not a new measurement. Native Tessie publishes a
charge-state measurement clock separately; read that existing frame, never its
HTTP-fetch time, and require it to agree with every explicitly mapped input.
No requests, wakeups, synthetic timestamps, entity writes or cached permissions.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from math import isfinite

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er


def _retained_valid(item, now):
    return (
        item.available_state is not None and not item.restored
        and item.last_reported is not None and item.last_reported <= now
    )


def before_export_vehicle_feedback_valid(hass, feedback, *, now, max_age_seconds):
    """Qualify one vehicle cohort without changing ordinary/maintenance rules."""
    items = (
        feedback.soc, feedback.current_limit, feedback.charge_limit,
        feedback.cable_connected, feedback.charging_state,
        feedback.actual_current, feedback.charge_switch,
    )
    if any(not _retained_valid(item, now) for item in items):
        return False
    strict_fresh = all(item.fresh(now, max_age_seconds) for item in items) and (
        feedback.physical_observation(now=now, max_age_seconds=max_age_seconds).available
    )
    registry = er.async_get(hass)
    soc = registry.async_get(feedback.soc.entity_id) if feedback.soc.entity_id else None
    if soc is None or soc.platform != "tessie":
        # An arbitrary mapped publisher has no established native-frame contract.
        return strict_fresh
    entry = hass.config_entries.async_get_entry(soc.config_entry_id)
    device = dr.async_get(hass).async_get(soc.device_id) if soc.device_id else None
    if (
        entry is None or entry.domain != "tessie" or entry.state != ConfigEntryState.LOADED
        or device is None or entry.entry_id not in device.config_entries
    ):
        return False
    vins = {value for domain, value in device.identifiers if domain == "tessie"}
    if len(vins) != 1:
        return False
    vin = next(iter(vins))
    fields = (
        (feedback.soc, "charge_state_usable_battery_level"),
        (feedback.current_limit, "charge_state_charge_current_request"),
        (feedback.charge_limit, "charge_state_charge_limit_soc"),
        (feedback.cable_connected, "charge_state_conn_charge_cable"),
        (feedback.charging_state, "charge_state_charging_state"),
        (feedback.actual_current, "charge_state_charger_actual_current"),
        (feedback.charge_switch, "charge_state_charge_enable_request"),
    )
    for item, field in fields:
        row = registry.async_get(item.entity_id) if item.entity_id else None
        if row is None or row.platform != "tessie":
            return strict_fresh  # Preserve fresh explicit mixed-source mappings.
        if (
            row.disabled_by is not None
            or row.config_entry_id != entry.entry_id or row.device_id != device.id
            or row.unique_id != f"{vin}-{field}"
        ):
            return False
    vehicles = getattr(getattr(entry, "runtime_data", None), "vehicles", None)
    if isinstance(vehicles, Mapping):
        vehicles = vehicles.values()
    elif not isinstance(vehicles, (list, tuple)):
        return False
    matches = [vehicle for vehicle in vehicles if getattr(vehicle, "vin", None) == vin]
    if len(matches) != 1:
        return False
    provider = getattr(matches[0], "data_coordinator", None)
    if (
        provider is None or getattr(provider, "last_update_success", False) is not True
        or getattr(getattr(provider, "config_entry", None), "entry_id", None) != entry.entry_id
    ):
        return False
    data = getattr(provider, "data", None)
    if not isinstance(data, Mapping) or data.get("state") != "online":
        return False
    stamp = data.get("charge_state_timestamp")
    if type(stamp) not in (int, float) or not isfinite(stamp):
        return False
    try:
        observed_at = datetime.fromtimestamp(stamp / 1000, UTC)
    except (OverflowError, OSError, ValueError):
        return False
    if not isfinite(max_age_seconds) or not (
        0 <= (now - observed_at).total_seconds() <= max_age_seconds
    ):
        return False
    for item, field in (
        (feedback.soc, "charge_state_usable_battery_level"),
        (feedback.current_limit, "charge_state_charge_current_request"),
        (feedback.charge_limit, "charge_state_charge_limit_soc"),
        (feedback.actual_current, "charge_state_charger_actual_current"),
    ):
        value = data.get(field)
        if type(value) not in (int, float) or not isfinite(value) or item.number != value:
            return False
    cable = data.get("charge_state_conn_charge_cable")
    charging = data.get("charge_state_charging_state")
    if not isinstance(cable, str) or not isinstance(charging, str):
        return False  # Includes optimistic command booleans, not vehicle feedback.
    state = {"Charging": "charging", "Stopped": "stopped", "Complete": "complete",
             "Disconnected": "disconnected", "NoPower": "no_power"}.get(charging)
    return (
        state is not None and feedback.charging_state.available_state == state
        and feedback.cable_connected.available_state == ("off" if cable == "<invalid>" else "on")
        and feedback.charge_switch.available_state == ("on" if state == "charging" else "off")
        and feedback.actual_current.current_a is not None and feedback.actual_current.current_a >= 0
        and feedback.current_limit.unit == "A" and feedback.actual_current.unit == "A"
        and feedback.soc.number is not None and 0 <= feedback.soc.number <= 100
    )


def before_export_inverter_feedback_valid(hass, mode, battery_soc, grid, *, now, max_age_seconds):
    """Retain stable mode/SoC only with the mapped inverter's live local grid.

    FoxESS mode/SoC may not publish when unchanged. They remain value evidence,
    while the existing fast electrical gates prove the connection is alive.
    A different inverter, generic template or failed/unloaded entry cannot
    refresh this evidence. Generic mode publishers retain the original limit.
    """
    if not _retained_valid(mode, now) or not _retained_valid(battery_soc, now):
        return False
    if mode.fresh(now, max_age_seconds):
        return True  # Existing fresh mode does not need a native alternative.
    registry = er.async_get(hass)
    mode_row = registry.async_get(mode.entity_id) if mode.entity_id else None
    if mode_row is None or mode_row.platform != "foxess_modbus":
        return False
    entry = hass.config_entries.async_get_entry(mode_row.config_entry_id)
    if (
        entry is None or entry.domain != "foxess_modbus" or entry.state != ConfigEntryState.LOADED
        or mode_row.disabled_by is not None or not mode_row.device_id
    ):
        return False
    device = dr.async_get(hass).async_get(mode_row.device_id)
    if device is None or entry.entry_id not in device.config_entries:
        return False
    ids = [battery_soc.entity_id, *(source.entity_id for source in grid.sources)]
    if len(ids) < 2:
        return False
    for entity_id in ids:
        row = registry.async_get(entity_id) if entity_id else None
        if (
            row is None or row.platform != "foxess_modbus" or row.disabled_by is not None
            or row.config_entry_id != entry.entry_id or row.device_id != mode_row.device_id
        ):
            return False
    return True
