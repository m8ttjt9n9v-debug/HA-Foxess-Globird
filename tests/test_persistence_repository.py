"""Typed Store repository characterization tests."""

from __future__ import annotations

from datetime import date, datetime
from typing import cast
from zoneinfo import ZoneInfo

from homeassistant.helpers.storage import Store

from custom_components.home_energy_orchestrator.persistence import (
    TypedStoreRepository,
    TypedValueStoreRepository,
)
from custom_components.home_energy_orchestrator.planner.daily_meter import (
    DailyImportAccumulator,
)
from custom_components.home_energy_orchestrator.planner.forecast import (
    ForecastFeedbackState,
)

TZ = ZoneInfo("Australia/Sydney")
NOW = datetime(2026, 9, 17, 12, tzinfo=TZ)


class FakeStore:
    """Minimal in-memory Store boundary for repository tests."""

    def __init__(self, payload: object = None) -> None:
        self.payload = payload

    async def async_load(self) -> object:
        return self.payload

    async def async_save(self, payload: dict[str, object]) -> None:
        self.payload = payload


def repository(payload: object = None) -> tuple[TypedStoreRepository, FakeStore]:
    store = FakeStore(payload)
    return TypedStoreRepository(cast(Store[dict[str, object]], store)), store


async def test_repository_restores_existing_payload_without_changing_shape() -> None:
    source = DailyImportAccumulator()
    source.observe(2.0, NOW)
    source.observe(2.0, NOW.replace(minute=30))
    repo, _store = repository(source.to_payload())
    restored = DailyImportAccumulator()

    assert await repo.async_restore(restored, NOW.replace(minute=31)) == "restored"
    assert restored.imported_kwh == source.imported_kwh
    assert restored.last_import_kw == source.last_import_kw


async def test_repository_missing_payload_uses_domain_fallback() -> None:
    repo, _store = repository()
    restored = DailyImportAccumulator(imported_kwh=99.0)

    assert await repo.async_restore(restored, NOW) == "missing"
    assert restored.imported_kwh == 0.0
    assert restored.local_date == NOW.date()


async def test_repository_invalid_outer_payload_fails_safely() -> None:
    repo, _store = repository(["not", "a", "mapping"])
    restored = DailyImportAccumulator(imported_kwh=99.0)

    assert await repo.async_restore(restored, NOW) == "invalid"
    assert restored.imported_kwh == 0.0
    assert restored.local_date == NOW.date()


async def test_repository_saves_exact_existing_payload() -> None:
    repo, store = repository()
    state = DailyImportAccumulator()
    state.observe(3.0, NOW)

    await repo.async_save(state)

    assert store.payload == state.to_payload()


def forecast_repository(
    payload: object = None,
) -> tuple[TypedValueStoreRepository[ForecastFeedbackState], FakeStore]:
    store = FakeStore(payload)
    repository = TypedValueStoreRepository(
        cast(Store[dict[str, object]], store),
        decode=lambda value: ForecastFeedbackState.restore(
            value,
            today=date(2026, 9, 17),
        ),
        encode=ForecastFeedbackState.to_payload,
    )
    return repository, store


async def test_value_repository_restores_and_saves_existing_forecast_payload() -> None:
    state = ForecastFeedbackState.restore(None, today=date(2026, 9, 17))
    state.observe_export(planned_total_kwh=20.0, realised_kwh=10.0)
    repo, store = forecast_repository(state.to_payload())

    restored = await repo.async_load()
    await repo.async_save(restored)

    assert restored.to_payload() == state.to_payload()
    assert store.payload == state.to_payload()


async def test_value_repository_invalid_outer_payload_uses_forecast_fallback() -> None:
    repo, _store = forecast_repository(["not", "a", "mapping"])

    restored = await repo.async_load()

    assert restored.current.local_date == date(2026, 9, 17)
    assert restored.export_realisation_fraction == 0.75
    assert repo.last_restore_status == "invalid"
