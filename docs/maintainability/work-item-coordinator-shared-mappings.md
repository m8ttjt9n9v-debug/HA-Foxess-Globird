# Work item — typed coordinator shared mappings

## Scope

Reuse immutable site, battery and EV mappings in the coordinator for SoC,
capacity, topology, solar capability, grid current and state-qualified EV power.

## Existing contract

- Battery and EV state mappings retain truthy-to-string coercion.
- EV and site phase counts remain strict positive integers at ledger time;
  malformed explicit values invalidate the ledger rather than using defaults.
- Missing solar capability remains upgrade-compatible; exact `false` supplies a
  valid zero-generation sample.
- EV power remains charging-state-qualified, freshness-bounded and unit-aware.

## Invariants and non-goals

- Preserve invalid-configuration outcomes, telemetry reasons and timestamps.
- Preserve every numeric conversion, freshness check and derived-current rule.
- Do not migrate power-direction, tariff, learning or time-window fields.
- Do not change serialized fields, validation or entity identity.

Focused telemetry/lifecycle tests, the full suite and previous-release rehearsal
are the acceptance gates. Rollback requires no data migration.

## Outcome

- Added battery-capacity mapping and strict EV phase parse evidence to the
  immutable snapshots.
- Migrated coordinator SoC, capacity, phase topology, solar capability, site
  current and state-qualified EV-power consumers.
- Added characterization separating parse validity from the established
  non-negative presentation projection.
- Reduced AST-visible raw runtime configuration access from 35 to 26.
- Validation: 562 tests, repository-wide Ruff, configuration and persistence
  contracts, and the `v0.12.26` previous-release rehearsal all pass.
