# OM-XXX — Outcome

## Problem and evidence

Describe the concrete maintainability problem and the evidence that it exists.

## Existing contract

Record current inputs, outputs, state transitions, public entities and
attributes, persisted state, service calls and timing.

## Invariants

- List every behaviour that must remain unchanged.
- Include Safety Lock, ownership, failure and restoration obligations where
  applicable.

## Non-goals

- Identify adjacent cleanup, naming or feature work deliberately excluded.

## Deliverables

- List code, tests, generated artifacts and documentation that will exist.

## Compatibility

Address entity and unique IDs, state values, public attributes, configuration
keys, stored payloads, dashboards, automations, Fleet, Recorder and downgrade.

## Test plan

- Characterisation written before implementation.
- Lifecycle, restart, reload and reconfigure cases.
- Missing, stale, delayed, contradictory and out-of-order evidence where
  applicable.
- Ordered service-call and persistence trace comparison.

## Rollback

Explain how to reverse the change without losing state or leaving hardware in
an HEO-owned mode.

## Acceptance evidence

List exact local and CI commands, snapshots, review results and canary evidence.

## Completion record

- [ ] Existing behaviour characterised
- [ ] Implementation complete
- [ ] Compatibility checks passed
- [ ] Documentation and roadmap updated
- [ ] Independent review complete
- [ ] Rollback demonstrated
- [ ] Operational soak complete where required
