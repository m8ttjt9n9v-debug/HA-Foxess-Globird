# OM-704C — Pure FoxESS unavailable-feedback recovery boundary

## Problem and evidence

When actuator feedback disappears, the controller rewrites retained sessions
to recovery state and immediately persists them. This next-state decision and
its persistence obligations need an explicit pure result.

## Existing contract

Starting, active, stopping and already-recovering charge sessions are rebuilt
as recovering and saved. Any non-idle export session is rebuilt as recovering
and saved. Existing command timestamps are retained; otherwise the current
evaluation time is captured. Idle sessions are neither changed nor saved.

## Invariants

- Existing power, attempts and non-null command timestamps remain unchanged.
- Already-recovering sessions still carry a save obligation.
- Charge retains its explicit known-phase set; export retains its broad
  non-idle rule.
- The planner cannot access storage or Home Assistant.

## Non-goals

- Do not wire the planner into production yet.
- Do not validate or normalize malformed in-memory phases.
- Do not alter feedback availability classification.
- Do not change subsequent session recovery transitions.

## Deliverables

- Immutable result containing both next sessions and save flags.
- Exhaustive phase and timestamp characterization.

## Compatibility

This boundary is unwired and adds no entity, attribute, configuration field,
Store payload, service payload, timer, retry or runtime behavior.

## Test plan

- Both idle sessions.
- Every retained charge/export phase.
- Existing versus missing command timestamp.
- Asymmetric unexpected-phase behavior.
- Full lifecycle, compatibility-contract and previous-release gates.

## Rollback

Revert this commit. Because the planner is unwired and side-effect-free,
rollback has no runtime or storage consequence.

## Acceptance evidence

- 92 focused recovery and lifecycle tests passed.
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
