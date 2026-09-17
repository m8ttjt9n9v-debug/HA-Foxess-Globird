# OM-703E — Pure FoxESS export-policy boundary

## Problem and evidence

Automatic export currently mixes EV priority, time eligibility, inverter
limits, allowance accounting, protected-energy planning and retained-session
ownership inside the active controller. The derivation must be frozen before
controller mutation and command execution can be separated.

## Existing contract

The requested discharge is the lower of the non-negative configured inverter
limit and actuator maximum; the legacy user power preference is not applied.
EV-before-export can withhold a new session while still publishing a candidate
plan. Retained sessions continue so they can stop safely. Invalid early input
retains prior accounting publications, while invalid later planning input can
leave newly calculated allowance and EV protection visible with no plan.

## Invariants

- Latest-start, efficiency, energy protection and allowance formulas remain.
- EV priority affects effective enablement, not candidate-plan visibility.
- Source capability remains separate from discharge maximum.
- Missing mode capability is delegated to export-session reconciliation rather
  than independently changing energy eligibility.
- Partial-publication behavior on malformed inputs remains exact.
- No persistence, scheduling or hardware command occurs in the evaluator.

## Non-goals

- Do not wire the evaluator into production yet.
- Do not move EV presence/cable acquisition in this seam.
- Do not alter export-session transitions or command planning.
- Do not repair stale publication behavior during structural extraction.

## Deliverables

- Immutable primitive `FoxessExportPolicyContext`.
- Immutable `FoxessExportPolicyResult` with candidate and transition inputs.
- Characterization of healthy, withheld, retained, missing and malformed paths.

## Compatibility

This boundary is unwired and adds no entity, attribute, configuration field,
Store payload, service payload, timer, retry or runtime behavior.

## Test plan

- Healthy bounded plan and latest start.
- EV-priority idle withholding and active-session finish.
- Early and later malformed-input partial publications.
- Missing energy inputs, exact finish boundary and zero power.
- Full lifecycle, compatibility-contract and previous-release gates.

## Rollback

Revert this commit. Because the evaluator is unwired and side-effect-free,
rollback has no runtime or storage consequence.

## Acceptance evidence

- 111 focused pure-policy, planning, session and lifecycle tests passed.
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
