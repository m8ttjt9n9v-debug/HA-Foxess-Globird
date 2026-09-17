# Work item: EV disconnected cleanup transition

## Change

Move disconnected outside-session cleanup into one immutable transition. It
clears daily, pre-free, Charge-to-Full timer and ownership state and returns the
retained solar-spill diagnostic.

The controller still performs the existing config-entry cleanup and the
separate smart-socket power action at their Home Assistant boundaries.

## Invariants

- No disconnected cleanup issues a new EV command.
- Charge-to-Full config is cleared only when its timer was active.
- Smart-socket cleanup order and reasons remain unchanged.
- Energy totals and ready-cycle identity are retained while session ownership
  and stop retries are cleared.
- Persistence schema and public contracts remain unchanged.

## Verification

- Pure tests cover enabled/disabled solar diagnostics and config-write intent.
- The pre-extraction direct and smart-socket traces remain authoritative.
- Full pytest, Ruff, contracts and previous-release rehearsal must pass before
  local commit.

## Rollback

Revert this commit to restore the identical cleanup assignments in the facade.

## Completion evidence

- Focused pure and live disconnected suite: `7 passed`.
- Full pytest suite: `820 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
