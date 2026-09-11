# Changelog

## 0.12.8 — Stable whole-house EV allowance accounting

- Add an explicit **Mapped house-load sensor includes EV charging** topology
  setting. When enabled, the free-window allowance projection removes measured
  EV power exactly once before projecting non-EV house demand. This prevents a
  whole-house meter from making the controller alternate between high and low
  current as its own Tesla command changes the mapped load.
- Preserve the Working Single Phase Pilot Site's EV-exclusive house-load
  behavior by default. Invalid actual-current feedback fails the optional
  correction closed instead of guessing, and controller diagnostics expose the
  projected house load and removed EV power.
- Prefill the numeric battery-capacity fallback from an unambiguous live FoxESS
  Modbus capacity entity when available. Runtime continues to prefer that live
  entity; the numeric value is now labelled as fallback only.

## 0.12.7 — Battery telemetry recovery

- Keep the Working Single Phase Pilot Site's paired charge-minus-discharge
  battery source authoritative while both magnitudes are fresh.
- When an inactive zero magnitude alone stops refreshing, recover from the
  separately mapped fresh signed battery-power sensor and expose the fallback
  in canonical sensor provenance.
- Continue to fail unavailable through genuine telemetry outages, disconnected
  inputs, invalid magnitudes, future timestamps, or a stale signed fallback.

## 0.12.6 — Safe single-phase current fallback

- Reject power entities from the optional most-loaded-phase current mapping;
  that role must report amperes. A single-phase site may leave the mapping
  blank and derive signed service current from normalized grid power and its
  configured voltage.
- If an upgraded single-phase entry already contains a power sensor in the
  current role, fail over to that same grid-power derivation instead of making
  EV service headroom permanently unavailable. Multiphase sites continue to
  fail closed without explicit most-loaded-phase current evidence.
- Preserve all submitted mappings and limits when setup or reconfiguration
  validation finds an error, so correcting one field no longer resets the rest
  of a manually commissioned form.

## 0.12.5 — Truthful controller presentation

- Report the commissioned HEO control mode as the orchestrator status instead
  of exposing the house-learning ledger's legacy `observer_only` reason. The
  ledger reason remains available as a diagnostic status attribute.
- Keep calculating the underlying economic export candidate, but expose its
  planned start, energy and duration only when automatic export is effectively
  permitted. An EV-before-export hold now reports
  `withheld_ev_below_target` rather than presenting a dormant export as an
  imminent action.
- Rename the Home Assistant device model from Observer to Energy Orchestrator.

## 0.12.4 — Protected baseline with unavailable headroom

- Treat a live outside-window service ceiling below the physical EV charging
  minimum as the existing fail-closed `outside_power_ceiling_too_low` planning
  result. Discretionary backfill remains blocked, while the separately protected
  baseline can still reconcile to its configured minimum.
- Add the live-derived zero-service-ceiling regression exposed while verifying
  v0.12.3 on the disposable commissioning site.

## 0.12.3 — Tessie reconnect baseline

- Restore the Working Single Phase Pilot Site's interpretation of Tessie's
  current metadata: when the number entity advertises a zero minimum, one
  positive actuator step is the minimum physical charging command. This keeps
  an opted-in direct-EVSE outside-window policy at its configured protected
  baseline instead of selecting a false 0 A solar-spill target.
- Preserve pending daily-backfill stop reconciliation in the correct persisted
  state object so a Home Assistant restart cannot discard an unfinished stop.
- Add a live-derived regression for a Tesla reconnect outside the free window
  with Tessie's actual `min: 0`, `step: 1` metadata.

## 0.12.2 — Project identity

- Rename the integration **FoxESS GloBird Tesla Energy Orchestrator** to reflect
  its independently gated FoxESS battery, GloBird tariff, and Tesla charging
  control paths. Preserve the integration domain and entity IDs for upgrades.
- Record the normalized EV charge-rate and EV-exclusive house-load helpers
  required by the proven pilot power-flow card as explicit roadmap work.

## 0.12.1 — Explicit battery-schedule confirmation

- Show the submitted battery free-power window in unambiguous 24-hour notation,
  with its duration and a compact 24-hour timeline, before saving an enabled
  automatic charge request.
- Require a second explicit acknowledgement when the selected window crosses
  midnight. Provider windows may differ by account signup date, so confirmation
  directs the operator to verify the tariff for the specific account.
- Persist schedule confirmation separately from automation intent. Upgrades
  from v0.12 fail safe by disabling automatic battery charging until the new
  confirmation is completed; the dashboard switch cannot bypass it.
- Record the deferred commissioning, diagnostics, dashboard, Tessie, weather,
  documentation, copy-editing, cost-estimation, naming, and 1.0-readiness work
  requested during the first v0.12 live trial.

