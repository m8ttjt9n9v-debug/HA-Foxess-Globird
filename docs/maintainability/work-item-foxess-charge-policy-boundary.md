# OM-703C — Pure FoxESS charge-policy boundary

## Problem and evidence

The automatic controller derives charge limits, source availability, allowance
status, SoC eligibility, session ownership and finish intent inline before it
advances the retained charge session. These calculations need a pure contract
before controller mutation and command execution can be separated safely.

## Existing contract

The request is enabled only when automatic charging and the local schedule
confirmation are both true. Charge power is the lower of non-negative
configured maximum and observed actuator maximum. Source availability also
requires the mapped mode options to support Self Use and Force Charge. An idle
start additionally requires an active free window, positive remaining
allowance, SoC from zero up to but excluding target, positive power and Self
Use feedback. A retained session continues reconciliation after policy, window
or allowance changes so it can restore safely.

## Invariants

- Schedule, mode and allowance reason precedence remains exact.
- A retained session continues to own the tick until reconciled idle.
- Missing actuator range makes the source unavailable without erasing session.
- Missing mode capability is passed to session reconciliation as unavailable;
  it does not independently rewrite the existing eligibility calculation.
- The evaluator cannot persist, schedule or execute hardware commands.
- No numeric clamp or eligibility formula is improved in this seam.

## Non-goals

- Do not wire the evaluator into production yet.
- Do not call `advance_charge_session` or alter its transitions.
- Do not change free-window timing, allowance accounting or target SoC.
- Do not extract export policy in the same commit.

## Deliverables

- Immutable primitive `FoxessChargePolicyContext`.
- Immutable derived `FoxessChargePolicyResult`.
- Characterization of every idle failure and retained-session finish path.

## Compatibility

This boundary is unwired and adds no entity, attribute, configuration field,
Store payload, service payload, timer, retry or runtime behavior.

## Test plan

- Eligible start and bounded maximum.
- Missing, exhausted and negative allowance.
- Schedule and mode precedence.
- SoC, window, enable and actuator-range boundaries.
- Active and recovering retained-session paths.
- Full lifecycle, compatibility-contract and previous-release gates.

## Rollback

Revert this commit. Because the evaluator is unwired and side-effect-free,
rollback has no runtime or storage consequence.

## Acceptance evidence

- 96 focused pure-policy, retained-controller and lifecycle tests passed.
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
