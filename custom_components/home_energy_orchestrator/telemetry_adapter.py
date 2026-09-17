"""Home Assistant adapter for capturing raw site telemetry evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from homeassistant.core import HomeAssistant, State

from .planner.forecast import RetailerScorecardObservation
from .telemetry import SiteTelemetrySources, TelemetrySource


@dataclass(frozen=True, slots=True)
class TelemetryEntityIds:
    """Configured entity IDs used for one source capture."""

    grid_power: str | None
    signed_battery_power: str | None
    battery_charge_power: str | None
    battery_discharge_power: str | None
    solar_power: str | None
    house_load: str | None
    site_grid_current: str | None


class StateTimestamp(Protocol):
    """Timestamp selector accepted by the source-capture compatibility seam."""

    def __call__(self, state: State) -> datetime: ...


def state_reported_at(state: State) -> datetime:
    """Use Home Assistant's report time so stable polled values stay fresh."""
    return getattr(state, "last_reported", state.last_updated)


def capture_telemetry_source(
    hass: HomeAssistant,
    entity_id: object,
    *,
    reported_at: StateTimestamp = state_reported_at,
) -> TelemetrySource | None:
    """Capture one configured source without interpreting unit or sign."""
    if not isinstance(entity_id, str) or not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None:
        return TelemetrySource(entity_id, None, None, None)
    return TelemetrySource(
        entity_id=entity_id,
        raw_value=state.state,
        raw_unit=state.attributes.get("unit_of_measurement"),
        updated_at=reported_at(state),
    )


def capture_site_telemetry(
    hass: HomeAssistant, entity_ids: TelemetryEntityIds
) -> SiteTelemetrySources:
    """Capture all raw sources without applying units or sign conventions."""
    return SiteTelemetrySources(
        grid_power=capture_telemetry_source(hass, entity_ids.grid_power),
        signed_battery_power=capture_telemetry_source(
            hass, entity_ids.signed_battery_power
        ),
        battery_charge_power=capture_telemetry_source(
            hass, entity_ids.battery_charge_power
        ),
        battery_discharge_power=capture_telemetry_source(
            hass, entity_ids.battery_discharge_power
        ),
        solar_power=capture_telemetry_source(hass, entity_ids.solar_power),
        house_load=capture_telemetry_source(hass, entity_ids.house_load),
        site_grid_current=capture_telemetry_source(
            hass, entity_ids.site_grid_current
        ),
    )


def capture_retailer_scorecard(
    hass: HomeAssistant,
    *,
    cost_entity: str | None,
    status_entity: str | None,
) -> RetailerScorecardObservation:
    """Capture only fields required for the read-only forecast scorecard."""
    cost_state = hass.states.get(cost_entity) if cost_entity else None
    status_state = hass.states.get(status_entity) if status_entity else None
    return RetailerScorecardObservation(
        cost_configured=bool(cost_entity),
        status_configured=bool(status_entity),
        cost_available=cost_state is not None,
        status_available=status_state is not None,
        cost_complete=(
            bool(cost_state.attributes.get("latest_available_day_complete", False))
            if cost_state is not None
            else False
        ),
        status_complete=(
            bool(status_state.attributes.get("latest_available_day_complete", False))
            if status_state is not None
            else False
        ),
        cost_date=(
            cost_state.attributes.get("latest_available_day")
            or cost_state.attributes.get("latest_day")
            if cost_state is not None
            else None
        ),
        status_date=(
            status_state.attributes.get("latest_available_day")
            or status_state.attributes.get("latest_day")
            if status_state is not None
            else None
        ),
        cost_value=cost_state.state if cost_state is not None else None,
        status_value=status_state.state if status_state is not None else None,
    )
