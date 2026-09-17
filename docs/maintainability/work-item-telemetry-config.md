# Work item — typed telemetry configuration

## Scope

Migrate telemetry freshness, legacy battery sign fallback and split battery
charge/discharge mappings to immutable runtime settings.

## Existing contract

- Missing, invalid, non-finite or non-positive freshness uses the established
  default.
- An explicit battery direction wins; a missing or falsey direction retains
  the legacy `battery_charge_positive` fallback.
- Split battery sources are enabled only by non-empty string entity IDs.
- A configured split pair keeps charge-minus-discharge behavior and the signed
  battery source remains its established stale-pair fallback.

## Invariants and non-goals

- Preserve source timestamps, units, freshness reasons and sign conventions.
- Preserve setup/reload recovery and no-command observer behavior.
- Do not alter telemetry normalization, source subscription or configuration
  migration.
- Do not change serialized fields, entity identities or hardware control.

Focused telemetry/lifecycle tests, the full suite and previous-release rehearsal
are the acceptance gates. Rollback requires no data migration.

## Outcome

- Runtime raw configuration access reduced from 13 to nine; coordinator raw
  access reduced from nine to five.
- Existing freshness validation, explicit/legacy sign precedence, split-source
  admission and stale-pair fallback behavior are characterized and preserved.
- Acceptance passed: 160 focused tests, 572 full-suite tests, Ruff, all tracked
  configuration/persistence contracts and the v0.12.26 upgrade rehearsal.
