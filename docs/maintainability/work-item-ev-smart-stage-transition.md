# Work item: EV smart-socket stage transition

## Problem

The active EV controller mutates the pending smart-socket current target and
hold timestamp while filtering a command plan. This mixes reconciliation state
with the Home Assistant facade and makes exact retry behaviour harder to test.

## Change

Represent the transient staged-current hold as an immutable state and pure
transition. The controller supplies the current state and timing configuration,
then applies the returned next state and filtered command plan.

## Invariants

- The first staged-current write remains permitted immediately.
- Repeated writes remain suppressed until the five-minute retry boundary.
- The public awaiting and not-confirmed reasons retain their exact timing.
- A socket-on command clears the hold; unrelated plans retain it.
- The hold remains transient and is not added to persisted storage.
- Command ordering, service calls, save cadence and public contracts do not
  change.

## Verification

- Pure boundary tests cover first write, confirmation timeout, retry and reset.
- Existing smart-socket command-order and lifecycle tests remain unchanged.
- Focused tests, full pytest, Ruff, contracts and previous-release rehearsal
  must pass before local commit.

## Rollback

Revert this commit to return the transition mutation to the controller without
changing persisted state or public contracts.

## Completion evidence

- Focused pure-boundary and live EV lifecycle suite: `114 passed`.
- Full pytest suite: `808 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
