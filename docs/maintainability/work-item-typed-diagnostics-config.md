# Work item — typed diagnostics configuration

## Scope

Add free-charge schedule confirmation to the immutable automation settings and
make support diagnostics project their operator, EV-priority and electrical
configuration from the same runtime snapshot used by entities.

## Invariants

- Preserve diagnostic keys, value types and established defaults.
- Reflect an in-memory operator change consistently in status and diagnostics.
- Keep actuator mappings redacted and counted at the Home Assistant boundary.
- Do not change controller gates, scheduling, persistence or hardware commands.

Setup, diagnostics, controller and configuration-contract tests provide the
behavioral gate. Reverting the commit needs no data migration.
