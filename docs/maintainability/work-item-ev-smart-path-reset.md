# Work item: EV smart-path reset

## Change

Move the smart-only recovery and staged-current latch reset into one immutable
path-selection decision with explicit save intent.

## Invariants

- Smart path retains both latches unchanged.
- Selecting Direct / EVSE clears either latch and requests exactly one save.
- An already-clear Direct / EVSE cycle does not request another save.
- Reset still occurs before telemetry gates, so unavailable feedback cannot
  retain a stale smart-socket fault episode.
- Commands, persistence schema and public contracts are unchanged.

## Verification

- Pure tests cover retained, cleared and already-clear paths.
- Existing recovery and staged-current lifecycle tests remain authoritative.
- Focused EV suite: `117 passed`.
- Full suite: `823 passed`.
- Repository Ruff check passed.
- All nine architecture contracts passed.
- Previous-release rehearsal against `v0.12.26` passed.

## Rollback

Revert this commit to restore the identical reset condition in the controller.
