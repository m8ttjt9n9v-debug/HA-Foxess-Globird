# Work item — configuration mutation boundary

## Problem and evidence

Nine runtime actions write directly into `coordinator.config`. A future immutable
typed configuration cannot remain coherent while each switch, number, select
and controller mutates the backing dictionary independently.

## Observable contract

- The same config-entry update occurs before each runtime mirror update.
- The same key and value become immediately visible through `coordinator.config`.
- Existing state refreshes, reconciliation calls, persistence and service-call
  order remain unchanged.

## Invariants and non-goals

- Introduce one mutation boundary only; do not add typed parsing yet.
- Do not change defaults, validation, state, actions or hardware commands.
- Do not change config-entry serialization or version.

## Tests and rollback

The configuration usage contract must retain each key mutation while reporting
no direct runtime constant-key subscript stores. Existing switch, number,
select, charge-to-full and lifecycle tests prove behavior. Revert the commit to
roll back; no persisted migration is involved.
