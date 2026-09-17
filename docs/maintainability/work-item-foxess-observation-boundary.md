# OM-702A — Immutable FoxESS observation boundary

## Problem and evidence

`ActiveFoxessController` reads Home Assistant mode, power, option and range
state directly in several helpers. Manual diagnostics perform a separate read
and conversion. Phase 7 needs one side-effect-free observation contract before
any controller can be decomposed safely.

## Existing contract

Mode is unavailable when its entity is missing, `unknown` or `unavailable`.
Force-power feedback accepts W/kW/MW through `power_to_kw`; invalid or missing
state is unavailable. A missing or invalid number maximum resolves to 0 kW.
Charge capability requires `Self Use` and `Force Charge` options; export
capability requires `Self Use` and `Force Discharge`.

## Invariants

- No service call, Store access, scheduling or controller mutation.
- No inferred entity, mode option, unit, limit or ownership.
- Missing and malformed state fails closed.
- Existing controller reads remain authoritative until shadow parity passes.

## Non-goals

- Do not wire the snapshot into either active controller yet.
- Do not alter controller gates, decisions, timing or commands.
- Do not merge manual diagnostic ownership with automatic ownership.

## Deliverables

- Immutable `FoxessFeedbackSnapshot`.
- One read-only capture function over an explicit `FoxessEntityMap`.
- Unit, invalid-input and legacy-controller shadow-parity tests.

## Compatibility

The boundary is not yet consumed by production. It adds no entity,
configuration key, persistence payload, service call or public attribute.

## Test plan

- Healthy W/kW conversion and range metadata.
- Independent mode capability and power-feedback validity.
- Missing, unavailable, malformed and unsupported metadata.
- Exact comparison with every equivalent legacy controller helper.
- Full lifecycle, compatibility-contract and previous-release gates.

## Rollback

Revert the single boundary commit. Because it is unwired and side-effect-free,
rollback has no runtime or storage consequence.

## Acceptance evidence

- Four direct observation tests, including exact legacy-helper shadow parity,
  passed with the 62-test focused adapter/controller/manual corpus.
- Full repository suite: 685 passed.
- Ruff passed for production, tests and scripts.
- Frozen entity, configuration, presentation and persistence contracts passed.
- The `v0.12.26` previous-release rehearsal passed.
- `README.md` remained unchanged.

## Completion record

- [x] Existing behaviour characterised
- [x] Implementation complete
- [x] Compatibility checks passed
- [x] Documentation and roadmap updated
- [ ] Independent review complete
- [x] Rollback demonstrated
- [x] Operational soak complete where required — not required while unwired
