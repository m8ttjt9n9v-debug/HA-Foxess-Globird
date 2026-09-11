# Project roadmap

Status here describes behavioral parity, not merely the presence of code.

## Completed and retained

- [x] Observer ledger with unit/sign normalization and persisted daily,
  free-window, and ZEROHERO interval meters.
- [x] Bounded canonical telemetry layer with explicit grid, battery, solar, and
  service-current directions; W/kW/MW conversion; timestamp freshness and
  provenance; pilot paired battery magnitudes; migration lock; shared automatic
  write gate; canonical entities; and single-/three-phase golden tests.
- [x] Configurable tariff, battery reserve, phase, service, inverter, EV, export,
  and timing inputs without site entity IDs in control code.
- [x] Explicit FoxESS ownership: Observer, Local Modbus, or FoxCloud Scheduler.
- [x] Separately identified, default-off Local Modbus free-window battery
  charging extension: configured 24-hour window and SoC start qualification,
  fixed bounded power, persistent session latch, finite feedback retries,
  noon/midnight regression coverage, and deliberate Self Use restoration.
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
- [x] Configuration-driven daily EV ready-by allocation extension: ready-cycle
  protection, live post-midnight energy calculation, proportional discretionary
  share, discrete inverter-percentage/service cap, latest-start latch, confirmed
  wall-energy accounting, shortfall reporting, cloud-compatible Tessie-only
  operation, and prospective Local-Modbus export protection.
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

## Confirmed bugs

- [x] Preserve every submitted mapping and value when setup or reconfiguration
  validation fails. The form must redisplay the user's complete attempted
  configuration and attach errors to the relevant section; it must not rebuild
  the page from discovery defaults and force manual entity mapping to restart.
  Completed in v0.12.6.

- [ ] Allow reconfiguration to complete when the operator changes FoxESS
  ownership from Local Modbus to Observer or FoxCloud Scheduler while
  Local-Modbus-only solar-spill or pre-free EV options remain enabled. Do not
  silently enable those policies and do not block the ownership change. Save
  the safe non-Modbus owner, then show a dedicated follow-up warning that the
  incompatible EV stages are suspended until Local Modbus ownership returns,
  with a clear option to disable them. The emergency Safety Lock must remain an
  immediate, independent block on every HEO-owned FoxESS and Tessie command.

- [x] Fix paired battery-magnitude freshness handling. During steady charging or
  discharging, the inactive FoxESS magnitude can remain exactly zero without a
  new Home Assistant `last_updated` timestamp. HEO currently marks the combined
  `sensor.home_energy_battery_power` unavailable when that unchanged zero ages
  beyond the telemetry limit, even while the active magnitude and signed battery
  sensor remain fresh. Do not solve this by accepting an arbitrary stale zero.
  Prefer a fresh, explicitly mapped signed battery-power sample when the pair is
  not fresh, or establish coherent same-device reporting evidence. Add regression
  coverage for steady charge, steady discharge, direction changes, disconnected
  inputs, restart, and genuine stale telemetry before the distributed power-flow
  card relies on the normalized sensor. Completed in v0.12.7 with a bounded
  fresh signed-sensor fallback used only when staleness is the pair's sole
  failure.

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

### Human commissioning and dashboard usability

- [ ] **HIGH PRIORITY — replace the monolithic setup and reconfigure form with
  a shared, multi-page commissioning flow.** Start with a short Site and
  Capabilities page, followed by small logical pages for Battery, Inverter,
  Grid and Tariff, House, Car and Charger, EV Policies, and Automation and
  Safety, then a plain-language Review and Apply page. Reconfigure should also
  provide a section menu so an operator can revisit one area without traversing
  or re-entering every unrelated field.

  Validate each page independently. A successful Next action must merge that
  page into an in-flow working draft; returning to the page must show the
  validated values, and an error on any later page must never discard completed
  pages or rebuild manual mappings from discovery suggestions. An invalid page
  must retain all of its submitted values and attach specific errors to that
  page. Run cross-page validation at Review and direct the operator to the
  relevant section without clearing the draft. Apply the complete configuration
  and reload HEO only after final confirmation, so the live config entry is
  never left partially updated. Cancelling before Apply must leave the existing
  entry unchanged. Initial setup and reconfigure must share the same page
  schemas, validation, descriptions, and tests so the two flows cannot drift.

  The first page must include explicit **Configure solar?** and **Configure EV
  automation?** capability choices. When solar is disabled, hide all solar
  mappings and solar-dependent policy fields, skip their validation, and expose
  canonical solar power as a deliberate `0` with provenance indicating that
  solar was configured absent; do not require a fake zero-valued helper or
  infer absence from unavailable telemetry. Solar-spill control must remain
  unavailable while the capability is disabled. Re-enabling solar must restore
  previously saved mappings rather than deleting them. Add navigation,
  checkpoint-retention, cancellation, conditional-page, old-entry, and final
  cross-page validation regression coverage.

