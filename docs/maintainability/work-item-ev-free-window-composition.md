# Phase 7.9 — extract EV free-window target composition

## Problem and evidence

`ActiveEvController._calculate_target` still contains domain composition around
the retained pure current planner: physical baseline/minimum clamps, Charge to
Full policy-limit override, vehicle-limit gating, telemetry-validity evidence
and final current/phase selection.

## Existing contract

- The commissioned path ceiling, physical charging minimum and actuator step
  bound both the protected baseline and effective free-window minimum.
- Charge to Full selects a 100% policy limit and retains its established
  priority inside the existing current planner.
- Otherwise the configured free-window limit decides vehicle eligibility. At
  or above that limit, the target is the protected baseline and the public
  phase is `policy_limit_reached` regardless of the unused base-plan result.
- Grid average is valid only with a value, at least 0.67 age coverage and valid
  source evidence. EV average validity and state-qualified actual current keep
  their existing semantics.
- EV priority applies only while below the policy limit; allowance pacing and
  charge-limit actuator policy remain later, independent stages.

## Invariants and non-goals

- Preserve baseline, effective minimum, target current, policy limit and phase.
- Preserve current-planner branch ordering and exact telemetry thresholds.
- Preserve missing metadata/SoC rejection in the facade.
- Do not alter allowance projection, command reconciliation, retry timing,
  Charge to Full persistence, solar, pre-free or outside-window policy.

## Deliverables and gates

Characterize runtime policy-limit and existing pure branch outcomes; introduce
immutable primitive composition inputs/results; retain a thin facade mapping;
run focused, lifecycle, frozen-contract, previous-release, full-suite, Ruff and
rollback checks. Reversion requires no data or hardware-state migration.

## Acceptance evidence

- Focused free-window planner/facade selection: 21 passed; broader runtime
  allowance, policy-limit and Charge-to-Full selection: 13 passed.
- Full repository suite: 905 passed in 36.19 seconds.
- Frozen architecture and compatibility contracts: 24 passed.
- Previous-release rehearsal against `v0.12.26`: 1 passed.
- Repository-wide Ruff, `git diff --check` and reverse-patch applicability:
  passed.
- `README.md`, public entities, configuration keys, persistence payloads and
  command behavior are unchanged.
- Independent review and the complete Phase 7 exit/rollout gates remain
  separate obligations; this extraction is not authorized for deployment.

## Completion record

- [x] Existing behaviour characterised
- [x] Implementation complete
- [x] Compatibility checks passed
- [x] Documentation and roadmap updated
- [ ] Independent review complete
- [x] Rollback demonstrated
- [x] Operational soak not required for this side-effect-free extraction
