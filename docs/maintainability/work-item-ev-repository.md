# Work item — composite EV typed repository

## Problem

The EV controller's single Store contains timed averages, driving evidence,
direct-EVSE reconciliation, pre-free ownership, daily backfill, Charge to Full
timing and smart-socket recovery. Direct Store access and one large untyped
payload made that restart surface difficult to review as a contract.

## Change and preserved behavior

`EvPersistenceState` and `DailyBackfillPersistenceState` define the existing
composite payload and its fallback groups. A dedicated
`TypedValueStoreRepository` wraps the retained EV Store. Timed-average payloads
are restored into the same configured windows. Valid driving history and its
snapshot survive malformed control-session evidence, while reconciliation,
pre-free, backfill, Charge to Full, outside-control ownership and smart recovery
fail safe together exactly as before.

All EV policy, priority, current selection, command reconciliation, recovery,
learning and write gates remain in the controller. The Store key, version 1,
privacy flag, payload shape and save timing are unchanged.

## Rollback

Restore the former direct Store load/save calls and remove the repository and
typed persistence model. No payload migration or stored-data rollback is
needed.

## Verification

- A complete existing payload round-trips without shape or value drift.
- Malformed control evidence retains valid driving evidence and resets the
  coupled control obligations together.
- Existing daily-backfill, pre-free, smart-recovery, driving-learning,
  unplug/replug, setup/reload and lifecycle fixtures remain unchanged.
- Focused EV, lifecycle and persistence selection: 72 passed.
- Full repository suite: 662 passed.
- Ruff and all frozen compatibility contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- The frozen v0.12.26 persistence contract remains unchanged.
- `README.md` remained unchanged.
