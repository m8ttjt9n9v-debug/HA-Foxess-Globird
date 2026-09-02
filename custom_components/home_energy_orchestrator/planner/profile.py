"""Commissioned, adapter-neutral FoxESS profile validation."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class FoxessProfile:
    """The explicit site facts required before FoxESS writes are possible."""

    model: str
    firmware: str
    phase_count: int
    battery_model: str
    battery_soc_entity: str
    grid_power_entity: str
    load_power_entity: str | None
    work_mode_entity: str | None
    force_charge_power_entity: str | None
    force_discharge_power_entity: str | None
    safe_restore_mode: str
    supported_modes: tuple[str, ...]
    charge_power_max_kw: float
    discharge_power_max_kw: float


def validate_foxess_profile(
    profile: FoxessProfile, *, require_actuators: bool = False
) -> tuple[str, ...]:
    """Return commissioning errors without making assumptions about hardware."""
    errors: list[str] = []
    if not profile.model.strip():
        errors.append("model_missing")
    if profile.phase_count not in (1, 3):
        errors.append("phase_count_invalid")
    if not profile.battery_model.strip():
        errors.append("battery_model_missing")
    for field_name in ("battery_soc_entity", "grid_power_entity"):
        if not getattr(profile, field_name).strip():
            errors.append(f"{field_name}_missing")
    if profile.load_power_entity is not None and not profile.load_power_entity.strip():
        errors.append("load_power_entity_invalid")
    for field_name in ("charge_power_max_kw", "discharge_power_max_kw"):
        value = getattr(profile, field_name)
        if not isfinite(value) or value <= 0:
            errors.append(f"{field_name}_invalid")
    if not profile.safe_restore_mode.strip():
        errors.append("safe_restore_mode_missing")
    if profile.safe_restore_mode not in profile.supported_modes:
        errors.append("safe_restore_mode_unsupported")
    if require_actuators:
        for field_name in (
            "work_mode_entity",
            "force_charge_power_entity",
            "force_discharge_power_entity",
        ):
            value = getattr(profile, field_name)
            if value is None or not value.strip():
                errors.append(f"{field_name}_missing")
        for mode in ("Self Use", "Force Charge", "Force Discharge"):
            if mode not in profile.supported_modes:
                errors.append(f"mode_{mode.casefold().replace(' ', '_')}_unsupported")
    return tuple(errors)
