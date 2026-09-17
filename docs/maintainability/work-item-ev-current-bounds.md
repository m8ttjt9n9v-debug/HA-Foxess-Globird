# Work item: EV current bounds

## Change

Move physical-minimum fallback, selected-path ceiling and outside-window
service-headroom arithmetic into the pure EV planner. The controller retains
configuration and coherent current-feedback acquisition only.

## Invariants

- A reported zero actuator minimum falls back to one positive actuator step.
- Missing or non-positive step metadata makes the physical minimum unavailable.
- Smart-socket and Direct / EVSE paths retain their separately commissioned
  ceilings.
- A disabled service limit leaves the physical ceiling unchanged without
  requiring current feedback.
- An enabled service limit fails closed on unavailable grid or EV current.
- Valid headroom remains rounded down to the actuator step and capped by the
  physical ceiling.
- Commands, reasons, persistence and public contracts are unchanged.

## Verification

- Pure tests cover both paths, minimum fallback, disabled limit, unavailable
  feedback, headroom subtraction and step rounding.
- Existing EV service-limit and outside-window lifecycle tests remain
  authoritative.
- Focused EV planner, active-controller and daily-backfill suite: `137 passed`.
- Full suite: `840 passed`.
- Repository Ruff check passed.
- All ten architecture contracts passed.
- Previous-release rehearsal against `v0.12.26` passed.

## Rollback

Revert this commit to restore the identical branches and arithmetic in the EV
controller helpers.
