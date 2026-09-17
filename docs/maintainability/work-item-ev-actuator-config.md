# Work item — typed EV actuator mappings

## Scope

Migrate only the active EV controller's current-number, charge-limit-number,
charge-switch and optional smart-socket entity mappings to one immutable
actuator snapshot.

## Existing contract

- The direct adapter exists only when current, limit and charge-switch mappings
  are all truthy.
- The smart socket remains optional for the direct path.
- Truthy legacy mapping values are converted with `str`; falsey values are
  treated as missing.
- Missing entities, unreadable states or incomplete number metadata prevent an
  observation and therefore prevent commands.

## Invariants and non-goals

- Preserve exact service targets, command order, state parsing and metadata
  requirements.
- Preserve the existing EV authorization gate and smart-socket path rules.
- Do not migrate EV telemetry, policy values, write authorization or services.
- Do not change serialized fields, defaults, validation or entity identity.

Parser, adapter and observation characterization plus the complete suite are
the acceptance gates. Rollback requires no data migration.

## Outcome

- Added a typed actuator snapshot for the current number, charge-limit number,
  charge switch and optional smart socket.
- Migrated adapter construction, direct observations and smart-socket recovery
  evidence without changing service targets or serialized configuration.
- Added parser characterization for missing, complete, legacy non-string and
  incomplete mappings.
- Reduced AST-visible raw runtime configuration access from 75 to 66.
- Validation: 535 tests, repository-wide Ruff, configuration and persistence
  contracts, and the `v0.12.26` previous-release rehearsal all pass.
