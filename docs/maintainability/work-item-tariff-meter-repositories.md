# Work item — tariff-meter typed repositories

## Problem

Six remaining tariff accumulators still loaded and saved their Home Assistant
Stores directly after the daily-import repository seam was proven. This left
one state family with two persistence paths.

## Change and preserved behavior

Daily export, peak-rate export, free-window import, peak-window import,
ZEROHERO hourly import and ZEROHERO export now use the same
`TypedStoreRepository` mechanics as daily import. Every retained repository
wraps its original Store object. Store keys, version 1, privacy flags, payload
shapes, checkpoint thresholds and save timing are unchanged.

## Rollback

Replace each repository load/save call with its former direct Store call and
remove the six repository attributes. Stored data needs no migration or
rollback.

## Verification

- A wiring regression proves all seven tariff repositories retain the exact
  frozen Store objects.
- Existing transition-checkpoint, tariff-window, restart and accounting tests
  continue to exercise the same payloads and timing.
- Focused persistence, setup, tariff and ledger suite: 76 passed.
- Full repository suite: 649 passed.
- Ruff and all frozen compatibility contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- The frozen v0.12.26 persistence contract remains unchanged.
- `README.md` remained unchanged.
