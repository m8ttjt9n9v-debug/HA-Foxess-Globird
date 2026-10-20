# Work item: retire an obsolete disconnected EV acknowledgement

## Problem and observable contract

A synthetic disconnected, non-charging vehicle with charge switch off can retain
a positive raw current and an older direct current target in `awaiting_feedback`.
The disconnected controller path returns before updating that reconciliation;
its valid stored episode restores on restart. Fleet admission separately treats
the retained raw current as physical charging. Four repository-independent red
regressions reproduced the stale episode, stale checkpoint, false activity
blockers and retained decision cadence before this correction.

The existing connected policy, retry/backoff, owners, persistent energy and
learning histories remain the control contract. Maintenance is a read-only
consumer and cannot erase an acknowledgement or exempt genuine pending work.

## Source mapping and correction boundary

| Source decision | Existing HEO boundary | Bounded correction |
| --- | --- | --- |
| Pilot actual-current template qualifies raw current with explicit charging state | `EvFeedbackSnapshot.actual_current_result` | Preserve current-control arithmetic; add a separate fresh physical-idle observation |
| Pilot home scope rejects away current/charge-switch writes | Existing connection and service gates | Retirement issues no command and grants no eligibility |
| Disconnected cleanup withdraws outside policy ownership | `cleanup_disconnected_ev` and controller routing | Retire only an unowned direct episode after qualified idle proof |
| Direct retry episode survives restart while still relevant | Version-one EV persistence codec | Save existing idle payload immediately; do not age out or erase episodes during decoding |
| Fleet requires fresh native feedback and idle owners | `maintenance_safety` | Share immutable proof; ignore retained raw positive current only when fully disconnected and idle |

Episode retirement is an explicit lifecycle bug correction, not a new charging
algorithm or additional parity claim. No site fact, time, current, topology or
entity identifier becomes a policy assumption.

## Invariants and non-goals

- Capture each source once, retaining its native report clock and restored flag.
- Require fresh valid cable, charging state, actual-current and charge-switch
  observations. Unknown, stale, future, restored, invalid or contradictory idle
  evidence cannot retire an episode. Existing freshness bounds remain unchanged.
- Retire only the direct episode and its active targets/decision cadence.
  Existing Full/Trip, outside/pre-free/daily and smart duties prevent it.
- An unconfirmed stop survives unplug. Only the shared qualified idle proof can
  complete the existing switch-off transition and clear its transient request
  flag before retiring the now-unowned episode. Persist both changes together.
- Keep the existing `idle` phase. Retirement never asserts `confirmed`.
- Save immediately; restore the pending in-memory episode if saving fails.
- Keep all commands, safety gates, retry intervals and connection policy intact.
- Preserve learning, energy delivery, dated Trip intent, ownership generations
  and absolute timeouts. Do not clear a historical Fleet maintenance audit.

## Compatibility and rollback

There are no new entities, public phase values, configuration fields, timers,
services, Store fields or schema versions. Additions to the internal immutable
feedback type retain native source evidence only. Reverting this correction
reads the same version-one idle payload and cannot resurrect the retired
positive target. Relevant episodes still pending under unqualified feedback keep
their original target, attempts and last-command clock across restart.

## Verification and acceptance

Synthetic regressions cover retained-current unplug, disabled/rehearsal control,
missing multiphase current, stale/unknown/invalid/contradictory feedback,
immediate unplug while stop feedback is pending, checkpoint/storage failure,
restart, reconnect redecision, direct
versus smart path, and genuine owner/stop/recovery preservation. Native report
tests cover equal-value refresh, future clocks and restored placeholders.
Existing native/helper Trip pause/resume, startup, timeout/generation ownership,
EV policy and maintenance suites remain required.

The final unversioned full suite passes 3,463 tests, including all retained
contracts. Ruff and diff validation pass. Upgrade/rollback rehearsals against
v0.12.48 and the retained v0.12.26 baseline pass two cases each. Independent
bounded review passes 409 focused tests with no remaining blocker after adding
the immediate-unplug stop sequence. The original four separately stored red
regressions now pass. No live system was contacted or changed for this work.

Versioned release gates, publication and separately authorised live acceptance
remain outstanding; repository tests do not establish physical charging performance.
