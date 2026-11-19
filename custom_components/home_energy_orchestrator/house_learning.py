"""Learning-only source identity; no actuator or live-current authority."""

from __future__ import annotations

import json
from hashlib import sha256

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .configuration import RuntimeConfiguration


def learning_source_binding(
    hass: HomeAssistant, config: RuntimeConfiguration,
) -> tuple[str, ...]:
    """Bind unfinished energy to its commissioned sources and interpretation.

    Hash registry identities rather than publishing native identifiers in
    diagnostics. Provider health is deliberately not an identity: an outage
    marks missing evidence, while an actual mapping change starts new progress.
    """
    power, ev, connection = config.power_sources, config.ev_telemetry, config.ev_connection
    entities = (
        power.house_load_entity, power.grid_entity, power.battery_entity, power.solar_entity,
        config.battery.charge_power_entity, config.battery.discharge_power_entity,
        config.house.heater_power_entity, ev.soc_entity, ev.charging_state_entity,
        ev.actual_current_entity, connection.cable_connected_entity,
        connection.local_connection_entity, config.ev_actuators.charge_switch_entity,
        config.ev_actuators.current_limit_entity, config.ev_actuators.charge_limit_entity,
    )
    registry = er.async_get(hass)
    identities = []
    for entity_id in entities:
        row = registry.async_get(entity_id) if entity_id else None
        identities.append(
            [entity_id, row.id, row.platform, row.unique_id, row.config_entry_id,
             row.device_id, str(row.disabled_by)]
            if row else [entity_id]
        )
    electrical = config.electrical
    semantic = [
        "house-learning-v2", hass.config.time_zone, power.house_load_source,
        config.house.load_includes_ev, connection.configured,
        connection.configured_voltage_v, connection.phase_count,
        str(config.windows.free_charge_start), str(config.windows.free_charge_end),
        electrical.effective_grid_power_direction,
        electrical.battery_power_positive_direction, electrical.solar_generation_direction,
        identities,
    ]
    digest = sha256(json.dumps(semantic, separators=(",", ":")).encode()).hexdigest()
    return ("house-learning-v2", digest)
