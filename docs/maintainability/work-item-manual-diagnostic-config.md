# Work item — typed manual-diagnostic control configuration

## Scope

Extend the immutable inverter settings with the three existing FoxESS actuator
entity mappings, then migrate only manual diagnostic gates, feedback reads and
adapter construction to the typed snapshot.

## Invariants

- Preserve all serialized keys, values, defaults and config-entry versions.
- Preserve Local Modbus ownership and Safety Lock as absolute no-write gates.
- Preserve the exact command plan, retry bounds, storage payloads and public
  diagnostics.
- Treat a falsey mapping exactly as the existing incomplete-mapping gate did.
- Do not migrate tariff or time-window logic in this work item.

The manual diagnostic, lifecycle, configuration-contract and raw-access metric
tests provide the behavioural and structural gate. Reverting the change needs
no data migration.
