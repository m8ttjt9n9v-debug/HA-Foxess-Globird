# Work item: EV daily-backfill stop transition

## Problem

The direct-EVSE daily-backfill stop path mixes pending feedback, retry timing,
attempt bounds, ownership cleanup, save decisions and command execution inside
the Home Assistant controller.

## Change

Move the pre-execution stop decision and successful-attempt recording into pure
immutable transitions. The controller still executes the returned command via
the existing adapter and records an attempt only when that exact stop action
was issued.

## Invariants

- The first stop request remains immediate.
- Retries remain 30 seconds apart and are capped at three attempts.
- Safety Lock neither consumes an attempt nor mutates the pending state.
- Service failures retain existing adapter diagnostics and attempt semantics.
- Confirmed stopped feedback clears the pending latch, attempts, timestamp and
  outside-control ownership, and requires the same save.
- Public reasons, command order, persistence schema and entities are unchanged.

## Verification

- The pre-extraction unchanged-controller golden trace remains authoritative.
- Pure tests cover command, wait, retry, fault and confirmed cleanup states.
- Focused tests, full pytest, Ruff, contracts and previous-release rehearsal
  must pass before local commit.

## Rollback

Revert this commit to restore the identical decision branches in the controller.

## Completion evidence

- Focused transition, golden lifecycle and persistence suite: `77 passed`.
- Full pytest suite: `815 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
