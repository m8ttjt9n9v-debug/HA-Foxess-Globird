# Phase 7.9 — extract EV pre-free plan composition

## Problem and evidence

`ActiveEvController._calculate_outside_target` combined Home Assistant mapping
with the domain calculation that infers vehicle wall-energy room and caps it by
the protected export plan. The calculation can be pure while the pre-free
session latch, frozen start, current selection and command ownership remain in
the active facade.

## Existing contract

- Missing export-plan or stored-vehicle-energy evidence withholds the plan.
- Vehicle wall-energy room is inferred from live stored energy, SoC, target and
  configured charging efficiency using the retained capacity model.
- Only export energy inside the pre-free window is discretionary; outside the
  window, complete evidence retains the existing empty diagnostic plan.
- Planned energy remains the lesser of protected export energy and vehicle
  room. Latest start uses only current above the protected baseline.

## Invariants and non-goals

- Preserve plan values, frozen-start lifecycle, phase, target and command
  ordering.
- Preserve missing-input and outside-window distinctions.
- Do not alter the live pre-free current calculation, solar-spill blending,
  current cadence, persistence, reconciliation or retries.
- Do not implement the separately specified fixed-current, exclusive pre-free
  takeover in this behaviour-preserving extraction.

## Deliverables and gates

Characterize full, missing and outside-window evidence; introduce immutable
primitive evidence/result types; retain a thin facade mapping; run focused,
lifecycle, frozen-contract, previous-release, full-suite, Ruff and rollback
checks. Reversion requires no data or hardware-state migration.

## Acceptance evidence

- Pre-extraction planner/runtime characterization: 4 passed.
- Post-extraction focused planner/runtime selection: 44 passed.
- Full repository suite: 916 passed in 36.40 seconds.
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
