"""Collection quality is independent from the unchanged protected-budget model."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.home_energy_orchestrator.planner.learning import (
    DailyDemandCycleSampler,
    DemandCycleSample,
    DemandCycleSampler,
    DemandHistory,
    DemandPersistenceState,
    HouseLearningObservation,
    advance_house_learning,
)


def _feed(
    sampler: DemandCycleSampler,
    begin: datetime,
    finish: datetime,
    power: float | None = 1.0,
) -> list[DemandCycleSample]:
    """Feed five-minute observations in real elapsed time, including DST folds."""
    instant = begin.astimezone(UTC)
    samples = []
    while instant <= finish.astimezone(UTC):
        sample = sampler.observe(instant.astimezone(begin.tzinfo), power)
        if sample is not None:
            samples.append(sample)
        instant += timedelta(minutes=5)
    return samples


def test_missing_ev_power_during_entire_excluded_window_is_not_a_gap() -> None:
    begin = datetime(2026, 9, 1, 12, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    _feed(sampler, begin, begin + timedelta(hours=3), None)
    samples = _feed(
        sampler, begin + timedelta(hours=3, minutes=5), begin + timedelta(days=1)
    )
    # No reading at the first protected instant leaves its following five
    # minutes genuinely unknown. A valid boundary reading fixes that case.
    assert samples == []
    assert sampler.last_cycle["missing_seconds"] == 300

    sampler = DemandCycleSampler(time(12), time(15))
    _feed(sampler, begin, begin + timedelta(hours=2, minutes=55), None)
    samples = _feed(sampler, begin + timedelta(hours=3), begin + timedelta(days=1))
    assert len(samples) == 1
    assert samples[0].energy_kwh == pytest.approx(21)
    assert sampler.last_cycle["observed_seconds"] == 21 * 3600
    assert sampler.last_cycle["missing_seconds"] == 0


def test_an_unsampled_free_only_gap_does_not_destroy_a_cycle() -> None:
    begin = datetime(2026, 9, 1, 12, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    sampler.observe(begin, None)
    samples = _feed(sampler, begin + timedelta(hours=3), begin + timedelta(days=1))
    assert len(samples) == 1
    assert samples[0].energy_kwh == pytest.approx(21)


def test_midnight_spanning_free_window_has_no_requirement_for_excluded_power() -> None:
    begin = datetime(2026, 9, 1, 23, tzinfo=UTC)
    sampler = DemandCycleSampler(time(22), time(2))
    sampler.observe(begin, None)
    samples = _feed(sampler, begin + timedelta(hours=3), begin + timedelta(hours=23))
    assert len(samples) == 1
    assert samples[0].energy_kwh == pytest.approx(20)


def test_duplicate_or_older_observation_cannot_erase_or_renew_progress() -> None:
    begin = datetime(2026, 9, 1, 12, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    _feed(sampler, begin, begin + timedelta(hours=4))
    payload = sampler.to_payload()
    sampler.observe(begin + timedelta(hours=4), None)
    sampler.observe(begin + timedelta(hours=3), 20)
    assert sampler.to_payload() == payload


def test_first_observation_inside_free_window_establishes_complete_protected_start() -> None:
    begin = datetime(2026, 9, 1, 13, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    sampler.observe(begin, None)
    samples = _feed(sampler, begin + timedelta(hours=2), begin + timedelta(hours=23))
    assert len(samples) == 1
    assert samples[0].energy_kwh == pytest.approx(21)


@pytest.mark.parametrize("explicit_missing", [False, True])
def test_protected_gap_preserves_known_energy_but_never_admits_partial_cycle(
    explicit_missing: bool,
) -> None:
    begin = datetime(2026, 9, 1, 12, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    _feed(sampler, begin, begin + timedelta(hours=8))
    known = sampler.known_energy_kwh
    assert known == pytest.approx(5)
    if explicit_missing:
        # Existing evidence covers the interval ending at this instant;
        # unavailable evidence applies to the following protected interval.
        sampler.observe(begin + timedelta(hours=8, minutes=5), None)
        _feed(sampler, begin + timedelta(hours=8, minutes=10),
              begin + timedelta(hours=8, minutes=20), None)
    sampler.observe(begin + timedelta(hours=8, minutes=25), 1)
    assert sampler.known_energy_kwh >= known
    assert sampler.missing_seconds > 0
    assert sampler.missing_reason in {"observation_gap", "missing_power"}
    samples = _feed(sampler, begin + timedelta(hours=8, minutes=30),
                    begin + timedelta(days=1))
    assert samples == []
    assert sampler.last_cycle["complete"] is False
    assert sampler.last_cycle["energy_kwh"] > 20
    assert sampler.last_cycle["missing_seconds"] > 0
    # The next cycle can recover; missingness does not permanently poison it.
    samples = _feed(sampler, begin + timedelta(days=1, minutes=5),
                    begin + timedelta(days=2))
    assert len(samples) == 1
    assert samples[0].energy_kwh == pytest.approx(21)


def test_restart_during_free_only_gap_keeps_cycle_without_renewing_power_clock() -> None:
    begin = datetime(2026, 9, 1, 12, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    sampler.observe(begin, None)
    payload = sampler.to_payload()
    restored = DemandCycleSampler(time(12), time(15))
    restored.restore(payload, begin + timedelta(hours=2))
    assert restored.to_payload() == payload
    restored.observe(begin + timedelta(hours=2), None)
    samples = _feed(restored, begin + timedelta(hours=3), begin + timedelta(days=1))
    assert len(samples) == 1
    assert samples[0].energy_kwh == pytest.approx(21)


def test_restart_across_protected_gap_keeps_partial_energy_and_records_missingness() -> None:
    begin = datetime(2026, 9, 1, 12, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    _feed(sampler, begin, begin + timedelta(hours=8))
    payload = sampler.to_payload()
    restored = DemandCycleSampler(time(12), time(15))
    restored.restore(payload, begin + timedelta(hours=8, minutes=20))
    restored.observe(begin + timedelta(hours=8, minutes=20), 1)
    assert restored.known_energy_kwh == pytest.approx(5 + 1 / 6)
    assert restored.missing_seconds == 600
    assert _feed(restored, begin + timedelta(hours=8, minutes=25),
                 begin + timedelta(days=1)) == []


def test_partial_cycle_remains_incomplete_for_new_reader_and_legacy_rollback() -> None:
    begin = datetime(2026, 9, 1, 12, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    _feed(sampler, begin, begin + timedelta(hours=8))
    resumed_at = begin + timedelta(hours=8, minutes=20)
    sampler.observe(resumed_at, 1)
    payload = sampler.to_payload()
    assert payload["cycle_started"] is False
    assert payload["coverage_cycle_started"] is True

    current_reader = DemandCycleSampler(time(12), time(15))
    current_reader.restore(payload, resumed_at)
    assert current_reader.cycle_started
    assert current_reader.known_energy_kwh == pytest.approx(5 + 1 / 6)
    assert current_reader.missing_seconds == 600

    # Model an old reader's four-field view, which does not know the additive
    # coverage fields. Its admission flag must remain withdrawn through the
    # following boundary even with entirely healthy new observations.
    legacy_payload = {key: payload[key] for key in (
        "last_at", "last_power_kw", "cycle_started", "cycle_energy_kwh"
    )}
    legacy_reader = DemandCycleSampler(time(12), time(15))
    legacy_reader.restore(legacy_payload, resumed_at)
    assert not legacy_reader.cycle_started
    assert _feed(legacy_reader, resumed_at + timedelta(minutes=5),
                 begin + timedelta(days=1)) == []


@pytest.mark.parametrize("flag", ["true", 1, None, []])
def test_malformed_coverage_cycle_flag_does_not_restore_progress(flag: object) -> None:
    at = datetime(2026, 9, 1, 12, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    sampler.observe(at, 1)
    payload = sampler.to_payload()
    payload["coverage_cycle_started"] = flag
    restored = DemandCycleSampler(time(12), time(15))
    restored.restore(payload, at)
    assert restored.to_payload() is None


def test_brief_missing_reading_retains_existing_bounded_left_method() -> None:
    begin = datetime(2026, 9, 1, 15, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    sampler.observe(begin - timedelta(minutes=5), 4)
    sampler.observe(begin, 4)
    sampler.observe(begin + timedelta(seconds=30), None)
    assert sampler.missing_seconds == 0
    assert sampler.known_energy_kwh == pytest.approx(4 * 30 / 3600)
    sampler.observe(begin + timedelta(minutes=1), 4)
    assert sampler.known_energy_kwh == pytest.approx(4 / 60)
    assert sampler.missing_seconds == 0
    samples = _feed(sampler, begin + timedelta(minutes=5), begin + timedelta(hours=21), 4)
    assert len(samples) == 1
    assert samples[0].energy_kwh == pytest.approx(84)


def test_none_observations_never_renew_the_original_qualified_clock() -> None:
    begin = datetime(2026, 9, 1, 15, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    sampler.observe(begin - timedelta(minutes=5), 4)
    sampler.observe(begin, 4)
    for minutes in range(1, 16):
        sampler.observe(begin + timedelta(minutes=minutes), None)
        payload = sampler.to_payload()
        assert payload["last_qualified_at"] == begin.isoformat()
        assert payload["last_qualified_power_kw"] == 4
        assert payload["last_power_kw"] is None
    assert sampler.known_energy_kwh == pytest.approx(4 * 10 / 60)
    assert sampler.missing_seconds == 300


@pytest.mark.parametrize("extra_seconds", [-0.001, 0, 0.001])
def test_hold_expires_at_original_max_gap_without_an_added_delay(extra_seconds: float) -> None:
    begin = datetime(2026, 9, 1, 15, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    sampler.observe(begin - timedelta(minutes=5), 1)
    sampler.observe(begin, 1)
    sampler.observe(begin + timedelta(minutes=10, seconds=extra_seconds), None)
    assert sampler.known_energy_kwh == pytest.approx(min(600 + extra_seconds, 600) / 3600)
    assert sampler.missing_seconds == pytest.approx(max(extra_seconds, 0))


def test_restart_during_a_brief_missing_reading_does_not_extend_the_hold() -> None:
    begin = datetime(2026, 9, 1, 15, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    sampler.observe(begin - timedelta(minutes=5), 1)
    sampler.observe(begin, 1)
    sampler.observe(begin + timedelta(minutes=5), None)
    payload = sampler.to_payload()
    restored = DemandCycleSampler(time(12), time(15))
    restored.restore(payload, begin + timedelta(minutes=8))
    restored.observe(begin + timedelta(minutes=12), None)
    assert restored.known_energy_kwh == pytest.approx(10 / 60)
    assert restored.missing_seconds == 120
    assert restored.to_payload()["last_qualified_at"] == begin.isoformat()


@pytest.mark.parametrize("seconds_before_boundary,complete", [
    (599, True), (600, True), (601, False),
])
def test_free_boundary_can_close_protected_energy_covered_until_its_original_expiry(
    seconds_before_boundary: int, complete: bool,
) -> None:
    begin = datetime(2026, 9, 1, 12, tzinfo=UTC)
    finish = begin + timedelta(days=1)
    sampler = DemandCycleSampler(time(12), time(15))
    _feed(sampler, begin, finish - timedelta(minutes=15))
    sampler.observe(finish - timedelta(seconds=seconds_before_boundary), 1)
    sample = sampler.observe(finish, None)
    assert (sample is not None) is complete
    assert sampler.last_cycle["missing_seconds"] == max(seconds_before_boundary - 600, 0)
    if sample is not None:
        assert sample.energy_kwh == pytest.approx(21)


@pytest.mark.parametrize("fields", [
    {"last_qualified_at": "not-a-clock"},
    {"last_qualified_at": "2026-09-01T12:00:00"},
    {"last_qualified_at": "2026-09-01T12:01:00+00:00"},
    {"last_qualified_at": None},
    {"last_qualified_power_kw": None},
    {"last_qualified_power_kw": True},
    {"last_qualified_power_kw": float("nan")},
    {"last_qualified_power_kw": -1},
    {"last_qualified_power_kw": 2},
])
def test_malformed_qualified_clocks_cannot_extend_or_create_learning_evidence(
    fields: dict[str, object],
) -> None:
    at = datetime(2026, 9, 1, 12, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    sampler.observe(at, 1)
    payload = sampler.to_payload()
    payload.update(fields)
    restored = DemandCycleSampler(time(12), time(15))
    restored.restore(payload, at)
    assert restored.to_payload() is None


@pytest.mark.parametrize("field", ["last_qualified_at", "last_qualified_power_kw"])
def test_partially_present_new_clock_fields_are_not_mistaken_for_legacy(field: str) -> None:
    at = datetime(2026, 9, 1, 12, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    sampler.observe(at, 1)
    payload = sampler.to_payload()
    del payload[field]
    restored = DemandCycleSampler(time(12), time(15))
    restored.restore(payload, at)
    assert restored.to_payload() is None


@pytest.mark.parametrize("begin,expected", [
    (datetime(2026, 4, 4, 12, tzinfo=ZoneInfo("Australia/Sydney")), 22),
    (datetime(2026, 10, 3, 12, tzinfo=ZoneInfo("Australia/Sydney")), 20),
])
def test_local_cycle_boundaries_use_actual_elapsed_energy_over_dst(
    begin: datetime, expected: float,
) -> None:
    sampler = DemandCycleSampler(time(12), time(15))
    samples = _feed(sampler, begin, begin + timedelta(days=1))
    assert len(samples) == 1
    assert samples[0].energy_kwh == pytest.approx(expected)
    assert sampler.last_cycle["observed_seconds"] == expected * 3600


def test_dst_fold_does_not_merge_distinct_equal_wall_clock_instants() -> None:
    zone = ZoneInfo("Australia/Sydney")
    sampler = DemandCycleSampler(time(12), time(15), max_gap=timedelta(days=2))
    sampler.observe(datetime(2026, 4, 4, 12, tzinfo=zone), 1)
    sampler.observe(datetime(2026, 4, 5, 2, 30, tzinfo=zone, fold=0), 1)
    before = sampler.known_energy_kwh
    sampler.observe(datetime(2026, 4, 5, 2, 30, tzinfo=zone, fold=1), 1)
    assert sampler.known_energy_kwh == pytest.approx(before + 1)


def test_restored_offset_uses_site_zone_for_later_dst_boundaries() -> None:
    zone = ZoneInfo("Australia/Sydney")
    begin = datetime(2026, 10, 3, 12, tzinfo=zone)
    sampler = DemandCycleSampler(time(12), time(15), max_gap=timedelta(days=2))
    sampler.observe(begin, 1)
    restored = DemandCycleSampler(time(12), time(15), max_gap=timedelta(days=2))
    restored.restore(sampler.to_payload(), begin + timedelta(days=1))
    sample = restored.observe(begin + timedelta(days=1), 1)
    assert sample is not None
    assert sample.energy_kwh == pytest.approx(20)


def test_heater_cycle_can_complete_while_base_power_is_unavailable() -> None:
    begin = datetime(2026, 9, 1, 12, tzinfo=UTC)
    base = DemandCycleSampler(time(12), time(15))
    heater = DailyDemandCycleSampler(time(12), max_gap=timedelta(days=2))
    base_history = DemandHistory([])
    heater_history = DemandHistory([])
    for at in (begin, begin + timedelta(days=1)):
        result = advance_house_learning(
            demand_sampler=base, heater_sampler=heater,
            demand_history=base_history, heater_history=heater_history,
            observation=HouseLearningObservation(at, None, 2), last_saved_at=begin,
        )
    assert result.accepted
    assert result.heater_cycle_completed
    assert not result.base_cycle_completed
    assert base_history.samples == []
    assert heater_history.samples[0].energy_kwh == pytest.approx(48)


def test_valid_legacy_progress_payload_remains_usable() -> None:
    begin = datetime(2026, 9, 1, 15, tzinfo=UTC)
    legacy = {
        "last_at": begin.isoformat(), "last_power_kw": 1,
        "cycle_started": True, "cycle_energy_kwh": 0,
    }
    sampler = DemandCycleSampler(time(12), time(15))
    sampler.restore(legacy, begin + timedelta(minutes=1))
    samples = _feed(sampler, begin + timedelta(minutes=5), begin + timedelta(hours=21))
    assert len(samples) == 1
    assert samples[0].energy_kwh == pytest.approx(21)


@pytest.mark.parametrize("field,value", [
    ("last_at", "bad"), ("last_at", "2026-09-03T12:00:00+00:00"),
    ("last_power_kw", float("nan")), ("last_power_kw", True),
    ("cycle_started", "false"), ("cycle_energy_kwh", -1),
    ("cycle_energy_kwh", True), ("cycle_observed_seconds", False),
    ("cycle_observed_seconds", float("inf")), ("cycle_missing_seconds", -1),
    ("cycle_missing_seconds", 300),
])
def test_malformed_progress_never_restores_a_measured_cycle(field: str, value: object) -> None:
    begin = datetime(2026, 9, 1, 12, tzinfo=UTC)
    sampler = DemandCycleSampler(time(12), time(15))
    sampler.observe(begin, 1)
    payload = sampler.to_payload()
    payload[field] = value
    restored = DemandCycleSampler(time(12), time(15))
    restored.restore(payload, begin + timedelta(minutes=1))
    assert restored.to_payload() is None


def test_history_deduplicates_replayed_cycle_with_a_different_offset() -> None:
    at = datetime(2026, 9, 1, 12, tzinfo=UTC)
    history = DemandHistory([])
    history.add(at, 5)
    history.add(at.astimezone(ZoneInfo("Australia/Sydney")), 50)
    assert len(history.samples) == 1
    assert history.samples[0].energy_kwh == 5


def test_history_prunes_expired_samples_without_a_new_completed_cycle() -> None:
    at = datetime(2026, 9, 1, 12, tzinfo=UTC)
    history = DemandHistory([DemandCycleSample(at + timedelta(days=i), 5) for i in range(7)])
    assert history.select(9, now=at + timedelta(days=7)).model == "p80"
    result = history.select(9, now=at + timedelta(days=50))
    assert result.model == "fallback"
    assert result.sample_count == 0


def test_raw_progress_and_binding_are_optional_additive_persistence() -> None:
    at = datetime(2026, 9, 1, 12, tzinfo=UTC)
    raw = DemandCycleSampler(time(12), time(15))
    raw.observe(at, 3)
    binding = ("sensor.house", "includes_ev", "12:00:00", "15:00:00")
    state = DemandPersistenceState.capture(
        DemandHistory([]), DemandHistory([]), None, None,
        raw_house_sampler=raw, source_binding=binding,
    )
    payload = state.to_payload()
    restored = DemandPersistenceState.restore(payload, at)
    assert restored.source_binding == binding
    assert restored.raw_house_in_progress_cycle == raw.to_payload()
    assert restored.to_payload() == payload
    legacy = DemandPersistenceState.restore({"samples": []}, at)
    assert legacy.source_binding is None
    assert not legacy.include_raw_house_in_progress_cycle


@pytest.mark.parametrize("binding", [[], "bad", ["sensor.house", None], [False], [""]])
def test_malformed_binding_is_not_coerced_into_source_authority(binding: object) -> None:
    at = datetime(2026, 9, 1, tzinfo=UTC)
    restored = DemandPersistenceState.restore(
        {
            "source_binding": binding,
            "samples": [{"observed_at": at.isoformat(), "energy_kwh": 5}],
            "in_progress_cycle": {"pending": "base"},
            "heater_in_progress_cycle": {"pending": "heater"},
            "raw_house_in_progress_cycle": {"pending": "raw"},
        }, at,
    )
    assert restored.source_binding is None
    assert len(restored.demand_history.samples) == 1
    assert restored.in_progress_cycle is None
    assert restored.heater_in_progress_cycle is None
    assert restored.raw_house_in_progress_cycle is None


def test_heater_elapsed_energy_also_preserves_both_dst_fold_instants() -> None:
    zone = ZoneInfo("Australia/Sydney")
    sampler = DailyDemandCycleSampler(time(12), max_gap=timedelta(days=2))
    sampler.observe(datetime(2026, 4, 4, 12, tzinfo=zone), 1)
    sampler.observe(datetime(2026, 4, 5, 2, 30, tzinfo=zone, fold=0), 1)
    before = sampler.to_payload()["cycle_energy_kwh"]
    sampler.observe(datetime(2026, 4, 5, 2, 30, tzinfo=zone, fold=1), 1)
    assert sampler.to_payload()["cycle_energy_kwh"] == pytest.approx(before + 1)
