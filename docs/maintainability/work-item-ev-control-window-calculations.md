# Work item: EV control-window calculations

## Change

Move EV free-window position/duration, daily-ready cycle, pre-free interval and
boosted-export membership arithmetic into the shared pure control-window
planner. Existing controller methods remain thin configuration adapters.

## Invariants

- Free-window elapsed and remaining values retain exact inclusive/exclusive
  boundaries and overnight wrapping.
- Equal free-window bounds retain the historical 24-hour duration.
- Daily ready deadlines roll at the exact deadline and preserve next-free rules.
- Pre-free membership and hours-until-free are unchanged.
- Equal boosted-window bounds remain disabled, while overnight boosted windows
  retain their existing membership rule.
- Commands, reasons, persistence and public contracts are unchanged.

## Verification

- Pure tests cover ordinary, overnight, equal-bound and exact-boundary cases.
- Existing EV lifecycle, learning, daily-backfill and solar-spill tests remain
  authoritative.
- Focused window, EV lifecycle, daily-backfill and learning suite: `114 passed`.
- Full suite: `838 passed`.
- Repository Ruff check passed.
- All ten architecture contracts passed.
- Previous-release rehearsal against `v0.12.26` passed.

## Rollback

Revert this commit to restore the identical datetime arithmetic inside the EV
controller helpers.
