# Work item — centralized runtime configuration mutation

## Scope

Move the two charge-to-full compatibility updates behind the coordinator's
single runtime configuration mutation boundary.

## Existing contract

- The first owned switch action removes the legacy helper mapping and stores
  the owned boolean in the config entry and live runtime mirror.
- Automatic completion/timeout performs the same replacement with `false`.
- The immutable runtime snapshot is rebuilt synchronously before reconciliation.
- Unrelated operator-owned mutations continue to update one value at a time.

## Invariants and non-goals

- Preserve config-entry persistence, entity state and reconciliation order.
- Preserve the legacy helper until the owned switch or automatic clear acts.
- Do not change charge eligibility, targets, timeouts or service calls.
- Do not remove compatibility fields from serialized configuration or migration.

Focused configuration/EV/setup tests, the full suite and previous-release
rehearsal are the acceptance gates. Rollback requires no data migration.

## Outcome

- All 11 named-constant runtime accesses are classified managed mutations.
  A later v3 inventory audit found variable-key raw helpers that v2 did not
  count; those are tracked separately and do not alter this work item's
  persistence/live-snapshot replacement behavior.
- Owned-switch and automatic-clear paths now share one persistence/live-snapshot
  replacement boundary while retaining legacy-helper removal semantics.
- Acceptance passed: 167 focused tests, 579 full-suite tests, Ruff, all tracked
  configuration/persistence contracts and the v0.12.26 upgrade rehearsal.
