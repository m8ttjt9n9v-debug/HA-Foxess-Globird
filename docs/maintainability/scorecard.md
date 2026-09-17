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
