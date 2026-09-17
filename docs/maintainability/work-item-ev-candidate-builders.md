# Work item: pure EV candidate builders

## Problem

The Phase 7.6 shadow candidates proved parity, but their construction remained
spread through `ActiveEvController`. That temporarily increased facade size and
would make the later pure priority selector depend on controller internals.

## Change

Move candidate construction into side-effect-free planner helpers. The outside
builder receives only immutable primitive results from the retained stage
calculations and returns all five candidates without selecting among them.
Common accepted and rejected builders cover free-window, general-limit,
smart-socket, recovery and battery-floor descriptions.

The active controller still computes every input, owns every state transition,
selects every stage and executes every command.

## Invariants

- Candidate order and all shadow fields remain identical.
- Simultaneously eligible stages remain visible independently.
- Disabled and unavailable stages remain distinguishable.
- No runtime policy, persistence, public entity or configuration changes.

## Verification

- Pure unit tests cover immutability, rejection, simultaneous eligibility,
  stable ordering, targets, persistence obligations and disabled/unavailable
  distinctions.
- Existing controller parity assertions remain unchanged.
- Focused tests, full pytest, Ruff, contracts and previous-release rehearsal
  must pass before local commit.

## Rollback

Revert this refactor; shadow candidate behavior has no runtime ownership.

## Completion evidence

- Focused candidate, EV outside-window and lifecycle suite: `131 passed`.
- Full pytest suite: `782 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