## 0.12.0 — Local Modbus free-window battery charging

- Add a separately identified, default-off scheduled house-battery Force
  Charge extension for exclusive Local Modbus ownership. It does not program
  FoxESS native schedule-period registers.
- Use the configured 24-hour free-window start/end and battery target. Fresh
  normalized SoC below target qualifies a new session; the session then remains
  fixed and latched until the window end to avoid target-boundary mode flapping.
- Request the commissioned inverter charge limit, bounded again by the mapped
  FoxESS force-charge number maximum. Clear discharge power, set charge power,
  wait, and then select Force Charge through the shared FoxESS adapter.
- Persist the session phase, frozen power, attempts and last-command timestamp.
  Reconcile direct mapped feedback every 30 seconds with at most three attempts,
  and deliberately restore Self Use after the window or when the independent
  charge request is disabled.
- Require Local Modbus ownership, the master FoxESS gate, verified telemetry
  directions, complete actuator mappings and Safety Lock OFF. FoxCloud
  ownership blocks the extension for the entire day.
- Add an integration-owned Automatic Battery Free Charge switch, status/power
  sensors, diagnostics, dashboard cards, provenance, restart tests, a noon-
  versus-midnight regression test, and overlapping-window rejection.

## 0.11.0 — opt-in EV-before-export gate

- Add the deliberately small first stage of EV-before-export arbitration. When
  explicitly enabled, EV SoC below the adjustable target withholds new
  automatic ZEROHERO export and deliberately ends an HEO-owned active export.
- Keep the saved Automatic ZEROHERO Export request unchanged, so normal export
  eligibility returns automatically when EV SoC reaches the inclusive target.
- Fail closed when the policy is enabled but EV SoC or its target is invalid or
  unavailable. With the policy disabled, existing export behavior is unchanged.
- Create an integration-owned priority switch, SoC-target number, status sensor,
  diagnostics, and dashboard controls. No external helper is required.
- This first stage does not start EV charging, choose an energy source, or allow
  paid-grid charging; those broader arbitration options remain roadmap work.

## 0.10.1 — deterministic Home Assistant service-call tests

- Wait for Home Assistant's event loop before asserting service-call events in
  the cloud-owner and outside-window general-limit tests. Runtime behavior is
  unchanged from 0.10.0.

## 0.10.0 — daily EV ready-by allocation

- Add a separate, configuration-driven extension around the pilot's retained
  latest-start backfill: daily protected EV wall energy, ready time,
  outside-window inverter percentage, and planning buffer.
- Use ready-to-ready accounting so Local-Modbus ZEROHERO export protects the
  following morning's remaining EV allocation. With FoxCloud ownership, use
  the current live battery/house ledger without pretending prior cloud export
  was controlled or that the allocation is guaranteed.
- Protect the remaining house budget once, then the remaining EV allocation,
  and offer a time-proportional share of any further discretionary energy.
  Cap the result by vehicle room, live energy, connector rating, commissioned
  service headroom, and whole actuator steps.
- Persist the ready-cycle deadline, confirmed delivered wall energy, session
  target, and frozen latest start. Expose planned energy/current/start,
  remaining allocation, delivered energy, and shortfall on the dashboard.
- Make Charge to Full the documented paid-grid exception outside the free
  window. It bypasses normal energy and inverter-percentage policy but retains
  Safety Lock, connector and service limits, and clears at full, disconnect
  after start, or its configured timeout.

## 0.9.0 — canonical telemetry normalization

- Replace scattered raw signed-power handling with one timestamp-aware
  canonical telemetry boundary. HEO now publishes import-positive grid/current,
  charge-positive battery, and generation-positive solar sensors with local
  source provenance and explicit freshness reasons.
- Add explicit direction selectors for grid, battery, solar, and optional
  service current, plus support for the Working Single Phase Pilot Site's
  separate non-negative charge/discharge battery sensors.
- Add a sign-commissioning confirmation that is cleared by v1 migration or any
  normalized source/direction change. Automatic FoxESS and EV writes fail
  closed until the operator verifies known physical states; diagnostics remain
  bounded by their existing independent guards.
- Add golden sign/unit/freshness tests for the pilot source shape and reversed
  FoxESS grid, inverter-battery, and CT2 readings.
- Remove the misleading entities-card aggregate toggle from the dashboard and
  separate the global Safety Lock from independent automation requests. Display
  the effective FoxESS and EV gates instead of presenting the status sensor's
  raw state as an operating mode.
- Record the observed EW11 single-client constraint: concurrent Modbus polling
  can lock the bridge even when only one Home Assistant instance is intended to
  write.
