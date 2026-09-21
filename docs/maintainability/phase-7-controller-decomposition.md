# Phase 7 — controller decomposition

## Outcome

Separate observation, eligibility, policy planning, reconciliation, command
execution and persistence without changing a single controller decision,
service call, delay, retry, reason, public state or stored obligation.

This is a mechanical decomposition, not a controller redesign. The Working
Single Phase Pilot Site provenance documents and Phase 0 lifecycle traces are
the behavioral authority.

## Problem and evidence

At the Phase 6 gate, `active.py` is 703 lines and `ev_active.py` is 2,553 lines.
They mix Home Assistant state acquisition with session ownership, eligibility,
priority selection, feedback reconciliation, persistence and adapter calls.
`ev_active.py` alone directly reads Home Assistant state in multiple policy
stages. This concentration makes a small maintenance change difficult to
review against command ordering and restart obligations.

The existing pure planners, command adapters and typed repositories are useful
seams, but the active controllers still assemble and mutate too many stages in
one reconciliation method.

## Existing contract

The following remain frozen:

- `ActiveFoxessController` and `ActiveEvController` setup, stop and timer
  behavior;
- the independent 30-second controller schedules until Phase 8;
- every gate, reason string, stage priority and effective target;
- service domains, services, payloads, order, delay and retry cadence;
- charge, export, EV, daily-backfill, pre-free and smart-recovery payloads;
- Store keys, versions, privacy and checkpoint timing;
- all entities, attributes, configuration keys and Fleet fields; and
- unload, reload, restart, reconfigure and malformed-state behavior.

Policy provenance remains in:

- `zerohero-export-policy.md`;
- `free-window-battery-ownership.md`;
- `ev-charging-policy.md`;
- `ev-solar-spill-and-pre-free-policy.md`;
- `ev-daily-ready-backfill.md`; and
- `ev-driving-learning-port.md`.

## Invariants

- Safety Lock produces no hardware service call and does not consume a retry.
- A non-Local-Modbus inverter owner never receives an HEO Modbus command.
- Incomplete, stale, contradictory or unverified evidence fails closed exactly
  as it does at the Phase 6 baseline.
- No controller adopts an unowned forced mode.
- Every HEO-owned forced mode retains a bounded completion or restoration
  obligation across reload and restart.
- A completed free-charge hold cannot be reasserted in the same window unless
  the already-characterized restart eligibility rule applies.
- EV location, cable and charging-state evidence continue to gate actuation,
  while read-only learning remains independent of connection.
- EV stages retain their present priority, transition holds, physical limits,
  target/actual feedback rules and maximum attempts.
- Controller adapters remain the only hardware-service boundary.

## Non-goals

- No scheduling consolidation; that belongs to Phase 8.
- No new feature, policy, entity, configuration field or user-facing rename.
- No retry, timeout, delay, cadence or persistence optimization.
- No new algorithm, simplified policy, dead-code removal or line-count target.
- No change to native FoxESS or Tessie integration behavior.

## Extraction sequence

Each numbered seam is independently committed and must pass the full gate
before the next begins.

### 7.1 — freeze command-plan traces

Add deterministic snapshots for inverter and EV evaluation results before
moving code. Cover ordinary, gated, stale, mismatched-feedback, session-active,
recovery and exact-boundary cases. Record ordered adapter plans, persistence
transitions and public reasons, not just final target values.

### 7.2 — immutable inverter observation

Move FoxESS mode and force-power state acquisition, option/range metadata and
source availability into a read-only adapter result. The active controller
must no longer call `hass.states` directly. Manual diagnostics consume the same
observation boundary without sharing policy or ownership state.

Implemented as separately revertible OM-702A, OM-702B and OM-702C seams: the
boundary, automatic-controller wiring and legacy-compatible diagnostic wiring.
The remaining direct active-controller state read is deliberately assigned to
the EV observation seam rather than mixed into inverter scope.

### 7.3 — inverter gate and policy evaluation

Build one immutable evaluation context from runtime configuration, telemetry,
observation and retained sessions. Extract gate evaluation first, then free
charge and export candidate evaluation. Preserve charge-before-export
ownership completion and overlap handling exactly.

### 7.4 — inverter reconciliation plan

