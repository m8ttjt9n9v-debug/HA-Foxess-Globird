"""Actual current DispatchIS evidence, archive bounds and fail-closed transport."""

import io
import zipfile
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from custom_components.home_energy_orchestrator.aemo_monitor import (
    AEMO_DATA_SOURCE,
    AemoMarketMonitor,
    _DispatchReport,
    _FeedUnavailable,
    current_dispatch_report_url,
    parse_aemo_dispatch_csv,
    parse_aemo_dispatch_zip,
    parse_aemo_summary,
)
from custom_components.home_energy_orchestrator.configuration import AemoMonitorConfiguration

NOW = datetime(2026, 10, 12, 4, 26, tzinfo=UTC)
CONFIG = AemoMonitorConfiguration(True, "NSW1", 3.0, None)
AEST = timezone(timedelta(hours=10))
HEADER = [
    "SETTLEMENTDATE",
    "RUNNO",
    "REGIONID",
    "INTERVENTION",
    "RRP",
    "APCFLAG",
    "MARKETSUSPENDEDFLAG",
    "PRICE_STATUS",
]


def dispatch_csv(now=NOW, region="NSW1", price=9998.66, **changes):
    market = now.astimezone(AEST).replace(second=0, microsecond=0)
    end = market + timedelta(minutes=5 - market.minute % 5)
    record = {
        "SETTLEMENTDATE": end.strftime("%Y/%m/%d %H:%M:%S"),
        "RUNNO": "1",
        "REGIONID": region,
        "INTERVENTION": "0",
        "RRP": str(price),
        "APCFLAG": "0",
        "MARKETSUSPENDEDFLAG": "0",
        "PRICE_STATUS": "FIRM",
    }
    record.update(changes)
    text = "I,DISPATCH,PRICE,5," + ",".join(HEADER) + "\n"
    text += "D,DISPATCH,PRICE,5," + ",".join(str(record[key]) for key in HEADER) + "\n"
    return text.encode()


def dispatch_report(now=NOW, region="NSW1", price=9998.66, serial=1, **changes):
    """A sanitized real-report-shaped fixture; no site/notification evidence."""
    market = now.astimezone(AEST).replace(second=0, microsecond=0)
    end = market + timedelta(minutes=5 - market.minute % 5)
    stem = "PUBLIC_DISPATCHIS_" + end.strftime("%Y%m%d%H%M") + f"_{serial:016d}"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(stem + ".CSV", dispatch_csv(now, region, price, **changes))
    return _DispatchReport(stream.getvalue(), AEMO_DATA_SOURCE + stem + ".zip")


@pytest.mark.freeze_time(NOW)
def test_actual_market_spike_has_coherent_units_interval_and_source():
    report = dispatch_report()
    result = parse_aemo_dispatch_zip(report.body, CONFIG, NOW, source_url=report.source_url)
    assert result.status == "possible_export_event"
    assert result.price_per_mwh == 9998.66
    assert result.price_per_kwh == pytest.approx(9.99866)
    assert result.interval_start == datetime(2026, 10, 12, 4, 25, tzinfo=UTC)
    assert result.interval_end == datetime(2026, 10, 12, 4, 30, tzinfo=UTC)
    assert result.intervention == 0
    assert result.source_kind == "dispatchis"
    assert result.data_source == report.source_url
    assert result.price_trigger_valid is True
    assert result.attributes()["price_unit"] == "AUD/kWh"
    assert result.control_authority is False
    assert result.declared_event_confirmed is result.payment_confirmed is False


@pytest.mark.freeze_time(NOW)
@pytest.mark.parametrize(
    "changes,status",
    [
        ({"INTERVENTION": "1"}, "nonzero_intervention"),
        ({"RUNNO": "2"}, "invalid_dispatch_run"),
        ({"PRICE_STATUS": "ESTIMATE"}, "unknown_price_status"),
        ({"APCFLAG": "1"}, "administered_pricing"),
        ({"MARKETSUSPENDEDFLAG": "1"}, "market_suspended"),
        ({"APCFLAG": "2"}, "invalid_market_flags"),
        ({"RRP": "NaN"}, "invalid_dispatch_report"),
        ({"RRP": "inf"}, "invalid_dispatch_report"),
        ({"RRP": "1e999"}, "invalid_dispatch_report"),
        ({"RRP": "True"}, "invalid_dispatch_report"),
        ({"REGIONID": "QLD1"}, "missing_region"),
        ({"SETTLEMENTDATE": "2026/10/12 14:25:00"}, "stale"),
        ({"SETTLEMENTDATE": "2026/10/12 14:35:00"}, "future"),
        ({"SETTLEMENTDATE": "2026/10/12 14:31:00"}, "invalid_interval"),
    ],
)
def test_non_actual_or_invalid_record_never_authorizes(changes, status):
    result = parse_aemo_dispatch_csv(dispatch_csv(**changes), CONFIG, NOW)
    assert result.status == status
    assert result.price_trigger_valid is False


