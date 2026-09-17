# Work item: smart-socket and recovery EV candidates shadow

## Problem

The smart-socket command stage and one-shot recovery already return pure plans,
but the active controller does not expose them through the common Phase 7.6
candidate contract. Eligibility, ordered command intent and recovery
persistence obligations therefore remain implicit at the orchestration seam.

## Change

Translate retained smart-socket and recovery plans into immutable shadow
`EvStageCandidate` values before the existing rehearsal or execution branches.
Disconnected socket-off and unavailable-feedback paths are included. Candidate
command intent preserves the planner's exact order.

The existing planners, stage-suppression latch, recovery state machine,
notification behavior, saves and adapter execution remain authoritative.

## Invariants

- No retry, settle, dwell, confirmation or rearm timing changes.
- No smart-socket power-switching or current formula changes.
- Safety Lock continues to avoid latching recovery state or issuing services.
- Candidate state resets each reconciliation and is not persisted or published.

## Verification

- Existing settle, ordered start, disconnected socket-off and Safety Lock
  recovery scenarios assert exact candidate reason and command order.
- Existing full recovery/restart sequence remains authoritative.
- Focused tests, full pytest, Ruff, contracts and previous-release rehearsal
  must pass before local commit.

## Rollback

Revert this shadow-only commit; runtime ownership never moved.

## Completion evidence

- Focused EV, smart-socket and lifecycle suite: `148 passed`.
- Full pytest suite: `779 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
