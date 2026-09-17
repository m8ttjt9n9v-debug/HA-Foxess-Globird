# OM-704D — Wire FoxESS unavailable-feedback recovery planning

## Problem and evidence

OM-704C froze the exact next sessions and persistence obligations when mapped
FoxESS feedback disappears. The controller still constructed those states
inline.

## Existing contract

Retained charge and export sessions become recovering, preserving power,
attempt count and an existing command timestamp. Missing timestamps use the
current evaluation time. Charge is saved before export, and already-recovering
sessions are deliberately saved again. Idle sessions remain unwritten.

## Invariants

- Next-state values and save predicates remain exact.
- Charge-before-export repository ordering remains unchanged.
- The recovery planner cannot access storage or Home Assistant.
- Subsequent policy/session reconciliation remains untouched.

## Non-goals

- Do not change feedback availability rules.
- Do not alter Store payloads or repository behavior.
- Do not merge recovery with charge/export session state machines.
- Do not suppress repeated recovery saves.

## Deliverables

- The controller invokes one pure recovery planner.
- The controller assigns returned states and executes returned save obligations.
- Duplicate inline recovery construction is removed.

## Compatibility

No entity, attribute, configuration field, Store payload, service payload,
reason, timer or retry contract changes.

## Test plan

- Every retained and idle phase.
- Existing and missing command timestamps.
- Exact repository write count and order across lifecycle fixtures.
- Full compatibility contracts and previous-release rehearsal.

## Rollback

Revert this wiring commit. The pure OM-704C planner may remain unused. No
stored data or state conversion is involved.

## Acceptance evidence

- 93 focused recovery, persistence and lifecycle tests passed.
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
- [x] Operational soak complete where required — no policy change
