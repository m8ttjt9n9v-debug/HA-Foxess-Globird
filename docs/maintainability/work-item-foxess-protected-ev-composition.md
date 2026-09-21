# Phase 7.9 — extract protected EV energy composition

## Problem and evidence

The FoxESS export facade added the connected-EV keepalive reservation to the
cycle-scoped daily-backfill reservation itself. This arithmetic directly
changes energy available for automatic export and therefore belongs with the
existing pure EV-before-export policy rather than the Home Assistant facade.

## Existing contract

- Missing mandatory connection evidence remains `None` and blocks a new
  export; daily-backfill energy must not turn it into a numeric reservation.
- A numeric keepalive reservation includes the current ready-cycle's remaining
  daily-backfill protection when an EV controller is present.
- Without an EV controller or daily allocation, the keepalive reservation is
  retained unchanged.
- Daily-backfill evidence is not requested when keepalive evidence has already
  failed closed.

## Change and invariants

One pure composition function now owns the addition and missing-evidence rule.
The facade retains evidence acquisition order and publishes the result exactly
where it did previously.

No export eligibility, energy reserve, command, entity, configuration,
persistence or public-reason behavior changes.

## Verification and rollback

Pure cases cover numeric composition, absent daily protection and fail-closed
keepalive evidence. Existing keepalive mapping, malformed export, daily-cycle
and lifecycle fixtures remain gates alongside the full suite, frozen
contracts, previous-release rehearsal, Ruff and reversible-patch checks.
Reversion needs no migration.

## Acceptance evidence

- Pre-extraction keepalive, malformed and daily-cycle characterization:
  11 passed.
- Post-extraction focused policy/controller suite: 12 passed.
- Full repository suite: 950 passed in 36.56 seconds.
- Frozen architecture and compatibility contracts: 24 passed.
- Previous-release rehearsal against `v0.12.26`: 1 passed.
- Repository-wide Ruff, `git diff --check` and reverse-patch applicability:
  passed.
- Public entities, configuration keys, persistence payloads, fail-closed
  reservation behavior and commands are unchanged. Independent review and the
  complete Phase 7 exit/rollout gates remain separate obligations; this
  extraction is not authorized for deployment.

## Completion record

- [x] Existing behaviour characterised
- [x] Implementation complete
- [x] Compatibility checks passed
- [x] Documentation updated
- [ ] Independent review complete
- [x] Rollback demonstrated
- [x] Operational soak not required for this side-effect-free extraction
