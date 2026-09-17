"""Advance all daily accounting meters from one captured power observation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from .daily_meter import (
    DailyImportAccumulator,
    HourlyWindowImportAccumulator,
    WindowImportAccumulator,
)

DAILY_IMPORT = "daily_import"
DAILY_EXPORT = "daily_export"
STANDARD_RATE_EXPORT = "standard_rate_export"
FREE_WINDOW_IMPORT = "free_window_import"
PEAK_IMPORT = "peak_import"
ZEROHERO_IMPORT = "zerohero_import"
ZEROHERO_EXPORT = "zerohero_export"


@dataclass(frozen=True, slots=True)
class AccountingMeterSet:
    """The separate retained accumulators advanced by one cycle."""

    daily_import: DailyImportAccumulator
    daily_export: DailyImportAccumulator
    standard_rate_export: WindowImportAccumulator
    free_window_import: WindowImportAccumulator
    peak_import: WindowImportAccumulator
    zerohero_import: HourlyWindowImportAccumulator
    zerohero_export: WindowImportAccumulator


@dataclass(frozen=True, slots=True)
class MeterCheckpointState:
    """Last persisted totals used to coalesce Store writes."""

    daily_import: float | None
    daily_export: float | None
    standard_rate_export: float | None
    free_window_import: float | None
    peak_import: float | None
    zerohero_import: float | None
    zerohero_export: float | None


@dataclass(frozen=True, slots=True)
class MeterCheckpointRequest:
    """One ordered request for the adapter to persist a changed meter."""

    name: str
    total_kwh: float


async def advance_accounting_meters(
    meters: AccountingMeterSet,
    *,
    grid_power_kw: float | None,
    export_power_kw: float | None,
    observed_at: datetime,
    checkpoints: MeterCheckpointState,
    checkpoint: Callable[[MeterCheckpointRequest], Awaitable[None]],
) -> tuple[MeterCheckpointRequest, ...]:
    """Advance every meter once and return ordered checkpoint requests.

    The function never accesses persistence directly. It awaits the coordinator
    adapter's checkpoint callback before advancing the next meter, preserving
    the established Store order and failure short-circuiting.
    """
    requests: list[MeterCheckpointRequest] = []
    definitions = (
        (DAILY_IMPORT, meters.daily_import, grid_power_kw, checkpoints.daily_import, 0.05),
        (DAILY_EXPORT, meters.daily_export, export_power_kw, checkpoints.daily_export, 0.05),
        (
            STANDARD_RATE_EXPORT,
            meters.standard_rate_export,
            export_power_kw,
            checkpoints.standard_rate_export,
            0.01,
        ),
        (
            FREE_WINDOW_IMPORT,
            meters.free_window_import,
            grid_power_kw,
            checkpoints.free_window_import,
            0.05,
        ),
        (PEAK_IMPORT, meters.peak_import, grid_power_kw, checkpoints.peak_import, 0.05),
        (
            ZEROHERO_IMPORT,
            meters.zerohero_import,
            grid_power_kw,
            checkpoints.zerohero_import,
            0.01,
        ),
        (
            ZEROHERO_EXPORT,
            meters.zerohero_export,
            export_power_kw,
            checkpoints.zerohero_export,
            0.01,
        ),
    )
    for name, meter, power_kw, last_saved, threshold in definitions:
        if not meter.observe(power_kw, observed_at):
            continue
        total = meter.imported_kwh
        prior = 0.0 if last_saved is None else last_saved
        if (
            last_saved is None
            or total < prior
            or total - prior >= threshold
            or meter.checkpoint_required
        ):
            request = MeterCheckpointRequest(name, total)
            requests.append(request)
            await checkpoint(request)
    return tuple(requests)