- [ ] Complete the **Configure EV automation?** capability behavior introduced
  by the multi-page flow. When
  disabled, hide EV telemetry, actuator, capacity, floor, reserve, charger,
  inverter, current, voltage, learning, and policy fields; skip all EV-specific
  validation; and create no impression that Tessie or an EV is required for a
  FoxESS-only installation. Re-enabling it must preserve previously saved EV
  configuration.

- [x] Define the clean disposable test installation as the staging and
  acceptance template for the distributed dashboard. Use the Working Single
  Phase Pilot Site as the design reference, iterate on the clean-site dashboard
  until accepted, and then promote that approved configuration into the
  repository rather than maintaining an independently designed example.

- [x] Add a mandatory confirmation step before automatic Local Modbus battery
  charging can be enabled. Show the exact window in 24-hour notation, its
  duration, a compact 24-hour timeline, and a second explicit confirmation for
  any window that crosses midnight. Provider windows can differ by account
  signup date, so the UI must tell the operator to verify the actual tariff.
- [ ] Publish a pre-commissioning worksheet and guided setup introduction that
  lists every required value and mapped entity. Explain how to inspect live
  entity states under known import/export, battery charge/discharge, and solar
  generation conditions before confirming sensor directions.
- [ ] Explain the optional paired battery charge/discharge magnitude sensors in
  plain language, including when they are preferable to one signed battery
  power sensor and that both members of the pair are required.
- [ ] Fix bounded FoxESS diagnostic submission so requested power is clamped to
  the smaller of the commissioned inverter limit and the mapped native number
  maximum. A rejected service call must not leave a diagnostic session latched
  as active or require a manual Stop action before retrying.
- [ ] Add an upgrade-safe dashboard configuration surface for occupied and away
  house fallback energy, away-confirmation duration, house occupancy policy,
  EV supply path, EV location policy, free-window priority, all telemetry sign
  directions, Charge to Full timeout, whole-site free-energy allowance and
  margin, daily protected EV energy, daily ready-by time, and outside-window EV
  inverter percentage.
- [ ] Put the operational switches on that configuration surface: Local Modbus
  battery charging, ZEROHERO export, EV-before-export priority and threshold,
  automatic EV control, and Safety Lock. Descriptions must be sourced from one
  maintained documentation vocabulary rather than duplicated dashboard text.
- [ ] Add the normalized helpers required by the Working Single Phase Pilot
  Site power-flow card: EV charge rate in kW and house load excluding EV load.
  Define the input topology explicitly so an already EV-exclusive house sensor
  is not reduced twice, and fail unavailable when the subtraction cannot be
  supported by fresh compatible telemetry.
- [ ] Add a live site-power card that clearly separates house load excluding EV,
  EV charge rate, solar, battery, grid import, and grid export. Battery and EV
  SoC controls should also show current charge/discharge power, even when that
  requires larger cards.
- [ ] Add a plain-language Current Plan surface describing the next house,
  battery, export, and EV actions and their scheduled times. Never label EV
  charging as house load in the human-facing presentation.
- [ ] Show configured battery-charge and export windows on a persistent 24-hour
  dashboard timeline, including explicit next-day presentation for overnight
  windows.
- [ ] Build the Advanced view from the proven Working Single Phase Pilot Site
  calibration layout, while retaining configuration-driven entities and
  upgrade-safe user overlays.
- [ ] Make dashboard help extensive but maintainable from the same canonical
  documentation source as setup, entities, and README guidance.
- [ ] Add safe Tessie convenience controls for unlock, front trunk, rear trunk,
  and window venting, with explicit confirmation appropriate to each action.
- [ ] Add solar forecasting and weather context. First characterize whether and
  how the Working Single Phase Pilot Site currently uses forecast, temperature,
  heating-demand, and solar relationships; port that evidence before extending
  control decisions.
- [ ] Reduce unnecessary hyphenated prose during a dedicated human copy-edit
  without changing established entity IDs or configuration keys.
- [ ] Add a Charge to Full decision estimate: completion time, predicted grid
  versus battery contribution, tariff-aware total cost, and average cost per
  kWh, so the operator can compare home charging with another charging option.
- [x] Rename the project **FoxESS GloBird Tesla Energy Orchestrator** now that it
  includes active, independently gated battery, export, and EV control paths.
  Retain the stable `home_energy_orchestrator` domain and entity IDs so upgrades
  do not break existing installations.
- [ ] Reassess 1.0 readiness only after sustained trials of automated battery
  buying, ZEROHERO selling, and EV charging on the Working Single Phase Pilot
  Site and the H3 site. Publish only independently proven inverter/battery
  combinations as known working.

- [x] Make the free-window allowance topology-aware for arbitrary phase
  count, per-phase service limits, charger phases, voltage, and commissioned
  current limits without changing its base decisions. Multiphase active control
  requires an explicit most-loaded-phase signed current mapping.
