import pytest

from custom_components.home_energy_orchestrator.configuration import RuntimeConfiguration
from custom_components.home_energy_orchestrator.const import EV_REQUIRED_ENTITY_KEYS
from custom_components.home_energy_orchestrator.ev_adapter import ev_control_gate_status


def commissioned_config(**changes):
    config = {
        "ev_automatic_control_enabled": True,
        "rehearsal_mode": False,
        "ev_control_commissioned": True,
        "sign_conventions_verified": True,
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
        == "sign_conventions_unverified"
    )
    config = commissioned_config(ev_charge_switch_entity=None)
    assert ev_control_gate_status(config) == "incomplete_mapping"
    assert ev_control_gate_status(commissioned_config()) == "adapter_not_connected"
    assert (
        ev_control_gate_status(commissioned_config(), adapter_connected=True) == "ready"
    )

    explicitly_absent = commissioned_config(configure_ev=False)
    assert ev_control_gate_status(explicitly_absent, adapter_connected=True) == "disabled"


def test_multiphase_control_requires_explicit_most_loaded_phase_current():
    config = commissioned_config(site_phase_count=3)
    assert (
        ev_control_gate_status(config, adapter_connected=True)
        == "multiphase_current_mapping_required"
    )
    config["site_grid_current_entity"] = "sensor.grid_max_phase_current"
    assert ev_control_gate_status(config, adapter_connected=True) == "ready"


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"ev_charge_path": "smart_socket"}, "smart_socket_mapping_required"),
        (
            {
                "ev_charge_path": "smart_socket",
                "ev_smart_socket_entity": "switch.car_socket",
            },
            "smart_socket_limit_invalid",
        ),
        (
            {
                "ev_charge_path": "smart_socket",
                "ev_smart_socket_entity": "switch.car_socket",
                "ev_smart_socket_current_limit_a": "invalid",
            },
            "smart_socket_limit_invalid",
        ),
        (
            {
                "ev_charge_path": "smart_socket",
                "ev_smart_socket_entity": "switch.car_socket",
                "ev_smart_socket_current_limit_a": 16,
            },
            "ready",
        ),
        ({"site_phase_count": None}, "invalid_site_topology"),
        ({"site_phase_count": "invalid"}, "invalid_site_topology"),
        ({"site_phase_count": float("nan")}, "ready"),
    ],
)
def test_typed_gate_preserves_mapping_input_outcomes(changes, expected):
    """The compatibility adapter and typed snapshot must have identical gates."""
    config = commissioned_config(**changes)
    runtime = RuntimeConfiguration.from_mapping(config)

    assert ev_control_gate_status(config, adapter_connected=True) == expected
    assert ev_control_gate_status(runtime, adapter_connected=True) == expected
