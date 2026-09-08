from custom_components.home_energy_orchestrator.discovery import (
    DiscoveryEntity,
    discover_entity_defaults,
)


def _entity(entity_id, platform, entry="one", *, disabled=False):
    return DiscoveryEntity(entity_id, platform, entry, disabled=disabled)


def test_discovers_observed_foxess_and_tessie_roles():
    result = discover_entity_defaults(
        [
            _entity("sensor.battery_soc", "foxess_modbus", "fox"),
            _entity("sensor.grid_ct", "foxess_modbus", "fox"),
            _entity("sensor.load_power", "foxess_modbus", "fox"),
            _entity("select.work_mode", "foxess_modbus", "fox"),
            _entity("number.force_charge_power", "foxess_modbus", "fox"),
            _entity("sensor.jns_x_battery_level", "tessie", "car"),
            _entity("device_tracker.jns_x_location", "tessie", "car"),
            _entity("binary_sensor.jns_x_charge_cable", "tessie", "car"),
            _entity("sensor.jns_x_charging", "tessie", "car"),
            _entity("number.jns_x_charge_current", "tessie", "car"),
            _entity("number.jns_x_charge_limit", "tessie", "car"),
            _entity("switch.jns_x_charge", "tessie", "car"),
        ]
    )

    assert result["battery_soc_entity"] == "sensor.battery_soc"
    assert result["grid_power_entity"] == "sensor.grid_ct"
    assert result["ev_soc_entity"] == "sensor.jns_x_battery_level"
    assert result["ev_charging_state_entity"] == "sensor.jns_x_charging"
    assert result["ev_charge_switch_entity"] == "switch.jns_x_charge"


def test_equal_device_cohorts_are_ambiguous_and_not_mixed():
    result = discover_entity_defaults(
        [
            _entity("sensor.car_one_battery_level", "tessie", "car-one"),
            _entity("number.car_one_charge_current", "tessie", "car-one"),
            _entity("sensor.car_two_battery_level", "tessie", "car-two"),
            _entity("number.car_two_charge_current", "tessie", "car-two"),
        ]
    )
    assert not any(key.startswith("ev_") for key in result)


def test_disabled_and_near_name_entities_are_not_suggested():
    result = discover_entity_defaults(
        [
            _entity("sensor.battery_soc", "foxess_modbus", disabled=True),
            _entity("sensor.grid_ct_estimate", "foxess_modbus"),
            _entity("sensor.jns_x_charging", "tessie", disabled=True),
        ]
    )
    assert result == {}
