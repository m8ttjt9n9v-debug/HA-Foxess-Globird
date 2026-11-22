"""Replay Dynamic reservation outages through the existing EV/export owners."""

from datetime import timedelta

import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.home_energy_orchestrator.ev_active import ActiveEvController
from custom_components.home_energy_orchestrator.ev_current_measurement import (
    measure_ev_current,
    measure_ev_soc,
)
from custom_components.home_energy_orchestrator.foxess_adapter import FoxessWriteBlocked
from custom_components.home_energy_orchestrator.planner.foxess_export_policy import (
    evaluate_foxess_export_policy,
)
from tests.test_ev_backfill_timing import _fresh
from tests.test_ev_dynamic_reservation_runtime import (
    _budget,
    _context,
    _publish_vehicle,
    _rig,
    _services,
)
from tests.test_ev_dynamic_reservation_runtime import (
    native_provider_cleanup as native_provider_cleanup,
)
from tests.test_ev_dynamic_reservation_runtime import (
    utc_clock as utc_clock,
)

BEHAVIOR = "ev_reservation_unavailable_behavior"
TIMEOUT = "ev_reservation_unplugged_soc_max_age_minutes"
LOCAL_CABLE = "binary_sensor.local_ev_connected"


def _publish_current_modbus(rig):
    """Publish this trace's fresh electrical cohort without a vehicle report.

    The older fixture refreshed only its cached model. Positive command checks
    now independently read the commissioned raw sources, so each explicit local
    publication must supply those HA states too. Reads never renew a clock.
    """
    telemetry = rig.coordinator.telemetry
    for key, sample in (
        ("grid_power_entity", telemetry.grid_power),
        ("battery_power_entity", telemetry.battery_power),
        ("house_load_entity", telemetry.house_load),
    ):
        assert len(sample.sources) == 1
        source = sample.sources[0]
        assert source.entity_id == rig.coordinator.config[key]
        assert source.updated_at == rig.now
        rig.coordinator.hass.states.async_set(
            source.entity_id, str(source.raw_value), {"unit_of_measurement": source.raw_unit},
            timestamp=rig.now.timestamp(), force_update=True,
        )
    raw = rig.coordinator._normalized_telemetry(rig.now)
    assert raw.grid_power.valid and raw.grid_power.fresh
    assert raw.battery_power.valid and raw.battery_power.fresh


def _advance(freezer, rig, elapsed):
    rig.now += elapsed
    freezer.move_to(rig.now)
    _fresh(rig.coordinator, rig.now)
    _publish_current_modbus(rig)


def _offline(hass, rig, *, reported_soc="unavailable"):
    rig.provider.data["state"] = "offline"
    hass.states.async_set("sensor.car_soc", reported_soc, {"unit_of_measurement": "%"})


async def _restart_ev(hass, rig):
    rig.controller = ActiveEvController(hass, rig.coordinator)
    rig.coordinator.ev_controller = rig.controller
    await rig.controller._async_restore()


def _export_budget(rig, *, available=24, house=5, keepalive=0):
    return rig.controller.reservation_budget(
        rig.now, available_ac_kwh=available, protected_house_kwh=house, keepalive_kwh=keepalive,
        allow_retained_soc=True,
    )


