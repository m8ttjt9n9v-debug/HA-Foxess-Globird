# Phase 7.9 — extract EV general-limit reconciliation

## Problem and evidence

The connected, outside-window general charge-limit path still calculated the
Charge to Full override, learned target, anti-pause guard, confirmation
tolerance, duplicate-write fingerprint and command intent inside the Home
Assistant facade.

## Existing contract

- Charge to Full selects the actuator maximum; otherwise the learned general
  limit is authoritative.
- The existing anti-pause headroom guard remains active only for a positive
  protected baseline.
- Feedback within one actuator step confirms the target and clears the pending
  fingerprint.
- An identical target/feedback pair suppresses a duplicate write while waiting
  for feedback.
- A new pair proposes exactly one `set_charge_limit` command. Safety Lock may
  display that command but must not latch its fingerprint or execute it.

## Change and invariants

One immutable evaluator now returns the target, reason, command plan and an
explicit `clear`, `retain` or `set_on_execute` fingerprint transition. The
facade publishes the result, applies the transition at the same lifecycle
point and remains the only adapter executor.

No current target, public reason, retry cadence, entity, configuration key,
persistence payload or service call changes. The extraction does not alter the
separately confirmed fixed-attempt recovery bug.

## Verification and rollback

Pure tests cover new-write, awaiting-feedback and confirmed Charge to Full
outcomes. Existing active-controller general-limit and Safety Lock traces,
full lifecycle, frozen contracts, previous-release rehearsal, Ruff and reverse
patch checks remain gates. Reversion requires no migration or hardware action.

## Acceptance evidence

- Pre-extraction active general-limit characterization: 1 passed; the new pure
  cases freeze command, pending-feedback and confirmed outcomes before wiring.
- Post-extraction focused planner/facade selection: 80 passed, including the
  explicit Safety Lock no-write/no-fingerprint regression.
- Full repository suite: 922 passed in 36.45 seconds.
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
