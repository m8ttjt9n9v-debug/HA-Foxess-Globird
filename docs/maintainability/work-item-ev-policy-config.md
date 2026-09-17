# Work item — typed EV policy modes

## Scope

Migrate the active EV controller's existing charge-path, free-window-priority,
allowance-guard, solar-spill, pre-free and smart-socket-power selections to one
immutable policy snapshot. Reuse the already typed FoxESS control owner.

## Existing contract

- Direct EVSE is the default path; only exact `smart_socket` selects the socket
  path.
- Only exact `ev` grants free-window EV priority.
- Optional feature switches retain Python truthiness of their persisted values.
- Solar-spill and pre-free outside-window control still require Local Modbus
  ownership.

## Invariants and non-goals

- Preserve every condition, reason, target, command and persistence outcome.
- Do not enable a policy, change a default or normalize an invalid legacy enum.
- Do not migrate numeric policy values, solar commissioning or house metering.
- Do not change serialized fields, validation or entity identity.

Parser and controller characterization plus the complete suite are the
acceptance gates. Rollback requires no data migration.

## Outcome

- Added a typed policy snapshot for charge path, free-window priority,
  allowance protection, solar spill, pre-free charging and smart-socket power
  switching.
- Reused typed FoxESS ownership in the outside-window authorization condition.
- Added parser characterization for defaults, valid selections and malformed
  legacy enum/truthiness values.
- Reduced AST-visible raw runtime configuration access from 63 to 49.
- Validation: 542 tests, repository-wide Ruff, configuration and persistence
  contracts, and the `v0.12.26` previous-release rehearsal all pass.
