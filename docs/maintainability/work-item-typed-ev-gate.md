# Work item — typed EV authorization gate

## Scope

Make the EV authorization gate consume the immutable runtime snapshot while
retaining mapping input as a backward-compatible adapter for tests and callers.

## Existing contract

The ordered outcomes remain: explicit EV disable, automatic-control disable,
Safety Lock, unverified directions, uncommissioned control, incomplete mapping,
smart-socket mapping/limit faults, invalid site topology, missing multiphase
current, then adapter connection.

## Invariants and non-goals

- Preserve every gate reason and its precedence.
- Preserve missing versus explicitly-false EV configuration semantics.
- Preserve invalid-number behavior, including legacy non-finite floats.
- Do not change service execution, controller policy or serialized fields.

Gate characterization, full-suite parity and previous-release rehearsal are the
acceptance gates. Rollback requires no data migration.

## Outcome

- Added explicit-disable, smart-socket limit and site-topology inputs to the
  immutable snapshot.
- Migrated controller, sensor and diagnostics callers to the typed gate while
  preserving mapping input as a compatibility adapter.
- Added parity characterization for all smart-socket and topology fault paths,
  including malformed and non-finite legacy values.
- Removed all raw configuration reads from the EV authorization adapter;
  repository-wide raw runtime access fell from 45 to 35.
- Validation: 556 tests, repository-wide Ruff, configuration and persistence
  contracts, and the `v0.12.26` previous-release rehearsal all pass.
