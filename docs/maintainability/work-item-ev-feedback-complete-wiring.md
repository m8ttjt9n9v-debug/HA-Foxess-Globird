# Work item: complete EV feedback boundary wiring

## Problem

After the core EV helpers moved to a cycle-scoped immutable snapshot, the
smart-socket stability/recovery path and solar-spill source-presence check still
read Home Assistant state directly. Those extra reads could observe a newer
state than the rest of the same reconciliation.

## Preserved contract

- Smart-socket state and `last_changed` age retain their existing on/off and
  settle-time semantics.
- Recovery evidence retains the existing unavailable-state, minimum-age,
  location, cable and charge-switch rules.
- Solar-spill telemetry coherence still requires the actual-current and battery
  SoC entities to exist; their age remains deliberately excluded from the fast
  electrical telemetry clock check.
- Helpers called outside reconciliation still capture current Home Assistant
  state rather than retaining a completed cycle's snapshot.

## Change

All remaining EV controller entity reads now pass through the read-only EV
observation adapter. During reconciliation they resolve to the immutable cycle
snapshot; outside reconciliation the adapter performs one live read. The
controller no longer accesses `hass.states` directly.

## Invariants

- No actuator, service-call, current, charge-limit, safety or timing policy is
  changed.
- Entity presence remains distinct from entity availability.
- `last_changed` remains the source for smart-socket and recovery stability.
- Unknown, unavailable and empty states continue to fail closed.

## Verification

- The smart-socket runtime regression exercises the real controller path and
  asserts every mapped EV entity is read exactly once in the cycle.
- Existing smart-socket command-order, recovery, solar-spill, connectivity and
  restart tests remain authoritative.
- Focused EV tests, full pytest, Ruff, repository contracts and the previous
  release rehearsal must pass before local commit.

## Rollback

Revert this wiring commit. The preceding core snapshot wiring remains a valid,
independently verified boundary.

## Completion evidence

- Focused EV and lifecycle suite: `118 passed`.
- Full pytest suite: `773 passed`.
- Repository-wide Ruff: passed.
- Nine architecture/configuration/persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
