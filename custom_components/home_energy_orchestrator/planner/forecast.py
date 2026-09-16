"""Pure optimistic-cost forecast and bounded calibration helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from math import isfinite


@dataclass(frozen=True, slots=True)
class OptimisticCostForecast:
    """One auditable forecast assembled from measured and assumed terms."""

    raw_net_cost: float
    calibrated_net_cost: float
    assumed_zerohero_credit: float
    export_realisation_fraction: float
    forecast_remaining_export_kwh: float
    forecast_additional_export_revenue: float
    learned_cost_bias: float


@dataclass(frozen=True, slots=True)
class ForecastDayRecord:
    """One privacy-minimal daily prediction and later retailer score."""

    local_date: date
    frozen_forecast_cost: float | None = None
    frozen_raw_forecast_cost: float | None = None
    planned_export_kwh: float = 0.0
    realised_export_kwh: float = 0.0
    export_realisation_ratio: float | None = None
    retailer_actual_cost: float | None = None
    retailer_zerohero_status: str | None = None
    forecast_error: float | None = None
    feedback_applied: bool = False

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-safe Home Assistant storage row."""
        return {
            "date": self.local_date.isoformat(),
            "frozen_forecast_cost": self.frozen_forecast_cost,
            "frozen_raw_forecast_cost": self.frozen_raw_forecast_cost,
            "planned_export_kwh": self.planned_export_kwh,
            "realised_export_kwh": self.realised_export_kwh,
            "export_realisation_ratio": self.export_realisation_ratio,
            "retailer_actual_cost": self.retailer_actual_cost,
            "retailer_zerohero_status": self.retailer_zerohero_status,
            "forecast_error": self.forecast_error,
            "feedback_applied": self.feedback_applied,
        }

    @classmethod
    def from_payload(cls, payload: object) -> ForecastDayRecord | None:
        """Decode one row while rejecting malformed numeric evidence."""
        if not isinstance(payload, dict):
            return None
        try:
            local_date = date.fromisoformat(str(payload["date"]))
            numeric = {
                key: _optional_finite(payload.get(key))
                for key in (
                    "frozen_forecast_cost",
                    "frozen_raw_forecast_cost",
                    "export_realisation_ratio",
                    "retailer_actual_cost",
                    "forecast_error",
                )
            }
            planned = float(payload.get("planned_export_kwh", 0.0))
            realised = float(payload.get("realised_export_kwh", 0.0))
        except (TypeError, ValueError):
            return None
        if (
            not isfinite(planned)
            or planned < 0
            or not isfinite(realised)
            or realised < 0
        ):
            return None
        ratio = numeric["export_realisation_ratio"]
        if ratio is not None and ratio < 0:
            return None
        status = payload.get("retailer_zerohero_status")
        return cls(
            local_date=local_date,
            frozen_forecast_cost=numeric["frozen_forecast_cost"],
            frozen_raw_forecast_cost=numeric["frozen_raw_forecast_cost"],
            planned_export_kwh=planned,
            realised_export_kwh=realised,
            export_realisation_ratio=ratio,
            retailer_actual_cost=numeric["retailer_actual_cost"],
            retailer_zerohero_status=str(status).casefold() if status else None,
            forecast_error=numeric["forecast_error"],
            feedback_applied=bool(payload.get("feedback_applied", False)),
        )


