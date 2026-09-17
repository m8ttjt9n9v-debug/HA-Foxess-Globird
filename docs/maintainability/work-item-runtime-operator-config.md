# Work item — typed runtime operator configuration

## Problem and evidence

Dashboard switches, the EV priority number and occupancy select both mutate and
read the raw config mapping. The central mutation boundary allows these
human-facing values to use one immutable runtime snapshot without touching
controller policy.

## Contract and invariants

- Persisted keys, defaults and malformed-value fallbacks remain identical.
- `coordinator.config` remains available to all unmigrated consumers.
- A runtime mutation updates the raw mirror and rebuilds the immutable snapshot
  synchronously before state listeners or reconciliation run.
- Config-entry persistence, service order, hardware commands and entity state
  vocabulary do not change.

## Scope

Typed slices cover automation requests/Safety Lock, EV-before-export and
charge-to-full preferences, and house occupancy mode. Only their integration-
owned switch/number/select state readers migrate in this work item.

## Tests and rollback

Pure parser tests freeze defaults and malformed input handling; setup and entity
action tests prove persistence and immediate state. Full lifecycle tests prove
no controller delta. Revert the commit to roll back; serialized data is
unchanged.
