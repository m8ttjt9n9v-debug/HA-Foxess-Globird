# Work item — typed EV telemetry mappings

## Scope

Migrate the active EV controller's vehicle SoC, charging-state, actual-current,
stored-energy and lifetime-energy entity mappings to one immutable telemetry
snapshot.

## Existing contract

- Truthy legacy mapping values are converted with `str`; falsey values are
  treated as missing.
- Unknown/unavailable charging state and missing/non-finite numeric state fail
  closed.
- Energy values retain unit conversion and reject negative/non-finite values.
- Actual current retains unit conversion and rejects negative values.

## Invariants and non-goals

- Preserve all reason strings, learning outcomes, freshness checks, targets and
  command outcomes.
- Preserve unit conversion and Home Assistant state timestamps exactly.
- Do not migrate battery, policy, schedule or authorization configuration.
- Do not change serialized fields, defaults, validation or entity identity.

Parser and telemetry characterization plus the complete suite are the
acceptance gates. Rollback requires no data migration.

## Outcome

- Added a typed telemetry snapshot for vehicle SoC, charging state, actual
  current, stored energy and lifetime energy.
- Migrated every active-controller consumer of those mappings and removed the
  generic config-key telemetry helpers.
- Added parser characterization for missing, string, legacy non-string and
  falsey mappings.
- Reduced AST-visible raw runtime configuration access from 66 to 63; this
  metric understates the seam because the removed generic helpers hid repeated
  dynamic key reads.
- Validation: 539 tests, repository-wide Ruff, configuration and persistence
  contracts, and the `v0.12.26` previous-release rehearsal all pass.