- Record roadmap requirements for upgrade-safe generated/reusable Lovelace
  surfaces and capability-driven, reconciliation-safe manual inverter recovery.

## 0.8.1 — integration-owned charge-to-full control

- Replace the confusing external helper mapping with the automatically created
  `switch.home_energy_ev_charge_to_full`.
- Preserve the pilot behavior: ON temporarily uses Tessie's advertised maximum
  charge limit and, in the managed free window, prioritizes the commissioned
  connector ceiling before service and allowance guards. OFF resumes normal
  learned/free-window targets.
- Preserve the effective state of an existing mapped
  `input_boolean.charge_to_full` during upgrade. The first use of the new HEO
  switch persists its state and removes that legacy mapping. No charging
  algorithm or safety gate is changed.

## 0.8.0 — faithful occupancy-aware house learning

- Port the Working Single Phase Pilot Site's persistent Auto/Home/Away house-
  energy policy. Auto assumes Home with no people, uncertain presence, or an
  incomplete away-confirmation interval; manual Away bypasses the delay.
- Preserve the existing restart-persistent base/whole-house P80 history and add
  an optional independent full-day heater P80 history at the configured free-
  window boundary. Both retain 28 samples for at most 35 days.
- When a heater is mapped, require seven valid samples in both streams before
  replacing the occupied fallback with base P80 plus heater P80. Away always
  uses its configured fallback. Without a heater mapping, the mapped house
  source remains the complete protected demand and can mature independently.
- Feed exactly one selected protected-house budget into export and reserve
  planning. Weather remains diagnostic and is not added as hidden demand.
- Add a persistent occupancy selector, transparent occupancy/base/heater
  sensors, redacted diagnostics, dashboard cards, and source-provenance tests.

## 0.7.0 — assisted FoxESS and Tessie discovery

- Inspect Home Assistant's entity registry during setup and reconfiguration and
  pre-fill high-confidence FoxESS Modbus and Tessie role mappings.
- Match by integration-owned entity identity, expected entity domain, and one
  unambiguous config-entry cohort. Disabled entities and loose near-name
  matches are excluded.
- Refuse automatic selection when two devices are equally plausible, preventing
  roles from being silently mixed across inverters or vehicles.
- Preserve every registered existing mapping. During reconfiguration, propose a
  detected replacement only for a missing role or a stale entity ID that no
  longer exists; no proposal is saved until the user reviews and submits.
- Keep sign conventions, battery semantics, electrical ratings, topology,
  ownership, commissioning, and all write gates explicitly user-confirmed.
- Add discovery fixtures based on the clean FoxESS/Tessie entity inventory and
  tests for ambiguity, disabled entities, stale mappings, and custom mappings.

## 0.6.0 — faithful Tessie daily-driving learning

- Port the exact free-window-boundary cumulative-energy snapshot. A sample is
  accepted only from the immediately preceding day and only when the lifetime
  meter has not decreased; missed days reset the baseline without fabricating
  a multi-day driving sample.
- Persist and retain the latest 28 valid samples for at most 35 days, then use
  the configured sample threshold and P85 daily energy exactly as the source.
- Port usable-capacity estimation, complete-free-window SoC gain, learning
  fallback, configured arrival reserve, actuator-step floor/ceiling rules, and
  general/free/charge-to-full limit selection.
- Retain the current Tessie limit while away or disconnected. While connected
  outside the free window, apply only the general charge limit and do not take
  ownership of charging current unless a separately enabled outside policy is
  active. Suppress repeated writes while identical feedback is pending.
- Extend only the source electrical conversion through configured EV phase
  count, with separate one-phase and three-phase characterization tests.
- Add seven learning/diagnostic sensors, Tesla-dashboard cards, installation
  requirements, and a source-to-runtime provenance table.
- Document that the canonical pilot used FoxESS internal/cloud free-window
  charging and contains no local automatic Force Charge writer. Such a writer
  is not a missing port and remains absent.

## 0.5.0 — faithful smart-socket runtime and recovery

- Connect the characterized Working Single Phase Pilot Site smart-socket path
  to the independent EV runtime. Preserve the source order: stage a bounded
  service-valid current, energise only the explicitly selected outlet, settle,
  recheck permissions, re-bound current, and then start charging.
- Retain the source zero-demand policy: do not remove outlet power inside the
  free window; outside it, remove power only when configured switching is
  enabled or the vehicle is no longer connected for planning.
- Connect restart-persistent one-shot `no_power` recovery. Require sustained
  fault and stable home/cable/charge-switch evidence, latch before physical
  action, confirm current and each outlet transition, observe configured dwell
  times, wait for Tessie to become writable after power returns, and recheck
  permission before every delayed transition.
