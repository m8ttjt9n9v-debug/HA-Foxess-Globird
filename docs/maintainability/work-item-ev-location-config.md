# Work item — typed EV home-presence configuration

## Scope

Migrate only the active EV controller's Home/Auto/Away mode and already-typed
home/cable mappings to the immutable EV connection settings.

## Existing contract

- `away` always blocks home current control.
- `home` is an explicit operator override and does not require tracker state.
- `auto` requires the mapped home entity to report exactly `home` or `on`.
- A connected-at-home decision additionally requires cable `on` and a readable
  charging state other than `disconnected`.
- Missing, unknown or unavailable evidence fails closed.

## Invariants and non-goals

- Preserve all connection reason strings and fail-closed branches.
- Preserve smart-socket recovery evidence ages and state requirements.
- Preserve every command, current target, scheduling and persistence outcome.
- Do not migrate actuator mappings or other EV policy values in this item.
- Do not change serialized fields, defaults, validation or entity identity.

Parser and connection-state characterization plus the complete EV/lifecycle
suite are the acceptance gates. Rollback requires no data migration.

## Outcome

- Added location mode to the immutable EV connection snapshot and migrated the
  active controller's home and cable consumers without changing persisted keys.
- Added explicit characterization for Home, Auto and Away modes, disconnected
  cable evidence, and unknown/unavailable Auto-mode presence evidence.
- Reduced AST-visible raw runtime configuration access from 79 to 75.
- Validation: 531 tests, repository-wide Ruff, configuration and persistence
  contracts, and the `v0.12.26` previous-release rehearsal all pass.
