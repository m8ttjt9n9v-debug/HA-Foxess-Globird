# Phase 7.9 — extract automatic-export remainder evaluation

## Problem and evidence

The automatic-export cap remainder was calculated twice: once in the active
FoxESS facade for safe partial publication and again in the pure export policy.
Besides duplicating arithmetic, the controller copy encoded a subtle rule:
malformed exported-energy evidence retains the prior remainder and prevents
later protected-energy fields from being republished in that cycle.

## Existing contract

- Valid exported energy is subtracted from the configured automatic cap and
  floored at zero.
- A missing counter publishes an unknown remainder but does not itself make the
  later export evidence malformed.
- A malformed counter retains the prior published remainder, withholds the
  plan, and stops later evidence publication for that cycle.
- The pure policy and active facade must use the same calculation.

## Change and invariants

One immutable evaluation now returns both the retained remainder and an
explicit validity flag. The facade preserves its existing publication order by
ending the optional-evidence block when that flag is false; the pure policy
uses the same result and fallback.

No tariff, cap, eligibility, session, command, entity, configuration or
persistence behavior changes.

## Verification and rollback

Pure cases cover valid, missing and malformed counters. Existing malformed
partial-publication, ready-export, session and lifecycle fixtures remain
authoritative. Full suite, frozen contracts, previous-release rehearsal, Ruff
and reversible-patch checks remain gates. Reversion needs no migration.

## Acceptance evidence

- Pre-extraction malformed/remaining/export-plan characterization: 12 passed.
- Post-extraction focused pure and active-controller suite: 13 passed.
- Full repository suite: 949 passed in 36.54 seconds.
- Frozen architecture and compatibility contracts: 24 passed.
- Previous-release rehearsal against `v0.12.26`: 1 passed.
- Repository-wide Ruff, `git diff --check` and reverse-patch applicability:
  passed.
- Public entities, configuration keys, persistence payloads, partial
  publication order and command behaviour are unchanged. Independent review
  and the complete Phase 7 exit/rollout gates remain separate obligations;
  this extraction is not authorized for deployment.

## Completion record

- [x] Existing behaviour characterised
- [x] Implementation complete
- [x] Compatibility checks passed
- [x] Documentation updated
- [ ] Independent review complete
- [x] Rollback demonstrated
- [x] Operational soak not required for this side-effect-free extraction
