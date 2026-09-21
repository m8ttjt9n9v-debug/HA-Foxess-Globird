# Phase 7.9 — extract FoxESS export base policy

## Problem and evidence

`ActiveFoxessController._async_reconcile_export` duplicated the pure policy's
EV-before-export gate, control-window comparison, inverter/actuator power clamp
and latched-session fallback before invoking the complete energy planner. That
left domain formulas in the Home Assistant facade and two implementations that
could drift.

## Existing contract

- EV-before-export can suspend a new export without erasing a latched session.
- The session window uses the exact inclusive start and exclusive finish.
- Requested discharge is the lower of the non-negative commissioned inverter
  limit and actuator maximum.
- A latched session advances even if optional protected-energy planning fails;
  an idle session does not start without a valid eligible plan.
- Effective enablement and the exact finish boundary determine restoration.

## Change and invariants

One pure base evaluator now owns those formulas. The complete export evaluator
uses the same result, and the active facade uses it as its safe fallback before
gathering optional protected-house/EV evidence.

Service ordering, session transitions, energy planning, publication values,
repositories, adapters and commands remain unchanged. No entity,
configuration or persistence contract changes. This work does not alter the
inverter's configured export limit or any operational policy.

## Verification and rollback

Characterize enabled-idle and latched-finish base outcomes, retain complete
policy and active-controller regressions, and run the full lifecycle,
compatibility, previous-release, Ruff and reverse-patch gates. Revert this one
commit to restore the duplicated facade formulas; no data or hardware-state
migration is required.

## Acceptance evidence

- Pre-extraction export-policy characterization: 6 passed.
- Post-extraction focused policy/runtime selection: 54 passed.
- Full repository suite: 918 passed in 36.32 seconds.
- Frozen architecture and compatibility contracts: 24 passed.
- Previous-release rehearsal against `v0.12.26`: 1 passed.
- Repository-wide Ruff, `git diff --check` and reverse-patch applicability:
  passed.
- `_async_reconcile_export` fell from eight arithmetic/boolean operations and
  nine comparisons to two and five respectively; the remaining branches are
  optional-evidence acquisition, result application and lifecycle execution.
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
