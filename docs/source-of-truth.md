# Project source of truth

The public product name is **FoxESS GloBird Tesla Energy Orchestrator**. The
existing `home_energy_orchestrator` integration domain, entity IDs, and `HEO`
short form remain stable for upgrade compatibility.

Registered entity IDs become user-owned after first creation. Setup and reload
must preserve a user's entity ID, custom name, area, labels, visibility and
enabled state. HEO may improve default display translations, but must not
silently reclaim a registered object ID or treat presentation changes as
permission to change unique IDs, machine states or public attributes.

This is the public, durable design record for the project. Git records what
changed; this file records the authority order, supported behavior, and rules
future work must preserve. Site addresses, credentials, incident chronology,
and private operational evidence belong only in the local private record.

## Authority order

1. Direct inverter registers and measured electrical behavior.
2. The proven Working Single Phase Pilot Site v1.4.24 implementation and observed behavior.
3. Home Assistant recorder and service-call evidence.
4. HEO characterization tests and implementation.
5. UI labels and cloud-app displays, which may be stale.

The reference implementation is Working Single Phase Pilot Site v1.4.24 at source commit
`5806b4a5313331fbc421108e9e0c98e661ca20fe`. Public contributors may not have
that private source snapshot, so every port must capture its behavior in a
provenance table and golden characterization tests before implementation.

Different service ratings, phase counts, inverter sizes, solar arrays, and EV
charging capacities are configuration differences. They justify extension
layers around the proven algorithm, not replacement algorithms.

## Current software truth

- Persisted energy meters immediately checkpoint a positive-flow-to-zero
  transition. Energy-delta write thresholds may reduce routine storage writes,
  but must never leave a positive import/export anchor behind after the
  canonical flow has stopped; otherwise a reload can manufacture energy from
  the bounded gap integration interval. When a native cumulative daily-import
  sensor is commissioned, both the exposed ledger total and cost estimate use
  it; the local accumulator is only the fallback daily total.
- Daily financial reporting keeps import charges, the supply charge, and export
  earnings separate. Export inside the configured Peak Solar/GenerationFeedin
  window receives its base rate and all remaining export receives the configured
  Off-peak base rate; boosted-window export independently
  receives the configured additional ZEROHERO boost up to the lesser of
  measured window export, measured daily export, and the boosted daily
  allowance. The independently configured automatic-export cap
  limits controller energy without changing tariff eligibility. Existing
  entries migrate the old shared allowance into that cap to preserve behavior.
  Measured net cost is gross cost minus measured export revenue and any credit
  already qualified by HEO. The separate daily forecast is deliberately
  optimistic: it assumes the configured ZEROHERO credit and initially assumes
  75% of the remaining planned export will be realised. Neither value is the
  retailer's final bill.
- Forecast calibration is read-only and has no control authority. HEO freezes
  one daily forecast, matches it only to complete same-date GloBird results,
  and exposes forecast, actual, error, and ZEROHERO outcome as a scorecard. It
  slowly calibrates forecast export realisation and a bounded cost residual;
  it never changes export, charge, EV, inverter, or Safety Lock decisions.
  Days on which ZEROHERO was not achieved remain visible but do not train the
  residual because they violate the forecast's explicit optimistic assumption.
  Existing entries migrate a complete, unambiguous pair of GloBird scorecard
  entities from one GloBird config entry; explicit or partial mappings remain
  untouched for manual review. The GloBird `missed` result is normalized to
  HEO's retained `not_achieved` value. Incomplete, pending, unknown, and
  mismatched-date results never enter the scorecard.
- ZEROHERO automatic export requests the configured inverter discharge maximum,
  capped only by the mapped actuator maximum. The inverter enforces its own grid
  export limit. A lower legacy user-entered discharge preference is ignored so
  ordinary house load cannot consume artificially withheld discharge headroom.
- The configurable ZEROHERO daily credit defaults to $1.00 and is deducted once
  from estimated net cost only after the full configured window is complete,
  all expected clock-hour buckets were observed, and no bucket exceeds the
  configured per-hour import threshold. It is never multiplied by the number
  of qualifying hours and is not awarded early from the live debounce guard.

- HEO is observer-by-default.
- The verified Working Single Phase Pilot Site ZEROHERO export port is behind Local Modbus ownership,
  the FoxESS automatic gate, the independent export toggle, and the Safety
  Lock.
- A faithful direct-EVSE free-window Tessie path is present behind its own
  default-off intent, explicit commissioning flag, complete mappings, and the
  shared Safety Lock. It has not been enabled on a live site.