- Rearm recovery only after configured sustained healthy charging or selection
  of Direct / EVSE, including when connection telemetry is unavailable. A
  failed episode remains latched, exposes its phase in sensors/diagnostics, and
  raises one persistent notification; a confirmed recovery dismisses it.
- Preserve the pilot's five-minute staged-current retry cadence as a configurable
  default so the 30-second runtime does not create a new rapid retry loop.
- Add active-runtime tests for ordered commands, Safety Lock non-mutation,
  disconnected outlet handling, direct-path rearm, delayed actuator recovery,
  one physical cycle per episode, and restart latch restoration.

## 0.4.0 — port-first reset and direct-EVSE parity

- Restore the proven dashboard's seven operational views—Overview, Tesla,
  House, Solar & Weather, Configuration, Advanced, and Manual—in the portable
  example. Shared cards use only HEO-owned entities; vehicle-native Tessie,
  weather, room, and site-equipment cards remain explicit local overlays.

- Port the Working Single Phase Pilot Site solar-spill EV controller behind a
  separate default-off option. It reconstructs current surplus from coherent
  signed grid, battery-flow, and Tessie telemetry, suppresses charging during
  boosted export, floors to the Tessie current step, and restores the protected
  direct baseline when spill disappears.
- Port the restart-safe latest-start pre-free EV backfill. It caps energy by the
  protected ZEROHERO export plan and vehicle room, schedules backwards from the
  configured free boundary, freezes the active start, recalculates live safe
  current directly, and cannot overlap an active export session.
- Require Local Modbus ownership for both outside-window stages, while retaining
  independent Tessie-only writes and the shared Safety Lock. Battery power,
  sign, SoC threshold, and telemetry age/skew are explicitly commissioned;
  phase count extends only the source power/current conversion.
- Persist pre-free phase and outside-policy cleanup ownership so Home Assistant
  restarts or vehicle reconnects cannot strand Tessie at a prior high current.
- Restore the pilot rule that the commissioned connector rating—not Tessie's
  transient writable maximum—is the planning ceiling. The live maximum bounds
  only an immediate service call and a later range refresh catches up directly.
- Expose solar-spill and pre-free decisions through the EV status sensor and
  first-class portable sensors, the example dashboard, and redacted diagnostics.
  The complete suite now includes reference single-phase, configurable
  three-phase, ownership, telemetry, restart, and runtime tests.
- Let a commissioned direct-EVSE path calculate read-only targets while Safety
  Lock is on. Rehearsal exposes ordered `would_*` actions but performs no retry
  transition and cannot pass the adapter's independent `ready` write guard.

- Characterize the Working Single Phase Pilot Site smart-socket command path:
  configured physical rating, pre-power current staging, service-valid
  feedback, configurable settling, post-settle rebounding, current-before-start
  ordering, and the outside-window zero-demand power policy. The outlet adapter
  and one-shot recovery remain deliberately disconnected.
- Rename all current public repository references to the source installation as
  “Working Single Phase Pilot Site”; learned driving targets are explicitly the
  last-priority compatibility stage pending a Tessie-native capability review.
- Add an explicit direct-EVSE/smart-socket supply selection, mapped outlet,
  configurable physical socket ceiling/settling/power policy, and adapter
  boundary. Existing entries remain direct EVSE; selected smart-socket runtime
  is deliberately non-writing until the full delayed sequence is connected.
- Characterize the restart-serializable, one-attempt `no_power` recovery state
  machine with coherent-evidence gates, confirmed current and outlet phases,
  configurable dwell/timeout durations, post-power rebounding, latched failure,
  and sustained-health/path-change rearm. It remains disconnected from runtime.

- Remove the rewritten automatic FoxESS free-charge/reconciliation controller
  and simplified Tessie current/session controller. Neither had demonstrated
  parity with the proven Working Single Phase Pilot Site behavior.
- Retain automatic ZEROHERO export as the only verified automatic write path;
  retain separately submitted, bounded FoxESS diagnostics.
- Remove obsolete sensors, configuration fields, dashboard claims, and tests
  that implied the removed controllers remained supported.
- Persist an in-progress house-demand learning cycle across ordinary Home
  Assistant restarts while continuing to reject cycles with excessive gaps.
- Require explicit EV home/cable mappings for protected export baseline
  calculations; missing evidence fails closed instead of being auto-discovered.
- Add a repository instruction hook, source-of-truth record, port-first guide,
  system requirements, and parity-based roadmap for future work.
- Add a pure, branch-for-branch Working Single Phase Pilot Site free-window EV current planner and
  separate Tessie anti-pause charge-limit target with golden tests.
