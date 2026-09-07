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
- Direct-EVSE free-window Tessie current, charge-limit, and charge-start control
  is implemented. It never stops or pauses direct charging outside the window,
  and one unchanged target is bounded to three feedback-confirmed attempts.
- The smart-socket command policy is characterized but not connected to an
  outlet adapter. It preserves the source ordering: bound/stage current before
  power, accept service-valid staged feedback, settle the configured interval,
  then bound current again and start charging. It cannot write an outlet yet.
- Protected-house demand learning integrates the explicitly mapped source
  outside the free window, persists an in-progress cycle across ordinary
  restarts, rejects an over-gap cycle, and derives a conservative P80 model
  from up to 28 valid samples over 35 days.
- FoxCloud ownership blocks all HEO Modbus writes for the entire day. HEO does
  not mix cloud scheduling and local Modbus automation.
- FoxCloud inverter ownership does not block the independent Tessie path,
  because it does not write FoxESS. The shared Safety Lock blocks both paths.
- Entity roles and physical topology are explicitly configured. HEO does not
  guess actuator mappings or infer electrical limits from transient readings.
- A multiphase EV controller must receive explicit signed current for the
  most-loaded service phase. Aggregate power is not treated as proof that phase
  loading is balanced.

## Working Single Phase Pilot Site behaviors that remain the port target

The reference EV policy includes explicit occupancy/location overrides, cable
and charge-state evidence, two charging supplies, configurable current ceilings,
priority, guaranteed free-window current, a free-window SoC target, matched
three-minute grid/current feedback, a settling phase, restart-safe latches,
solar-spill charging, latest-start pre-free backfill, learned driving demand and
charge targets, and smart-socket recovery.

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
