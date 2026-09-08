# Project source of truth

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

- HEO is observer-by-default.
- The verified Working Single Phase Pilot Site ZEROHERO export port is behind Local Modbus ownership,
  the FoxESS automatic gate, the independent export toggle, and the Safety
  Lock.
- A faithful direct-EVSE free-window Tessie path is present behind its own
  default-off intent, explicit commissioning flag, complete mappings, and the
  shared Safety Lock. It has not been enabled on a live site.
- Bounded, explicitly submitted FoxESS diagnostics remain available behind
  their guards. They are not schedules.
- Automatic FoxESS free-window charging is not implemented.
- The canonical pilot source contains no local automatic `Force Charge` writer;
  its EV controller assumes battery charging is externally established. A new
  local battery controller is therefore an extension, not missing port code.
- Direct-EVSE free-window Tessie current, charge-limit, and charge-start control
  is implemented. Default-off solar-spill and latest-start pre-free stages are
  also implemented for Local Modbus ownership. All three use the same bounded
  feedback reconciliation; no direct path issues a stop or pause command.
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
- FoxCloud ownership blocks all HEO Modbus writes for the entire day. HEO does
  not mix cloud scheduling and local Modbus automation.
- FoxCloud inverter ownership does not block free-window Tessie control,
  because that path does not write FoxESS. It does block solar-spill and
  pre-free stages: both are explicitly Local-Modbus-only policies. The shared
  Safety Lock blocks every write path.
- Entity roles and physical topology are explicitly configured. HEO does not
  guess actuator mappings or infer electrical limits from transient readings.
- A multiphase EV controller must receive explicit signed current for the
  most-loaded service phase. Aggregate power is not treated as proof that phase
  loading is balanced.
- The portable dashboard preserves the proven operational view structure:
  Overview, Tesla, House, Solar & Weather, Configuration, Advanced, and Manual.
  Shared views use only HEO-owned entity IDs; vehicle-native, weather, room, and
  other site-specific cards are local overlays rather than shared assumptions.
- The dashboard must not expose Home Assistant's entities-card aggregate toggle
  as though it were an HEO master switch. Safety Lock is the global no-write
  interlock (ON means no HEO hardware commands); export and EV switches are
  independent behavior requests whose gates remain separately visible.
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

The P85 daily-driving model contributes to the general charge limit outside the
free window; it is not part of active free-window current calculation. HEO
collects the same consecutive-day cumulative-meter deltas, persists the same
28-sample/35-day evidence window, and preserves the source fallback and
actuator-step rounding. Configured phase count extends only the electrical
energy conversion.

Its export policy protects learned house demand and mandatory connected-EV
energy, computes sellable energy and latest start, latches a fixed-power
session, observes the export allowance, and deliberately restores Self Use at
the configured finish. The retained HEO ZEROHERO path represents this policy;
its detailed mapping is in `docs/zerohero-export-policy.md`.

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
