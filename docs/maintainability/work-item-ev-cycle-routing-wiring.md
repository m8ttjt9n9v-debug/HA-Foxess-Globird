# Work item: EV cycle routing wiring

## Problem

The pure eligibility and policy route selectors have passed collision tables and
live shadow comparisons. The active controller still duplicates their branch
conditions.

## Change

Use the verified route results for:

- disconnected smart-socket cleanup versus ordinary connection blocking;
- connected actuator-feedback blocking;
- general-limit-only versus free-window/outside-window calculation.

Disconnected state cleanup, Charge-to-Full lifecycle handling, decision cadence,
target calculations, reconciliation and execution remain in their original
locations.

## Invariants

- Exact public reasons and disconnected cleanup behavior are preserved.
- Charge-to-Full completion still occurs before policy routing.
- Free-window cadence and transition-hold calculations retain the original
  `in_window` timing value.
- No persistence, service-call, target or public-contract changes.

## Verification

- Pure route collision tables and live route assertions remain authoritative.
- Existing disconnected, unavailable feedback, free-window, outside-window and
  general-limit lifecycle tests must remain unchanged.
- Focused tests, full pytest, Ruff, contracts and previous-release rehearsal
  must pass before local commit.

## Rollback

Revert this commit to restore retained branch conditions while keeping the
verified shadow route selectors.

## Completion evidence

- Focused cycle-routing, EV and lifecycle suite: `174 passed`.
- Full pytest suite: `805 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
