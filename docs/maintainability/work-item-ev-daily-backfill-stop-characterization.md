# Work item: EV daily-backfill stop characterization

## Purpose

Freeze the retained direct-EVSE stop-feedback trace before extracting its
pending state, bounded attempts and save decisions in Phase 7.8.

## Frozen trace

- The first stop command is immediate.
- Feedback is awaited without a repeated write for 30 seconds.
- Stop is attempted at most three times, at 30-second intervals.
- Exhaustion publishes `daily_backfill_stop_fault_maximum_attempts`.
- Confirmed stopped feedback clears the obligation, attempts, timestamp and
  outside-control ownership, then publishes `daily_backfill_stopped`.

No production code changes in this work item.

## Completion evidence

- Focused unchanged-controller trace: `2 passed`.
- Full pytest suite: `814 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