- The daily EV ready-by allocation is a separately identified configurable
  extension around the retained latest-start arithmetic. Its Tessie-only path
  may run with FoxCloud ownership from live post-midnight energy, but only
  Local Modbus ownership allows HEO to protect the following ready cycle from
  its own ZEROHERO export. That protection is not independent permission to
  charge: the ready-by path is capped by the live ZEROHERO export plan and
  stops when genuinely sellable energy disappears. The ready-to-ready ledger,
  confirmed wall-energy accumulator, shrinking active-session target and start
  latch survive restart.
- Bounded, explicitly submitted FoxESS diagnostics remain available behind
  their guards. They are not schedules. Test ownership, timing and restoration
  attempts persist across reload/restart. An interrupted test immediately
  enters bounded Self Use restoration on setup and remains visibly active until
  mapped mode plus both force targets confirm completion; an unconfirmed
  restoration cannot silently release automatic inverter control. Safety Lock,
  non-Local-Modbus ownership, or incomplete actuator mappings block restoration
  service calls without consuming the bounded attempt allowance; the persisted
  obligation remains visible and retryable.
- A separately gated, default-off Local Modbus free-window Force Charge
  extension is implemented. It uses the configured 24-hour window, requires
  fresh SoC below target and remaining daily free-import allowance to start,
  freezes bounded power for the session, persists its latch/retry state, and
  deliberately restores Self Use at the end or when the allowance is exhausted.
  After restart, current window, SoC, allowance, and control gates are
  authoritative: transient Self Use or Back-up feedback with an unfinished
  HEO-owned session, and an older persisted completed phase, cannot suppress
  an otherwise eligible current-window charge. A clean Back-up mode with no
  unfinished HEO session remains external and is never adopted. Turning off
  the independent charge request or enabling Safety Lock is the deliberate
  operator override. It does not program native schedule registers.
- Automatic Force Charge additionally requires an explicitly confirmed
  schedule. Setup presents exact 24-hour times, duration, and a visual timeline;
  a crossing-midnight window needs a second acknowledgement. v0.12 entries are
  migrated with charging disabled until this review is completed.
- The canonical pilot source contains no local automatic `Force Charge` writer;
  its EV controller assumes battery charging is externally established. The
  local battery controller is therefore explicitly an extension, not missing
  port code or claimed parity.
- Direct-EVSE free-window Tessie current, charge-limit, and charge-start control
  is implemented. Default-off solar-spill and latest-start pre-free stages are
  also implemented for Local Modbus ownership. All three use the same bounded
  feedback reconciliation; no direct path issues a stop or pause command. If
  outside-window charging reaches its battery reserve, HEO ends the paid
  session but retains a non-zero configured protected baseline through that
  same reconciliation path; only a configured 0 A baseline may stop the
  charge switch. Entry to the configured free-power window is a separate
  reconciliation epoch, so it cannot inherit a failed pre-free/baseline retry
  episode even when both stages select the same current. A valid direct-EVSE
  target has no terminal attempt-count latch: retry intervals progress from
  30 seconds through 1, 2, 4, 8 and 16 minutes, then remain capped at 30
  minutes; the episode and its timing survive restart.
- Charge-to-full operator intent is an integration-owned, persistent switch;
  it is not a site entity mapping. Existing installations retain the effective
  state of the pilot-style external helper until the HEO switch is first used.
  The switch then becomes the sole persistent owner. It preserves the
  source policy ordering and cannot bypass commissioning, ownership, telemetry,
  service-current, allowance, or Safety Lock gates.
- Solar spill reconstructs only measured surplus from EV power, grid export,
  and signed battery flow. Pre-free backfill consumes no more than the local
  protected export plan and the vehicle's wall-energy room, starts as late as
  possible, and persists only its active phase and frozen start.
- Morning measured-solar EV capture is a separate default-off policy before
  the free-power window. It uses the same coherent measured-surplus equation
  but an independently configured house-battery reserve, rather than the
  post-free solar-spill full-battery threshold. The dashboard exposes its
  switch and reserve number. Existing entries keep the policy off and use their
  commissioned outside-window reserve until the new number is explicitly
  saved. An active scheduled pre-free session has exclusive fixed-current
  ownership and completely replaces variable morning solar capture.
