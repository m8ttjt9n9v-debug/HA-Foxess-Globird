# Work item — typed automatic-control inverter limits

## Scope

Migrate only the automatic FoxESS controller's existing configured charge and
discharge limits to the immutable inverter settings already used by manual
diagnostics and configuration entities.

## Contract and invariants

- Preserve established numeric parsing, defaults and the controller's
  non-negative clamp.
- Preserve the lower-of configured limit and live actuator maximum rule.
- Preserve all eligibility, scheduling, session, command and delay behavior.
- Do not migrate battery targets, export allowance, efficiency or time fields.
- Do not change serialized data, entities, services or persistence.

Parameterized parsing/clamp tests and the existing maximum-power controller
tests are the characterization. Rollback is a code revert only.

Validation completed with 519 tests, repository-wide Ruff, configuration and
persistence contracts, and the unmodified v0.12.26 previous-release rehearsal.
