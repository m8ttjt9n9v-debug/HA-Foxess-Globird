# Phase 7.9 — extract smart-socket observation composition

## Problem and evidence

The active EV facade still calculated smart-socket powered age, coherent cloud
evidence age, charging-state age, charge permission and writable-actuator
status. These values directly govern staged current and the one-shot recovery
policy, so leaving their formulas beside Home Assistant reads obscured the
observation/policy boundary.

## Existing contract

- Smart-socket feedback is usable only for available `on`/`off` state with a
  timestamp; powered age is non-negative and an off socket has zero age.
- Location, cable and cloud charge-switch evidence must all be available, not
  future-dated, at least the configured age, and semantically coherent.
- Missing charging timestamps produce zero age.
- Missing target, actual-current validity, vehicle SoC or writable actuator
  evidence fails closed using the existing false/NaN representation.
- The cycle-scoped feedback snapshot remains the sole Home Assistant read
  source during reconciliation.

## Change and invariants

Two immutable evidence types and pure evaluators now compose the existing
smart-socket and recovery observations. The facade only acquires feedback and
maps typed configuration before invoking them.

No recovery sequence, timing boundary, retry, command, entity, configuration,
persistence or public-reason behavior changes.

## Verification and rollback

Pure cases cover exact age boundaries, future timestamps, unavailable socket,
missing cloud evidence and missing numeric evidence. Existing staged-current,
settle, ordered recovery, Safety Lock, restart and one-read-per-cycle fixtures
remain authoritative. Full suite, frozen contracts, previous-release
rehearsal, Ruff and reversible-patch checks remain gates. Reversion requires
no migration.

## Acceptance evidence

- Pre-extraction smart-socket and recovery runtime characterization retained
  the ordered, Safety Lock, restart and feedback-age traces.
- Post-extraction focused pure and runtime suite: 24 passed.
- Full repository suite: 953 passed in 36.03 seconds.
- Frozen architecture and compatibility contracts: 24 passed.
- Previous-release rehearsal against `v0.12.26`: 1 passed.
- Repository-wide Ruff, `git diff --check` and reverse-patch applicability:
  passed.
- Public entities, configuration keys, persistence payloads, recovery timing,
  command ordering and reasons are unchanged. Independent review and the
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
