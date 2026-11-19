"""House collection survives EV gaps without granting physical-control authority."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.const import DOMAIN
from custom_components.home_energy_orchestrator.coordinator import EnergyCoordinator
from custom_components.home_energy_orchestrator.ev_current_measurement import measure_ev_current
from custom_components.home_energy_orchestrator.ev_observation_adapter import (
    capture_ev_feedback,
    ev_observation_entity_map,
)
from custom_components.home_energy_orchestrator.models import SiteSnapshot
from custom_components.home_energy_orchestrator.planner.learning import DemandPersistenceState

from .test_ev_before_export_source_clocks import (
    native_provider_cleanup as native_provider_cleanup,
)
from .test_ev_before_export_source_clocks import utc_clock as utc_clock
from .test_ev_delayed_current_runtime import _asleep_unplugged, _house_learner, _morning
from .test_setup import ENTRY_DATA, _entity_id


def _collector(hass, monkeypatch, **changes):
    coordinator = EnergyCoordinator(
        hass,
        {
            **ENTRY_DATA,
            "free_charge_window_start": "12:00:00",
            "free_charge_window_end": "15:00:00",
            **changes,
        },
        "house-collection-regression",
    )
    coordinator.snapshot = SiteSnapshot(
        battery_soc=50,
        battery_capacity_kwh=20,
        battery_floor_percent=10,
        reserve_kwh=0,
        grid_power_kw=0,
        house_load_kw=4,
    )
    monkeypatch.setattr(coordinator, "_async_save_demand_state", AsyncMock())
    return coordinator


async def _observe(coordinator, monkeypatch, at):
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.coordinator.dt_util.now",
        lambda: at,
    )
    await coordinator._async_sample_house_load()


async def test_raw_house_collects_while_ev_gap_remains_explicit(hass, monkeypatch):
    coordinator = _collector(hass, monkeypatch, house_load_includes_ev=True)
    monkeypatch.setattr(coordinator, "_state_qualified_ev_power_kw", lambda _now: None)
    start = datetime(2026, 11, 17, 12, tzinfo=UTC)
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    try:
        for minute in range(0, 24 * 60 + 1, 5):
            await _observe(coordinator, monkeypatch, start + timedelta(minutes=minute))
        raw = coordinator.raw_house_sampler.last_cycle
        qualified = coordinator.demand_sampler.last_cycle
        assert raw["complete"] is True
        assert raw["energy_kwh"] == pytest.approx(4 * 21)
        assert qualified["complete"] is False
        assert qualified["energy_kwh"] == 0
        assert qualified["missing_seconds"] == pytest.approx(21 * 3600)
        assert coordinator.demand_history.samples == []
        await hass.async_block_till_done()
        assert calls == []
    finally:
        coordinator.shutdown()


async def test_house_gap_is_not_recorded_as_zero_even_without_ev(hass, monkeypatch):
    coordinator = _collector(hass, monkeypatch)
    start = datetime(2026, 11, 17, 12, tzinfo=UTC)
    try:
        for minute in range(0, 3 * 60 + 1, 5):
            await _observe(coordinator, monkeypatch, start + timedelta(minutes=minute))
        coordinator.snapshot = None
        await _observe(coordinator, monkeypatch, start + timedelta(hours=3, minutes=5))
        coordinator.snapshot = SiteSnapshot(
            battery_soc=50,
            battery_capacity_kwh=20,
            battery_floor_percent=10,
            reserve_kwh=0,
            grid_power_kw=0,
            house_load_kw=4,
        )
        await _observe(coordinator, monkeypatch, start + timedelta(hours=3, minutes=10))
        # Preserve the existing bounded left-method bridge rather than teaching
        # five minutes of zero consumption or rejecting a recoverable day.
        assert coordinator.raw_house_sampler.missing_seconds == 0
        assert coordinator.demand_sampler.missing_seconds == 0
        assert coordinator.raw_house_sampler.known_energy_kwh == pytest.approx(4 / 6)
        assert coordinator.demand_sampler.known_energy_kwh == pytest.approx(4 / 6)
        assert coordinator.demand_history.samples == []
    finally:
        coordinator.shutdown()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("house_load_entity", "sensor.replacement_house"),
        ("house_load_includes_ev", True),
        ("heater_power_entity", "sensor.replacement_heater"),
        ("battery_charge_power_entity", "sensor.replacement_battery_charge"),
        ("battery_discharge_power_entity", "sensor.replacement_battery_discharge"),
        ("ev_voltage", 240),
        ("ev_phase_count", 3),
        ("free_charge_window_start", "11:00:00"),
        ("free_charge_window_end", "14:00:00"),
    ],
)
async def test_source_edits_reset_progress_but_preserve_completed_history(
    hass, monkeypatch, key, value,
):
    coordinator = _collector(hass, monkeypatch)
    start = datetime(2026, 11, 17, 12, tzinfo=UTC)
    coordinator.demand_history.add(start - timedelta(days=1), 17)
    try:
        for minute in range(0, 4 * 60 + 1, 5):
            await _observe(coordinator, monkeypatch, start + timedelta(minutes=minute))
        assert coordinator.demand_sampler.known_energy_kwh == pytest.approx(4)
        before = coordinator._learning_source_binding()
        coordinator.update_config_value(key, value)
        assert coordinator._learning_source_binding() != before
        await _observe(coordinator, monkeypatch, start + timedelta(hours=4, minutes=5))
        assert coordinator.demand_sampler.known_energy_kwh == 0
        assert coordinator.raw_house_sampler.known_energy_kwh == 0
        assert [s.energy_kwh for s in coordinator.demand_history.samples] == [17]
        assert coordinator.demand_sampler.free_window_start.isoformat() == (
            value if key == "free_charge_window_start" else "12:00:00"
        )
        assert coordinator.demand_sampler.free_window_end.isoformat() == (
            value if key == "free_charge_window_end" else "15:00:00"
        )
    finally:
        coordinator.shutdown()


async def test_non_source_setting_does_not_erase_collected_progress(hass, monkeypatch):
    coordinator = _collector(hass, monkeypatch)
    start = datetime(2026, 11, 17, 12, tzinfo=UTC)
    try:
        for minute in range(0, 4 * 60 + 1, 5):
            await _observe(coordinator, monkeypatch, start + timedelta(minutes=minute))
        before = coordinator._learning_source_binding()
        coordinator.update_config_value("reserve_kwh", 3)
        assert coordinator._learning_source_binding() == before
        await _observe(coordinator, monkeypatch, start + timedelta(hours=4, minutes=5))
        assert coordinator.demand_sampler.known_energy_kwh == pytest.approx(4 + 4 / 12)
    finally:
        coordinator.shutdown()


@pytest.mark.parametrize("provider_state", ["online", "asleep"])
@pytest.mark.parametrize("retained_current", [1, 2, 3])
async def test_confirmed_unplug_can_learn_despite_current_echo_without_refreshing_control(
    hass, freezer, provider_state, retained_current,
):
    rig = _morning(hass, freezer)
    _asleep_unplugged(hass, rig, rig.now - timedelta(hours=2))
    rig.provider.data["state"] = provider_state
    rig.provider.data["charge_state_charger_actual_current"] = retained_current
    hass.states.async_set(
        "sensor.car_actual_current", str(retained_current), {"unit_of_measurement": "A"}
    )
    coordinator = _house_learner(hass, rig)
    try:
        feedback = capture_ev_feedback(hass, ev_observation_entity_map(coordinator.runtime_config))
        assert not measure_ev_current(hass, feedback, now=rig.now, max_age_seconds=90).valid
        assert coordinator._protected_house_learning_power_kw(rig.now) == 6
        assert not measure_ev_current(hass, feedback, now=rig.now, max_age_seconds=90).valid
    finally:
        coordinator.shutdown()


async def test_learning_unplug_exception_withdraws_on_local_reconnect(hass, freezer):
    rig = _morning(hass, freezer)
    _asleep_unplugged(hass, rig, rig.now - timedelta(hours=2))
    coordinator = _house_learner(
        hass, rig, ev_local_connection_entity="binary_sensor.local_charger_connected"
    )
    try:
        hass.states.async_set("binary_sensor.local_charger_connected", "off")
        assert coordinator._protected_house_learning_power_kw(rig.now) == 6
        hass.states.async_set("binary_sensor.local_charger_connected", "on")
        assert coordinator._protected_house_learning_power_kw(rig.now) is None
        coordinator.snapshot = replace(coordinator.snapshot, house_load_kw=9)
        assert coordinator._protected_house_learning_power_kw(rig.now) is None
    finally:
        coordinator.shutdown()


async def test_raw_and_qualified_progress_restore_independently(hass, monkeypatch):
    coordinator = _collector(hass, monkeypatch, house_load_includes_ev=True)
    monkeypatch.setattr(coordinator, "_state_qualified_ev_power_kw", lambda _now: None)
    start = datetime(2026, 11, 17, 12, tzinfo=UTC)
    coordinator.demand_history.add(start - timedelta(days=1), 17)
    restarted = None
    try:
        for minute in range(0, 4 * 60 + 1, 5):
            await _observe(coordinator, monkeypatch, start + timedelta(minutes=minute))
        repository = SimpleNamespace(async_save=AsyncMock())
        coordinator._demand_repository = repository
        await EnergyCoordinator._async_save_demand_state(coordinator)
        saved = repository.async_save.call_args.args[0].to_payload()
        assert saved["raw_house_in_progress_cycle"]["cycle_energy_kwh"] == pytest.approx(4)
        assert saved["in_progress_cycle"]["cycle_missing_seconds"] == pytest.approx(3600)
        assert saved["source_binding"] == list(coordinator._learning_source_binding())
        restored_at = start + timedelta(hours=4, minutes=1)
        state = DemandPersistenceState.restore(saved, restored_at)
        restarted = _collector(hass, monkeypatch, house_load_includes_ev=True)
        monkeypatch.setattr(restarted, "_state_qualified_ev_power_kw", lambda _now: None)
        restarted._demand_repository = SimpleNamespace(async_load=AsyncMock(return_value=state))
        monkeypatch.setattr(
            "custom_components.home_energy_orchestrator.coordinator.dt_util.now",
            lambda: restored_at,
        )
        await restarted.async_load_demand_history()
        assert restarted.raw_house_sampler.known_energy_kwh == pytest.approx(4)
        assert restarted.demand_sampler.missing_seconds == pytest.approx(3600)
        assert restarted.raw_house_sampler._last_at == start + timedelta(hours=4)
        assert restarted.demand_sampler._last_at == start + timedelta(hours=4)
        assert [s.energy_kwh for s in restarted.demand_history.samples] == [17]
        await restarted._async_sample_house_load()
        assert restarted.raw_house_sampler.known_energy_kwh == pytest.approx(4 + 4 / 60)
        assert restarted.demand_sampler.missing_seconds == pytest.approx(3660)
        assert [s.energy_kwh for s in restarted.demand_history.samples] == [17]
    finally:
        coordinator.shutdown()
        if restarted is not None:
            restarted.shutdown()


@pytest.mark.parametrize("corrupt_binding", [[], True, ["house-learning-v2", None]])
async def test_corrupt_present_binding_preserves_history_but_rejects_progress(
    hass, monkeypatch, corrupt_binding,
):
    coordinator = _collector(hass, monkeypatch)
    now = datetime(2026, 11, 17, 16, tzinfo=UTC)
    payload = {
        "samples": [{"observed_at": (now - timedelta(days=1)).isoformat(), "energy_kwh": 17}],
        "in_progress_cycle": {
            "last_at": (now - timedelta(minutes=1)).isoformat(),
            "last_power_kw": 4,
            "cycle_started": True,
            "cycle_energy_kwh": 4,
        },
        "raw_house_in_progress_cycle": {
            "last_at": (now - timedelta(minutes=1)).isoformat(),
            "last_power_kw": 5,
            "cycle_started": True,
            "cycle_energy_kwh": 5,
        },
        "source_binding": corrupt_binding,
    }
    state = DemandPersistenceState.restore(payload, now)
    coordinator._demand_repository = SimpleNamespace(async_load=AsyncMock(return_value=state))
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.coordinator.dt_util.now", lambda: now,
    )
    try:
        await coordinator.async_load_demand_history()
        assert [s.energy_kwh for s in coordinator.demand_history.samples] == [17]
        assert coordinator.raw_house_sampler.known_energy_kwh == 0
        assert coordinator.demand_sampler.known_energy_kwh == 0
    finally:
        coordinator.shutdown()


async def test_registry_identity_change_resets_only_progress(hass, monkeypatch):
    coordinator = _collector(hass, monkeypatch)
    registry = er.async_get(hass)
    row = registry.async_get_or_create(
        "sensor", "test_meter", "meter-one", suggested_object_id="test_house_load"
    )
    assert row.entity_id == "sensor.test_house_load"
    start = datetime(2026, 11, 17, 12, tzinfo=UTC)
    coordinator.demand_history.add(start - timedelta(days=1), 17)
    try:
        for minute in range(0, 4 * 60 + 1, 5):
            await _observe(coordinator, monkeypatch, start + timedelta(minutes=minute))
        before = coordinator._learning_source_binding()
        registry.async_update_entity(row.entity_id, new_unique_id="meter-two")
        assert coordinator._learning_source_binding() != before
        await _observe(coordinator, monkeypatch, start + timedelta(hours=4, minutes=5))
        assert coordinator.demand_sampler.known_energy_kwh == 0
        assert coordinator.raw_house_sampler.known_energy_kwh == 0
        assert [s.energy_kwh for s in coordinator.demand_history.samples] == [17]
    finally:
        coordinator.shutdown()


async def test_native_learning_entities_expose_collection_without_extra_controls(hass):
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.test_house_load", "4", {"unit_of_measurement": "kW"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Learning collection",
        data={**ENTRY_DATA, "house_load_includes_ev": True},
        version=6,
    )
    entry.add_to_hass(hass)
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    try:
        for key in ["learning_status", "learning_samples"]:
            state = hass.states.get(_entity_id(hass, entry, key))
            assert state.attributes["reason"] == "subtraction_unavailable"
            assert "known_energy_kwh" in state.attributes["raw_house"]
            assert "missing_seconds" in state.attributes["base_house"]
            assert "source_binding" not in state.attributes
        assert calls == []
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_legacy_progress_keeps_upgrade_contract_without_inventing_raw_history(
    hass, monkeypatch,
):
    coordinator = _collector(hass, monkeypatch)
    now = datetime(2026, 11, 17, 16, tzinfo=UTC)
    payload = {
        "samples": [{"observed_at": (now - timedelta(days=1)).isoformat(), "energy_kwh": 17}],
        "in_progress_cycle": {
            "last_at": (now - timedelta(minutes=1)).isoformat(),
            "last_power_kw": 4,
            "cycle_started": True,
            "cycle_energy_kwh": 4,
        },
    }
    state = DemandPersistenceState.restore(payload, now)
    coordinator._demand_repository = SimpleNamespace(async_load=AsyncMock(return_value=state))
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.coordinator.dt_util.now", lambda: now,
    )
    try:
        await coordinator.async_load_demand_history()
        assert [s.energy_kwh for s in coordinator.demand_history.samples] == [17]
        assert coordinator.demand_sampler.known_energy_kwh == 4
        assert coordinator.raw_house_sampler.to_payload() is None
        assert coordinator.demand_sampler._last_at == now - timedelta(minutes=1)
    finally:
        coordinator.shutdown()


async def test_new_ha_reports_do_not_extend_original_unplugged_frame_age(hass, freezer):
    rig = _morning(hass, freezer)
    _asleep_unplugged(hass, rig, rig.now - timedelta(hours=2))
    rig.provider.data["state"] = "online"
    coordinator = _house_learner(hass, rig, ev_reservation_soc_max_age_hours=2)
    original_stamp = rig.provider.data["charge_state_timestamp"]
    try:
        assert coordinator._protected_house_learning_power_kw(rig.now) == 6
        expired_at = rig.now + timedelta(seconds=1)
        freezer.move_to(expired_at)
        for entity_id in [
            "binary_sensor.car_cable", "sensor.car_charging",
            "sensor.car_actual_current", "switch.car_charge",
        ]:
            state = hass.states.get(entity_id)
            hass.states.async_set(entity_id, state.state, dict(state.attributes), force_update=True)
        assert coordinator._protected_house_learning_power_kw(expired_at) is None
        assert rig.provider.data["charge_state_timestamp"] == original_stamp
        feedback = capture_ev_feedback(hass, ev_observation_entity_map(coordinator.runtime_config))
        assert not measure_ev_current(hass, feedback, now=expired_at, max_age_seconds=90).valid
    finally:
        coordinator.shutdown()
        await hass.async_block_till_done()
        await coordinator.async_shutdown()


async def test_repeated_ev_gaps_do_not_renew_learning_hold(hass, monkeypatch):
    coordinator = _collector(hass, monkeypatch, house_load_includes_ev=True)
    ev_power = {"value": 0}
    monkeypatch.setattr(coordinator, "_state_qualified_ev_power_kw", lambda _now: ev_power["value"])
    start = datetime(2026, 11, 17, 12, tzinfo=UTC)
    last_qualified = start + timedelta(hours=3)
    try:
        await _observe(coordinator, monkeypatch, start)
        await _observe(coordinator, monkeypatch, last_qualified)
        ev_power["value"] = None
        for seconds in range(30, 15 * 60 + 1, 30):
            await _observe(coordinator, monkeypatch, last_qualified + timedelta(seconds=seconds))
        payload = coordinator.demand_sampler.to_payload()
        assert payload["last_qualified_at"] == last_qualified.isoformat()
        assert payload["last_qualified_power_kw"] == 4
        assert payload["last_at"] == (last_qualified + timedelta(minutes=15)).isoformat()
        assert payload["last_power_kw"] is None
        assert coordinator.demand_sampler.known_energy_kwh == pytest.approx(4 / 6)
        assert coordinator.demand_sampler.missing_seconds == pytest.approx(5 * 60)
        assert coordinator.raw_house_sampler.known_energy_kwh == pytest.approx(1)
        assert coordinator.raw_house_sampler.missing_seconds == 0
        assert coordinator.demand_history.samples == []
    finally:
        coordinator.shutdown()


@pytest.mark.parametrize(("minutes_before_free", "complete"), [(5, True), (10, True), (11, False)])
async def test_ev_gap_at_cycle_finish_uses_protected_hold_boundary(
    hass, monkeypatch, minutes_before_free, complete,
):
    coordinator = _collector(hass, monkeypatch, house_load_includes_ev=True)
    ev_power = {"value": 0}
    monkeypatch.setattr(coordinator, "_state_qualified_ev_power_kw", lambda _now: ev_power["value"])
    start = datetime(2026, 11, 17, 12, tzinfo=UTC)
    finish = start + timedelta(days=1)
    last_qualified = finish - timedelta(minutes=minutes_before_free)
    try:
        at = start
        while at < last_qualified:
            await _observe(coordinator, monkeypatch, at)
            at += timedelta(minutes=5)
        await _observe(coordinator, monkeypatch, last_qualified)
        ev_power["value"] = None
        for minute in range(1, minutes_before_free + 1):
            await _observe(coordinator, monkeypatch, last_qualified + timedelta(minutes=minute))
        closed = coordinator.demand_sampler.last_cycle
        assert closed["complete"] is complete
        missing_seconds = max(minutes_before_free - 10, 0) * 60
        assert closed["missing_seconds"] == pytest.approx(missing_seconds)
        assert closed["energy_kwh"] == pytest.approx(4 * (21 - missing_seconds / 3600))
        assert coordinator.raw_house_sampler.last_cycle["complete"] is True
        assert len(coordinator.demand_history.samples) == int(complete)
        if complete:
            assert coordinator.demand_history.samples[0].energy_kwh == pytest.approx(84)
    finally:
        coordinator.shutdown()


async def test_restart_cannot_extend_a_partly_used_learning_hold(hass, monkeypatch):
    coordinator = _collector(hass, monkeypatch, house_load_includes_ev=True)
    ev_power = {"value": 0}
    monkeypatch.setattr(coordinator, "_state_qualified_ev_power_kw", lambda _now: ev_power["value"])
    start = datetime(2026, 11, 17, 12, tzinfo=UTC)
    last_qualified = start + timedelta(hours=3)
    restarted = None
    try:
        await _observe(coordinator, monkeypatch, start)
        await _observe(coordinator, monkeypatch, last_qualified)
        ev_power["value"] = None
        await _observe(coordinator, monkeypatch, last_qualified + timedelta(minutes=5))
        repository = SimpleNamespace(async_save=AsyncMock())
        coordinator._demand_repository = repository
        await EnergyCoordinator._async_save_demand_state(coordinator)
        saved = repository.async_save.call_args.args[0].to_payload()
        assert saved["in_progress_cycle"]["last_qualified_at"] == last_qualified.isoformat()
        restarted_at = last_qualified + timedelta(minutes=6)
        state = DemandPersistenceState.restore(saved, restarted_at)
        restarted = _collector(hass, monkeypatch, house_load_includes_ev=True)
        monkeypatch.setattr(restarted, "_state_qualified_ev_power_kw", lambda _now: None)
        restarted._demand_repository = SimpleNamespace(async_load=AsyncMock(return_value=state))
        monkeypatch.setattr(
            "custom_components.home_energy_orchestrator.coordinator.dt_util.now",
            lambda: restarted_at,
        )
        await restarted.async_load_demand_history()
        restored = restarted.demand_sampler.to_payload()
        assert restored["last_qualified_at"] == last_qualified.isoformat()
        assert restored["last_at"] == (last_qualified + timedelta(minutes=5)).isoformat()
        await _observe(restarted, monkeypatch, last_qualified + timedelta(minutes=10))
        assert restarted.demand_sampler.known_energy_kwh == pytest.approx(4 / 6)
        assert restarted.demand_sampler.missing_seconds == 0
        await _observe(restarted, monkeypatch, last_qualified + timedelta(minutes=11))
        assert restarted.demand_sampler.known_energy_kwh == pytest.approx(4 / 6)
        assert restarted.demand_sampler.missing_seconds == pytest.approx(60)
        assert (
            restarted.demand_sampler.to_payload()["last_qualified_at"]
            == last_qualified.isoformat()
        )
    finally:
        coordinator.shutdown()
        if restarted is not None:
            restarted.shutdown()
