# Phase 7.9 — extract EV outside-window current envelope

## Problem and evidence

`ActiveEvController._calculate_outside_target` composed the protected baseline,
service/inverter pre-free ceiling and minimum service-current gate alongside
Home Assistant state mapping and lifecycle ownership. These current bounds are
domain calculations and can be reviewed independently of session mutation and
command execution.

## Existing contract

- A configured baseline at or below zero remains exactly 0 A.
- A positive baseline is raised to the physical charging minimum and current
  step, then capped by the commissioned path ceiling.
- The pre-free ceiling is the lower of live service and configured inverter
  ceilings, but never below the protected baseline.
- Charge to Full is rejected when live service headroom is below the physical
  charging minimum.

## Invariants and non-goals

- Preserve every target, phase, reason and candidate value.
- Preserve service-current sampling and the inverter-current calculation.
- Do not alter solar-spill/pre-free precedence, current cadence, session state,
  persistence, reconciliation, retries or commands.
- In particular, do not implement the separately specified fixed-current,
  exclusive pre-free takeover in this behaviour-preserving extraction.

## Deliverables and gates

Characterize zero, negative, sub-minimum, over-ceiling and service-starved
inputs; introduce immutable primitive evidence/result types; retain a thin
facade mapping; run focused, lifecycle, frozen-contract, previous-release,
full-suite, Ruff and rollback checks. Reversion requires no data or hardware
state migration.

## Acceptance evidence

- Pre-extraction runtime characterization: 5 passed.
- Post-extraction focused planner/runtime selection: 42 passed.
- Full repository suite: 912 passed in 35.98 seconds.
- Frozen architecture and compatibility contracts: 24 passed.
- Previous-release rehearsal against `v0.12.26`: 1 passed.
- Repository-wide Ruff, `git diff --check` and reverse-patch applicability:
  passed.
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
