# Changelog

## Unreleased

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

## 0.4.0 — port-first reset and durable project truth

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
