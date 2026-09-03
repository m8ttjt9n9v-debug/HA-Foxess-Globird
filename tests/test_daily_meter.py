from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from custom_components.home_energy_orchestrator.planner.daily_meter import (
    DailyImportAccumulator,
    WindowImportAccumulator,
)

TZ = ZoneInfo("Australia/Sydney")


def test_accumulator_integrates_power_and_caps_restart_gap() -> None:
    meter = DailyImportAccumulator(max_gap_hours=0.25)
    first = datetime(2026, 9, 3, 12, 0, tzinfo=TZ)
    meter.observe(2.0, first)
    meter.observe(4.0, first.replace(hour=12, minute=30))
    assert meter.imported_kwh == 0.75

    meter.observe(10.0, first.replace(hour=18))
    assert meter.imported_kwh == 2.5


def test_accumulator_resets_on_local_midnight_and_restores_same_day() -> None:
    meter = DailyImportAccumulator()
    before = datetime(2026, 9, 3, 23, 59, tzinfo=TZ)
    after = datetime(2026, 9, 4, 0, 1, tzinfo=TZ)
    meter.observe(2.0, before)
    meter.observe(2.0, after)
    assert meter.local_date == after.date()
    assert meter.imported_kwh == 0.0

    restored = DailyImportAccumulator()
    restored.restore(meter.to_payload(), after)
    assert restored.local_date == after.date()
    assert restored.imported_kwh == 0.0


def test_window_accumulator_counts_only_window_overlap() -> None:
    meter = WindowImportAccumulator(
        max_gap_hours=3.0,
        window_start=datetime(2026, 9, 3, 12, tzinfo=TZ).timetz().replace(tzinfo=None),
        window_end=datetime(2026, 9, 3, 15, tzinfo=TZ).timetz().replace(tzinfo=None),
    )
    meter.observe(4.0, datetime(2026, 9, 3, 11, 30, tzinfo=TZ))
    meter.observe(4.0, datetime(2026, 9, 3, 13, 30, tzinfo=TZ))
    meter.observe(4.0, datetime(2026, 9, 3, 16, tzinfo=TZ))
    assert meter.imported_kwh == 12.0
