# Phase 8 — serialized reconciliation and operational rollout

## Status and entry gate

**Design only. Implementation is prohibited until Phase 7 Gates 2 and 3 pass
and the project owner explicitly accepts Phase 8.** The current controllers
retain independent schedules deliberately; this document does not authorize a
lock, timer, task, configuration change, persistence change or release.

The required entry evidence is:

1. the clean-staging Gate 1 record remains compatible with the chosen release
   candidate;
2. a pilot observes an applicable complete ZEROCHARGE, ZEROHERO, export and EV
   cycle, including idle reload/restart evidence; and
3. one remote topology repeats its applicable cycle with no site-specific code
   or manual storage intervention.

## Current contract to preserve

There are three independent sources of reconciliation today:

- `EnergyCoordinator`: a 30-second coordinator interval and mapped source
  state changes;
- `ActiveFoxessController`: its own 30-second interval; and
- `ActiveEvController`: a 30-second interval plus specific time callbacks.

The existing Phase 0/7 fixtures freeze public state, reason, persistence,
command order, retry cadence, timer boundaries and restoration obligations.
Those contracts take priority over a smaller call count or a different internal
shape. The two existing controllers must continue to own distinct charge,
export, manual-diagnostic and EV session state machines.

## Target boundary

Introduce one entry-scoped, ephemeral cycle-request coordinator. It is not a
new policy engine and it owns no persisted session state.

```text
source/timer/operator trigger
          │
          ▼
request(reason, urgency)
          │     (merge duplicate requests; retain strongest urgency)
          ▼
single running cycle ──► acquire immutable observation
                         ► account and learn
                         ► evaluate inverter
                         ► evaluate EV
                         ► execute already-authorized plans in retained order
                         ► persist retained obligations
                         ► publish one coherent read model
```

An `asyncio.Lock` alone is insufficient: it serializes calls but retains a
backlog of redundant work. The request coordinator must instead record pending
reasons while a cycle runs, coalesce ordinary requests, and run at most one
additional pass from the newest available evidence. Urgent safety transitions
may bypass a normal cadence wait, but never the single active command sequence.

## Required implementation order

1. **Characterize triggers.** Mechanically inventory every interval, time
   callback, source listener, config reload and operator action. Record its
   current owner, urgency, expected public reason, commands and persistence
   effect in a test table.
2. **Shadow request collector.** Add a side-effect-free collector that records
   proposed coalescing decisions while the three existing schedules remain
   authoritative. Its trace must match the frozen lifecycle fixtures.
3. **One source at a time.** Route coordinator-originated ordinary requests
   through the collector first. Do not move inverter and EV timers together.
   After exact trace parity, route one controller seam in a separate release.
4. **Retire only proven duplicates.** Remove an old interval/listener only
   after its replacement has equivalent command, persistence, reason and
   reload/restart traces. Preserve urgent operator action semantics explicitly.
5. **Operational rollout.** Repeat clean staging, pilot, remote topology and
   remaining-site gates for each active routing seam. A failure reverts that
   seam only, retaining existing Store payloads.

## Invariants and non-goals

- At most one HEO command sequence may execute per config entry.
- No trigger, timer, retry, published reason, command order, service payload,
  Store key/version/payload, entity, configuration field or actuator authority
  may change without a separately approved compatibility decision.
- Safety Lock, ownership, sign verification, mapping completeness and stale
  telemetry remain no-write gates before and after coalescing.
- Reload/unload cancels only ephemeral queued work; persisted charge, export,
  EV and manual restoration obligations remain authoritative and are restored
  by their existing repositories.
- This phase does not merge the inverter and EV state machines, create a
  physics/economic simulator, change the 30-second policy cadence merely for
  efficiency, or introduce cross-site state.

## Mandatory verification

- Existing Phase 0 ordinary-day, incident, malformed-store and fixed-seed
  Safety Lock traces are unchanged.
- Trigger storms coalesce to the documented bounded number of passes; each
  retained urgent boundary is observed exactly once.
- Re-entrant state changes during command execution cannot start a second
  command sequence or lose the newer request.
- Reload, unload, reconfigure and restart during an idle pass, active pass and
  queued pass leave no task leak and preserve the same controller obligations.
- The current → previous-release → current rehearsal remains storage
  compatible with an empty hardware trace under Safety Lock.
- Entity, configuration, presentation, persistence, dashboard and Fleet
  contracts, full tests, lint and independent review pass before every routed
  seam is eligible for operational observation.

## Rollback and acceptance

Every routing seam is separately revertible. Rollback disables only the new
request route and restores the previous trigger owner; it must never delete a
config entry, registry record, Recorder history or Store. Before any rollback,
engage Safety Lock and verify no HEO command sequence is active.

Phase 8 is complete only after the roadmap exit gate is demonstrated on clean
staging, pilot, remote topology and remaining sites, and a fresh-context review
accepts exact lifecycle/command/persistence parity.
