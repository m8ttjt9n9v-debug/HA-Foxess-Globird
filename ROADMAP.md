# Project roadmap

Status here describes behavioral parity, not merely the presence of code.

## Completed and retained

- [x] Observer ledger with unit/sign normalization and persisted daily,
  free-window, and ZEROHERO interval meters.
- [x] Configurable tariff, battery reserve, phase, service, inverter, EV, export,
  and timing inputs without site entity IDs in control code.
- [x] Explicit FoxESS ownership: Observer, Local Modbus, or FoxCloud Scheduler.
- [x] Safety Lock, rehearsal behavior, redacted diagnostics, and bounded manual
  FoxESS tests with Self Use restoration.
- [x] Faithful Mangerton ZEROHERO export core: protected-energy calculation,
  fixed-power plan, latest start, persistent session latch, allowance counter,
  retry bounds, and deliberate Self Use finish.
- [x] Restart-persistent house-demand sampling with conservative P80 selection,
  sample retention, fallback, and over-gap rejection.
- [x] Pure Mangerton free-window EV current planner with golden branch-order
  tests, separate charge-policy/anti-pause limit planning, and a topology-aware
  daily-allowance ceiling that is inert for ordinary sessions that fit.
- [x] Fail-closed direct-EVSE command boundary and Tessie service adapter,
  still disconnected from the automatic gate pending mappings and runtime
  reconciliation tests.
- [x] Explicit direct-path commissioning schema and restart-serializable
  three-minute feedback primitive with coverage/source-validity evidence.

## Removed pending a faithful port

These behaviors existed in earlier HEO releases as simplified or newly written
controllers. They were removed because passing tests did not demonstrate
Mangerton parity.

- [ ] Automatic FoxESS free-window charging and completion reconciliation.
- [ ] Active Tessie automatic current/session adapter. Its independent,
  default-off intent gate is restored but deliberately remains non-actuating.
- [ ] Connect the tested whole-site daily-free-energy ceiling to explicit,
  auditable house, FoxESS, and EV projections.
- [x] Pure EV/house priority, guaranteed-current, service-overrun, settle, and
  feedback-hold policy.
- [ ] Connect the matched three-minute grid/current primitive and settling
  behavior to runtime state sampling and the direct-path planner.
- [ ] Learned Tesla driving demand, arrival reserve, and charge-target policy.
- [ ] Solar-spill EV charging after the battery is full.
- [ ] Latest-start, reserve-aware pre-free EV backfill.
- [ ] Explicit smart-socket/direct-EVSE selection and smart-socket recovery.
- [ ] Occupancy and Tesla location Auto/Home/Away overrides.

## Required extensions and investigation

- [ ] Make the faithful Mangerton policy topology-aware for arbitrary phase
  count, per-phase service limits, charger phases, voltage, and commissioned
  current/power limits without changing its base decisions.
- [ ] Add coherent-source freshness and matched-sample validation for all
  multi-sensor control decisions.
- [ ] Add durable Home Assistant service-call and direct-Modbus transition
  tracing sufficient to identify any post-test or time-boundary writer.
- [ ] Read and record FoxESS schedule registers where supported, without writing
  them, and distinguish firmware capability from assumptions.
- [ ] Design a cloud-schedule adapter only after the full schedule/remaining-mode
  semantics are proven. Never substitute mixed local Modbus commands.
- [ ] Package dashboard views that expose the faithfully ported controls without
  embedding personal entity IDs.

## Definition of done for each control item

An item cannot be checked off until it has:

1. A provenance table mapping every input, decision branch, output, and
   persistent latch to the Mangerton source.
2. Golden characterization tests for Mangerton behavior before extension.
3. Separate tests for the reference single-phase and configurable multi-phase
   sites.
4. No literal site limits, times, entity IDs, or tariff assumptions in logic.
5. Fail-closed tests for missing, stale, contradictory, and restarted state.
6. Ownership and rollback tests proving it cannot fight another writer.
7. Updated source-of-truth, requirements, user documentation, and changelog.