- Add the higher-capacity-site allowance only as an outer, topology-aware
  ceiling: ordinary sessions that fit the configured whole-site kWh allowance
  retain the pilot-site target instead of being evenly spread across the window.
- Restore the independent, default-off Automatic EV Control intent switch.
  Until the Tessie adapter is completed it explicitly reports blocked and no
  EV service call can be made, even if the switch is turned on.
- Use configured service current, site voltage, phase count, and remaining
  window time to prove when the daily allowance is physically unreachable.
  Only higher-capacity sites continue to the projected-energy pacing check.
- Retain raw FoxESS SoC and subtract the configured minimum SoC once in the
  energy ledger; do not feed a human-relative display percentage back into
  control calculations.
- Add a fail-closed direct-EVSE command planner and Tessie service adapter.
  The plan preserves charge-limit/current/start ordering, treats the physical
  connector rating separately from Tessie's live transport maximum, requires
  writable metadata, and never invents a direct-path stop command.
- Add explicit EV commissioning mappings and configurable pilot-site policy
  inputs for location, priority, charge target, guaranteed current, settling,
  limit headroom, efficiencies, battery target, service headroom, and allowance
  margin. Legacy enabled state cannot bypass the separate commissioning flag.
- Add restart-serializable three-minute average-step buffers with explicit age
  coverage and latest-source validity for matched grid/EV feedback.
- Connect the direct-EVSE free-window runtime behind the independent default-off
  EV intent, explicit commissioning, complete mappings, and shared Safety Lock.
  The path writes Tessie only, so FoxCloud may continue to own the inverter.
- Require explicit most-loaded-phase signed current feedback for multiphase EV
  commissioning instead of assuming aggregate site power is balanced.
- Persist matched samples and direct-EVSE reconciliation state. Confirm current,
  charge limit, and switch feedback; bound one unchanged target to three writes
  at least 30 seconds apart, then latch a visible anti-flapping fault.
- Expose the EV decision phase, allowance phase, target current/limit, averages,
  retry state, last actions, and write count for dashboard and diagnostics use.

## 0.3.8 — Working Single Phase Pilot Site ZEROHERO selling automation

- Port the proven Working Single Phase Pilot Site surplus-energy ledger, calculated latest start,
  fixed-power session latch, deliberate 21:01 finish, and Self Use recovery.
- Require Local Modbus ownership, the FoxESS automatic gate, an independent
  automatic-export toggle, and an unlocked Safety Lock before any export write.
- Persist both boosted-window export energy and the active session latch across
  Home Assistant restarts and Modbus outages.
- Protect learned house demand plus only an explicitly configured mandatory
  connected-EV baseline; optional EV target energy does not suppress a sale.
- Bound start and restore retries, including a stable no-write state after
  exhaustion so a competing writer cannot cause indefinite mode flapping.
- Expose the plan, latest start, accumulated export, session phase, and
  allowance evidence as portable sensors and diagnostics.

## 0.3.7 — exclusive FoxESS control ownership

- Add an explicit FoxESS owner selector: Observer only, Local Modbus, or
  FoxCloud Mode Scheduler. Legacy entries safely default to Observer only.
- Permit automatic local FoxESS writes only when Local Modbus is the selected
  owner; selecting FoxCloud blocks reconciliation and Modbus diagnostics even
  outside the cloud charge period.
- Report configured ownership and effective Modbus authorization separately in
  status and diagnostics so an enabled-looking boolean cannot imply ownership.
- Record the verified scheduler boundary: FoxCloud's Remaining Time Work Mode
  controls uncovered periods, while remote-control evidence shows Modbus can
  cancel the remainder of an active scheduled period.
- Defer dynamic cloud export to a schedule-aware cloud adapter that preserves
  non-overlapping charge periods. HEO does not mix transports as a workaround.

## 0.3.6 — portable whole-site EV allowance control

- Port the Working Single Phase Pilot Site EV-priority current controller behind the independent
  Tessie gate and bound it with a whole-site free-window energy envelope.
- Derive an EV energy budget from remaining kWh after reserving the live
  FoxESS capacity gap and forecast house demand, then spread that budget over
  the remaining window. No site-specific battery-energy guess is required.
- Stop a controller-owned EV session at the configured cutoff, or hold it off
  when the residual is below the charger's minimum current. Never stop or
  alter a manually/cloud-started session.
- Treat the lower of the configured physical charger profile and Tessie's
  entity maximum as authoritative, and expose the allowance calculation in
  status attributes for commissioning evidence.
- Add single-phase 63 A and three-phase 80 A regression scenarios and record
  the reusable policy and H3 troubleshooting lessons in project documentation.

