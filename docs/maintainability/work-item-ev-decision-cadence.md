# Phase 7.9 — extract EV decision cadence and transition hold

## Problem and evidence

`ActiveEvController._async_reconcile_cycle` still assembled the target-decision
fingerprint, three-minute boundary, whole-house EV-current convergence hold,
policy-limit crossing and service-overrun bypass. This block decides whether
HEO recalculates at all and is domain policy rather than Home Assistant facade
work.

## Existing contract

- Ordinary free-window decisions occur at most every three minutes unless a
  relevant fingerprint changes.
- A vehicle-SoC-only change may temporarily retain the previous target while
  requested and actual EV current are converging, but only with allowance
  protection enabled for an explicitly commissioned whole-house load source.
- Reaching the vehicle policy limit, disabling the allowance guard, or a
  measured service-limit overrun bypasses that hold immediately.
- The exact three-minute boundary, an absent target, first decision, active
  pre-free session and every outside-window cycle remain eligible to decide.
- The fingerprint retains the same nine SoC, policy, current-range and
  charge-limit-range values.

## Change and invariants

One immutable evaluator now returns the fingerprint plus every intermediate
hold/safety fact and the final `should_decide` result. The facade supplies one
cycle's observation/configuration evidence, publishes the retained transition
hold phase, invokes the chosen evaluator and checkpoints the returned
fingerprint only after a calculation succeeds.

No interval, threshold, target, stage priority, reason, command, entity,
configuration field or persistence payload changes.

## Verification and rollback

Golden pure cases cover the ordinary convergence hold and each safety, policy,
time, pre-free and outside-window bypass. Existing multiphase runtime traces,
full lifecycle, frozen contracts, previous-release rehearsal, Ruff and reverse
patch checks remain gates. Reversion requires no migration or hardware action.

## Acceptance evidence

- Pre-extraction multiphase runtime characterization: 4 passed.
- Post-extraction focused pure/facade selection: 88 passed.
- Full repository suite: 929 passed in 36.41 seconds.
- Frozen architecture and compatibility contracts: 24 passed.
- Previous-release rehearsal against `v0.12.26`: 1 passed.
- Repository-wide Ruff, `git diff --check` and reverse-patch applicability:
  passed.
- `_async_reconcile_cycle` fell from 381 to 348 lines, from 25 to 13
  arithmetic/boolean operations and from 37 to 23 comparisons. The extracted
  values are now independently visible in a typed evaluation result rather
  than implicit facade locals.
- Public entities, configuration keys, persistence payloads and command
  behaviour are unchanged. Independent review and the complete Phase 7
  exit/rollout gates remain separate obligations; this extraction is not
  authorized for deployment.

## Completion record

- [x] Existing behaviour characterised
- [x] Implementation complete
- [x] Compatibility checks passed
- [x] Documentation updated
- [ ] Independent review complete
- [x] Rollback demonstrated
- [x] Operational soak not required for this side-effect-free extraction
