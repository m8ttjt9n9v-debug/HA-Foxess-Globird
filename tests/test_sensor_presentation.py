from types import SimpleNamespace

from custom_components.home_energy_orchestrator.const import (
    CONF_AUTOMATIC_CHARGE_ENABLED,
    CONF_AUTOMATIC_CONTROL_ENABLED,
    CONF_AUTOMATIC_EXPORT_ENABLED,
    CONF_FOXESS_CONTROL_OWNER,
    FOXESS_CONTROL_OWNER_MODBUS,
)
from custom_components.home_energy_orchestrator.sensor import EnergySensor


def _sensor(*, config, controller):
    sensor = object.__new__(EnergySensor)
    sensor.coordinator = SimpleNamespace(
        config=config,
        active_controller=controller,
    )
    return sensor


def test_status_uses_commissioned_control_mode_instead_of_ledger_reason():
    sensor = _sensor(
        config={
            CONF_FOXESS_CONTROL_OWNER: FOXESS_CONTROL_OWNER_MODBUS,
            CONF_AUTOMATIC_CONTROL_ENABLED: True,
            CONF_AUTOMATIC_CHARGE_ENABLED: True,
            CONF_AUTOMATIC_EXPORT_ENABLED: True,
        },
        controller=SimpleNamespace(gate_status="ready"),
    )

    assert sensor._control_mode() == "local_modbus_charge_and_export"


def test_ev_priority_withholds_dormant_export_plan_from_dashboard():
    candidate_plan = SimpleNamespace(
        planned_export_energy_kwh=7.6,
        planned_duration_h=0.76,
    )
    controller = SimpleNamespace(
        export_effective_enabled=False,
        export_plan=candidate_plan,
        ev_before_export_decision=SimpleNamespace(
            export_allowed=False,
            reason="ev_below_target",
        ),
        export_session=SimpleNamespace(phase="idle"),
    )
    sensor = _sensor(
        config={CONF_AUTOMATIC_EXPORT_ENABLED: True},
        controller=controller,
    )

    assert sensor._effective_export_plan() is None
    assert sensor._export_status() == "withheld_ev_below_target"
