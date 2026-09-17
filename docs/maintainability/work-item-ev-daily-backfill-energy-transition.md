# Work item: EV daily-backfill energy transition

## Problem

The active EV controller directly mutates daily-backfill sampling timestamps,
current feedback and delivered wall energy. This numerical reconciliation is
interleaved with Home Assistant lifecycle handling.

## Change

Move only the existing trapezoidal energy integration into a pure immutable
transition. The controller retains ready-cycle rollover, policy ownership,
session start/stop, retries, persistence and command execution.

## Invariants

- Energy is integrated only while daily backfill is active.
- Missing, stale or out-of-order samples add no energy.
- Active valid samples retain the same trapezoidal calculation.
- Inactive policy clears transient samples without changing delivered energy.
- No session, retry, persistence, command or public-contract behaviour changes.

## Verification

- Pure tests cover valid, stale, missing and inactive transitions.
- Existing daily-backfill lifecycle and persistence tests remain authoritative.
- Focused tests, full pytest, Ruff, contracts and previous-release rehearsal
  must pass before local commit.

## Rollback

Revert this commit to restore the identical calculation inside the controller.

## Completion evidence

- Focused daily-backfill lifecycle and persistence suite: `73 passed`.
- Full pytest suite: `811 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
