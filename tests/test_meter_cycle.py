from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.home_energy_orchestrator.planner.daily_meter import (
    DailyImportAccumulator,
    HourlyWindowImportAccumulator,
    WindowImportAccumulator,
)
from custom_components.home_energy_orchestrator.planner.meter_cycle import (
    DAILY_EXPORT,
    DAILY_IMPORT,
    FREE_WINDOW_IMPORT,
    PEAK_IMPORT,
    STANDARD_RATE_EXPORT,
    ZEROHERO_EXPORT,
    ZEROHERO_IMPORT,
    AccountingMeterSet,
    MeterCheckpointState,
    advance_accounting_meters,
)


def _meters() -> AccountingMeterSet:
    return AccountingMeterSet(
        daily_import=DailyImportAccumulator(),
        daily_export=DailyImportAccumulator(),
        standard_rate_export=WindowImportAccumulator(
            window_start=time(16), window_end=time(23)
        ),
        free_window_import=WindowImportAccumulator(
            window_start=time(11), window_end=time(14)
        ),
        peak_import=WindowImportAccumulator(
            window_start=time(16), window_end=time(23)
        ),
        zerohero_import=HourlyWindowImportAccumulator(
            window_start=time(18), window_end=time(21)
        ),
        zerohero_export=WindowImportAccumulator(
            window_start=time(18), window_end=time(21)
        ),
    )


def _checkpoints(value: float | None) -> MeterCheckpointState:
    return MeterCheckpointState(
        daily_import=value,
        daily_export=value,
        standard_rate_export=value,
        free_window_import=value,
        peak_import=value,
        zerohero_import=value,
        zerohero_export=value,
    )


def _capture(requests):
    async def capture(request) -> None:
        requests.append(request)

    return capture


async def test_first_observation_requests_every_store_in_existing_order() -> None:
    captured = []
    requests = await advance_accounting_meters(
        _meters(),
        grid_power_kw=-1.0,
        export_power_kw=1.0,
        observed_at=datetime(2026, 9, 17, 18, tzinfo=ZoneInfo("Australia/Sydney")),
        checkpoints=_checkpoints(None),
        checkpoint=_capture(captured),
    )

    assert requests == tuple(captured)
    assert [request.name for request in requests] == [
        DAILY_IMPORT,
        DAILY_EXPORT,
        STANDARD_RATE_EXPORT,
        FREE_WINDOW_IMPORT,
        PEAK_IMPORT,
        ZEROHERO_IMPORT,
        ZEROHERO_EXPORT,
    ]


async def test_cycle_uses_existing_per_meter_checkpoint_thresholds() -> None:
    meters = _meters()
    first = datetime(2026, 9, 17, 18, tzinfo=ZoneInfo("Australia/Sydney"))
    await advance_accounting_meters(
        meters,
        grid_power_kw=-1.0,
        export_power_kw=1.0,
        observed_at=first,
        checkpoints=_checkpoints(None),
        checkpoint=_capture([]),
    )

    requests = await advance_accounting_meters(
        meters,
        grid_power_kw=-1.0,
        export_power_kw=1.0,
        observed_at=first + timedelta(minutes=1),
        checkpoints=_checkpoints(0.0),
        checkpoint=_capture([]),
    )

    assert [request.name for request in requests] == [
        STANDARD_RATE_EXPORT,
        ZEROHERO_EXPORT,
    ]
    assert requests[0].total_kwh == pytest.approx(1 / 60)


async def test_power_drop_forces_a_checkpoint_below_energy_threshold() -> None:
    meters = _meters()
    first = datetime(2026, 9, 17, 18, tzinfo=ZoneInfo("Australia/Sydney"))
    await advance_accounting_meters(
        meters,
        grid_power_kw=1.0,
        export_power_kw=0.0,
        observed_at=first,
        checkpoints=_checkpoints(None),
        checkpoint=_capture([]),
    )

    requests = await advance_accounting_meters(
        meters,
        grid_power_kw=0.0,
        export_power_kw=0.0,
        observed_at=first + timedelta(seconds=30),
        checkpoints=_checkpoints(0.0),
        checkpoint=_capture([]),
    )

    assert [request.name for request in requests] == [
        DAILY_IMPORT,
        FREE_WINDOW_IMPORT,
        PEAK_IMPORT,
        ZEROHERO_IMPORT,
    ]


async def test_checkpoint_failure_stops_before_later_meters_are_observed() -> None:
    meters = _meters()

    async def fail_first(_request) -> None:
        raise RuntimeError("store unavailable")

    with pytest.raises(RuntimeError):
        await advance_accounting_meters(
            meters,
            grid_power_kw=1.0,
            export_power_kw=0.0,
            observed_at=datetime(
                2026, 9, 17, 18, tzinfo=ZoneInfo("Australia/Sydney")
            ),
            checkpoints=_checkpoints(None),
            checkpoint=fail_first,
        )

    assert meters.daily_import.last_at is not None
    assert meters.daily_export.last_at is None