@pytest.mark.parametrize(("soc", "reserve"), [(35, 3.6), (53, 0)])
@pytest.mark.parametrize("home", [False, True])
async def test_last_known_replays_verified_soc_after_a_week_and_restart(
    hass, freezer, soc, reserve, home,
):
    rig = await _rig(hass, freezer, **{
        BEHAVIOR: "last_known", "ev_automatic_control_enabled": False,
    })
    _publish_vehicle(hass, rig, soc=soc, home=home, connected=False)
    await rig.controller.async_reconcile(rig.now)

    _advance(freezer, rig, timedelta(days=7))
    _offline(hass, rig)
    await _restart_ev(hass, rig)
    budget = _export_budget(rig, available=12, house=6, keepalive=1)
    assert budget.valid
    assert budget.requested_reservation_kwh == pytest.approx(reserve)
    assert budget.exportable_kwh == pytest.approx(5 - reserve)
    assert _export_budget(rig, available=6, house=6, keepalive=1).exportable_kwh == 0
    assert not _budget(rig).valid
    for price in (False, True):
        policy = evaluate_foxess_export_policy(_context(hass, rig, price=price))
        assert policy.eligible
        assert policy.protected_ev_kwh == pytest.approx(reserve)

    feedback = rig.controller._capture_feedback()
    assert measure_ev_soc(hass, feedback, now=rig.now, max_age_seconds=90) is None
    assert not measure_ev_current(hass, feedback, now=rig.now, max_age_seconds=90).valid

    # A qualified return reading replaces the retained value, even below minimum.
    _publish_vehicle(hass, rig, soc=25, home=True, connected=True)
    assert _budget(rig).requested_reservation_kwh == pytest.approx(9.6)
    assert rig.controller.dynamic_topup_requested(rig.now)
    assert not rig.fox._ev_before_export_handoff_ready(rig.now)


@pytest.mark.parametrize(("minutes", "age", "valid"), [
    (None, 5399.999, True), (None, 5400, True), (None, 5400.001, False),
    (15, 900, True), (15, 900.001, False), (0, 31, False),
])
async def test_timeout_uses_original_measurement_age_at_inclusive_cutoff(
    hass, freezer, minutes, age, valid,
):
    changes = {} if minutes is None else {TIMEOUT: minutes}
    rig = await _rig(hass, freezer, **changes)
    _publish_vehicle(hass, rig, soc=35, home=False, connected=False)
    measured = rig.now - timedelta(seconds=30)
    rig.provider.data["charge_state_timestamp"] = measured.timestamp() * 1000
    await rig.controller.async_reconcile(rig.now)

    _advance(freezer, rig, timedelta(seconds=age - 30))
    # A new HA publication cannot age the original Tessie frame backwards.
    _offline(hass, rig, reported_soc="35")
    await _restart_ev(hass, rig)
    assert _export_budget(rig).valid is valid
    assert rig.controller.daily_backfill_protection_kwh(rig.now, allow_retained_soc=True) == (
        pytest.approx(3.6) if valid else None
    )
    policy = evaluate_foxess_export_policy(_context(hass, rig, price=True))
    assert policy.eligible is valid
    if not valid:
        assert policy.finish_requested
    assert rig.provider.data["charge_state_timestamp"] == measured.timestamp() * 1000

    _publish_vehicle(hass, rig, soc=53, home=False, connected=False)
    assert _export_budget(rig).valid
    assert _export_budget(rig).requested_reservation_kwh == 0


@pytest.mark.parametrize("behavior", ["last_known", "timeout"])
@pytest.mark.parametrize("fault", ["no_history", "future_frame", "rebound", "anchor_mismatch"])
async def test_outage_without_matching_verified_history_holds_export(
    hass, freezer, behavior, fault,
):
    rig = await _rig(hass, freezer, **{BEHAVIOR: behavior})
    _publish_vehicle(hass, rig, soc=53, home=False, connected=False)
    if fault == "future_frame":
        rig.provider.data["charge_state_timestamp"] = (
            rig.now + timedelta(seconds=1)
        ).timestamp() * 1000
        await rig.controller.async_reconcile(rig.now)
    elif fault != "no_history":
        await rig.controller.async_reconcile(rig.now)
        registry = er.async_get(hass)
        if fault == "rebound":
            registry.async_update_entity("sensor.car_soc", new_unique_id="other-vehicle")
        else:
            registry.async_update_entity("binary_sensor.car_cable", new_unique_id="other-cable")
    _offline(hass, rig)
    assert not _export_budget(rig).valid
    for price in (False, True):
        assert not evaluate_foxess_export_policy(_context(hass, rig, price=price)).eligible