@dataclass(slots=True)
class ForecastFeedbackState:
    """Restart-safe forecast calibration with no control authority."""

    current: ForecastDayRecord
    export_realisation_fraction: float = 0.75
    learned_cost_bias: float = 0.0
    history: list[ForecastDayRecord] | None = None
    maximum_records: int = 28

    def __post_init__(self) -> None:
        if self.history is None:
            self.history = []

    @classmethod
    def restore(
        cls,
        payload: object,
        *,
        today: date,
        default_fraction: float = 0.75,
    ) -> ForecastFeedbackState:
        """Restore valid evidence and retain an unfinished previous day."""
        fallback = cls(
            current=ForecastDayRecord(today),
            export_realisation_fraction=default_fraction,
        )
        if not isinstance(payload, dict):
            return fallback
        current = ForecastDayRecord.from_payload(payload.get("current"))
        try:
            fraction = float(payload.get("export_realisation_fraction", default_fraction))
            bias = float(payload.get("learned_cost_bias", 0.0))
        except (TypeError, ValueError):
            return fallback
        if not isfinite(fraction) or not 0.5 <= fraction <= 1.0 or not isfinite(bias):
            return fallback
        rows = payload.get("history", [])
        history = (
            [record for row in rows if (record := ForecastDayRecord.from_payload(row))]
            if isinstance(rows, list)
            else []
        )
        return cls(
            current=current or ForecastDayRecord(today),
            export_realisation_fraction=fraction,
            learned_cost_bias=min(max(bias, -2.0), 2.0),
            history=sorted(history, key=lambda record: record.local_date)[-28:],
        )

    def roll_to(self, today: date) -> bool:
        """Finalize an older current day and begin today's record."""
        if self.current.local_date == today:
            return False
        if self.current.local_date < today:
            ratio = (
                self.current.realised_export_kwh / self.current.planned_export_kwh
                if self.current.planned_export_kwh > 0
                else None
            )
            self.current = replace(
                self.current,
                export_realisation_ratio=None if ratio is None else round(ratio, 4),
            )
            if self.current.planned_export_kwh >= 0.1:
                self.export_realisation_fraction = update_export_realisation_fraction(
                    self.export_realisation_fraction,
                    planned_export_kwh=self.current.planned_export_kwh,
                    realised_export_kwh=self.current.realised_export_kwh,
                )
            assert self.history is not None
            self.history = [
                record
                for record in self.history
                if record.local_date != self.current.local_date
            ]
            self.history.append(self.current)
            self.history = sorted(
                self.history, key=lambda record: record.local_date
            )[-self.maximum_records :]
        self.current = ForecastDayRecord(today)
        return True

    def observe_export(self, *, planned_total_kwh: float, realised_kwh: float) -> bool:
        """Retain the largest plan authority and latest measured window export."""
        if (
            not isfinite(planned_total_kwh)
            or planned_total_kwh < 0
            or not isfinite(realised_kwh)
            or realised_kwh < 0
        ):
            return False
        planned = max(self.current.planned_export_kwh, planned_total_kwh)
        changed = (
            abs(planned - self.current.planned_export_kwh) >= 0.01
            or abs(realised_kwh - self.current.realised_export_kwh) >= 0.01
        )
        self.current = replace(
            self.current,
            planned_export_kwh=round(planned, 4),
            realised_export_kwh=round(realised_kwh, 4),
        )
        return changed

    def freeze(self, forecast: OptimisticCostForecast) -> bool:
        """Freeze the pre-window forecast once, without overwriting history."""
        if self.current.frozen_forecast_cost is not None:
            return False
        self.current = replace(
            self.current,
            frozen_forecast_cost=forecast.calibrated_net_cost,
            frozen_raw_forecast_cost=forecast.raw_net_cost,
        )
        return True

    def match_retailer(
        self,
        *,
        result_date: date,
        actual_cost: float,
        zerohero_status: str,
    ) -> str:
        """Score one completed retailer day and apply feedback once."""
        if not isfinite(actual_cost):
            return "retailer_cost_invalid"
        assert self.history is not None
        for index, record in enumerate(self.history):
            if record.local_date != result_date:
                continue
            if record.frozen_forecast_cost is None:
                return "forecast_unavailable_for_day"
            status = zerohero_status.casefold()
            error = round(actual_cost - record.frozen_forecast_cost, 4)
            already_applied = record.feedback_applied
            updated = replace(
                record,
                retailer_actual_cost=round(actual_cost, 4),
                retailer_zerohero_status=status,
                forecast_error=error,
                feedback_applied=True,
            )
            self.history[index] = updated
            if not already_applied:
                self.learned_cost_bias = update_cost_bias(
                    self.learned_cost_bias,
                    forecast_cost=record.frozen_forecast_cost,
                    actual_cost=actual_cost,
                    zerohero_achieved=status == "achieved",
                )
            return "matched" if status == "achieved" else "matched_credit_not_achieved"
        return "no_matching_forecast"

    def record_for(self, result_date: date) -> ForecastDayRecord | None:
        """Return one retained comparison day."""
        assert self.history is not None
        return next(
            (record for record in self.history if record.local_date == result_date),
            None,
        )

    def to_payload(self) -> dict[str, object]:
        """Return the privacy-minimal restart payload."""
        assert self.history is not None
        return {
            "current": self.current.to_payload(),
            "export_realisation_fraction": self.export_realisation_fraction,
            "learned_cost_bias": self.learned_cost_bias,
            "history": [record.to_payload() for record in self.history],
        }


def _optional_finite(value: object) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError("value must be finite")
    return parsed


def window_overlap_fraction(
    start: datetime,
    end: datetime,
    window_start: time,
    window_end: time,
) -> float:
    """Return the fraction of one planned interval inside a daily window."""
    if end <= start or window_start == window_end:
        return 0.0
    total = (end - start).total_seconds()
    overlap = 0.0
    day = start.date() - timedelta(days=1)
    while day <= end.date():
        left = datetime.combine(day, window_start, tzinfo=start.tzinfo)
        right = datetime.combine(day, window_end, tzinfo=start.tzinfo)
        if window_end <= window_start:
            right += timedelta(days=1)
        overlap_left = max(start, left)
        overlap_right = min(end, right)
        if overlap_right > overlap_left:
            overlap += (overlap_right - overlap_left).total_seconds()
        day += timedelta(days=1)
    return min(max(overlap / total, 0.0), 1.0)


