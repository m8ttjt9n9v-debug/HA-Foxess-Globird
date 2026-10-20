"""Synthetic real-HA lifecycle traces for combined pre-free EV policy.

Only provider states and ordinary configuration are supplied. The real entry,
canonical telemetry, energy ledger, protected export plan, EV planner, adapter,
storage and public projections run together. Services are recorded, not sent to
devices. No planner output or energy-ledger result is replaced.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import floor

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.const import DOMAIN
from tests.helpers.lifecycle import LifecycleHarness
from tests.test_lifecycle_harness import (
    _ev_entry_data,
    _register_ev_services,
    _seed_ev_states,
    _seed_foxess_states,
)


def _at(hour=11, minute=0, second=0):
    return datetime(2026, 9, 17, hour, minute, second, tzinfo=UTC)


async def _site(hass, monkeypatch, *, away=False):
    # Give all policy clocks one synthetic UTC site; freeze_time still advances
    # native HA timestamps and the underlying physical clock together.
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.coordinator.dt_util.now",
        lambda: datetime.now(UTC),
    )
    harness = LifecycleHarness(hass)
    _register_ev_services(harness, monkeypatch)
    await _seed_foxess_states(harness, 25)
    await _seed_ev_states(
        harness,
        soc=44,
        actual_current=0,
        requested_current=16,
        stored_energy=30.8,
        house_load=0.5,
        site_current=0,
    )
    await harness.set_state("sensor.test_battery_power", 2.5, {"unit_of_measurement": "kW"})
    await harness.set_state("sensor.test_solar", 3, {"unit_of_measurement": "kW"})
    if away:
        await harness.set_state("device_tracker.test_ev", "not_home")
        await harness.set_state("binary_sensor.test_ev_cable", "off")
        await harness.set_state("sensor.test_ev_charging", "disconnected")
        await harness.set_state("switch.test_ev_charge", "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic three-phase morning",
        version=6,
        data=_ev_entry_data(
            automatic_control_enabled=True,
            foxess_control_owner="local_modbus",
            automatic_charge_enabled=False,
            automatic_export_enabled=False,
            battery_capacity_kwh=40,
            battery_floor_percent=17,
            reserve_kwh=0,
            battery_power_entity="sensor.test_battery_power",
            solar_configured=True,
            solar_power_entity="sensor.test_solar",
            house_load_includes_ev=False,
            house_learning_fallback_kwh=12,
            ev_pre_free_backfill_enabled=True,
            ev_pre_free_backfill_timing="ready_by",
            ev_daily_ready_time="08:00:00",
            ev_daily_backfill_energy_kwh=0,
            ev_morning_solar_enabled=True,
            ev_morning_solar_reserve_soc_percent=17,
            ev_outside_battery_reserve_percent=17,
            ev_outside_inverter_percent=50,
            inverter_discharge_limit_kw=15,
            ev_allowance_guard_enabled=False,
            free_charge_window_start="12:01:00",
            free_charge_window_end="15:01:00",
        ),
    )
    entry.add_to_hass(hass)
    await harness.setup(entry)
    return harness, entry


async def _inputs(
    harness,
    at,
    *,
    solar=3,
    current=0,
    connected=True,
    stale_house=False,
    battery_soc=25,
):
    """Publish one coherent provider report, without replacing planner output.

    Batch its state events before draining listeners so a deliberate two-minute
    test clock jump is not itself a sequential partial-source outage. Separate
    outage tests below deliberately age the house source within this report.
    """
    watts = {"unit_of_measurement": "kW"}
    reports = [
        ("sensor.test_battery_soc", battery_soc, {"unit_of_measurement": "%"}, at),
        ("sensor.test_grid_power", 0, watts, at),
        ("sensor.test_solar", solar, watts, at),
        ("sensor.test_house_load", 0.5, watts, at - timedelta(minutes=5) if stale_house else at),
        ("sensor.test_battery_power", solar - 0.5 - current * 0.69, watts, at),
        ("sensor.test_site_current", 0, {"unit_of_measurement": "A"}, at),
        ("device_tracker.test_ev", "home" if connected else "not_home", {}, at),
        ("binary_sensor.test_ev_cable", "on" if connected else "off", {}, at),
        ("sensor.test_ev_charging", "charging" if connected else "disconnected", {}, at),
        ("sensor.test_ev_actual_current", current, {"unit_of_measurement": "A"}, at),
        ("switch.test_ev_charge", "on" if connected else "off", {}, at),
    ]
    for entity, state, attributes, observed_at in reports:
        harness.hass.states.async_set(
            entity, str(state), attributes, timestamp=observed_at.timestamp()
        )
    await harness.hass.async_block_till_done()


async def _cycle(harness, entry, at):
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    await coordinator.active_controller.async_reconcile()
    await coordinator.ev_controller.async_reconcile(at)
    coordinator.async_update_listeners()
    await harness.hass.async_block_till_done()
    status, target = harness.states(
        ["sensor.home_energy_ev_control_status", "sensor.home_energy_ev_current_target"]
    )
    return status, None if target.state == "unknown" else float(target.state)


async def _close(harness, entry):
    await harness.unload(entry)
    for domain, service in (("number", "set_value"), ("switch", "turn_on"), ("switch", "turn_off")):
        harness.hass.services.async_remove(domain, service)
    harness.close()


@pytest.mark.freeze_time("2026-09-17 10:59:00+00:00")
async def test_arrival_cloud_house_budget_loss_and_independent_free_takeover(
    hass, monkeypatch, freezer
):
    """Public policy cannot preserve retained 16A or a revoked battery hold."""
    harness, entry = await _site(hass, monkeypatch, away=True)
    assert harness.service_calls == ()

    freezer.move_to(_at())
    await _inputs(harness, _at())
    status, target = await _cycle(harness, entry, _at())
    assert status.attributes["decision_phase"] == "pre_free_combined", {
        "public": status.attributes,
        "foxess": entry.runtime_data.active_controller.last_reason,
        "plan": entry.runtime_data.active_controller.export_plan,
        "protected": entry.runtime_data.learning_remaining_kwh,
        "ledger": entry.runtime_data.data,
    }
    assert floor(2.5 / 0.69) < target <= 10 < 16
    assert any(
        call.service_data.get("entity_id") == "number.test_ev_current"
        and call.service_data.get("value") == target
        for call in harness.service_calls
    )

    freezer.move_to(_at(11, 2))
    await _inputs(harness, _at(11, 2), solar=0.5, current=target)
    cloudy, cloud_target = await _cycle(harness, entry, _at(11, 2))
    assert cloudy.attributes["decision_phase"] == "pre_free_combined"
    assert 0 < cloud_target <= 10

    # Seed valid completed history via the coordinator's normal learner API.
    # The revised house model now protects more energy than the battery holds;
    # no planner result or export budget is monkeypatched to manufacture that.
    for days_ago in range(1, 8):
        await entry.runtime_data.async_record_demand_cycle(100, _at() - timedelta(days=days_ago))
    freezer.move_to(_at(11, 3))
    await _inputs(harness, _at(11, 3), current=cloud_target)
    lost, safe_target = await _cycle(harness, entry, _at(11, 3))
    assert not lost.attributes["pre_free_session_active"]
    assert safe_target <= floor(2.5 / 0.69)

    freezer.move_to(_at(12, 1))
    await _inputs(harness, _at(12, 1), current=safe_target)
    free, free_target = await _cycle(harness, entry, _at(12, 1))
    assert free_target == 16
    assert not free.attributes["pre_free_session_active"]
    assert free.attributes["decision_phase"] != "pre_free_combined"
    await _close(harness, entry)


@pytest.mark.freeze_time("2026-09-17 11:00:00+00:00")
async def test_unplug_replug_then_real_reload_preserves_combined_journal(
    hass, monkeypatch, freezer
):
    harness, entry = await _site(hass, monkeypatch)
    await _inputs(harness, _at())
    first, target = await _cycle(harness, entry, _at())
    assert first.attributes["decision_phase"] == "pre_free_combined"

    freezer.move_to(_at(11, 1))
    await _inputs(harness, _at(11, 1), connected=False)
    absent, absent_target = await _cycle(harness, entry, _at(11, 1))
    assert not absent.attributes["pre_free_session_active"]
    assert absent_target is None
    assert absent.attributes["reconciliation_phase"] == "idle"
    harness.clear_service_calls()
    await _cycle(harness, entry, _at(11, 1))
    assert harness.service_calls == ()

    freezer.move_to(_at(11, 2))
    await _inputs(harness, _at(11, 2), current=0)
    replug, target = await _cycle(harness, entry, _at(11, 2))
    assert replug.attributes["decision_phase"] == "pre_free_combined"
    before = entry.runtime_data.ev_controller.measured_solar_adjustment
    assert before.phase == "morning_solar"
    assert before.battery_current_a is not None
    await _inputs(harness, _at(11, 2), current=target)
    await _cycle(harness, entry, _at(11, 2))
    before = entry.runtime_data.ev_controller.measured_solar_adjustment
    await harness.reload(entry)
    restored, restored_target = await _cycle(harness, entry, _at(11, 2))
    after = entry.runtime_data.ev_controller.measured_solar_adjustment
    assert restored.attributes["decision_phase"] == "pre_free_combined"
    assert restored_target == target
    assert after.phase == "morning_solar"
    assert after.changed_at == before.changed_at
    assert after.battery_current_a == pytest.approx(before.battery_current_a)
    assert after.target_current_a == before.target_current_a
    await _close(harness, entry)


@pytest.mark.freeze_time("2026-09-17 11:57:00+00:00")
@pytest.mark.parametrize("loss", ["protected_budget", "stale_house"])
async def test_joint_authority_loss_cannot_fall_back_on_later_cycles(
    hass, monkeypatch, freezer, loss
):
    harness, entry = await _site(hass, monkeypatch)
    await _inputs(harness, _at(11, 57))
    first, target = await _cycle(harness, entry, _at(11, 57))
    assert first.attributes["decision_phase"] == "pre_free_combined"
    assert target == 10

    for second in (0, 30):
        at = _at(11, 58, second)
        freezer.move_to(at)
        await _inputs(
            harness,
            at,
            solar=0.5,
            current=target,
            stale_house=loss == "stale_house",
            # Still ABOVE the configured 17% hard cutoff. The genuine ledger
            # leaves no discretionary energy after protecting house demand.
            battery_soc=17.01 if loss == "protected_budget" else 25,
        )
        blocked, reduced = await _cycle(harness, entry, at)
        assert not blocked.attributes["pre_free_session_active"], {
            "public": blocked.attributes,
            "ledger": entry.runtime_data.data,
            "plan": entry.runtime_data.active_controller.export_plan,
            "dailyhold": entry.runtime_data.ev_controller.daily_backfill_hold_reason,
        }
        assert blocked.attributes["decision_phase"] != "pre_free_combined"
        assert reduced == 0

    freezer.move_to(_at(11, 59))
    await _inputs(harness, _at(11, 59))
    recovered, recovered_target = await _cycle(harness, entry, _at(11, 59))
    assert recovered.attributes["decision_phase"] == "pre_free_combined"
    assert recovered_target == 10
    await _close(harness, entry)
