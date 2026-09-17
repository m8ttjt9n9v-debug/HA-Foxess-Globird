# Work item: free-window EV candidate shadow

## Problem

Phase 7.6 requires each retained EV stage to expose eligibility, reason, target,
command intent and persistence transition before priority selection is moved.
The current controller stores only mutable target and diagnostic fields.

## Change

Introduce the immutable `EvStageCandidate` contract and populate it in shadow
for the existing free-window calculation. The retained `_calculate_target`
method still performs every formula, mutation and branch. The candidate neither
selects policy nor executes commands.

Successful candidates mirror the retained current target, charge-limit target
and decision phase. Rejected candidates mirror the exact existing public
reason and have no command intent. The free-window stage has no persistence
transition of its own.

## Invariants

- No current, SoC, allowance, service-headroom or charge-limit formula changes.
- Existing branch order, timers, reconciliation and service calls remain owned
  by `ActiveEvController`.
- Candidate construction is immutable and side-effect-free.
- No public entity, configuration or persistence schema changes.

## Verification

- A real successful reconciliation must exactly match candidate and retained
  target/phase fields.
- A missing-site-snapshot rejection must exactly match the retained boolean and
  public reason.
- Existing free-window, allowance, Charge to Full, service-overrun and command
  tests remain authoritative.
- Focused tests, full pytest, Ruff, contracts and previous-release rehearsal
  must pass before local commit.

## Rollback

Revert this shadow-only commit; runtime ownership never moved.

## Completion evidence

- Focused EV, planner and lifecycle suite: `148 passed`.
- Full pytest suite: `779 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
