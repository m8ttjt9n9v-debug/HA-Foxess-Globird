# Work item — complete native-state read model

## Problem

Twenty-six native sensor states still read ledger, telemetry, ZEROHERO
accumulators, controllers and manual-test previews directly in `sensor.py`.
Although their producers were authoritative, the presentation layer was not a
pure projection and the sensor catalogue contract still depended on a second
local mapping.

## Change and preserved behavior

Immutable operational and manual-test submodels now own those existing state
projections. `EnergySensor.native_value` performs one canonical read-model
lookup. Ledger values remain unrounded, ZEROHERO accumulator values retain
three-decimal rounding, and missing-sample/controller fallbacks are unchanged.
Manual-test previews remain read-only and are evaluated once per model build,
matching the previous native-value evaluation behavior.

The AST entity contract now requires the pure read-model lookup and still
compares every projected key with the frozen sensor catalogue.

## Verification

- Exact read-model characterization covers all operational and manual-test
  states and precision rules.
- Focused read-model, entity-contract, setup and manual-test suite: 75 passed.
- Full repository suite: 637 passed.
- Ruff and the frozen entity, attribute, configuration and persistence
  contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- `README.md` remained unchanged.
