"""Process-local maintenance fence; never a persistent control setting."""

KEY = "heo_maintenance_fence"


def maintenance_writes_blocked(hass) -> bool:
    """All HEO actuator paths share this gate, including delayed commands."""
    return hass.data.get(KEY) is True
