# Phase 7.9 — extract EV outside battery-reserve gate

## Problem and evidence

The immutable battery-reserve abort transition was already extracted, but the
active Home Assistant facade still owned the domain decision that activates
it. That inline condition combined the explicit paid Charge to Full exception,
snapshot availability and the inclusive configured reserve boundary.

## Existing contract

- Automatic outside-window charging aborts when battery SoC is equal to or
  below the configured EV reserve.
- Missing site or battery-SoC evidence does not infer that the reserve has
  been reached.
- Explicit Charge to Full remains the paid-charging exception even at or below
  reserve.
- The existing immutable abort transition remains solely responsible for
  session cleanup, stop intent, targets and diagnostics.

## Change and invariants

One immutable evidence object and pure predicate now own the reserve decision.
The facade supplies live snapshot and typed configuration values, then invokes
the unchanged abort transition when the predicate is true.

No threshold, command, priority, reason, entity, configuration key,
persistence payload or public behavior changes. This work does not implement
the separately specified morning-solar/pre-free-backfill handover.

## Verification and rollback

Pure cases cover equality, above-reserve, unavailable SoC and Charge to Full.
The retained end-to-end abort and paid-override traces, full suite, frozen
contracts, previous-release rehearsal, Ruff and reversible-patch check remain
gates. Reversion requires no migration or hardware action.

## Acceptance evidence

- Pre-extraction retained abort and paid-override characterization: 2 passed.
- Post-extraction pure and end-to-end reserve suite: 13 passed.
- Full repository suite: 946 passed in 36.64 seconds.
- Frozen architecture and compatibility contracts: 24 passed.
- Previous-release rehearsal against `v0.12.26`: 1 passed.
- Repository-wide Ruff, `git diff --check` and reverse-patch applicability:
  passed.
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
