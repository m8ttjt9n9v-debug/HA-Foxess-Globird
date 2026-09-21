# Phase 7.9 — wire the typed EV persistence model into the facade

## Problem and evidence

The composite EV Store already had a typed codec and repository, but the active
controller immediately serialized the decoded value and repeated the complete
parsing, validation and grouped-fallback implementation. Saving repeated the
entire payload schema in the facade before passing it back through that codec.
The duplicate implementation left persistence formulas, timestamp parsing and
schema ownership in the controller and created two places that could drift.

## Existing contract

- Store key, version, privacy flag and payload shape remain unchanged.
- Timed averages, driving history and driving snapshot restore independently.
- Malformed coupled control evidence resets reconciliation, pre-free,
  daily-backfill, Charge to Full, outside ownership and smart recovery as one
  group while retaining valid driving evidence.
- Save-time validation applies the same grouped safe fallback and rounds
  delivered daily-backfill energy to six decimals.
- Missing or invalid outer Store evidence retains the repository's established
  no-restore behavior.

## Change and invariants

The controller now projects a decoded `EvPersistenceState` directly onto its
runtime fields and constructs that same typed state for saving. The typed model
owns payload encoding, decoding, validation and grouped fallbacks. A
`validated_for_storage` operation preserves the prior save-time sanitization
without exposing schema dictionaries in the facade.

No command, policy, timing, entity, configuration key, Store key/version,
payload field or public reason changes. This is persistence-boundary wiring,
not a migration or a change to recovery policy.

## Verification and rollback

Codec cases cover complete round-trip, stable-feedback phase, malformed
control evidence and save-time grouped fallback. Existing controller restart,
daily-backfill, pre-free, smart-recovery and driving-learning fixtures remain
authoritative. Full suite, frozen contracts, previous-release rehearsal, Ruff
and reversible-patch checks remain gates. Reversion needs no data migration.

## Acceptance evidence

- Pre-wiring codec and controller restart characterization: 10 passed.
- Post-wiring codec, controller and persistence-boundary suite: 88 passed.
- Full repository suite: 948 passed in 37.04 seconds.
- Frozen architecture and compatibility contracts: 24 passed.
- Previous-release rehearsal against `v0.12.26`: 1 passed.
- Repository-wide Ruff, `git diff --check` and reverse-patch applicability:
  passed.
- The active facade no longer parses timestamps, validates payload fields or
  constructs schema dictionaries; those rules now have one typed owner.
- Public entities, configuration keys, Store key/version/payload and command
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
- [x] Operational soak not required for this schema-preserving extraction
