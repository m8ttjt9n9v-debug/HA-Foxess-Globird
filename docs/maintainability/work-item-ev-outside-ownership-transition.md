# Work item: EV outside-window ownership transition

## Change

Move outside-window target ownership, retained control ownership and the
carried free-window charge stop latch into one immutable transition.

## Invariants

- Charge to Full, active daily backfill, pre-free charging and solar spill
  retain target ownership.
- The mandatory connected baseline retains current ownership independently of
  target ownership.
- An existing daily-backfill stop obligation remains authoritative.
- A still-charging free-window target creates the same fresh bounded stop
  obligation when no outside policy takes ownership.
- Existing outside control remains retained until confirmed feedback releases
  it through direct-EVSE reconciliation.
- Commands, priority, reasons, retry bounds, persistence and public contracts
  are unchanged.

## Verification

- Pure tests cover active target, baseline, retained stop, carried charge and
  retained control branches.
- Existing outside-window controller and stop-retry traces remain authoritative.
- Focused outside-state, active-controller and daily-backfill suite: `84 passed`.
- Full suite: `827 passed`.
- Repository Ruff check passed.
- All nine architecture contracts passed.
- Previous-release rehearsal against `v0.12.26` passed.

## Rollback

Revert this commit to restore the identical ownership branch in the active
controller.