- Normal measured-solar EV-current changes are restart-safe and require a
  stable 15-minute target before Tessie is asked to change. Verified grid
  import may curtail immediately. Any failed solar eligibility condition,
  including stale telemetry, reserve loss, disconnection, EV limit or Safety
  Lock, discards the hold and returns to the protected baseline. Pre-free,
  free-window, daily-backfill and charge-to-full stages also discard it.
- Solar-spill coherence applies to the fast electrical grid and effective
  battery sources. Rejected inactive-magnitude provenance cannot invalidate a
  fresh signed-battery fallback. Stable battery SoC and state-qualified Tessie
  current keep the pilot implementation's value semantics rather than being
  treated as fast polling clocks.
- The smart-socket command policy is connected to the independently gated EV
  runtime. It preserves the source ordering: bound/stage current before
  power, accept service-valid staged feedback, settle the configured interval,
  then bound current again and start charging. It cannot write an outlet yet.
- Smart-socket configuration and adapter commands require an explicitly mapped
  outlet and configured physical ceiling. Recovery is a restart-serializable
  state machine with a pre-action latch, current and outlet confirmation,
  configurable dwell/timeout periods, delayed permission rechecks, one physical
  cycle per fault episode, visible status, and sustained-health/path rearming.
- Protected-house demand learning integrates the explicitly mapped base or
  whole-house source outside the free window. When a separate heater-power
  source is mapped, it records an independent daily stream and requires seven
  valid samples in both streams before their P80 values replace the occupied
  fallback. Auto occupancy assumes Home unless every Home Assistant person is
  validly away for the configured confirmation period; persistent Home and
  Away overrides reproduce the source controls. Away always selects its own
  fallback. Exactly one resulting budget enters the ledger, and weather
  forecasts remain diagnostic rather than an additive control term. Histories
  and in-progress samples survive ordinary restarts and reject over-gap cycles.
  Source composition retains the pilot order: state-qualify Tessie current,
  remove EV power exactly once only for a commissioned whole-house topology,
  remove an optional separately metered heater exactly once, clamp base demand
  at zero, and accumulate it with the pilot's left integration method. Invalid
  required subtraction telemetry withholds sampling rather than learning a
  knowingly incorrect load.
- FoxCloud ownership blocks all HEO Modbus writes for the entire day. HEO does
  not mix cloud scheduling and local Modbus automation.
- FoxCloud inverter ownership does not block free-window Tessie control,
  because that path does not write FoxESS. It does block solar-spill and
  pre-free stages: both are explicitly Local-Modbus-only policies. The shared
  Safety Lock blocks every write path.
- Entity roles and physical topology are explicitly configured. HEO does not
  guess actuator mappings or infer electrical limits from transient readings.
- All runtime consumers use one timestamp-aware canonical telemetry boundary:
  grid and service current are import-positive, battery power is charge-positive,
  and solar is generation-positive. Signed battery input or the pilot's paired
  charge-minus-discharge magnitudes are supported. Source/direction changes and
  v1 migration clear an independent sign-verification gate, closing automatic
  FoxESS and EV writes until locally recommissioned.
- Setup is a conditional multi-page commissioning workflow; reconfigure uses
  the same page schemas through a section menu. Values remain in an in-memory
  draft and cannot alter the live entry before explicit Review and Apply.
  Electrical-direction verification is part of the final Review and Apply
  boundary, not a standalone reconfiguration section. Changing an electrical
  source or direction clears the displayed confirmation there, so the operator
  can re-verify it before applying rather than unknowingly saving an observer-only
  configuration. Automatic sign calibration must use
  coherent physical evidence and the persisted diagnostic restoration path;
  it must not infer from entity names or enable an automatic-control request.
- Paired battery charge/discharge magnitudes remain the canonical pilot source.
  When a steady inactive zero alone becomes stale, a separately mapped fresh
  signed battery-power sensor may recover the canonical value with explicit
  fallback provenance. Invalid magnitudes, disconnected sources and genuine
  telemetry outages remain unavailable.
- An installation with EV control explicitly uncommissioned has no EV energy
  reservation. Retained EV defaults or stale mappings cannot withhold its
  otherwise valid battery export plan.
- A multiphase EV controller must receive explicit signed current for the
  most-loaded service phase. Aggregate power is not treated as proof that phase
  loading is balanced.
- House-load topology is explicit. The retained pilot mapping already excludes
  EV power and remains the default. A whole-house mapping may opt into removing
  measured EV current converted with the commissioned voltage and EV phase
  count exactly once for the free-window allowance projection. HEO never
  infers this choice from entity names, site phase count, or inverter model;
  invalid actual-current evidence makes the projection unavailable.
