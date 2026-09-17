# Work item — typed required runtime numbers

## Problem and evidence

Battery capacity/floor/reserve and EV voltage/current limits were repeatedly
read through a generic coordinator helper against the mutable configuration
mapping. Unlike optional values, these inputs deliberately make the ledger
invalid when absent, malformed or non-finite.

## Existing contract

- Valid finite values are used without additional clamping.
- Missing, malformed, `NaN` and infinite values fail the required-number gate.
- Measured battery capacity takes precedence over configured capacity.
- Existing ledger error handling and single-phase current derivation remain
  unchanged.

## Invariants and non-goals

- Preserve invalid-configuration outcomes and measured-capacity precedence.
- Preserve current, power and phase calculations.
- Do not change configuration validation, policy or hardware commands.
- Do not invent defaults for required runtime inputs.

## Deliverables

- Parse the six required numbers once into domain-grouped immutable settings.
- Retain the coordinator compatibility bridge without mutable mapping access.
- Characterize valid, zero, missing, malformed and non-finite values.

## Outcome

- The coordinator required-number bridge now consumes only the immutable
  battery and EV snapshots.
- Focused configuration, setup, lifecycle and ledger tests: 174 passed.
- Raw runtime configuration reads fell from three to two.
- Complete regression suite: 617 passed.
- Ruff, all generated/frozen contracts and the v0.12.26 previous-release
  rehearsal passed.
