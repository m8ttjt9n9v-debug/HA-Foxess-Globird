# Work item: FoxESS control-window calculations

## Change

Move ZEROHERO finish derivation, chronological window bounds, time-until-free
and daily-window overlap calculations from the active FoxESS controller into a
pure planner module. Controller methods remain thin configuration adapters for
existing private test and diagnostic compatibility.

## Invariants

- Offset-derived and legacy force-discharge finish times are unchanged.
- Overnight window membership before and after midnight is unchanged.
- An exact free-window start still resolves to the next day's start.
- Touching window endpoints do not overlap; positive-duration intersections do.
- Enable gates, reasons, commands, persistence and public contracts are
  unchanged.

## Verification

- Pure tests cover offset wrap, legacy finish, overnight bounds, exact boundary
  rollover, wrapped overlap and touching endpoints.
- Existing active-controller overlap and ZEROHERO boundary tests remain
  authoritative.
- Focused pure-window and active-controller suite: `48 passed`.
- Full suite: `832 passed`.
- Repository Ruff check passed.
- All ten architecture contracts passed.
- Previous-release rehearsal against `v0.12.26` passed.

## Rollback

Revert this commit to return the identical arithmetic to the controller helper
methods.
