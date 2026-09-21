# Phase 7 technical exit audit — controller decomposition

Date: 2026-09-21

## Verdict

The deterministic technical work for Phase 7 is complete on the local
maintenance branch. The inverter and EV controllers now retain Home Assistant
lifecycle, observation, repository, adapter-execution and publication duties,
while immutable planner boundaries own gate, policy, priority, reconciliation
and persistence decisions.

The original immutable implementation candidate for independent review was
commit `4a73017` (full object ID
`4a73017f90bd11813570ffda6b8c465851697f89`). Its review found four
malformed-evidence/diagnostic defects and a review-scope error. Correction
candidate `67a5ab7` (full object ID
`67a5ab71744e5ed670b88faf278f86d3d4d5a490`) fixes those defects and was
accepted by independent re-review. The original rejection and accepted
re-review are retained as separate records.

This audit does **not** authorize a release or deployment. The clean-instance,
pilot, remote-topology and remaining-site soak sequence remains outstanding.
Phase 8 scheduling work must not begin until those Phase 7 operational gates
are accepted.

## Exact deterministic corpus

The Phase 7 controller and lifecycle gate contains 294 collected cases:

| Corpus | Cases | Contract exercised |
| --- | ---: | --- |
| `test_ev_candidates.py` | 33 | EV candidates, collision priority and selector parity |
| `test_ev.py` | 87 | EV policy, feedback reconciliation and command plans |
| `test_ev_active.py` | 80 | EV facade lifecycle, routing, persistence and adapter execution |
| `test_zerohero_active.py` | 44 | inverter facade, ownership, charge/export and restoration |
| `test_lifecycle_harness.py` | 47 | setup, reload, reconfigure, outage, incident and ownership sequences |
| `test_phase6_recorded_day.py` | 1 | 24-hour accounting, learning, persistence and no-command replay |
| controller and persistence boundary contracts | 2 | platform and raw-storage isolation |

The 47 expanded lifecycle cases contain 68 ordered service-call trace
checkpoints and 41 persisted-store readback checkpoints. Twenty-two explicit
stored-state seeds exercise restart reconstruction, malformed evidence and
in-flight obligations. These are source-counted checkpoints, not an estimate
of branch coverage or a claim that every checkpoint emits a command.

The ordinary-day restart fixture compares uninterrupted execution with reloads
at every starting, active and stopping boundary. Both paths retain the same
eight ordered FoxESS service calls and finish with charge and export sessions
persisted idle.

The recorded-day fixture adds six public accounting/learning checkpoints and
freezes 573 repository writes across nine separately named stores, zero
hardware service calls and one learned daily sample. Its unchanged fixture was
already compared against the pre-extraction coordinator baseline in the Phase
6 audit.

## Shadow and extraction evidence

Each controller seam was characterized before ownership moved. The paired
work-item records identify the shadow-only and wiring commits for:

- FoxESS observation, absolute gates, charge policy, export policy, ownership
  and feedback recovery;
- EV observation, free-window and outside-window candidates, collision
  priority and cycle routing;
- EV direct feedback, transition holds, daily-backfill state, smart recovery
  and typed persistence; and
- the final formula/composition seams retained behind the controller facades.

Shadow evaluators were side-effect-free. Once a wired seam passed its focused,
lifecycle and compatibility gates, the duplicate retained expression was
removed rather than preserved as a second source of truth. The current corpus
therefore freezes the selected reason, command plan, next state and persistence
intent rather than maintaining two production algorithms indefinitely.

## Boundary audit

- `active.py` and `ev_active.py` contain no direct `hass.states`,
  `hass.services` or raw `Store` access.
- Planner modules import no Home Assistant package and cannot access Home
  Assistant states or services.
- Hardware calls remain behind the FoxESS and EV adapters.
- Active-controller loads and saves cross typed repository boundaries.
- Remaining controller branches are lifecycle, evidence-availability, route,
  result-application and publication branches; reviewed domain arithmetic and
  transition rules are owned by immutable planner functions.
- The two controllers retain their independent 30-second schedules. Combining
  or serializing them is exclusively Phase 8 work.

The static boundary scripts enforce the controller/planner platform-access and
repository-I/O portions of these claims on every run. The separate Phase 5
compatibility exception remains unchanged: some surrounding runtime components
still construct frozen v0.12.26 `Store` objects, while all loads, saves,
validation and serialization pass through repositories. That is not
controller-owned storage and is not silently expanded by this audit.

## Compatibility validation

At this audit checkpoint:

- the 294-case controller/lifecycle corpus passed;
- the complete repository suite passed with 956 tests;
- 24 frozen compatibility contracts passed;
- the current codecs produced representative non-idle charge, export and EV
  state that the isolated `v0.12.26` release restored with zero hardware
  service calls, then current code restored the state reserialized by that
  release with the same empty command trace;
- repository-wide Ruff passed;
- controller and persistence static boundary scripts passed;
- a clean `git archive` export of candidate `4a73017` separately passed the
  956-test suite, 24 contracts, both static boundaries and Ruff;
- the complete Phase 7 patch reverse-applied cleanly to an isolated copy of
  `HEAD`, where the resulting pre-Phase-7 tree passed all 685 of its tests; and
- `README.md` remained unchanged.

The test run emitted only the known local pytest-cache permission warning; it
did not affect collected or executed cases.

## Compatibility and rollback

Phase 7 changes no entity ID, unique ID, public state, attribute, configuration
key, Store key/version/privacy flag, serialized obligation, retry cadence,
timer cadence, service payload or command ordering. It adds no storage
migration.

Every extraction and ownership switch is a separately revertible local commit.
The binary diff from pre-Phase-7 commit `4838e51` through the current `HEAD`
reverse-applied cleanly in an isolated exported tree; that reconstructed tree's
full 685-test suite passed. The `v0.12.26` rehearsal separately proves the
retained configuration and serialized controller obligations remain readable
by the previous release. Operational downgrade is not yet approved: it still
requires the programme's clean-instance rollback exercise after a release
candidate exists.

Nothing in this audit has been pushed, tagged, released or deployed.

## Remaining gate and Phase 8 boundary

Deterministic implementation and compatibility evidence are complete. The
following remain deliberately open:

1. clean-instance install/upgrade and an operational rollback exercise for the
   eventual release candidate; the codec-level one-version downgrade already
   passes locally. A local-only `0.12.29rc2` clean observer now has restart,
   config-entry reload, diagnostics-redaction and recoverable `rc2 → rc1 →
   rc2` evidence with all 107 entities retained. It deliberately does not
   claim restoration of non-empty controller Stores: the clean observer has no
   actuator session, and that evidence remains in the deterministic lifecycle
   corpus until an applicable pilot cycle is observed;
2. pilot soak across complete relevant ZEROCHARGE, ZEROHERO, export and EV
   operating cycles;
3. one remote-topology soak, then remaining-site rollout; and
4. explicit acceptance before Phase 8 changes scheduling.

The staged observations, pass/fail criteria and immediate rollback triggers are
defined in the
[Phase 7 operational soak and rollback plan](phase-7-operational-soak-plan.md).

Phase 8 may introduce one serialized, coalescing cycle request per config
entry only after these gates. It must preserve the Phase 7 command,
persistence, reason, boundary and incident traces exactly.
