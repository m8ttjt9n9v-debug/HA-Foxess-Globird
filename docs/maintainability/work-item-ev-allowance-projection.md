# Phase 7.9 — extract EV free-window allowance projection

## Problem and evidence

`ActiveEvController._allowance_target` still combines Home Assistant entity
observation and mutable diagnostic publication with the domain calculation
that composes house load, EV demand, battery demand and the whole-site daily
allowance. The component estimators are already pure, but their orchestration
remains embedded in the active controller facade.

## Existing contract

- Stored vehicle energy, vehicle SoC, battery SoC and house load are required.
- A commissioned EV-exclusive house-load source is used unchanged.
- A commissioned whole-house source removes state-qualified measured EV power
  exactly once using configured EV voltage and phase count. Invalid actual EV
  current makes the projection unavailable rather than learning or budgeting a
  knowingly incorrect house load.
- Missing cumulative free-window import remains a valid planner input and
  returns the protected baseline with `allowance_meter_unavailable`.
- Vehicle wall-energy need, other free-window import and the current ceiling
  retain their existing rounding, topology, safety-margin and exception
  semantics.
- The facade publishes the composed house load and, only for whole-house
  topology, the removed EV power.

## Invariants

- Preserve every target current, reason and diagnostic value.
- Preserve fail-closed missing/invalid evidence behavior.
- Preserve explicit topology; never infer whether house load includes EV.
- No timing, hold, current reconciliation, service-call or persistence change.
- No Home Assistant import or side effect enters the pure evaluator.

## Non-goals

- Do not change the allowance algorithm, tariff model or free-window policy.
- Do not change entity mappings, configuration defaults or topology choices.
- Do not implement morning solar charging, cadence control or pre-free
  precedence.
- Do not broaden malformed configuration acceptance.

## Deliverables

- Characterization of both house-load topologies and unavailable evidence.
- Immutable primitive evidence and result types.
- A pure evaluator composing the existing projection functions.
- A thin controller adapter that observes inputs and publishes diagnostics.

## Compatibility and rollback

There are no entity, unique-ID, state-value, attribute, configuration-key,
storage, dashboard, Fleet or Recorder changes. Reverting the extraction commit
restores the same calculation to the facade without data or hardware-state
migration.

## Test plan

- Freeze current facade outcomes before extraction.
- Add pure topology, missing-evidence and missing-meter tests.
- Retain transition-hold and full runtime tests.
- Run focused, lifecycle, frozen-contract, previous-release, Ruff and full
  repository gates.

## Acceptance evidence

- Pre-extraction facade characterization: 5 passed.
- Post-extraction focused pure/facade allowance suite: 17 passed; broader
  free-window and EV runtime selection: 39 passed.
- Full repository suite: 888 passed in 36.13 seconds.
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