- [x] Make free-window allowance accounting explicit for house meters that
  include EV charging. Subtract measured EV power exactly once only when the
  operator selects that topology, preserve the pilot's already EV-exclusive
  mapping by default, fail closed without valid current evidence, and expose
  both projection inputs diagnostically. Completed in v0.12.8.
- [x] Defer only a vehicle-SoC-triggered early allowance recalculation while
  requested and actual EV current are converging in whole-house topology.
  Retain the normal three-minute boundary and never defer service-overrun
  evaluation. Completed in v0.12.10.
- [x] Add coherent-source validity and matched-sample validation to the active
  free-window EV decision. Other future multi-sensor policies retain this rule.
- [ ] Add durable Home Assistant service-call and direct-Modbus transition
  tracing sufficient to identify any post-test or time-boundary writer.
- [ ] Read and record FoxESS schedule registers where supported, without writing
  them, and distinguish firmware capability from assumptions.
- [ ] Design a cloud-schedule adapter only after the full schedule/remaining-mode
  semantics are proven. Never substitute mixed local Modbus commands.
- [x] Implement the explicitly requested default-off Local Modbus battery free-
  charge extension as new functionality, not canonical source parity. It reuses
  HEO's mapped FoxESS adapter and ZEROHERO session boundaries, requires exclusive
  Local Modbus ownership, and does not claim to identify or suppress unrelated
  writers. Durable writer tracing remains a separate unfinished investigation.
- [x] Add the deliberately narrow first stage of opt-in **EV-before-export**
  arbitration: below a user-adjustable EV SoC target, prevent a new automatic
  ZEROHERO export or stop an HEO-owned active one without changing the saved
  export request. Fail closed on invalid EV SoC, expose integration-owned
  controls/status, and leave existing behavior untouched when disabled.
- [ ] Extend EV-before-export only after separately specifying home/connected
  qualification, EV charge activation, eligible energy sources, protected and
  paid-grid boundaries, hysteresis, withheld-energy accounting, and interaction
  with the daily-ready allocation. The simple gate must not silently grow into
  an unreviewed energy-transfer controller.
- [ ] Add an opt-in weekly **EV ready-by target** policy with three user-facing
  modes: **Off**, **Learned with overrides**, and **User schedule**. Each weekday
  has an optional ready time and desired SoC; an unset day means no departure
  target. User schedule uses only those entries. Learned mode requires a new,
  independently validated history of actual home-departure times and departure
  SoC needs—existing cumulative-energy P85 learning does not provide this—and
  any configured weekday entry overrides that day's learned target. Calculate
  the latest safe start from current SoC, usable capacity, charging efficiency,
  commissioned charging power, and all eligible tariff/free windows, then
  continuously re-plan from confirmed charging feedback. Define missed-target,
  low-confidence, away, unplugged, DST/time-zone, overnight-boundary, conflicting
  target, and restart behavior before actuation. The dashboard must show the
  source of today's target (none, learned, or user override), confidence,
  required energy, planned start, and whether the target is currently achievable.
- [ ] Replace manual dashboard copying with an upgrade-safe, integration-owned
  dashboard delivery mechanism. Evaluate a generated Lovelace dashboard and
  reusable strategy/cards; preserve user overlays and custom cards, carry an
  explicit dashboard schema version, preview migrations, and never silently
  overwrite a user's dashboard. HACS upgrades must be able to deliver compatible
  dashboard changes without raw-YAML copy and paste.
- [ ] Add an explicit manual inverter-control hold for Local Modbus ownership,
  using the mapped FoxESS Modbus entities instead of reproducing inverter
  profiles, register writes, force-power bounds, or remote-control watchdog
  behavior. The dashboard mirrors only the options currently advertised by the
  mapped work-mode select, so Backup appears only when FoxESS Modbus exposes it;
  Force Charge and Force Discharge use that integration's mapped native power
  controls and limits.

  Before forwarding a manual mode selection, HEO must persist a visible manual
  hold and cancel every HEO-owned inverter session that could later restore or
  reassert another mode, including automatic export and an active diagnostic.
  Cancelling for a manual handoff must clear HEO latches/timers without sending
  a competing Self Use restoration over the operator's requested mode. While
  the hold is active, no HEO automatic inverter reconciliation may run. A
  separate deliberate action returns control to automation; merely choosing
  Self Use does not silently resume it. A timed force-mode convenience may be
  added later, but is not required for the first native-entity surface.

  Safety Lock and exclusive Local Modbus ownership remain mandatory. HEO can
  suppress only its own writers: FoxCloud scheduling and legacy or unrelated
  Home Assistant inverter automations must already be disabled and cannot be
  treated as cancelled merely because the HEO hold is active. Test command
  ordering, restart persistence, active-session handoff, missing entities,
  changing advertised options, and explicit release before exposing controls.
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
