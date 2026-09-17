# Work item — typed control-surface constraints

## Scope

Add inverter charge/discharge limits used by commissioning number entities to
an immutable inverter slice. Read the already-typed free-charge schedule
confirmation from the same snapshot when enabling automatic charging.

## Invariants

- Preserve number maxima, the 0.1 kW UI floor and established defaults.
- Preserve the existing refusal message when schedule confirmation is absent.
- Do not change manual-test execution, controller gates or hardware commands.
- Do not change persisted keys, entity identities or config-entry version.

Configuration, entity-platform, setup and controller tests provide the gate.
Reverting the commit needs no data migration.
