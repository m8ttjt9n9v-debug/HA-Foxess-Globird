# Work item: active-controller Store construction boundary

## Change

Move raw Home Assistant `Store` construction out of both active controllers and
behind the typed persistence repository factory. Controllers retain repository
load/save invocation as their lifecycle responsibility.

## Invariants

- Storage version, key, privacy flag and payload shape are unchanged.
- Charge, export and EV restoration fallbacks are unchanged.
- Save cadence and repository status reporting are unchanged.
- No migration, entity, configuration, command or public-state change is added.
- The persistence contract now rejects a raw `Store` import or constructor in
  either active controller.

## Verification

- Existing Home Assistant Store round-trip and restart tests remain
  authoritative.
- Persistence repository and boundary-contract tests cover the seam.
- The first full run exposed that factory-created Stores were absent from the
  frozen inventory; the scanner was extended to prove the same 13 logical
  Stores without changing the reviewed baseline.
- Focused persistence and lifecycle suite: `95 passed`; focused post-scanner
  contract suite: `55 passed`.
- Full suite after the scanner correction: `827 passed`.
- Repository Ruff check passed.
- All nine architecture contracts passed.
- Previous-release rehearsal against `v0.12.26` passed.

## Rollback

Revert this commit to reconstruct the same Store instances in the controller
constructors; persisted data remains compatible in either direction.
