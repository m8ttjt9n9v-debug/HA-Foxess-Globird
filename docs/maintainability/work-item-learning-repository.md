# Work item — house-learning typed repository

## Problem

House learning persisted two histories and two optional in-progress samplers in
one established payload assembled directly by the coordinator. A generic value
repository alone could not express that composite contract clearly.

## Change and preserved behavior

`DemandPersistenceState` now owns decoding, capture and encoding of the existing
composite payload. The coordinator applies decoded sampler payloads to the same
configured sampler instances, preserving their freshness and gap validation.
The retained Store object, private key, version 1, history retention,
field presence, partial-cycle payloads and save timing are unchanged.

## Rollback

Restore the former coordinator assembly/load code and direct `_demand_store`
calls. No payload migration or stored-data rollback is needed.

## Verification

- Composite-payload characterization proves exact history, heater and
  in-progress sampler round-trip.
- Invalid outer payload restores empty histories safely.
- Existing learning maturity, partial-cycle restart, setup/reload and
  persistence tests remain unchanged.
- Focused learning and persistence selection: 42 passed.
- Full repository suite: 653 passed.
- Ruff and all frozen compatibility contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- The frozen v0.12.26 persistence contract remains unchanged.
- `README.md` remained unchanged.
