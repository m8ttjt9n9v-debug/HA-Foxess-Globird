"""Unit and sign normalisation isolated from Home Assistant runtime code."""

POWER_TO_KW = {"W": 0.001, "kW": 1.0, "MW": 1000.0}


def power_to_kw(value: float, unit: str | None) -> float:
    """Convert a supported power value to kW; reject ambiguity."""
    try:
        return value * POWER_TO_KW[unit or ""]
    except KeyError as err:
        raise ValueError(f"Unsupported power unit: {unit!r}") from err


def percent(value: float) -> float:
    """Validate a percentage without silently accepting invalid telemetry."""
    if not 0 <= value <= 100:
        raise ValueError(f"Percentage outside 0–100: {value}")
    return value


def signed_grid_power_to_import_kw(value_kw: float, import_positive: bool) -> float:
    """Return import-positive power for either documented site convention."""
    return value_kw if import_positive else -value_kw