Return an immutable result containing next charge/export session state,
reason, action plan and persistence obligations. Run the extracted evaluator
in shadow beside the retained controller and require exact equality across the
lifecycle corpus before switching ownership. `FoxessServiceAdapter` remains
the only executor.

### 7.5 — immutable EV observation

Capture the mapped location, cable, charge state, requested/actual current,
charge limit, energy, socket, actuator range and source timestamps once per
cycle. Preserve stable-value versus fast-telemetry freshness semantics. Remove
direct `hass.states` access from `ActiveEvController` only after the old and new
observation snapshots match.

### 7.6 — EV stage candidates

Wrap the existing free-window, solar-spill, pre-free, daily-ready, general
limit, smart-socket and recovery decisions as explicit candidate results. No
formula is rewritten. Each candidate names its eligibility, reason, target,
command intent and persistent transition.

### 7.7 — EV priority selection

Extract the current branch order into one pure selector over candidate results.
Golden tests must prove that two or more simultaneously eligible stages select
the same winner, including Charge to Full, free-window priority, service
overrun, battery-floor and export-protection boundaries.

### 7.8 — EV reconciliation state

Separate pending feedback, bounded attempts, transition holds, daily-backfill
accounting, smart-socket recovery and save decisions from Home Assistant calls.
Run old and new reconciliation in shadow over fixed incident sequences until
next-state, reason, action and persistence traces are byte-for-byte equivalent.

Implementation and deterministic compatibility evidence are recorded in the
[Phase 7.8 exit audit](phase-7-8-exit-audit.md). That audit closes only this
bounded extraction step; it does not satisfy the Phase 7 exit gate or authorize
deployment.

### 7.9 — facade and boundary audit

Leave active controllers responsible only for timer/lifecycle entry points,
observation acquisition, evaluator invocation, repository invocation, adapter
execution and publication. Add static contracts rejecting direct Home
Assistant state access, storage I/O and service calls from policy modules.

## Test plan

Every seam runs:

- focused characterization before implementation;
- Phase 0 ordinary-day and incident lifecycle replays;
- all charge/export session phases across reload and restart;
- Safety Lock, owner, sign, mapping and source-availability transitions;
- stale, unavailable, delayed, contradictory and out-of-order feedback;
- EV current-ramp, battery-floor, disconnected-learning and smart-recovery
  fixtures;
- exact ordered service-call, persistence and public-reason comparisons;
- frozen entity, configuration, presentation and persistence contracts;
- the previous-release `v0.12.26` rehearsal; and
- full pytest, Ruff and diff checks with `README.md` unchanged.

Generated sequences are permitted only after deterministic shadow parity is in
place. Every discovered counterexample becomes a named deterministic fixture.

## Compatibility and rollback

There is no storage migration and no public-contract change. Shadow evaluators
are side-effect-free and cannot execute commands. Each switched seam is one
revertable commit. Rollback restores the immediately preceding controller
facade while retaining unchanged Store payloads and pending obligations.

No Phase 7 checkpoint is deployed merely because unit tests pass. Operational
rollout waits for the complete phase exit gate and the programme's staging,
pilot and remote-topology soak order.

## Exit gate

Phase 7 is complete only when:

- old and extracted command plans match for every lifecycle fixture;
- service order, payloads, delays, retries, restoration and reason states are
  unchanged;
- active controllers contain no domain formula and directly access neither
  `hass.states` nor storage;
- policy modules cannot issue Home Assistant service calls;
- every existing incident fixture and frozen compatibility contract passes;
  and
- an exit audit records the exact shadow corpus, command/persistence trace
  counts, rollback rehearsal and remaining Phase 8 scheduling boundary.

## Completion record

- [x] Existing command behavior characterized
- [x] Inverter decomposition complete
- [x] EV decomposition complete
- [x] Shadow comparisons passed
- [x] Compatibility checks passed
- [x] Documentation and roadmap updated
- [ ] Independent review complete
- [x] Structural and local one-version rollback demonstrated
- [ ] Operational soak complete where required

The deterministic technical evidence and exact corpus are recorded in the
[Phase 7 technical exit audit](phase-7-exit-audit.md). The unchecked review and
soak gates mean this phase is not approved for release, deployment or Phase 8
scheduling work.
