from custom_components.home_energy_orchestrator.const import EV_REQUIRED_ENTITY_KEYS
from custom_components.home_energy_orchestrator.ev_adapter import ev_control_gate_status


def commissioned_config(**changes):
    config = {
        "ev_automatic_control_enabled": True,
        "rehearsal_mode": False,
        "ev_control_commissioned": True,
        **{key: f"sensor.{index}" for index, key in enumerate(EV_REQUIRED_ENTITY_KEYS)},
    }
    config.update(changes)
    return config


def test_gate_priority_is_explicit_and_fail_closed():
    assert ev_control_gate_status({}) == "disabled"
    assert (
        ev_control_gate_status({"ev_automatic_control_enabled": True})
        == "safety_locked"
    )
    assert (
        ev_control_gate_status(
            {"ev_automatic_control_enabled": True, "rehearsal_mode": False}
        )
        == "not_commissioned"
    )
    config = commissioned_config(ev_charge_switch_entity=None)
    assert ev_control_gate_status(config) == "incomplete_mapping"
    assert ev_control_gate_status(commissioned_config()) == "adapter_not_connected"
    assert (
        ev_control_gate_status(commissioned_config(), adapter_connected=True) == "ready"
    )


def test_multiphase_control_requires_explicit_most_loaded_phase_current():
    config = commissioned_config(site_phase_count=3)
    assert (
        ev_control_gate_status(config, adapter_connected=True)
        == "multiphase_current_mapping_required"
    )
    config["site_grid_current_entity"] = "sensor.grid_max_phase_current"
    assert ev_control_gate_status(config, adapter_connected=True) == "ready"
