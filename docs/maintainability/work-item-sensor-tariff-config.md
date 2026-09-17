# Work item — typed sensor tariff configuration

## Scope

Add the three export rates and ZEROHERO hourly import threshold currently
displayed by observer entities to an immutable tariff slice. Migrate those
attributes plus free-charge schedule confirmation to the typed snapshot.

## Invariants

- Preserve entity states, attribute keys, numeric values and defaults.
- Do not migrate accounting, forecasting, scheduling or controller decisions.
- Do not change persisted keys, config-flow fields or config-entry version.

Configuration, setup, accounting and entity-contract tests provide the
behavioral gate. Reverting the commit needs no data migration.
