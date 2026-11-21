"""Bounded history for the optional afternoon solar-spill policy extension."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import floor, isfinite

from .ev_outside_window import EV_CONTROL_INTERVAL
from .timed_average import TimedAverageWindow


class SolarSoakAverage:
    """Average only contiguous qualified observations, never a stale tail."""

    def __init__(self, duration):
        self.window = TimedAverageWindow(duration)
        self.binding = None

    def configure(self, duration):
        """A changed averaging window starts new evidence, not a stretched tail."""
        if duration != self.window.duration:
            self.window = TimedAverageWindow(duration)
            self.binding = None

    def clear(self):
        self.window.samples.clear()
        self.binding = None

    def observe(self, now, value, *, binding, max_gap_seconds):
        now = now.astimezone(UTC)
        binding = list(binding)
        if self.needs_reset(now, binding=binding, max_gap_seconds=max_gap_seconds):
            self.clear()
        self.binding = binding
        self.window.observe(now, value, source_valid=True)
        self.window.samples = self.window.samples[-512:]
        result = self.window.result(now)
        # Start with the first observed value, not invented historical coverage.
        return value if result.value is None else result.value

    def needs_reset(self, now, *, binding, max_gap_seconds):
        return (
            self.binding != list(binding)
            or not self.window.samples
            or not 0
            <= (now.astimezone(UTC) - self.window.samples[-1].at.astimezone(UTC)).total_seconds()
            <= max_gap_seconds
        )

    def to_payload(self):
        if not self.window.samples:
            return None
        return {"binding": self.binding, "window": self.window.to_payload()}

    def restore(self, payload, now, *, binding, max_gap_seconds):
        now = now.astimezone(UTC)
        self.clear()
        if not isinstance(payload, dict) or payload.get("binding") != list(binding):
            return False
        window = payload.get("window")
        rows = window.get("samples") if isinstance(window, dict) else None
        if not isinstance(rows, list) or not rows or len(rows) > 512:
            return False
        try:
            last = None
            for row in rows:
                at = datetime.fromisoformat(row["at"])
                value = row["value"]
                if (
                    at.tzinfo is None
                    or at > now
                    or isinstance(value, bool)
                    or not isinstance(value, (float, int))
                    or not isfinite(value)
                    or value < 0
                    or row["source_valid"] is not True
                    or last is not None
                    and not 0 < (at - last).total_seconds() <= max_gap_seconds
                ):
                    return False
                last = at
            if not 0 <= (now - last).total_seconds() <= max_gap_seconds:
                return False
        except (KeyError, ValueError, TypeError):
            return False
        self.window.restore(window, now)
        self.binding = list(binding)
        return True


@dataclass(frozen=True, slots=True)
class SolarSoakMaximumState:
    """A source-bound hysteresis episode, never independent power authority.

    The existing EV journal may retain this optional payload. ``last_at`` is
    the last qualified policy evaluation, not a replacement source timestamp.
    The caller must still qualify current evidence before every command.
    """

    active: bool = False
    binding: tuple[object, ...] | None = None
    last_at: datetime | None = None

    def to_payload(self) -> dict[str, object] | None:
        """Encode only a valid active episode; inactive clears old intent."""
        if (
            self.active is not True
            or _maximum_binding(self.binding) is None
            or not _maximum_clock(self.last_at)
        ):
            return None
        return {
            "active": True,
            "binding": list(self.binding),
            "last_at": self.last_at.astimezone(UTC).isoformat(),
        }

    @classmethod
    def restore(
        cls,
        payload: object,
        now: datetime,
        *,
        binding: object,
        max_gap_seconds: float,
    ) -> SolarSoakMaximumState:
        """Retain a recent compatible episode without renewing its clock."""
        expected = _maximum_binding(binding)
        if (
            not isinstance(payload, dict)
            or payload.get("active") is not True
            or expected is None
            or _maximum_binding(payload.get("binding")) != expected
            or not _maximum_clock(now)
            or not _maximum_number(max_gap_seconds, positive=True)
        ):
            return cls()
        try:
            at = datetime.fromisoformat(payload["last_at"])
        except (KeyError, TypeError, ValueError):
            return cls()
        if not _maximum_clock(at):
            return cls()
        age = (now.astimezone(UTC) - at.astimezone(UTC)).total_seconds()
        if not 0 <= age <= max_gap_seconds:
            return cls()
        return cls(active=True, binding=expected, last_at=at)


@dataclass(frozen=True, slots=True)
class SolarSoakMaximumInputs:
    """Qualified inputs to the opt-in maximum-rate afternoon extension.

    ``eligible`` includes the retained location/connection/EV-target, policy
    ownership and scheduling gates. ``telemetry_valid`` includes original
    source clocks and coherent electrical/current evidence. The ceiling and
    protected pool are already bounded by the existing controller; this
    extension can only reduce them. Bind the source and relevant settings.
    """

    now: datetime
    binding: object
    enabled: bool
    eligible: bool
    telemetry_valid: bool
    battery_soc_percent: float | None
    start_soc_percent: float | None
    stop_soc_percent: float | None
    outside_reserve_percent: float | None
    solar_generation_kw: float | None
    protected_energy_kwh: float | None
    battery_capacity_kwh: float | None
    discharge_efficiency_percent: float | None
    current_ceiling_a: float | None
    charger_minimum_a: float | None
    current_step_a: float | None
    voltage_v: float | None
    phase_count: int | None
    max_gap_seconds: float


@dataclass(frozen=True, slots=True)
class SolarSoakMaximumDecision:
    """One existing-writer candidate and its retained activation episode."""

    state: SolarSoakMaximumState
    current_a: float
    phase: str
    buffer_energy_kwh: float = 0.0


def plan_maximum_solar_soak(
    state: SolarSoakMaximumState,
    inputs: SolarSoakMaximumInputs,
) -> SolarSoakMaximumDecision:
    """Start above the high boundary; retain to the lower protected floor.

    Positive gross solar is required to start. Once qualified, fresh zero PV
    may represent an ordinary cloud; battery energy above the stop floor can
    carry the configured current. Missing/stale evidence, lost ownership or
    an exhausted pool always withdraw immediately. No new current or energy
    authority is created, and no average sets the maximum-mode target.
    """
    inactive = SolarSoakMaximumState()

    def stop(phase: str) -> SolarSoakMaximumDecision:
        return SolarSoakMaximumDecision(inactive, 0.0, phase)

    if inputs.enabled is not True:
        return stop("disabled")
    if not _maximum_clock(inputs.now) or not _maximum_number(
        inputs.max_gap_seconds, positive=True
    ):
        return stop("clock_invalid")
    binding = _maximum_binding(inputs.binding)
    if binding is None:
        return stop("binding_unavailable")
    if not (
        _maximum_number(inputs.start_soc_percent)
        and _maximum_number(inputs.stop_soc_percent)
        and 0 <= inputs.stop_soc_percent < inputs.start_soc_percent <= 100
    ):
        return stop("thresholds_invalid")
    if not (
        _maximum_number(inputs.battery_soc_percent)
        and _maximum_number(inputs.outside_reserve_percent)
        and 0 <= inputs.battery_soc_percent <= 100
        and 0 <= inputs.outside_reserve_percent <= 100
    ):
        return stop("battery_soc_unavailable")
    if inputs.eligible is not True:
        return stop("not_eligible")
    if inputs.telemetry_valid is not True:
        return stop("telemetry_unavailable")
    if not _maximum_number(inputs.solar_generation_kw) or inputs.solar_generation_kw < 0:
        return stop("solar_generation_unavailable")
    if not (
        _maximum_number(inputs.battery_capacity_kwh, positive=True)
        and _maximum_number(inputs.discharge_efficiency_percent, positive=True)
        and inputs.discharge_efficiency_percent <= 100
        and _maximum_number(inputs.protected_energy_kwh)
        and inputs.protected_energy_kwh >= 0
    ):
        return stop("energy_unavailable")
    if not (
        _maximum_number(inputs.voltage_v, positive=True)
        and type(inputs.phase_count) is int
        and _maximum_number(inputs.phase_count, positive=True)
        and _maximum_number(inputs.current_step_a, positive=True)
        and _maximum_number(inputs.charger_minimum_a)
        and inputs.charger_minimum_a >= 0
        and _maximum_number(inputs.current_ceiling_a)
        and inputs.current_ceiling_a >= 0
    ):
        return stop("topology_unavailable")
    floor_percent = max(inputs.stop_soc_percent, inputs.outside_reserve_percent)
    if inputs.battery_soc_percent <= floor_percent:
        return stop("buffer_floor")
    retained = SolarSoakMaximumState.restore(
        state.to_payload(), inputs.now, binding=binding, max_gap_seconds=inputs.max_gap_seconds
    )
    if not retained.active:
        if inputs.battery_soc_percent <= max(inputs.start_soc_percent, floor_percent):
            return stop("below_start")
        if inputs.solar_generation_kw <= 0:
            return stop("no_solar_start")

    # Both amounts are ceilings on the same battery-funded interval, never
    # cumulative deductions. No future solar is counted to fund the request.
    buffer_energy = (
        inputs.battery_capacity_kwh
        * (inputs.battery_soc_percent - floor_percent)
        / 100
        * inputs.discharge_efficiency_percent
        / 100
    )
    funded_energy = min(inputs.protected_energy_kwh, buffer_energy)
    energy_per_amp = (
        inputs.voltage_v
        * inputs.phase_count
        / 1000
        * EV_CONTROL_INTERVAL.total_seconds()
        / 3600
    )
    if not isfinite(buffer_energy):
        return stop("energy_unavailable")
    if not isfinite(energy_per_amp) or energy_per_amp <= 0:
        return stop("topology_unavailable")
    ceiling = min(inputs.current_ceiling_a, funded_energy / energy_per_amp)
    steps = ceiling / inputs.current_step_a
    if not isfinite(steps):
        return stop("topology_unavailable")
    stepped = floor(round(steps, 9)) * inputs.current_step_a
    minimum = max(inputs.charger_minimum_a, inputs.current_step_a)
    if stepped < minimum:
        phase = (
            "energy_exhausted"
            if funded_energy <= energy_per_amp * minimum else "below_charger_minimum"
        )
        return stop(phase)
    return SolarSoakMaximumDecision(
        SolarSoakMaximumState(True, binding, inputs.now.astimezone(UTC)),
        round(stepped, 3),
        "solar_soak_maximum",
        buffer_energy,
    )


def _maximum_number(value: object, *, positive: bool = False) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value) and (not positive or value > 0)
    except OverflowError:
        return False


def _maximum_clock(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _maximum_binding(value: object) -> tuple[object, ...] | None:
    if not isinstance(value, (list, tuple)) or not value:
        return None
    if any(
        item is not None
        and not isinstance(item, (str, bool))
        and not _maximum_number(item)
        for item in value
    ):
        return None
    return tuple(value)
