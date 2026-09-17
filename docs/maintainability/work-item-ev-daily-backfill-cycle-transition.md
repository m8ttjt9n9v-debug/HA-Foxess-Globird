# Work item: EV daily-backfill cycle transition

## Problem

Ready-cycle rollover directly resets nine controller fields and conditionally
creates a stop obligation when an active backfill crosses into a new cycle.
That lifecycle rule is difficult to review while embedded in the facade.

## Change

Represent the rollover inputs as immutable cycle state and return the exact next
state from a pure transition. The controller remains responsible for obtaining
the ready time and applying the returned fields.

## Invariants

- Repeated evaluation of the same ready cycle is a no-op.
- A new cycle resets energy, transient samples and session targets.
- An active old cycle creates a fresh stop obligation with zero attempts.
- An inactive old cycle retains any existing stop obligation and retry state.
- Persistence, policy selection, command execution and public contracts remain
  unchanged.

## Verification

- Pure tests cover active rollover, retained inactive stop state and same-cycle
  identity.
- Existing daily-backfill lifecycle and persistence tests remain authoritative.
- Focused tests, full pytest, Ruff, contracts and previous-release rehearsal
  must pass before local commit.

## Rollback

Revert this commit to restore the identical field resets inside the controller.

## Completion evidence

- Focused cycle, lifecycle and persistence suite: `75 passed`.
- Full pytest suite: `813 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
