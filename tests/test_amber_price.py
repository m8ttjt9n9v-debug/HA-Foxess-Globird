"""Native Amber evidence and bounded provider failover, without another API client."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import nextafter
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.home_energy_orchestrator import aemo_monitor, amber_price
from custom_components.home_energy_orchestrator.aemo_monitor import AemoMarketMonitor
from custom_components.home_energy_orchestrator.amber_price import (
    AmberPriceSample,
    capture_amber_price,
)
from custom_components.home_energy_orchestrator.configuration import AemoMonitorConfiguration

from .test_aemo_dispatch_feed import dispatch_report

NOW = datetime(2026, 10, 12, 9, 2, tzinfo=UTC)
START = NOW.replace(minute=0)
END = START + timedelta(minutes=5)
ENTITY = "sensor.renamed_wholesale_source"
CONFIG = AemoMonitorConfiguration(True, "NSW1", 3, None, ENTITY, "NSW1")


@pytest.fixture
def native(monkeypatch):
    attributes = {
        "unit_of_measurement": "$/kWh",
        "channel_type": "feedIn",
        "duration": 5,
        "estimate": False,
        "spot_per_kwh": 3.3,
        "per_kwh": -100,
        "start_time": (START + timedelta(seconds=1)).isoformat(),
        "end_time": END.isoformat(),
    }
    state = SimpleNamespace(state="-100", attributes=attributes, last_updated=NOW)
    registry = SimpleNamespace(
        platform="amberelectric",
        disabled_by=None,
        config_entry_id="amber-provider",
        unique_id="synthetic-site-current-feed_in",
    )
    entry = SimpleNamespace(
        domain="amberelectric",
        state=ConfigEntryState.LOADED,
        # No credential or API client is needed or available to this reader.
        data={"site_id": "synthetic-site"},
    )
    hass = SimpleNamespace(
        states=SimpleNamespace(get=Mock(return_value=state)),
        config_entries=SimpleNamespace(async_get_entry=Mock(return_value=entry)),
    )
    monkeypatch.setattr(
        amber_price.er,
        "async_get",
        lambda _: SimpleNamespace(
            async_get=Mock(return_value=registry),
        ),
    )
    return SimpleNamespace(hass=hass, state=state, registry=registry, entry=entry, attrs=attributes)


def capture(native, **kwargs):
    return capture_amber_price(
        native.hass, ENTITY, "NSW1", kwargs.pop("region", "NSW1"), kwargs.pop("now", NOW), **kwargs
    )


@pytest.mark.parametrize(
    "spot,expected",
    [
        (3.3, 3),
        (nextafter(3.3, float("-inf")), nextafter(3, float("-inf"))),
        (3.29999, 2.999990909090909),
        (0.117172, 0.10652),
        (-1.1, -1),
        (0, 0),
    ],
)
def test_only_wholesale_attribute_normalizes_gst_once_without_tariff_or_sign(
    native, spot, expected
):
    native.attrs["spot_per_kwh"] = spot
    result = capture(native)
    assert result.status == "confirmed"
    assert result.price_per_kwh == expected
    assert result.interval_start == START
    assert result.interval_end == END


@pytest.mark.parametrize(
    "field,value",
    [
        ("estimate", True),
        ("estimate", None),
        ("estimate", "false"),
        ("estimate", 0),
        ("duration", 30),
        ("duration", 5.0),
        ("duration", True),
        ("spot_per_kwh", None),
        ("spot_per_kwh", True),
        ("spot_per_kwh", "3.3"),
        ("spot_per_kwh", float("nan")),
        ("spot_per_kwh", float("inf")),
        ("unit_of_measurement", "c/kWh"),
        ("channel_type", []),
        ("channel_type", "invalid"),
        ("restored", True),
        ("restored", "false"),
        ("start_time", None),
        ("start_time", "2026-10-12T09:00:00"),
        ("start_time", (START + timedelta(seconds=2)).isoformat()),
        ("end_time", (END + timedelta(seconds=1)).isoformat()),
        ("end_time", (END + timedelta(minutes=1)).isoformat()),
    ],
)
def test_bad_native_evidence_is_not_a_price(native, field, value):
    native.attrs[field] = value
    assert capture(native).price_per_kwh is None


@pytest.mark.parametrize(
    "case",
    [
        "not_native",
        "different_entry",
        "unloaded",
        "disabled",
        "wrong_channel",
        "old_clock",
        "future_clock",
        "unavailable",
        "unknown",
        "wrong_region",
    ],
)
def test_source_identity_and_clocks_fail_closed(native, case):
    if case == "not_native":
        native.registry.platform = "template"
    elif case == "different_entry":
        native.entry.data["site_id"] = "another-site"
    elif case == "unloaded":
        native.entry.state = ConfigEntryState.NOT_LOADED
    elif case == "disabled":
        native.registry.disabled_by = "user"
    elif case == "wrong_channel":
        native.registry.unique_id = "synthetic-site-current-general"
    elif case == "old_clock":
        native.state.last_updated = START - timedelta(seconds=1)
    elif case == "future_clock":
        native.state.last_updated = NOW + timedelta(seconds=1)
    elif case in {"unavailable", "unknown"}:
        native.state.state = case
    assert (
        capture(native, region="QLD1" if case == "wrong_region" else "NSW1").price_per_kwh is None
    )


@pytest.mark.parametrize(
    "now,expected",
    [
        (START - timedelta(microseconds=1), "future"),
        (END, "stale"),
        (END + timedelta(minutes=5), "stale"),
    ],
)
def test_no_previous_or_future_interval_authority(native, now, expected):
    assert capture(native, now=now).status == expected


@pytest.fixture
async def monitor_rig(hass, monkeypatch, freezer):
    freezer.move_to(NOW)
    native = SimpleNamespace(sample=AmberPriceSample("unavailable", ENTITY))
    monkeypatch.setattr(aemo_monitor, "capture_amber_price", lambda *_: native.sample)
    monitor = AemoMarketMonitor(hass, "amber-selector", CONFIG)
    await monitor.async_restore_history()
    monitor._async_fetch_summary = AsyncMock(return_value=dispatch_report(NOW, price=5000))
    await monitor.async_start()
    native.sample = AmberPriceSample("confirmed", ENTITY, 3, START, END, NOW)
    try:
        yield SimpleNamespace(hass=hass, monitor=monitor, native=native)
    finally:
        await monitor.async_stop()


async def feed(monitor, price=5000, **kwargs):
    report = dispatch_report(NOW, price=price, **kwargs)
    result = aemo_monitor.parse_aemo_dispatch_zip(
        report.body, monitor.configuration, NOW, source_url=report.source_url
    )
    await monitor._async_apply_result(result)


@pytest.mark.parametrize("primary,fallback", [(3, 1), (3, 5), (2, 5), (0, 5), (-1, 5)])
async def test_qualified_primary_wins_including_low_prices(monitor_rig, primary, fallback):
    rig = monitor_rig
    rig.native.sample = replace(rig.native.sample, price_per_kwh=primary)
    await feed(rig.monitor, fallback * 1000)
    result = rig.monitor.current_result
    assert result.source_kind == "amber"
    assert result.price_per_kwh == primary
    assert result.price_trigger_valid
    assert result.price_status is result.apc_flag is result.intervention is None
    assert result.payment_confirmed is result.declared_event_confirmed is False


@pytest.mark.parametrize("reason", ["unavailable", "unconfirmed", "stale", "region_mismatch"])
async def test_unqualified_primary_uses_current_firm_aemo(monitor_rig, reason):
    rig = monitor_rig
    rig.native.sample = AmberPriceSample(reason, ENTITY)
    await feed(rig.monitor)
    assert rig.monitor.current_result.source_kind == "dispatchis"
    assert rig.monitor.current_result.price_trigger_valid
    rig.native.sample = AmberPriceSample("confirmed", ENTITY, 2, START, END, NOW)
    await rig.monitor._async_amber_changed(0)
    assert rig.monitor.current_result.source_kind == "amber"
    assert rig.monitor.current_result.price_per_kwh == 2


async def test_revoked_primary_does_not_resurrect_from_same_interval_fallback(monitor_rig, freezer):
    rig = monitor_rig
    await feed(rig.monitor)
    freezer.tick(timedelta(seconds=30))
    rig.native.sample = replace(
        rig.native.sample, price_per_kwh=2, updated_at=NOW + timedelta(seconds=30)
    )
    await rig.monitor._async_amber_changed(0)
    rig.native.sample = AmberPriceSample("unavailable", ENTITY)
    await rig.monitor._async_amber_changed(0)
    assert rig.monitor.current_result.status == "provider_disagreement"
    assert not rig.monitor.current_result.price_trigger_valid
    # Preserve the latest low correction across restart, not just the first high.
    restarted = AemoMarketMonitor(rig.hass, "amber-selector", CONFIG)
    try:
        await restarted.async_restore_history()
        assert any(
            record.source_kind == "amber" and record.price_per_kwh == 2
            for record in restarted._state.observations
        )
        assert restarted.current_result.price_per_kwh is None
        restarted._async_fetch_summary = AsyncMock(return_value=dispatch_report(NOW, price=5000))
        await restarted.async_start()
        assert restarted.current_result.status == "provider_disagreement"
    finally:
        await restarted.async_stop()


@pytest.mark.parametrize("flags", [{"APCFLAG": 1}, {"MARKETSUSPENDEDFLAG": 1}, {"INTERVENTION": 1}])
async def test_known_current_aemo_restriction_vetoes_primary(monitor_rig, flags):
    rig = monitor_rig
    await feed(rig.monitor, **flags)
    assert rig.monitor.current_result.price_per_kwh is None
    assert not rig.monitor.current_result.price_trigger_valid


@pytest.mark.parametrize("flags", [{"APCFLAG": 1}, {"MARKETSUSPENDEDFLAG": 1}, {"INTERVENTION": 1}])
async def test_known_aemo_veto_survives_transport_failure_old_report_and_restart(
    monitor_rig, flags
):
    rig = monitor_rig
    await feed(rig.monitor, serial=2, **flags)
    rig.monitor._async_fetch_summary = AsyncMock(side_effect=TimeoutError)
    await rig.monitor.async_refresh()
    assert not rig.monitor.current_result.price_trigger_valid
    await feed(rig.monitor, serial=1)
    assert not rig.monitor.current_result.price_trigger_valid
    restarted = AemoMarketMonitor(rig.hass, "amber-selector", CONFIG)
    restarted._async_fetch_summary = AsyncMock(return_value=dispatch_report(NOW, price=5000))
    try:
        await restarted.async_restore_history()
        await restarted.async_start()
        assert not restarted.current_result.price_trigger_valid
        await feed(restarted, serial=3)
        assert restarted.current_result.price_trigger_valid
    finally:
        await restarted.async_stop()


async def test_slow_aemo_response_reselects_newer_primary(monitor_rig, monkeypatch, freezer):
    rig = monitor_rig
    entered, finish = asyncio.Event(), asyncio.Event()

    async def delayed():
        entered.set()
        await finish.wait()
        return dispatch_report(NOW, price=5000)

    monkeypatch.setattr(rig.monitor, "_async_fetch_summary", delayed)
    pending = asyncio.create_task(rig.monitor.async_refresh())
    await entered.wait()
    freezer.tick(timedelta(seconds=1))
    rig.native.sample = replace(
        rig.native.sample, price_per_kwh=2, updated_at=NOW + timedelta(seconds=1)
    )
    await rig.monitor._async_amber_changed(0)
    finish.set()
    await pending
    assert rig.monitor.current_result.source_kind == "amber"
    assert rig.monitor.current_result.price_per_kwh == 2


async def test_expiry_and_old_setting_callbacks_cannot_renew_source(monitor_rig, freezer):
    rig = monitor_rig
    await feed(rig.monitor)
    await rig.monitor.async_update_configuration(replace(CONFIG, enabled=False))
    await rig.monitor._async_amber_changed(0)
    assert rig.monitor.current_result.status == "disabled"
    freezer.move_to(END)
    await rig.monitor._async_expire(END, END, 0)
    assert rig.monitor.current_result.price_per_kwh is None


async def test_same_interval_primary_correction_replay_cannot_restore_old_high(
    monitor_rig, freezer
):
    rig = monitor_rig
    await feed(rig.monitor)
    old = rig.native.sample
    freezer.tick(timedelta(seconds=1))
    rig.native.sample = replace(old, price_per_kwh=2, updated_at=NOW + timedelta(seconds=1))
    await rig.monitor._async_amber_changed(0)
    rig.native.sample = old
    assert rig.monitor.current_result.status == "source_replay"
    assert not rig.monitor.current_result.price_trigger_valid


async def test_both_providers_missing_do_not_manufacture_zero_or_use_history(monitor_rig):
    rig = monitor_rig
    await feed(rig.monitor)
    rig.native.sample = AmberPriceSample("unavailable", ENTITY)
    rig.monitor._async_fetch_summary = AsyncMock(side_effect=TimeoutError)
    await rig.monitor.async_refresh()
    assert rig.monitor.current_result.price_per_kwh is None
    assert not rig.monitor.current_result.price_trigger_valid


@pytest.mark.parametrize(
    "invalid", ["invalid_dispatch_archive", "unknown_price_status", "invalid_market_flags"]
)
async def test_newer_invalid_report_cannot_clear_an_affirmative_veto(monitor_rig, invalid):
    rig = monitor_rig
    await feed(rig.monitor, serial=2, APCFLAG=1)
    newer = dispatch_report(NOW, serial=3)
    await rig.monitor._async_apply_result(
        replace(
            rig.monitor._aemo_result,
            status=invalid,
            price_per_mwh=None,
            price_per_kwh=None,
            apc_flag=None,
            source_url=newer.source_url,
        )
    )
    assert not rig.monitor.current_result.price_trigger_valid
    assert rig.monitor.current_result.status == "administered_pricing"


async def test_newer_official_low_is_retained_while_primary_wins(monitor_rig):
    rig = monitor_rig
    await feed(rig.monitor, price=2000, serial=2)
    assert rig.monitor.current_result.source_kind == "amber"
    await feed(rig.monitor, price=5000, serial=1)
    rig.native.sample = AmberPriceSample("unavailable", ENTITY)
    result = rig.monitor.current_result
    assert result.source_kind == "dispatchis"
    assert result.price_per_kwh == 2
    assert result.status == "watching"


async def test_primary_low_seen_during_official_veto_is_not_forgotten(monitor_rig, freezer):
    rig = monitor_rig
    await feed(rig.monitor, serial=2, APCFLAG=1)
    freezer.tick(timedelta(seconds=1))
    rig.native.sample = replace(
        rig.native.sample,
        price_per_kwh=2,
        updated_at=NOW + timedelta(seconds=1),
    )
    await rig.monitor._async_amber_changed(0)
    rig.native.sample = AmberPriceSample("unavailable", ENTITY)
    await feed(rig.monitor, serial=3)
    assert rig.monitor.current_result.status == "provider_disagreement"
    assert not rig.monitor.current_result.price_trigger_valid


async def test_same_timestamp_contradictory_native_price_is_not_a_new_correction(monitor_rig):
    rig = monitor_rig
    await feed(rig.monitor)
    rig.native.sample = replace(rig.native.sample, price_per_kwh=5)
    assert rig.monitor.current_result.status == "source_replay"
    assert not rig.monitor.current_result.price_trigger_valid
