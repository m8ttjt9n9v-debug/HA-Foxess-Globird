# Work item — manual-diagnostic typed repository

## Problem

The manual FoxESS diagnostic controller directly decoded and encoded its Store
payload even though that payload is the durable ownership and restoration
obligation for an interrupted force test.

## Change and preserved behavior

`ManualTestPersistenceState` now owns the unchanged payload codec, and a
dedicated `TypedValueStoreRepository` wraps the original Store. Repository load
status maps exactly to the retained safety vocabulary (`valid`, `missing`, or
`malformed`). A valid idle payload retains the controller's established no-op
load behavior.

Command execution, bounded retries, timer scheduling, Safety Lock and mapping
gates, unload behavior and visible failure states are unchanged. The Store key,
version 1, privacy flag, payload shape and write timing are unchanged.

## Rollback

Restore the former controller codec bodies and direct Store calls, then remove
the repository attribute. No payload migration or stored-data rollback is
needed.

## Verification

- Codec characterization covers an active restoration obligation and malformed
  phase evidence.
- Existing restart, unload, bounded retry, no-write gate and lifecycle fixtures
  remain unchanged.
- Focused manual, ownership and lifecycle selection: 34 passed.
- Full repository suite: 659 passed.
- Ruff and all frozen compatibility contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- The frozen v0.12.26 persistence contract remains unchanged.
- `README.md` remained unchanged.
