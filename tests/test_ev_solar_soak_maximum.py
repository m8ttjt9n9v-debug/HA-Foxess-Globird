"""Maximum soak retains a protected SoC band, never extra power authority."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.home_energy_orchestrator.planner.ev_solar_soak import (
    SolarSoakMaximumInputs,
    SolarSoakMaximumState,
    plan_maximum_solar_soak,
)


def inputs(**changes):
    return replace(
        SolarSoakMaximumInputs(
            now=datetime(2026, 9, 7, 5, tzinfo=UTC),
            binding=("grid", "battery", "vehicle", 95, 90),
            enabled=True,
            eligible=True,
            telemetry_valid=True,
            battery_soc_percent=100,
            start_soc_percent=95,
            stop_soc_percent=90,
            outside_reserve_percent=15,
            solar_generation_kw=2,
            protected_energy_kwh=15,
            battery_capacity_kwh=40,
            discharge_efficiency_percent=95,
            current_ceiling_a=11,
            charger_minimum_a=1,
            current_step_a=1,
            voltage_v=230,
            phase_count=3,
            max_gap_seconds=90,
        ),
        **changes,
    )


@pytest.mark.parametrize("soc,active", [(89.9, False), (90, False), (94.999, False),
                                          (95, False), (95.001, True), (100, True)])
def test_start_boundary_is_strict_and_configured(soc, active):
    result = plan_maximum_solar_soak(
        SolarSoakMaximumState(), inputs(battery_soc_percent=soc)
    )
    assert result.state.active is active
    assert result.current_a == (11 if active else 0)


def test_jitter_around_activation_does_not_repeat_start_stop():
    state = SolarSoakMaximumState()
    base = inputs()
    targets = []
    for tick, soc in enumerate([94.9, 95, 95.01, 94.9, 95.1, 94.8, 91, 90, 90.2, 94.9, 95, 95.1]):
        result = plan_maximum_solar_soak(
            state, replace(base, now=base.now + timedelta(seconds=30 * tick),
                           battery_soc_percent=soc)
        )
        state = result.state
        targets.append(result.current_a)
    assert targets == [0, 0, 11, 11, 11, 11, 11, 0, 0, 0, 0, 11]


@pytest.mark.parametrize("soc", [89.999, 90, 90.001, 91, 95, 100])
def test_stop_floor_and_funded_tick_apply_to_a_latched_episode(soc):
    base = inputs()
    active = plan_maximum_solar_soak(SolarSoakMaximumState(), base).state
    result = plan_maximum_solar_soak(
        active, replace(base, now=base.now + timedelta(seconds=30), battery_soc_percent=soc)
    )
    if soc <= 90:
        assert result.phase == "buffer_floor" and result.current_a == 0
    elif soc == 90.001:
        assert result.phase == "energy_exhausted" and result.current_a == 0
    else:
        assert result.state.active and result.current_a == 11


def test_gross_pv_is_only_a_start_requirement_and_dips_do_not_change_current():
    base = inputs()
    assert plan_maximum_solar_soak(
        SolarSoakMaximumState(), replace(base, solar_generation_kw=0)
    ).phase == "no_solar_start"
    state = SolarSoakMaximumState()
    for tick, pv in enumerate([0.01, 8, 0, 0.1, 0, 5]):
        result = plan_maximum_solar_soak(
            state, replace(base, now=base.now + timedelta(seconds=30 * tick),
                           solar_generation_kw=pv, battery_soc_percent=96 - tick * 0.5)
        )
        assert result.current_a == 11 and result.state.active
        state = result.state


@pytest.mark.parametrize("higher_floor", [95, 96, 99, 100])
def test_existing_higher_reserve_remains_protected(higher_floor):
    base = inputs(outside_reserve_percent=higher_floor)
    blocked = plan_maximum_solar_soak(
        SolarSoakMaximumState(), replace(base, battery_soc_percent=higher_floor)
    )
    assert blocked.current_a == 0
    if higher_floor < 100:
        admitted = plan_maximum_solar_soak(SolarSoakMaximumState(), base)
        assert admitted.current_a > 0
        stopped = plan_maximum_solar_soak(
            admitted.state, replace(base, now=base.now + timedelta(seconds=30),
                                    battery_soc_percent=higher_floor)
        )
        assert stopped.current_a == 0 and not stopped.state.active


@pytest.mark.parametrize("ceiling,step,expected", [(16, 1, 16), (11.9, 1, 11),
                                                  (11.9, 2, 10), (4.4, 0.5, 4),
                                                  (0.5, 1, 0), (0, 1, 0)])
def test_existing_current_ceiling_only_rounds_down(ceiling, step, expected):
    result = plan_maximum_solar_soak(
        SolarSoakMaximumState(), inputs(current_ceiling_a=ceiling, current_step_a=step)
    )
    assert result.current_a == expected and result.current_a <= ceiling


@pytest.mark.parametrize("field", ["protected_energy_kwh", "battery_capacity_kwh",
                                   "discharge_efficiency_percent"])
def test_energy_sources_must_be_known_and_valid(field):
    for value in [None, float("nan"), float("inf"), -1, True]:
        result = plan_maximum_solar_soak(
            SolarSoakMaximumState(), inputs(**{field: value})
        )
        assert result.current_a == 0 and not result.state.active


def test_existing_pool_and_above_floor_energy_are_ceiling_the_same_interval():
    base = inputs()
    amp_kwh = 230 * 3 / 1000 * 30 / 3600
    result = plan_maximum_solar_soak(
        SolarSoakMaximumState(), replace(base, protected_energy_kwh=amp_kwh * 4)
    )
    assert result.current_a == 4
    active = plan_maximum_solar_soak(SolarSoakMaximumState(), base).state
    near_floor = plan_maximum_solar_soak(
        active, replace(base, now=base.now + timedelta(seconds=30),
                        battery_soc_percent=90.1)
    )
    assert near_floor.current_a == 6
    spent = near_floor.current_a * amp_kwh
    assert spent <= near_floor.buffer_energy_kwh
    assert near_floor.buffer_energy_kwh == pytest.approx(0.038)
    # Solar generation is not counted again to inflate the protected pool.
    assert plan_maximum_solar_soak(
        SolarSoakMaximumState(), replace(base, protected_energy_kwh=amp_kwh * 4,
                                        solar_generation_kw=100)
    ).current_a == 4


@pytest.mark.parametrize("field,value", [
    ("enabled", False), ("eligible", False), ("telemetry_valid", False),
    ("protected_energy_kwh", 0), ("battery_capacity_kwh", 0),
    ("discharge_efficiency_percent", 0), ("discharge_efficiency_percent", 101),
    ("solar_generation_kw", None), ("solar_generation_kw", -0.01),
    ("current_ceiling_a", None), ("current_step_a", 0), ("phase_count", 0),
    ("phase_count", True), ("voltage_v", 0), ("max_gap_seconds", 0),
    ("start_soc_percent", 90), ("start_soc_percent", 101),
    ("stop_soc_percent", 95), ("stop_soc_percent", -1),
    ("battery_soc_percent", float("nan")), ("outside_reserve_percent", None),
    ("binding", []), ("binding", [float("nan")]),
])
def test_invalid_or_withdrawn_authority_immediately_clears_active_intent(field, value):
    base = inputs()
    active = plan_maximum_solar_soak(SolarSoakMaximumState(), base).state
    result = plan_maximum_solar_soak(
        active, replace(base, now=base.now + timedelta(seconds=30), **{field: value})
    )
    assert result.current_a == 0 and not result.state.active
    assert result.state.to_payload() is None


@pytest.mark.parametrize("gap,retained", [(0, True), (30, True), (90, True), (90.001, False)])
def test_restore_is_bound_recent_and_does_not_renew_time(gap, retained):
    base = inputs()
    active = plan_maximum_solar_soak(SolarSoakMaximumState(), base).state
    restored = SolarSoakMaximumState.restore(
        active.to_payload(), base.now + timedelta(seconds=gap), binding=base.binding,
        max_gap_seconds=90,
    )
    assert restored.active is retained
    if retained:
        assert restored.last_at == base.now
    result = plan_maximum_solar_soak(
        restored, replace(base, now=base.now + timedelta(seconds=gap),
                          battery_soc_percent=94, solar_generation_kw=0)
    )
    assert (result.current_a == 11) is retained


@pytest.mark.parametrize("fault", ["missing", "false", "binding", "future", "naive", "nan"])
def test_corrupt_or_different_restart_evidence_never_latches(fault):
    base = inputs()
    payload = plan_maximum_solar_soak(SolarSoakMaximumState(), base).state.to_payload()
    if fault == "missing":
        payload.pop("last_at")
    elif fault == "false":
        payload["active"] = "true"
    elif fault == "binding":
        payload["binding"] = ["changed-source"]
    elif fault == "future":
        payload["last_at"] = (base.now + timedelta(seconds=1)).isoformat()
    elif fault == "naive":
        payload["last_at"] = base.now.replace(tzinfo=None).isoformat()
    else:
        payload["binding"] = [float("nan")]
    restored = SolarSoakMaximumState.restore(
        payload, base.now, binding=base.binding, max_gap_seconds=90
    )
    assert not restored.active


def test_source_setting_change_releases_the_old_band_and_requires_new_activation():
    base = inputs()
    active = plan_maximum_solar_soak(SolarSoakMaximumState(), base).state
    changed = replace(base, binding=("new-source-or-settings",),
                      now=base.now + timedelta(seconds=30), battery_soc_percent=94)
    assert plan_maximum_solar_soak(active, changed).phase == "below_start"
    # The owner may separately lower both thresholds; the new valid policy is
    # eligible on its own evidence, rather than inheriting the old journal.
    admitted = plan_maximum_solar_soak(
        active, replace(changed, start_soc_percent=93, stop_soc_percent=89)
    )
    assert admitted.state.active and admitted.state.binding == changed.binding


def test_unqualified_read_cannot_extend_retained_restart_evidence():
    base = inputs()
    active = plan_maximum_solar_soak(SolarSoakMaximumState(), base).state
    result = plan_maximum_solar_soak(
        active, replace(base, now=base.now + timedelta(seconds=80), telemetry_valid=False)
    )
    assert not result.state.active and result.state.last_at is None


@pytest.mark.parametrize("field,value", [
    ("battery_capacity_kwh", 1e308), ("voltage_v", 1e308),
    ("voltage_v", 1e-323), ("current_step_a", 1e-323),
    ("phase_count", 10 ** 500), ("binding", [10 ** 500]),
])
def test_unrepresentable_numeric_evidence_fails_closed_without_raising(field, value):
    result = plan_maximum_solar_soak(SolarSoakMaximumState(), inputs(**{field: value}))
    assert result.current_a == 0 and not result.state.active
