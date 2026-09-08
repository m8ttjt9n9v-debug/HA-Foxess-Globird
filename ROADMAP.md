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
- [x] Faithful Working Single Phase Pilot Site ZEROHERO export core: protected-energy calculation,
  fixed-power plan, latest start, persistent session latch, allowance counter,
  retry bounds, and deliberate Self Use finish.
- [x] Faithful occupancy-aware house-demand learning: persistent Auto/Home/Away
  policy, conservative all-person away confirmation, distinct occupied/away
  fallbacks, restart-persistent base and optional heater histories, paired P80
  maturity, one selected protection budget, and over-gap rejection.
- [x] Pure Working Single Phase Pilot Site free-window EV current planner with golden branch-order
  tests, separate charge-policy/anti-pause limit planning, and a topology-aware
  daily-allowance ceiling that is inert for ordinary sessions that fit.
- [x] Fail-closed direct-EVSE command boundary and Tessie service adapter.
- [x] Explicit direct-path commissioning schema and restart-serializable
  three-minute feedback primitive with coverage/source-validity evidence.
- [x] Independent, default-off direct-EVSE runtime with matched sampling,
  allowance projection, ordered Tessie commands, feedback confirmation,
  restart-persistent state, and a three-attempt anti-flapping latch.
- [x] Safety-Lock rehearsal planning with visible ordered `would_*` actions,
  zero retry-state mutation, and an independently closed service adapter.
- [x] Auto/Home/Away EV location policy with cable and charge-state evidence.
- [x] Smart-socket command/runtime preserving staged current, explicit physical
  ceiling, outlet settling, periodic retry, zero-demand power policy, ordered
  charge start, restart state, and delayed gate rechecks.
- [x] Restart-serializable smart-socket `no_power` recovery state machine and
  runtime:
  sustained/coherent evidence, current-first sequence, confirmed outlet cycle,
  settle/restart, one-attempt latch, timeout faults, and sustained-health rearm.
- [x] Faithful, default-off solar-spill EV charging: coherent signed grid,
  battery-flow, and Tessie telemetry; battery-full/vehicle-room/export-window
  gates; reconstructed live surplus; whole-step current; and protected-baseline
  restoration.
- [x] Faithful, default-off latest-start pre-free EV backfill: protected export
  budget, vehicle wall-energy room, additional-power calculation, backwards
  scheduling, restart-persistent phase/start, live current reduction, and
  export-session exclusion.
- [x] Faithful Tessie daily-driving learning: exact free-window-boundary
  cumulative-meter deltas, restart-persistent 28-sample/35-day history, P85
  selection, configured arrival reserve, full-window fallback, actuator-step
  rounding, and the original general/free/override charge-limit policy.
- [x] Integration-owned persistent charge-to-full operator switch, with
  state-preserving migration from the pilot-style external helper on first use
  and no setup mapping or weakened safety gate.
- [x] Conservative setup discovery for FoxESS Modbus and Tessie roles:
  integration/domain-aware matching, single-device cohort selection,
  ambiguity rejection, disabled-entity filtering, and stale-only reconfigure
  suggestions without inferred signs, limits, ownership, or write authority.

## Removed pending a faithful port

These behaviors existed in earlier HEO releases as simplified or newly written
controllers. They were removed because passing tests did not demonstrate
Working Single Phase Pilot Site parity.

- [x] Remove automatic FoxESS free-window charging/reconciliation that had no
  canonical pilot-site source. It is not represented as a port.
- [x] Active Tessie automatic current/session adapter for the direct-EVSE
  free-window path. It remains uncommissioned and default-off.
- [x] Connect the tested whole-site daily-free-energy ceiling to explicit,
  auditable house, FoxESS, and EV projections.
- [x] Pure EV/house priority, guaranteed-current, service-overrun, settle, and
  feedback-hold policy.
- [x] Connect the matched three-minute grid/current primitive and settling
  behavior to runtime state sampling and the direct-path planner.
- [x] Solar-spill EV charging after the battery is full.
- [x] Latest-start, reserve-aware pre-free EV backfill.
- [x] Connect the characterized smart-socket command and recovery state machines
  to runtime with restart storage and delayed gate rechecks verified.
- [x] Tesla location Auto/Home/Away overrides, including the presence gates
  consumed by solar-spill and pre-free control.
- [x] Learned Tesla driving demand, arrival reserve, and charge-target policy.
  The mapped cumulative Tessie lifetime-energy sensor supplies the source data;
  no trip or departure-time inference was added.

## Required extensions and investigation

- [x] Make the free-window allowance topology-aware for arbitrary phase
  count, per-phase service limits, charger phases, voltage, and commissioned
  current limits without changing its base decisions. Multiphase active control
  requires an explicit most-loaded-phase signed current mapping.
- [x] Add coherent-source validity and matched-sample validation to the active
  free-window EV decision. Other future multi-sensor policies retain this rule.
- [ ] Add durable Home Assistant service-call and direct-Modbus transition
  tracing sufficient to identify any post-test or time-boundary writer.
- [ ] Read and record FoxESS schedule registers where supported, without writing
  them, and distinguish firmware capability from assumptions.
- [ ] Design a cloud-schedule adapter only after the full schedule/remaining-mode
  semantics are proven. Never substitute mixed local Modbus commands.
- [ ] Only if explicitly requested as new functionality, design a default-off
  local-Modbus battery free-charge extension after writer tracing and schedule
  interaction are proven. This is not required for canonical source parity.
- [ ] Replace manual dashboard copying with an upgrade-safe, integration-owned
  dashboard delivery mechanism. Evaluate a generated Lovelace dashboard and
  reusable strategy/cards; preserve user overlays and custom cards, carry an
  explicit dashboard schema version, preview migrations, and never silently
  overwrite a user's dashboard. HACS upgrades must be able to deliver compatible
  dashboard changes without raw-YAML copy and paste.
- [ ] Add an explicit manual inverter-mode recovery surface for Local Modbus
  ownership. Self Use, Force Charge, and Force Discharge require confirmed
  profile support and mapped feedback; Backup is shown only when the
  commissioned inverter advertises or has independently proven that capability.
  A manual selection must suspend automatic reconciliation for a visible,
  persistent hold so HEO cannot immediately undo the operator's command. Force
  modes must require explicit power and duration, remain bounded, show direct
  feedback, and restore or hand control back deliberately. Define Safety Lock,
  ownership, confirmation, timeout, restart, and cloud-scheduler interactions
  before exposing buttons.
- [x] Package the proven seven-view dashboard information architecture using
  HEO-owned entities, with site-specific Tessie, weather, room, and equipment
  cards explicitly retained as local overlays.

## Definition of done for each control item

An item cannot be checked off until it has:

1. A provenance table mapping every input, decision branch, output, and
   persistent latch to the Working Single Phase Pilot Site source.
2. Golden characterization tests for Working Single Phase Pilot Site behavior before extension.
3. Separate tests for the reference single-phase and configurable multi-phase
   sites.
4. No literal site limits, times, entity IDs, or tariff assumptions in logic.
5. Fail-closed tests for missing, stale, contradictory, and restarted state.
6. Ownership and rollback tests proving it cannot fight another writer.
7. Updated source-of-truth, requirements, user documentation, and changelog.
