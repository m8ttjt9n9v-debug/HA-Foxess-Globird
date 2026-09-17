# Work item: cycle-scoped EV feedback wiring

## Problem

The EV controller historically reread mapped Home Assistant entities through
several helper methods during one reconciliation. A state transition part-way
through the cycle could therefore give policy code a mixture of old and new
feedback, while also making the read boundary difficult to audit.

## Preserved contract

- Acquire the existing EV controller lock before sampling entity feedback.
- Capture each explicitly mapped core EV entity once per reconciliation.
- Reuse that immutable snapshot for state, number, energy, actual-current and
  direct-EVSE observation helpers during that reconciliation.
- Keep helper calls outside a reconciliation as live Home Assistant reads so
  the independent driving-boundary callback and diagnostics do not see stale
  data.
- Preserve the legacy charge-to-full fallback's exact `state == "on"`
  semantics.
- Reset task-local feedback after success or failure.

## Invariants

- No service-call, current-target, charge-limit, timing or safety policy changes.
- Unknown, unavailable and empty mapped states continue to fail closed.
- Missing mappings and invalid/non-finite numeric values keep their retained
  meanings.
- Concurrent tasks cannot share a reconciliation snapshot.

## Deliberate non-goals

Smart-socket recovery/stability observations and the remaining solar-spill
source-presence checks still have their own direct reads. They will be migrated
as separately characterized seams rather than broadening this work item.

## Verification

- Adapter characterization covers unavailable, empty, numeric, unit and
  metadata behavior.
- Controller regression tests prove a core entity is read once per cycle.
- Controller regression tests prove the snapshot is cleared after both normal
  completion and an exception.
- Focused EV tests, full pytest, Ruff, repository contracts and the previous
  release rehearsal must pass before local commit.

## Rollback

Revert the wiring commit. The immutable adapter and its characterization tests
can remain without changing runtime behavior.

## Completion evidence

- Focused EV and lifecycle suite: `118 passed`.
- Full pytest suite: `773 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
