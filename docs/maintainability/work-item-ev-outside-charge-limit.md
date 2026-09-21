# Phase 7.9 — extract EV outside charge-limit selection

## Problem and evidence

The active EV facade still selected among Charge to Full, the configured
outside-window soft limit and the learned general limit, then composed that
policy with the existing anti-pause charge-limit guard. This calculation was
embedded beside session ownership and command orchestration.

## Existing contract

- Charge to Full selects the actuator maximum.
- An active outside-window current policy selects the configured soft limit.
- With no active outside current target, a learned general limit takes
  precedence when one exists; otherwise the configured soft limit is used.
- A positive protected baseline retains the anti-pause guard above current
  vehicle SoC, rounded to the actuator step and bounded by actuator metadata.
- This extraction does not alter current-stage selection, solar-spill,
  pre-free backfill, free-window control or command reconciliation.

## Change and invariants

One immutable evaluator now returns the selected policy limit and the existing
guarded actuator target. The facade supplies primitive policy and observation
evidence and retains ownership of lifecycle state and side effects.

No branch order, target, command, entity, configuration field, persistence
payload or public behavior changes. In particular, this behavior-preserving
extraction does not implement the separately specified morning-solar to
pre-free-backfill handover: that future fix must give pre-free backfill
exclusive authority at one frozen current once its session begins.

## Verification and rollback

Pure cases cover every policy source, the missing-learned fallback and the
anti-pause guard. Existing runtime characterization, the full suite, frozen
contracts, previous-release rehearsal, Ruff and reverse-patch checks remain
gates. Reversion requires no migration or hardware action.

## Acceptance evidence

- Pre-extraction Charge to Full and learned-limit runtime characterization:
  2 passed.
- Post-extraction focused pure/runtime characterization: 48 passed.
- Full repository suite: 944 passed in 36.43 seconds.
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