- In that whole-house topology, a vehicle-SoC update alone must not recalculate
  the allowance while requested and actual EV current are still converging.
  Hold the existing target only until feedback agrees or the normal
  three-minute decision boundary. A measured service-limit overrun always
  bypasses this transition hold. The hold exists only while allowance
  protection is enabled and both the prior and current EV SoC remain below the
  configured target; reaching the target is evaluated immediately.
- A mapped live FoxESS battery-capacity entity is authoritative over the
  configured numeric fallback. Setup may prefill that fallback from an
  unambiguous live FoxESS Modbus capacity value, but must not manufacture a
  capacity from inverter rating or site identity. When no valid live capacity
  exists, setup requires an explicit commissioned fallback and presents no
  default value.
- The portable dashboard preserves the proven operational view structure:
  Overview, Tesla, House, Solar & Weather, Configuration, Advanced, and Manual.
  Shared views use only HEO-owned entity IDs; vehicle-native, weather, room, and
  other site-specific cards are local overlays rather than shared assumptions.
- Dashboard design is informed by the Working Single Phase Pilot Site, but the
  clean disposable test installation is the staging and acceptance template for
  the distributed dashboard. Only dashboard changes reviewed there and accepted
  by the project owner are promoted into `examples/dashboard.yaml`.
- The dashboard must not expose Home Assistant's entities-card aggregate toggle
  as though it were an HEO master switch. Safety Lock is the global no-write
  interlock (ON means no HEO hardware commands); export and EV switches are
  independent behavior requests whose gates remain separately visible.
- Dashboard delivery remains manual in the current release. A future generated
  dashboard or Lovelace strategy/card layer must be upgrade-safe, versioned, and
  preserve local overlays rather than overwriting user customisation.
- Future manual inverter recovery is a distinct operator-control handoff, not a
  second inverter implementation. HEO will use the mapped FoxESS Modbus work-
  mode select and native force-power entities, mirror only their advertised
  options and bounds, and leave register, profile and remote-watchdog behavior
  to that integration. HEO must first persist a visible manual hold and cancel
  its own export/diagnostic latches without issuing a restoration command that
  overwrites the operator's selection. The hold survives restart and suppresses
  all HEO inverter reconciliation until an explicit resume action. Safety Lock
  and exclusive Local Modbus ownership remain mandatory. The hold cannot stop
  or prove the absence of FoxCloud or unrelated Home Assistant writers.
- Treat an EW11 Modbus TCP bridge as single-client unless its exact hardware and
  firmware are independently proven otherwise. Concurrent polling alone can
  make the observed bridge unresponsive, regardless of which client owns write
  control.

## Working Single Phase Pilot Site behaviors that remain the port target

The reference EV policy includes explicit occupancy/location overrides, cable
and charge-state evidence, two charging supplies, configurable current ceilings,
priority, guaranteed free-window current, a free-window SoC target, matched
three-minute grid/current feedback, a settling phase, restart-safe latches,
solar-spill charging, latest-start pre-free backfill, learned driving demand and
charge targets, and smart-socket recovery. These behaviors are now retained
ports, with the learned policy's detailed mapping in
`docs/ev-driving-learning-port.md`.

The house-demand policy and its source mapping are retained in
`docs/house-learning-port.md`.

The pilot's original free-window **House battery** branch used only signed
grid-current headroom. That is not the distributed product policy: a FoxESS
inverter can keep grid current below the same limit by reducing its own battery
charge first, leaving the EV untouched and reversing the selected priority.
HEO therefore treats this as a characterized correction. Below the configured
**House battery SoC for EV taper handoff**, the EV target accounts
for the difference between commissioned inverter charge power and fresh
canonical battery charge power. The conversion uses configured voltage and
site phase count and remains bounded by the connector minimum/maximum and the
physical service-limit correction. At or above that SoC, HEO releases the
battery-power claim and lets the EV absorb capacity exposed by normal BMS
taper. Missing battery SoC or battery-power evidence fails to the configured
free-window minimum. FoxESS remains authoritative for its hardware import
limit; HEO does not write that limit.

The P85 daily-driving model contributes to the general charge limit outside the
free window; it is not part of active free-window current calculation. HEO
collects the same consecutive-day cumulative-meter deltas, persists the same
28-sample/35-day evidence window, and preserves the source fallback and
actuator-step rounding. Configured phase count extends only the electrical
energy conversion.

