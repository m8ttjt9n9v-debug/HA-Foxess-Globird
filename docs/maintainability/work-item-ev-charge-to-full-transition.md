# Work item: EV Charge-to-Full transition

## Change

Move the paid-grid override timer and stop-latch lifecycle into one immutable
transition covering start, continuation, full-SoC completion, timeout and
manual cancellation. The controller retains the config-entry mutation.

## Invariants

- Start time is latched once and survives ordinary reconciliation.
- Full SoC and the exact timeout boundary clear the request configuration.
- Manual cancellation clears the timer without another config write.
- Completion or cancellation creates a fresh stop obligation only when no
  protected baseline is configured.
- Command execution, persistence schema and public contracts are unchanged.

## Verification

- Pure tests cover start, full SoC, timeout, baseline and manual cancellation.
- Existing full-SoC end-to-end stop trace remains authoritative.
- Full pytest, Ruff, contracts and previous-release rehearsal must pass before
  local commit.

## Rollback

Revert this commit to restore the identical lifecycle branches in the facade.

## Completion evidence

- Focused pure and end-to-end Charge-to-Full suite: `4 passed`.
- Full pytest suite: `821 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