## 0.3.5 — independent EV control authorization

- Restore a separate, default-off automatic-control gate for mapped
  Tessie/Tessy writes. Enabling automatic FoxESS control no longer authorizes
  EV current or charge-switch services.
- Permit a commissioned EV policy to run while automatic FoxESS control is
  disabled, while retaining the shared Safety Lock as an absolute no-write
  interlock.
- Expose both authorization states independently in status attributes and
  redacted diagnostics.

## 0.3.4 — full-rate free-window target and cutoff stop

- Request the commissioned inverter charge limit while the configured
  free-window import cutoff remains; house load and AC-coupled PV are retained
  only for estimating the resulting grid import.
- Restore Self Use as soon as the cutoff is reached, regardless of battery SoC.
- Keep the full-battery-before-cutoff outcome as Back-up so the remaining
  allowance can serve the house.

## 0.3.3 — explicit Safety Lock switch

- Expose `switch.home_energy_safety_lock` with unambiguous semantics: ON means
  locked and no FoxESS/Tessie hardware writes are allowed.
- Persist lock changes without coupling them to the automatic-control switch.
- Add the safety control to the portable Diagnostics dashboard template.

## 0.3.2 — diagnostics naming and rate feedback

- Rename the remaining user-facing Test labels to Diagnostics.
- Add read-only current import/export rate sensors so both previews show the
  configured rate used for their estimate.
- Clarify the Rehearsal option as **Safety Lock (ON = no hardware writes)**;
  its default remains ON.

## 0.3.1 — diagnostics commissioning surface

- Rename the manual Test view to Diagnostics and make its purpose explicit:
  live telemetry, previews, and bounded FoxESS checks in one place.
- Derive the discharge preview from the configured standard or ZEROHERO-window
  export rate; the rate is no longer an editable test input.
- Extend the bounded diagnostic duration ceiling to 120 minutes.
- Keep the automatic scheduler disabled while allowing an explicitly
  confirmed diagnostic test once Rehearsal mode is disabled and all actuator
  mappings are complete.

## 0.3.0 — preview-first FoxESS commissioning tests

- Add editable charge/discharge power and duration inputs for a dedicated Test
  view, with pre-submit cost and export-earning estimates.
- Add explicit, timed FoxESS force-charge and force-discharge buttons plus a
  stop-and-restore-Self-Use button. Tests require automatic-control opt-in,
  Rehearsal mode disabled, complete FoxESS mappings, valid telemetry, and a
  30-minute maximum duration.
- Block force-charge tests outside the configured free window and pause the
  automatic FoxESS/EV loops while a manual test is active.
- Keep the stop path fail-safe when actuator feedback disappears by clearing
  both force-power targets before selecting Self Use.
- Add live test status, remaining time, power history, and regression tests.

## 0.2.34 — rounded currency state

- Round the currency-specific estimated daily cost state to two decimal places;
  Home Assistant cannot apply a display precision hint reliably without a
  native unit.

## 0.2.33 — concise numeric display

- Suggest a maximum of two decimal places for numeric energy, power, state of
  charge, and cost entities in Home Assistant.

## 0.2.32 — portable dashboard references

- Correct the starter dashboard entity references to the stable integration
  keys introduced in 0.2.31, removing the remaining `Entity not found` cards.

## 0.2.31 — stable portable entity IDs

- Use stable `sensor.home_energy_*` IDs for the dashboard regardless of the
  config-entry display name.
- Migrate an existing entity to its stable ID only when that ID is unused;
  otherwise preserve the existing entity and fail safely.

## 0.2.30 — portable two-column dashboard

- Add mapped battery SOC, solar, house-load, and EV SOC sensors so a dashboard
  can use stable integration entity IDs rather than site-specific source IDs.
- Replace the minimal starter view with generic Overview, EV, and
  Commissioning views using a two-column layout and no personal imagery.
- Keep the dashboard read-only and retain observer-by-default control gates.

## 0.2.29 — visible ZEROHERO hourly import evidence

- Expose a read-only **ZEROHERO Import This Window** sensor.
- Include each local hourly import bucket, accumulator date, last sample, and
  configured hourly threshold as sensor attributes for direct evening review.
- Add the sensor to the importable Lovelace starter and document where to find
  the evidence. No control boundary changes.

## 0.2.28 — guarded EV session commands and dashboard starter

- Start a mapped Tessie/Tessy charge session only when the vehicle is confirmed
  at home, connected, below its mapped charge-limit target, and the planner has
  an active free-window, solar-spill, or pre-window intent.
- Stop only sessions started by this controller when the mapped target is
  reached or the managed window ends; manually/cloud-started sessions are not
  stopped by the integration.