@pytest.mark.freeze_time(NOW)
def test_duplicate_header_or_region_and_unknown_schema_fail_closed():
    csv = dispatch_csv()
    header, row = csv.splitlines()
    for bad in (
        csv + row + b"\n",
        header + b"\n" + csv,
        csv.replace(b",PRICE,5,", b",PRICE,6,"),
        csv.replace(b",PRICE_STATUS", b",REGIONID"),
        row + b"\n",
    ):
        assert not parse_aemo_dispatch_csv(bad, CONFIG, NOW).price_trigger_valid


@pytest.mark.freeze_time(NOW)
def test_same_threshold_is_not_an_export_candidate_and_exact_expiry_is_closed(freezer):
    exact = parse_aemo_dispatch_csv(dispatch_csv(price=3000), CONFIG, NOW)
    assert exact.status == "watching"
    assert exact.price_trigger_valid
    freezer.move_to(datetime(2026, 10, 12, 4, 30, tzinfo=UTC))
    assert not exact.source_fresh
    assert not exact.price_trigger_valid


def test_current_directory_selection_cannot_adopt_stale_or_future_interval():
    current = dispatch_report().source_url.rsplit("/", 1)[1]
    assert current_dispatch_report_url(current + " " + current, NOW).endswith(current)
    higher = current.replace("0000000000000001", "0000000000000002")
    assert current_dispatch_report_url(current + " " + higher, NOW).endswith(higher)
    for index in (current.replace("1430", "1425"), current.replace("1430", "1435")):
        with pytest.raises(_FeedUnavailable):
            current_dispatch_report_url(index, NOW)
    with pytest.raises(_FeedUnavailable):
        current_dispatch_report_url(current, datetime(2026, 10, 12, 4, 30, tzinfo=UTC))


@pytest.mark.freeze_time(NOW)
def test_zip_paths_multiple_members_ratio_bounds_and_filename_mismatch_are_rejected():
    for name, body, extra in (
        ("../record.CSV", dispatch_csv(), False),
        ("PUBLIC_DISPATCHIS_202610121430_0000000000000001.CSV", dispatch_csv(), True),
        ("PUBLIC_DISPATCHIS_202610121435_0000000000000001.CSV", dispatch_csv(), False),
        ("PUBLIC_DISPATCHIS_202610121430_0000000000000001.CSV", b"0" * 200000, False),
    ):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(name, body)
            if extra:
                archive.writestr("another.CSV", body)
        result = parse_aemo_dispatch_zip(stream.getvalue(), CONFIG, NOW)
        assert result.price_trigger_valid is False
    for payload in (b"bad ZIP", b"x" * (2 * 1024 * 1024 + 1)):
        assert parse_aemo_dispatch_zip(payload, CONFIG, NOW).price_trigger_valid is False


@pytest.mark.freeze_time(NOW)
def test_report_url_cannot_label_an_older_member_as_a_newer_correction():
    older = dispatch_report(serial=1)
    newer = dispatch_report(serial=2)
    result = parse_aemo_dispatch_zip(older.body, CONFIG, NOW, source_url=newer.source_url)
    assert result.status == "report_identity_mismatch"
    assert not result.price_trigger_valid


@pytest.mark.freeze_time(NOW)
async def test_older_high_replay_preserves_newer_low_and_original_fetch_time(hass, freezer):
    newer = dispatch_report(price=100, serial=3)
    monitor = AemoMarketMonitor(hass, "serial-replay", CONFIG)
    monitor._async_fetch_summary = AsyncMock(
        side_effect=[
            dispatch_report(price=9998.66, serial=1),
            newer,
            dispatch_report(price=9998.66, serial=2),
        ]
    )
    try:
        await monitor.async_refresh()
        assert monitor.current_result.status == "possible_export_event"
        freezer.tick(timedelta(seconds=10))
        await monitor.async_refresh()
        accepted = monitor.current_result
        assert accepted.status == "watching"
        freezer.tick(timedelta(seconds=10))
        await monitor.async_refresh()
        assert monitor.current_result == accepted
        assert monitor.current_result.source_url == newer.source_url
        assert monitor.current_result.successful_fetch_at == NOW + timedelta(seconds=10)
        assert len(monitor.recent_observations) == 2
    finally:
        await monitor.async_stop()


