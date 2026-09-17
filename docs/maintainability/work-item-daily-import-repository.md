# Work item — daily-import typed repository

## Problem

Coordinator code directly loaded and saved the daily-import Store. Repeating
that pattern across state families makes fallback behavior and payload-boundary
rules harder to review consistently.

## Change and preserved behavior

`TypedStoreRepository` now mediates load and save for the daily-import
accumulator. The existing Store object, key, version, privacy flag, payload,
checkpoint threshold and save timing are unchanged. The repository rejects a
non-mapping outer payload and restores the accumulator's safe empty state;
field-level validation remains with `DailyImportAccumulator.restore()`.

## Rollback

Revert the coordinator's three repository references and call the retained
`_daily_import_store` directly. No stored data or migration must be reversed.

## Verification

- Repository characterization covers valid, missing and invalid payloads plus
  exact payload preservation on save.
- Existing meter checkpoint and setup/reload tests remain unchanged.
- Focused persistence and setup suite: 55 passed.
- Full repository suite: 648 passed.
- Ruff and all frozen compatibility contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- Frozen v0.12.26 persistence contract remains unchanged.
- `README.md` remained unchanged.
