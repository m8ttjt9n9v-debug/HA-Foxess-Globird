# Work item — typed control-status presentation configuration

## Scope

Add FoxESS control ownership to the immutable automation settings and migrate
only read-only status sensor presentation for automation requests, safety lock,
electrical verification and control ownership.

## Invariants

- Preserve exact stored values and established defaults.
- Do not migrate controller gates, scheduling or hardware decisions.
- Do not change entity state vocabulary, attributes, availability, config-entry
  data or version.

Existing status-presentation, setup, controller and entity-contract tests
provide the behavioral gate. Reverting the commit needs no data migration.