Its export policy protects learned house demand and mandatory connected-EV
energy, computes sellable energy and latest start, latches a fixed-power
session, observes the independent automatic-export cap, and deliberately
restores Self Use at the configured finish. The retained HEO ZEROHERO path
represents this policy; its detailed mapping is in
`docs/zerohero-export-policy.md`.

The default-off EV-before-export threshold is a separately identified
extension, not pilot parity. Its first stage changes only effective export
permission: EV SoC below the adjustable target prevents or ends HEO automatic
export while preserving the user's saved export request. It neither starts EV
charging nor selects an energy source. Invalid or unavailable EV SoC withholds
export only while the opt-in is enabled.

Direct Tessie control also treats the configured connected-EV baseline
as site policy: an otherwise unauthorised plug-in auto-start cannot retain a
vehicle's previous charging current. A zero baseline creates a bounded stop
obligation, while free-window, solar, backfill and explicit Charge to Full
authority remain unchanged.

Crossing into ZEROCHARGE while pre-free charging is active forces an immediate
EV decision. HEO clears outside ownership and applies the configured free-window
settlement policy at that boundary; the previous battery-backed current target
must not persist until the ordinary decision interval.

The configured outside-window inverter percentage limits both daily backfill
and pre-free battery-backed EV charging. It is a percentage of commissioned
inverter output, not a percentage of the EVSE current setting. Conversion uses
configured EV voltage and phase count and rounds down to a supported step.

Dashboard plan entities describe actions HEO is currently permitted to take,
not merely an internal economic candidate. When EV-before-export or another
effective gate withholds export, planned start, energy and duration are absent
and the export status names the hold. The internal candidate remains available
to the controller for immediate recalculation when the hold clears.

## Delayed control-conformance supervision

The active controllers remain the only normal policy writers and continue to
reconcile every 30 seconds. A separate supervisor observes their declared
targets and actuator feedback. It requires the same mismatch continuously for
five minutes before opening one fresh, bounded reconciliation epoch. It does
not write every cycle, does not bypass Safety Lock or commissioning gates, and
does not replace the underlying controller state machines.

The supervisor covers failures that are unambiguous from commissioned local
evidence: a battery charge or export session not holding its HEO-owned mode, an
unexpected Force Charge or non-forced mode outside an HEO session, and an EV
requested current or charge switch that does not match HEO's current target.
It emits `home_energy_orchestrator_control_issue` when a sustained issue opens
and when it recovers, and mirrors the issue in the Orchestrator Status entity
attributes and a local persistent notification. Notification delivery is a
Home Assistant automation concern, so Telegram, ntfy, mobile-app and other
channels do not become integration dependencies.

An unexpected Force Discharge is not inferred to be a VPP event. FoxESS Modbus
does not provide FoxESS Cloud/VPP event provenance, so HEO reports it as an
unattributed external forced discharge with cloud verification unavailable.
It alerts but does not automatically cancel that mode, because doing so could
fight a legitimate VPP instruction. A future exemption may be labelled
verified VPP only when an explicit cloud event source supplies affirmative,
fresh evidence; timing correlation, absence of an HEO command, or the mode
itself is insufficient.

During Home Assistant startup inside ZEROCHARGE, Tessie feedback may recover
before the signed grid-current average. HEO preserves an already-running EV
request for at most five minutes while the normal average gains coverage. A
measured service-limit overrun still curtails immediately. This prevents a
healthy free-window request being actively reduced to the fallback current
solely because integrations restored in a different order.

## Inverter evidence rules

For supported H3 remote control, work mode register `49203` uses `1` Self Use,
`2` Feed-in First, and `3` Backup. Remote control uses registers `46001` enable,
`46002` timeout, and `46003–46004` active power. Treat direct register state as
authoritative when Home Assistant or a cloud UI is stale.

Timing correlation, a disabled-looking boolean, or the absence of a visible
cloud schedule does not identify a writer. Preserve service-call and register-
transition evidence, distinguish manual intervention, and label hypotheses as
hypotheses. Never change a Home Assistant clock to test a time boundary.

## Decision log protocol

For every future control change, record in this file or a linked policy:

- evidence and its source;
- Working Single Phase Pilot Site source sections and preserved decisions;
- configurable site extensions, separately identified;
- rejected alternatives and why;
- tests proving parity, restart behavior, stale-data handling, and ownership;
- deployment state and rollback condition.

Update the private local operational record separately when site-specific
evidence changes. Confirmed facts and hypotheses must remain visibly separate.

The free-window ownership evidence and extension boundary are recorded in
[`free-window-battery-ownership.md`](free-window-battery-ownership.md).
