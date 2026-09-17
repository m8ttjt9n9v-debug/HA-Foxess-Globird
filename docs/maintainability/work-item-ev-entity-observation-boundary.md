# OM-705A — Immutable mapped EV entity observation

## Problem and evidence

`ActiveEvController` repeatedly reads mapped Home Assistant entities through
several helpers with different state, numeric, current, energy, attribute and
timestamp semantics. Phase 7.5 needs one lossless read boundary before those
domain-specific observations can be composed safely.

## Existing contract

Mapped state excludes `unknown` and `unavailable` case-insensitively while
retaining entity presence and raw state. General numeric reads require finite
values. Current conversion retains its historical non-finite behavior; energy
requires finite non-negative kWh. Actuator min/max/step accept float-convertible
metadata without adding a finiteness rule. Both Home Assistant timestamps are
retained for later stable-value and fast-telemetry policies.

## Invariants

- Exactly one `hass.states.get` supplies one entity snapshot.
- No freshness, connection, charging or eligibility policy is applied.
- No unit, attribute, non-finite or unavailable-state rule is improved.
- The boundary cannot mutate state, storage or services.

## Non-goals

- Do not wire the boundary into EV control yet.
- Do not compose the complete per-cycle EV observation in this seam.
- Do not merge stable cloud evidence with fast electrical freshness.
- Do not change actuator or smart-socket policy.

## Deliverables

- Immutable `EvEntityFeedback` with raw, interpreted and timestamp evidence.
- One side-effect-free capture function for an explicit entity ID.
- Characterization of unavailable, missing, unit, metadata and non-finite rules.

## Compatibility

This boundary is unwired and adds no entity, attribute, configuration field,
Store payload, service payload, timer, retry or runtime behavior.

## Test plan

- State availability and case handling.
- General number, current and energy conversions.
- Missing/invalid actuator metadata.
- Negative and non-finite values.
- Exact source timestamps and immutability.
- Full EV/lifecycle, compatibility-contract and previous-release gates.

## Rollback

Revert this commit. Because the boundary is unwired and side-effect-free,
rollback has no runtime or storage consequence.

## Acceptance evidence

- 109 focused observation, EV controller, adapter and lifecycle tests passed.
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
