# Phase 7.8 exit audit — EV reconciliation state

Date: 2026-09-18

## Verdict

The bounded Phase 7.8 implementation is complete against the deterministic
repository corpus. Pending feedback, bounded attempts, transition holds,
daily-backfill accounting, smart-socket recovery, outside ownership and their
save decisions now cross explicit immutable transition boundaries.

This is not the Phase 7 exit. The controller still contains policy assembly and
result publication assigned to Phase 7.9, and no checkpoint is approved for
deployment or release by this audit.

## Extraction evidence

| Phase 7.8 concern | Pure boundary and retained evidence | Extraction commit |
| --- | --- | --- |
| Smart-socket staged-current hold and retry | `reconcile_smart_socket_stage`; live staged-current retry trace | `7f67b2d` |
| Daily-backfill wall-energy integration | missing, stale, out-of-order, inactive and trapezoidal fixtures | `2f9876f` |
| Daily ready-cycle rollover | same-cycle, active rollover and retained stop-obligation fixtures | `c717115` |
| Bounded stop feedback and attempts | fixed command/wait/retry/fault/confirmed trace; three-attempt cap | `d3292a8` |
| Daily-backfill session lifetime | start, frozen origin, live shrink, completion and terminal stop latch | `56e6291` |
| Battery-floor abort | pre-extraction lifecycle trace and immutable abort result | `0527e26` |
| Disconnected cleanup | pre-extraction lifecycle trace and immutable cleanup result | `466b826` |
| Charge-to-Full timer and cancellation | start, completion, timeout, manual cancellation and stop obligation | `98ae54a` |
| Direct-EVSE reconciliation persistence | pending feedback, bounded retry, confirmed ownership release and distinct save intent | `791020a` |
| Charge-path change cleanup | smart-path retention, Direct / EVSE reset and already-clear no-op | `68c4dfd` |
| Smart-recovery runtime persistence | active phase classification, changed/unchanged save intent and retained lifecycle traces | `52d5510` |
| Free-window entry cleanup | active pre-free cleanup and no-op retention cases | `9792e31` |
| Outside-window ownership | target, baseline, retained control, retained stop and carried-charge stop branches | `f75b027` |

The characterization-only commits `075e9a1`, `89f78f7` and `bd8b9ab` froze
the highest-risk battery-floor, stop-retry and disconnected-cleanup traces
before their corresponding controller mutations were replaced.

## Boundary audit

- Planner modules contain no `hass.states`, Home Assistant service call or
  Store access.
- Hardware commands still execute only through the EV adapter.
- Store writes remain in the active controller facade and repository; pure
  decisions expose whether a state transition requires a save.
- Remaining reconciliation assignments in `ev_active.py` apply immutable
  results, initialize controller state, or restore persisted state.
- The per-cycle candidate reset and `outside_stop_requested` reset are
  transient presentation/orchestration state, not retained policy decisions.
- Pre-free session advancement was already a pure transition; disabling that
  configured feature still clears its retained session at the facade boundary.
- Periodic checkpoints and command-success/failure saves remain lifecycle I/O
  responsibilities of the facade and are intentionally not moved into policy.

## Compatibility gate

- Focused suites were run for every extraction before its local commit.
- Full repository suite after the final extraction: `827 passed`.
- Repository-wide Ruff: passed.
- Nine architecture, configuration and persistence contracts: passed.
- Previous-release rehearsal against `v0.12.26`: passed.
- `README.md`: unchanged.
- Storage keys and version, entity IDs, configuration keys, command ordering,
  retry cadence, public reasons and adapter payloads: unchanged.

## Rollback

Each row above is an independently revertible local commit. Reverting in
reverse table order restores the immediately preceding controller expression
without a storage migration. Nothing in Phase 7.8 has been pushed, released or
deployed by this work.

## Next boundary

Phase 7.9 must reduce the active controllers to lifecycle/facade roles and add
static boundary enforcement. It must not reinterpret this audit as permission
to redesign EV policy, combine timers, alter persistence cadence or change any
public contract. Phase 7 remains incomplete until its full exit audit,
independent review, rollback demonstration and required operational soak pass.