@pytest.mark.freeze_time(NOW)
async def test_highest_serial_same_price_is_retained_across_history_restore(hass, freezer):
    key = "serial-roundtrip"
    latest = dispatch_report(price=100, serial=4)
    first = AemoMarketMonitor(hass, key, CONFIG)
    first._async_fetch_summary = AsyncMock(
        side_effect=[
            dispatch_report(price=9998.66, serial=1),
            dispatch_report(price=100, serial=3),
            latest,
        ]
    )
    for _ in range(3):
        await first.async_refresh()
        freezer.tick(timedelta(seconds=5))
    assert len(first.recent_observations) == 3
    accepted = first.current_result
    await first.async_stop()
    restored = AemoMarketMonitor(hass, key, CONFIG)
    restored._async_fetch_summary = AsyncMock(return_value=dispatch_report(price=9998.66, serial=2))
    try:
        await restored.async_restore_history()
        assert restored.current_result.price_per_kwh is None
        # History order is not an authority rule: choose the highest serial,
        # not the oldest matching observation or whichever one happens to be last.
        restored._state.observations.reverse()
        await restored.async_refresh()
        assert restored.current_result == accepted
        assert restored.current_result.source_url == latest.source_url
        assert restored.current_result.status == "watching"
    finally:
        await restored.async_stop()


@pytest.mark.freeze_time(NOW)
@pytest.mark.parametrize("flag", ["APCFLAG", "MARKETSUSPENDEDFLAG"])
async def test_older_normal_price_cannot_replace_a_newer_market_restriction(hass, flag):
    monitor = AemoMarketMonitor(hass, "serial-market-restriction", CONFIG)
    monitor._async_fetch_summary = AsyncMock(
        side_effect=[
            dispatch_report(serial=2, **{flag: "1"}),
            dispatch_report(serial=1),
        ]
    )
    try:
        await monitor.async_refresh()
        newest = monitor.current_result
        assert not newest.price_trigger_valid
        await monitor.async_refresh()
        assert monitor.current_result == newest
        assert not monitor.current_result.price_trigger_valid
    finally:
        await monitor.async_stop()


@pytest.mark.freeze_time(NOW)
async def test_live_fetch_uses_exact_report_and_not_cached_summary(hass, aioclient_mock):
    report = dispatch_report()
    aioclient_mock.get(AEMO_DATA_SOURCE, text=report.source_url)
    aioclient_mock.get(report.source_url, content=report.body)
    monitor = AemoMarketMonitor(hass, "dispatch-feed", CONFIG)
    await monitor.async_restore_history()
    await monitor.async_start()
    try:
        assert monitor.current_result.price_trigger_valid
        assert monitor.current_result.data_source == report.source_url
        assert aioclient_mock.call_count == 2
    finally:
        await monitor.async_stop()


@pytest.mark.freeze_time(NOW)
@pytest.mark.parametrize("bad_index", ["", "PUBLIC_DISPATCHIS_202610121425_0000000000000001.zip"])
async def test_missing_current_report_never_downloads_older_archive(
    hass, aioclient_mock, bad_index
):
    aioclient_mock.get(AEMO_DATA_SOURCE, text=bad_index)
    monitor = AemoMarketMonitor(hass, "missing-feed", CONFIG)
    await monitor.async_start()
    try:
        assert monitor.current_result.status == "awaiting_current_report"
        assert monitor.current_result.price_per_kwh is None
        assert not monitor.current_result.price_trigger_valid
        assert aioclient_mock.call_count == 1
    finally:
        await monitor.async_stop()


@pytest.mark.freeze_time(NOW)
async def test_transport_timeout_and_oversized_body_fail_closed(hass, aioclient_mock):
    aioclient_mock.get(AEMO_DATA_SOURCE, exc=TimeoutError)
    monitor = AemoMarketMonitor(hass, "timeout-feed", CONFIG)
    await monitor.async_start()
    try:
        assert monitor.current_result.status == "unavailable"
        assert not monitor.current_result.price_trigger_valid
        aioclient_mock.clear_requests()
        aioclient_mock.get(AEMO_DATA_SOURCE, content=b"x" * (2 * 1024 * 1024 + 1))
        await monitor.async_refresh()
        assert monitor.current_result.status == "response_size_limit"
        assert not monitor.current_result.price_trigger_valid
    finally:
        await monitor.async_stop()


@pytest.mark.freeze_time(NOW)
def test_summary_characterization_does_not_authorize_dispatch_control():
    result = parse_aemo_summary(
        {
            "ELEC_NEM_SUMMARY": [
                {
                    "REGIONID": "NSW1",
                    "SETTLEMENTDATE": "2026-10-12T14:30:00",
                    "PRICE": 9998.66,
                    "PRICE_STATUS": "FIRM",
                    "APCFLAG": 0,
                    "MARKETSUSPENDEDFLAG": 0,
                }
            ]
        },
        CONFIG,
        NOW,
    )
    assert result.status == "possible_export_event"
    assert result.source_kind == "summary"
    assert not result.price_trigger_valid
