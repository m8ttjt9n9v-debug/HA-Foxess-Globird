# OM-704A — Pure FoxESS retained-ownership boundary

## Problem and evidence

The active controller currently decides whether a forced inverter mode belongs
to a retained automatic/manual session while also resetting and persisting
state. The decision must be separated from those effects before reconciliation
can become an explicit plan.

## Existing contract

Matching retained charge, export or manual evidence permits reconciliation.
Self Use also permits a retained obligation to resume or confirm restoration,
even when an unrelated storage family is degraded. Self Use with no retained
owner converts degraded evidence to a safe checkpoint. A non-Self-Use mode
without a matching owner is held as unknown when storage is degraded and as an
external owner when storage is trustworthy.

## Invariants

- No external forced mode is adopted as an HEO-owned session.
- Degraded unrelated storage cannot erase a valid retained obligation.
- Only observed Self Use may authorize the degraded-evidence reset obligation.
- The evaluator cannot persist, mutate sessions or call Home Assistant.
- Ownership statuses and public reasons remain exact.

## Non-goals

- Do not wire the evaluator into production yet.
- Do not change Store decoding or restoration behavior.
- Do not combine ownership with charge/export session transitions.
- Do not alter manual diagnostic ownership.

## Deliverables

- Immutable `FoxessOwnershipContext` over retained evidence.
- Immutable result with hold, reset, checkpoint and publication obligations.
- Characterization of every mode/evidence branch and precedence rule.

## Compatibility

This boundary is unwired and adds no entity, attribute, configuration field,
Store payload, service payload, timer, retry or runtime behavior.

## Test plan

- Matching charge, export and manual owners.
- Self Use with retained obligations and unrelated degraded storage.
- Safe checkpoint from each degraded storage status.
- Unknown versus verified external forced modes.
- Full lifecycle, compatibility-contract and previous-release gates.

## Rollback

Revert this commit. Because the evaluator is unwired and side-effect-free,
rollback has no runtime or storage consequence.

## Acceptance evidence

- 102 focused ownership and lifecycle tests passed.
- Full repository suite and Ruff passed.
- All nine frozen compatibility contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- `README.md` unchanged.

## Completion record

- [x] Existing behaviour characterised
- [x] Implementation complete
- [x] Compatibility checks passed
- [x] Documentation and roadmap updated
- [ ] Independent review complete
- [x] Rollback demonstrated
- [x] Operational soak complete where required — not required while unwired
