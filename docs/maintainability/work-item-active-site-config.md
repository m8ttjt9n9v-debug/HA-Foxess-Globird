# Work item — typed active-controller site inputs

## Scope

Migrate the last non-mutating direct configuration reads in the active EV
controller: whether house load includes EV power, whether solar is configured,
and the battery-SoC entity mapping.

## Existing contract

- House-load inclusion retains Python truthiness and defaults to `false`.
- Solar is considered configured unless the persisted value is exactly the
  boolean `false`; this preserves pre-capability entries.
- A truthy battery-SoC mapping is converted with `str`; falsey values are
  treated as missing and solar-spill telemetry fails closed.

## Invariants and non-goals

- Preserve allowance math, transition holds and solar-spill freshness rules.
- Preserve all reason strings, targets, commands and timestamps.
- Leave charge-to-full managed mutations as explicit persistence boundaries.
- Do not change serialized fields, defaults, validation or entity identity.

Parser and controller characterization plus the complete suite are the
acceptance gates. Rollback requires no data migration.

## Outcome

- Added upgrade-compatible site capability and battery mapping snapshots, and
  expanded the typed house snapshot with EV-load inclusion.
- Migrated allowance projection, transition hold, solar capability and
  solar-spill coherence consumers.
- Added parser characterization for missing, valid and malformed legacy values,
  including exact-boolean solar semantics.
- The active EV controller now has no non-mutating direct configuration reads;
  repository-wide raw runtime access fell from 49 to 45.
- Validation: 546 tests, repository-wide Ruff, configuration and persistence
  contracts, and the `v0.12.26` previous-release rehearsal all pass.
