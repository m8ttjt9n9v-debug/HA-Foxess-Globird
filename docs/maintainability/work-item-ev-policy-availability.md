# Phase 7.9 — extract EV outside-policy availability

## Problem and evidence

The active EV cycle still assembled whether any outside-window policy owned the
cycle. That expression combines the protected baseline, daily backfill,
Charge to Full, pending stop obligation, Local Modbus-only solar/pre-free
stages and the confirmed retained-current auto-start fix.

## Existing contract

- A positive protected baseline enables outside control.
- Daily backfill, Charge to Full and an unfinished daily stop obligation each
  independently keep outside reconciliation active.
- Solar-spill and pre-free stages count only when Local Modbus ownership
  authorizes them.
- A direct-path vehicle charging unexpectedly against a configured 0 A
  baseline enters outside reconciliation so HEO can issue the existing bounded
  stop. The smart-socket path does not use this direct-path fallback.
- When none applies, the general charge-limit-only route remains selected.

## Change and invariants

One immutable evaluator now returns both the unexpected-direct-charge fact and
the aggregate outside-enabled decision. The facade maps typed configuration
and live switch state, then passes the result to the existing pure route
selector and reconciliation finalizer.

No route order, target, stop obligation, command, entity, configuration field
or persistence payload changes.

## Verification and rollback

Pure cases cover every independent authority and the Modbus/smart-path
boundaries. Existing direct auto-start incident replay, route collision tests,
full lifecycle, frozen contracts, previous-release rehearsal, Ruff and reverse
patch checks remain gates. Reversion requires no migration or hardware action.

## Acceptance evidence

- Pre-extraction route and retained-current incident characterization: 7 passed.
- Post-extraction focused pure route/runtime/incident selection: 35 passed.
- Full repository suite: 939 passed in 37.03 seconds.
- Frozen architecture and compatibility contracts: 24 passed.
- Previous-release rehearsal against `v0.12.26`: 1 passed.
- Repository-wide Ruff, `git diff --check` and reverse-patch applicability:
  passed.
- `_async_reconcile_cycle` now contains nine arithmetic/boolean operations and
  21 comparisons, down from 13 and 23 at the preceding checkpoint; outside
  authority is one typed evaluator result.
- Public entities, configuration keys, persistence payloads and command
  behaviour are unchanged. Independent review and the complete Phase 7
  exit/rollout gates remain separate obligations; this extraction is not
  authorized for deployment.

## Completion record

- [x] Existing behaviour characterised
- [x] Implementation complete
- [x] Compatibility checks passed
- [x] Documentation updated
- [ ] Independent review complete
- [x] Rollback demonstrated
- [x] Operational soak not required for this side-effect-free extraction
