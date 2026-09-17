# OM-705B — Composite immutable EV feedback snapshot

## Problem and evidence

OM-705A introduced a lossless mapped-entity read. EV reconciliation still
needs a single per-cycle composition covering connection, vehicle telemetry,
actuator feedback, smart socket, legacy override and battery-SoC presence.

## Existing contract

Actual current is invalid when charging state is unavailable, exactly zero and
valid whenever state is not `charging`, and numeric/unit-qualified only while
charging. Direct EVSE feedback requires both number entities, charge-switch
state and all six min/max/step attributes. Raw actuator numeric values retain
non-finite behavior, unlike general mapped-number reads.

## Invariants

- Each unique mapped entity ID is read no more than once per snapshot.
- Raw source timestamps and presence remain available to later policies.
- Charging-state qualification and actuator completeness remain exact.
- No freshness, location, connection or command policy is applied.
- The snapshot cannot mutate Home Assistant, storage or services.

## Non-goals

- Do not wire the snapshot into EV control yet.
- Do not calculate smart-recovery stability or solar-spill coherence yet.
- Do not change legacy charge-to-full fallback behavior.
- Do not remove retained EV controller helpers before shadow parity.

## Deliverables

- Explicit immutable entity map for every EV-related source.
- One typed runtime-to-map constructor, including lifetime driving energy and
  battery-SoC presence evidence.
- Immutable composite snapshot with actual-current and direct-actuator views.
- Unique-ID read cache and characterization.

## Compatibility

This boundary is unwired and adds no entity, attribute, configuration field,
Store payload, service payload, timer, retry or runtime behavior.

## Test plan

- Complete direct actuator observation.
- Missing/stopped/charging actual-current branches.
- Duplicate mappings read once.
- Raw versus finite numeric behavior.
- Exact shadow comparison with retained controller state, number, current,
  energy and direct-actuator helpers.
- Full EV/lifecycle, compatibility-contract and previous-release gates.

## Rollback

Revert this commit. OM-705A may remain as an unused low-level boundary. No
stored data or state conversion is involved.

## Acceptance evidence

- 199 focused composite observation, typed configuration, EV controller and
  lifecycle tests passed after completing the entity map.
- Full repository suite and Ruff passed.
- All nine frozen compatibility contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- `README.md` unchanged.

## Completion record

- [x] Existing behaviour characterised
- [x] Implementation complete
- [x] Compatibility checks passed
- [x] Documentation and roadmap updated
- [ ] Independent review complete
- [x] Rollback demonstrated
- [x] Operational soak complete where required — not required while unwired
