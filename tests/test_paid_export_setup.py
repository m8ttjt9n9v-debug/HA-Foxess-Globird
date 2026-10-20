"""Native counter wiring, upgrade, durable failure and unchanged old meters."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_energy_orchestrator.const import DOMAIN
from custom_components.home_energy_orchestrator.coordinator import EnergyCoordinator
from custom_components.home_energy_orchestrator.planner.export_session import ExportSessionState
from tests.test_setup import ENTRY_DATA, _entity_id

NOW = datetime(2026, 10, 20, 12, tzinfo=ZoneInfo("Australia/Sydney"))


async def _coordinator(hass, monkeypatch, *, legacy=None, paid=None, **settings):
    monkeypatch.setattr(
        "custom_components.home_energy_orchestrator.coordinator.dt_util.now", lambda: NOW
    )
    coordinator = EnergyCoordinator(hass, {**ENTRY_DATA, **settings}, "paid-cap-test")
    coordinator._daily_export_store.async_load = AsyncMock(return_value=legacy)
    coordinator._paid_export_store.async_load = AsyncMock(return_value=paid)
    coordinator._paid_export_store.async_save = AsyncMock()
    await coordinator.async_load_daily_import()
    return coordinator


def _legacy(total=13.0):
    return {
        "date": NOW.date().isoformat(), "imported_kwh": total,
        "last_at": NOW.isoformat(), "last_import_kw": 0.0,
    }


async def test_upgrade_seeds_once_and_saves_before_allowance_is_ready(hass, monkeypatch):
    coordinator = await _coordinator(hass, monkeypatch, legacy=_legacy())
    assert coordinator._paid_export_storage_ready
    assert coordinator.paid_export.imported_kwh == 13.0
    assert coordinator.paid_export.legacy_seeded
    coordinator._paid_export_store.async_save.assert_awaited_once()
    saved = coordinator._paid_export_store.async_save.await_args.args[0]
    assert saved["imported_kwh"] == 13.0
    coordinator._paid_export_store.async_load.return_value = saved
    coordinator._daily_export_store.async_load.return_value = _legacy(22)
    await coordinator.async_load_daily_import()
    assert coordinator.paid_export.imported_kwh == 13.0
    assert coordinator.daily_export.imported_kwh == 22.0


@pytest.mark.parametrize("paid", [False, {}, {"date": NOW.date().isoformat()}])
async def test_corrupt_paid_store_never_gets_a_fresh_legacy_allowance(hass, monkeypatch, paid):
    coordinator = await _coordinator(hass, monkeypatch, legacy=_legacy(8), paid=paid)
    assert not coordinator._paid_export_storage_ready
    assert not coordinator.paid_export.needs_legacy_seed


@pytest.mark.parametrize("legacy", [{}, False, {"date": NOW.date().isoformat()}])
async def test_unidentifiable_legacy_history_blocks_upgrade_day(hass, monkeypatch, legacy):
    coordinator = await _coordinator(hass, monkeypatch, legacy=legacy)
    assert not coordinator._paid_export_storage_ready


async def test_midnight_clears_only_paid_day_and_unpaid_solar_does_not_consume_it(
    hass, monkeypatch,
):
    coordinator = await _coordinator(hass, monkeypatch, legacy=_legacy(13))
    tomorrow = NOW + timedelta(days=1)
    await coordinator._async_advance_paid_export(6, tomorrow)
    await coordinator._async_advance_paid_export(6, tomorrow + timedelta(minutes=10))
    assert coordinator.paid_export.imported_kwh == 0
    assert not coordinator.paid_export.legacy_seeded
    assert coordinator.daily_export.imported_kwh == 13
    saved = coordinator._paid_export_store.async_save.await_args.args[0]
    assert saved["date"] == tomorrow.date().isoformat()
    assert saved["imported_kwh"] == 0


async def test_price_owned_export_consumes_paid_cap_once_and_stops_at_permission_end(
    hass, monkeypatch,
):
    coordinator = await _coordinator(hass, monkeypatch)
    coordinator.active_controller = SimpleNamespace(export_session=ExportSessionState(
        phase="active", requested_power_kw=6, last_command_at=NOW,
        authority_source="price", price_deadline=NOW + timedelta(minutes=5),
        price_permission_end=NOW + timedelta(minutes=5),
    ))
    await coordinator._async_advance_paid_export(6, NOW)
    await coordinator._async_advance_paid_export(6, NOW + timedelta(minutes=5))
    assert coordinator.paid_export.imported_kwh == pytest.approx(0.5)
    await coordinator._async_advance_paid_export(6, NOW + timedelta(minutes=10))
    assert coordinator.paid_export.imported_kwh == pytest.approx(0.5)


async def test_bonus_meter_is_read_before_its_current_interval_is_debited(hass, monkeypatch):
    coordinator = await _coordinator(hass, monkeypatch)
    now = NOW.replace(hour=18)
    coordinator.zerohero_export.local_date = now.date()
    coordinator.zerohero_export.imported_kwh = 14.8
    await coordinator._async_advance_paid_export(6, now)
    await coordinator._async_advance_paid_export(6, now + timedelta(minutes=5))
    assert coordinator.paid_export.imported_kwh == pytest.approx(0.2)
    assert coordinator.zerohero_export.imported_kwh == 14.8


async def test_counter_checkpoint_failure_closes_cap_even_if_old_ledger_survives(hass, monkeypatch):
    coordinator = await _coordinator(hass, monkeypatch, export_rate_per_kwh=0.02)
    now = NOW.replace(hour=18)
    await coordinator._async_advance_paid_export(6, now)
    coordinator._paid_export_store.async_save.side_effect = OSError("storage failed")
    with pytest.raises(OSError, match="storage failed"):
        await coordinator._async_advance_paid_export(6, now + timedelta(minutes=5))
    assert not coordinator._paid_export_storage_ready


async def test_failed_subthreshold_stop_checkpoint_is_retried_before_cap_reopens(hass, monkeypatch):
    coordinator = await _coordinator(hass, monkeypatch, export_rate_per_kwh=0.02)
    now = NOW.replace(hour=18)
    await coordinator._async_advance_paid_export(1, now)
    coordinator._paid_export_store.async_save.side_effect = OSError("storage failed")
    with pytest.raises(OSError):
        await coordinator._async_advance_paid_export(0, now + timedelta(seconds=1))
    assert coordinator.paid_export.imported_kwh < 0.01
    assert coordinator._paid_export_last_saved is None
    assert not coordinator._paid_export_storage_ready
    await coordinator._async_advance_paid_export(0, now + timedelta(seconds=1))
    assert not coordinator._paid_export_storage_ready
    with pytest.raises(OSError):
        await coordinator._async_advance_paid_export(0, now + timedelta(seconds=2))
    assert not coordinator._paid_export_storage_ready
    coordinator._paid_export_store.async_save.side_effect = None
    await coordinator._async_advance_paid_export(0, now + timedelta(seconds=3))
    assert coordinator._paid_export_storage_ready
    assert coordinator._paid_export_store.async_save.await_args.args[0]["last_import_kw"] == 0


async def test_expired_price_cleanup_command_does_not_poison_regular_paid_meter(hass, monkeypatch):
    coordinator = await _coordinator(hass, monkeypatch, offpeak_export_rate_per_kwh=0.02)
    await coordinator._async_advance_paid_export(6, NOW)
    coordinator.active_controller = SimpleNamespace(export_session=ExportSessionState(
        phase="stopping", requested_power_kw=6,
        last_command_at=NOW + timedelta(minutes=6), authority_source="price",
        price_deadline=NOW + timedelta(minutes=5),
    ))
    await coordinator._async_advance_paid_export(6, NOW + timedelta(minutes=6))
    assert coordinator.paid_export.valid
    assert coordinator.paid_export.imported_kwh == pytest.approx(0.6)


async def test_native_setup_reload_keeps_total_meter_and_paid_cap_separate(hass, freezer):
    freezer.move_to(NOW)
    hass.states.async_set("sensor.test_battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.test_grid_power", "0", {"unit_of_measurement": "kW"})
    entry = MockConfigEntry(domain=DOMAIN, title="Paid-cap setup", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    original = entry.runtime_data
    original.paid_export.imported_kwh = 4
    await original._paid_export_repository.async_save(original.paid_export)
    original.daily_export.imported_kwh = 24
    await original._daily_export_repository.async_save(original.daily_export)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert coordinator is not original
    assert coordinator.data.paid_export_kwh == 4
    assert coordinator.data.daily_export_kwh == 24
    state = hass.states.get(_entity_id(hass, entry, "daily_export"))
    assert state.state == "24.0"
    assert state.attributes["paid_export_kwh"] == 4
    assert state.attributes["automatic_export_cap_basis"] == "paid_export"
    assert coordinator.paid_export.legacy_seeded
