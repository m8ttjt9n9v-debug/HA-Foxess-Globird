# Maintainability scorecard

The scorecard prevents subjective completion claims. A nominal 10/10 requires
at least 95 points and every hard gate below. Scores require linked evidence;
intent or partial implementation earns no points.

| Area | Points | Evidence required |
|---|---:|---|
| Lifecycle and incident evidence | 20 | Deterministic setup/reload/restart/reconfigure harness; every confirmed incident retained as a replay |
| Entity and configuration contracts | 15 | Reviewed machine-readable coverage of every public entity, attribute and persisted field |
| Typed configuration | 10 | Runtime consumes immutable typed configuration; raw mappings remain only at migration/platform boundaries |
| Canonical presentation model | 10 | Entities, diagnostics and Fleet project one read model without business recalculation |
| Versioned persistence | 10 | Typed repositories, fixture-backed migrations, corruption handling and rollback evidence |
| Controller boundaries | 15 | Observation, policy, priority, lifecycle and command execution have explicit tested boundaries |
| Scheduling and concurrency | 10 | One serialized/coalescing cycle per entry; no overlapping command sequence |
| Release, rollback and diagnostics | 10 | Supported-version CI, redacted support evidence, staged rollout and demonstrated one-version rollback |
| **Total** | **100** | |

## Hard gates

- Safety Lock produces zero hardware service calls in every generated sequence.
- Restart and reload from the same persisted state produce equivalent plans,
  ownership and bounded recovery obligations.
- Every known operational incident has a permanent sanitized replay.
- User registry customisation survives setup, reload, upgrade and downgrade.
- Existing dashboards, automations, Fleet consumers and Recorder statistics are
  preserved or covered by an explicit approved compatibility migration.
- No unfinished HEO forced-mode ownership or restoration obligation can be
  erased by missing, stale or malformed persisted state.
- One-version rollback is demonstrated for every migration-bearing release.

## Baseline assessment

The initial qualitative baseline is 55/100. It recognises strong pure-policy
and focused regression coverage, explicit safety gates and successful operation
on three sites, while withholding credit for the incomplete lifecycle harness,
implicit public contracts, duplicated presentation/configuration truth,
repeated persistence mechanics and overlapping reconciliation loops.

Update this assessment only at a phase gate and link the supporting artifacts.

## Phase 7 technical-gate assessment — 2026-09-21

The current evidence earns **78/100**. This is material progress from the
55/100 baseline, but it is deliberately not rounded into a nominal 10/10. The
remaining points correspond to specific uncompleted evidence rather than code
volume or subjective polish.

| Area | Awarded | Evidence and withheld credit |
|---|---:|---|
| Lifecycle and incident evidence | 16/20 | The deterministic harness has 46 expanded lifecycle cases and the incident catalogue links every known class to evidence. Some rows remain focused-only or request fuller system timelines/generated transitions. |
| Entity and configuration contracts | 13/15 | All 107 entities, public attributes and 124 wizard fields are mechanically frozen and reviewed. Full registry-safe downgrade to the pre-foundation release remains impossible because that old release reclaimed preferred IDs. |
| Typed configuration | 10/10 | Phase 3 reports zero raw runtime mapping operations; retained accesses are explicit managed mutation boundaries. |
| Canonical presentation model | 10/10 | The Phase 4 exit audit proves entities, attributes, diagnostics and Fleet project one immutable read model. |
| Versioned persistence | 9/10 | All 13 Stores use typed repositories with unchanged schemas, corruption handling and restart fixtures. Current → `v0.12.26` → current retained-state round trip passes; live release-candidate rollback remains open. |
| Controller boundaries | 13/15 | The 293-case Phase 7 corpus and static contracts prove observation, planner, repository and adapter boundaries. Independent fresh-context review and operational soak are not complete. |
| Scheduling and concurrency | 0/10 | Phase 8 has not started; independent 30-second controller schedules remain intentionally unchanged. |
| Release, rollback and diagnostics | 7/10 | Frozen contracts, redaction boundaries, previous-release restoration and local round-trip rollback pass. Clean-instance release-candidate validation and staged pilot/remote rollout remain open. |
| **Total** | **78/100** | Below the 95-point threshold and with open hard gates. |

Hard-gate status at this checkpoint:

- **Partial — Safety Lock generated sequences:** named system fixtures prove
  zero writes across reload and persisted recovery, but broader generated
  transition sequences remain catalogue work.
- **Pass — restart/reload equivalence:** ordinary-day and incident lifecycle
  traces retain equivalent plans, ownership and obligations.
- **Partial — incident replay completeness:** all classes are catalogued, but
  several still have focused rather than full system timelines.
- **Open — registry-safe downgrade:** current releases preserve user-owned
  registry state, but `v0.12.26` itself predates that guarantee and can reclaim
  a preferred ID.
- **Pass — public consumers:** entity, attribute, dashboard, configuration,
  presentation, persistence and Fleet contracts are enforced.
- **Pass — malformed ownership evidence:** missing or malformed evidence fails
  closed and cannot silently erase a forced-mode obligation.
- **Partial — release rollback:** configuration and retained controller state
  round-trip locally across `v0.12.26`; clean-instance and live operational
  rollback of a release candidate remain outstanding.

Supporting evidence: [Phase 7 technical exit audit](phase-7-exit-audit.md),
[Phase 7 rollback rehearsal](work-item-phase7-rollback-rehearsal.md), and
[incident fixture catalogue](incident-fixture-catalogue.md).
