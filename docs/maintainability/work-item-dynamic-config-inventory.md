# Work item — dynamic configuration access inventory

## Problem and evidence

The Phase 3 usage contract counted only calls whose key argument was a named
`CONF_*` constant. Runtime helpers such as `config.get(key, default)` therefore
disappeared from the metric, allowing a false boundary-only raw-access result.

## Existing contract

Named constant access, managed mutations, source/scope and boundary/runtime
classification are frozen in the v0.12.26 usage contract.

## Invariants and non-goals

- Do not change runtime configuration values, defaults, policy or commands.
- Preserve every previously inventoried access and managed mutation.
- Count variable keys only on the known coordinator configuration mappings, so
  unrelated dictionary helpers are not false positives.
- This seam exposes the debt; later bounded seams migrate it.

## Deliverables

- Usage-contract schema v3 with explicit dynamic-access count and key
  expression records.
- Tests preventing variable-key runtime helpers from disappearing again.
- A reviewed regenerated baseline before any dynamic helper is migrated.

## Compatibility and rollback

This changes only engineering evidence. No runtime, serialized configuration,
entity, service or storage behavior changes. Rollback restores the prior metric
but also restores its known blind spot.

## Acceptance evidence

Focused usage-contract tests, full suite, Ruff, all contracts and the v0.12.26
previous-release rehearsal must pass.

## Outcome

- Contract schema v3 preserves the 436 previously visible accesses and exposes
  11 additional raw runtime accesses: ten variable-key operations plus the
  literal legacy grid-direction fallback.
- Runtime inventory now reports 22 accesses: 11 managed mutation calls and 11
  direct mapping operations. The two direct writes are confined to the
  coordinator's central `update_config_value` implementation.
- Focused usage/configuration tests: 73 passed.
- Complete regression suite: 601 passed.
- Ruff, all generated/frozen contracts and the v0.12.26 previous-release
  rehearsal passed.
