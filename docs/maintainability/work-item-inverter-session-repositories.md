# Work item — inverter-session typed repositories

## Problem

The active FoxESS controller directly decoded, encoded, loaded and saved charge
and export session payloads. Those payloads preserve hardware-restoration
obligations, so duplicated persistence mechanics increased the risk of a future
change erasing ownership after reload.

## Change and preserved behavior

`ChargeSessionState` and `ExportSessionState` now own their established payload
codecs. Separate `TypedValueStoreRepository` instances wrap the original charge
and export Store objects. Repository load status maps exactly to the retained
controller safety vocabulary: restored is `valid`, absent is `missing`, and an
invalid envelope or session is `malformed`.

All command planning, phase transitions, retries, session ordering, restoration
and ownership checks remain in the active controller. The compatibility payload
helpers remain and delegate to the state codecs. Store keys, version 1, privacy,
payload shape and write timing are unchanged.

## Rollback

Restore the former controller codec bodies and direct Store calls, then remove
the two repository attributes. No payload migration or stored-data rollback is
needed.

## Verification

- Codec characterization round-trips every allowed charge/export phase and
  rejects malformed evidence.
- Existing restart-at-every-phase, reconfigure, ownership recovery, command
  trace and source-loss lifecycle fixtures remain unchanged.
- Focused session, ownership and lifecycle selection: 51 passed.
- Full repository suite: 657 passed.
- Ruff and all frozen compatibility contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- The frozen v0.12.26 persistence contract remains unchanged.
- `README.md` remained unchanged.
