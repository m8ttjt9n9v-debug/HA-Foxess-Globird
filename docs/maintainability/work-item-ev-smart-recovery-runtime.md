# Work item: EV smart-recovery runtime decision

## Change

Move the controller's smart-recovery activity classification, state-change
classification and save intent into one immutable runtime decision.

## Invariants

- The same seven in-progress recovery phases retain stage ownership.
- Recovery commands, reasons and state-machine transitions are unchanged.
- Changed recovery state requests exactly one save.
- Unchanged state does not request an additional save.
- Safety Lock still returns before applying or saving a recovery transition.
- Public candidate fields and persistence-transition strings are unchanged.

## Verification

- Pure tests cover active changed, active unchanged and idle unchanged results.
- Existing smart-recovery lifecycle tests remain authoritative.
- Focused EV suite: `118 passed`.
- Full suite: `824 passed`.
- Repository Ruff check passed.
- All nine architecture contracts passed.
- Previous-release rehearsal against `v0.12.26` passed.

## Rollback

Revert this commit to restore activity and save classification in the active
controller.
