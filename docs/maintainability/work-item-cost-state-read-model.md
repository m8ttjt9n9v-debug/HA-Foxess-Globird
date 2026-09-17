# Work item — cost entity-state read model

## Problem

Gross cost, import cost, supply charge, export revenue, ZEROHERO credit and
forecast-calibration entity states were still formatted directly in
`sensor.py`, separate from the canonical cost values already used by Fleet,
attributes and diagnostics.

## Change and preserved behavior

`CostReadModel.sensor_values()` now owns those eight existing entity states.
It applies the same two-decimal state rounding and one-decimal learned export
percentage. Tariff allocation, ledger calculation, forecast calibration,
entity identity, attributes and availability are unchanged.

## Verification

- Characterization covers all canonical cost-state keys and precision rules.
- Frozen sensor key extraction includes the cost projection.
- Focused read-model, entity-contract, setup and lifecycle suite: 98 passed.
- Full repository suite: 633 passed.
- Ruff and the frozen entity, attribute, configuration and persistence
  contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- `README.md` remained unchanged.
