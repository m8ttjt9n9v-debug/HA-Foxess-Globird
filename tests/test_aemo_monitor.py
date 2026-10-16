"""Read-only AEMO extension: interval evidence, events and restart behavior."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from aiohttp import ClientConnectionError
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.home_energy_orchestrator.aemo_monitor import (
    AEMO_DATA_SOURCE,
    AEMO_HISTORY_LIMIT,
    AEMO_REQUEST_TIMEOUT,
    AEMO_SUMMARY_SOURCE,
    EVENT_MARKET_OPPORTUNITY,
    AemoMarketMonitor,
    parse_aemo_summary,
)
from custom_components.home_energy_orchestrator.configuration import AemoMonitorConfiguration

from .test_aemo_dispatch_feed import dispatch_report

NOW = datetime(2026, 10, 10, 22, 2, tzinfo=UTC)
INTERVAL_END = datetime(2026, 10, 10, 22, 5, tzinfo=UTC)
CONFIGURATION = AemoMonitorConfiguration(True, "NSW1", 3.0, None)


def _collect_events(events):
    """Collect native callbacks in event-loop order, not executor thread order."""

    @callback
    def collect(event):
        events.append(event)

    return collect


def summary(price: object = 3001, **overrides: object) -> dict[str, object]:
    return {
        "ELEC_NEM_SUMMARY": [
            {
                "REGIONID": "NSW1",
                "PRICE": price,
                "SETTLEMENTDATE": "2026-10-11T08:05:00",
                "PRICE_STATUS": "FIRM",
                "APCFLAG": 0.0,
                "MARKETSUSPENDEDFLAG": 0.0,
                **overrides,
            }
        ]
    }


@pytest.mark.parametrize(
    ("price", "status", "price_per_kwh"),
    [
        (2999.99, "watching", 2.99999),
        (3000, "possible_export_event", 3.0),
        (3000.01, "possible_export_event", 3.00001),
        (-1000, "watching", -1.0),
        (0, "watching", 0.0),
    ],
)
def test_units_inclusive_export_threshold_and_no_inferred_import(price, status, price_per_kwh):
    result = parse_aemo_summary(summary(price), CONFIGURATION, NOW)
    assert result.status == status
    assert result.price_per_mwh == price
    assert result.price_per_kwh == pytest.approx(price_per_kwh)
    assert result.declared_event_confirmed is False
    assert result.payment_confirmed is False
    assert result.control_authority is False
    assert result.data_source == AEMO_SUMMARY_SOURCE


@pytest.mark.parametrize(("price", "status"), [(-201, "possible_import_event"), (-200, "watching")])
def test_import_candidate_requires_explicit_threshold_and_strict_comparison(price, status):
    configuration = AemoMonitorConfiguration(True, "NSW1", 3.0, -0.2)
    assert parse_aemo_summary(summary(price), configuration, NOW).status == status


def test_nem_interval_end_uses_fixed_aest_even_during_site_dst():
    result = parse_aemo_summary(summary(), CONFIGURATION, NOW)
    assert result.interval_start == datetime(2026, 10, 10, 22, 0, tzinfo=UTC)
    assert result.interval_end == INTERVAL_END
    assert result.interval_end.astimezone(ZoneInfo("Australia/Sydney")).hour == 9
    assert result.first_seen_at == NOW
    assert result.latency_seconds == 120
    assert result.attributes()["latency_basis"] == "first_observation_after_interval_start"


@pytest.mark.parametrize(
    ("now", "status"),
    [
        (NOW - timedelta(minutes=3), "future"),
        (NOW - timedelta(minutes=2), "possible_export_event"),
        (INTERVAL_END - timedelta(microseconds=1), "possible_export_event"),
        (INTERVAL_END, "stale"),
        (INTERVAL_END + timedelta(hours=1), "stale"),
    ],
)
def test_only_exact_current_interval_is_eligible(now, status):
    result = parse_aemo_summary(summary(), CONFIGURATION, now)
    assert result.status == status
    if status in {"future", "stale"}:
        assert result.price_per_kwh is None
        assert result.price_per_mwh is None


@pytest.mark.parametrize("price", [None, True, False, "3001", float("nan"), float("inf")])
def test_invalid_prices_are_unavailable_not_zero(price):
    result = parse_aemo_summary(summary(price), CONFIGURATION, NOW)
    assert result.status == "invalid_price"
    assert result.price_per_kwh is None


@pytest.mark.parametrize(
    "timestamp",
    [
        None,
        "bad-date",
        "2026-10-11T08:04:00",
        "2026-10-11T08:05:01",
        "2026-10-11T08:05:00.001",
        "2026-10-11T08:05:00+10:00",
    ],
)
def test_interval_end_requires_naive_five_minute_alignment(timestamp):
    result = parse_aemo_summary(summary(SETTLEMENTDATE=timestamp), CONFIGURATION, NOW)
    assert result.status == "invalid_interval"
    assert result.price_per_kwh is None


@pytest.mark.parametrize("price_status", [None, "", "PRELIM", "firm", True])
def test_unknown_price_status_suppresses_candidate(price_status):
    result = parse_aemo_summary(summary(PRICE_STATUS=price_status), CONFIGURATION, NOW)
    assert result.status == "unknown_price_status"
    assert result.price_per_kwh is None


@pytest.mark.parametrize("flag_name", ["APCFLAG", "MARKETSUSPENDEDFLAG"])
@pytest.mark.parametrize("value", [None, True, False, "0", 2, -1, float("nan"), float("inf")])
def test_flags_require_explicit_finite_numeric_zero_or_one(flag_name, value):
    result = parse_aemo_summary(summary(**{flag_name: value}), CONFIGURATION, NOW)
    assert result.status == "invalid_market_flags"
    assert result.price_per_kwh is None


@pytest.mark.parametrize(
    ("overrides", "status"),
    [({"APCFLAG": 1}, "administered_pricing"), ({"MARKETSUSPENDEDFLAG": 1}, "market_suspended")],
)
def test_known_market_intervention_is_visible_and_cannot_be_a_candidate(overrides, status):
    result = parse_aemo_summary(summary(**overrides), CONFIGURATION, NOW)
    assert result.status == status
    assert result.is_candidate is False


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        (None, "invalid_payload"),
        ({}, "invalid_payload"),
        ({"ELEC_NEM_SUMMARY": None}, "invalid_payload"),
        ({"ELEC_NEM_SUMMARY": [None]}, "invalid_payload"),
        (summary(REGIONID="QLD1"), "missing_region"),
        ({"ELEC_NEM_SUMMARY": []}, "missing_region"),
    ],
)
def test_missing_payload_or_configured_region_remains_explicit(payload, status):
    result = parse_aemo_summary(payload, CONFIGURATION, NOW)
    assert result.status == status
    assert result.price_per_kwh is None


def test_duplicate_configured_region_fails_closed():
    payload = summary()
    payload["ELEC_NEM_SUMMARY"] *= 2
    result = parse_aemo_summary(payload, CONFIGURATION, NOW)
    assert result.status == "duplicate_region"
    assert result.price_per_kwh is None


@pytest.mark.parametrize("missing", ["PRICE", "PRICE_STATUS", "APCFLAG", "MARKETSUSPENDEDFLAG"])
def test_missing_required_field_never_manufactures_a_normal_price(missing):
    payload = summary()
    del payload["ELEC_NEM_SUMMARY"][0][missing]
    assert parse_aemo_summary(payload, CONFIGURATION, NOW).price_per_kwh is None


async def test_off_and_unconfigured_monitor_perform_no_http_and_no_device_writes(hass):
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, _collect_events(calls))
    for configuration in [
        AemoMonitorConfiguration(False, "NSW1", 3, None),
        AemoMonitorConfiguration(True, None, 3, None),
    ]:
        monitor = AemoMarketMonitor(hass, "off-monitor", configuration)
        with patch(
            "custom_components.home_energy_orchestrator.aemo_monitor.async_get_clientsession"
        ) as session:
            await monitor.async_restore_history()
            await monitor.async_start()
            session.assert_not_called()
            assert monitor.current_result.status in {"disabled", "unconfigured"}
            assert monitor.update_interval is None
            await monitor.async_stop()
    await hass.async_block_till_done()
    assert calls == []


async def test_http_get_is_shared_bounded_and_checks_status(hass, freezer, aioclient_mock):
    freezer.move_to(NOW)
    report = dispatch_report(now=NOW, price=5000)
    aioclient_mock.get(AEMO_DATA_SOURCE, text=report.source_url)
    aioclient_mock.get(report.source_url, content=report.body)
    native_session = async_get_clientsession(hass)
    session = MagicMock()
    session.get.side_effect = native_session.get
    monitor = AemoMarketMonitor(hass, "http-monitor", CONFIGURATION)
    with patch(
        "custom_components.home_energy_orchestrator.aemo_monitor.async_get_clientsession",
        return_value=session,
    ) as shared_session:
        await monitor.async_refresh()
    shared_session.assert_called_once_with(hass)
    assert [call.args[0] for call in session.get.call_args_list] == [
        AEMO_DATA_SOURCE,
        report.source_url,
    ]
    assert all(
        call.kwargs["timeout"].total == AEMO_REQUEST_TIMEOUT for call in session.get.call_args_list
    )
    assert monitor.current_result.status == "possible_export_event"
    assert monitor.current_result.price_trigger_valid
    await monitor.async_stop()


async def test_poll_corrections_events_and_first_observation_latency(hass, freezer):
    freezer.move_to(NOW)
    events, writes = [], []
    hass.bus.async_listen(EVENT_MARKET_OPPORTUNITY, _collect_events(events))
    hass.bus.async_listen(EVENT_CALL_SERVICE, _collect_events(writes))
    monitor = AemoMarketMonitor(hass, "event-monitor", CONFIGURATION)
    monitor._async_fetch_summary = AsyncMock(return_value=summary())
    save = AsyncMock(wraps=monitor._repository.store.async_save)
    monitor._repository.store.async_save = save
    await monitor.async_restore_history()
    await monitor.async_start()
    await hass.async_block_till_done()
    assert [event.data["phase"] for event in events] == ["onset"]
    assert len(monitor.recent_observations) == 1
    assert "recent_observations" not in monitor.result_attributes
    assert monitor.result_attributes["recent_observation_count"] == 1
    assert save.await_count == 1
    freezer.move_to(NOW + timedelta(seconds=30))
    await monitor.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 1
    assert save.await_count == 1
    assert monitor.current_result.first_seen_at == NOW
    assert monitor.current_result.successful_fetch_at == NOW + timedelta(seconds=30)
    assert monitor.current_result.latency_seconds == 120
    monitor._async_fetch_summary.return_value = summary(4000)
    await monitor.async_refresh()
    await hass.async_block_till_done()
    assert [event.data["phase"] for event in events] == ["onset", "update"]
    assert save.await_count == 2
    assert monitor.current_result.first_seen_at == NOW
    monitor._async_fetch_summary.return_value = summary(2000)
    await monitor.async_refresh()
    await hass.async_block_till_done()
    assert [event.data["phase"] for event in events] == ["onset", "update", "clear"]
    assert monitor.current_result.status == "watching"
    assert writes == []
    assert all(event.data["control_authority"] is False for event in events)
    await monitor.async_stop()


async def test_feed_failure_clears_current_price_without_failing_setup(hass, freezer):
    freezer.move_to(NOW)
    monitor = AemoMarketMonitor(hass, "outage-monitor", CONFIGURATION)
    monitor._async_fetch_summary = AsyncMock(side_effect=ClientConnectionError())
    await monitor.async_restore_history()
    await monitor.async_start()
    assert monitor.current_result.status == "unavailable"
    assert monitor.last_update_success is True
    assert monitor.current_result.price_per_kwh is None
    monitor._async_fetch_summary.side_effect = None
    monitor._async_fetch_summary.return_value = summary()
    await monitor.async_refresh()
    successful_fetch = monitor.current_result.successful_fetch_at
    monitor._async_fetch_summary.side_effect = TimeoutError()
    await monitor.async_refresh()
    assert monitor.current_result.status == "unavailable"
    assert monitor.current_result.price_per_kwh is None
    assert monitor.current_result.successful_fetch_at == successful_fetch
    assert len(monitor.recent_observations) == 1
    await monitor.async_stop()


async def test_exact_expiry_never_exposes_cached_price_or_waits_for_http(hass, freezer):
    freezer.move_to(NOW)
    events = []
    hass.bus.async_listen(EVENT_MARKET_OPPORTUNITY, _collect_events(events))
    monitor = AemoMarketMonitor(hass, "expiry-monitor", CONFIGURATION)
    monitor._async_fetch_summary = AsyncMock(return_value=summary())
    await monitor.async_refresh()
    await hass.async_block_till_done()
    # Prove the property fails closed before the asynchronous timer is serviced.
    freezer.move_to(INTERVAL_END)
    assert monitor.current_result.status == "stale"
    assert monitor.current_result.price_per_kwh is None
    async_fire_time_changed(hass, INTERVAL_END)
    await hass.async_block_till_done()
    assert [event.data["phase"] for event in events] == ["onset", "clear"]
    assert events[-1].data["status"] == "stale"
    await monitor._async_expire(INTERVAL_END + timedelta(seconds=30))
    await hass.async_block_till_done()
    assert len(events) == 2
    assert monitor._async_fetch_summary.await_count == 1
    await monitor.async_stop()


async def test_reload_restores_history_and_deduplicates_unchanged_candidate(hass, freezer):
    freezer.move_to(NOW)
    events = []
    hass.bus.async_listen(EVENT_MARKET_OPPORTUNITY, _collect_events(events))
    first = AemoMarketMonitor(hass, "restart-monitor", CONFIGURATION)
    first._async_fetch_summary = AsyncMock(return_value=summary())
    await first.async_restore_history()
    await first.async_start()
    await hass.async_block_till_done()
    await first.async_stop()
    freezer.move_to(NOW + timedelta(seconds=30))
    second = AemoMarketMonitor(hass, "restart-monitor", CONFIGURATION)
    second._async_fetch_summary = AsyncMock(return_value=summary())
    await second.async_restore_history()
    await second.async_start()
    await hass.async_block_till_done()
    assert len(events) == 1
    assert second.current_result.first_seen_at == NOW
    assert len(second.recent_observations) == 1
    second._async_fetch_summary.return_value = summary(4000)
    await second.async_refresh()
    await hass.async_block_till_done()
    assert [event.data["phase"] for event in events] == ["onset", "update"]
    await second.async_stop()


async def test_next_interval_same_price_is_new_evidence(hass, freezer):
    freezer.move_to(NOW)
    events = []
    hass.bus.async_listen(EVENT_MARKET_OPPORTUNITY, _collect_events(events))
    monitor = AemoMarketMonitor(hass, "interval-monitor", CONFIGURATION)
    monitor._async_fetch_summary = AsyncMock(return_value=summary())
    await monitor.async_refresh()
    freezer.move_to(INTERVAL_END + timedelta(seconds=10))
    monitor._async_fetch_summary.return_value = summary(SETTLEMENTDATE="2026-10-11T08:10:00")
    await monitor.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 2
    assert events[-1].data["interval_end"] != events[0].data["interval_end"]
    assert monitor.current_result.latency_seconds == 10
    assert len(monitor.recent_observations) == 2
    await monitor.async_stop()


async def test_history_is_bounded_and_repeated_invalid_polls_do_not_write(hass, freezer):
    freezer.move_to(NOW)
    monitor = AemoMarketMonitor(hass, "bounded-monitor", CONFIGURATION)
    monitor._async_fetch_summary = AsyncMock()
    save = AsyncMock(wraps=monitor._repository.store.async_save)
    monitor._repository.store.async_save = save
    for index in range(AEMO_HISTORY_LIMIT + 5):
        monitor._async_fetch_summary.return_value = summary(100 + index)
        await monitor.async_refresh()
    assert len(monitor.recent_observations) == AEMO_HISTORY_LIMIT
    assert save.await_count == AEMO_HISTORY_LIMIT + 5
    monitor._async_fetch_summary.return_value = summary(None)
    for _ in range(3):
        await monitor.async_refresh()
    assert save.await_count == AEMO_HISTORY_LIMIT + 5
    assert monitor.current_result.price_per_kwh is None
    await monitor.async_stop()


async def test_runtime_enable_and_disable_without_reload_or_blocking_http(hass, freezer):
    freezer.move_to(NOW)
    off = AemoMonitorConfiguration(False, "NSW1", 3, None)
    monitor = AemoMarketMonitor(hass, "runtime-toggle", off)
    await monitor.async_start()
    entered, never_ready = asyncio.Event(), asyncio.Event()

    async def slow_feed():
        entered.set()
        await never_ready.wait()
        return summary()

    monitor._async_fetch_summary = AsyncMock(side_effect=slow_feed)
    # A UI transaction must release its lock before waiting for a network read.
    async with monitor.settings_lock:
        await monitor.async_update_configuration(CONFIGURATION)
    await entered.wait()
    assert monitor.current_result.status == "awaiting_data"
    assert monitor.update_interval == timedelta(seconds=30)
    async with monitor.settings_lock:
        await monitor.async_update_configuration(off)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert monitor.current_result.status == "disabled"
    assert monitor.current_result.price_per_kwh is None
    assert monitor.update_interval is None
    assert monitor._configuration_refresh_task is None
    assert monitor._expiry_unsub is None
    assert monitor._keepalive_unsub is None
    later = NOW + timedelta(seconds=31)
    freezer.move_to(later)
    async_fire_time_changed(hass, later)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert monitor._async_fetch_summary.await_count == 1
    await monitor.async_stop()


async def test_runtime_threshold_update_clears_price_then_reads_current_settings(hass, freezer):
    freezer.move_to(NOW)
    events = []
    hass.bus.async_listen(EVENT_MARKET_OPPORTUNITY, _collect_events(events))
    monitor = AemoMarketMonitor(hass, "runtime-threshold", CONFIGURATION)
    monitor._async_fetch_summary = AsyncMock(return_value=summary())
    await monitor.async_start()
    old_history = monitor.recent_observations[0]
    changed = AemoMonitorConfiguration(True, "NSW1", 5, None)
    await monitor.async_update_configuration(changed)
    assert monitor.configuration == changed
    assert monitor.current_result.status == "awaiting_data"
    assert monitor.current_result.price_per_kwh is None
    assert monitor.data.price_per_kwh is None
    await hass.async_block_till_done(wait_background_tasks=True)
    assert monitor.current_result.status == "watching"
    assert monitor.current_result.export_threshold_per_kwh == 5
    assert monitor.recent_observations[0] == old_history
    assert [event.data["phase"] for event in events] == ["onset", "clear"]
    assert len(monitor.recent_observations) == 2
    await monitor.async_stop()


async def test_runtime_region_change_discards_uncancelled_inflight_poll(hass, freezer):
    freezer.move_to(NOW)
    monitor = AemoMarketMonitor(hass, "runtime-region", CONFIGURATION)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def feed():
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
            return summary(9000)
        return summary(100, REGIONID="QLD1")

    monitor._async_fetch_summary = AsyncMock(side_effect=feed)
    original_poll = asyncio.create_task(monitor._async_update_data())
    await entered.wait()
    changed = AemoMonitorConfiguration(True, "QLD1", 3, None)
    await monitor.async_update_configuration(changed)
    assert monitor.current_result.region == "QLD1"
    assert monitor.current_result.price_per_kwh is None
    await hass.async_block_till_done(wait_background_tasks=True)
    assert monitor.current_result.price_per_kwh == 0.1
    release.set()
    await original_poll
    assert monitor.current_result.region == "QLD1"
    assert monitor.current_result.price_per_kwh == 0.1
    assert {record["region"] for record in monitor.recent_observations} == {"QLD1"}
    await monitor.async_stop()


async def test_runtime_off_discards_uncancelled_inflight_poll(hass, freezer):
    freezer.move_to(NOW)
    events = []
    hass.bus.async_listen(EVENT_MARKET_OPPORTUNITY, _collect_events(events))
    monitor = AemoMarketMonitor(hass, "runtime-off-inflight", CONFIGURATION)
    entered, release = asyncio.Event(), asyncio.Event()

    async def feed():
        entered.set()
        await release.wait()
        return summary(9000)

    monitor._async_fetch_summary = AsyncMock(side_effect=feed)
    original_poll = asyncio.create_task(monitor._async_update_data())
    await entered.wait()
    await monitor.async_update_configuration(AemoMonitorConfiguration(False, "NSW1", 3, None))
    release.set()
    await original_poll
    await hass.async_block_till_done(wait_background_tasks=True)
    assert monitor.current_result.status == "disabled"
    assert monitor.current_result.price_per_kwh is None
    assert monitor.recent_observations == []
    assert events == []
    await monitor.async_stop()


async def test_settings_generation_rejects_result_waiting_for_state_lock(hass, freezer):
    freezer.move_to(NOW)
    monitor = AemoMarketMonitor(hass, "runtime-lock-delay", CONFIGURATION)
    generation = monitor._configuration_generation
    old = parse_aemo_summary(summary(), CONFIGURATION, NOW)
    off = AemoMonitorConfiguration(False, "NSW1", 3, None)
    async with monitor._lock:
        update = asyncio.create_task(monitor.async_update_configuration(off))
        await asyncio.sleep(0)
        delayed = asyncio.create_task(
            monitor._async_apply_result(old, configuration_generation=generation)
        )
        await asyncio.sleep(0)
    await update
    assert await delayed is False
    assert monitor.current_result.status == "disabled"
    assert monitor.recent_observations == []
    await monitor.async_stop()


async def test_old_expiry_generation_cannot_clear_reconfigured_same_interval(hass, freezer):
    freezer.move_to(NOW)
    monitor = AemoMarketMonitor(hass, "runtime-old-expiry", CONFIGURATION)
    monitor._async_fetch_summary = AsyncMock(return_value=summary(5000))
    await monitor.async_start()
    old_generation = monitor._configuration_generation
    await monitor.async_update_configuration(AemoMonitorConfiguration(True, "NSW1", 4, None))
    await hass.async_block_till_done(wait_background_tasks=True)
    await monitor._async_expire(INTERVAL_END, INTERVAL_END, old_generation)
    assert monitor.current_result.status == "possible_export_event"
    assert monitor.current_result.export_threshold_per_kwh == 4
    assert monitor._expiry_unsub is not None
    await monitor.async_stop()


async def test_concurrent_runtime_changes_converge_on_latest_configuration(hass, freezer):
    freezer.move_to(NOW)
    monitor = AemoMarketMonitor(hass, "runtime-concurrent", CONFIGURATION)
    monitor._async_fetch_summary = AsyncMock(return_value=summary(100, REGIONID="QLD1"))
    first = AemoMonitorConfiguration(True, "QLD1", 3, None)
    second = AemoMonitorConfiguration(True, "QLD1", 6, -0.5)
    await asyncio.gather(
        monitor.async_update_configuration(first), monitor.async_update_configuration(second)
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert monitor.configuration == second
    assert monitor.current_result.region == "QLD1"
    assert monitor.current_result.export_threshold_per_kwh == 6
    assert monitor.current_result.import_threshold_per_kwh == -0.5
    assert all(record["export_threshold_per_kwh"] == 6 for record in monitor.recent_observations)
    assert monitor._configuration_refresh_task is None
    await monitor.async_stop()


async def test_shutdown_registration_is_once_across_runtime_toggles(hass, freezer):
    freezer.move_to(NOW)
    off = AemoMonitorConfiguration(False, "NSW1", 3, None)
    monitor = AemoMarketMonitor(hass, "runtime-shutdown-registration", off)
    monitor._async_fetch_summary = AsyncMock(return_value=summary())
    register = AsyncMock(wraps=monitor.async_register_shutdown)
    monitor.async_register_shutdown = register
    await monitor.async_start()
    for _ in range(2):
        await monitor.async_update_configuration(CONFIGURATION)
        await hass.async_block_till_done(wait_background_tasks=True)
        await monitor.async_update_configuration(off)
    assert register.await_count == 1
    await monitor.async_stop()
    await monitor.async_update_configuration(CONFIGURATION)
    assert monitor.current_result.status == "disabled"
    assert monitor._configuration_refresh_task is None


async def test_shutdown_cancels_pending_runtime_read(hass, freezer):
    freezer.move_to(NOW)
    off = AemoMonitorConfiguration(False, "NSW1", 3, None)
    monitor = AemoMarketMonitor(hass, "runtime-shutdown-read", off)
    entered, release = asyncio.Event(), asyncio.Event()

    async def feed():
        entered.set()
        await release.wait()
        return summary()

    monitor._async_fetch_summary = AsyncMock(side_effect=feed)
    await monitor.async_update_configuration(CONFIGURATION)
    await entered.wait()
    await monitor.async_stop()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert monitor._configuration_refresh_task is None
    assert monitor._expiry_unsub is None
    assert monitor.recent_observations == []


async def test_runtime_missing_region_cannot_enable_http(hass, freezer):
    freezer.move_to(NOW)
    monitor = AemoMarketMonitor(hass, "runtime-region-required", CONFIGURATION)
    monitor._async_fetch_summary = AsyncMock()
    await monitor.async_update_configuration(AemoMonitorConfiguration(True, None, 3, None))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert monitor.current_result.status == "unconfigured"
    assert monitor.update_interval is None
    monitor._async_fetch_summary.assert_not_called()
    await monitor.async_stop()


async def test_shutdown_during_setting_save_cannot_schedule_new_http_or_timers(hass, freezer):
    freezer.move_to(NOW)
    monitor = AemoMarketMonitor(hass, "runtime-shutdown-save", CONFIGURATION)
    monitor._async_fetch_summary = AsyncMock(return_value=summary())
    await monitor.async_start()
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_save(payload):
        entered.set()
        await release.wait()

    monitor._repository.store.async_save = slow_save
    update = asyncio.create_task(
        monitor.async_update_configuration(AemoMonitorConfiguration(True, "NSW1", 4, None))
    )
    await entered.wait()
    stop = asyncio.create_task(monitor.async_stop())
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(update, stop)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert monitor._configuration_refresh_task is None
    assert monitor._expiry_unsub is None
    assert monitor._unsub_refresh is None
    assert monitor._async_fetch_summary.await_count == 1


async def test_shutdown_finishes_started_runtime_observation_save(hass, freezer):
    freezer.move_to(NOW)
    monitor = AemoMarketMonitor(
        hass, "runtime-finish-save", AemoMonitorConfiguration(False, "NSW1", 3, None)
    )
    monitor._async_fetch_summary = AsyncMock(return_value=summary())
    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def save(payload):
        entered.set()
        await release.wait()
        finished.set()

    monitor._repository.store.async_save = save
    await monitor.async_update_configuration(CONFIGURATION)
    await entered.wait()
    stop = asyncio.create_task(monitor.async_stop())
    await asyncio.sleep(0)
    assert not stop.done()
    release.set()
    await stop
    assert finished.is_set()
    assert monitor._configuration_refresh_task is None
    assert monitor._expiry_unsub is None
    assert monitor._unsub_refresh is None


async def test_periodic_monitor_runs_without_energy_or_entity_listeners(hass, freezer):
    freezer.move_to(NOW)
    monitor = AemoMarketMonitor(hass, "periodic-monitor", CONFIGURATION)
    monitor._async_fetch_summary = AsyncMock(return_value=summary())
    await monitor.async_start()
    await hass.async_block_till_done()
    assert monitor._async_fetch_summary.await_count == 1
    next_poll = NOW + timedelta(seconds=31)
    freezer.move_to(next_poll)
    async_fire_time_changed(hass, next_poll)
    await hass.async_block_till_done()
    assert monitor._async_fetch_summary.await_count == 2
    await monitor.async_stop()
    after_stop = next_poll + timedelta(seconds=31)
    freezer.move_to(after_stop)
    async_fire_time_changed(hass, after_stop)
    await hass.async_block_till_done()
    assert monitor._async_fetch_summary.await_count == 2


async def test_disabling_retains_observations_and_clears_candidate_without_http(hass, freezer):
    freezer.move_to(NOW)
    events = []
    hass.bus.async_listen(EVENT_MARKET_OPPORTUNITY, _collect_events(events))
    first = AemoMarketMonitor(hass, "disable-monitor", CONFIGURATION)
    first._async_fetch_summary = AsyncMock(return_value=summary())
    await first.async_restore_history()
    await first.async_start()
    await first.async_stop()
    disabled = AemoMarketMonitor(
        hass, "disable-monitor", AemoMonitorConfiguration(False, "NSW1", 3.0, None)
    )
    disabled._async_fetch_summary = AsyncMock()
    await disabled.async_restore_history()
    await disabled.async_start()
    await hass.async_block_till_done()
    assert disabled.current_result.status == "disabled"
    assert len(disabled.recent_observations) == 1
    disabled._async_fetch_summary.assert_not_called()
    assert [event.data["phase"] for event in events] == ["onset", "clear"]
    await disabled.async_stop()


async def test_threshold_change_rechecks_candidate_without_rewriting_history(hass, freezer):
    freezer.move_to(NOW)
    events = []
    hass.bus.async_listen(EVENT_MARKET_OPPORTUNITY, _collect_events(events))
    first = AemoMarketMonitor(hass, "threshold-monitor", CONFIGURATION)
    first._async_fetch_summary = AsyncMock(return_value=summary())
    await first.async_restore_history()
    await first.async_start()
    await first.async_stop()
    changed = AemoMarketMonitor(
        hass, "threshold-monitor", AemoMonitorConfiguration(True, "NSW1", 5.0, None)
    )
    changed._async_fetch_summary = AsyncMock(return_value=summary())
    await changed.async_restore_history()
    assert changed.recent_observations[0]["status"] == "possible_export_event"
    assert changed.recent_observations[0]["export_threshold_per_kwh"] == 3
    await changed.async_start()
    await hass.async_block_till_done()
    assert changed.current_result.status == "watching"
    assert [event.data["phase"] for event in events] == ["onset", "clear"]
    assert len(changed.recent_observations) == 2
    await changed.async_stop()


async def test_late_expiry_callback_cannot_clear_newer_interval(hass, freezer):
    freezer.move_to(NOW)
    events = []
    hass.bus.async_listen(EVENT_MARKET_OPPORTUNITY, _collect_events(events))
    monitor = AemoMarketMonitor(hass, "late-expiry-monitor", CONFIGURATION)
    monitor._async_fetch_summary = AsyncMock(return_value=summary())
    await monitor.async_refresh()
    freezer.move_to(INTERVAL_END + timedelta(seconds=10))
    monitor._async_fetch_summary.return_value = summary(SETTLEMENTDATE="2026-10-11T08:10:00")
    await monitor.async_refresh()
    await monitor._async_expire(INTERVAL_END + timedelta(seconds=11), INTERVAL_END)
    await hass.async_block_till_done()
    assert monitor.current_result.status == "possible_export_event"
    assert monitor.current_result.interval_end == INTERVAL_END + timedelta(minutes=5)
    assert [event.data["phase"] for event in events] == ["onset", "update"]
    await monitor.async_stop()


async def test_result_waiting_for_state_lock_cannot_emit_expired_candidate(hass, freezer):
    freezer.move_to(NOW)
    events = []
    hass.bus.async_listen(EVENT_MARKET_OPPORTUNITY, _collect_events(events))
    monitor = AemoMarketMonitor(hass, "waiting-expiry-monitor", CONFIGURATION)
    candidate = parse_aemo_summary(summary(), CONFIGURATION, NOW)
    async with monitor._lock:
        pending = asyncio.create_task(monitor._async_apply_result(candidate))
        await asyncio.sleep(0)
        freezer.move_to(INTERVAL_END)
    await pending
    await hass.async_block_till_done()
    assert monitor.current_result.status == "stale"
    assert monitor.current_result.price_per_kwh is None
    assert events == []
    await monitor.async_stop()


async def test_storage_outage_is_visible_but_cannot_fail_normal_setup(hass, freezer):
    freezer.move_to(NOW)
    monitor = AemoMarketMonitor(hass, "storage-outage-monitor", CONFIGURATION)
    monitor._repository.store.async_load = AsyncMock(side_effect=OSError("unavailable"))
    monitor._repository.store.async_save = AsyncMock(side_effect=OSError("unavailable"))
    monitor._async_fetch_summary = AsyncMock(return_value=summary())
    await monitor.async_restore_history()
    assert monitor.result_attributes["persistence_status"] == "unavailable"
    await monitor.async_start()
    assert monitor.current_result.status == "possible_export_event"
    assert monitor.result_attributes["persistence_status"] == "unavailable"
    assert monitor.last_update_success is True
    await monitor.async_stop()


async def test_corrupted_history_is_not_restored_as_numeric_evidence(hass, freezer):
    freezer.move_to(NOW)
    monitor = AemoMarketMonitor(hass, "corrupt-monitor", CONFIGURATION)
    payload = {
        "observations": [{"region": "NSW1", "price_per_mwh": float("nan")}],
        "active_candidate": {"region": "NSW1", "price_per_mwh": True},
        "last_notified_signature": None,
    }
    monitor._repository.store.async_load = AsyncMock(return_value=payload)
    await monitor.async_restore_history()
    assert monitor.recent_observations == []
    assert monitor.current_result.price_per_kwh is None
    await monitor.async_stop()


async def test_store_save_crossing_interval_end_cannot_emit_late_candidate(hass, freezer):
    freezer.move_to(NOW)
    events = []
    hass.bus.async_listen(EVENT_MARKET_OPPORTUNITY, _collect_events(events))
    monitor = AemoMarketMonitor(hass, "slow-save-monitor", CONFIGURATION)
    monitor._async_fetch_summary = AsyncMock(return_value=summary())
    original_save = monitor._repository.store.async_save

    async def slow_save(payload):
        freezer.move_to(INTERVAL_END)
        async_fire_time_changed(hass, INTERVAL_END)
        await original_save(payload)

    monitor._repository.store.async_save = slow_save
    await monitor.async_refresh()
    await hass.async_block_till_done()
    assert [event.data["phase"] for event in events] == ["onset", "clear"]
    assert events[0].time_fired < INTERVAL_END
    assert events[-1].data["status"] == "stale"
    assert monitor.current_result.price_per_kwh is None
    await monitor.async_stop()
