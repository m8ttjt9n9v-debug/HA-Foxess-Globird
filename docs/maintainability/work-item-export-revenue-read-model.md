# Work item — authoritative export-revenue components

## Problem

The Estimated Export Revenue entity multiplied export energy by tariff rates
inside `sensor.py`. This was the last tariff arithmetic in entity
presentation, duplicated the financial engine's total-revenue calculation and
could drift from accounting.

## Change and preserved behavior

`DailyFinancialSummary` now exposes standard, off-peak and boosted component
revenues from the same calculation that produces total export revenue. The
transient `EnergyLedger` carries those components and `CostReadModel` projects
the established attribute names, rates, energy breakdown and four-decimal
formatting. Entity identity, total revenue, tariff policy and persistence are
unchanged.

The frozen attribute-contract extractor now follows the canonical cost method;
its checked contract remains unchanged.

## Verification

- Tariff characterization proves component revenues sum through the existing
  single-counted financial calculation.
- Exact read-model characterization covers all eleven public attributes.
- Focused tariff, read-model, setup and entity-contract suite: 74 passed.
- Full repository suite: 638 passed.
- Ruff and the frozen entity, attribute, configuration and persistence
  contracts passed.
- The `v0.12.26` previous-release compatibility rehearsal passed.
- `README.md` remained unchanged.