async def test_saved_value_keeps_its_clock_when_provider_republishes_without_a_measurement(
    hass, freezer,
):
    rig = await _rig(hass, freezer, **{BEHAVIOR: "last_known"})
    _publish_vehicle(hass, rig, soc=35, home=False, connected=False)
    stamp = rig.provider.data["charge_state_timestamp"]
    await rig.controller.async_reconcile(rig.now)

    _advance(freezer, rig, timedelta(minutes=1))
    _publish_vehicle(hass, rig, soc=53, home=False, connected=False)
    rig.provider.data["charge_state_timestamp"] = stamp
    await rig.controller.async_reconcile(rig.now)

    _advance(freezer, rig, timedelta(minutes=5))
    _offline(hass, rig)
    await _restart_ev(hass, rig)
    assert _export_budget(rig).requested_reservation_kwh == pytest.approx(3.6)


@pytest.mark.parametrize(("state", "minutes_old"), [("asleep", 120), ("online", 10)])
async def test_qualified_planning_only_sample_can_seed_history_before_outage(
    hass, freezer, state, minutes_old,
):
    rig = await _rig(hass, freezer, **{BEHAVIOR: "last_known"})
    _publish_vehicle(hass, rig, soc=35, home=False, connected=False)
    measured = rig.now - timedelta(minutes=minutes_old)
    rig.provider.data.update(state=state, charge_state_timestamp=measured.timestamp() * 1000)
    await rig.controller.async_reconcile(rig.now)
    assert _budget(rig).requested_reservation_kwh == pytest.approx(3.6)
    assert measure_ev_soc(
        hass, rig.controller._capture_feedback(), now=rig.now, max_age_seconds=90,
    ) is None

    _advance(freezer, rig, timedelta(days=7))
    _offline(hass, rig)
    await _restart_ev(hass, rig)
    assert _export_budget(rig).requested_reservation_kwh == pytest.approx(3.6)
    assert rig.provider.data["charge_state_timestamp"] == measured.timestamp() * 1000


@pytest.mark.parametrize("registered", [True, False])
async def test_generic_soc_outage_requires_a_registered_publisher_for_history(
    hass, freezer, registered,
):
    rig = await _rig(hass, freezer, **{BEHAVIOR: "last_known"})
    registry = er.async_get(hass)
    registry.async_remove("sensor.car_soc")
    if registered:
        hass.states.async_remove("sensor.car_soc")
        publisher = registry.async_get_or_create(
            "sensor", "mqtt", "registered-vehicle-soc", suggested_object_id="car_soc",
        )
        assert publisher.entity_id == "sensor.car_soc"
    _publish_vehicle(hass, rig, soc=35, home=False, connected=False)
    await rig.controller.async_reconcile(rig.now)
    assert _budget(rig).requested_reservation_kwh == pytest.approx(3.6)

    _advance(freezer, rig, timedelta(days=7))
    hass.states.async_set("sensor.car_soc", "unavailable")
    await _restart_ev(hass, rig)
    budget = _export_budget(rig)
    assert budget.valid is registered
    if registered:
        assert budget.requested_reservation_kwh == pytest.approx(3.6)


@pytest.mark.parametrize("fault", ["future_frame", "disagreeing_soc", "invalid_soc"])
async def test_affirmative_bad_reading_cannot_fall_back_to_an_old_zero_reserve(
    hass, freezer, fault,
):
    rig = await _rig(hass, freezer, **{BEHAVIOR: "last_known"})
    _publish_vehicle(hass, rig, soc=53, home=False, connected=False)
    await rig.controller.async_reconcile(rig.now)

    _advance(freezer, rig, timedelta(minutes=5))
    _publish_vehicle(hass, rig, soc=35, home=False, connected=False)
    if fault == "future_frame":
        rig.provider.data["charge_state_timestamp"] = (
            rig.now + timedelta(seconds=1)
        ).timestamp() * 1000
    elif fault == "disagreeing_soc":
        rig.provider.data["charge_state_usable_battery_level"] = 45
    else:
        hass.states.async_set("sensor.car_soc", "101", {"unit_of_measurement": "%"})
    assert not _export_budget(rig).valid


