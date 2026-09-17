# OM-702B — Wire immutable FoxESS feedback into automatic control

## Problem and evidence

OM-702A introduced an unwired snapshot whose values match the legacy
controller helpers. `ActiveFoxessController` still performed separate direct
state reads for mode, power, supported options and number maxima during one
reconciliation cycle.

## Existing contract

The automatic controller evaluates its gates before reading actuator feedback.
With complete mappings and site telemetry, unavailable mode or either
force-power value marks retained sessions source-unavailable and publishes
`foxess_feedback_unavailable`. Charge and export policy retain their existing
option and native maximum requirements.

## Invariants

- Gate precedence and no-write outcomes remain unchanged.
- One snapshot supplies every inverter feedback value used in one cycle.
- Charge-before-export session ownership and policy order remain unchanged.
- No command plan, reason, retry, save or service-call ordering changes.
- Manual diagnostics remain on their existing read path in this seam.

## Non-goals

- Do not extract gate or policy evaluation.
- Do not remove retained legacy helpers until this wiring passes all gates.
- Do not change manual-test observation, scheduling or controller timers.

## Deliverables

- Automatic reconciliation captures one `FoxessFeedbackSnapshot` after all
  absolute gates and mapping/telemetry checks pass.
- Charge and export reconciliation consume the frozen capability and maximum
  values from that snapshot.
- Existing lifecycle and command traces remain unchanged.

## Compatibility

No entity, attribute, configuration field, Store payload, service payload,
reason or timing contract changes. The snapshot reads the same three mapped
entities synchronously through the already-characterized conversion rules.

## Test plan

- Observation shadow parity.
- Gate precedence and unavailable-feedback behavior.
- Charge and export start, active, finish and recovery traces.
- Reload/restart equivalence across every retained session phase.
- Manual diagnostic regression even though it remains unwired.
- Full frozen contracts and previous-release rehearsal.

## Rollback

Revert this wiring commit. The separately committed observation boundary may
remain unused. No storage migration or state conversion is involved.

## Acceptance evidence

- 102 focused observation, inverter, lifecycle and manual-diagnostic tests.
- Full suite, Ruff, compatibility contracts and rollback rehearsal required
  before the commit.
- `README.md` unchanged.

## Post-wiring cleanup

After the wired implementation passed the complete gate, the four duplicate
legacy helpers for force-power conversion, native maxima and mode capability
were removed in a separate commit. Their characterization remains as literal
snapshot expectations. The unrelated EV home/cable read helper remains until
the EV observation phase, preserving scope separation.

## Completion record

- [x] Existing behaviour characterised
- [x] Implementation complete
- [x] Compatibility checks passed
- [x] Documentation and roadmap updated
- [ ] Independent review complete
- [x] Rollback demonstrated
- [ ] Operational soak complete where required
