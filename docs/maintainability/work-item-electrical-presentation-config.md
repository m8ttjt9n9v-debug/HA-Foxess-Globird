# Work item — typed electrical presentation configuration

## Scope

Add an immutable electrical-direction slice containing verification plus grid,
battery, solar and site-current sign settings. Migrate only the read-only
commissioning binary sensor and its attributes.

## Invariants

- Preserve exact stored values and established defaults.
- Do not migrate normalization, controller gates or hardware decisions yet.
- Do not change availability, state, attributes, config-entry data or version.

Existing setup, reversed-sign, migration and entity-contract tests provide the
behavioral gate. Reverting the commit needs no data migration.
