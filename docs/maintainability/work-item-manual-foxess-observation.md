# OM-702C — Share FoxESS feedback with manual diagnostics

## Problem and evidence

Automatic inverter control now consumes one immutable FoxESS feedback
snapshot, while manual commissioning tests still repeated the same three
Home Assistant state reads and power conversions. The two paths could drift
despite observing the same configured actuator entities.

## Existing contract

Manual diagnostics distinguish two failures. A missing mapped entity reports
`FoxESS actuator feedback is unavailable`; an existing but non-numeric power
state reports `FoxESS power feedback is unavailable`. Unlike automatic
control, the historical diagnostic path retains the raw mode string, including
`unknown` or `unavailable`, when all three entities exist and both power values
are numeric. Restoration still fails safe by explicitly selecting Self Use and
clearing both targets when feedback cannot form an observation.

## Invariants

- Diagnostic gate order, ownership and safety-lock behavior remain unchanged.
- Error text and missing-versus-invalid distinction remain unchanged.
- Raw diagnostic mode behavior remains unchanged.
- No command plan, service ordering, retry, timer or Store payload changes.
- Automatic control continues to reject `unknown` and `unavailable` modes.

## Non-goals

- Do not merge automatic and manual controller ownership.
- Do not change diagnostic eligibility, power limits or duration limits.
- Do not reinterpret an unavailable mode or alter fail-safe restoration.
- Do not extract inverter policy or reconciliation in this seam.

## Deliverables

- The immutable feedback snapshot retains both filtered automatic mode and raw
  reported mode, plus mapped-entity presence.
- Manual diagnostics consume the common snapshot through a legacy-compatible
  diagnostic observation view.
- Focused tests freeze all three diagnostic outcomes.

## Compatibility

No entity, attribute, configuration field, Store payload, service payload,
reason, timer or public interface changes. The shared boundary reads the same
three mapped entities synchronously and uses the existing `power_to_kw`
conversion.

## Test plan

- Missing mapped entity preserves the actuator-feedback error.
- Invalid numeric power preserves the power-feedback error.
- Raw `unavailable` mode with valid numeric powers remains a diagnostic
  observation while automatic feedback remains unavailable.
- Timed start, stop, restoration, restart and bounded-retry tests.
- Full frozen contracts and previous-release rehearsal.

## Rollback

Revert this commit. The automatic controller can continue using the snapshot;
manual diagnostics return to their independent read path. No stored data or
state conversion is involved.

## Acceptance evidence

- 106 focused observation, diagnostic, ZEROHERO and lifecycle tests passed.
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
- [x] Operational soak complete where required — no behavior change
