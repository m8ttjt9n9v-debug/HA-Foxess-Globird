# Work item: outside-window EV selector wiring

## Problem

The extracted outside-stage selector has passed pure collision tests and live
shadow comparisons, but the controller still duplicates the retained priority
branch. Phase 7.7 requires the pure selector to own that bounded decision.

## Change

Use the verified `EvStageSelection` result to construct the retained
`EvCurrentDecision`. Remove only the duplicate Charge to Full/daily-ready/
pre-free/solar/baseline selection branch from `ActiveEvController`.

All candidate calculations, session transitions, target-limit calculation,
active-control flags, reconciliation and command execution remain unchanged.

## Invariants

- Exact selected current and public decision reason are preserved.
- Charge to Full, daily-ready, pre-free/solar and baseline ordering is unchanged.
- No persistence, timing, service-call, public entity or configuration change.
- The preceding shadow-selector commit is the immediate rollback point.

## Verification

- Pure collision tests remain authoritative for branch ordering.
- Live scenarios cover every selected outside stage.
- Focused tests, full pytest, Ruff, contracts and previous-release rehearsal
  must pass before local commit.

## Rollback

Revert this commit to restore retained selection while keeping the verified
shadow selector and candidates.

## Completion evidence

- Focused selector, EV outside-window and lifecycle suite: `138 passed`.
- Full pytest suite: `789 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
