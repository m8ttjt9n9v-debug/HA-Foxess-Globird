"""Tests for explicit FoxESS hardware-profile validation."""

from __future__ import annotations

from custom_components.home_energy_orchestrator.planner.profile import (
    FoxessProfile,
    validate_foxess_profile,
)


def profile(**changes) -> FoxessProfile:
    values = dict(
        model="H3-15.0-Smart",
        firmware="Master 1.47 / Manager 1.29",
        phase_count=3,
        battery_model="FoxESS HV battery",
        battery_soc_entity="sensor.battery_soc",
        grid_power_entity="sensor.grid_ct",
        load_power_entity="sensor.load_power",
        work_mode_entity="select.work_mode",
        force_charge_power_entity="number.force_charge_power",
        force_discharge_power_entity="number.force_discharge_power",
        safe_restore_mode="Self Use",
        supported_modes=("Self Use", "Force Charge", "Force Discharge"),
        charge_power_max_kw=15,
        discharge_power_max_kw=15,
    )
    values.update(changes)
    return FoxessProfile(**values)


def test_profile_is_valid_for_read_only_and_actuator_commissioning() -> None:
    assert validate_foxess_profile(profile()) == ()
    assert validate_foxess_profile(profile(), require_actuators=True) == ()


def test_profile_does_not_infer_missing_actuators() -> None:
    errors = validate_foxess_profile(
        profile(work_mode_entity=None, force_charge_power_entity=None), require_actuators=True
    )
    assert errors == (
        "work_mode_entity_missing",
        "force_charge_power_entity_missing",
    )


def test_profile_rejects_unsafe_limits_and_restore_mode() -> None:
    errors = validate_foxess_profile(profile(charge_power_max_kw=0, safe_restore_mode="Backup"))
    assert errors == ("charge_power_max_kw_invalid", "safe_restore_mode_unsupported")
