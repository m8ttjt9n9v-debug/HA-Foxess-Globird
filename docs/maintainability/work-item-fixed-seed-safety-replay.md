# OM-007 — fixed-seed Safety Lock lifecycle replay

## Problem and evidence

Named lifecycle fixtures prove the Safety Lock at known incident boundaries,
but the maintainability scorecard still identifies broader generated transition
coverage as incomplete. A regression can therefore pass a fixed collection of
examples while failing when legitimate state changes and reloads are combined
in an unfamiliar order.

## Existing contract

With Local Modbus ownership and automatic control otherwise configured, Safety
Lock is an absolute no-write boundary. It must hold for fresh, unavailable,
contradictory and externally forced FoxESS feedback, across config-entry
reloads. The public safety state remains visible; no actuator command may be
issued or persisted as an HEO-owned session.

## Invariants

- The replay uses only the existing Home Assistant lifecycle harness and fake
  mapped FoxESS entities.
- Each generated trace has a stable named seed and a reproducible event list.
- Safety Lock permits no `number.set_value` or `select.select_option` call for
  the mapped FoxESS entities, regardless of event order.
- The test changes no controller, timer, configuration, entity, persistence or
  service contract.

## Non-goals

- This is not a physical/economic simulator or a substitute for named incident
  fixtures.
- It does not expand HEO authority, introduce a random runtime dependency, or
  test third-party FoxESS/Tessie behaviour.
- It does not authorize Phase 8 scheduling work or a production rollout.

## Deliverables

- A fixed-seed generator and a 100-event synthetic Home Assistant replay in
  the lifecycle harness.
- An assertion of an empty ordered FoxESS service-call trace after every event
  and reload boundary.
- Scorecard and incident-catalogue evidence updates.

## Compatibility

The work is test and documentation only. It changes no runtime source,
configuration key, Store payload, entity contract, dashboard, Fleet payload,
Recorder statistic or downgrade path.

## Test plan

- Seed canonical mapped telemetry, then replay 100 deterministic changes drawn
  from battery SoC, grid and house power, unavailable telemetry, external work
  mode/force-power feedback and config-entry reloads.
- Record the seed and event ordinal in every failure assertion.
- Run the existing lifecycle harness, focused Safety Lock tests, full suite and
  Ruff.

## Rollback

Revert the test and documentation commit. No persistent state or hardware
command exists to restore.

## Acceptance evidence

- The fixed-seed replay passes with no FoxESS service calls.
- Existing Safety Lock and lifecycle fixtures remain green.
- Full suite and repository-wide Ruff pass.

On 2026-09-21, the deterministic 100-event replay passed with no captured
FoxESS command. The complete 975-case suite passed in runner-safe batches, as
did repository-wide Ruff. The test is pure harness coverage: it has no live
site, package, release or hardware side effect.

## Completion record

- [x] Existing behaviour characterised
- [x] Implementation complete
- [x] Compatibility checks passed
- [x] Documentation and roadmap updated
- [ ] Independent review complete
- [x] Rollback demonstrated
- [ ] Operational soak complete where required