async def test_outage_mode_edit_applies_to_existing_record_on_next_export_evaluation(hass, freezer):
    rig = await _rig(hass, freezer, **{BEHAVIOR: "last_known"})
    _publish_vehicle(hass, rig, soc=35, home=False, connected=False)
    await rig.controller.async_reconcile(rig.now)
    _advance(freezer, rig, timedelta(days=20))
    _offline(hass, rig)
    assert _export_budget(rig).valid

    rig.coordinator.update_config_value(BEHAVIOR, "timeout")
    assert not _export_budget(rig).valid
    assert not evaluate_foxess_export_policy(_context(hass, rig, price=True)).eligible

    rig.coordinator.update_config_value(BEHAVIOR, "last_known")
    assert _export_budget(rig).requested_reservation_kwh == pytest.approx(3.6)


async def test_last_known_requires_independent_physical_handoff_for_real_export(
    hass, freezer, monkeypatch,
):
    rig = await _rig(
        hass, freezer, **{BEHAVIOR: "last_known", "ev_local_connection_entity": LOCAL_CABLE},
    )
    calls = _services(hass, monkeypatch, rig)
    _publish_vehicle(hass, rig, soc=53, home=True, connected=False)
    await rig.controller.async_reconcile(rig.now)

    _advance(freezer, rig, timedelta(days=7))
    _offline(hass, rig)
    await _restart_ev(hass, rig)
    assert _export_budget(rig).valid
    assert not rig.fox._ev_before_export_handoff_ready(rig.now)
    await rig.fox.async_reconcile()
    assert not rig.fox.export_effective_enabled
    assert not any(value == "Force Discharge" for _, value in calls)

    hass.states.async_set(LOCAL_CABLE, "off")
    await rig.fox.async_reconcile()
    assert rig.fox.ev_export_handoff_reason == "local_disconnected"
    assert rig.fox.export_effective_enabled
    assert ("select.foxess_mode", "Force Discharge") in calls
    calls.clear()

    # A local reconnect invalidates independent unplugged proof during the outage.
    hass.states.async_set(LOCAL_CABLE, "on")
    await rig.fox.async_reconcile()
    await rig.controller.async_reconcile(rig.now)
    assert not rig.fox.export_effective_enabled
    assert ("select.foxess_mode", "Self Use") in calls
    assert not any(
        value == "Force Discharge"
        or (entity == "switch.car_charge" and value == "on")
        or (entity == "number.car_current" and value > 0)
        for entity, value in calls
    )


@pytest.mark.parametrize("cross_during_write", [False, True])
async def test_timeout_withdraws_live_export_at_original_deadline(
    hass, freezer, monkeypatch, cross_during_write,
):
    rig = await _rig(hass, freezer, **{TIMEOUT: 15, "ev_local_connection_entity": LOCAL_CABLE})
    calls = _services(hass, monkeypatch, rig)
    _publish_vehicle(hass, rig, soc=53, home=False, connected=False)
    await rig.controller.async_reconcile(rig.now)
    _advance(freezer, rig, timedelta(minutes=15))
    _offline(hass, rig)
    hass.states.async_set(LOCAL_CABLE, "off")
    assert _export_budget(rig).valid
    if cross_during_write:
        repository = type(rig.fox._export_repository)
        save = repository.async_save

        async def cross_deadline(self, state):
            await save(self, state)
            if self is rig.fox._export_repository:
                _advance(freezer, rig, timedelta(milliseconds=1))

        monkeypatch.setattr(repository, "async_save", cross_deadline)
        with pytest.raises(FoxessWriteBlocked):
            await rig.fox.async_reconcile()
    else:
        await rig.fox.async_reconcile()
        assert ("select.foxess_mode", "Force Discharge") in calls
        calls.clear()
        _advance(freezer, rig, timedelta(milliseconds=1))
        await rig.fox.async_reconcile()
        assert not rig.fox.export_effective_enabled
        assert ("select.foxess_mode", "Self Use") in calls
    assert not any(
        value == "Force Discharge" or (entity == "number.foxess_discharge" and value > 0)
        for entity, value in calls
    )