def calculate_optimistic_cost_forecast(
    *,
    measured_gross_cost: float,
    measured_export_revenue: float,
    assumed_zerohero_credit: float,
    planned_remaining_export_kwh: float,
    export_realisation_fraction: float,
    forecast_additional_export_revenue: float,
    learned_cost_bias: float,
) -> OptimisticCostForecast:
    """Forecast today's net cost without changing any control decision.

    The caller tariffs the forecast export after applying the realisation
    fraction. Keeping tariff allocation outside this helper lets the existing
    measured tariff engine remain the single source for rate tiers.
    """
    nonnegative = (
        measured_gross_cost,
        measured_export_revenue,
        assumed_zerohero_credit,
        planned_remaining_export_kwh,
        forecast_additional_export_revenue,
    )
    if (
        not all(isfinite(value) and value >= 0 for value in nonnegative)
        or not isfinite(export_realisation_fraction)
        or not 0 <= export_realisation_fraction <= 1
        or not isfinite(learned_cost_bias)
    ):
        raise ValueError("forecast inputs are invalid")
    forecast_export_kwh = planned_remaining_export_kwh * export_realisation_fraction
    raw = (
        measured_gross_cost
        - measured_export_revenue
        - assumed_zerohero_credit
        - forecast_additional_export_revenue
    )
    return OptimisticCostForecast(
        raw_net_cost=round(raw, 4),
        calibrated_net_cost=round(raw + learned_cost_bias, 4),
        assumed_zerohero_credit=round(assumed_zerohero_credit, 4),
        export_realisation_fraction=round(export_realisation_fraction, 4),
        forecast_remaining_export_kwh=round(forecast_export_kwh, 4),
        forecast_additional_export_revenue=round(
            forecast_additional_export_revenue, 4
        ),
        learned_cost_bias=round(learned_cost_bias, 4),
    )


def update_export_realisation_fraction(
    current: float,
    *,
    planned_export_kwh: float,
    realised_export_kwh: float,
    learning_rate: float = 0.2,
    maximum_daily_step: float = 0.02,
    minimum: float = 0.5,
    maximum: float = 1.0,
) -> float:
    """Move the forecast fraction slowly toward measured plan realisation."""
    values = (
        current,
        planned_export_kwh,
        realised_export_kwh,
        learning_rate,
        maximum_daily_step,
        minimum,
        maximum,
    )
    if (
        not all(isfinite(value) for value in values)
        or planned_export_kwh <= 0
        or realised_export_kwh < 0
        or not 0 < learning_rate <= 1
        or maximum_daily_step <= 0
        or not 0 <= minimum <= maximum <= 1
        or not minimum <= current <= maximum
    ):
        raise ValueError("export-realisation calibration inputs are invalid")
    observed = min(max(realised_export_kwh / planned_export_kwh, minimum), maximum)
    requested_step = (observed - current) * learning_rate
    step = min(max(requested_step, -maximum_daily_step), maximum_daily_step)
    return round(min(max(current + step, minimum), maximum), 4)


def update_cost_bias(
    current: float,
    *,
    forecast_cost: float,
    actual_cost: float,
    zerohero_achieved: bool,
    learning_rate: float = 0.2,
    maximum_daily_step: float = 0.10,
    maximum_absolute_bias: float = 2.0,
) -> float:
    """Learn a small retailer residual only from comparable successful days.

    A failed ZEROHERO day violates the forecast's explicit optimistic
    assumption. It remains visible in the scorecard but must not teach a
    permanent one-dollar bias into otherwise qualifying days.
    """
    values = (
        current,
        forecast_cost,
        actual_cost,
        learning_rate,
        maximum_daily_step,
        maximum_absolute_bias,
    )
    if (
        not all(isfinite(value) for value in values)
        or not 0 < learning_rate <= 1
        or maximum_daily_step <= 0
        or maximum_absolute_bias < 0
    ):
        raise ValueError("cost-bias calibration inputs are invalid")
    if not zerohero_achieved:
        return round(current, 4)
    requested_step = (actual_cost - forecast_cost) * learning_rate
    step = min(max(requested_step, -maximum_daily_step), maximum_daily_step)
    return round(
        min(max(current + step, -maximum_absolute_bias), maximum_absolute_bias),
        4,
    )
