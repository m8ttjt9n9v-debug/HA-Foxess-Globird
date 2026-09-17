# Work item: general-limit EV candidate shadow

## Problem

The outside-window learned general charge limit is a distinct EV stage, but its
eligibility, target and command intent remain implicit inside an async method
that also performs writes.

## Change

Populate the immutable `EvStageCandidate` contract in shadow for every retained
general-limit exit: rejected, already confirmed, awaiting prior feedback, and
requiring a charge-limit command. The retained method still owns calculation,
deduplication, rehearsal handling and execution.

## Invariants

- No learned-limit, headroom, rounding or charge-limit formula changes.
- The existing write fingerprint remains authoritative.
- Rehearsal and live execution retain their exact reasons and service behavior.
- Shadow state resets at the start of every reconciliation and is never
  persisted or published.

## Verification

- Existing two-cycle feedback-deduplication and command scenarios assert exact
  candidate parity with retained target, reason and command intent.
- Focused tests, full pytest, Ruff, contracts and previous-release rehearsal
  must pass before local commit.

## Rollback

Revert this shadow-only commit; runtime ownership never moved.

## Completion evidence

- Focused EV learning and lifecycle suite: `104 passed`.
- Full pytest suite: `779 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