- Keep away, unknown, disconnected, and unavailable states fail-closed.
- Expand the importable Lovelace starter view with tariff, planning, and house-
  learning sensors. HACS still does not install dashboards automatically.
- Add mocked coverage for EV session start/stop and retain the full regression
  suite (135 public-package tests pass).

## 0.2.27 — Tessie solar spill, away bypass, and pre-window backfill

- Add an opt-in Tessie/Tessy current planner for three explicit behaviours:
  free-window allowance charging, post-window solar-spill charging after the
  battery is full, and a modest reserve-aware backfill before the free window.
- Confirm a Tessie/Tessy vehicle tracker is `home` before writing. An away,
  supercharging, unknown, disconnected, or ambiguous vehicle fails closed;
  away vehicles receive no current-limit write.
- Apply the configurable 20%/30% inverter-capacity ceilings only to slower
  load-following sessions. Free-window charging remains governed by the
  import allowance and commissioned electrical ceiling.
- Keep the active boundary narrow: only the explicitly mapped EV current
  number may be written. Tessie charge start/stop, SoC-limit, and FoxESS
  export writers remain outside this release.
- Add regression coverage for away bypass, solar-spill conversion, pre-window
  backfill, unknown presence, and free-window cap semantics (133 tests pass).

## 0.2.26 — gated Tessie current control

- Connect the tested EV current planner and service adapter to the active
  coordinator behind the existing automatic-control and Rehearsal gates.
- Adjust only the explicitly mapped Tessie/Tessy current setpoint during the
  configured free window when local cable and charger-current feedback exists.
- Do not start or stop charging or change the vehicle SoC limit in this
  milestone; unavailable or ambiguous feedback fails closed.

## 0.2.25 — conservative Tessie entity suggestions

- Suggest common Tessie/Tessy EV entities during setup when the installed
  entities produce one clear match (or an exact known ID).
- Leave ambiguous, unavailable, or non-Tessie entities blank so setup never
  silently controls the wrong vehicle.

## 0.2.24 — opt-in FoxESS free-window controller

- Add an explicit automatic-control opt-in and Rehearsal mode interlock to the
  config and reconfigure forms; defaults remain no-write.
- Wire the tested FoxESS free-window charge/restore planner into a 30-second
  coordinator loop only when all three FoxESS actuator mappings are present
  and the interlocks permit control.
- Keep the first active capability narrow: allowance-paced Force Charge and
  reviewed `Backup`/`Self Use` restoration. Tessie/EV and export writers are
  not enabled by this release.
- Expose control-gate state, last control reason/actions, and write count in
  the status sensor attributes for commissioning evidence.
- Add mocked Home Assistant tests covering disabled, rehearsal, and active
  FoxESS paths.

## 0.2.23 — explicit free-window completion modes

- Add a configurable full-battery import threshold (49 kWh by default) to the
  setup and reconfigure forms.
- Add a pure completion policy for the three reviewed outcomes: continue while
  below full, restore `Backup` when full before the threshold, and restore
  `Self Use` at the threshold or once the 50 kWh allowance is exhausted.
- Extend the adapter-neutral FoxESS planner and runtime composition to support
  `Backup` restoration, while retaining the no-write observer boundary.
- Expose the completion recommendation as a read-only sensor and test the
  exact-threshold boundary explicitly.
- Document the evidence and commissioning rule for FoxCloud schedule versus
  local Modbus ownership; no mixed-control behaviour is assumed.

## 0.2.22 — read-only free-window charge target

- Add an optional AC-coupled solar-power mapping to the setup and reconfigure
  forms.
- Expose a read-only **Free-Window Charge Power Target** sensor that combines
  the persisted free-window import allowance, remaining local window time,
  measured house load, measured AC-coupled PV, and the commissioned inverter
  charge limit.
- Keep the target fail-closed: it is unavailable unless the required evidence
  is mapped and valid, and this release still performs no service calls.

## 0.2.21 — normal-mode restoration at zero charge

- Add a pure FoxESS response-reconciliation policy with a retry interval and
  finite attempt limit. It never calls Home Assistant services; active
  coordinator wiring remains gated behind commissioning.
- Reject partial FoxESS or EV actuator mappings at setup time so an active
  coordinator can never receive an incomplete control surface.
- Add a pure export-session state machine covering bounded start retries,
  feedback acceptance, latching, finish restoration, and source-loss recovery.
- Add an allowance-paced battery-charge planner that converts remaining kWh and
  remaining window time into a grid-import target, then accounts for measured
  house load and AC-coupled PV before applying the inverter limit.
- Feed the optional charge plan through the pure runtime composition boundary,
  so the eventual coordinator and reconciliation layer share one bounded
  target calculation.
