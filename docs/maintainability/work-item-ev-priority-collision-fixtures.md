# Work item: EV priority collision fixtures

## Problem

Single-branch tests do not prove priority when several safety or charging
conditions are true at once. Phase 7.7 requires golden collision evidence
before a broader selector can replace controller branch order.

## Frozen order

Free-window current policy:

1. service-limit correction;
2. Charge to Full;
3. EV-before-house priority;
4. FoxESS settling hold;
5. telemetry fallback;
6. EV-feedback hold/deadband/house-battery alignment.

Outside-window policy retains Charge to Full as the explicit paid exception to
the automatic battery-floor stop. Separately, existing FoxESS tests retain EV
export protection both before a new export and during an active export.

## Change

Add deterministic collisions only. No production code or ownership changes.

## Verification

- Service overrun collides with Charge to Full and EV priority.
- Charge to Full collides with EV priority and settling.
- EV priority collides with settling.
- Settling collides with invalid grid telemetry.
- Invalid grid telemetry collides with missing EV-current feedback.
- Charge to Full collides with house-battery floor outside the free window.
- Existing new-session and active-session EV export-protection fixtures remain
  part of the full suite.

## Rollback

Tests and evidence only; revert this commit without runtime effect.

## Completion evidence

- Focused EV, FoxESS export-protection and lifecycle suite: `197 passed`.
- Full pytest suite: `795 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