- Treat an exhausted allowance, finished window, or zero charge target as a
  request to restore normal inverter mode, rather than issuing Force Charge at
  0 kW; Self Use then remains available to soak up solar.

## 0.2.15 — Dashboard entity-ID correction

- Correct the shipped observer dashboard to use the entity IDs generated by
  the integration (`sensor.home_energy_*`).
- Add a regression check so the example cannot silently ship invalid entity
  references.

## 0.2.14 — Explicit actuator mapping groundwork

- Add optional, domain-constrained FoxESS and Tessie actuator mappings to the
  setup and reconfigure flows for future commissioning.
- Validate and redact mapping presence in diagnostics without enabling writes.

## 0.2.13 — Hassfest translation fix

- Place selector option translations at the Home Assistant-supported
  top-level location so Hassfest validates the integration metadata.

## 0.2.12 — Hourly ZEROHERO guard correction

- Evaluate the GloBird ZEROHERO threshold independently for each hourly bucket
  in the 18:00–21:00 window. A single bucket above 0.03 kWh/hour fails the
  guard even when the three-hour sum is below 0.09 kWh.
- Clarify the setup label and tariff-meter documentation to distinguish the
  retailer's hourly condition from the local telemetry debounce.
- Keep the HACS integration observer-only; no hardware-control service calls
  are enabled.

## Unreleased — GloBird FoxESS automation pilot

- Added opt-in, fail-closed FoxESS Modbus free-window charging automation.
- Added opt-in export automation with protected-energy and sustained-import
  guards.
- Added configurable windows, SOC target and command-power limits.
- Kept Tesla vehicle control disabled until a vehicle-current actuator is
  explicitly installed and mapped.
- Recorded the remote H3 commissioning boundary and rollback procedure.
- Added persistent non-free-window house-demand sampling and read-only learning
  sensors to the HACS core.
- Added an automatic EV policy to the YAML pilot: once armed after
  commissioning, a connected vehicle starts in the battery-funded backfill
  window, hands over to free charging, and stops at its target, disconnect, or
  user-configured ready-by time (06:00 default).
- Added explicit FoxESS profile validation plus adapter-neutral, fail-closed
  command planning and mocked service-layer tests; no live HACS writes are
  enabled.
- Added an explicit EV physical phase-count setting (single- or three-phase)
  and phase-aware configured charging-power calculation. Existing entries remain
  single-phase by default until the site is deliberately configured otherwise.
- Added setup choices for the supported EV profiles (single-phase 10/15/32 A or
  three-phase 16 A), plus configurable 6–9 pm and other-paid-period
  load-following ceilings (20% and 30% defaults) and a load-following-preserving
  override. These are policy inputs only until the HACS actuator adapter is
  commissioned.
- Added explicit, configurable bonus-window boundaries (18:00–21:00 defaults)
  so the zero-import policy is a reviewed site setting rather than a hidden
  clock assumption.
- Added explicit site topology plus commissioned service-import, export, and
  inverter charge/discharge limits. Zero means not commissioned and therefore
  cannot silently become an assumed electrical rating.
- Added a pure tariff guard and read-only allowance sensors. A mapped
  cumulative import meter now caps the remaining daily free-energy budget, and
  the bonus guard requires qualified, sustained zero import before it can be
  considered eligible.
- Added a fail-closed EV service adapter and pure runtime safety-state
  evaluator. They are deliberately not connected to the observer entry yet;
  no EV or inverter write is enabled by this release.
- Added a pure runtime composition seam that evaluates tariff, EV and FoxESS
  decisions together before any adapter can be granted write permission.
- Connected the learned protected-house budget to the runtime export plan, so
  learned demand is subtracted before any sellable-energy calculation.

## 0.2.1 — Learning timezone correction

- Use Home Assistant local time when sampling configured site learning windows,
  so Australian 12:01–14:59 windows are not interpreted as UTC.

## 0.2.2 — Remaining learning budget

- Expose the full-cycle house-learning budget scaled to the time remaining
  before the next configured free-power window, with read-only tests.

## 0.2.0 — Observer parity update

- Synced the HACS release tree with measured battery-potential capacity and
  persistent rolling house-demand learning.
- Included tested, adapter-neutral FoxESS planning and response-verification
  primitives while keeping the HACS integration observer-only.

## 0.1.0 — Observer release

- Initial HACS custom-integration package.
- Guided entity mapping with no YAML edits required.
- Normalised, observer-only energy ledger and diagnostics.
- No actuator services are called by this release.
- Added setup, reconfiguration, live-update, unload, and no-service-call tests
  using the Home Assistant test harness.
